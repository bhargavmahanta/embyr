"""Unit tests for Supabase JWT verification (issue #34).

The verification layer is tested with real asymmetric signatures: tokens are
signed with a locally generated EC key and verified against the matching public
key. No live Supabase endpoint is contacted.
"""
from __future__ import annotations

import datetime as dt

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth.principal import AuthError, AuthFailure, ExternalIdentity
from app.auth.verifier import SupabaseTokenVerifier


def _verifier(jwk_client, auth_config) -> SupabaseTokenVerifier:
    return SupabaseTokenVerifier(
        issuer=auth_config.issuer,
        audience=auth_config.audience,
        algorithms=("ES256", "RS256"),
        jwk_client=jwk_client,
    )


def test_valid_token_returns_supabase_external_identity(
    make_token, jwk_client, auth_config
):
    identity = _verifier(jwk_client, auth_config).verify(make_token())

    assert identity == ExternalIdentity(
        provider="SUPABASE", subject=auth_config.subject
    )


def test_token_signed_by_other_key_is_rejected(make_token, jwk_client, auth_config):
    other_key = ec.generate_private_key(ec.SECP256R1())

    with pytest.raises(AuthError) as error:
        _verifier(jwk_client, auth_config).verify(make_token(key=other_key))

    assert error.value.failure is AuthFailure.INVALID_TOKEN


def test_expired_token_is_rejected(make_token, jwk_client, auth_config):
    token = make_token(overrides={"exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)})

    with pytest.raises(AuthError) as error:
        _verifier(jwk_client, auth_config).verify(token)

    assert error.value.failure is AuthFailure.EXPIRED_TOKEN


def test_wrong_issuer_is_rejected(make_token, jwk_client, auth_config):
    token = make_token(overrides={"iss": "https://attacker.supabase.co/auth/v1"})

    with pytest.raises(AuthError) as error:
        _verifier(jwk_client, auth_config).verify(token)

    assert error.value.failure is AuthFailure.INVALID_TOKEN


def test_wrong_audience_is_rejected(make_token, jwk_client, auth_config):
    token = make_token(overrides={"aud": "service_role"})

    with pytest.raises(AuthError) as error:
        _verifier(jwk_client, auth_config).verify(token)

    assert error.value.failure is AuthFailure.INVALID_TOKEN


def test_missing_subject_is_rejected(make_token, jwk_client, auth_config):
    token = make_token(drop=("sub",))

    with pytest.raises(AuthError) as error:
        _verifier(jwk_client, auth_config).verify(token)

    assert error.value.failure is AuthFailure.INVALID_TOKEN


def test_missing_expiry_is_rejected(make_token, jwk_client, auth_config):
    token = make_token(drop=("exp",))

    with pytest.raises(AuthError) as error:
        _verifier(jwk_client, auth_config).verify(token)

    assert error.value.failure is AuthFailure.INVALID_TOKEN


def test_not_yet_valid_token_is_rejected(make_token, jwk_client, auth_config):
    token = make_token(
        overrides={"nbf": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)}
    )

    with pytest.raises(AuthError) as error:
        _verifier(jwk_client, auth_config).verify(token)

    assert error.value.failure is AuthFailure.INVALID_TOKEN


def test_symmetric_algorithm_is_not_accepted(make_token, jwk_client, auth_config):
    token = make_token(key="shared-secret" * 4, alg="HS256")

    with pytest.raises(AuthError) as error:
        _verifier(jwk_client, auth_config).verify(token)

    assert error.value.failure is AuthFailure.UNSUPPORTED_TOKEN


def test_malformed_token_is_rejected(jwk_client, auth_config):
    with pytest.raises(AuthError) as error:
        _verifier(jwk_client, auth_config).verify("not-a-jwt")

    assert error.value.failure is AuthFailure.INVALID_TOKEN
