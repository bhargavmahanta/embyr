"""Process configuration for the Embyr backend.

Values are supplied from the process environment; no secret is committed and no
dotenv dependency is used. The Supabase Auth issuer is required to build the
token verifier; the JWKS URL and audience fall back to Supabase's documented
defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SUPABASE_AUDIENCE = "authenticated"
JWKS_SUFFIX = "/.well-known/jwks.json"


@dataclass(frozen=True)
class Settings:
    database_url: str
    supabase_auth_issuer: str
    supabase_jwt_audience: str = DEFAULT_SUPABASE_AUDIENCE
    supabase_jwks_url: str | None = None

    @property
    def resolved_jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        return self.supabase_auth_issuer.rstrip("/") + JWKS_SUFFIX

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        source = env if env is not None else os.environ
        return cls(
            database_url=source["EMBYR_DATABASE_URL"],
            supabase_auth_issuer=source["EMBYR_SUPABASE_AUTH_ISSUER"],
            supabase_jwt_audience=source.get(
                "EMBYR_SUPABASE_JWT_AUDIENCE", DEFAULT_SUPABASE_AUDIENCE
            ),
            supabase_jwks_url=source.get("EMBYR_SUPABASE_JWKS_URL"),
        )
