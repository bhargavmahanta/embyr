"""Frozen upload lifecycle endpoints.

Authorization creates a durable ``AUTHORIZED`` upload session and then mints an
ephemeral signed upload capability. Completion verifies the uploaded object
through Storage metadata and advances ``AUTHORIZED`` to ``UPLOADED_UNVALIDATED``
only. Full content validation, trusted hashing, metadata stripping, and
``media_objects`` creation are deliberately out of scope for Issue #35.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_principal, get_session, get_settings, get_storage
from app.api.errors import AppError
from app.api.idempotency import (
    IdempotencyReservation,
    find_idempotent_result,
    reserve_idempotent_command,
    request_fingerprint,
    require_idempotency_key,
    store_idempotent_result,
)
from app.api.schemas import (
    UploadAuthorizationRequest,
    UploadAuthorizationResponse,
    UploadCompleteResponse,
    UploadStatusResponse,
)
from app.auth.principal import AuthenticatedPrincipal
from app.config import Settings
from app.db.session import set_current_user
from app.storage import (
    StorageObjectMissing,
    StorageService,
    StorageUnavailable,
    content_types_match,
    generate_artifact_object_key,
    validate_object_key,
)

router = APIRouter(prefix="/api/v1", tags=["uploads"])

COMMAND_AUTHORIZE_UPLOAD = "uploads.authorize"
COMMAND_COMPLETE_UPLOAD = "uploads.complete"

_STATUS_AUTHORIZED = "AUTHORIZED"
_STATUS_UPLOADED_UNVALIDATED = "UPLOADED_UNVALIDATED"
_STATUS_VALIDATED = "VALIDATED"
_STATUS_REJECTED = "REJECTED"
_ADVANCED_STATUSES = (_STATUS_UPLOADED_UNVALIDATED, _STATUS_VALIDATED)


@dataclass(frozen=True)
class UploadSessionRow:
    id: UUID
    user_id: UUID
    object_key: str
    status: str
    content_type: str
    size_bytes: int
    created_at: datetime
    completed_at: datetime | None
    validated_at: datetime | None
    rejected_at: datetime | None


_LOAD_UPLOAD_SQL = text(
    """
    select id, user_id, object_key, status,
           declared_content_type as content_type,
           declared_size_bytes as size_bytes,
           created_at, completed_at, validated_at, rejected_at
      from public.upload_sessions
     where user_id = :user_id and id = :id
    """
)

_LOCK_UPLOAD_SQL = text(
    """
    select id, user_id, object_key, status,
           declared_content_type as content_type,
           declared_size_bytes as size_bytes,
           created_at, completed_at, validated_at, rejected_at
      from public.upload_sessions
     where user_id = :user_id and id = :id
     for update
    """
)

_INSERT_UPLOAD_SQL = text(
    """
    insert into public.upload_sessions
      (id, user_id, purpose, declared_content_type, declared_size_bytes,
       object_key, status)
    values
      (:id, :user_id, 'ARTIFACT', :content_type, :size_bytes, :object_key,
       'AUTHORIZED')
    returning created_at
    """
)

_MARK_UPLOADED_SQL = text(
    """
    update public.upload_sessions
       set status = 'UPLOADED_UNVALIDATED',
           completed_at = greatest(created_at, now())
     where id = :id and user_id = :user_id
    returning completed_at
    """
)

_MARK_REJECTED_SQL = text(
    """
    update public.upload_sessions
       set status = 'REJECTED',
           completed_at = greatest(created_at, now()),
           rejected_at = greatest(created_at, now())
     where id = :id and user_id = :user_id
    returning completed_at
    """
)


def _row(row) -> UploadSessionRow:
    return UploadSessionRow(
        id=row.id,
        user_id=row.user_id,
        object_key=row.object_key,
        status=row.status,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
        completed_at=row.completed_at,
        validated_at=row.validated_at,
        rejected_at=row.rejected_at,
    )


async def _load_upload(
    session: AsyncSession, user_id: UUID, upload_id: UUID
) -> UploadSessionRow | None:
    result = (
        await session.execute(
            _LOAD_UPLOAD_SQL, {"user_id": user_id, "id": upload_id}
        )
    ).first()
    return _row(result) if result is not None else None


async def _lock_upload(
    session: AsyncSession, user_id: UUID, upload_id: UUID
) -> UploadSessionRow | None:
    result = (
        await session.execute(
            _LOCK_UPLOAD_SQL, {"user_id": user_id, "id": upload_id}
        )
    ).first()
    return _row(result) if result is not None else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _complete_body(
    upload_id: UUID,
    status: str,
    completed_at: datetime | None,
    *,
    code: str | None = None,
) -> dict:
    body = {
        "upload_id": str(upload_id),
        "status": status,
        "completed_at": _iso(completed_at),
    }
    if code is not None:
        body["code"] = code
    return body


def _complete_response(body: dict) -> UploadCompleteResponse:
    return UploadCompleteResponse(
        upload_id=body["upload_id"],
        status=body["status"],
        completed_at=body["completed_at"],
    )


_COMPLETE_ERRORS: dict[str, tuple[str, str]] = {
    "UPLOAD_METADATA_MISMATCH": (
        "Upload metadata mismatch",
        "The uploaded object does not match the declared size or content type.",
    ),
    "INVALID_STATE_TRANSITION": (
        "Invalid upload state",
        "The upload session is terminal and cannot be completed.",
    ),
}


def _complete_result(
    response_status: int, body: dict
) -> UploadCompleteResponse:
    """Return the stored success, or re-raise the stored command failure.

    A completion command that settled as an error must replay as the same
    error, not as a fabricated success.
    """
    if response_status == 202:
        return _complete_response(body)
    code = body.get("code", "INVALID_STATE_TRANSITION")
    title, detail = _COMPLETE_ERRORS.get(
        code, ("Invalid upload state", "The upload session cannot be completed.")
    )
    raise AppError(code=code, status=response_status, title=title, detail=detail)


def _storage_failure(error: Exception) -> AppError:
    if isinstance(error, StorageObjectMissing):
        return AppError(
            code="UPLOAD_OBJECT_MISSING",
            status=409,
            title="Upload object missing",
            detail="The upload object does not exist yet; retry after the "
            "upload completes.",
        )
    return AppError(
        code="STORAGE_UNAVAILABLE",
        status=502,
        title="Storage unavailable",
        detail="Object storage is temporarily unavailable; retry the request.",
    )


def _authorization_response(
    upload: UploadSessionRow, capability, settings: Settings
) -> UploadAuthorizationResponse:
    return UploadAuthorizationResponse(
        upload_id=upload.id,
        object_key=upload.object_key,
        status=upload.status,
        content_type=upload.content_type,
        size_bytes=upload.size_bytes,
        created_at=upload.created_at,
        signed_upload_url=capability.signed_url,
        signed_upload_token=capability.token,
        signed_upload_expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=capability.expires_in),
        expires_in=capability.expires_in,
    )


@router.post(
    "/uploads",
    status_code=201,
    response_model=UploadAuthorizationResponse,
)
async def authorize_upload(
    payload: UploadAuthorizationRequest,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    storage: StorageService = Depends(get_storage),
    idempotency_key: str = Depends(require_idempotency_key),
) -> UploadAuthorizationResponse:
    fingerprint = request_fingerprint(
        COMMAND_AUTHORIZE_UPLOAD, payload.model_dump()
    )
    reservation = await reserve_idempotent_command(
        session,
        user_id=principal.user_id,
        idempotency_key=idempotency_key,
        command_name=COMMAND_AUTHORIZE_UPLOAD,
        fingerprint=fingerprint,
    )

    if reservation.replay:
        upload = (
            await _load_upload(session, principal.user_id, reservation.result_id)
            if reservation.result_id is not None
            else None
        )
        if upload is None:
            raise AppError(
                code="INVALID_STATE_TRANSITION",
                status=409,
                title="Invalid idempotent state",
                detail="The replayed upload command has no durable result.",
            )
    else:
        upload_id = uuid4()
        object_key = generate_artifact_object_key(principal.user_id)
        validate_object_key(object_key, user_id=principal.user_id)
        created_at = (
            await session.execute(
                _INSERT_UPLOAD_SQL,
                {
                    "id": upload_id,
                    "user_id": principal.user_id,
                    "content_type": payload.content_type,
                    "size_bytes": payload.size_bytes,
                    "object_key": object_key,
                },
            )
        ).scalar_one()
        upload = UploadSessionRow(
            id=upload_id,
            user_id=principal.user_id,
            object_key=object_key,
            status=_STATUS_AUTHORIZED,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            created_at=created_at,
            completed_at=None,
            validated_at=None,
            rejected_at=None,
        )
        await store_idempotent_result(
            session,
            user_id=principal.user_id,
            record_id=reservation.record_id,
            result_type="UPLOAD_SESSION",
            result_id=upload_id,
            response_status=201,
            response_body={
                "upload_id": str(upload_id),
                "object_key": object_key,
                "status": _STATUS_AUTHORIZED,
                "content_type": payload.content_type,
                "size_bytes": payload.size_bytes,
                "created_at": _iso(created_at),
            },
        )

    # Release the PostgreSQL transaction before the Storage network call; the
    # durable session must exist independently of the ephemeral capability.
    if session.in_transaction():
        await session.commit()

    try:
        capability = await storage.create_upload_capability(
            upload.object_key, upsert=False
        )
    except (StorageObjectMissing, StorageUnavailable) as error:
        raise _storage_failure(error) from error

    return _authorization_response(upload, capability, settings)


@router.post(
    "/uploads/{upload_id}/complete",
    status_code=202,
    response_model=UploadCompleteResponse,
)
async def complete_upload(
    upload_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage),
    idempotency_key: str = Depends(require_idempotency_key),
) -> UploadCompleteResponse:
    fingerprint = request_fingerprint(
        COMMAND_COMPLETE_UPLOAD, {"upload_id": str(upload_id)}
    )

    early = await find_idempotent_result(
        session,
        user_id=principal.user_id,
        idempotency_key=idempotency_key,
        command_name=COMMAND_COMPLETE_UPLOAD,
        fingerprint=fingerprint,
    )
    if early is not None:
        if early.response_status is None or early.response_body is None:
            raise AppError(
                code="INVALID_STATE_TRANSITION",
                status=409,
                title="Invalid idempotent state",
                detail="The replayed completion command has no durable result.",
            )
        if session.in_transaction():
            await session.commit()
        return _complete_result(early.response_status, early.response_body)

    upload = await _load_upload(session, principal.user_id, upload_id)
    if upload is None:
        raise AppError(
            code="UPLOAD_NOT_FOUND",
            status=404,
            title="Upload not found",
        )
    if upload.status == _STATUS_REJECTED:
        raise AppError(
            code="INVALID_STATE_TRANSITION",
            status=409,
            title="Invalid upload state",
            detail="The upload session is terminal and cannot be completed.",
        )

    # Storage metadata is read outside the PostgreSQL transaction.
    if upload.status not in _ADVANCED_STATUSES:
        if session.in_transaction():
            await session.commit()
        try:
            info = await storage.object_info(upload.object_key)
        except (StorageObjectMissing, StorageUnavailable) as error:
            raise _storage_failure(error) from error
    else:
        info = None

    # Re-enter a transaction, lock the row, and re-check before transitioning.
    await set_current_user(session, principal.user_id)
    locked = await _lock_upload(session, principal.user_id, upload_id)
    if locked is None:
        raise AppError(
            code="UPLOAD_NOT_FOUND", status=404, title="Upload not found"
        )

    reservation = await reserve_idempotent_command(
        session,
        user_id=principal.user_id,
        idempotency_key=idempotency_key,
        command_name=COMMAND_COMPLETE_UPLOAD,
        fingerprint=fingerprint,
    )
    if reservation.replay:
        if reservation.response_status is None or reservation.response_body is None:
            raise AppError(
                code="INVALID_STATE_TRANSITION",
                status=409,
                title="Invalid idempotent state",
                detail="The replayed completion command has no durable result.",
            )
        await session.commit()
        return _complete_result(
            reservation.response_status, reservation.response_body
        )

    if locked.status in _ADVANCED_STATUSES:
        body = _complete_body(locked.id, locked.status, locked.completed_at)
        await store_idempotent_result(
            session,
            user_id=principal.user_id,
            record_id=reservation.record_id,
            result_type="UPLOAD_SESSION",
            result_id=locked.id,
            response_status=202,
            response_body=body,
        )
        await session.commit()
        return _complete_response(body)

    if locked.status == _STATUS_REJECTED:
        body = _complete_body(
            locked.id,
            locked.status,
            locked.completed_at,
            code="INVALID_STATE_TRANSITION",
        )
        await store_idempotent_result(
            session,
            user_id=principal.user_id,
            record_id=reservation.record_id,
            result_type="UPLOAD_SESSION",
            result_id=locked.id,
            response_status=409,
            response_body=body,
        )
        await session.commit()
        return _complete_result(409, body)

    if info is not None and info.size == locked.size_bytes and content_types_match(
        locked.content_type, info.content_type
    ):
        completed_at = (
            await session.execute(
                _MARK_UPLOADED_SQL,
                {"id": locked.id, "user_id": principal.user_id},
            )
        ).scalar_one()
        body = _complete_body(locked.id, _STATUS_UPLOADED_UNVALIDATED, completed_at)
        await store_idempotent_result(
            session,
            user_id=principal.user_id,
            record_id=reservation.record_id,
            result_type="UPLOAD_SESSION",
            result_id=locked.id,
            response_status=202,
            response_body=body,
        )
        await session.commit()
        return _complete_response(body)

    completed_at = (
        await session.execute(
            _MARK_REJECTED_SQL,
            {"id": locked.id, "user_id": principal.user_id},
        )
    ).scalar_one()
    body = _complete_body(
        locked.id,
        _STATUS_REJECTED,
        completed_at,
        code="UPLOAD_METADATA_MISMATCH",
    )
    await store_idempotent_result(
        session,
        user_id=principal.user_id,
        record_id=reservation.record_id,
        result_type="UPLOAD_SESSION",
        result_id=locked.id,
        response_status=422,
        response_body=body,
    )
    await session.commit()
    return _complete_result(422, body)


@router.get("/uploads/{upload_id}", response_model=UploadStatusResponse)
async def get_upload(
    upload_id: UUID,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> UploadStatusResponse:
    upload = await _load_upload(session, principal.user_id, upload_id)
    if upload is None:
        raise AppError(
            code="UPLOAD_NOT_FOUND", status=404, title="Upload not found"
        )
    return UploadStatusResponse(
        upload_id=upload.id,
        status=upload.status,
        content_type=upload.content_type,
        size_bytes=upload.size_bytes,
        created_at=upload.created_at,
        completed_at=upload.completed_at,
        validated_at=upload.validated_at,
        rejected_at=upload.rejected_at,
    )
