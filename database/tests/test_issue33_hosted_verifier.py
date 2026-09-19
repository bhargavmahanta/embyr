"""Tests for the authoritative Issue #33 hosted security verifier.

These tests exercise the verifier's inventory constants, privilege matrix,
default-ACL logic (including implicit PUBLIC EXECUTE), expected-SQLSTATE harness,
guaranteed temporary-grant cleanup, fixture lifecycle, final zero-data gate, and
complete orphan verification against a real disposable PostgreSQL 17 database.
No PostgreSQL security semantics are mocked.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPOSITORY_ROOT / "database" / "tools" / "issue33_hosted_verifier.py"
ALEMBIC_INI = REPOSITORY_ROOT / "database" / "alembic.ini"


def _load_verifier():
    assert VERIFIER_PATH.exists(), f"verifier not found at {VERIFIER_PATH}"
    spec = importlib.util.spec_from_file_location("issue33_hosted_verifier", VERIFIER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier():
    return _load_verifier()


def _psycopg_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def admin_conn(database_url):
    """Autocommit psycopg connection as the migration owner (superuser)."""
    with psycopg.connect(_psycopg_url(database_url), autocommit=True) as conn:
        yield conn


@pytest.fixture
def clean_application_data(migrated_engine, verifier):
    """Isolate tests that assert global application-table emptiness.

    The session-scoped migrated database may hold rows committed by other test
    files. This truncates all 45 Embyr application tables as superuser with FK
    enforcement disabled for the statement only; it never touches hosted.
    """
    with migrated_engine.begin() as conn:
        conn.execute(text("set local session_replication_role = replica"))
        for table in verifier.FINAL_0013_APPLICATION_TABLES:
            conn.execute(text(f'truncate table public."{table}" cascade'))
    yield


@pytest.fixture(scope="module")
def client_roles(database_url):
    """Ensure the Supabase client roles exist; drop only those we created."""
    created: list[str] = []
    engine = create_engine(database_url)
    with engine.begin() as conn:
        for role in ("anon", "authenticated", "service_role"):
            exists = conn.execute(
                text("select 1 from pg_roles where rolname = :role"), {"role": role}
            ).scalar_one_or_none()
            if exists is None:
                conn.execute(text(f"create role {role} nologin"))
                created.append(role)
    yield
    with engine.begin() as conn:
        for role in created:
            conn.execute(text(f"drop role if exists {role}"))
    engine.dispose()


# ---------------------------------------------------------------------------
# Issue #33 hardening pass 2 fixtures (Findings 1-5)
# ---------------------------------------------------------------------------

LEGACY_REVISION = "0006_practical_artifacts"
LEGACY_DB_NAME = "embyr_p33_legacy_test"
# The frozen hosted role contract (provisioning/supabase_roles.sql). The shared
# test harness provisions runtime roles NOLOGIN for convenience, so the legacy
# fixture converges them and the teardown restores the harness state.
LEGACY_ROLE_ATTRIBUTES = {
    "app_backend": "login nobypassrls nocreaterole nocreatedb noreplication",
    "app_worker": "login bypassrls nocreaterole nocreatedb noreplication",
    "app_maintenance": "nologin bypassrls nocreaterole nocreatedb noreplication",
    "app_owner": "login nosuperuser nobypassrls nocreaterole nocreatedb "
    "noreplication",
}
HARNESS_ROLE_ATTRIBUTES = {
    "app_backend": "nologin nobypassrls",
    "app_worker": "nologin bypassrls",
    "app_maintenance": "nologin bypassrls",
    "app_owner": "login nobypassrls",
}
LEGACY_ROLE_COLUMNS = (
    "rolcanlogin",
    "rolsuper",
    "rolbypassrls",
    "rolcreaterole",
    "rolcreatedb",
    "rolreplication",
)


def _restore_role_attributes(engine) -> None:
    with engine.begin() as conn:
        for role, attributes in HARNESS_ROLE_ATTRIBUTES.items():
            exists = conn.execute(
                text("select 1 from pg_roles where rolname = :role"), {"role": role}
            ).scalar_one_or_none()
            if exists is not None:
                conn.execute(text(f"alter role {role} with {attributes}"))


POLICY_USER_A = "33333333-3333-3333-3333-333333333333"
POLICY_USER_B = "44444444-4444-4444-4444-444444444444"


def _alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.fixture(scope="module")
def legacy_engine(database_url, verifier, client_roles):
    """A disposable database migrated to the legacy ``0006`` hosted state.

    Preflight is a gate on the *starting* state, so exercising it requires a
    database genuinely at ``0006_practical_artifacts`` with the frozen hosted
    extension layout (``vector`` in ``public``, ``pgcrypto`` in ``extensions``).
    The fixture explicitly converges the ``app_owner -> app_maintenance``
    membership to the frozen ``ADMIN=false / INHERIT=false / SET=true`` state
    and restores whatever existed before it ran.
    """
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    base = database_url.rsplit("/", 1)[0]
    legacy_url = f"{base}/{LEGACY_DB_NAME}"
    with admin.connect() as conn:
        conn.execute(text(f"drop database if exists {LEGACY_DB_NAME} with (force)"))
        conn.execute(text(f"create database {LEGACY_DB_NAME}"))
    engine = create_engine(legacy_url)
    prior_membership = verifier.capture_owner_membership(engine)
    with engine.begin() as conn:
        for role, attributes in LEGACY_ROLE_ATTRIBUTES.items():
            exists = conn.execute(
                text("select 1 from pg_roles where rolname = :role"), {"role": role}
            ).scalar_one_or_none()
            if exists is None:
                conn.execute(text(f"create role {role} {attributes}"))
            else:
                conn.execute(text(f"alter role {role} with {attributes}"))
        conn.execute(
            text(
                "grant usage, create on schema public to app_owner "
                "with grant option"
            )
        )
    verifier.apply_owner_membership(
        engine, verifier.MembershipState(exists=True, admin=False, inherit=False, set=True)
    )
    command.upgrade(_alembic_config(legacy_url), LEGACY_REVISION)
    with engine.begin() as conn:
        conn.execute(text("create schema if not exists extensions"))
        conn.execute(text("alter extension pgcrypto set schema extensions"))
    try:
        yield engine
    finally:
        verifier.apply_owner_membership(engine, prior_membership)
        _restore_role_attributes(engine)
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(
                text(f"drop database if exists {LEGACY_DB_NAME} with (force)")
            )
        admin.dispose()


# ---------------------------------------------------------------------------
# 1-5: inventory constants
# ---------------------------------------------------------------------------


def test_legacy_inventory_has_29_unique_entries(verifier):
    tables = verifier.LEGACY_0006_APPLICATION_TABLES
    assert len(tables) == 29
    assert len(set(tables)) == 29


def test_final_inventory_has_45_unique_entries(verifier):
    tables = verifier.FINAL_0013_APPLICATION_TABLES
    assert len(tables) == 45
    assert len(set(tables)) == 45
    assert "alembic_version" not in tables


def test_rls_inventory_has_34_unique_entries(verifier):
    tables = verifier.RLS_LEARNER_TABLES
    assert len(tables) == 34
    assert len(set(tables)) == 34


def test_final_inventory_matches_migration_application_relations(verifier):
    from app.db.base import Base
    from app.db import models  # noqa: F401

    assert set(verifier.FINAL_0013_APPLICATION_TABLES) == set(Base.metadata.tables)
    assert set(verifier.LEGACY_0006_APPLICATION_TABLES) <= set(
        verifier.FINAL_0013_APPLICATION_TABLES
    )
    assert set(verifier.RLS_LEARNER_TABLES) <= set(
        verifier.FINAL_0013_APPLICATION_TABLES
    )


def test_all_eight_pg17_table_privileges_enumerated(verifier):
    assert set(verifier.PG17_TABLE_PRIVILEGES) == {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "REFERENCES",
        "TRIGGER",
        "MAINTAIN",
    }
    assert len(verifier.PG17_TABLE_PRIVILEGES) == 8


def test_pg16_table_privileges_are_seven_without_maintain(verifier):
    expected = {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "REFERENCES",
        "TRIGGER",
    }
    assert set(verifier.PG16_TABLE_PRIVILEGES) == expected
    assert "MAINTAIN" not in verifier.PG16_TABLE_PRIVILEGES
    assert verifier.PG16_TABLE_PRIVILEGES == verifier.PG17_TABLE_PRIVILEGES[:-1]


def test_supported_table_privileges_pg16_branch(
    monkeypatch, migrated_engine, verifier
):
    monkeypatch.setattr(verifier, "server_version_num", lambda obj: 160010)
    selected = verifier.supported_table_privileges(migrated_engine)
    assert selected == verifier.PG16_TABLE_PRIVILEGES
    assert "MAINTAIN" not in selected


def test_supported_table_privileges_pg17_branch(
    monkeypatch, migrated_engine, verifier
):
    monkeypatch.setattr(verifier, "server_version_num", lambda obj: 170006)
    selected = verifier.supported_table_privileges(migrated_engine)
    assert selected == verifier.PG17_TABLE_PRIVILEGES
    assert "MAINTAIN" in selected


def test_supported_table_privileges_matches_live_server(
    migrated_engine, verifier
):
    version = verifier.server_version_num(migrated_engine)
    selected = verifier.supported_table_privileges(migrated_engine)
    if version >= 170000:
        assert selected == verifier.PG17_TABLE_PRIVILEGES
        assert "MAINTAIN" in selected
    else:
        assert selected == verifier.PG16_TABLE_PRIVILEGES
        assert "MAINTAIN" not in selected


# ---------------------------------------------------------------------------
# 6-7: client privilege matrix detection
# ---------------------------------------------------------------------------


def test_client_privilege_matrix_clean(migrated_engine, verifier, client_roles):
    violations = verifier.client_privilege_violations(migrated_engine)
    assert violations == []


def test_client_privilege_matrix_detects_injected_select(
    migrated_engine, verifier, client_roles
):
    with migrated_engine.begin() as conn:
        conn.execute(text("grant select on public.learner_preferences to anon"))
    try:
        violations = verifier.client_privilege_violations(migrated_engine)
        assert any(v.role == "anon" and v.table == "learner_preferences"
                   and v.privilege == "SELECT" for v in violations)
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(text("revoke select on public.learner_preferences from anon"))
    assert verifier.client_privilege_violations(migrated_engine) == []


def test_client_privilege_matrix_detects_injected_non_select(
    migrated_engine, verifier, client_roles
):
    with migrated_engine.begin() as conn:
        conn.execute(
            text("grant insert, trigger on public.learner_preferences to authenticated")
        )
    try:
        violations = verifier.client_privilege_violations(migrated_engine)
        found = {(v.role, v.table, v.privilege) for v in violations}
        assert ("authenticated", "learner_preferences", "INSERT") in found
        assert ("authenticated", "learner_preferences", "TRIGGER") in found
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "revoke insert, trigger on public.learner_preferences "
                    "from authenticated"
                )
            )
    assert verifier.client_privilege_violations(migrated_engine) == []


def test_client_privilege_matrix_detects_injected_maintain(
    migrated_engine, verifier, client_roles
):
    """PG17 genuinely exercises MAINTAIN; PG16 cannot issue the query."""
    if verifier.server_version_num(migrated_engine) < 170000:
        pytest.skip("MAINTAIN is a PostgreSQL 17 privilege")
    with migrated_engine.begin() as conn:
        conn.execute(
            text("grant maintain on public.learner_preferences to anon")
        )
    try:
        violations = verifier.client_privilege_violations(migrated_engine)
        assert any(
            v.role == "anon"
            and v.table == "learner_preferences"
            and v.privilege == "MAINTAIN"
            for v in violations
        ), violations
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(
                text("revoke maintain on public.learner_preferences from anon")
            )
    assert verifier.client_privilege_violations(migrated_engine) == []


# ---------------------------------------------------------------------------
# 8-10: default ACL, implicit PUBLIC, explicit PUBLIC
# ---------------------------------------------------------------------------


def test_default_acl_clean_state(migrated_engine, verifier, client_roles):
    assert verifier.function_default_acl_violations(migrated_engine) == []


def test_default_acl_detects_explicit_unsafe_public_default(
    migrated_engine, verifier, client_roles
):
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "alter default privileges for role app_owner in schema public "
                "grant execute on functions to public"
            )
        )
    try:
        violations = verifier.function_default_acl_violations(migrated_engine)
        assert violations, "unsafe PUBLIC function default must be detected"
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "alter default privileges for role app_owner in schema public "
                    "revoke execute on functions from public"
                )
            )
    assert verifier.function_default_acl_violations(migrated_engine) == []


def test_default_acl_detects_implicit_public_execute(database_url, verifier, client_roles):
    """No explicit pg_default_acl row must not hide the built-in PUBLIC EXECUTE.

    ``0013`` stores an explicit global function-default row whose ACL has the
    PUBLIC EXECUTE entry removed. Deleting that row makes the effective default
    fall back to ``acldefault('f', owner_oid)``, which grants PUBLIC EXECUTE.
    The verifier must still report the unsafe effective default rather than
    treating the absence of a row as safe.
    """
    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            conn.execute(
                text(
                    """
                    delete from pg_default_acl d using pg_roles r
                    where r.oid = d.defaclrole and r.rolname = 'app_owner'
                      and d.defaclnamespace = 0 and d.defaclobjtype = 'f'
                    """
                )
            )
            violations = verifier.function_default_acl_violations(conn)
            assert violations, (
                "implicit built-in PUBLIC EXECUTE default must be detected"
            )
            transaction.rollback()
        with engine.connect() as conn:
            assert verifier.function_default_acl_violations(conn) == []
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 11-13: expected-SQLSTATE harness
# ---------------------------------------------------------------------------


def test_expect_sqlstate_accepts_exact_state(database_url, verifier):
    with psycopg.connect(_psycopg_url(database_url)) as conn:
        verifier.expect_sqlstate(
            conn, "22P02", "select 'not-a-uuid'::uuid"
        )


def test_expect_sqlstate_rejects_unexpected_success(database_url, verifier):
    with psycopg.connect(_psycopg_url(database_url)) as conn:
        with pytest.raises(verifier.VerifierError):
            verifier.expect_sqlstate(conn, "22P02", "select 1")


def test_expect_sqlstate_rejects_wrong_state(database_url, verifier):
    with psycopg.connect(_psycopg_url(database_url)) as conn:
        with pytest.raises(verifier.VerifierError):
            verifier.expect_sqlstate(conn, "99999", "select 'not-a-uuid'::uuid")


def test_expect_sqlstate_leaves_connection_reusable(database_url, verifier):
    with psycopg.connect(_psycopg_url(database_url)) as conn:
        verifier.expect_sqlstate(conn, "22P02", "select 'not-a-uuid'::uuid")
        with conn.cursor() as cur:
            cur.execute("select 1")
            assert cur.fetchone()[0] == 1


# ---------------------------------------------------------------------------
# 14: guaranteed temporary worker UPDATE grant cleanup
# ---------------------------------------------------------------------------


def test_worker_update_grant_is_revoked_on_success(migrated_engine, verifier):
    with verifier.temporary_worker_update_grant(migrated_engine):
        assert verifier.worker_has_update(migrated_engine) is True
    assert verifier.worker_has_update(migrated_engine) is False


def test_worker_update_grant_revoked_after_induced_failure(
    migrated_engine, verifier
):
    with pytest.raises(RuntimeError, match="induced"):
        with verifier.temporary_worker_update_grant(migrated_engine):
            assert verifier.worker_has_update(migrated_engine) is True
            raise RuntimeError("induced failure after GRANT")
    assert verifier.worker_has_update(migrated_engine) is False


# ---------------------------------------------------------------------------
# 15-16: fixture identifiers and residual-row detection
# ---------------------------------------------------------------------------


def test_fixture_identifiers_are_full_uuids(verifier):
    assert UUID(verifier.USER_A_ID)
    assert UUID(verifier.USER_B_ID)
    assert verifier.USER_A_ID != verifier.USER_B_ID
    assert verifier.TEMP_CANONICAL_ENTITY_KEY


def test_fixture_cleanup_leaves_no_identifiers(migrated_engine, verifier):
    verifier.seed_behavioral_fixtures(migrated_engine)
    assert verifier.fixture_residue(migrated_engine) != [], "seed must create fixtures"
    verifier.cleanup_behavioral_fixtures(migrated_engine)
    assert verifier.fixture_residue(migrated_engine) == []


def test_final_zero_data_gate_detects_residual_row(
    migrated_engine, verifier, clean_application_data
):
    # Clean state first.
    verifier.cleanup_behavioral_fixtures(migrated_engine)
    assert verifier.application_row_violations(migrated_engine) == []
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "insert into app_users (id, auth_provider, auth_subject) "
                "values (gen_random_uuid(), 'test', 'residual')"
            )
        )
    try:
        violations = verifier.application_row_violations(migrated_engine)
        assert any(v.table == "app_users" for v in violations)
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(text("delete from app_users where auth_subject = 'residual'"))
    assert verifier.application_row_violations(migrated_engine) == []


# ---------------------------------------------------------------------------
# 17-18: orphan relationship inventory and detection
# ---------------------------------------------------------------------------


def test_orphan_relationship_inventory_matches_database(
    migrated_engine, verifier, clean_application_data
):
    actual = verifier.database_foreign_keys(migrated_engine)
    assert set(actual) == set(verifier.EXPECTED_FOREIGN_KEYS)
    assert len(verifier.EXPECTED_FOREIGN_KEYS) == len(set(verifier.EXPECTED_FOREIGN_KEYS))


def test_orphan_checker_clean(migrated_engine, verifier, clean_application_data):
    verifier.cleanup_behavioral_fixtures(migrated_engine)
    assert verifier.orphan_violations(migrated_engine) == []


def test_orphan_checker_detects_injected_orphan(
    migrated_engine, verifier, clean_application_data
):
    """Create a real FK orphan inside a rolled-back superuser transaction.

    ``session_replication_role = replica`` disables FK enforcement so an orphan
    row can be created in a controlled disposable state; the whole transaction
    is rolled back, leaving no residue.
    """
    verifier.cleanup_behavioral_fixtures(migrated_engine)
    with migrated_engine.connect() as conn:
        transaction = conn.begin()
        conn.execute(text("set local session_replication_role = replica"))
        conn.execute(
            text(
                "insert into public.jobs (id, user_id, job_type, status) "
                "values (gen_random_uuid(), gen_random_uuid(), 'EVALUATION', 'PENDING')"
            )
        )
        violations = verifier.orphan_violations(conn)
        assert any(v.child_table == "jobs" for v in violations), violations
        transaction.rollback()
    assert verifier.orphan_violations(migrated_engine) == []


# ---------------------------------------------------------------------------
# 19: clean final state passes
# ---------------------------------------------------------------------------


def test_clean_final_state_passes(
    migrated_engine, verifier, client_roles, clean_application_data
):
    verifier.cleanup_behavioral_fixtures(migrated_engine)
    assert verifier.application_row_violations(migrated_engine) == []
    assert verifier.orphan_violations(migrated_engine) == []
    assert verifier.fixture_residue(migrated_engine) == []


# ---------------------------------------------------------------------------
# Finding 1: preflight must reject unsafe starting state
# ---------------------------------------------------------------------------


def test_preflight_exact_state_clean(legacy_engine, verifier):
    assert verifier.preflight_exact_state_violations(legacy_engine) == []


def test_preflight_revision_mismatch_detected(legacy_engine, verifier):
    with legacy_engine.begin() as conn:
        conn.execute(
            text(
                "update public.alembic_version "
                "set version_num = '0005_assessment_evidence'"
            )
        )
    try:
        violations = verifier.preflight_exact_state_violations(legacy_engine)
        assert any(v.kind == "preflight_revision" for v in violations), violations
    finally:
        with legacy_engine.begin() as conn:
            conn.execute(
                text("update public.alembic_version set version_num = :rev"),
                {"rev": LEGACY_REVISION},
            )
    assert verifier.preflight_exact_state_violations(legacy_engine) == []


def test_preflight_backend_bypassrls_detected(legacy_engine, verifier):
    with legacy_engine.begin() as conn:
        conn.execute(text("alter role app_backend bypassrls"))
    try:
        violations = verifier.preflight_exact_state_violations(legacy_engine)
        assert any(
            v.role == "app_backend" and "bypassrls" in v.detail.lower()
            for v in violations
        ), violations
    finally:
        with legacy_engine.begin() as conn:
            conn.execute(text("alter role app_backend nobypassrls"))
    assert verifier.preflight_exact_state_violations(legacy_engine) == []


def test_preflight_worker_bypassrls_false_detected(legacy_engine, verifier):
    with legacy_engine.begin() as conn:
        conn.execute(text("alter role app_worker nobypassrls"))
    try:
        violations = verifier.preflight_exact_state_violations(legacy_engine)
        assert any(v.role == "app_worker" for v in violations), violations
    finally:
        with legacy_engine.begin() as conn:
            conn.execute(text("alter role app_worker bypassrls"))
    assert verifier.preflight_exact_state_violations(legacy_engine) == []


def test_preflight_missing_pgcrypto_detected(legacy_engine, verifier):
    with legacy_engine.begin() as conn:
        conn.execute(text("drop extension pgcrypto"))
    try:
        violations = verifier.preflight_exact_state_violations(legacy_engine)
        assert any("pgcrypto" in v.detail for v in violations), violations
    finally:
        with legacy_engine.begin() as conn:
            conn.execute(text("create extension pgcrypto schema extensions"))
    assert verifier.preflight_exact_state_violations(legacy_engine) == []


def test_preflight_extension_schema_mismatch_detected(legacy_engine, verifier):
    with legacy_engine.begin() as conn:
        conn.execute(text("alter extension vector set schema extensions"))
    try:
        violations = verifier.preflight_exact_state_violations(legacy_engine)
        assert any("vector" in v.detail for v in violations), violations
    finally:
        with legacy_engine.begin() as conn:
            conn.execute(text("alter extension vector set schema public"))
    assert verifier.preflight_exact_state_violations(legacy_engine) == []


def test_preflight_membership_revoked_detected(legacy_engine, verifier):
    with legacy_engine.begin() as conn:
        conn.execute(text("revoke app_maintenance from app_owner"))
    try:
        violations = verifier.preflight_exact_state_violations(legacy_engine)
        assert any(v.kind == "preflight_membership" for v in violations), violations
    finally:
        with legacy_engine.begin() as conn:
            conn.execute(
                text(
                    "grant app_maintenance to app_owner "
                    "with set true, inherit false, admin false"
                )
            )
    assert verifier.preflight_exact_state_violations(legacy_engine) == []


# ---------------------------------------------------------------------------
# Finding 2: freeze full RLS policy semantics
# ---------------------------------------------------------------------------


def _jobs_policy_definition(migrated_engine) -> dict:
    with migrated_engine.connect() as conn:
        row = conn.execute(
            text(
                """
                select pg_get_expr(p.polqual, p.polrelid) as qual,
                       pg_get_expr(p.polwithcheck, p.polrelid) as with_check,
                       p.polcmd,
                       (select array_agg(r.rolname)
                          from pg_roles r where r.oid = any(p.polroles)) as roles
                from pg_policy p
                join pg_class c on c.oid = p.polrelid
                join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'public' and c.relname = 'jobs'
                  and p.polname = 'jobs_user_policy'
                """
            )
        ).one()
    return {
        "qual": row.qual,
        "with_check": row.with_check,
        "roles": list(row.roles),
    }


def _count_jobs_for_other_user_as_backend(database_url: str) -> int:
    with psycopg.connect(_psycopg_url(database_url)) as conn:
        with conn.cursor() as cur:
            cur.execute("set local role app_backend")
        with conn.cursor() as cur:
            cur.execute(
                "select set_config('app.user_id', %s, true)", (POLICY_USER_A,)
            )
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from public.jobs where user_id = %s",
                (POLICY_USER_B,),
            )
            count = cur.fetchone()[0]
        conn.rollback()
    return count


def test_rls_policy_contract_clean(migrated_engine, verifier, clean_application_data):
    verifier.cleanup_behavioral_fixtures(migrated_engine)
    assert verifier.rls_violations(migrated_engine) == []


def test_rls_detects_permissive_same_name_policy(
    database_url, migrated_engine, verifier, clean_application_data
):
    """A same-name permissive policy must fail and admit cross-user rows."""
    original = _jobs_policy_definition(migrated_engine)
    with migrated_engine.begin() as conn:
        conn.execute(text("insert into public.app_users (id, auth_provider, auth_subject) values (:a, 'test', 'p33-policy-a'), (:b, 'test', 'p33-policy-b')"), {"a": POLICY_USER_A, "b": POLICY_USER_B})
        conn.execute(text("insert into public.jobs (user_id, job_type, status) values (:b, 'EVALUATION', 'PENDING')"), {"b": POLICY_USER_B})
    with migrated_engine.begin() as conn:
        conn.execute(text("drop policy jobs_user_policy on public.jobs"))
        conn.execute(
            text(
                "create policy jobs_user_policy on public.jobs "
                "to app_backend using (true) with check (true)"
            )
        )
    try:
        assert _count_jobs_for_other_user_as_backend(database_url) == 1
        violations = verifier.rls_violations(migrated_engine)
        assert any(v.table == "jobs" for v in violations), violations
        assert any(v.field == "qual" for v in violations), violations
    finally:
        roles = ", ".join(original["roles"])
        with migrated_engine.begin() as conn:
            conn.execute(text("drop policy jobs_user_policy on public.jobs"))
            conn.execute(
                text(
                    f"create policy jobs_user_policy on public.jobs to {roles} "
                    f"using ({original['qual']}) "
                    f"with check ({original['with_check']})"
                )
            )
        with migrated_engine.begin() as conn:
            conn.execute(text("delete from public.jobs where user_id = :b"), {"b": POLICY_USER_B})
            conn.execute(text("delete from public.app_users where id in (:a, :b)"), {"a": POLICY_USER_A, "b": POLICY_USER_B})
    assert verifier.rls_violations(migrated_engine) == []
    assert _count_jobs_for_other_user_as_backend(database_url) == 0


# ---------------------------------------------------------------------------
# Finding 3: default ACL must account for inherited privileges
# ---------------------------------------------------------------------------


def test_default_acl_detects_inherited_client_execute(
    migrated_engine, verifier, client_roles
):
    helper = "p33_dacl_helper"
    with migrated_engine.begin() as conn:
        conn.execute(text(f"drop role if exists {helper}"))
        conn.execute(text(f"create role {helper} nologin"))
        conn.execute(text(f"grant {helper} to anon with inherit true, set false"))
        conn.execute(
            text(
                "alter default privileges for role app_owner in schema public "
                f"grant execute on functions to {helper}"
            )
        )
    with migrated_engine.begin() as conn:
        conn.execute(text("set local role app_owner"))
        conn.execute(
            text(
                "create function public.p33_future_fn() returns int "
                "language sql as 'select 1'"
            )
        )
    try:
        with migrated_engine.connect() as conn:
            effective = conn.execute(
                text(
                    "select has_function_privilege("
                    "'anon', 'public.p33_future_fn()', 'EXECUTE')"
                )
            ).scalar_one()
        assert effective is True
        violations = verifier.function_default_acl_violations(migrated_engine)
        assert any(v.role == "anon" for v in violations), violations
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(text("drop function if exists public.p33_future_fn()"))
            conn.execute(
                text(
                    "alter default privileges for role app_owner in schema public "
                    f"revoke execute on functions from {helper}"
                )
            )
            conn.execute(text(f"revoke {helper} from anon"))
            conn.execute(text(f"drop role if exists {helper}"))
    assert verifier.function_default_acl_violations(migrated_engine) == []


# ---------------------------------------------------------------------------
# Finding 4: freeze FK semantics, not just FK names
# ---------------------------------------------------------------------------


def test_foreign_key_contract_matches_database(
    migrated_engine, verifier, clean_application_data
):
    actual = verifier.database_foreign_key_contract(migrated_engine)
    expected = {spec.name: spec for spec in verifier.EXPECTED_FOREIGN_KEY_CONTRACT}
    assert len(expected) == len(verifier.EXPECTED_FOREIGN_KEY_CONTRACT)
    assert actual == expected


def test_foreign_key_contract_detects_same_name_drift(
    migrated_engine, verifier, clean_application_data
):
    with migrated_engine.connect() as conn:
        definition = conn.execute(
            text(
                "select pg_get_constraintdef(oid) from pg_constraint "
                "where conname = 'fk_jobs_user_id_app_users'"
            )
        ).scalar_one()
    with migrated_engine.begin() as conn:
        conn.execute(
            text("alter table public.jobs drop constraint fk_jobs_user_id_app_users")
        )
        conn.execute(
            text(
                "alter table public.jobs add constraint fk_jobs_user_id_app_users "
                "foreign key (id) references public.app_users (id)"
            )
        )
    try:
        violations = verifier.foreign_key_violations(migrated_engine)
        drifted = [v for v in violations if v.table == "fk_jobs_user_id_app_users"]
        assert drifted, violations
        assert any(v.field for v in drifted), drifted
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "alter table public.jobs "
                    "drop constraint fk_jobs_user_id_app_users"
                )
            )
            conn.execute(
                text(
                    "alter table public.jobs add constraint "
                    f"fk_jobs_user_id_app_users {definition}"
                )
            )
    assert verifier.foreign_key_violations(migrated_engine) == []


def test_final_skips_orphan_checker_when_fk_contract_fails(
    monkeypatch, migrated_engine, verifier, clean_application_data
):
    def _explode(obj):  # pragma: no cover - must never run
        raise AssertionError("orphan checker ran before FK contract passed")

    monkeypatch.setattr(verifier, "orphan_violations", _explode)
    with migrated_engine.begin() as conn:
        conn.execute(
            text("alter table public.jobs drop constraint fk_jobs_user_id_app_users")
        )
        conn.execute(
            text(
                "alter table public.jobs add constraint fk_jobs_user_id_app_users "
                "foreign key (id) references public.app_users (id)"
            )
        )
    try:
        assert verifier.final_foreign_key_violations(migrated_engine)
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "alter table public.jobs "
                    "drop constraint fk_jobs_user_id_app_users"
                )
            )
            conn.execute(
                text(
                    "alter table public.jobs add constraint "
                    "fk_jobs_user_id_app_users foreign key (user_id) "
                    "references public.app_users (id) on delete cascade"
                )
            )
    assert verifier.foreign_key_violations(migrated_engine) == []


# ---------------------------------------------------------------------------
# Finding 5: expect_sqlstate must not roll back caller work
# ---------------------------------------------------------------------------


def _sentinel_survives(verifier, database_url, expected, sql, should_raise):
    with psycopg.connect(_psycopg_url(database_url)) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "insert into public.app_users (id, auth_provider, auth_subject) "
                "values (gen_random_uuid(), 'test', 'p33-sqlstate-sentinel')"
            )
        if should_raise:
            with pytest.raises(verifier.VerifierError):
                verifier.expect_sqlstate(conn, expected, sql)
        else:
            verifier.expect_sqlstate(conn, expected, sql)
        with conn.cursor() as cur:
            cur.execute(
                "select count(*) from public.app_users "
                "where auth_subject = 'p33-sqlstate-sentinel'"
            )
            assert cur.fetchone()[0] == 1, "helper destroyed caller sentinel"
            cur.execute("select 1")
            assert cur.fetchone()[0] == 1, "connection unusable after helper"
        conn.rollback()


def test_expect_sqlstate_preserves_caller_on_expected_state(
    database_url, verifier
):
    _sentinel_survives(
        verifier, database_url, "22P02", "select 'not-a-uuid'::uuid", False
    )


def test_expect_sqlstate_preserves_caller_on_wrong_state(
    database_url, verifier
):
    _sentinel_survives(
        verifier, database_url, "99999", "select 'not-a-uuid'::uuid", True
    )


def test_expect_sqlstate_preserves_caller_on_unexpected_success(
    database_url, verifier
):
    _sentinel_survives(verifier, database_url, "22P02", "select 1", True)


def test_expect_sqlstate_isolates_without_outer_transaction(
    database_url, verifier
):
    from psycopg import pq

    with psycopg.connect(_psycopg_url(database_url)) as conn:
        verifier.expect_sqlstate(conn, "22P02", "select 'not-a-uuid'::uuid")
        assert conn.info.transaction_status == pq.TransactionStatus.IDLE
        with conn.cursor() as cur:
            cur.execute("select 1")
            assert cur.fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Pass 3 Finding 1: required hosted client roles must exist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ("anon", "authenticated", "service_role"))
def test_preflight_missing_client_role_detected(legacy_engine, verifier, role):
    with legacy_engine.begin() as conn:
        conn.execute(text(f"drop role {role}"))
    try:
        violations = verifier.preflight_exact_state_violations(legacy_engine)
        assert any(
            v.kind == "missing_client_role" and v.role == role
            for v in violations
        ), violations
    finally:
        with legacy_engine.begin() as conn:
            conn.execute(text(f"create role {role} nologin"))
    assert verifier.preflight_exact_state_violations(legacy_engine) == []


@pytest.mark.parametrize("role", ("anon", "authenticated", "service_role"))
def test_post_upgrade_missing_client_role_detected(
    migrated_engine, verifier, client_roles, role
):
    with migrated_engine.begin() as conn:
        conn.execute(text(f"drop role {role}"))
    try:
        violations = verifier.post_upgrade_violations(migrated_engine)
        assert any(
            v.kind == "missing_client_role" and v.role == role
            for v in violations
        ), violations
    finally:
        with migrated_engine.begin() as conn:
            conn.execute(text(f"create role {role} nologin"))
    assert verifier.missing_client_role_violations(migrated_engine) == []


def test_post_upgrade_clean_with_required_client_roles(
    migrated_engine, verifier, client_roles, clean_application_data
):
    verifier.cleanup_behavioral_fixtures(migrated_engine)
    # The shared test harness applies migrations as ``postgres``, so object
    # ownership is checked only by the app_owner-owned four-mode rehearsal; the
    # remaining post-upgrade security checks must be clean here.
    assert verifier.missing_client_role_violations(migrated_engine) == []
    assert verifier.rls_violations(migrated_engine) == []
    assert verifier.maintenance_function_violations(migrated_engine) == []
    assert verifier.client_privilege_violations(migrated_engine) == []
    assert verifier.function_default_acl_violations(migrated_engine) == []


# ---------------------------------------------------------------------------
# Pass 3 Finding 2: policy normalization must preserve quoted literals
# ---------------------------------------------------------------------------


def test_normalize_predicate_preserves_quoted_literal_contents(verifier):
    expected = (
        "(user_id = (NULLIF(current_setting('app.user_id'::text, true), "
        "''::text))::uuid)"
    )
    tampered = (
        "(user_id = (NULLIF(current_setting('app.user_id'::text, true), "
        "'::text'::text))::uuid)"
    )
    assert verifier._normalize_predicate(expected) != verifier._normalize_predicate(
        tampered
    )


def test_normalize_predicate_only_strips_catalog_casts_outside_literals(verifier):
    canonical = (
        "(user_id = (NULLIF(current_setting('app.user_id'::text, true), "
        "''::text))::uuid)"
    )
    without_cast = (
        "(user_id = (NULLIF(current_setting('app.user_id', true), ''))::uuid)"
    )
    assert verifier._normalize_predicate(canonical) == verifier._normalize_predicate(
        without_cast
    )
    # whitespace-only differences are harmless
    spaced = (
        "( user_id  =  ( NULLIF( current_setting('app.user_id'::text, true),  "
        "''::text ) )::uuid )"
    )
    assert verifier._normalize_predicate(canonical) == verifier._normalize_predicate(
        spaced
    )
    # literal contents are never rewritten
    literal = "select '::text'"
    assert "::text" in verifier._normalize_predicate(literal)


def test_rls_detects_changed_policy_literal(
    migrated_engine, verifier, clean_application_data
):
    original = _jobs_policy_definition(migrated_engine)
    tampered_predicate = (
        "user_id = (NULLIF(current_setting('app.user_id'::text, true), "
        "'::text'::text))::uuid"
    )
    with migrated_engine.begin() as conn:
        conn.execute(text("drop policy jobs_user_policy on public.jobs"))
        conn.execute(
            text(
                "create policy jobs_user_policy on public.jobs to app_backend "
                f"using ({tampered_predicate}) with check ({tampered_predicate})"
            )
        )
    try:
        violations = verifier.rls_violations(migrated_engine)
        assert any(v.table == "jobs" and v.field == "qual" for v in violations), (
            violations
        )
    finally:
        roles = ", ".join(original["roles"])
        with migrated_engine.begin() as conn:
            conn.execute(text("drop policy jobs_user_policy on public.jobs"))
            conn.execute(
                text(
                    f"create policy jobs_user_policy on public.jobs to {roles} "
                    f"using ({original['qual']}) "
                    f"with check ({original['with_check']})"
                )
            )
    assert verifier.rls_violations(migrated_engine) == []


# ---------------------------------------------------------------------------
# Pass 3 Finding 3: membership fixture must establish full frozen state
# ---------------------------------------------------------------------------


def test_legacy_fixture_membership_state(legacy_engine, verifier):
    assert verifier.capture_owner_membership(legacy_engine) == (
        verifier.MembershipState(exists=True, admin=False, inherit=False, set=True)
    )


def test_membership_fixture_restore_round_trip(migrated_engine, verifier):
    original = verifier.capture_owner_membership(migrated_engine)
    target = verifier.MembershipState(
        exists=True, admin=False, inherit=False, set=True
    )
    try:
        verifier.apply_owner_membership(migrated_engine, target)
        assert verifier.capture_owner_membership(migrated_engine) == target
        verifier.apply_owner_membership(
            migrated_engine, verifier.MembershipState(exists=False)
        )
        assert verifier.capture_owner_membership(migrated_engine) == (
            verifier.MembershipState(exists=False)
        )
    finally:
        verifier.apply_owner_membership(migrated_engine, original)
    assert verifier.capture_owner_membership(migrated_engine) == original
