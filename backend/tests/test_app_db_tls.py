"""The FastAPI production engine path must enforce the Issue #32 TLS policy.

``create_app`` builds the runtime engine itself when no session factory is
injected, so it must route through the same single TLS validator used by
``async_session_factory``. These tests do not open a database connection.
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.db.session import TLS_REQUIRED_SSLMODES, require_database_tls
from app.main import create_app

ISSUER = "https://embyr-dev.supabase.co/auth/v1"
FAKE_PASSWORD = "-".join(("definitely", "not", "a", "secret"))
BASE_URL = (
    "postgresql+psycopg://app_backend.projectref:"
    f"{FAKE_PASSWORD}@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
)


def _settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url, supabase_auth_issuer=ISSUER
    )


@pytest.mark.parametrize(
    "query",
    ["", "?sslmode=disable", "?sslmode=allow", "?sslmode=prefer"],
)
def test_create_app_rejects_insecure_database_url(query):
    with pytest.raises(RuntimeError, match="must require TLS"):
        create_app(settings=_settings(BASE_URL + query))


@pytest.mark.parametrize("mode", sorted(TLS_REQUIRED_SSLMODES))
def test_create_app_accepts_required_tls_modes(mode):
    app = create_app(settings=_settings(f"{BASE_URL}?sslmode={mode}"))
    try:
        assert app.state.engine is not None
    finally:
        asyncio.run(app.state.engine.dispose())


def test_shared_validator_is_the_single_tls_policy():
    for mode in sorted(TLS_REQUIRED_SSLMODES):
        require_database_tls(f"{BASE_URL}?sslmode={mode}")
    for query in ("", "?sslmode=disable", "?sslmode=allow", "?sslmode=prefer"):
        with pytest.raises(RuntimeError, match="must require TLS"):
            require_database_tls(BASE_URL + query)
