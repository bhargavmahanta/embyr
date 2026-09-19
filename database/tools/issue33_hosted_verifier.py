"""Authoritative Issue #33 hosted security verifier.

This module is the single source of truth for the Embyr hosted Supabase
migration/RLS verification procedure (Issue #33). It is a verifier/harness, not
an automated reset tool: it never performs the destructive migration and has no
import-time side effects.

Modes
-----
``--preflight``    read-only legacy inventory, exact row counts, and the
                   ``app_owner`` connectivity/privilege preflight (explicit
                   ``BEGIN READ ONLY``).
``--post-upgrade`` catalog/security inspection of the rebuilt ``0013`` schema.
``--behavioral``   temporary fixtures and expected-SQLSTATE behavior; requires
                   explicit Phase B authorization before running against hosted.
``--final``        post-cleanup zero-data, fixture-residue, orphan, and
                   platform-count assertions.

Credentials are read from environment variables only; no secret is stored here:

* ``EMBYR_HOSTED_ADMIN_URL``   administrative ``postgres`` identity.
* ``EMBYR_HOSTED_OWNER_URL``   ``app_owner`` identity.
* ``EMBYR_HOSTED_BACKEND_URL`` ``app_backend`` identity.
* ``EMBYR_HOSTED_WORKER_URL``  ``app_worker`` identity.

Supavisor Session mode does not preserve a URL-level
``default_transaction_read_only``; the owner preflight sets it explicitly.
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Sequence

import psycopg
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

# ---------------------------------------------------------------------------
# Immutable inventories (derived from frozen migrations 0001-0013 and tests)
# ---------------------------------------------------------------------------

# Tables created by migrations 0001-0006, i.e. the legacy hosted state at
# revision ``0006_practical_artifacts``. Deterministic migration order.
LEGACY_0006_APPLICATION_TABLES: tuple[str, ...] = (
    # 0001_foundation
    "app_users",
    "user_devices",
    "idempotency_records",
    "jobs",
    # 0002_ontology
    "learning_entities",
    "learning_entity_versions",
    "entity_domains",
    "ontology_edges",
    "learning_objectives",
    "misconceptions",
    "claims",
    "entity_embeddings",
    # 0003_preferences
    "learner_preferences",
    "user_motivations",
    "explicit_interest_preferences",
    # 0004_exploration
    "explorations",
    "reflections",
    # 0005_assessment_evidence
    "assessment_sessions",
    "assessment_interactions",
    "assessment_support_requests",
    "assessment_responses",
    "evaluation_runs",
    "learning_evidence",
    # 0006_practical_artifacts
    "practical_challenges",
    "practical_challenge_versions",
    "upload_sessions",
    "media_objects",
    "artifacts",
    "artifact_analyses",
)

# Every Embyr application-data table at revision ``0013_default_acl_hardening``.
# ``alembic_version`` and all Supabase/platform and extension-owned relations
# are excluded. Deterministic migration order.
FINAL_0013_APPLICATION_TABLES: tuple[str, ...] = (
    *LEGACY_0006_APPLICATION_TABLES,
    # 0007_experience_ledger
    "learning_events",
    # 0008_learner_state
    "learner_interest_state",
    "learner_objective_state",
    "learner_retention_state",
    "learner_confidence_state",
    "learner_challenge_state",
    "state_evidence_links",
    # 0009_recommendations
    "recommendations",
    # 0010_worldmodel
    "learner_worlds",
    "world_regions",
    "world_nodes",
    "world_connections",
    "world_artifacts",
    "world_changes",
    # 0011_stories_and_exports
    "curiosity_stories",
    "account_operation_requests",
)

# Learner-owned tables that migration ``0012_rls_and_security`` puts under
# ENABLE + FORCE row level security (34 tables).
RLS_LEARNER_TABLES: tuple[str, ...] = (
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

CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated", "service_role")

# Every table privilege ``has_table_privilege`` supports on PostgreSQL 17.
PG17_TABLE_PRIVILEGES: tuple[str, ...] = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
    "MAINTAIN",
)

MAINTENANCE_FUNCTION = "public.maintenance_delete_account(uuid)"

# The complete foreign-key constraint inventory of the rebuilt schema, derived
# from frozen migrations 0001-0011. The orphan checker asserts the database
# matches this set before running per-relationship orphan detection.
EXPECTED_FOREIGN_KEYS: tuple[str, ...] = (
    "fk_account_operation_requests_idempotency_owner",
    "fk_account_operation_requests_user_id_app_users",
    "fk_artifact_analyses_artifact_owner",
    "fk_artifacts_exploration_challenge_owner_version",
    "fk_artifacts_media_owner",
    "fk_artifacts_reflection_owner_exploration",
    "fk_assessment_interactions_objective_id_learning_objectives",
    "fk_assessment_interactions_session_owner",
    "fk_assessment_responses_interaction_owner_session",
    "fk_assessment_sessions_exploration_owner_version",
    "fk_assessment_support_requests_interaction_owner_session",
    "fk_claims_entity_id_learning_entities",
    "fk_curiosity_stories_user_id_app_users",
    "fk_entity_domains_domain_id_learning_entities",
    "fk_entity_domains_entity_id_learning_entities",
    "fk_entity_embeddings_entity_version",
    "fk_evaluation_runs_response_owner",
    "fk_evaluation_runs_superseded_owner_response",
    "fk_explicit_interest_preferences_entity_id_learning_entities",
    "fk_explicit_interest_preferences_user_id_app_users",
    "fk_explorations_entity_version",
    "fk_explorations_practical_challenge_version",
    "fk_explorations_recommendation_owner",
    "fk_explorations_user_id_app_users",
    "fk_idempotency_records_user_id_app_users",
    "fk_jobs_user_id_app_users",
    "fk_learner_challenge_state_area_id_learning_entities",
    "fk_learner_challenge_state_user_id_app_users",
    "fk_learner_confidence_state_entity_id_learning_entities",
    "fk_learner_confidence_state_user_id_app_users",
    "fk_learner_interest_state_entity_id_learning_entities",
    "fk_learner_interest_state_user_id_app_users",
    "fk_learner_objective_state_objective_id_learning_objectives",
    "fk_learner_objective_state_user_id_app_users",
    "fk_learner_preferences_user_id_app_users",
    "fk_learner_retention_state_entity_id_learning_entities",
    "fk_learner_retention_state_user_id_app_users",
    "fk_learner_worlds_user_id_app_users",
    "fk_learning_entities_current_version",
    "fk_learning_entity_versions_entity_id_learning_entities",
    "fk_learning_events_artifact_owner",
    "fk_learning_events_assessment_session_owner",
    "fk_learning_events_command_id_idempotency_records",
    "fk_learning_events_device_owner",
    "fk_learning_events_entity_id_learning_entities",
    "fk_learning_events_exploration_owner",
    "fk_learning_events_user_id_app_users",
    "fk_learning_evidence_evaluation_owner_source",
    "fk_learning_evidence_objective_entity",
    "fk_learning_evidence_user_id_app_users",
    "fk_learning_objectives_entity_version",
    "fk_media_objects_upload_owner",
    "fk_misconceptions_entity_id_learning_entities",
    "fk_misconceptions_objective_id_learning_objectives",
    "fk_ontology_edges_source_entity_id_learning_entities",
    "fk_ontology_edges_target_entity_id_learning_entities",
    "fk_practical_challenge_versions_challenge_entity",
    "fk_practical_challenge_versions_entity_version",
    "fk_practical_challenges_entity_id_learning_entities",
    "fk_recommendations_challenge_id_practical_challenges",
    "fk_recommendations_entity_version",
    "fk_recommendations_user_id_app_users",
    "fk_reflections_exploration_owner_entity",
    "fk_state_evidence_links_event_owner",
    "fk_state_evidence_links_evidence_owner",
    "fk_state_evidence_links_user_id_app_users",
    "fk_upload_sessions_user_id_app_users",
    "fk_user_devices_user_id_app_users",
    "fk_user_motivations_user_id_app_users",
    "fk_world_artifacts_artifact_owner",
    "fk_world_artifacts_region_owner",
    "fk_world_artifacts_user_id_app_users",
    "fk_world_artifacts_world_owner",
    "fk_world_changes_user_id_app_users",
    "fk_world_changes_world_owner",
    "fk_world_connections_ontology_edge_id_ontology_edges",
    "fk_world_connections_source_node_owner",
    "fk_world_connections_target_node_owner",
    "fk_world_connections_user_id_app_users",
    "fk_world_connections_world_owner",
    "fk_world_nodes_entity_id_learning_entities",
    "fk_world_nodes_region_owner",
    "fk_world_nodes_user_id_app_users",
    "fk_world_nodes_world_owner",
    "fk_world_regions_primary_domain_id_learning_entities",
    "fk_world_regions_user_id_app_users",
    "fk_world_regions_world_owner",
)

# Complete fixture identifiers (full valid UUIDs / keys). Cleanup refers to the
# exact same constants used during fixture creation.
USER_A_ID = "11111111-1111-1111-1111-111111111111"
USER_B_ID = "22222222-2222-2222-2222-222222222222"
TEMP_CANONICAL_ENTITY_KEY = "p33-fixture-canonical"
TEMP_IDEMPOTENCY_KEY = "p33-fixture-key"

def _learner_owner_orphan_sql() -> str:
    """Aggregate maintenance invariant over every learner-owned table.

    The per-FK checker already covers each composite ownership foreign key; this
    explicit cross-check asserts the whole-table invariant that
    ``maintenance_delete_account(uuid)`` relies on: no learner-owned row may
    reference a ``user_id`` with no ``app_users`` row.
    """
    branches = "\nunion all\n".join(
        f"select '{table}' as relation, count(*) as n from public.{table} x "
        "where x.user_id is not null "
        "and not exists (select 1 from public.app_users u where u.id = x.user_id)"
        for table in RLS_LEARNER_TABLES
    )
    return f"select relation, sum(n) as n from (\n{branches}\n) s group by relation having sum(n) > 0"


# Non-FK ownership relationships that maintenance_delete_account(uuid) depends
# on but which PostgreSQL does not express as foreign keys. This is the
# aggregate maintenance invariant over all 34 learner-owned tables.
EXTRA_ORPHAN_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "learner-owned rows whose user_id has no app_users row",
        _learner_owner_orphan_sql(),
    ),
)

ADMIN_ENV = "EMBYR_HOSTED_ADMIN_URL"
OWNER_ENV = "EMBYR_HOSTED_OWNER_URL"
BACKEND_ENV = "EMBYR_HOSTED_BACKEND_URL"
WORKER_ENV = "EMBYR_HOSTED_WORKER_URL"


# ---------------------------------------------------------------------------
# Result types and errors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """A single verification failure with enough context to diagnose it."""

    kind: str
    detail: str
    role: str | None = None
    table: str | None = None
    privilege: str | None = None
    child_table: str | None = None
    count: int | None = None

    def __str__(self) -> str:  # pragma: no cover - presentation helper
        return f"[{self.kind}] {self.detail}"


class VerifierError(RuntimeError):
    """Raised when the verifier itself cannot proceed or an expectation fails."""


@dataclass
class Report:
    mode: str
    violations: list[Violation] = field(default_factory=list)
    info: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.violations


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


@contextmanager
def _connect(obj: Engine | Connection) -> Iterator[Connection]:
    if isinstance(obj, Engine):
        with obj.connect() as connection:
            yield connection
    else:
        yield obj


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


# ---------------------------------------------------------------------------
# Finding 1: exact inventory and row counts
# ---------------------------------------------------------------------------


def inventory_violations(
    obj: Engine | Connection, expected: Sequence[str]
) -> list[Violation]:
    with _connect(obj) as conn:
        present = {
            row[0]
            for row in conn.execute(
                text("select tablename from pg_tables where schemaname = 'public'")
            )
        }
    expected_set = set(expected)
    violations: list[Violation] = []
    for name in sorted(expected_set - present):
        violations.append(Violation("missing_table", f"expected table {name} absent", table=name))
    for name in sorted(present - expected_set - {"alembic_version"}):
        violations.append(
            Violation("unexpected_table", f"unexpected application table {name}", table=name)
        )
    return violations


def exact_row_count_violations(
    obj: Engine | Connection, tables: Sequence[str]
) -> list[Violation]:
    violations: list[Violation] = []
    with _connect(obj) as conn:
        present = {
            row[0]
            for row in conn.execute(
                text("select tablename from pg_tables where schemaname = 'public'")
            )
        }
        for table in tables:
            if table not in present:
                continue
            count = conn.execute(text(f'select count(*) from public."{table}"')).scalar_one()
            if count != 0:
                violations.append(
                    Violation(
                        "nonzero_rows",
                        f"{table} has {count} rows",
                        table=table,
                        count=count,
                    )
                )
    return violations


def platform_count_violations(
    obj: Engine | Connection,
    expected: dict[str, int] | None = None,
) -> list[Violation]:
    expected = expected or {"auth.users": 0, "storage.buckets": 0, "storage.objects": 0}
    violations: list[Violation] = []
    with _connect(obj) as conn:
        for relation, want in expected.items():
            count = conn.execute(text(f"select count(*) from {relation}")).scalar_one()
            if count != want:
                violations.append(
                    Violation(
                        "platform_count",
                        f"{relation} = {count}, expected {want}",
                        table=relation,
                        count=count,
                    )
                )
    return violations


# ---------------------------------------------------------------------------
# Finding 2A: complete client privilege matrix
# ---------------------------------------------------------------------------


def existing_client_roles(obj: Engine | Connection) -> list[str]:
    with _connect(obj) as conn:
        present = {
            row[0]
            for row in conn.execute(
                text("select rolname from pg_roles where rolname = any(:roles)"),
                {"roles": list(CLIENT_ROLES)},
            )
        }
    return [role for role in CLIENT_ROLES if role in present]


def client_privilege_violations(obj: Engine | Connection) -> list[Violation]:
    """Every effective table privilege for every existing client role."""
    violations: list[Violation] = []
    with _connect(obj) as conn:
        roles = [
            row[0]
            for row in conn.execute(
                text("select rolname from pg_roles where rolname = any(:roles)"),
                {"roles": list(CLIENT_ROLES)},
            )
        ]
        for table in FINAL_0013_APPLICATION_TABLES:
            exists = conn.execute(
                text("select to_regclass(:name)"), {"name": f"public.{table}"}
            ).scalar_one()
            if exists is None:
                continue
            for role in roles:
                for privilege in PG17_TABLE_PRIVILEGES:
                    granted = conn.execute(
                        text(
                            "select has_table_privilege(:role, :table, :privilege)"
                        ),
                        {"role": role, "table": f"public.{table}", "privilege": privilege},
                    ).scalar_one()
                    if granted:
                        violations.append(
                            Violation(
                                "client_table_privilege",
                                f"{role} has {privilege} on {table}",
                                role=role,
                                table=table,
                                privilege=privilege,
                            )
                        )
        # maintenance function EXECUTE for clients and PUBLIC
        for role in (*roles, "public"):
            granted = conn.execute(
                text(
                    "select has_function_privilege(:role, :fn, 'EXECUTE')"
                ),
                {"role": role, "fn": MAINTENANCE_FUNCTION},
            ).scalar_one()
            if granted:
                violations.append(
                    Violation(
                        "client_function_privilege",
                        f"{role} has EXECUTE on maintenance_delete_account",
                        role=role,
                        privilege="EXECUTE",
                    )
                )
    return violations


# ---------------------------------------------------------------------------
# Finding 2A: default ACL including implicit PUBLIC
# ---------------------------------------------------------------------------


def function_default_acl_violations(obj: Engine | Connection) -> list[Violation]:
    """Unsafe future default privileges for app_owner.

    Handles the global function default specially: when no explicit
    ``pg_default_acl`` row exists, PostgreSQL's built-in
    ``acldefault('f', owner_oid)`` still grants ``PUBLIC EXECUTE``. Absence of a
    row must therefore not be read as absence of PUBLIC EXECUTE.
    """
    violations: list[Violation] = []
    roles = list(CLIENT_ROLES)
    with _connect(obj) as conn:
        owner_oid = conn.execute(
            text("select oid from pg_roles where rolname = 'app_owner'")
        ).scalar_one_or_none()
        if owner_oid is None:
            return [
                Violation("missing_role", "app_owner role is absent")
            ]

        # Global function defaults (explicit row coalesced with built-in).
        global_grants = conn.execute(
            text(
                """
                select acl.grantee, coalesce(g.rolname, 'PUBLIC') as grantee_name,
                       acl.privilege_type
                from aclexplode(
                    coalesce(
                        (
                            select d.defaclacl from pg_default_acl d
                            where d.defaclrole = :owner
                              and d.defaclnamespace = 0
                              and d.defaclobjtype = 'f'
                        ),
                        acldefault('f', :owner)
                    )
                ) acl
                left join pg_roles g on g.oid = acl.grantee
                where acl.privilege_type = 'EXECUTE'
                  and (acl.grantee = 0 or g.rolname = any(:roles))
                """
            ),
            {"owner": owner_oid, "roles": roles},
        ).all()
        for _grantee, grantee_name, privilege in global_grants:
            violations.append(
                Violation(
                    "default_acl_function_global",
                    f"global function default grants {privilege} to {grantee_name}",
                    role=grantee_name,
                    privilege=privilege,
                )
            )

        # public-schema-specific function defaults (explicit rows only).
        schema_grants = conn.execute(
            text(
                """
                select coalesce(g.rolname, 'PUBLIC') as grantee_name,
                       acl.privilege_type
                from pg_default_acl d
                cross join lateral aclexplode(d.defaclacl) acl
                left join pg_roles g on g.oid = acl.grantee
                join pg_namespace n on n.oid = d.defaclnamespace
                where d.defaclrole = :owner
                  and d.defaclobjtype = 'f'
                  and n.nspname = 'public'
                  and acl.privilege_type = 'EXECUTE'
                  and (acl.grantee = 0 or g.rolname = any(:roles))
                """
            ),
            {"owner": owner_oid, "roles": roles},
        ).all()
        for grantee_name, privilege in schema_grants:
            violations.append(
                Violation(
                    "default_acl_function_schema",
                    f"public-schema function default grants {privilege} to {grantee_name}",
                    role=grantee_name,
                    privilege=privilege,
                )
            )

        # table and sequence defaults for PUBLIC and client roles.
        object_grants = conn.execute(
            text(
                """
                select d.defaclobjtype, coalesce(g.rolname, 'PUBLIC') as grantee_name,
                       acl.privilege_type
                from pg_default_acl d
                cross join lateral aclexplode(d.defaclacl) acl
                left join pg_roles g on g.oid = acl.grantee
                where d.defaclrole = :owner
                  and d.defaclobjtype in ('r', 'S')
                  and (acl.grantee = 0 or g.rolname = any(:roles))
                """
            ),
            {"owner": owner_oid, "roles": roles},
        ).all()
        for objtype, grantee_name, privilege in object_grants:
            violations.append(
                Violation(
                    "default_acl_object",
                    f"{objtype} default grants {privilege} to {grantee_name}",
                    role=grantee_name,
                    privilege=privilege,
                )
            )
    return violations


# ---------------------------------------------------------------------------
# Finding 2B: committed expected-SQLSTATE harness
# ---------------------------------------------------------------------------


def expect_sqlstate(
    connection: psycopg.Connection,
    expected_sqlstate: str,
    sql: str,
    params: Sequence | dict | None = None,
) -> None:
    """Assert ``sql`` raises exactly ``expected_sqlstate``; leave conn reusable.

    Begins an isolated transaction, executes, fails on unexpected success,
    compares the exact SQLSTATE, and rolls back the failed transaction so the
    connection can be used for the next case.
    """
    if connection.autocommit:
        raise VerifierError("expect_sqlstate requires a non-autocommit connection")
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params or ())
    except psycopg.Error as exc:
        actual = exc.sqlstate
        connection.rollback()
        if actual != expected_sqlstate:
            raise VerifierError(
                f"expected SQLSTATE {expected_sqlstate}, got {actual}: {exc}"
            ) from exc
        return
    connection.rollback()
    raise VerifierError(
        f"expected SQLSTATE {expected_sqlstate} but operation succeeded"
    )


# ---------------------------------------------------------------------------
# Finding 2C: guaranteed temporary worker UPDATE grant cleanup
# ---------------------------------------------------------------------------


@contextmanager
def temporary_worker_update_grant(obj: Engine | Connection) -> Iterator[None]:
    """Temporarily grant app_worker UPDATE on learning_events, always revoking."""
    with _connect(obj) as conn:
        conn.execute(text("grant update on public.learning_events to app_worker"))
        conn.commit()
    try:
        yield
    finally:
        with _connect(obj) as conn:
            conn.execute(text("revoke update on public.learning_events from app_worker"))
            conn.commit()


def worker_has_update(obj: Engine | Connection) -> bool:
    with _connect(obj) as conn:
        return conn.execute(
            text(
                "select has_table_privilege("
                "'app_worker', 'public.learning_events', 'UPDATE')"
            )
        ).scalar_one()


# ---------------------------------------------------------------------------
# Finding 3: complete fixture identifiers and lifecycle
# ---------------------------------------------------------------------------


def fixture_residue(obj: Engine | Connection) -> list[Violation]:
    violations: list[Violation] = []
    with _connect(obj) as conn:
        checks = (
            ("app_users", "select count(*) from public.app_users where id = :id", {"id": USER_A_ID}),
            ("app_users", "select count(*) from public.app_users where id = :id", {"id": USER_B_ID}),
            (
                "learning_entities",
                "select count(*) from public.learning_entities where canonical_key = :key",
                {"key": TEMP_CANONICAL_ENTITY_KEY},
            ),
            ("learner_preferences", "select count(*) from public.learner_preferences where user_id in (:a, :b)", {"a": USER_A_ID, "b": USER_B_ID}),
            ("jobs", "select count(*) from public.jobs where user_id in (:a, :b)", {"a": USER_A_ID, "b": USER_B_ID}),
            ("idempotency_records", "select count(*) from public.idempotency_records where user_id in (:a, :b)", {"a": USER_A_ID, "b": USER_B_ID}),
            ("learning_events", "select count(*) from public.learning_events where user_id in (:a, :b)", {"a": USER_A_ID, "b": USER_B_ID}),
        )
        for table, sql, params in checks:
            count = conn.execute(text(sql), params).scalar_one()
            if count:
                violations.append(
                    Violation(
                        "fixture_residue",
                        f"{table} still holds {count} fixture row(s)",
                        table=table,
                        count=count,
                    )
                )
    return violations


def seed_behavioral_fixtures(obj: Engine | Connection) -> None:
    cleanup_behavioral_fixtures(obj)
    with _connect(obj) as conn:
        conn.execute(
            text(
                "insert into public.learning_entities (canonical_key, entity_type, status) "
                "values (:key, 'TOPIC', 'REVIEWED')"
            ),
            {"key": TEMP_CANONICAL_ENTITY_KEY},
        )
        conn.execute(
            text(
                "insert into public.app_users (id, auth_provider, auth_subject) "
                "values (:a, 'test', 'p33-a'), (:b, 'test', 'p33-b')"
            ),
            {"a": USER_A_ID, "b": USER_B_ID},
        )
        conn.execute(
            text(
                "insert into public.learner_preferences "
                "(user_id, adventure_preference, preferred_effort, support_style) "
                "values (:a, 'BALANCED', '15_20_MIN', 'SMALL_HINT'), "
                "(:b, 'BALANCED', '15_20_MIN', 'SMALL_HINT')"
            ),
            {"a": USER_A_ID, "b": USER_B_ID},
        )
        conn.execute(
            text(
                "insert into public.jobs (user_id, job_type, status) "
                "values (:a, 'EVALUATION', 'PENDING')"
            ),
            {"a": USER_A_ID},
        )
        conn.execute(
            text(
                "insert into public.idempotency_records "
                "(user_id, idempotency_key, command_name, request_fingerprint, expires_at) "
                "values (:a, :key, 'bootstrap', 'sha256:p33', now() + interval '1 day')"
            ),
            {"a": USER_A_ID, "key": TEMP_IDEMPOTENCY_KEY},
        )
        conn.execute(
            text(
                "insert into public.learning_events "
                "(user_id, event_type, occurred_at, schema_version) "
                "values (:a, 'EXPLORATION_STARTED', now(), 1)"
            ),
            {"a": USER_A_ID},
        )
        conn.commit()


def cleanup_behavioral_fixtures(obj: Engine | Connection) -> None:
    """Remove fixtures through the maintenance path; safe when absent.

    ``learning_events`` is immutable to every identity except the
    ``app_maintenance`` owner of ``maintenance_delete_account(uuid)``, so the
    ledger is cleared through that SECURITY DEFINER routine rather than a raw
    DELETE.
    """
    with _connect(obj) as conn:
        for user_id in (USER_A_ID, USER_B_ID):
            conn.execute(
                text("select public.maintenance_delete_account(:id)"), {"id": user_id}
            )
        conn.execute(
            text(
                "delete from public.learning_entities where canonical_key = :key"
            ),
            {"key": TEMP_CANONICAL_ENTITY_KEY},
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Finding 4A: complete final zero-data gate
# ---------------------------------------------------------------------------


def application_row_violations(obj: Engine | Connection) -> list[Violation]:
    """Exact ``COUNT(*)`` for every Embyr application-data table; expect zero.

    No migration inserts persistent seed rows, so every table must be empty.
    """
    return exact_row_count_violations(obj, FINAL_0013_APPLICATION_TABLES)


# ---------------------------------------------------------------------------
# Finding 4B: complete orphan verification
# ---------------------------------------------------------------------------


def database_foreign_keys(obj: Engine | Connection) -> set[str]:
    with _connect(obj) as conn:
        return {
            row[0]
            for row in conn.execute(
                text(
                    """
                    select con.conname
                    from pg_constraint con
                    join pg_class child on child.oid = con.conrelid
                    join pg_namespace n on n.oid = child.relnamespace
                    where con.contype = 'f' and n.nspname = 'public'
                    """
                )
            )
        }


def foreign_key_violations(obj: Engine | Connection) -> list[Violation]:
    violations: list[Violation] = []
    actual = database_foreign_keys(obj)
    expected = set(EXPECTED_FOREIGN_KEYS)
    for name in sorted(expected - actual):
        violations.append(
            Violation("missing_foreign_key", f"expected FK {name} absent", table=name)
        )
    for name in sorted(actual - expected):
        violations.append(
            Violation("unexpected_foreign_key", f"unexpected FK {name}", table=name)
        )
    return violations


def _foreign_key_definitions(conn: Connection):
    return conn.execute(
        text(
            """
            select con.conname,
                   child.relname as child_table,
                   parent.relname as parent_table,
                   (
                     select array_agg(a.attname order by u.ord)
                     from unnest(con.conkey) with ordinality u(attnum, ord)
                     join pg_attribute a
                       on a.attrelid = con.conrelid and a.attnum = u.attnum
                   ) as child_columns,
                   (
                     select array_agg(a.attname order by u.ord)
                     from unnest(con.confkey) with ordinality u(attnum, ord)
                     join pg_attribute a
                       on a.attrelid = con.confrelid and a.attnum = u.attnum
                   ) as parent_columns
            from pg_constraint con
            join pg_class child on child.oid = con.conrelid
            join pg_class parent on parent.oid = con.confrelid
            join pg_namespace n on n.oid = child.relnamespace
            where con.contype = 'f' and n.nspname = 'public'
            order by con.conname
            """
        )
    ).all()


def orphan_violations(obj: Engine | Connection) -> list[Violation]:
    """Detect rows whose foreign-key parent is missing, for every FK."""
    violations: list[Violation] = []
    with _connect(obj) as conn:
        for fk in _foreign_key_definitions(conn):
            child_cols = list(fk.child_columns)
            parent_cols = list(fk.parent_columns)
            not_null = " and ".join(f"c.{col} is not null" for col in child_cols)
            join = " and ".join(
                f"p.{pc} = c.{cc}"
                for cc, pc in zip(child_cols, parent_cols)
            )
            sql = (
                f"select count(*) from public.{fk.child_table} c "
                f"where {not_null} and not exists ("
                f"select 1 from public.{fk.parent_table} p where {join})"
            )
            count = conn.execute(text(sql)).scalar_one()
            if count:
                violations.append(
                    Violation(
                        "orphan_rows",
                        f"{fk.conname}: {count} orphan row(s) in {fk.child_table}",
                        child_table=fk.child_table,
                        count=count,
                    )
                )
        for label, sql in EXTRA_ORPHAN_CHECKS:
            for relation, count in conn.execute(text(sql)).all():
                violations.append(
                    Violation(
                        "orphan_rows",
                        f"{label} ({relation}): {count} row(s)",
                        child_table=relation,
                        count=count,
                    )
                )
    return violations


# ---------------------------------------------------------------------------
# Catalog security inspection (post-upgrade)
# ---------------------------------------------------------------------------


def rls_violations(obj: Engine | Connection) -> list[Violation]:
    violations: list[Violation] = []
    with _connect(obj) as conn:
        rows = {
            row.relname: (row.relrowsecurity, row.relforcerowsecurity)
            for row in conn.execute(
                text(
                    """
                    select c.relname, c.relrowsecurity, c.relforcerowsecurity
                    from pg_class c
                    join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = 'public' and c.relkind = 'r'
                      and c.relname = any(:tables)
                    """
                ),
                {"tables": list(RLS_LEARNER_TABLES)},
            )
        }
        for table in RLS_LEARNER_TABLES:
            flags = rows.get(table)
            if flags != (True, True):
                violations.append(
                    Violation(
                        "rls_not_forced",
                        f"{table} ENABLE/FORCE RLS = {flags}",
                        table=table,
                    )
                )
        policy_count = conn.execute(
            text(
                """
                select count(*) from pg_policies
                where schemaname = 'public' and roles = '{app_backend}'
                  and cmd = 'ALL'
                """
            )
        ).scalar_one()
        if policy_count != len(RLS_LEARNER_TABLES):
            violations.append(
                Violation(
                    "policy_count",
                    f"expected {len(RLS_LEARNER_TABLES)} app_backend policies, "
                    f"found {policy_count}",
                )
            )
    return violations


def maintenance_function_violations(obj: Engine | Connection) -> list[Violation]:
    violations: list[Violation] = []
    with _connect(obj) as conn:
        row = conn.execute(
            text(
                """
                select pg_get_userbyid(p.proowner) as owner,
                       p.prosecdef as security_definer,
                       p.proconfig as config
                from pg_proc p
                join pg_namespace n on n.oid = p.pronamespace
                where n.nspname = 'public'
                  and p.proname = 'maintenance_delete_account'
                """
            )
        ).one_or_none()
        if row is None:
            return [Violation("missing_function", "maintenance_delete_account absent")]
        if row.owner != "app_maintenance":
            violations.append(
                Violation("function_owner", f"owner is {row.owner}", role=row.owner)
            )
        if row.security_definer is not True:
            violations.append(Violation("function_security", "not SECURITY DEFINER"))
        expected_path = ["search_path=pg_catalog, public, pg_temp"]
        if list(row.config or []) != expected_path:
            violations.append(
                Violation("function_search_path", f"search_path = {row.config}")
            )
        for role in ("public", *CLIENT_ROLES, "app_backend"):
            granted = conn.execute(
                text("select has_function_privilege(:role, :fn, 'EXECUTE')"),
                {"role": role, "fn": MAINTENANCE_FUNCTION},
            ).scalar_one()
            if granted:
                violations.append(
                    Violation(
                        "function_execute",
                        f"{role} unexpectedly has EXECUTE",
                        role=role,
                    )
                )
        worker_execute = conn.execute(
            text("select has_function_privilege('app_worker', :fn, 'EXECUTE')"),
            {"fn": MAINTENANCE_FUNCTION},
        ).scalar_one()
        if not worker_execute:
            violations.append(
                Violation("function_execute", "app_worker lacks EXECUTE", role="app_worker")
            )
    return violations


def ownership_violations(obj: Engine | Connection) -> list[Violation]:
    violations: list[Violation] = []
    with _connect(obj) as conn:
        rows = conn.execute(
            text(
                """
                select pg_get_userbyid(c.relowner) as owner, count(*) as n
                from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
                where n.nspname = 'public' and c.relkind = 'r'
                  and not exists (
                    select 1 from pg_depend d
                    where d.classid = 'pg_class'::regclass and d.objid = c.oid
                      and d.deptype = 'e'
                  )
                group by 1
                """
            )
        ).all()
        for owner, count in rows:
            if owner != "app_owner":
                violations.append(
                    Violation(
                        "object_owner",
                        f"{count} public tables owned by {owner}",
                        role=owner,
                        count=count,
                    )
                )
    return violations


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def _engine(url: str) -> Engine:
    from sqlalchemy import create_engine

    return create_engine(url)


def _require_env(name: str) -> str:
    import os

    value = os.environ.get(name)
    if not value:
        raise VerifierError(f"environment variable {name} is required")
    return value


def owner_readonly_preflight(owner_url: str) -> list[Violation]:
    """Connect as app_owner, explicit BEGIN READ ONLY, SELECT-only, ROLLBACK."""
    violations: list[Violation] = []
    with psycopg.connect(_psycopg_url(owner_url), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("begin read only")
            read_only = cur.execute("show transaction_read_only").fetchone()[0]
            if read_only != "on":
                violations.append(
                    Violation("owner_read_only", f"transaction_read_only = {read_only}")
                )
            current_user = cur.execute("select current_user").fetchone()[0]
            if current_user != "app_owner":
                violations.append(
                    Violation("owner_identity", f"current_user = {current_user}", role=current_user)
                )
            predicates = {
                "CONNECT": "select has_database_privilege('app_owner', current_database(), 'CONNECT')",
                "USAGE": "select has_schema_privilege('app_owner', 'public', 'USAGE')",
                "CREATE": "select has_schema_privilege('app_owner', 'public', 'CREATE')",
                "SET_ROLE_MAINTENANCE": (
                    "select exists (select 1 from pg_auth_members am "
                    "join pg_roles m on m.oid = am.member "
                    "join pg_roles g on g.oid = am.roleid "
                    "where m.rolname = 'app_owner' and g.rolname = 'app_maintenance' "
                    "and am.set_option)"
                ),
            }
            for label, sql in predicates.items():
                if not cur.execute(sql).fetchone()[0]:
                    violations.append(
                        Violation("owner_privilege", f"app_owner lacks {label}")
                    )
            cur.execute("rollback")
    return violations


def run_preflight(admin_url: str, owner_url: str) -> Report:
    report = Report("preflight")
    engine = _engine(admin_url)
    report.violations += inventory_violations(engine, LEGACY_0006_APPLICATION_TABLES)
    report.violations += exact_row_count_violations(
        engine, LEGACY_0006_APPLICATION_TABLES
    )
    report.violations += platform_count_violations(engine)
    report.violations += owner_readonly_preflight(owner_url)
    return report


def run_post_upgrade(admin_url: str) -> Report:
    report = Report("post-upgrade")
    engine = _engine(admin_url)
    report.violations += ownership_violations(engine)
    report.violations += rls_violations(engine)
    report.violations += maintenance_function_violations(engine)
    report.violations += client_privilege_violations(engine)
    report.violations += function_default_acl_violations(engine)
    return report


def run_behavioral(
    admin_url: str, backend_url: str, worker_url: str
) -> Report:
    report = Report("behavioral")
    engine = _engine(admin_url)
    seed_behavioral_fixtures(engine)
    try:
        with psycopg.connect(_psycopg_url(backend_url)) as backend:
            verifier_expectations = (
                ("42501", "insert into public.learner_preferences "
                          "(user_id, adventure_preference, preferred_effort, support_style) "
                          f"values ('{USER_B_ID}', 'BALANCED', '15_20_MIN', 'SMALL_HINT')"),
                ("22P02", "select nullif(current_setting('app.user_id', true), '')::uuid"),
            )
            for state, sql in verifier_expectations:
                with backend.cursor() as cur:
                    if state == "42501":
                        cur.execute(
                            "select set_config('app.user_id', %s, true)", (USER_A_ID,)
                        )
                    else:
                        cur.execute(
                            "select set_config('app.user_id', 'not-a-uuid', true)"
                        )
                try:
                    expect_sqlstate(backend, state, sql)
                except VerifierError as exc:
                    report.violations.append(Violation("behavioral", str(exc)))
        with psycopg.connect(_psycopg_url(worker_url)) as worker:
            try:
                expect_sqlstate(
                    worker,
                    "22004",
                    "select public.maintenance_delete_account(null)",
                )
            except VerifierError as exc:
                report.violations.append(Violation("behavioral", str(exc)))
        with temporary_worker_update_grant(engine):
            if not worker_has_update(engine):
                report.violations.append(
                    Violation("behavioral", "temporary worker UPDATE grant ineffective")
                )
            with psycopg.connect(_psycopg_url(worker_url)) as worker:
                try:
                    expect_sqlstate(
                        worker,
                        "55000",
                        "update public.learning_events set schema_version = 2",
                    )
                except VerifierError as exc:
                    report.violations.append(Violation("behavioral", str(exc)))
        if worker_has_update(engine):
            report.violations.append(
                Violation("behavioral", "worker UPDATE not revoked after cleanup")
            )
    finally:
        cleanup_behavioral_fixtures(engine)
    return report


def run_final(admin_url: str) -> Report:
    report = Report("final")
    engine = _engine(admin_url)
    report.violations += application_row_violations(engine)
    report.violations += fixture_residue(engine)
    report.violations += foreign_key_violations(engine)
    report.violations += orphan_violations(engine)
    report.violations += platform_count_violations(engine)
    with _connect(engine) as conn:
        revision = conn.execute(
            text("select version_num from public.alembic_version")
        ).scalar_one_or_none()
    if revision != "0013_default_acl_hardening":
        report.violations.append(
            Violation("revision", f"final revision is {revision}")
        )
    return report


def _emit(report: Report, as_json: bool) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "mode": report.mode,
                    "ok": report.ok,
                    "violations": [v.__dict__ for v in report.violations],
                },
                indent=2,
            )
        )
    else:
        print(f"mode={report.mode} violations={len(report.violations)}")
        for violation in report.violations:
            print(f"  {violation}")
        print("PASS" if report.ok else "FAIL")
    return 0 if report.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Issue #33 hosted verifier")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true")
    group.add_argument("--post-upgrade", action="store_true")
    group.add_argument("--behavioral", action="store_true")
    group.add_argument("--final", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.preflight:
        report = run_preflight(_require_env(ADMIN_ENV), _require_env(OWNER_ENV))
    elif args.post_upgrade:
        report = run_post_upgrade(_require_env(ADMIN_ENV))
    elif args.behavioral:
        report = run_behavioral(
            _require_env(ADMIN_ENV),
            _require_env(BACKEND_ENV),
            _require_env(WORKER_ENV),
        )
    else:
        report = run_final(_require_env(ADMIN_ENV))
    return _emit(report, args.json)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
