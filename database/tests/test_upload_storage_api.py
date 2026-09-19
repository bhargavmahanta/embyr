"""Database-backed upload lifecycle, ownership, and idempotency tests.

The FastAPI app runs against a real disposable PostgreSQL database as the
least-privileged ``app_backend`` role, so FORCE RLS, transaction-local
``app.user_id``, and the frozen lifecycle constraints are exercised for real.
Storage is a deterministic in-memory double; no network is used. Assertions on
durable state read through the migration (superuser) connection.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_external_identity
from app.auth.principal import ExternalIdentity
from app.config import Settings
from app.main import create_app
from app.storage.client import (
    DownloadCapability,
    ObjectInfo,
    StorageObjectMissing,
    StorageUnavailable,
    UploadCapability,
)

ISSUER = "https://embyr-dev.supabase.co/auth/v1"
BUCKET = "embyr-media"
SUBJECT_A = "p35-subject-a"
SUBJECT_B = "p35-subject-b"
BODY = {"purpose": "ARTIFACT", "content_type": "image/jpeg", "size_bytes": 10}


class FakeStorage:
    bucket = BUCKET

    def __init__(self) -> None:
        self.upload_calls: list[tuple] = []
        self.info_calls: list[str] = []
        self.download_calls: list[tuple] = []
        self.info_error: Exception | None = None
        self.upload_error: Exception | None = None
        self.info_result = ObjectInfo(
            object_key="",
            size=10,
            content_type="image/jpeg",
            etag="e",
            bucket_id=BUCKET,
            last_modified=None,
        )
        self._upload_seq = 0

    async def create_upload_capability(self, object_key, *, upsert=False):
        self.upload_calls.append((object_key, upsert))
        if self.upload_error:
            raise self.upload_error
        self._upload_seq += 1
        return UploadCapability(
            object_key=object_key,
            signed_url=f"https://storage.test/{object_key}?token=t{self._upload_seq}",
            token=f"t{self._upload_seq}",
            expires_in=7200,
        )

    async def object_info(self, object_key):
        self.info_calls.append(object_key)
        if self.info_error:
            raise self.info_error
        return self.info_result

    async def create_download_capability(self, object_key, ttl_seconds):
        self.download_calls.append((object_key, ttl_seconds))
        return DownloadCapability(object_key, "https://x", ttl_seconds)

    async def aclose(self) -> None:
        return None


def _set_backend_role(conn) -> None:
    conn.exec_driver_sql("set local role app_backend")


@pytest.fixture
def upload_env(migrated_engine, database_url):
    env = _make_env(migrated_engine, database_url)
    env.client = TestClient(env.app)
    try:
        with env.client:
            yield env
    finally:
        _dispose_env(env)


@pytest.fixture
def upload_env_async(migrated_engine, database_url):
    """App/engine harness without a sync TestClient for concurrent requests."""
    env = _make_env(migrated_engine, database_url)
    try:
        yield env
    finally:
        _dispose_env(env)


def _make_env(migrated_engine, database_url):
    with migrated_engine.begin() as conn:
        user_a = conn.execute(
            text(
                "insert into public.app_users (auth_provider, auth_subject) "
                "values ('SUPABASE', :s) returning id"
            ),
            {"s": SUBJECT_A},
        ).scalar_one()
        user_b = conn.execute(
            text(
                "insert into public.app_users (auth_provider, auth_subject) "
                "values ('SUPABASE', :s) returning id"
            ),
            {"s": SUBJECT_B},
        ).scalar_one()

    engine = create_async_engine(database_url, poolclass=NullPool)
    event.listen(engine.sync_engine, "begin", _set_backend_role)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    storage = FakeStorage()
    app = create_app(
        settings=Settings(database_url="", supabase_auth_issuer=ISSUER),
        session_factory=factory,
        storage=storage,
    )

    def _identity() -> ExternalIdentity:
        return ExternalIdentity("SUPABASE", SUBJECT_A)

    app.dependency_overrides[get_external_identity] = _identity
    return SimpleNamespace(
        app=app,
        storage=storage,
        engine=engine,
        migrated_engine=migrated_engine,
        user_a=user_a,
        user_b=user_b,
    )


def _dispose_env(env):
    env.app.dependency_overrides.clear()
    with env.migrated_engine.begin() as conn:
        conn.execute(
            text("delete from public.app_users where auth_subject in (:a, :b)"),
            {"a": SUBJECT_A, "b": SUBJECT_B},
        )
    asyncio.run(env.engine.dispose())


def _authorize(env, key="k1", body=None):
    return env.client.post(
        "/api/v1/uploads",
        json=body or BODY,
        headers={"Idempotency-Key": key},
    )


def _complete(env, upload_id, key="c1"):
    return env.client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers={"Idempotency-Key": key},
    )


def _as_user_b(env):
    env.app.dependency_overrides[get_external_identity] = lambda: ExternalIdentity(
        "SUPABASE", SUBJECT_B
    )


def _stored_body(env, key):
    with env.migrated_engine.begin() as conn:
        row = conn.execute(
            text(
                "select response_body from public.idempotency_records "
                "where user_id = :u and idempotency_key = :k"
            ),
            {"u": env.user_a, "k": key},
        ).scalar_one()
    if isinstance(row, str):
        return json.loads(row)
    return row


def _upload_row(env, upload_id):
    with env.migrated_engine.begin() as conn:
        return conn.execute(
            text(
                "select status, object_key, completed_at, validated_at, "
                "rejected_at from public.upload_sessions where id = :id"
            ),
            {"id": upload_id},
        ).one()


def test_authorize_creates_authorized_upload_and_ephemeral_capability(upload_env):
    response = _authorize(upload_env)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "AUTHORIZED"
    assert body["content_type"] == "image/jpeg"
    assert body["size_bytes"] == 10
    assert body["expires_in"] == 7200
    assert body["signed_upload_token"] == "t1"
    assert body["object_key"].startswith(
        f"users/{upload_env.user_a}/artifacts/"
    )
    assert upload_env.storage.upload_calls == [(body["object_key"], False)]

    row = _upload_row(upload_env, body["upload_id"])
    assert row.status == "AUTHORIZED"
    assert row.object_key == body["object_key"]


def test_authorize_idempotent_replay_returns_same_upload_fresh_capability(
    upload_env,
):
    first = _authorize(upload_env).json()
    second = _authorize(upload_env).json()

    assert second["upload_id"] == first["upload_id"]
    assert second["object_key"] == first["object_key"]
    assert second["signed_upload_token"] != first["signed_upload_token"]
    assert len(upload_env.storage.upload_calls) == 2

    with upload_env.migrated_engine.begin() as conn:
        count = conn.execute(
            text("select count(*) from public.upload_sessions")
        ).scalar_one()
    assert count == 1


def test_authorize_reused_key_with_different_payload_conflicts(upload_env):
    assert _authorize(upload_env).status_code == 201
    response = _authorize(upload_env, body={**BODY, "size_bytes": 11})
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert len(upload_env.storage.upload_calls) == 1


def test_stored_idempotency_response_never_contains_capability(upload_env):
    _authorize(upload_env)
    stored = _stored_body(upload_env, "k1")
    assert "signed_upload_url" not in stored
    assert "signed_upload_token" not in stored
    assert "token" not in json.dumps(stored)


def test_complete_verifies_db_key_and_reaches_uploaded_unvalidated(upload_env):
    body = _authorize(upload_env).json()
    upload_env.storage.info_result = ObjectInfo(
        object_key=body["object_key"],
        size=10,
        content_type="image/jpeg",
        etag="e",
        bucket_id=BUCKET,
        last_modified=None,
    )
    response = _complete(upload_env, body["upload_id"])
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "UPLOADED_UNVALIDATED"
    assert response.json()["completed_at"] is not None
    assert upload_env.storage.info_calls == [body["object_key"]]

    row = _upload_row(upload_env, body["upload_id"])
    assert row.status == "UPLOADED_UNVALIDATED"
    assert row.completed_at is not None
    assert row.validated_at is None
    assert row.rejected_at is None

    with upload_env.migrated_engine.begin() as conn:
        media = conn.execute(
            text("select count(*) from public.media_objects")
        ).scalar_one()
    assert media == 0


def test_complete_size_mismatch_rejects_upload(upload_env):
    body = _authorize(upload_env).json()
    upload_env.storage.info_result = ObjectInfo(
        object_key=body["object_key"],
        size=999,
        content_type="image/jpeg",
        etag="e",
        bucket_id=BUCKET,
        last_modified=None,
    )
    response = _complete(upload_env, body["upload_id"])
    assert response.status_code == 422
    assert response.json()["code"] == "UPLOAD_METADATA_MISMATCH"

    row = _upload_row(upload_env, body["upload_id"])
    assert row.status == "REJECTED"
    assert row.completed_at is not None
    assert row.rejected_at is not None


def test_complete_content_type_mismatch_rejects_upload(upload_env):
    body = _authorize(upload_env).json()
    upload_env.storage.info_result = ObjectInfo(
        object_key=body["object_key"],
        size=10,
        content_type="image/png",
        etag="e",
        bucket_id=BUCKET,
        last_modified=None,
    )
    response = _complete(upload_env, body["upload_id"])
    assert response.status_code == 422
    assert response.json()["code"] == "UPLOAD_METADATA_MISMATCH"
    assert _upload_row(upload_env, body["upload_id"]).status == "REJECTED"


def test_complete_metadata_mismatch_replay_preserves_error(upload_env):
    body = _authorize(upload_env).json()
    upload_env.storage.info_result = ObjectInfo(
        object_key=body["object_key"],
        size=999,
        content_type="image/jpeg",
        etag="e",
        bucket_id=BUCKET,
        last_modified=None,
    )
    first = _complete(upload_env, body["upload_id"], key="mm")
    assert first.status_code == 422
    assert first.json()["code"] == "UPLOAD_METADATA_MISMATCH"

    replay = _complete(upload_env, body["upload_id"], key="mm")
    assert replay.status_code == 422
    assert replay.json()["code"] == "UPLOAD_METADATA_MISMATCH"


def test_complete_absent_object_is_retryable(upload_env):
    body = _authorize(upload_env).json()
    upload_env.storage.info_error = StorageObjectMissing("absent")
    response = _complete(upload_env, body["upload_id"])
    assert response.status_code == 409
    assert response.json()["code"] == "UPLOAD_OBJECT_MISSING"

    row = _upload_row(upload_env, body["upload_id"])
    assert row.status == "AUTHORIZED"
    assert row.completed_at is None


def test_complete_storage_failure_is_retryable(upload_env):
    body = _authorize(upload_env).json()
    upload_env.storage.info_error = StorageUnavailable("down")
    response = _complete(upload_env, body["upload_id"])
    assert response.status_code == 502
    assert response.json()["code"] == "STORAGE_UNAVAILABLE"
    assert _upload_row(upload_env, body["upload_id"]).status == "AUTHORIZED"


def test_complete_idempotent_replay_does_not_reverify(upload_env):
    body = _authorize(upload_env).json()
    first = _complete(upload_env, body["upload_id"])
    assert first.status_code == 202
    calls_after_first = len(upload_env.storage.info_calls)
    second = _complete(upload_env, body["upload_id"])
    assert second.status_code == 202
    assert second.json() == first.json()
    assert len(upload_env.storage.info_calls) == calls_after_first


def test_cross_user_cannot_complete_or_read(upload_env):
    body = _authorize(upload_env).json()
    _as_user_b(upload_env)

    complete = _complete(upload_env, body["upload_id"], key="b-complete")
    assert complete.status_code == 404
    assert complete.json()["code"] == "UPLOAD_NOT_FOUND"

    read = upload_env.client.get(f"/api/v1/uploads/{body['upload_id']}")
    assert read.status_code == 404


def test_status_response_has_no_object_key_or_capability(upload_env):
    body = _authorize(upload_env).json()
    response = upload_env.client.get(f"/api/v1/uploads/{body['upload_id']}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "AUTHORIZED"
    assert "object_key" not in payload
    assert "signed_upload_url" not in payload
    assert "signed_upload_token" not in payload


@pytest.mark.asyncio
async def test_concurrent_authorization_is_idempotent(upload_env_async):
    """Two simultaneous same-key authorizations converge on one durable upload.

    The requests run on one event loop through separate ASGI/DB execution paths
    and are released together by an ``asyncio.Barrier``, so the second request's
    idempotency reservation genuinely races the first one's insert/commit.
    """
    env = upload_env_async
    transport = httpx.ASGITransport(app=env.app)
    barrier = asyncio.Barrier(2)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:

        async def authorize():
            await barrier.wait()
            return await client.post(
                "/api/v1/uploads",
                json=BODY,
                headers={"Idempotency-Key": "conc-1"},
            )

        first, second = await asyncio.gather(authorize(), authorize())

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    body_a, body_b = first.json(), second.json()
    assert body_a["upload_id"] == body_b["upload_id"]
    assert body_a["object_key"] == body_b["object_key"]

    tokens = {body_a["signed_upload_token"], body_b["signed_upload_token"]}
    assert tokens == {"t1", "t2"}, "each response must get a fresh capability"
    assert len(env.storage.upload_calls) == 2
    assert {key for key, _ in env.storage.upload_calls} == {body_a["object_key"]}

    with env.migrated_engine.begin() as conn:
        uploads = conn.execute(
            text(
                "select count(*) from public.upload_sessions where user_id = :u"
            ),
            {"u": env.user_a},
        ).scalar_one()
        idempotency = conn.execute(
            text(
                "select count(*) from public.idempotency_records "
                "where user_id = :u and idempotency_key = 'conc-1'"
            ),
            {"u": env.user_a},
        ).scalar_one()
    assert uploads == 1, "concurrent authorization created a duplicate upload"
    assert idempotency == 1, "concurrent authorization created a duplicate record"

    stored = _stored_body(env, "conc-1")
    assert "signed_upload_url" not in stored
    assert "signed_upload_token" not in stored


@pytest.mark.asyncio
async def test_concurrent_completion_transitions_once(upload_env_async):
    """Two simultaneous same-key completions settle on one lifecycle transition."""
    env = upload_env_async
    transport = httpx.ASGITransport(app=env.app)
    barrier = asyncio.Barrier(2)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        authorized = await client.post(
            "/api/v1/uploads", json=BODY, headers={"Idempotency-Key": "auth-c"}
        )
        assert authorized.status_code == 201, authorized.text
        upload_id = authorized.json()["upload_id"]
        env.storage.info_result = ObjectInfo(
            object_key=authorized.json()["object_key"],
            size=10,
            content_type="image/jpeg",
            etag="e",
            bucket_id=BUCKET,
            last_modified=None,
        )

        async def complete():
            await barrier.wait()
            return await client.post(
                f"/api/v1/uploads/{upload_id}/complete",
                headers={"Idempotency-Key": "complete-c"},
            )

        first, second = await asyncio.gather(complete(), complete())

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json() == second.json()
    assert first.json()["status"] == "UPLOADED_UNVALIDATED"

    row = _upload_row(env, upload_id)
    assert row.status == "UPLOADED_UNVALIDATED"
    assert row.completed_at is not None
    assert row.validated_at is None
    assert row.rejected_at is None

    with env.migrated_engine.begin() as conn:
        media = conn.execute(
            text("select count(*) from public.media_objects")
        ).scalar_one()
        idempotency = conn.execute(
            text(
                "select count(*) from public.idempotency_records "
                "where user_id = :u and idempotency_key = 'complete-c'"
            ),
            {"u": env.user_a},
        ).scalar_one()
    assert media == 0
    assert idempotency == 1
