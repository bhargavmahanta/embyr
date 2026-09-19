"""Async adapter over Supabase Storage for private Embyr objects.

The adapter only ever operates on exact, server-generated object keys supplied
by application code. It exposes three capabilities:

* mint a short-lived signed upload capability for one key (``upsert=False``);
* read trusted-at-the-provider object metadata (existence, size, content type);
* mint a short-lived signed download capability after ownership has already
  been proven from Embyr database state.

It never accepts a client-chosen key, never signs an arbitrary path, and never
persists or logs the signed capability or the server credential.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx
from storage3 import create_client
from storage3.exceptions import StorageApiError
from storage3.utils import StorageException

# Supabase signed upload URLs are valid for two hours; the protocol value is
# fixed on the server and is echoed to clients for clarity.
SIGNED_UPLOAD_EXPIRES_IN = 7200


class StorageError(RuntimeError):
    """Base class for normalized Storage failures."""


class StorageUnavailable(StorageError):
    """Storage is temporarily unreachable or returned a server failure."""


class StorageObjectMissing(StorageError):
    """The requested object does not exist at the expected key."""


@dataclass(frozen=True)
class UploadCapability:
    object_key: str
    signed_url: str
    token: str
    expires_in: int


@dataclass(frozen=True)
class DownloadCapability:
    object_key: str
    signed_url: str
    expires_in: int


@dataclass(frozen=True)
class ObjectInfo:
    object_key: str
    size: int | None
    content_type: str | None
    etag: str | None
    bucket_id: str | None
    last_modified: str | None


def normalize_content_type(value: str | None) -> str | None:
    """Lower-case a media type and drop any parameters, or ``None``."""
    if value is None:
        return None
    primary = value.split(";", 1)[0].strip().lower()
    return primary or None


def content_types_match(declared: str | None, reported: str | None) -> bool:
    """Whether a provider-reported type is coherent with the declared type."""
    left = normalize_content_type(declared)
    right = normalize_content_type(reported)
    return left is not None and right is not None and left == right


@runtime_checkable
class StorageService(Protocol):
    bucket: str

    async def create_upload_capability(
        self, object_key: str, *, upsert: bool = False
    ) -> UploadCapability: ...

    async def object_info(self, object_key: str) -> ObjectInfo: ...

    async def create_download_capability(
        self, object_key: str, ttl_seconds: int
    ) -> DownloadCapability: ...

    async def aclose(self) -> None: ...


def _is_missing(error: StorageApiError) -> bool:
    if str(error.status) == "404":
        return True
    return "not found" in str(error.message).lower()


class SupabaseStorageService:
    """``StorageService`` backed by the official async storage3 client."""

    def __init__(self, *, storage_url: str, secret_key: str, bucket: str) -> None:
        self.bucket = bucket
        # Modern Supabase secret keys are not JWTs, so they are sent on the
        # ``apikey`` header only; storage3 adds no Authorization header itself.
        self._client = create_client(
            storage_url, {"apikey": secret_key}, is_async=True
        )

    def __repr__(self) -> str:
        return f"SupabaseStorageService(bucket={self.bucket!r})"

    async def aclose(self) -> None:
        await self._client.session.aclose()

    def _bucket_api(self):
        return self._client.from_(self.bucket)

    async def create_upload_capability(
        self, object_key: str, *, upsert: bool = False
    ) -> UploadCapability:
        options = {"upsert": "true"} if upsert else None
        try:
            data = await self._bucket_api().create_signed_upload_url(
                object_key, options
            )
        except (StorageApiError, StorageException, httpx.HTTPError) as error:
            raise StorageUnavailable(
                "storage upload capability creation failed"
            ) from error
        signed_url = data.get("signed_url") or data.get("signedUrl")
        token = data.get("token")
        if not signed_url or not token:
            raise StorageUnavailable(
                "storage returned an incomplete signed upload capability"
            )
        return UploadCapability(
            object_key=object_key,
            signed_url=signed_url,
            token=token,
            expires_in=SIGNED_UPLOAD_EXPIRES_IN,
        )

    async def object_info(self, object_key: str) -> ObjectInfo:
        try:
            data: dict[str, Any] = await self._bucket_api().info(object_key)
        except StorageApiError as error:
            if _is_missing(error):
                raise StorageObjectMissing("object is absent") from error
            raise StorageUnavailable("storage object lookup failed") from error
        except (StorageException, httpx.HTTPError) as error:
            raise StorageUnavailable("storage object lookup failed") from error

        raw_size = data.get("size")
        return ObjectInfo(
            object_key=object_key,
            size=int(raw_size) if raw_size is not None else None,
            content_type=data.get("content_type"),
            etag=data.get("etag"),
            bucket_id=data.get("bucket_id"),
            last_modified=data.get("last_modified"),
        )

    async def create_download_capability(
        self, object_key: str, ttl_seconds: int
    ) -> DownloadCapability:
        try:
            data = await self._bucket_api().create_signed_url(
                object_key, ttl_seconds
            )
        except (StorageApiError, StorageException, httpx.HTTPError) as error:
            raise StorageUnavailable(
                "storage download capability creation failed"
            ) from error
        signed_url = data.get("signedURL") or data.get("signedUrl")
        if not signed_url:
            raise StorageUnavailable("storage returned no signed download URL")
        return DownloadCapability(
            object_key=object_key,
            signed_url=signed_url,
            expires_in=ttl_seconds,
        )
