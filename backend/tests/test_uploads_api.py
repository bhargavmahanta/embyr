"""FastAPI upload-boundary tests that do not touch the database.

These cover the public HTTP contract of the frozen DTOs, the required
Idempotency-Key, and the authentication requirement. Database-backed lifecycle
behavior is exercised in the database test suite.
"""
from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_principal, get_session, get_storage
from app.auth.principal import AuthenticatedPrincipal, ExternalIdentity
from app.config import Settings
from app.main import create_app
from app.storage.client import (
    DownloadCapability,
    ObjectInfo,
    UploadCapability,
)

USER_ID = UUID("22222222-2222-2222-2222-222222222222")
ISSUER = "https://embyr-dev.supabase.co/auth/v1"


class FakeStorage:
    bucket = "embyr-media"

    def __init__(self) -> None:
        self.upload_calls: list[tuple] = []
        self.info_calls: list[str] = []

    async def create_upload_capability(self, object_key, *, upsert=False):
        self.upload_calls.append((object_key, upsert))
        return UploadCapability(
            object_key=object_key,
            signed_url=f"https://storage.test/{object_key}?token=tok",
            token="tok",
            expires_in=7200,
        )

    async def object_info(self, object_key):
        self.info_calls.append(object_key)
        return ObjectInfo(object_key, 10, "image/jpeg", "etag", self.bucket, None)

    async def create_download_capability(self, object_key, ttl_seconds):
        return DownloadCapability(object_key, "https://x", ttl_seconds)

    async def aclose(self) -> None:
        return None


class _DummySession:
    pass


async def _dummy_session():
    yield _DummySession()


def _dummy_factory():  # pragma: no cover - never used; get_session is overridden
    raise AssertionError("session factory must not be used in these tests")


def _app(*, authenticate: bool) -> tuple[TestClient, FakeStorage]:
    storage = FakeStorage()
    app = create_app(
        settings=Settings(database_url="", supabase_auth_issuer=ISSUER),
        session_factory=_dummy_factory,
        storage=storage,
    )
    app.dependency_overrides[get_session] = _dummy_session
    app.dependency_overrides[get_storage] = lambda: storage
    if authenticate:
        app.dependency_overrides[get_principal] = lambda: AuthenticatedPrincipal(
            user_id=USER_ID,
            identity=ExternalIdentity("SUPABASE", "subject"),
        )
    return TestClient(app), storage


_VALID_BODY = {"purpose": "ARTIFACT", "content_type": "image/jpeg", "size_bytes": 10}


def test_upload_authorization_requires_authentication():
    client, _ = _app(authenticate=False)
    with client:
        response = client.post(
            "/api/v1/uploads",
            json=_VALID_BODY,
            headers={"Idempotency-Key": "k1"},
        )
    assert response.status_code == 401


def test_upload_authorization_requires_idempotency_key():
    client, storage = _app(authenticate=True)
    with client:
        response = client.post("/api/v1/uploads", json=_VALID_BODY)
    assert response.status_code == 400
    assert response.json()["code"] == "MISSING_IDEMPOTENCY_KEY"
    assert storage.upload_calls == []


def test_upload_authorization_rejects_client_object_key():
    client, storage = _app(authenticate=True)
    body = {**_VALID_BODY, "object_key": "users/attacker/artifacts/x"}
    with client:
        response = client.post(
            "/api/v1/uploads", json=body, headers={"Idempotency-Key": "k1"}
        )
    assert response.status_code == 422
    assert storage.upload_calls == []


@pytest.mark.parametrize(
    "body",
    [
        {"purpose": "PROFILE", "content_type": "image/jpeg", "size_bytes": 10},
        {"purpose": "ARTIFACT", "content_type": "  ", "size_bytes": 10},
        {"purpose": "ARTIFACT", "content_type": "image/jpeg", "size_bytes": 0},
        {"purpose": "ARTIFACT", "content_type": "image/jpeg", "size_bytes": -5},
    ],
)
def test_upload_authorization_rejects_invalid_metadata(body):
    client, storage = _app(authenticate=True)
    with client:
        response = client.post(
            "/api/v1/uploads", json=body, headers={"Idempotency-Key": "k1"}
        )
    assert response.status_code == 422
    assert storage.upload_calls == []


def test_upload_authorization_rejects_overlong_idempotency_key():
    client, storage = _app(authenticate=True)
    with client:
        response = client.post(
            "/api/v1/uploads",
            json=_VALID_BODY,
            headers={"Idempotency-Key": "x" * 129},
        )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_IDEMPOTENCY_KEY"
    assert storage.upload_calls == []


def test_complete_requires_authentication():
    client, _ = _app(authenticate=False)
    with client:
        response = client.post(
            "/api/v1/uploads/33333333-3333-3333-3333-333333333333/complete",
            headers={"Idempotency-Key": "k1"},
        )
    assert response.status_code == 401


def test_status_requires_authentication():
    client, _ = _app(authenticate=False)
    with client:
        response = client.get(
            "/api/v1/uploads/33333333-3333-3333-3333-333333333333"
        )
    assert response.status_code == 401
