"""Unit tests for the Authorization header parsing boundary."""
from __future__ import annotations

import pytest

from app.auth.principal import AuthError, AuthFailure
from app.auth.verifier import parse_bearer


def test_missing_header_is_missing_credentials():
    with pytest.raises(AuthError) as error:
        parse_bearer(None)
    assert error.value.failure is AuthFailure.MISSING_CREDENTIALS


def test_empty_header_is_missing_credentials():
    with pytest.raises(AuthError) as error:
        parse_bearer("")
    assert error.value.failure is AuthFailure.MISSING_CREDENTIALS


def test_wrong_scheme_is_malformed_credentials():
    with pytest.raises(AuthError) as error:
        parse_bearer("Basic dXNlcjpwYXNz")
    assert error.value.failure is AuthFailure.MALFORMED_CREDENTIALS


def test_missing_token_is_malformed_credentials():
    with pytest.raises(AuthError) as error:
        parse_bearer("Bearer")
    assert error.value.failure is AuthFailure.MALFORMED_CREDENTIALS


def test_extra_segments_are_malformed_credentials():
    with pytest.raises(AuthError) as error:
        parse_bearer("Bearer a b")
    assert error.value.failure is AuthFailure.MALFORMED_CREDENTIALS


def test_valid_bearer_returns_token():
    assert parse_bearer("Bearer header.payload.signature") == (
        "header.payload.signature"
    )
