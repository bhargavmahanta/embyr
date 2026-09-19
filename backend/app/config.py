"""Process configuration for the Embyr backend.

Values are supplied from the process environment; no secret is committed and no
dotenv dependency is used. The Supabase Auth issuer is required to build the
token verifier; the JWKS URL and audience fall back to Supabase's documented
defaults. The Supabase project origin used by the private Storage client is
derived from the same issuer, so no second Supabase URL variable exists.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SUPABASE_AUDIENCE = "authenticated"
JWKS_SUFFIX = "/.well-known/jwks.json"

# The Auth issuer must carry this path for the project origin to be derivable.
AUTH_ISSUER_SUFFIX = "/auth/v1"
STORAGE_API_SUFFIX = "/storage/v1/"
DEFAULT_STORAGE_DOWNLOAD_URL_TTL_SECONDS = 300

# Modern Supabase server credential format. Legacy ``service_role`` JWTs are
# deliberately not accepted by this configuration path.
MODERN_SECRET_KEY_PREFIX = "sb_secret_"


class ConfigurationError(RuntimeError):
    """A configuration value is missing or violates the frozen contract."""


def _validate_bucket_name(bucket: str) -> None:
    if not bucket or bucket != bucket.strip():
        raise ConfigurationError(
            "EMBYR_SUPABASE_STORAGE_BUCKET must be a non-empty name"
        )
    if "/" in bucket or "\\" in bucket or ".." in bucket:
        raise ConfigurationError(
            "EMBYR_SUPABASE_STORAGE_BUCKET must not contain path separators"
        )


def _parse_download_ttl(raw: str | None) -> int:
    if raw is None or raw == "":
        return DEFAULT_STORAGE_DOWNLOAD_URL_TTL_SECONDS
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigurationError(
            "EMBYR_STORAGE_DOWNLOAD_URL_TTL_SECONDS must be a positive integer"
        ) from error
    if value <= 0:
        raise ConfigurationError(
            "EMBYR_STORAGE_DOWNLOAD_URL_TTL_SECONDS must be a positive integer"
        )
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    supabase_auth_issuer: str
    supabase_jwt_audience: str = DEFAULT_SUPABASE_AUDIENCE
    supabase_jwks_url: str | None = None
    storage_bucket: str | None = None
    storage_secret_key: str | None = None
    storage_download_url_ttl_seconds: int = DEFAULT_STORAGE_DOWNLOAD_URL_TTL_SECONDS

    @property
    def resolved_jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        return self.supabase_auth_issuer.rstrip("/") + JWKS_SUFFIX

    @property
    def supabase_project_origin(self) -> str:
        """The Supabase project origin derived from the Auth issuer.

        The issuer must carry the expected ``/auth/v1`` suffix before the
        origin is derived; anything else fails closed rather than producing an
        unbounded Storage endpoint.
        """
        issuer = self.supabase_auth_issuer.rstrip("/")
        if not issuer.endswith(AUTH_ISSUER_SUFFIX):
            raise ConfigurationError(
                "EMBYR_SUPABASE_AUTH_ISSUER must end with /auth/v1 to derive "
                "the Supabase project origin"
            )
        origin = issuer[: -len(AUTH_ISSUER_SUFFIX)]
        if not origin.startswith("https://") or origin == "https://":
            raise ConfigurationError(
                "EMBYR_SUPABASE_AUTH_ISSUER must be an https URL"
            )
        return origin

    @property
    def storage_api_url(self) -> str:
        """The Storage API base URL; storage3 requires a trailing slash."""
        return self.supabase_project_origin + STORAGE_API_SUFFIX

    @property
    def storage_enabled(self) -> bool:
        return bool(self.storage_bucket and self.storage_secret_key)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        source = env if env is not None else os.environ

        bucket = source.get("EMBYR_SUPABASE_STORAGE_BUCKET")
        if not bucket:
            raise ConfigurationError(
                "EMBYR_SUPABASE_STORAGE_BUCKET is required"
            )
        _validate_bucket_name(bucket)
        secret_key = source.get("EMBYR_SUPABASE_STORAGE_SECRET_KEY")
        if not secret_key:
            raise ConfigurationError(
                "EMBYR_SUPABASE_STORAGE_SECRET_KEY is required"
            )
        if not secret_key.startswith(MODERN_SECRET_KEY_PREFIX):
            raise ConfigurationError(
                "EMBYR_SUPABASE_STORAGE_SECRET_KEY must be a modern Supabase "
                "secret key (sb_secret_...)"
            )

        settings = cls(
            database_url=source["EMBYR_DATABASE_URL"],
            supabase_auth_issuer=source["EMBYR_SUPABASE_AUTH_ISSUER"],
            supabase_jwt_audience=source.get(
                "EMBYR_SUPABASE_JWT_AUDIENCE", DEFAULT_SUPABASE_AUDIENCE
            ),
            supabase_jwks_url=source.get("EMBYR_SUPABASE_JWKS_URL"),
            storage_bucket=bucket,
            storage_secret_key=secret_key,
            storage_download_url_ttl_seconds=_parse_download_ttl(
                source.get("EMBYR_STORAGE_DOWNLOAD_URL_TTL_SECONDS")
            ),
        )
        # Fail fast when the issuer cannot produce a bounded project origin.
        settings.supabase_project_origin
        return settings
