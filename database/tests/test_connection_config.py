"""Connection-configuration contract for the persistence session factory.

These tests exercise ``app.db.session`` without a live database. They pin the
provider-independent ``EMBYR_DATABASE_URL`` contract, the explicit failure when
it is missing, the masking of credentials in engine representations, and the
pooling configuration for the selected Supavisor Session-mode deployment.

Supavisor Session mode supports prepared statements and session state; only
Transaction mode requires disabling prepared statements. The factory must not
adopt any Transaction-pooler-only workaround.
"""
from __future__ import annotations

import pytest
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.db.session import async_session_factory

# A deliberately fake credential, assembled from low-entropy words so secret
# scanners do not mistake the test fixture for a real secret.
FAKE_PASSWORD = "-".join(("definitely", "not", "a", "secret"))

SESSION_URL = (
    "postgresql+psycopg://app_backend.projectref:"
    f"{FAKE_PASSWORD}@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
    "?sslmode=require"
)


def _engine(factory):
    engine = factory.kw["bind"]
    assert engine is not None
    return engine


def test_factory_reads_embyr_database_url(monkeypatch):
    monkeypatch.setenv("EMBYR_DATABASE_URL", SESSION_URL)
    engine = _engine(async_session_factory())
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.host == "aws-0-ap-south-1.pooler.supabase.com"
    assert engine.url.port == 5432
    assert engine.url.username == "app_backend.projectref"


def test_factory_accepts_explicit_url(monkeypatch):
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    engine = _engine(async_session_factory(SESSION_URL))
    assert engine.url.host == "aws-0-ap-south-1.pooler.supabase.com"


def test_factory_requires_embyr_database_url(monkeypatch):
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="EMBYR_DATABASE_URL is required"):
        async_session_factory()


def test_missing_url_error_does_not_echo_ambient_secret(monkeypatch):
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    monkeypatch.setenv("EMBYR_UNRELATED_SECRET", FAKE_PASSWORD)
    with pytest.raises(RuntimeError) as error:
        async_session_factory()
    assert FAKE_PASSWORD not in str(error.value)


def test_engine_repr_and_url_string_mask_password(monkeypatch):
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    engine = _engine(async_session_factory(SESSION_URL))
    # The secret is genuinely present on the URL but never rendered.
    assert engine.url.password == FAKE_PASSWORD
    assert FAKE_PASSWORD not in repr(engine)
    assert FAKE_PASSWORD not in str(engine.url)


def test_factory_uses_default_application_side_pool(monkeypatch):
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    engine = _engine(async_session_factory(SESSION_URL))
    assert isinstance(engine.pool, AsyncAdaptedQueuePool)


def test_selected_mode_does_not_disable_prepared_statements(monkeypatch):
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    engine = _engine(async_session_factory(SESSION_URL))
    _, connect_kwargs = engine.dialect.create_connect_args(engine.url)
    assert "prepare_threshold" not in connect_kwargs


def test_required_url_form_enforces_tls(monkeypatch):
    # libpq defaults to sslmode=prefer, which can fall back to plaintext. The
    # documented hosted URL form must carry an explicit sslmode=require and the
    # factory must pass it through unchanged.
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    engine = _engine(async_session_factory(SESSION_URL))
    _, connect_kwargs = engine.dialect.create_connect_args(engine.url)
    assert connect_kwargs.get("sslmode") == "require"


def test_factory_rejects_explicit_url_without_sslmode(monkeypatch):
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    insecure = SESSION_URL.replace("?sslmode=require", "")
    with pytest.raises(RuntimeError, match="must require TLS"):
        async_session_factory(insecure)


def test_factory_rejects_explicit_url_with_sslmode_disable(monkeypatch):
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    insecure = SESSION_URL.replace("sslmode=require", "sslmode=disable")
    with pytest.raises(RuntimeError, match="must require TLS"):
        async_session_factory(insecure)


def test_factory_rejects_env_url_without_sslmode(monkeypatch):
    monkeypatch.setenv(
        "EMBYR_DATABASE_URL", SESSION_URL.replace("?sslmode=require", "")
    )
    with pytest.raises(RuntimeError, match="must require TLS"):
        async_session_factory()


def test_tls_rejection_does_not_echo_the_credential(monkeypatch):
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    insecure = SESSION_URL.replace("?sslmode=require", "")
    with pytest.raises(RuntimeError) as error:
        async_session_factory(insecure)
    assert FAKE_PASSWORD not in str(error.value)


def test_factory_accepts_sslmode_verify_full(monkeypatch):
    monkeypatch.delenv("EMBYR_DATABASE_URL", raising=False)
    verified = SESSION_URL.replace("sslmode=require", "sslmode=verify-full")
    engine = _engine(async_session_factory(verified))
    _, connect_kwargs = engine.dialect.create_connect_args(engine.url)
    assert connect_kwargs.get("sslmode") == "verify-full"
