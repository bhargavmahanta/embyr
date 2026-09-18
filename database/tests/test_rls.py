"""Row-level security and runtime role boundary tests for migration 0012.

These tests exercise real PostgreSQL behaviour: roles, schema and table
privileges, RLS flags, policies, cross-user isolation, worker boundaries, the
maintenance deletion path under active RLS, and downgrade. No PostgreSQL
security semantics are mocked.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPOSITORY_ROOT / "database" / "alembic.ini"

BACKEND_ROLE = "app_backend"
WORKER_ROLE = "app_worker"
MAINTENANCE_ROLE = "app_maintenance"
MAINTENANCE_FUNCTION = "public.maintenance_delete_account"
CLIENT_ROLES = ("anon", "authenticated", "service_role")
HEAD = "0013_default_acl_hardening"

LEARNER_TABLES = (
    "user_devices",
    "idempotency_records",
    "jobs",
    "learner_preferences",
    "user_motivations",
    "explicit_interest_preferences",
    "explorations",
    "reflections",
    "assessment_sessions",
    "assessment_interactions",
    "assessment_support_requests",
    "assessment_responses",
    "evaluation_runs",
    "learning_evidence",
    "artifacts",
    "media_objects",
    "upload_sessions",
    "artifact_analyses",
    "learning_events",
    "learner_interest_state",
    "learner_confidence_state",
    "learner_retention_state",
    "learner_objective_state",
    "learner_challenge_state",
    "state_evidence_links",
    "recommendations",
    "learner_worlds",
    "world_regions",
    "world_nodes",
    "world_connections",
    "world_artifacts",
    "world_changes",
    "curiosity_stories",
    "account_operation_requests",
)

CANONICAL_TABLES = (
    "learning_entities",
    "learning_entity_versions",
    "learning_objectives",
    "ontology_edges",
    "entity_domains",
    "practical_challenges",
    "practical_challenge_versions",
    "misconceptions",
    "claims",
    "entity_embeddings",
)

# Approved matrix: app_backend request-path grants.
BACKEND_FULL_DML = (
    "user_devices",
    "idempotency_records",
    "learner_preferences",
    "user_motivations",
    "explicit_interest_preferences",
    "explorations",
    "reflections",
    "assessment_sessions",
    "assessment_interactions",
    "assessment_support_requests",
    "upload_sessions",
)
BACKEND_INSERT_SELECT = (
    "assessment_responses",
    "media_objects",
    "artifacts",
    "learning_events",
)
BACKEND_SELECT_INSERT_UPDATE = (
    "jobs",
    "evaluation_runs",
    "recommendations",
    "account_operation_requests",
)
BACKEND_SELECT_ONLY = (
    "learning_evidence",
    "artifact_analyses",
    "learner_interest_state",
    "learner_confidence_state",
    "learner_retention_state",
    "learner_objective_state",
    "learner_challenge_state",
    "state_evidence_links",
    "learner_worlds",
    "world_regions",
    "world_nodes",
    "world_connections",
    "world_artifacts",
    "world_changes",
    "curiosity_stories",
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _insert_user(connection) -> str:
    return connection.execute(
        text(
            "insert into app_users (auth_provider, auth_subject) "
            "values ('test', :subject) returning id"
        ),
        {"subject": str(uuid4())},
    ).scalar_one()


def _insert_entity(connection) -> str:
    return connection.execute(
        text(
            "insert into learning_entities (canonical_key, entity_type, status) "
            "values (:key, 'TOPIC', 'REVIEWED') returning id"
        ),
        {"key": f"rls-{uuid4()}"},
    ).scalar_one()


def _insert_preference(connection, user_id) -> None:
    connection.execute(
        text(
            "insert into learner_preferences "
            "(user_id, adventure_preference, preferred_effort, support_style) "
            "values (:user_id, 'BALANCED', '15_20_MIN', 'SMALL_HINT')"
        ),
        {"user_id": user_id},
    )


def _insert_event(connection, user_id) -> str:
    return connection.execute(
        text(
            "insert into learning_events "
            "(user_id, event_type, occurred_at, schema_version) "
            "values (:user_id, 'EXPLORATION_STARTED', now(), 1) returning id"
        ),
        {"user_id": user_id},
    ).scalar_one()


def _insert_job(connection, user_id) -> str:
    return connection.execute(
        text(
            "insert into jobs (user_id, job_type, status) "
            "values (:user_id, 'EVALUATION', 'PENDING') returning id"
        ),
        {"user_id": user_id},
    ).scalar_one()


def _count(connection, table: str, user_id) -> int:
    return connection.execute(
        text(f"select count(*) from {table} where user_id = :user_id"),
        {"user_id": user_id},
    ).scalar_one()


def _as_role(connection, role: str) -> None:
    connection.execute(text(f"set local role {role}"))


def _reset_role(connection) -> None:
    connection.execute(text("reset role"))


def _set_user(connection, user_id) -> None:
    connection.execute(
        text("select set_config('app.user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )


def _has_table_privilege(connection, role: str, table: str, privilege: str) -> bool:
    return connection.execute(
        text("select has_table_privilege(:role, :table, :privilege)"),
        {"role": role, "table": table, "privilege": privilege},
    ).scalar_one()


def _alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


# ---------------------------------------------------------------------------
# migration shape
# ---------------------------------------------------------------------------


def test_alembic_has_exactly_one_head():
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))

    assert script.get_heads() == [HEAD]


# ---------------------------------------------------------------------------
# RLS flags and policies
# ---------------------------------------------------------------------------


def test_rls_enabled_and_forced_for_all_learner_tables(migrated_connection):
    rows = {
        row.relname: (row.relrowsecurity, row.relforcerowsecurity)
        for row in migrated_connection.execute(
            text(
                """
                select c.relname, c.relrowsecurity, c.relforcerowsecurity
                from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'public'
                  and c.relkind = 'r'
                  and c.relname = any(:tables)
                """
            ),
            {"tables": list(LEARNER_TABLES)},
        ).all()
    }

    assert set(rows) == set(LEARNER_TABLES)
    for table in LEARNER_TABLES:
        enabled, forced = rows[table]
        assert enabled is True, f"{table} must enable RLS"
        assert forced is True, f"{table} must FORCE RLS"


def test_app_users_and_canonical_tables_have_no_rls(migrated_connection):
    tables = ["app_users", *CANONICAL_TABLES]
    rows = dict(
        migrated_connection.execute(
            text(
                """
                select c.relname, c.relrowsecurity
                from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'public' and c.relname = any(:tables)
                """
            ),
            {"tables": tables},
        ).all()
    )

    assert set(rows) == set(tables)
    for table in tables:
        assert rows[table] is False, f"{table} must not use RLS"


def test_backend_policy_uses_nullif_identity(migrated_connection):
    rows = {
        row.tablename: row
        for row in migrated_connection.execute(
            text(
                "select tablename, roles, cmd, qual, with_check "
                "from pg_policies where schemaname = 'public'"
            )
        ).all()
    }

    assert set(rows) == set(LEARNER_TABLES)
    for table, row in rows.items():
        assert list(row.roles) == [BACKEND_ROLE], table
        assert row.cmd == "ALL", table
        qual = row.qual.lower()
        check = row.with_check.lower()
        assert "nullif" in qual and "app.user_id" in qual, table
        assert "nullif" in check and "app.user_id" in check, table


# ---------------------------------------------------------------------------
# roles, schema, and grants (catalog)
# ---------------------------------------------------------------------------


def test_runtime_roles_are_provisioned_with_required_attributes(migrated_connection):
    rows = {
        row.rolname: (row.rolcanlogin, row.rolbypassrls, row.rolsuper)
        for row in migrated_connection.execute(
            text(
                "select rolname, rolcanlogin, rolbypassrls, rolsuper "
                "from pg_roles where rolname = any(:roles)"
            ),
            {"roles": [BACKEND_ROLE, WORKER_ROLE, MAINTENANCE_ROLE]},
        ).all()
    }

    assert rows == {
        BACKEND_ROLE: (False, False, False),
        WORKER_ROLE: (False, True, False),
        MAINTENANCE_ROLE: (False, True, False),
    }


def test_runtime_roles_have_usage_but_not_create_on_public(migrated_connection):
    for role in (BACKEND_ROLE, WORKER_ROLE, MAINTENANCE_ROLE):
        assert migrated_connection.execute(
            text("select has_schema_privilege(:role, 'public', 'USAGE')"),
            {"role": role},
        ).scalar_one() is True
        assert migrated_connection.execute(
            text("select has_schema_privilege(:role, 'public', 'CREATE')"),
            {"role": role},
        ).scalar_one() is False


def test_runtime_roles_do_not_own_unapproved_application_objects(
    migrated_connection,
):
    relation_owners = migrated_connection.execute(
        text(
            """
            select c.relname, pg_get_userbyid(c.relowner) as owner
            from pg_class c
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public'
              and pg_get_userbyid(c.relowner) = any(:roles)
            """
        ),
        {"roles": [BACKEND_ROLE, WORKER_ROLE, MAINTENANCE_ROLE]},
    ).all()
    function_owners = migrated_connection.execute(
        text(
            """
            select p.proname, pg_get_userbyid(p.proowner) as owner
            from pg_proc p
            join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public'
              and pg_get_userbyid(p.proowner) = any(:roles)
            """
        ),
        {"roles": [BACKEND_ROLE, WORKER_ROLE, MAINTENANCE_ROLE]},
    ).all()

    assert relation_owners == []
    assert function_owners == [("maintenance_delete_account", MAINTENANCE_ROLE)]


@pytest.mark.parametrize(
    ("unsafe_sql", "restore_sql", "message"),
    (
        (
            "alter role app_backend superuser",
            "alter role app_backend nosuperuser nocreaterole nocreatedb "
            "noreplication nologin nobypassrls",
            "app_backend must not be SUPERUSER",
        ),
        (
            "alter role app_worker superuser",
            "alter role app_worker nosuperuser nocreaterole nocreatedb "
            "noreplication nologin bypassrls",
            "app_worker must not be SUPERUSER",
        ),
        (
            "alter role app_maintenance superuser",
            "alter role app_maintenance nosuperuser nocreaterole nocreatedb "
            "noreplication nologin bypassrls",
            "app_maintenance must not be SUPERUSER",
        ),
        (
            "alter role app_maintenance login",
            "alter role app_maintenance nosuperuser nocreaterole nocreatedb "
            "noreplication nologin bypassrls",
            "app_maintenance must be NOLOGIN",
        ),
    ),
)
def test_upgrade_rejects_unsafe_runtime_role_attributes(
    database_url,
    migrated_engine,
    unsafe_sql,
    restore_sql,
    message,
):
    del migrated_engine  # ensure the session-scoped migrated database exists
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    command.downgrade(config, "0011a_account_deletion")

    try:
        with engine.begin() as connection:
            connection.execute(text(unsafe_sql))

        with pytest.raises(RuntimeError, match=message):
            command.upgrade(config, "head")
    finally:
        with engine.begin() as connection:
            connection.execute(text(restore_sql))
            current = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        if current != HEAD:
            command.upgrade(config, "head")
        engine.dispose()


@pytest.mark.parametrize("granted_role", (WORKER_ROLE, None))
def test_upgrade_rejects_any_outbound_runtime_role_membership(
    database_url,
    migrated_engine,
    granted_role,
):
    del migrated_engine  # ensure the session-scoped migrated database exists
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    generic_role = f"rls_generic_group_{uuid4().hex}"
    target_role = granted_role or generic_role
    command.downgrade(config, "0011a_account_deletion")

    try:
        with engine.begin() as connection:
            if granted_role is None:
                connection.execute(text(f"create role {generic_role} nologin"))
            connection.execute(text(f"grant {target_role} to {BACKEND_ROLE}"))

        with pytest.raises(
            RuntimeError,
            match="runtime roles must not be members of other roles",
        ):
            command.upgrade(config, "head")

        with engine.connect() as connection:
            assert connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one() == "0011a_account_deletion"
            assert connection.execute(
                text("select count(*) from pg_policies where schemaname = 'public'")
            ).scalar_one() == 0
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(f"revoke {target_role} from {BACKEND_ROLE}")
            )
            if granted_role is None:
                connection.execute(text(f"drop role {generic_role}"))
            current = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        if current != HEAD:
            command.upgrade(config, "head")
        engine.dispose()


def test_upgrade_allows_app_owner_membership_in_maintenance_role(
    database_url,
    migrated_engine,
):
    del migrated_engine  # ensure the session-scoped migrated database exists
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    admin_role = "app_owner"
    role_existed = None
    membership_existed = None

    try:
        command.downgrade(config, "0011a_account_deletion")
        with engine.begin() as connection:
            role_existed = connection.execute(
                text("select 1 from pg_roles where rolname = :role"),
                {"role": admin_role},
            ).scalar_one_or_none() is not None
            if not role_existed:
                connection.execute(text(f"create role {admin_role} nologin"))
            membership_existed = connection.execute(
                text(
                    """
                    select 1
                    from pg_auth_members membership
                    join pg_roles granted on granted.oid = membership.roleid
                    join pg_roles member on member.oid = membership.member
                    where granted.rolname = :granted_role
                      and member.rolname = :member_role
                    """
                ),
                {
                    "granted_role": MAINTENANCE_ROLE,
                    "member_role": admin_role,
                },
            ).scalar_one_or_none() is not None
            if not membership_existed:
                connection.execute(
                    text(f"grant {MAINTENANCE_ROLE} to {admin_role}")
                )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one() == HEAD
            assert connection.execute(
                text(
                    """
                    select count(*)
                    from pg_auth_members membership
                    join pg_roles granted on granted.oid = membership.roleid
                    join pg_roles member on member.oid = membership.member
                    where granted.rolname = :granted_role
                      and member.rolname = :member_role
                    """
                ),
                {
                    "granted_role": MAINTENANCE_ROLE,
                    "member_role": admin_role,
                },
            ).scalar_one() == 1
    finally:
        with engine.begin() as connection:
            if membership_existed is False:
                connection.execute(
                    text(f"revoke {MAINTENANCE_ROLE} from {admin_role}")
                )
            if role_existed is False:
                connection.execute(text(f"drop role {admin_role}"))
            current = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        if current != HEAD:
            command.upgrade(config, "head")
        engine.dispose()


def test_client_access_is_revoked_before_noinherit_function_owner_transfer(
    database_url,
    migrated_engine,
    monkeypatch,
):
    del migrated_engine  # ensure the session-scoped migrated database exists
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    migration_role = f"rls_migration_owner_{uuid4().hex}"
    client_role = "anon"
    migration_path = (
        REPOSITORY_ROOT
        / "database"
        / "migrations"
        / "versions"
        / "0012_rls_and_security.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0012_for_test", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    command.downgrade(config, "0011a_account_deletion")
    original_schema_owner = None
    original_function_owner = None
    original_table_owners = []
    client_role_existed = None
    client_execute_existed = None

    try:
        with engine.begin() as connection:
            original_schema_owner = connection.execute(
                text(
                    "select pg_get_userbyid(nspowner) "
                    "from pg_namespace where nspname = 'public'"
                )
            ).scalar_one()
            original_function_owner = connection.execute(
                text(
                    """
                    select pg_get_userbyid(p.proowner)
                    from pg_proc p
                    join pg_namespace n on n.oid = p.pronamespace
                    where n.nspname = 'public'
                      and p.proname = 'maintenance_delete_account'
                    """
                )
            ).scalar_one()
            client_role_existed = connection.execute(
                text("select 1 from pg_roles where rolname = :role"),
                {"role": client_role},
            ).scalar_one_or_none() is not None
            if not client_role_existed:
                connection.execute(text(f"create role {client_role} nologin"))
            client_execute_existed = connection.execute(
                text(
                    "select has_function_privilege("
                    ":role, 'public.maintenance_delete_account(uuid)', 'EXECUTE')"
                ),
                {"role": client_role},
            ).scalar_one()

            connection.execute(text(f"create role {migration_role} noinherit nologin"))
            original_table_owners = connection.execute(
                text(
                    """
                    select c.relname, pg_get_userbyid(c.relowner)
                    from pg_class c
                    join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = 'public' and c.relkind in ('r', 'p')
                    """
                )
            ).all()
            for table_name, _owner_name in original_table_owners:
                table = connection.dialect.identifier_preparer.quote(table_name)
                connection.execute(
                    text(f"alter table public.{table} owner to {migration_role}")
                )
            connection.execute(
                text(f"grant {MAINTENANCE_ROLE} to {migration_role}")
            )
            connection.execute(text(f"alter schema public owner to {migration_role}"))
            connection.execute(
                text(
                    "alter function public.maintenance_delete_account(uuid) "
                    f"owner to {migration_role}"
                )
            )
            connection.execute(
                text(
                    "grant execute on function "
                    "public.maintenance_delete_account(uuid) to anon"
                )
            )

        with engine.begin() as connection:
            connection.execute(text(f"set local role {migration_role}"))
            monkeypatch.setattr(
                migration,
                "op",
                Operations(MigrationContext.configure(connection)),
            )
            monkeypatch.setattr(migration, "_verify_runtime_roles", lambda bind: None)
            monkeypatch.setattr(migration, "_harden_schema", lambda: None)
            monkeypatch.setattr(migration, "_grant_canonical_read", lambda: None)
            monkeypatch.setattr(migration, "_grant_identity", lambda: None)
            monkeypatch.setattr(migration, "_grant_backend", lambda: None)
            monkeypatch.setattr(migration, "_grant_worker", lambda: None)
            monkeypatch.setattr(migration, "_grant_maintenance", lambda: None)
            monkeypatch.setattr(migration, "_enable_rls", lambda: None)
            monkeypatch.setattr(
                migration,
                "_harden_default_privileges",
                lambda bind: None,
            )
            migration.upgrade()

        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "select has_function_privilege("
                    ":role, 'public.maintenance_delete_account(uuid)', 'EXECUTE')"
                ),
                {"role": client_role},
            ).scalar_one() is False
    finally:
        with engine.begin() as connection:
            connection.execute(text("reset role"))
            if original_function_owner is not None:
                owner = connection.dialect.identifier_preparer.quote(
                    original_function_owner
                )
                connection.execute(
                    text(
                        "alter function public.maintenance_delete_account(uuid) "
                        f"owner to {owner}"
                    )
                )
            connection.execute(
                text(
                    "revoke execute on function "
                    "public.maintenance_delete_account(uuid) from app_worker"
                )
            )
            if client_role_existed is True and client_execute_existed is True:
                connection.execute(
                    text(
                        "grant execute on function "
                        "public.maintenance_delete_account(uuid) to anon"
                    )
                )
            elif client_role_existed is not None:
                connection.execute(
                    text(
                        "revoke execute on function "
                        "public.maintenance_delete_account(uuid) from anon"
                    )
                )
            for table_name, owner_name in original_table_owners:
                table = connection.dialect.identifier_preparer.quote(table_name)
                owner = connection.dialect.identifier_preparer.quote(owner_name)
                connection.execute(
                    text(f"alter table public.{table} owner to {owner}")
                )
            if original_schema_owner is not None:
                owner = connection.dialect.identifier_preparer.quote(
                    original_schema_owner
                )
                connection.execute(text(f"alter schema public owner to {owner}"))
            connection.execute(
                text(f"revoke {MAINTENANCE_ROLE} from {migration_role}")
            )
            connection.execute(text(f"drop role {migration_role}"))
            if client_role_existed is False:
                connection.execute(text("drop role anon"))
        command.upgrade(config, "head")
        engine.dispose()


def test_upgrade_revokes_preexisting_supabase_client_access(
    database_url,
    migrated_engine,
):
    del migrated_engine  # ensure the session-scoped migrated database exists
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    created_roles: list[str] = []
    command.downgrade(config, "0011a_account_deletion")

    try:
        with engine.begin() as connection:
            for role in CLIENT_ROLES:
                exists = connection.execute(
                    text("select 1 from pg_roles where rolname = :role"),
                    {"role": role},
                ).scalar_one_or_none()
                if exists is None:
                    connection.execute(text(f"create role {role} nologin"))
                    created_roles.append(role)
                connection.execute(
                    text(
                        f"grant select on public.learner_preferences to {role}"
                    )
                )
                connection.execute(
                    text(f"grant create on schema public to {role}")
                )
                connection.execute(
                    text(
                        f"grant execute on function {MAINTENANCE_FUNCTION}(uuid) "
                        f"to {role}"
                    )
                )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            for role in CLIENT_ROLES:
                assert connection.execute(
                    text(
                        "select has_table_privilege("
                        ":role, 'public.learner_preferences', 'SELECT')"
                    ),
                    {"role": role},
                ).scalar_one() is False
                assert connection.execute(
                    text(
                        "select has_schema_privilege("
                        ":role, 'public', 'CREATE')"
                    ),
                    {"role": role},
                ).scalar_one() is False
                assert connection.execute(
                    text(
                        "select has_function_privilege("
                        ":role, "
                        "'public.maintenance_delete_account(uuid)', "
                        "'EXECUTE')"
                    ),
                    {"role": role},
                ).scalar_one() is False
    finally:
        with engine.begin() as connection:
            for role in CLIENT_ROLES:
                connection.execute(
                    text(
                        f"revoke all on public.learner_preferences from {role}"
                    )
                )
                connection.execute(
                    text(f"revoke create on schema public from {role}")
                )
                connection.execute(
                    text(
                        f"revoke all on function {MAINTENANCE_FUNCTION}(uuid) "
                        f"from {role}"
                    )
                )
            for role in created_roles:
                connection.execute(text(f"drop role {role}"))
            current = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        if current != HEAD:
            command.upgrade(config, "head")
        engine.dispose()


def test_upgrade_revokes_preexisting_untrusted_function_executor(
    database_url,
    migrated_engine,
):
    del migrated_engine  # ensure the session-scoped migrated database exists
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    untrusted_role = f"rls_untrusted_executor_{uuid4().hex}"
    role_created = False

    try:
        command.downgrade(config, "0011a_account_deletion")
        with engine.begin() as connection:
            connection.execute(text(f"create role {untrusted_role} nologin"))
            role_created = True
            connection.execute(
                text(
                    "grant execute on function "
                    f"{MAINTENANCE_FUNCTION}(uuid) to {untrusted_role}"
                )
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "select has_function_privilege("
                    ":role, 'public.maintenance_delete_account(uuid)', "
                    "'EXECUTE')"
                ),
                {"role": untrusted_role},
            ).scalar_one() is False
    finally:
        with engine.begin() as connection:
            if role_created:
                connection.execute(
                    text(
                        "revoke all on function "
                        f"{MAINTENANCE_FUNCTION}(uuid) from {untrusted_role}"
                    )
                )
                connection.execute(text(f"drop role {untrusted_role}"))
            current = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        if current != HEAD:
            command.upgrade(config, "head")
        engine.dispose()


@pytest.mark.parametrize(
    ("missing_role", "attributes"),
    (
        (BACKEND_ROLE, "nologin nobypassrls"),
        (WORKER_ROLE, "nologin bypassrls"),
        (MAINTENANCE_ROLE, "nologin bypassrls"),
    ),
)
def test_upgrade_aborts_when_required_runtime_role_is_missing(
    database_url,
    migrated_engine,
    missing_role,
    attributes,
):
    del migrated_engine  # ensure the session-scoped migrated database exists
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    command.downgrade(config, "0011a_account_deletion")

    try:
        with engine.begin() as connection:
            connection.execute(text(f"drop role {missing_role}"))

        with pytest.raises(RuntimeError, match=f"missing: {missing_role}"):
            command.upgrade(config, "head")

        with engine.connect() as connection:
            assert connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one() == "0011a_account_deletion"
            assert connection.execute(
                text("select count(*) from pg_policies where schemaname = 'public'")
            ).scalar_one() == 0
    finally:
        with engine.begin() as connection:
            exists = connection.execute(
                text("select 1 from pg_roles where rolname = :role"),
                {"role": missing_role},
            ).scalar_one_or_none()
            if exists is None:
                connection.execute(
                    text(f"create role {missing_role} {attributes}")
                )
            current = connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one()
        if current != HEAD:
            command.upgrade(config, "head")
        engine.dispose()


def test_public_has_no_create_on_public_schema(migrated_connection):
    privileges = {
        row.privilege_type
        for row in migrated_connection.execute(
            text(
                """
                select acl.privilege_type
                from pg_namespace n, aclexplode(n.nspacl) acl
                where n.nspname = 'public' and acl.grantee = 0
                """
            )
        ).all()
    }

    assert "CREATE" not in privileges


def test_client_roles_have_no_privileges_on_application_tables(migrated_connection):
    tables = ["app_users", *LEARNER_TABLES, *CANONICAL_TABLES]
    rows = migrated_connection.execute(
        text(
            """
            select c.relname, acl.grantee::regrole::text as grantee
            from pg_class c
            join pg_namespace n on n.oid = c.relnamespace
            cross join lateral aclexplode(c.relacl) acl
            where n.nspname = 'public' and c.relname = any(:tables)
            """
        ),
        {"tables": tables},
    ).all()

    offenders = [row for row in rows if row.grantee in CLIENT_ROLES]
    assert offenders == [], f"client roles must have no table privileges: {offenders}"


def test_backend_operational_grants_follow_matrix(migrated_connection):
    for table in BACKEND_FULL_DML:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _has_table_privilege(
                migrated_connection, BACKEND_ROLE, table, privilege
            ) is True, f"{table}.{privilege}"

    for table in BACKEND_INSERT_SELECT:
        assert _has_table_privilege(
            migrated_connection, BACKEND_ROLE, table, "SELECT"
        ) is True, table
        assert _has_table_privilege(
            migrated_connection, BACKEND_ROLE, table, "INSERT"
        ) is True, table
        for privilege in ("UPDATE", "DELETE"):
            assert _has_table_privilege(
                migrated_connection, BACKEND_ROLE, table, privilege
            ) is False, f"{table}.{privilege}"

    for table in BACKEND_SELECT_INSERT_UPDATE:
        for privilege in ("SELECT", "INSERT", "UPDATE"):
            assert _has_table_privilege(
                migrated_connection, BACKEND_ROLE, table, privilege
            ) is True, f"{table}.{privilege}"
        assert _has_table_privilege(
            migrated_connection, BACKEND_ROLE, table, "DELETE"
        ) is False, table

    for table in BACKEND_SELECT_ONLY:
        assert _has_table_privilege(
            migrated_connection, BACKEND_ROLE, table, "SELECT"
        ) is True, table
        for privilege in ("INSERT", "UPDATE", "DELETE"):
            assert _has_table_privilege(
                migrated_connection, BACKEND_ROLE, table, privilege
            ) is False, f"{table}.{privilege}"


def test_backend_app_users_grants_exclude_delete(migrated_connection):
    for privilege in ("SELECT", "INSERT", "UPDATE"):
        assert _has_table_privilege(
            migrated_connection, BACKEND_ROLE, "app_users", privilege
        ) is True, privilege
    assert _has_table_privilege(
        migrated_connection, BACKEND_ROLE, "app_users", "DELETE"
    ) is False


def test_canonical_tables_are_read_only_for_runtime_roles(migrated_connection):
    for table in CANONICAL_TABLES:
        for role in (BACKEND_ROLE, WORKER_ROLE):
            assert _has_table_privilege(
                migrated_connection, role, table, "SELECT"
            ) is True, f"{role}.{table}"
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert _has_table_privilege(
                    migrated_connection, role, table, privilege
                ) is False, f"{role}.{table}.{privilege}"


def test_maintenance_has_table_select_and_delete_only(migrated_connection):
    for table in [*LEARNER_TABLES, "app_users"]:
        assert _has_table_privilege(
            migrated_connection, MAINTENANCE_ROLE, table, "SELECT"
        ) is True, table
        assert _has_table_privilege(
            migrated_connection, MAINTENANCE_ROLE, table, "DELETE"
        ) is True, table
        for privilege in ("INSERT", "UPDATE"):
            assert _has_table_privilege(
                migrated_connection, MAINTENANCE_ROLE, table, privilege
            ) is False, f"{table}.{privilege}"


# ---------------------------------------------------------------------------
# backend isolation behaviour
# ---------------------------------------------------------------------------


def test_backend_reads_only_own_rows(migrated_connection):
    user_a = _insert_user(migrated_connection)
    user_b = _insert_user(migrated_connection)
    _insert_preference(migrated_connection, user_a)
    _insert_preference(migrated_connection, user_b)

    _as_role(migrated_connection, BACKEND_ROLE)
    _set_user(migrated_connection, user_a)

    assert _count(migrated_connection, "learner_preferences", user_a) == 1
    assert _count(migrated_connection, "learner_preferences", user_b) == 0
    _reset_role(migrated_connection)


def test_backend_cross_user_insert_is_rejected(migrated_connection):
    user_a = _insert_user(migrated_connection)
    user_b = _insert_user(migrated_connection)

    _as_role(migrated_connection, BACKEND_ROLE)
    _set_user(migrated_connection, user_a)

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        _insert_preference(migrated_connection, user_b)

    assert error.value.orig.sqlstate == "42501"
    _reset_role(migrated_connection)


def test_backend_cross_user_update_and_delete_affect_no_rows(migrated_connection):
    user_a = _insert_user(migrated_connection)
    user_b = _insert_user(migrated_connection)
    _insert_preference(migrated_connection, user_b)

    _as_role(migrated_connection, BACKEND_ROLE)
    _set_user(migrated_connection, user_a)

    updated = migrated_connection.execute(
        text(
            "update learner_preferences set version = version + 1 "
            "where user_id = :user_id"
        ),
        {"user_id": user_b},
    ).rowcount
    deleted = migrated_connection.execute(
        text("delete from learner_preferences where user_id = :user_id"),
        {"user_id": user_b},
    ).rowcount

    assert updated == 0
    assert deleted == 0
    _reset_role(migrated_connection)
    assert _count(migrated_connection, "learner_preferences", user_b) == 1


def test_backend_empty_or_absent_user_context_fails_closed(migrated_connection):
    user = _insert_user(migrated_connection)
    _insert_preference(migrated_connection, user)

    _as_role(migrated_connection, BACKEND_ROLE)
    # Absent context: NULLIF yields NULL and the policy denies without error.
    assert migrated_connection.execute(
        text("select count(*) from learner_preferences")
    ).scalar_one() == 0
    # Empty context: the NULLIF form must not raise a uuid cast error.
    migrated_connection.execute(
        text("select set_config('app.user_id', '', true)")
    )
    assert migrated_connection.execute(
        text("select count(*) from learner_preferences")
    ).scalar_one() == 0
    # RESET after a valid SET produces PostgreSQL's empty custom setting and
    # must return to the same fail-closed behavior.
    _set_user(migrated_connection, user)
    assert migrated_connection.execute(
        text("select count(*) from learner_preferences")
    ).scalar_one() == 1
    migrated_connection.execute(text("reset app.user_id"))
    assert migrated_connection.execute(
        text("select count(*) from learner_preferences")
    ).scalar_one() == 0
    # Malformed non-empty context still fails closed with an error.
    migrated_connection.execute(
        text("select set_config('app.user_id', 'not-a-uuid', true)")
    )
    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text("select count(*) from learner_preferences")
        )
    assert error.value.orig.sqlstate == "22P02"
    _reset_role(migrated_connection)


def test_backend_cannot_write_canonical_corpus(migrated_connection):
    _as_role(migrated_connection, BACKEND_ROLE)

    # Reads remain available.
    assert migrated_connection.execute(
        text("select count(*) from learning_entities")
    ).scalar_one() >= 0

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text(
                "insert into learning_entities (canonical_key, entity_type, status) "
                "values (:key, 'TOPIC', 'REVIEWED')"
            ),
            {"key": f"denied-{uuid4()}"},
        )

    assert error.value.orig.sqlstate == "42501"
    _reset_role(migrated_connection)


def test_backend_cannot_write_derived_learner_state(migrated_connection):
    user = _insert_user(migrated_connection)
    entity = _insert_entity(migrated_connection)

    _as_role(migrated_connection, BACKEND_ROLE)
    _set_user(migrated_connection, user)

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text(
                "insert into learner_interest_state (user_id, entity_id, model_version) "
                "values (:user_id, :entity_id, 1)"
            ),
            {"user_id": user, "entity_id": entity},
        )

    assert error.value.orig.sqlstate == "42501"
    _reset_role(migrated_connection)


# ---------------------------------------------------------------------------
# worker boundary behaviour
# ---------------------------------------------------------------------------


def test_worker_sees_cross_user_rows(migrated_connection):
    user_a = _insert_user(migrated_connection)
    user_b = _insert_user(migrated_connection)
    _insert_event(migrated_connection, user_a)
    _insert_event(migrated_connection, user_b)

    _as_role(migrated_connection, WORKER_ROLE)
    assert migrated_connection.execute(
        text("select count(*) from learning_events")
    ).scalar_one() == 2
    _reset_role(migrated_connection)


def test_worker_can_claim_cross_user_job(migrated_connection):
    user = _insert_user(migrated_connection)
    job = _insert_job(migrated_connection, user)

    _as_role(migrated_connection, WORKER_ROLE)
    updated = migrated_connection.execute(
        text(
            "update jobs set status = 'RUNNING', locked_at = now(), "
            "locked_by = 'test-worker' where id = :job_id"
        ),
        {"job_id": job},
    ).rowcount
    assert updated == 1
    _reset_role(migrated_connection)


def test_worker_cannot_mutate_immutable_ledger_even_when_granted(migrated_connection):
    user = _insert_user(migrated_connection)
    _insert_event(migrated_connection, user)

    migrated_connection.execute(
        text(f"grant update on learning_events to {WORKER_ROLE}")
    )

    _as_role(migrated_connection, WORKER_ROLE)
    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text("update learning_events set schema_version = 2")
        )

    assert error.value.orig.sqlstate == "55000"
    assert (
        error.value.orig.diag.constraint_name == "ck_learning_events_immutable"
    )
    _reset_role(migrated_connection)


def test_worker_cannot_delete_immutable_history_by_default(migrated_connection):
    user = _insert_user(migrated_connection)
    _insert_event(migrated_connection, user)

    _as_role(migrated_connection, WORKER_ROLE)
    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text("delete from learning_events where user_id = :user_id"),
            {"user_id": user},
        )
    assert error.value.orig.sqlstate == "42501"
    _reset_role(migrated_connection)


# ---------------------------------------------------------------------------
# maintenance function activation
# ---------------------------------------------------------------------------


def test_backend_cannot_execute_maintenance_function(migrated_connection):
    _as_role(migrated_connection, BACKEND_ROLE)

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text(f"select {MAINTENANCE_FUNCTION}(:user_id)"),
            {"user_id": str(uuid4())},
        )

    assert error.value.orig.sqlstate == "42501"
    _reset_role(migrated_connection)


def test_public_has_no_execute_on_maintenance_function(migrated_connection):
    acl = migrated_connection.execute(
        text(
            """
            select p.proacl::text
            from pg_proc p
            join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public'
              and p.proname = 'maintenance_delete_account'
            """
        )
    ).scalar_one()

    # A NULL ACL means PostgreSQL's default, which grants EXECUTE to PUBLIC.
    assert acl is not None, "maintenance function must not carry default ACLs"
    public_execute = migrated_connection.execute(
        text(
            """
            select count(*)
            from pg_proc p
            join pg_namespace n on n.oid = p.pronamespace,
            aclexplode(p.proacl) acl
            where n.nspname = 'public'
              and p.proname = 'maintenance_delete_account'
              and acl.grantee = 0
              and acl.privilege_type = 'EXECUTE'
            """
        )
    ).scalar_one()

    assert public_execute == 0


def test_worker_can_execute_maintenance_deletion_under_active_rls(migrated_connection):
    user_a = _insert_user(migrated_connection)
    user_b = _insert_user(migrated_connection)
    _insert_preference(migrated_connection, user_a)
    _insert_preference(migrated_connection, user_b)
    _insert_event(migrated_connection, user_b)

    _as_role(migrated_connection, WORKER_ROLE)
    migrated_connection.execute(
        text(f"select {MAINTENANCE_FUNCTION}(:user_id)"),
        {"user_id": user_b},
    )
    _reset_role(migrated_connection)

    assert migrated_connection.execute(
        text("select count(*) from app_users where id = :user_id"),
        {"user_id": user_b},
    ).scalar_one() == 0
    assert _count(migrated_connection, "learner_preferences", user_b) == 0
    assert _count(migrated_connection, "learning_events", user_b) == 0
    assert migrated_connection.execute(
        text("select count(*) from app_users where id = :user_id"),
        {"user_id": user_a},
    ).scalar_one() == 1
    assert _count(migrated_connection, "learner_preferences", user_a) == 1


# ---------------------------------------------------------------------------
# default privileges
# ---------------------------------------------------------------------------


def test_default_privileges_strip_public_execute_on_new_functions(
    migrated_connection,
):
    migrated_connection.execute(
        text(
            "create function public._rls_default_probe() returns int "
            "language sql as 'select 1'"
        )
    )
    public_can_execute = migrated_connection.execute(
        text(
            "select has_function_privilege("
            ":role, 'public._rls_default_probe()', 'EXECUTE')"
        ),
        {"role": BACKEND_ROLE},
    ).scalar_one()

    owner_oid, owner_name = migrated_connection.execute(
        text(
            """
            select c.relowner, pg_get_userbyid(c.relowner)
            from pg_class c
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relname = 'app_users'
            """
        )
    ).one()
    public_global_default = migrated_connection.execute(
        text(
            """
            select count(*)
            from pg_default_acl d,
                 aclexplode(d.defaclacl) acl
            where d.defaclrole = :owner_oid
              and d.defaclnamespace = 0
              and d.defaclobjtype = 'f'
              and acl.grantee = 0
              and acl.privilege_type = 'EXECUTE'
            """
        ),
        {"owner_oid": owner_oid},
    ).scalar_one()
    marker = migrated_connection.execute(
        text(
            """
            select obj_description(p.oid, 'pg_policy')
            from pg_policy p
            join pg_class c on c.oid = p.polrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public'
              and c.relname = 'user_devices'
              and p.polname = 'user_devices_user_policy'
            """
        )
    ).scalar_one()

    assert public_can_execute is False
    assert public_global_default == 0
    assert json.loads(marker) == {
        "creator_role": owner_name,
        "global_public_execute": True,
        "revision": "0012_rls_and_security",
        "schema_public_execute": False,
    }


def test_downgrade_preserves_preexisting_hardened_function_defaults(
    database_url,
    migrated_engine,
):
    del migrated_engine  # ensure the session-scoped migrated database exists
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    command.downgrade(config, "0011a_account_deletion")

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "alter default privileges revoke execute on functions "
                    "from public"
                )
            )
            connection.execute(
                text(
                    "alter default privileges in schema public revoke execute "
                    "on functions from public"
                )
            )

        command.upgrade(config, "head")
        command.downgrade(config, "0011a_account_deletion")

        with engine.begin() as connection:
            connection.execute(
                text(
                    "create function public._rls_downgrade_default_probe() "
                    "returns int language sql as 'select 1'"
                )
            )
            assert connection.execute(
                text(
                    "select has_function_privilege("
                    ":role, 'public._rls_downgrade_default_probe()', 'EXECUTE')"
                ),
                {"role": BACKEND_ROLE},
            ).scalar_one() is False
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "drop function if exists "
                    "public._rls_downgrade_default_probe()"
                )
            )
            connection.execute(
                text(
                    "alter default privileges grant execute on functions "
                    "to public"
                )
            )
            connection.execute(
                text(
                    "alter default privileges in schema public revoke execute "
                    "on functions from public"
                )
            )
        command.upgrade(config, "head")
        engine.dispose()


# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------


def test_downgrade_to_0011a_removes_security_and_upgrade_restores(database_url):
    config = _alembic_config(database_url)
    command.downgrade(config, "0011a_account_deletion")

    try:
        with create_engine(database_url).connect() as connection:
            policies = connection.execute(
                text("select count(*) from pg_policies where schemaname = 'public'")
            ).scalar_one()
            assert policies == 0

            rls = connection.execute(
                text(
                    """
                    select count(*) from pg_class c
                    join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = 'public'
                      and c.relname = any(:tables)
                      and (c.relrowsecurity or c.relforcerowsecurity)
                    """
                ),
                {"tables": list(LEARNER_TABLES)},
            ).scalar_one()
            assert rls == 0

            owner = connection.execute(
                text(
                    """
                    select pg_get_userbyid(p.proowner)
                    from pg_proc p
                    join pg_namespace n on n.oid = p.pronamespace
                    where n.nspname = 'public'
                      and p.proname = 'maintenance_delete_account'
                    """
                )
            ).scalar_one()
            assert owner != MAINTENANCE_ROLE
            assert connection.execute(
                text(
                    "select has_table_privilege("
                    ":role, 'public.learner_preferences', 'SELECT')"
                ),
                {"role": BACKEND_ROLE},
            ).scalar_one() is False
            connection.execute(
                text(
                    "create function public._rls_downgrade_restore_probe() "
                    "returns int language sql as 'select 1'"
                )
            )
            assert connection.execute(
                text(
                    "select has_function_privilege("
                    ":role, 'public._rls_downgrade_restore_probe()', 'EXECUTE')"
                ),
                {"role": BACKEND_ROLE},
            ).scalar_one() is True
    finally:
        command.upgrade(config, "head")

    with create_engine(database_url).connect() as connection:
        assert connection.execute(
            text("select count(*) from pg_policies where schemaname = 'public'")
        ).scalar_one() == len(LEARNER_TABLES)
        owner = connection.execute(
            text(
                """
                select pg_get_userbyid(p.proowner)
                from pg_proc p
                join pg_namespace n on n.oid = p.pronamespace
                where n.nspname = 'public'
                  and p.proname = 'maintenance_delete_account'
                """
            )
        ).scalar_one()
        assert owner == MAINTENANCE_ROLE
