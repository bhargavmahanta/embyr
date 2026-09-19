"""Unit tests for Storage-related configuration and URL derivation."""
from __future__ import annotations

import pytest

from app.config import ConfigurationError, Settings

ISSUER = "https://embyr-dev.supabase.co/auth/v1"


def _settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql+psycopg://app_backend@example:5432/postgres",
        "supabase_auth_issuer": ISSUER,
        "storage_bucket": "embyr-media",
        "storage_secret_key": "sb_secret_test",
    }
    values.update(overrides)
    return Settings(**values)


def test_storage_api_url_is_derived_from_auth_issuer():
    settings = _settings()
    assert settings.supabase_project_origin == "https://embyr-dev.supabase.co"
    assert settings.storage_api_url == "https://embyr-dev.supabase.co/storage/v1/"


def test_storage_url_requires_expected_auth_suffix():
    with pytest.raises(ConfigurationError):
        _settings(supabase_auth_issuer="https://embyr-dev.supabase.co").storage_api_url


def test_storage_url_requires_https_origin():
    with pytest.raises(ConfigurationError):
        _settings(supabase_auth_issuer="http://embyr-dev.supabase.co/auth/v1").storage_api_url


def test_storage_enabled_only_when_bucket_and_secret_present():
    assert _settings().storage_enabled is True
    assert _settings(storage_bucket=None).storage_enabled is False
    assert _settings(storage_secret_key=None).storage_enabled is False


def _env(**overrides) -> dict[str, str]:
    env = {
        "EMBYR_DATABASE_URL": "postgresql+psycopg://app_backend@example:5432/postgres",
        "EMBYR_SUPABASE_AUTH_ISSUER": ISSUER,
        "EMBYR_SUPABASE_STORAGE_BUCKET": "embyr-media",
        "EMBYR_SUPABASE_STORAGE_SECRET_KEY": "sb_secret_test",
    }
    env.update(overrides)
    return env


def test_from_env_defaults_download_ttl_to_300():
    settings = Settings.from_env(_env())
    assert settings.storage_download_url_ttl_seconds == 300


def test_from_env_reads_download_ttl():
    settings = Settings.from_env(
        _env(EMBYR_STORAGE_DOWNLOAD_URL_TTL_SECONDS="900")
    )
    assert settings.storage_download_url_ttl_seconds == 900


@pytest.mark.parametrize("value", ["0", "-1", "not-an-int", "1.5"])
def test_from_env_rejects_bad_download_ttl(value):
    with pytest.raises(ConfigurationError):
        Settings.from_env(_env(EMBYR_STORAGE_DOWNLOAD_URL_TTL_SECONDS=value))


@pytest.mark.parametrize(
    "key", ["", "legacy-service-role-jwt", "sb_publishable_abc"]
)
def test_from_env_rejects_non_modern_secret_key(key):
    with pytest.raises(ConfigurationError):
        Settings.from_env(_env(EMBYR_SUPABASE_STORAGE_SECRET_KEY=key))


@pytest.mark.parametrize("bucket", ["", "  ", "a/b", "..", "a\\b"])
def test_from_env_rejects_bad_bucket(bucket):
    with pytest.raises(ConfigurationError):
        Settings.from_env(_env(EMBYR_SUPABASE_STORAGE_BUCKET=bucket))


def test_from_env_validates_derivable_origin():
    with pytest.raises(ConfigurationError):
        Settings.from_env(
            _env(EMBYR_SUPABASE_AUTH_ISSUER="https://embyr-dev.supabase.co")
        )


def test_from_env_missing_bucket_is_configuration_error():
    env = _env()
    del env["EMBYR_SUPABASE_STORAGE_BUCKET"]
    with pytest.raises(ConfigurationError):
        Settings.from_env(env)


def test_from_env_missing_secret_is_configuration_error():
    env = _env()
    del env["EMBYR_SUPABASE_STORAGE_SECRET_KEY"]
    with pytest.raises(ConfigurationError):
        Settings.from_env(env)
