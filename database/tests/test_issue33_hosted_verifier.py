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
from sqlalchemy import create_engine, text

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPOSITORY_ROOT / "database" / "tools" / "issue33_hosted_verifier.py"


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
