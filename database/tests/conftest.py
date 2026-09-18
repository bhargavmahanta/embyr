from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPOSITORY_ROOT / "database" / "alembic.ini"
PGVECTOR_IMAGE = "pgvector/pgvector:pg16"

# Runtime roles that migration ``0012_rls_and_security`` verifies. They are
# provisioned here rather than by the migration because creating a BYPASSRLS
# role requires superuser authority a migration credential is not guaranteed to
# hold on hosted PostgreSQL. The roles live at the cluster level and are
# discarded with the disposable test cluster.
RUNTIME_ROLES: dict[str, str] = {
    "app_backend": "nologin nobypassrls",
    "app_worker": "nologin bypassrls",
    "app_maintenance": "nologin bypassrls",
}

# The migration/object owner. It is provisioned here for the same reason as the
# runtime roles: migration ``0013_default_acl_hardening`` hardens
# ``app_owner``'s default privileges but never creates cluster roles.
OWNER_ROLE = "app_owner"
OWNER_ROLE_ATTRIBUTES = "nologin nobypassrls"


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg2://", "postgresql+psycopg://")


def _validate_disposable_url(url: str) -> None:
    database = urlparse(url).path.removeprefix("/").lower()
    if "test" not in database or database in {"postgres", "template0", "template1"}:
        raise RuntimeError(
            "EMBYR_TEST_DATABASE_URL must name a dedicated disposable test database"
        )


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    configured = os.getenv("EMBYR_TEST_DATABASE_URL")
    if configured:
        _validate_disposable_url(configured)
        yield _psycopg_url(configured)
        return

    with PostgresContainer(PGVECTOR_IMAGE, driver="psycopg") as postgres:
        yield _psycopg_url(postgres.get_connection_url())


def make_alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def provision_runtime_roles(engine: Engine) -> None:
    """Idempotently create the externally provisioned roles.

    Migration ``0012_rls_and_security`` verifies the runtime roles instead of
    creating them, and ``0013_default_acl_hardening`` requires the
    ``app_owner`` role, so the harness must provide them before ``upgrade
    head``. When a dedicated ``EMBYR_TEST_DATABASE_URL`` is used, the roles
    must either already exist or be creatable; otherwise the failure is
    explicit rather than silently skipping the security boundary.
    """
    roles = {**RUNTIME_ROLES, OWNER_ROLE: OWNER_ROLE_ATTRIBUTES}
    with engine.begin() as connection:
        for role, attributes in roles.items():
            exists = connection.execute(
                text("select 1 from pg_roles where rolname = :role"),
                {"role": role},
            ).scalar_one_or_none()
            if exists is not None:
                continue
            try:
                connection.execute(text(f"create role {role} {attributes}"))
            except DBAPIError as error:
                raise RuntimeError(
                    "the test database must expose pre-provisioned runtime "
                    f"role {role!r} or allow creating it, because migration "
                    "0012 verifies the role instead of provisioning it"
                ) from error
        # Mirror the platform provisioning that grants app_owner the schema
        # authority and ownership-transfer membership migrations require.
        connection.execute(
            text(
                "grant usage, create on schema public to app_owner "
                "with grant option"
            )
        )
        connection.execute(
            text("grant app_maintenance to app_owner with set true")
        )


@pytest.fixture(scope="session")
def migrated_engine(database_url: str) -> Iterator[Engine]:
    config = make_alembic_config(database_url)
    engine = create_engine(database_url)
    provision_runtime_roles(engine)
    command.upgrade(config, "head")
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")


@pytest.fixture
def migrated_connection(migrated_engine: Engine) -> Iterator[Connection]:
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
