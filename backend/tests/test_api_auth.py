"""FastAPI authentication boundary tests (issue #34).

These assert the public HTTP behaviour of the auth dependency and error model:
status codes, stable problem codes, and the ``WWW-Authenticate`` challenge. The
database-backed resolution path is exercised separately in the database test
suite; here the verifier is real and the session factory is deliberately unused
for authentication failures.
"""
from __future__ import annotations

import datetime as dt

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.api.deps import get_principal
from app.auth.principal import (
    AuthError,
    AuthFailure,
    AuthenticatedPrincipal,
)
from app.auth.verifier import SupabaseTokenVerifier
from app.config import Settings
from app.main import create_app


def _unused_session_factory():
    raise AssertionError("the database must not be touched for auth failures")


def _app(auth_config, jwk_client):
    verifier = SupabaseTokenVerifier(
        issuer=auth_config.issuer,
        audience=auth_config.audience,
        jwk_client=jwk_client,
    )
    return create_app(
        settings=Settings(
            database_url="",
            supabase_auth_issuer=auth_config.issuer,
            supabase_jwt_audience=auth_config.audience,
        ),
        session_factory=_unused_session_factory,
        verifier=verifier,
    )


def _assert_auth_failure(response, failure: AuthFailure) -> None:
    assert response.status_code == 401
    assert response.json()["code"] == failure.value
    assert response.headers["www-authenticate"] == "Bearer"
    body = response.text.lower()
    for forbidden in ("signature", "jwks", "app.user_id", "app_backend"):
        assert forbidden not in body


def test_missing_authorization_header_is_401(auth_config, jwk_client):
    with TestClient(_app(auth_config, jwk_client)) as client:
        response = client.post("/api/v1/session/bootstrap")

    _assert_auth_failure(response, AuthFailure.MISSING_CREDENTIALS)


def test_wrong_scheme_is_401(auth_config, jwk_client):
    with TestClient(_app(auth_config, jwk_client)) as client:
        response = client.get(
            "/api/v1/me", headers={"Authorization": "Basic abc"}
        )

    _assert_auth_failure(response, AuthFailure.MALFORMED_CREDENTIALS)


def test_invalid_signature_is_401(auth_config, jwk_client):
    other_key = ec.generate_private_key(ec.SECP256R1())
    import jwt

    token = jwt.encode(
        {
            "sub": auth_config.subject,
            "iss": auth_config.issuer,
            "aud": auth_config.audience,
            "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5),
        },
        other_key,
        algorithm="ES256",
    )

    with TestClient(_app(auth_config, jwk_client)) as client:
        response = client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
        )

    _assert_auth_failure(response, AuthFailure.INVALID_TOKEN)


def test_expired_token_is_401(auth_config, jwk_client, make_token):
    token = make_token(
        overrides={
            "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
        }
    )

    with TestClient(_app(auth_config, jwk_client)) as client:
        response = client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
        )

    _assert_auth_failure(response, AuthFailure.EXPIRED_TOKEN)


def test_wrong_audience_is_401(auth_config, jwk_client, make_token):
    token = make_token(overrides={"aud": "anon"})

    with TestClient(_app(auth_config, jwk_client)) as client:
        response = client.get(
            "/api/v1/me", headers={"Authorization": f"Bearer {token}"}
        )

    _assert_auth_failure(response, AuthFailure.INVALID_TOKEN)


def test_unmapped_identity_is_401(auth_config, jwk_client, make_token):
    app = _app(auth_config, jwk_client)

    def _unmapped() -> AuthenticatedPrincipal:
        raise AuthError(AuthFailure.UNMAPPED_IDENTITY)

    app.dependency_overrides[get_principal] = _unmapped

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {make_token()}"},
        )

    _assert_auth_failure(response, AuthFailure.UNMAPPED_IDENTITY)
