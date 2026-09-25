from __future__ import annotations

import json
import os
from logging.config import fileConfig

from alembic import context
from alembic.autogenerate import Rewriter
from alembic.operations import ops
from sqlalchemy import engine_from_config, pool

from app.db.base import Base
from app.db import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.getenv("EMBYR_DATABASE_URL") or config.get_main_option(
    "sqlalchemy.url"
)
if not database_url:
    raise RuntimeError("EMBYR_DATABASE_URL or sqlalchemy.url is required")
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata


def _is_0013_default_acl_marker(comment: str | None) -> bool:
    if comment is None:
        return False
    try:
        marker = json.loads(comment)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(marker, dict)
        and set(marker) == {"revision", "owner", "defaults"}
        and marker["revision"] == "0013_default_acl_hardening"
        and marker["owner"] == "app_owner"
        and isinstance(marker["defaults"], dict)
    )


autogenerate_rewriter = Rewriter()


@autogenerate_rewriter.rewrites(ops.DropTableCommentOp)
def _preserve_0013_default_acl_marker(
    _context: object, _revision: object, operation: ops.DropTableCommentOp
) -> ops.DropTableCommentOp | list[ops.MigrateOperation]:
    if (
        operation.table_name == "app_users"
        and operation.schema in (None, "public")
        and _is_0013_default_acl_marker(operation.existing_comment)
    ):
        return []
    return operation


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=autogenerate_rewriter,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
