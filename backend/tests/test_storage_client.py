"""Unit tests for the async Supabase Storage adapter (no network)."""
from __future__ import annotations

import httpx
import pytest
from storage3.exceptions import StorageApiError

from app.storage.client import (
    SIGNED_UPLOAD_EXPIRES_IN,
    ObjectInfo,
    StorageObjectMissing,
    StorageUnavailable,
    SupabaseStorageService,
    content_types_match,
    normalize_content_type,
)

SECRET = "sb_secret_do_not_leak"
BUCKET = "embyr-media"
KEY = "users/11111111-1111-1111-1111-111111111111/artifacts/abc"


class Recorder:
    def __init__(self) -> None:
        self.url = None
        self.headers = None
        self.is_async = None
        self.bucket_ids: list[str] = []
        self.upload_calls: list[tuple] = []
        self.info_calls: list[str] = []
        self.download_calls: list[tuple] = []
        self.upload_error: Exception | None = None
        self.info_error: Exception | None = None
        self.info_payload: dict = {
            "size": 10,
            "content_type": "image/jpeg",
            "etag": "abc",
            "bucket_id": BUCKET,
            "last_modified": "2026-01-01T00:00:00Z",
        }


class _FakeBucket:
    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder

    async def create_signed_upload_url(self, path, options=None):
        self._recorder.upload_calls.append((path, options))
        if self._recorder.upload_error:
            raise self._recorder.upload_error
        return {
            "signed_url": f"https://storage.test/{path}?token=uploadtok",
            "signedUrl": f"https://storage.test/{path}?token=uploadtok",
            "token": "uploadtok",
            "path": path,
        }

    async def info(self, path):
        self._recorder.info_calls.append(path)
        if self._recorder.info_error:
            raise self._recorder.info_error
        return self._recorder.info_payload

    async def create_signed_url(self, path, expires_in, options=None):
        self._recorder.download_calls.append((path, expires_in))
        return {
            "signedURL": f"https://storage.test/{path}?token=downloadtok",
            "signedUrl": f"https://storage.test/{path}?token=downloadtok",
        }


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeClient:
    def __init__(self, recorder: Recorder) -> None:
        self._recorder = recorder
        self.session = _FakeSession()

    def from_(self, bucket_id: str):
        self._recorder.bucket_ids.append(bucket_id)
        return _FakeBucket(self._recorder)


def _install(monkeypatch) -> Recorder:
    recorder = Recorder()

    def fake_create_client(url, headers, *, is_async, timeout=None):
        recorder.url = url
        recorder.headers = headers
        recorder.is_async = is_async
        return _FakeClient(recorder)

    monkeypatch.setattr("app.storage.client.create_client", fake_create_client)
    return recorder


def _service(monkeypatch) -> tuple[SupabaseStorageService, Recorder]:
    recorder = _install(monkeypatch)
    service = SupabaseStorageService(
        storage_url="https://ref.supabase.co/storage/v1/",
        secret_key=SECRET,
        bucket=BUCKET,
    )
    return service, recorder


def test_client_uses_apikey_only_and_async(monkeypatch):
    _, recorder = _service(monkeypatch)
    assert recorder.headers == {"apikey": SECRET}
    assert "Authorization" not in recorder.headers
    assert recorder.is_async is True
    assert recorder.url.endswith("/storage/v1/")


def test_repr_never_emits_secret(monkeypatch):
    service, _ = _service(monkeypatch)
    assert SECRET not in repr(service)


@pytest.mark.asyncio
async def test_create_upload_capability_uses_exact_key_and_no_upsert(monkeypatch):
    service, recorder = _service(monkeypatch)
    capability = await service.create_upload_capability(KEY)

    assert recorder.bucket_ids == [BUCKET]
    assert recorder.upload_calls == [(KEY, None)]
    assert capability.object_key == KEY
    assert capability.token == "uploadtok"
    assert capability.expires_in == SIGNED_UPLOAD_EXPIRES_IN == 7200


@pytest.mark.asyncio
async def test_create_upload_capability_upsert_opt_in(monkeypatch):
    service, recorder = _service(monkeypatch)
    await service.create_upload_capability(KEY, upsert=True)
    assert recorder.upload_calls == [(KEY, {"upsert": "true"})]


@pytest.mark.asyncio
async def test_object_info_normalizes_metadata(monkeypatch):
    service, recorder = _service(monkeypatch)
    info = await service.object_info(KEY)
    assert recorder.info_calls == [KEY]
    assert info == ObjectInfo(
        object_key=KEY,
        size=10,
        content_type="image/jpeg",
        etag="abc",
        bucket_id=BUCKET,
        last_modified="2026-01-01T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_object_info_404_is_missing(monkeypatch):
    service, recorder = _service(monkeypatch)
    recorder.info_error = StorageApiError("Object not found", "not_found", 404)
    with pytest.raises(StorageObjectMissing):
        await service.object_info(KEY)


@pytest.mark.asyncio
async def test_object_info_server_error_is_unavailable(monkeypatch):
    service, recorder = _service(monkeypatch)
    recorder.info_error = StorageApiError("boom", "internal", 500)
    with pytest.raises(StorageUnavailable):
        await service.object_info(KEY)


@pytest.mark.asyncio
async def test_object_info_transport_error_is_unavailable(monkeypatch):
    service, recorder = _service(monkeypatch)
    recorder.info_error = httpx.ConnectError("no route")
    with pytest.raises(StorageUnavailable):
        await service.object_info(KEY)


@pytest.mark.asyncio
async def test_upload_signing_failure_is_unavailable(monkeypatch):
    service, recorder = _service(monkeypatch)
    recorder.upload_error = httpx.ReadTimeout("slow")
    with pytest.raises(StorageUnavailable):
        await service.create_upload_capability(KEY)


@pytest.mark.asyncio
async def test_create_download_capability_uses_ttl(monkeypatch):
    service, recorder = _service(monkeypatch)
    capability = await service.create_download_capability(KEY, 300)
    assert recorder.download_calls == [(KEY, 300)]
    assert capability.signed_url.endswith("token=downloadtok")
    assert capability.expires_in == 300


@pytest.mark.asyncio
async def test_aclose_closes_session(monkeypatch):
    service, _ = _service(monkeypatch)
    await service.aclose()


def test_content_type_matching_is_parameter_and_case_insensitive():
    assert normalize_content_type("IMAGE/JPEG; charset=binary") == "image/jpeg"
    assert content_types_match("image/jpeg", "image/jpeg; charset=binary")
    assert not content_types_match("image/jpeg", "image/png")
    assert not content_types_match("image/jpeg", None)
