"""Owned resource, command and factual event helpers for learning operations."""

from datetime import datetime, timezone
import logging
import time
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.api.errors import AppError
from app.api.idempotency import (
    require_idempotency_key,
    request_fingerprint,
    reserve_idempotent_command,
    IdempotencyConflict,
    store_idempotent_result,
)
from app.db.models.events import LearningEvent

LIFECYCLE_VERSION = "exploration-lifecycle/v1"
EVENT_VERSION = "learning-lifecycle-events/v1"
LOGGER = logging.getLogger(__name__)


def fail(
    code, status=409, detail="The command conflicts with the current resource state."
):
    LOGGER.info(
        "learning_operation_rejected",
        extra={"failure_category": code, "http_status": status},
    )
    raise AppError(
        code=code,
        status=status,
        title=code.replace("_", " ").capitalize(),
        detail=detail,
    )


async def owned(session, model, user_id, resource_id, *, lock=False):
    query = select(model).where(model.user_id == user_id, model.id == resource_id)
    if lock:
        # Exploration keys are immutable. NO KEY UPDATE still serializes
        # learner commands, while allowing worker event FK KEY SHARE locks.
        query = query.with_for_update(key_share=model.__tablename__ == "explorations")
    row = await session.scalar(query)
    if row is None:
        fail(
            f"{model.__name__.upper()}_NOT_FOUND",
            404,
            "The requested resource was not found.",
        )
    return row


async def reserve(session, request, user_id, body):
    name = request.url.path
    session.info["learning_command_started"] = time.monotonic()
    try:
        command = await reserve_idempotent_command(
            session,
            user_id=user_id,
            idempotency_key=require_idempotency_key(request),
            command_name=name,
            fingerprint=request_fingerprint(name, body),
        )
    except IdempotencyConflict:
        LOGGER.info(
            "learning_command_conflict",
            extra={"failure_category": "IDEMPOTENCY_KEY_REUSED"},
        )
        raise
    LOGGER.info(
        "learning_command_reserved",
        extra={"command_id": str(command.record_id), "replay": command.replay},
    )
    return command


async def finish(
    session,
    user_id,
    command,
    body,
    resource_id,
    *,
    result_type="LEARNING_COMMAND",
    status=200,
):
    encoded = jsonable_encoder(body)
    await session.flush()
    await store_idempotent_result(
        session,
        user_id=user_id,
        record_id=command.record_id,
        result_type=result_type,
        result_id=resource_id,
        response_status=status,
        response_body=encoded,
    )
    LOGGER.info(
        "learning_command_result_staged",
        extra={
            "command_id": str(command.record_id),
            "resource_id": str(resource_id),
            "result_type": result_type,
            "http_status": status,
            "latency_seconds": time.monotonic()
            - session.info.get("learning_command_started", time.monotonic()),
        },
    )
    # Durable effects precede the acknowledgment. Request-scoped yield cleanup
    # can run after ASGI has sent a response, so it is not the commit boundary
    # for commands that create facts.
    await session.commit()
    return encoded


async def emit(
    session,
    user_id,
    event_type,
    *,
    command=None,
    ordinal=0,
    exploration=None,
    assessment_session_id=None,
    entity_id=None,
    metadata=None,
):
    row = LearningEvent(
        id=uuid4(),
        user_id=user_id,
        event_type=event_type,
        command_id=command.record_id if command else None,
        event_ordinal=ordinal if command else None,
        entity_id=exploration.entity_id if exploration else entity_id,
        exploration_id=exploration.id if exploration else None,
        assessment_session_id=assessment_session_id,
        learning_intent=exploration.learning_intent if exploration else None,
        occurred_at=datetime.now(timezone.utc),
        schema_version=1,
        event_metadata={"contract_version": EVENT_VERSION, **(metadata or {})},
    )
    session.add(row)
    await session.flush()
    LOGGER.info(
        "learning_event_staged",
        extra={"event_type": event_type, "event_contract_version": EVENT_VERSION},
    )
    return row


def check_version(row, base_version):
    if base_version is not None and row.version != base_version:
        fail(
            "VERSION_CONFLICT",
            detail="Read the current resource version before submitting this change.",
        )
