from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine
from testcontainers.community.postgres import PostgresContainer

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPOSITORY_ROOT / "database" / "alembic.ini"
PGVECTOR_IMAGE = "pgvector/pgvector:pg16"


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


@pytest.fixture(scope="session")
def migrated_engine(database_url: str) -> Iterator[Engine]:
    config = make_alembic_config(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
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
