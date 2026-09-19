"""Shared fixtures for the Embyr backend auth tests.

Signing material is generated locally so the cryptographic verification layer is
exercised for real without any live Supabase dependency. The JWKS client stub
returns the matching public key, which is the same interface
``jwt.PyJWKClient.get_signing_key_from_jwt`` exposes in production.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec


@dataclass(frozen=True)
class AuthConfig:
    issuer: str
    audience: str
    subject: str


@pytest.fixture(scope="session")
def auth_config() -> AuthConfig:
    return AuthConfig(
        issuer="https://embyr-dev.supabase.co/auth/v1",
        audience="authenticated",
        subject="11111111-1111-1111-1111-111111111111",
    )


@pytest.fixture(scope="session")
def signing_key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(scope="session")
def verification_key(signing_key):
    return signing_key.public_key()


@pytest.fixture
def jwk_client(verification_key):
    class _StaticJwkClient:
        def get_signing_key_from_jwt(self, token: str):
            return SimpleNamespace(key=verification_key)

    return _StaticJwkClient()


@pytest.fixture
def make_token(signing_key, auth_config):
    def _make(
        *,
        overrides: dict | None = None,
        drop: tuple[str, ...] = (),
        key=None,
        alg: str = "ES256",
    ) -> str:
        now = dt.datetime.now(dt.timezone.utc)
        payload: dict = {
            "sub": auth_config.subject,
            "iss": auth_config.issuer,
            "aud": auth_config.audience,
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
        }
        if overrides:
            payload.update(overrides)
        for claim in drop:
            payload.pop(claim, None)
        return jwt.encode(payload, key or signing_key, algorithm=alg)

    return _make
