"""Provider-independent authenticated principal model.

The external provider identity (for example Supabase's ``sub``) is deliberately
kept separate from Embyr's canonical ``app_users.id``. Only the internal UUID is
used for authorization and RLS identity propagation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

SUPABASE_PROVIDER = "SUPABASE"


@dataclass(frozen=True)
class ExternalIdentity:
    provider: str
    subject: str


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: UUID
    identity: ExternalIdentity


class AuthFailure(StrEnum):
    """Stable internal authentication failure categories.

    These are safe to map to public problem codes; they never carry token,
    signature, or datastore detail.
    """

    MISSING_CREDENTIALS = "MISSING_CREDENTIALS"
    MALFORMED_CREDENTIALS = "MALFORMED_CREDENTIALS"
    INVALID_TOKEN = "INVALID_TOKEN"
    EXPIRED_TOKEN = "EXPIRED_TOKEN"
    UNSUPPORTED_TOKEN = "UNSUPPORTED_TOKEN"
    UNMAPPED_IDENTITY = "UNMAPPED_IDENTITY"


class AuthError(Exception):
    """Authentication boundary failure carrying a stable category."""

    def __init__(self, failure: AuthFailure) -> None:
        super().__init__(failure.value)
        self.failure = failure
