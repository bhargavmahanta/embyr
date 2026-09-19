"""Server-owned, immutable Storage object keys.

Object keys are durable, provider-independent values stored in Embyr's
PostgreSQL tables. They are generated only on the server, never derived from a
client filename, URL, or signed token, and never chosen by a client.
"""
from __future__ import annotations

from uuid import UUID, uuid4

USER_PREFIX = "users"
ARTIFACT_NAMESPACE = "artifacts"


class InvalidObjectKey(ValueError):
    """A Storage object key violates the frozen key contract."""


def generate_artifact_object_key(user_id: UUID) -> str:
    """Return ``users/<internal_app_user_id>/artifacts/<opaque_uuid>``."""
    return f"{USER_PREFIX}/{user_id}/{ARTIFACT_NAMESPACE}/{uuid4()}"


def validate_object_key(object_key: str, *, user_id: UUID | None = None) -> str:
    """Validate a server-generated object key, raising ``InvalidObjectKey``.

    The rules are deliberately strict: no URL, no signed token, no traversal,
    no leading or double slash, and, when an owner is supplied, the canonical
    per-user artifact prefix with an opaque UUID leaf.
    """
    if not isinstance(object_key, str) or not object_key or object_key != object_key.strip():
        raise InvalidObjectKey("object key must be a non-empty trimmed string")
    if "://" in object_key:
        raise InvalidObjectKey("object key must not be a URL")
    if object_key.startswith("/"):
        raise InvalidObjectKey("object key must not start with a slash")
    if "\\" in object_key:
        raise InvalidObjectKey("object key must not contain a backslash")
    parts = object_key.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise InvalidObjectKey("object key must not contain empty or dot segments")

    if user_id is not None:
        prefix = f"{USER_PREFIX}/{user_id}/{ARTIFACT_NAMESPACE}/"
        if not object_key.startswith(prefix):
            raise InvalidObjectKey(
                "artifact object key must use the owner's canonical prefix"
            )
        leaf = object_key[len(prefix):]
        try:
            UUID(leaf)
        except ValueError as error:
            raise InvalidObjectKey(
                "artifact object key leaf must be an opaque uuid"
            ) from error
    return object_key
