"""Default-privilege hardening tests for migration 0013.

These tests exercise real PostgreSQL default ACL behaviour for the Supabase Data
API client roles (``anon``, ``authenticated``, ``service_role``). No privileges
are mocked, and every test that asserts a boundary first creates the client
roles and simulates the unsafe default state that the migration must remove, so
the assertions cannot pass vacuously when the roles are absent.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPOSITORY_ROOT / "database" / "alembic.ini"

HEAD = "0017_idempotency_key_reuse"
PREVIOUS = "0012_rls_and_security"
OWNER = "app_owner"
CLIENT_ROLES = ("anon", "authenticated", "service_role")
DEFAULT_OBJECT_TYPES = {"r": "TABLES", "S": "SEQUENCES", "f": "FUNCTIONS"}

TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)


def _config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _ensure_client_roles(engine) -> list[str]:
    created: list[str] = []
    with engine.begin() as connection:
        for role in CLIENT_ROLES:
            exists = connection.execute(
                text("select 1 from pg_roles where rolname = :role"),
                {"role": role},
            ).scalar_one_or_none()
            if exists is None:
                connection.execute(text(f"create role {role} nologin"))
                created.append(role)
    return created


def _drop_client_roles(engine, roles: list[str]) -> None:
    if not roles:
        return
    with engine.begin() as connection:
        for role in roles:
            for keyword in DEFAULT_OBJECT_TYPES.values():
                connection.execute(
                    text(
                        f"alter default privileges for role {OWNER} in schema "
                        f"public revoke all on {keyword} from {role}"
                    )
                )
            connection.execute(text(f"drop role if exists {role}"))


def _simulate_unsafe_defaults(engine, roles: Sequence[str]) -> None:
    with engine.begin() as connection:
        for role in roles:
            for keyword in DEFAULT_OBJECT_TYPES.values():
                connection.execute(
                    text(
                        f"alter default privileges for role {OWNER} in schema "
                        f"public grant all on {keyword} to {role}"
                    )
                )


def _owner_defaults(engine, schema: str = "public") -> dict[tuple[str, str], set[str]]:
    recorded: dict[tuple[str, str], set[str]] = {}
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                select d.defaclobjtype as objtype,
                       grantee.rolname as grantee,
                       acl.privilege_type as privilege
                from pg_default_acl d
                join pg_roles owner on owner.oid = d.defaclrole
                join pg_namespace n on n.oid = d.defaclnamespace
                cross join lateral aclexplode(d.defaclacl) acl
                join pg_roles grantee on grantee.oid = acl.grantee
                where owner.rolname = :owner
                  and n.nspname = :schema
                """
            ),
            {"owner": OWNER, "schema": schema},
        ).all()
    for row in rows:
        recorded.setdefault((row.objtype, row.grantee), set()).add(
            row.privilege
        )
    return recorded


def _owner_public_defaults(engine) -> dict[tuple[str, str], set[str]]:
    return _owner_defaults(engine, "public")


def _client_defaults(engine) -> dict[tuple[str, str], set[str]]:
    return {
        key: privileges
        for key, privileges in _owner_public_defaults(engine).items()
        if key[1] in CLIENT_ROLES
    }


def _create_owned_objects(engine, suffix: str) -> dict[str, str]:
    table = f"_embyr_dacl_table_{suffix}"
    sequence = f"_embyr_dacl_seq_{suffix}"
    function = f"_embyr_dacl_fn_{suffix}"
    with engine.begin() as connection:
        connection.execute(text("set local role app_owner"))
        connection.execute(text(f"create table public.{table} (id int)"))
        connection.execute(text(f"create sequence public.{sequence}"))
        connection.execute(
            text(
                f"create function public.{function}() returns int "
                "language sql as 'select 1'"
            )
        )
        connection.execute(text("reset role"))
    return {"table": table, "sequence": sequence, "function": function}


def _drop_owned_objects(engine, objects: dict[str, str]) -> None:
    with engine.begin() as connection:
        connection.execute(text("set local role app_owner"))
        connection.execute(
            text(f"drop function if exists public.{objects['function']}()")
        )
        connection.execute(
            text(f"drop sequence if exists public.{objects['sequence']}")
        )
        connection.execute(
            text(f"drop table if exists public.{objects['table']}")
        )
        connection.execute(text("reset role"))


def _head_revision() -> str:
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    heads = script.get_heads()
    assert len(heads) == 1
    return heads[0]


def test_repository_has_one_migration_head():
    assert _head_revision() == HEAD


def test_0013_preserves_unrelated_default_acl_entries(isolated_migrated_database):
    database_url = isolated_migrated_database.url
    config = _config(database_url)
    engine = create_engine(database_url)
    client_roles = _ensure_client_roles(engine)
    unrelated = f"dacl_unrelated_{uuid4().hex}"
    try:
        command.downgrade(config, PREVIOUS)
        with engine.begin() as connection:
            connection.execute(text(f"create role {unrelated} nologin"))
            connection.execute(
                text(
                    f"alter default privileges for role {OWNER} in schema "
                    f"public grant select on tables to {unrelated}"
                )
            )
        before = _owner_public_defaults(engine)

        command.upgrade(config, "head")
        assert _owner_public_defaults(engine).get(("r", unrelated)) == {"SELECT"}

        command.downgrade(config, PREVIOUS)
        assert _owner_public_defaults(engine) == before
    finally:
        command.downgrade(config, PREVIOUS)
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"alter default privileges for role {OWNER} in schema "
                    f"public revoke all on tables from {unrelated}"
                )
            )
            connection.execute(text(f"drop role if exists {unrelated}"))
        _drop_client_roles(engine, client_roles)
        command.upgrade(config, "head")
        engine.dispose()


def test_0013_downgrade_restores_prior_default_acl_state(
    isolated_migrated_database,
):
    database_url = isolated_migrated_database.url
    config = _config(database_url)
    engine = create_engine(database_url)
    client_roles = _ensure_client_roles(engine)
    try:
        command.downgrade(config, PREVIOUS)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "alter default privileges for role "
                    f"{OWNER} in schema public grant select, insert on tables "
                    "to anon, authenticated"
                )
            )
            connection.execute(
                text(
                    "alter default privileges for role "
                    f"{OWNER} in schema public grant usage, select on "
                    "sequences to authenticated"
                )
            )
            connection.execute(
                text(
                    "alter default privileges for role "
                    f"{OWNER} in schema public grant execute on functions "
                    "to service_role"
                )
            )
        before = _owner_public_defaults(engine)
        assert before[("r", "anon")] == {"SELECT", "INSERT"}
        assert before[("S", "authenticated")] == {"USAGE", "SELECT"}
        assert before[("f", "service_role")] == {"EXECUTE"}

        command.upgrade(config, "head")
        assert _client_defaults(engine) == {}

        command.downgrade(config, PREVIOUS)
        assert _owner_public_defaults(engine) == before
    finally:
        command.downgrade(config, PREVIOUS)
        _drop_client_roles(engine, client_roles)
        command.upgrade(config, "head")
        engine.dispose()


def test_0013_blocks_future_objects_for_client_roles(isolated_migrated_database):
    database_url = isolated_migrated_database.url
    config = _config(database_url)
    engine = create_engine(database_url)
    client_roles = _ensure_client_roles(engine)
    suffix = uuid4().hex
    objects = None
    try:
        command.downgrade(config, PREVIOUS)
        _simulate_unsafe_defaults(engine, CLIENT_ROLES)
        assert _client_defaults(engine) != {}

        command.upgrade(config, "head")
        assert _client_defaults(engine) == {}

        objects = _create_owned_objects(engine, suffix)
        with engine.connect() as connection:
            owner = connection.execute(
                text(
                    "select pg_get_userbyid(c.relowner) from pg_class c "
                    "join pg_namespace n on n.oid = c.relnamespace "
                    "where n.nspname = 'public' and c.relname = :name"
                ),
                {"name": objects["table"]},
            ).scalar_one()
            assert owner == OWNER

            for role in CLIENT_ROLES:
                for privilege in TABLE_PRIVILEGES:
                    assert connection.execute(
                        text(
                            "select has_table_privilege(:role, :table, "
                            ":privilege)"
                        ),
                        {
                            "role": role,
                            "table": f"public.{objects['table']}",
                            "privilege": privilege,
                        },
                    ).scalar_one() is False
                assert connection.execute(
                    text(
                        "select has_sequence_privilege(:role, :sequence, "
                        "'USAGE')"
                    ),
                    {
                        "role": role,
                        "sequence": f"public.{objects['sequence']}",
                    },
                ).scalar_one() is False
                assert connection.execute(
                    text(
                        "select has_function_privilege(:role, :function, "
                        "'EXECUTE')"
                    ),
                    {
                        "role": role,
                        "function": f"public.{objects['function']}()",
                    },
                ).scalar_one() is False
    finally:
        if objects is not None:
            _drop_owned_objects(engine, objects)
        command.downgrade(config, PREVIOUS)
        _drop_client_roles(engine, client_roles)
        command.upgrade(config, "head")
        engine.dispose()


def test_0013_preserves_non_public_default_acl_entries(
    isolated_migrated_database,
):
    """0013 only changes public/global defaults; other schemas are untouched."""
    database_url = isolated_migrated_database.url
    config = _config(database_url)
    engine = create_engine(database_url)
    client_roles = _ensure_client_roles(engine)
    other_schema = f"dacl_other_{uuid4().hex}"
    other_role = f"dacl_other_role_{uuid4().hex}"
    try:
        command.downgrade(config, PREVIOUS)
        with engine.begin() as connection:
            connection.execute(text(f"create schema {other_schema}"))
            connection.execute(text(f"create role {other_role} nologin"))
            connection.execute(
                text(
                    f"alter default privileges for role {OWNER} in schema "
                    f"{other_schema} grant select on tables to {other_role}"
                )
            )
        before = _owner_defaults(engine, other_schema)
        assert before.get(("r", other_role)) == {"SELECT"}

        command.upgrade(config, "head")
        assert _owner_defaults(engine, other_schema) == before

        command.downgrade(config, PREVIOUS)
        assert _owner_defaults(engine, other_schema) == before
    finally:
        command.downgrade(config, PREVIOUS)
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"alter default privileges for role {OWNER} in schema "
                    f"{other_schema} revoke all on tables from {other_role}"
                )
            )
            connection.execute(text(f"drop role if exists {other_role}"))
            connection.execute(
                text(f"drop schema if exists {other_schema} cascade")
            )
        _drop_client_roles(engine, client_roles)
        command.upgrade(config, "head")
        engine.dispose()


def test_0013_rejects_global_client_role_defaults(isolated_migrated_database):
    """A global client-role grant cannot be undone by a schema-scoped REVOKE."""
    database_url = isolated_migrated_database.url
    config = _config(database_url)
    engine = create_engine(database_url)
    client_roles = _ensure_client_roles(engine)
    try:
        command.downgrade(config, PREVIOUS)
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"alter default privileges for role {OWNER} "
                    "grant select on tables to anon"
                )
            )

        with pytest.raises(RuntimeError, match="global client-role defaults"):
            command.upgrade(config, "head")
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"alter default privileges for role {OWNER} "
                    "revoke all on tables from anon"
                )
            )
        _drop_client_roles(engine, client_roles)
        command.upgrade(config, "head")
        engine.dispose()
