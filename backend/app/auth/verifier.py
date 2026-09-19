"""Supabase JWT verification behind a provider-independent seam.

Verification is asymmetric (ES256/RS256) through the project's JWKS endpoint.
The signing key is resolved per token so key rotation is handled by PyJWT's JWKS
client rather than assumed at process start. Any failure to establish token
validity fails closed.
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence

import jwt

from app.auth.principal import (
    SUPABASE_PROVIDER,
    AuthError,
    AuthFailure,
    ExternalIdentity,
)

REQUIRED_CLAIMS = ("exp", "sub", "iss", "aud")

# Supabase access tokens carry a ``role`` claim. Only ``authenticated`` is a
# learner token; ``anon`` and ``service_role`` tokens must never establish an
# Embyr principal. The claim is never translated into a PostgreSQL role.
LEARNER_ROLE = "authenticated"

# JWKS cache/key-rotation policy. PyJWT 2.14+ caches the key set, gates forced
# refreshes behind an atomic cooldown lock, and retains the last known-good key
# set when a refresh fails. The floor is pinned in ``pyproject.toml`` because
# earlier releases force-refreshed on every lookup and wiped the cache on a
# failed fetch.
JWKS_CACHE_LIFESPAN_SECONDS = 300
JWKS_REFRESH_COOLDOWN_SECONDS = 30
JWKS_FETCH_TIMEOUT_SECONDS = 5


class _SigningKey(Protocol):
    key: Any


class SigningKeyClient(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> _SigningKey: ...


class TokenVerifier(Protocol):
    def verify(self, token: str) -> ExternalIdentity: ...


def parse_bearer(authorization: str | None) -> str:
    """Extract the bearer token from an Authorization header value."""
    if authorization is None or not authorization.strip():
        raise AuthError(AuthFailure.MISSING_CREDENTIALS)
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise AuthError(AuthFailure.MALFORMED_CREDENTIALS)
    return parts[1]


class SupabaseTokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        algorithms: Sequence[str] = ("ES256", "RS256"),
        jwk_client: SigningKeyClient | None = None,
        jwks_url: str | None = None,
    ) -> None:
        if jwk_client is None:
            if not jwks_url:
                raise ValueError(
                    "SupabaseTokenVerifier requires a jwk_client or jwks_url"
                )
            jwk_client = jwt.PyJWKClient(
                jwks_url,
                cache_jwk_set=True,
                lifespan=JWKS_CACHE_LIFESPAN_SECONDS,
                timeout=JWKS_FETCH_TIMEOUT_SECONDS,
                cooldown_duration=JWKS_REFRESH_COOLDOWN_SECONDS,
            )
        self._issuer = issuer
        self._audience = audience
        self._algorithms = list(algorithms)
        self._jwk_client = jwk_client

    def _signing_key(self, token: str) -> Any:
        try:
            return self._jwk_client.get_signing_key_from_jwt(token).key
        except (jwt.InvalidTokenError, jwt.PyJWKClientError, ValueError, OSError) as error:
            # The signing-key phase parses the unverified token header, so a
            # malformed token (DecodeError) and any missing/unreachable/malformed
            # JWKS must never authenticate.
            raise AuthError(AuthFailure.INVALID_TOKEN) from error

    def verify(self, token: str) -> ExternalIdentity:
        key = self._signing_key(token)
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=self._algorithms,
                issuer=self._issuer,
                audience=self._audience,
                options={"require": list(REQUIRED_CLAIMS)},
            )
        except jwt.ExpiredSignatureError as error:
            raise AuthError(AuthFailure.EXPIRED_TOKEN) from error
        except jwt.InvalidAlgorithmError as error:
            raise AuthError(AuthFailure.UNSUPPORTED_TOKEN) from error
        except jwt.InvalidTokenError as error:
            raise AuthError(AuthFailure.INVALID_TOKEN) from error

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise AuthError(AuthFailure.INVALID_TOKEN)
        if claims.get("role") != LEARNER_ROLE:
            raise AuthError(AuthFailure.INVALID_TOKEN)
        return ExternalIdentity(provider=SUPABASE_PROVIDER, subject=subject)
