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

# Supabase always provisions these roles. Hosted verification must fail closed
# when any of them is absent rather than silently skipping its privilege checks.
REQUIRED_CLIENT_ROLES: tuple[str, ...] = CLIENT_ROLES

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

# ---------------------------------------------------------------------------
# Finding 1: exact preflight starting-state contract
# ---------------------------------------------------------------------------

PREFLIGHT_REVISION = "0006_practical_artifacts"
FINAL_REVISION = "0013_default_acl_hardening"


@dataclass(frozen=True)
class ExtensionSpec:
    name: str
    schema: str


EXPECTED_EXTENSIONS: tuple[ExtensionSpec, ...] = (
    ExtensionSpec("vector", "public"),
    ExtensionSpec("pgcrypto", "extensions"),
)


@dataclass(frozen=True)
class RoleSpec:
    name: str
    login: bool
    superuser: bool
    bypassrls: bool
    createrole: bool
    createdb: bool
    replication: bool


EXPECTED_ROLES: tuple[RoleSpec, ...] = (
    RoleSpec("app_owner", True, False, False, False, False, False),
    RoleSpec("app_backend", True, False, False, False, False, False),
    RoleSpec("app_worker", True, False, True, False, False, False),
    RoleSpec("app_maintenance", False, False, True, False, False, False),
)

RUNTIME_ROLES: tuple[str, ...] = ("app_backend", "app_worker", "app_maintenance")


@dataclass(frozen=True)
class MembershipSpec:
    member: str
    granted: str
    admin: bool
    inherit: bool
    set: bool


EXPECTED_OWNER_MEMBERSHIP = MembershipSpec(
    "app_owner", "app_maintenance", admin=False, inherit=False, set=True
)

# ---------------------------------------------------------------------------
# Finding 2: exact RLS policy contract (derived from frozen 0012)
# ---------------------------------------------------------------------------

EXPECTED_POLICY_ROLES: tuple[str, ...] = ("app_backend",)
EXPECTED_POLICY_COMMAND = "ALL"
# Exact pg_get_expr rendering of 0012's predicate for polqual/polwithcheck on
# PostgreSQL 16 and 17. ``_normalize_predicate`` removes only whitespace and the
# semantically-irrelevant ``::text`` annotations, and only outside quoted
# literals/identifiers, before comparison.
EXPECTED_POLICY_PREDICATE = (
    "(user_id = (NULLIF(current_setting('app.user_id'::text, true), "
    "''::text))::uuid)"
)

# ---------------------------------------------------------------------------
# Finding 4: exact foreign-key contract (derived from frozen 0001-0011a)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ForeignKeySpec:
    """One frozen foreign-key relationship.

    ``child_schema``/``parent_schema`` are always ``public``, ``on_update`` is
    always ``NO ACTION``, ``match_type`` is always ``SIMPLE``, and every
    constraint is NOT DEFERRABLE on the frozen schema. Those invariants are the
    documented defaults below, so each entry still states the full tuple.
    """

    name: str
    child_table: str
    child_columns: tuple[str, ...]
    parent_table: str
    parent_columns: tuple[str, ...]
    on_delete: str
    child_schema: str = "public"
    parent_schema: str = "public"
    on_update: str = "NO ACTION"
    match_type: str = "SIMPLE"
    deferrable: bool = False
    deferred: bool = False


EXPECTED_FOREIGN_KEY_CONTRACT: tuple[ForeignKeySpec, ...] = (
    ForeignKeySpec('fk_account_operation_requests_idempotency_owner', 'account_operation_requests', ("user_id", "idempotency_record_id"), 'idempotency_records', ("user_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_account_operation_requests_user_id_app_users', 'account_operation_requests', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_artifact_analyses_artifact_owner', 'artifact_analyses', ("user_id", "artifact_id"), 'artifacts', ("user_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_artifacts_exploration_challenge_owner_version', 'artifacts', ("user_id", "exploration_id", "practical_challenge_id", "practical_challenge_version_id"), 'explorations', ("user_id", "id", "practical_challenge_id", "practical_challenge_version_id"), 'NO ACTION'),
    ForeignKeySpec('fk_artifacts_media_owner', 'artifacts', ("user_id", "media_object_id"), 'media_objects', ("user_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_artifacts_reflection_owner_exploration', 'artifacts', ("user_id", "exploration_id", "reflection_id"), 'reflections', ("user_id", "exploration_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_assessment_interactions_objective_id_learning_objectives', 'assessment_interactions', ("objective_id",), 'learning_objectives', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_assessment_interactions_session_owner', 'assessment_interactions', ("user_id", "assessment_session_id"), 'assessment_sessions', ("user_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_assessment_responses_interaction_owner_session', 'assessment_responses', ("user_id", "assessment_session_id", "interaction_id"), 'assessment_interactions', ("user_id", "assessment_session_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_assessment_sessions_exploration_owner_version', 'assessment_sessions', ("user_id", "exploration_id", "entity_version"), 'explorations', ("user_id", "id", "entity_version"), 'CASCADE'),
    ForeignKeySpec('fk_assessment_support_requests_interaction_owner_session', 'assessment_support_requests', ("user_id", "assessment_session_id", "interaction_id"), 'assessment_interactions', ("user_id", "assessment_session_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_claims_entity_id_learning_entities', 'claims', ("entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_curiosity_stories_user_id_app_users', 'curiosity_stories', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_entity_domains_domain_id_learning_entities', 'entity_domains', ("domain_id",), 'learning_entities', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_entity_domains_entity_id_learning_entities', 'entity_domains', ("entity_id",), 'learning_entities', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_entity_embeddings_entity_version', 'entity_embeddings', ("entity_id", "entity_version"), 'learning_entity_versions', ("entity_id", "version"), 'NO ACTION'),
    ForeignKeySpec('fk_evaluation_runs_response_owner', 'evaluation_runs', ("user_id", "response_id"), 'assessment_responses', ("user_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_evaluation_runs_superseded_owner_response', 'evaluation_runs', ("user_id", "supersedes_id", "response_id"), 'evaluation_runs', ("user_id", "id", "response_id"), 'NO ACTION'),
    ForeignKeySpec('fk_explicit_interest_preferences_entity_id_learning_entities', 'explicit_interest_preferences', ("entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_explicit_interest_preferences_user_id_app_users', 'explicit_interest_preferences', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_explorations_entity_version', 'explorations', ("entity_id", "entity_version"), 'learning_entity_versions', ("entity_id", "version"), 'NO ACTION'),
    ForeignKeySpec('fk_explorations_practical_challenge_version', 'explorations', ("practical_challenge_id", "practical_challenge_version_id"), 'practical_challenge_versions', ("challenge_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_explorations_recommendation_owner', 'explorations', ("user_id", "recommendation_id"), 'recommendations', ("user_id", "id"), 'SET NULL'),
    ForeignKeySpec('fk_explorations_user_id_app_users', 'explorations', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_idempotency_records_user_id_app_users', 'idempotency_records', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_jobs_user_id_app_users', 'jobs', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learner_challenge_state_area_id_learning_entities', 'learner_challenge_state', ("area_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_learner_challenge_state_user_id_app_users', 'learner_challenge_state', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learner_confidence_state_entity_id_learning_entities', 'learner_confidence_state', ("entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_learner_confidence_state_user_id_app_users', 'learner_confidence_state', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learner_interest_state_entity_id_learning_entities', 'learner_interest_state', ("entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_learner_interest_state_user_id_app_users', 'learner_interest_state', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learner_objective_state_objective_id_learning_objectives', 'learner_objective_state', ("objective_id",), 'learning_objectives', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_learner_objective_state_user_id_app_users', 'learner_objective_state', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learner_preferences_user_id_app_users', 'learner_preferences', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learner_retention_state_entity_id_learning_entities', 'learner_retention_state', ("entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_learner_retention_state_user_id_app_users', 'learner_retention_state', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learner_worlds_user_id_app_users', 'learner_worlds', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learning_entities_current_version', 'learning_entities', ("id", "current_version"), 'learning_entity_versions', ("entity_id", "version"), 'NO ACTION'),
    ForeignKeySpec('fk_learning_entity_versions_entity_id_learning_entities', 'learning_entity_versions', ("entity_id",), 'learning_entities', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learning_events_artifact_owner', 'learning_events', ("user_id", "artifact_id"), 'artifacts', ("user_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_learning_events_assessment_session_owner', 'learning_events', ("user_id", "assessment_session_id"), 'assessment_sessions', ("user_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_learning_events_command_id_idempotency_records', 'learning_events', ("command_id",), 'idempotency_records', ("id",), 'SET NULL'),
    ForeignKeySpec('fk_learning_events_device_owner', 'learning_events', ("device_id", "user_id"), 'user_devices', ("id", "user_id"), 'NO ACTION'),
    ForeignKeySpec('fk_learning_events_entity_id_learning_entities', 'learning_events', ("entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_learning_events_exploration_owner', 'learning_events', ("user_id", "exploration_id"), 'explorations', ("user_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_learning_events_user_id_app_users', 'learning_events', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learning_evidence_evaluation_owner_source', 'learning_evidence', ("user_id", "evaluation_run_id", "source_id"), 'evaluation_runs', ("user_id", "id", "response_id"), 'NO ACTION'),
    ForeignKeySpec('fk_learning_evidence_objective_entity', 'learning_evidence', ("entity_id", "objective_id"), 'learning_objectives', ("entity_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_learning_evidence_user_id_app_users', 'learning_evidence', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_learning_objectives_entity_version', 'learning_objectives', ("entity_id", "entity_version"), 'learning_entity_versions', ("entity_id", "version"), 'NO ACTION'),
    ForeignKeySpec('fk_media_objects_upload_owner', 'media_objects', ("user_id", "upload_id"), 'upload_sessions', ("user_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_misconceptions_entity_id_learning_entities', 'misconceptions', ("entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_misconceptions_objective_id_learning_objectives', 'misconceptions', ("objective_id",), 'learning_objectives', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_ontology_edges_source_entity_id_learning_entities', 'ontology_edges', ("source_entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_ontology_edges_target_entity_id_learning_entities', 'ontology_edges', ("target_entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_practical_challenge_versions_challenge_entity', 'practical_challenge_versions', ("challenge_id", "entity_id"), 'practical_challenges', ("id", "entity_id"), 'NO ACTION'),
    ForeignKeySpec('fk_practical_challenge_versions_entity_version', 'practical_challenge_versions', ("entity_id", "entity_version"), 'learning_entity_versions', ("entity_id", "version"), 'NO ACTION'),
    ForeignKeySpec('fk_practical_challenges_entity_id_learning_entities', 'practical_challenges', ("entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_recommendations_challenge_id_practical_challenges', 'recommendations', ("challenge_id",), 'practical_challenges', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_recommendations_entity_version', 'recommendations', ("entity_id", "entity_version"), 'learning_entity_versions', ("entity_id", "version"), 'NO ACTION'),
    ForeignKeySpec('fk_recommendations_user_id_app_users', 'recommendations', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_reflections_exploration_owner_entity', 'reflections', ("user_id", "exploration_id", "entity_id"), 'explorations', ("user_id", "id", "entity_id"), 'CASCADE'),
    ForeignKeySpec('fk_state_evidence_links_event_owner', 'state_evidence_links', ("user_id", "learning_event_id"), 'learning_events', ("user_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_state_evidence_links_evidence_owner', 'state_evidence_links', ("user_id", "learning_evidence_id"), 'learning_evidence', ("user_id", "id"), 'NO ACTION'),
    ForeignKeySpec('fk_state_evidence_links_user_id_app_users', 'state_evidence_links', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_upload_sessions_user_id_app_users', 'upload_sessions', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_user_devices_user_id_app_users', 'user_devices', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_user_motivations_user_id_app_users', 'user_motivations', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_world_artifacts_artifact_owner', 'world_artifacts', ("user_id", "artifact_id"), 'artifacts', ("user_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_world_artifacts_region_owner', 'world_artifacts', ("user_id", "region_id"), 'world_regions', ("user_id", "id"), 'SET NULL'),
    ForeignKeySpec('fk_world_artifacts_user_id_app_users', 'world_artifacts', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_world_artifacts_world_owner', 'world_artifacts', ("user_id", "world_id"), 'learner_worlds', ("user_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_world_changes_user_id_app_users', 'world_changes', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_world_changes_world_owner', 'world_changes', ("user_id", "world_id"), 'learner_worlds', ("user_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_world_connections_ontology_edge_id_ontology_edges', 'world_connections', ("ontology_edge_id",), 'ontology_edges', ("id",), 'SET NULL'),
    ForeignKeySpec('fk_world_connections_source_node_owner', 'world_connections', ("user_id", "source_world_node_id"), 'world_nodes', ("user_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_world_connections_target_node_owner', 'world_connections', ("user_id", "target_world_node_id"), 'world_nodes', ("user_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_world_connections_user_id_app_users', 'world_connections', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_world_connections_world_owner', 'world_connections', ("user_id", "world_id"), 'learner_worlds', ("user_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_world_nodes_entity_id_learning_entities', 'world_nodes', ("entity_id",), 'learning_entities', ("id",), 'NO ACTION'),
    ForeignKeySpec('fk_world_nodes_region_owner', 'world_nodes', ("user_id", "region_id"), 'world_regions', ("user_id", "id"), 'SET NULL'),
    ForeignKeySpec('fk_world_nodes_user_id_app_users', 'world_nodes', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_world_nodes_world_owner', 'world_nodes', ("user_id", "world_id"), 'learner_worlds', ("user_id", "id"), 'CASCADE'),
    ForeignKeySpec('fk_world_regions_primary_domain_id_learning_entities', 'world_regions', ("primary_domain_id",), 'learning_entities', ("id",), 'SET NULL'),
    ForeignKeySpec('fk_world_regions_user_id_app_users', 'world_regions', ("user_id",), 'app_users', ("id",), 'CASCADE'),
    ForeignKeySpec('fk_world_regions_world_owner', 'world_regions', ("user_id", "world_id"), 'learner_worlds', ("user_id", "id"), 'CASCADE'),

)

EXPECTED_FOREIGN_KEYS: tuple[str, ...] = tuple(
    spec.name for spec in EXPECTED_FOREIGN_KEY_CONTRACT
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
    field: str | None = None
    expected: str | None = None
    actual: str | None = None

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


def missing_client_role_violations(obj: Engine | Connection) -> list[Violation]:
    """Every required Supabase client role must exist for hosted verification."""
    with _connect(obj) as conn:
        present = {
            row[0]
            for row in conn.execute(
                text("select rolname from pg_roles where rolname = any(:roles)"),
                {"roles": list(REQUIRED_CLIENT_ROLES)},
            )
        }
    return [
        Violation(
            "missing_client_role",
            f"missing required role: {role}",
            role=role,
            field="presence",
            expected="present",
            actual="absent",
        )
        for role in REQUIRED_CLIENT_ROLES
        if role not in present
    ]


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


def _effective_grant_principals(
    conn: Connection,
    grants: Sequence,
    existing_roles: Sequence[str],
) -> list[tuple[str, str, str]]:
    """Resolve each ``(grantee_oid, grantee_name, privilege)`` grant to callers.

    A grant to ``PUBLIC`` (grantee OID 0) reaches every principal; a grant to a
    named role reaches that role and every client role that can use it through
    role membership (``pg_has_role(..., 'USAGE')``), so an intermediary helper
    role cannot launder privileges past the checker.
    """
    effective: list[tuple[str, str, str]] = []
    for grantee_oid, grantee_name, privilege in grants:
        if grantee_oid == 0:
            effective.append(("PUBLIC", grantee_name, privilege))
            for client in existing_roles:
                effective.append((client, grantee_name, privilege))
            continue
        for client in existing_roles:
            inherited = conn.execute(
                text("select pg_has_role(:client, :grantee, 'USAGE')"),
                {"client": client, "grantee": grantee_name},
            ).scalar_one()
            if inherited:
                effective.append((client, grantee_name, privilege))
    return effective


def function_default_acl_violations(obj: Engine | Connection) -> list[Violation]:
    """Unsafe future default privileges for app_owner.

    Handles the global function default specially: when no explicit
    ``pg_default_acl`` row exists, PostgreSQL's built-in
    ``acldefault('f', owner_oid)`` still grants ``PUBLIC EXECUTE``. It also
    resolves *effective* reachability: a grant to an intermediary role that a
    client can ``USAGE`` is reported against that client.
    """
    violations: list[Violation] = []
    with _connect(obj) as conn:
        owner_oid = conn.execute(
            text("select oid from pg_roles where rolname = 'app_owner'")
        ).scalar_one_or_none()
        if owner_oid is None:
            return [
                Violation("missing_role", "app_owner role is absent")
            ]
        existing_roles = [
            role
            for role in CLIENT_ROLES
            if conn.execute(
                text("select 1 from pg_roles where rolname = :role"),
                {"role": role},
            ).scalar_one_or_none()
            is not None
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
                """
            ),
            {"owner": owner_oid},
        ).all()
        for principal, grantee_name, privilege in _effective_grant_principals(
            conn, global_grants, existing_roles
        ):
            violations.append(
                Violation(
                    "default_acl_function_global",
                    f"global function default grants {privilege} to "
                    f"{grantee_name}, effectively reachable by {principal}",
                    role=principal,
                    privilege=privilege,
                    actual=grantee_name,
                )
            )

        # public-schema-specific function defaults (explicit rows only).
        schema_grants = conn.execute(
            text(
                """
                select acl.grantee, coalesce(g.rolname, 'PUBLIC') as grantee_name,
                       acl.privilege_type
                from pg_default_acl d
                cross join lateral aclexplode(d.defaclacl) acl
                left join pg_roles g on g.oid = acl.grantee
                join pg_namespace n on n.oid = d.defaclnamespace
                where d.defaclrole = :owner
                  and d.defaclobjtype = 'f'
                  and n.nspname = 'public'
                  and acl.privilege_type = 'EXECUTE'
                """
            ),
            {"owner": owner_oid},
        ).all()
        for principal, grantee_name, privilege in _effective_grant_principals(
            conn, schema_grants, existing_roles
        ):
            violations.append(
                Violation(
                    "default_acl_function_schema",
                    f"public-schema function default grants {privilege} to "
                    f"{grantee_name}, effectively reachable by {principal}",
                    role=principal,
                    privilege=privilege,
                    actual=grantee_name,
                )
            )

        # table and sequence defaults, resolved for effective client reach.
        object_grants = conn.execute(
            text(
                """
                select d.defaclobjtype, acl.grantee,
                       coalesce(g.rolname, 'PUBLIC') as grantee_name,
                       acl.privilege_type
                from pg_default_acl d
                cross join lateral aclexplode(d.defaclacl) acl
                left join pg_roles g on g.oid = acl.grantee
                where d.defaclrole = :owner
                  and d.defaclobjtype in ('r', 'S')
                """
            ),
            {"owner": owner_oid},
        ).all()
        by_objtype: dict[str, list] = {}
        for row in object_grants:
            by_objtype.setdefault(row.defaclobjtype, []).append(
                (row.grantee, row.grantee_name, row.privilege_type)
            )
        for objtype, rows in by_objtype.items():
            for principal, grantee_name, privilege in _effective_grant_principals(
                conn, rows, existing_roles
            ):
                violations.append(
                    Violation(
                        "default_acl_object",
                        f"{objtype} default grants {privilege} to {grantee_name}, "
                        f"effectively reachable by {principal}",
                        role=principal,
                        privilege=privilege,
                        actual=grantee_name,
                    )
                )
    return violations


# ---------------------------------------------------------------------------
# Finding 2B: committed expected-SQLSTATE harness
# ---------------------------------------------------------------------------


class _UnexpectedSuccess(Exception):
    """Internal marker forcing the helper's transaction scope to roll back."""


def expect_sqlstate(
    connection: psycopg.Connection,
    expected_sqlstate: str,
    sql: str,
    params: Sequence | dict | None = None,
) -> None:
    """Assert ``sql`` raises exactly ``expected_sqlstate``; leave conn reusable.

    The operation is bounded by its own transaction scope. psycopg3's
    ``connection.transaction()`` opens a real transaction when none is active
    and a SAVEPOINT when the caller already has one, so caller work that
    precedes the helper is never rolled back. Raising from inside the block
    forces that scope to roll back for every outcome, including unexpected
    success, while leaving any outer transaction usable.
    """
    if connection.autocommit:
        raise VerifierError("expect_sqlstate requires a non-autocommit connection")
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(sql, params or ())
            raise _UnexpectedSuccess
    except _UnexpectedSuccess as exc:
        raise VerifierError(
            f"expected SQLSTATE {expected_sqlstate} but operation succeeded"
        ) from exc
    except psycopg.Error as exc:
        actual = exc.sqlstate
        if actual != expected_sqlstate:
            raise VerifierError(
                f"expected SQLSTATE {expected_sqlstate}, got {actual}: {exc}"
            ) from exc
        return


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


_FK_ON_UPDATE = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}
_FK_ON_DELETE = _FK_ON_UPDATE
_FK_MATCH = {"f": "FULL", "p": "PARTIAL", "s": "SIMPLE"}


def database_foreign_key_contract(
    obj: Engine | Connection,
) -> dict[str, ForeignKeySpec]:
    """Full ordered foreign-key tuples from the live catalog."""
    with _connect(obj) as conn:
        rows = conn.execute(
            text(
                """
                select con.conname,
                       ns.nspname as child_schema,
                       child.relname as child_table,
                       (
                         select array_agg(a.attname order by u.ord)
                         from unnest(con.conkey) with ordinality u(attnum, ord)
                         join pg_attribute a
                           on a.attrelid = con.conrelid and a.attnum = u.attnum
                       ) as child_columns,
                       pns.nspname as parent_schema,
                       parent.relname as parent_table,
                       (
                         select array_agg(a.attname order by u.ord)
                         from unnest(con.confkey) with ordinality u(attnum, ord)
                         join pg_attribute a
                           on a.attrelid = con.confrelid and a.attnum = u.attnum
                       ) as parent_columns,
                       con.confupdtype, con.confdeltype, con.confmatchtype,
                       con.condeferrable, con.condeferred
                from pg_constraint con
                join pg_class child on child.oid = con.conrelid
                join pg_namespace ns on ns.oid = child.relnamespace
                join pg_class parent on parent.oid = con.confrelid
                join pg_namespace pns on pns.oid = parent.relnamespace
                where con.contype = 'f' and ns.nspname = 'public'
                order by con.conname
                """
            )
        ).all()
    return {
        row.conname: ForeignKeySpec(
            name=row.conname,
            child_schema=row.child_schema,
            child_table=row.child_table,
            child_columns=tuple(row.child_columns),
            parent_schema=row.parent_schema,
            parent_table=row.parent_table,
            parent_columns=tuple(row.parent_columns),
            on_update=_FK_ON_UPDATE[row.confupdtype],
            on_delete=_FK_ON_DELETE[row.confdeltype],
            match_type=_FK_MATCH[row.confmatchtype],
            deferrable=bool(row.condeferrable),
            deferred=bool(row.condeferred),
        )
        for row in rows
    }


def foreign_key_violations(obj: Engine | Connection) -> list[Violation]:
    """Compare the live foreign-key contract, field by field, to the freeze."""
    violations: list[Violation] = []
    actual = database_foreign_key_contract(obj)
    expected = {spec.name: spec for spec in EXPECTED_FOREIGN_KEY_CONTRACT}
    for name in sorted(set(expected) - set(actual)):
        violations.append(
            Violation("missing_foreign_key", f"expected FK {name} absent", table=name)
        )
    for name in sorted(set(actual) - set(expected)):
        violations.append(
            Violation("unexpected_foreign_key", f"unexpected FK {name}", table=name)
        )
    for name in sorted(set(actual) & set(expected)):
        want = expected[name]
        got = actual[name]
        for spec_field in ForeignKeySpec.__dataclass_fields__:
            want_value = getattr(want, spec_field)
            got_value = getattr(got, spec_field)
            if want_value != got_value:
                violations.append(
                    Violation(
                        "foreign_key_definition",
                        f"{name}: {spec_field} mismatch",
                        table=name,
                        field=spec_field,
                        expected=str(want_value),
                        actual=str(got_value),
                    )
                )
    return violations


def final_foreign_key_violations(obj: Engine | Connection) -> list[Violation]:
    """FK semantic contract first; orphan detection only if it holds."""
    violations = foreign_key_violations(obj)
    if violations:
        return violations
    return orphan_violations(obj)



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


def _normalize_predicate(expression: str | None) -> str | None:
    """Canonicalize a ``pg_get_expr`` predicate without touching literals.

    Outside quoted strings/identifiers the scanner removes whitespace and the
    catalog-added ``::text`` casts only. The exact bytes inside single-quoted
    strings (including ``''`` escapes), double-quoted identifiers, and
    dollar-quoted strings are copied verbatim. Parentheses are preserved, so a
    changed literal such as ``''`` -> ``'::text'`` can never compare equal.
    """
    if expression is None:
        return None
    out: list[str] = []
    index = 0
    length = len(expression)
    dollar_tag: str | None = None
    in_single = False
    in_double = False
    while index < length:
        char = expression[index]
        if dollar_tag is not None:
            if expression.startswith(dollar_tag, index):
                out.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                out.append(char)
                index += 1
            continue
        if in_single:
            out.append(char)
            if char == "'":
                if index + 1 < length and expression[index + 1] == "'":
                    out.append("'")
                    index += 2
                    continue
                in_single = False
            index += 1
            continue
        if in_double:
            out.append(char)
            if char == '"':
                if index + 1 < length and expression[index + 1] == '"':
                    out.append('"')
                    index += 2
                    continue
                in_double = False
            index += 1
            continue
        if char == "'":
            in_single = True
            out.append(char)
            index += 1
            continue
        if char == '"':
            in_double = True
            out.append(char)
            index += 1
            continue
        if char == "$":
            tag_end = expression.find("$", index + 1)
            if tag_end != -1:
                tag_body = expression[index + 1 : tag_end]
                if all(part.isalnum() or part == "_" for part in tag_body):
                    dollar_tag = expression[index : tag_end + 1]
                    out.append(dollar_tag)
                    index = tag_end + 1
                    continue
            out.append(char)
            index += 1
            continue
        if char.isspace():
            index += 1
            continue
        if expression.startswith("::text", index) and (
            index + 6 >= length
            or not (expression[index + 6].isalnum() or expression[index + 6] == "_")
        ):
            index += 6
            continue
        out.append(char.lower())
        index += 1
    return "".join(out)


def rls_violations(obj: Engine | Connection) -> list[Violation]:
    violations: list[Violation] = []
    expected_predicate = _normalize_predicate(EXPECTED_POLICY_PREDICATE)
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

        policies_by_table: dict[str, list] = {}
        for policy in conn.execute(
            text(
                """
                select tablename, policyname, cmd, roles, qual, with_check
                from pg_policies
                where schemaname = 'public' and tablename = any(:tables)
                """
            ),
            {"tables": list(RLS_LEARNER_TABLES)},
        ).all():
            policies_by_table.setdefault(policy.tablename, []).append(policy)

        for table in RLS_LEARNER_TABLES:
            expected_name = f"{table}_user_policy"
            table_policies = policies_by_table.get(table, [])
            names = sorted(policy.policyname for policy in table_policies)
            if names != [expected_name]:
                violations.append(
                    Violation(
                        "policy_inventory",
                        f"{table} policies = {names}, expected ['{expected_name}']",
                        table=table,
                        field="policyname",
                        expected=str([expected_name]),
                        actual=str(names),
                    )
                )
            match = next(
                (
                    policy
                    for policy in table_policies
                    if policy.policyname == expected_name
                ),
                None,
            )
            if match is None:
                continue
            if match.cmd != EXPECTED_POLICY_COMMAND:
                violations.append(
                    Violation(
                        "policy_command",
                        f"{table}.{expected_name}: cmd = {match.cmd}",
                        table=table,
                        field="cmd",
                        expected=EXPECTED_POLICY_COMMAND,
                        actual=match.cmd,
                    )
                )
            actual_roles = sorted(match.roles or [])
            if actual_roles != sorted(EXPECTED_POLICY_ROLES):
                violations.append(
                    Violation(
                        "policy_roles",
                        f"{table}.{expected_name}: roles = {actual_roles}",
                        table=table,
                        field="roles",
                        expected=str(sorted(EXPECTED_POLICY_ROLES)),
                        actual=str(actual_roles),
                    )
                )
            for field_name, actual_expr in (
                ("qual", match.qual),
                ("with_check", match.with_check),
            ):
                if _normalize_predicate(actual_expr) != expected_predicate:
                    violations.append(
                        Violation(
                            "policy_predicate",
                            f"{table}.{expected_name}: {field_name} predicate "
                            f"mismatch",
                            table=table,
                            field=field_name,
                            expected=EXPECTED_POLICY_PREDICATE,
                            actual=actual_expr,
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
        existing_clients = [
            role
            for role in CLIENT_ROLES
            if conn.execute(
                text("select 1 from pg_roles where rolname = :role"),
                {"role": role},
            ).scalar_one_or_none()
            is not None
        ]
        for role in ("public", *existing_clients, "app_backend"):
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


def preflight_revision_violations(obj: Engine | Connection) -> list[Violation]:
    """The legacy starting state must be exactly ``0006_practical_artifacts``."""
    with _connect(obj) as conn:
        revision = conn.execute(
            text("select version_num from public.alembic_version")
        ).scalar_one_or_none()
    if revision != PREFLIGHT_REVISION:
        return [
            Violation(
                "preflight_revision",
                f"revision is {revision}, expected {PREFLIGHT_REVISION}",
                field="alembic_version.version_num",
                expected=PREFLIGHT_REVISION,
                actual=str(revision),
            )
        ]
    return []


def preflight_extension_violations(obj: Engine | Connection) -> list[Violation]:
    violations: list[Violation] = []
    with _connect(obj) as conn:
        present = {
            row.extname: row.schema
            for row in conn.execute(
                text(
                    "select e.extname, n.nspname as schema "
                    "from pg_extension e "
                    "join pg_namespace n on n.oid = e.extnamespace"
                )
            )
        }
    for spec in EXPECTED_EXTENSIONS:
        actual = present.get(spec.name)
        if actual is None:
            violations.append(
                Violation(
                    "preflight_extension",
                    f"extension {spec.name} absent, expected schema {spec.schema}",
                    table=spec.name,
                    field="presence",
                    expected="present",
                    actual="absent",
                )
            )
        elif actual != spec.schema:
            violations.append(
                Violation(
                    "preflight_extension",
                    f"extension {spec.name} in schema {actual}, "
                    f"expected {spec.schema}",
                    table=spec.name,
                    field="schema",
                    expected=spec.schema,
                    actual=actual,
                )
            )
    return violations


def preflight_role_violations(obj: Engine | Connection) -> list[Violation]:
    """Complete frozen role topology, attributes, and membership model."""
    violations: list[Violation] = []
    role_names = [spec.name for spec in EXPECTED_ROLES]
    with _connect(obj) as conn:
        rows = {
            row.rolname: row
            for row in conn.execute(
                text(
                    "select rolname, rolcanlogin, rolsuper, rolbypassrls, "
                    "rolcreaterole, rolcreatedb, rolreplication "
                    "from pg_roles where rolname = any(:roles)"
                ),
                {"roles": role_names},
            )
        }
        for spec in EXPECTED_ROLES:
            row = rows.get(spec.name)
            if row is None:
                violations.append(
                    Violation(
                        "preflight_role",
                        f"role {spec.name} absent",
                        role=spec.name,
                        field="presence",
                        expected="present",
                        actual="absent",
                    )
                )
                continue
            expected_attributes = {
                "rolcanlogin": spec.login,
                "rolsuper": spec.superuser,
                "rolbypassrls": spec.bypassrls,
                "rolcreaterole": spec.createrole,
                "rolcreatedb": spec.createdb,
                "rolreplication": spec.replication,
            }
            for attribute, want in expected_attributes.items():
                got = bool(getattr(row, attribute))
                if got != want:
                    violations.append(
                        Violation(
                            "preflight_role_attribute",
                            f"role {spec.name}.{attribute} = {got}, "
                            f"expected {want}",
                            role=spec.name,
                            field=attribute,
                            expected=str(want),
                            actual=str(got),
                        )
                    )

        memberships = conn.execute(
            text(
                """
                select m.rolname as member, g.rolname as granted,
                       am.admin_option, am.inherit_option, am.set_option
                from pg_auth_members am
                join pg_roles m on m.oid = am.member
                join pg_roles g on g.oid = am.roleid
                where m.rolname = any(:roles)
                """
            ),
            {"roles": role_names},
        ).all()

        expected_edge = EXPECTED_OWNER_MEMBERSHIP
        owner_edges = [
            row for row in memberships if row.member == expected_edge.member
        ]
        if not any(
            row.granted == expected_edge.granted
            and bool(row.admin_option) == expected_edge.admin
            and bool(row.inherit_option) == expected_edge.inherit
            and bool(row.set_option) == expected_edge.set
            for row in owner_edges
        ):
            description = ", ".join(
                f"{row.granted}(admin={row.admin_option},"
                f"inherit={row.inherit_option},set={row.set_option})"
                for row in owner_edges
            ) or "absent"
            violations.append(
                Violation(
                    "preflight_membership",
                    f"app_owner membership is [{description}], expected "
                    "app_maintenance(admin=False,inherit=False,set=True)",
                    role="app_owner",
                    field="membership",
                    expected="app_owner -> app_maintenance set=True",
                    actual=description,
                )
            )
        for row in owner_edges:
            if row.granted != expected_edge.granted:
                violations.append(
                    Violation(
                        "preflight_membership",
                        f"unexpected app_owner membership to {row.granted}",
                        role="app_owner",
                        field="membership",
                        expected="app_owner -> app_maintenance only",
                        actual=f"app_owner -> {row.granted}",
                    )
                )
        for row in memberships:
            if row.member in RUNTIME_ROLES:
                violations.append(
                    Violation(
                        "preflight_membership",
                        f"runtime role {row.member} is a member of "
                        f"{row.granted}",
                        role=row.member,
                        field="membership",
                        expected="no outbound memberships",
                        actual=f"{row.member} -> {row.granted}",
                    )
                )
    return violations


@dataclass(frozen=True)
class MembershipState:
    """The full frozen option state of one role membership edge."""

    exists: bool
    admin: bool = False
    inherit: bool = False
    set: bool = False


def capture_owner_membership(obj: Engine | Connection) -> MembershipState:
    """Read the exact current ``app_owner -> app_maintenance`` option state."""
    with _connect(obj) as conn:
        row = conn.execute(
            text(
                """
                select am.admin_option, am.inherit_option, am.set_option
                from pg_auth_members am
                join pg_roles m on m.oid = am.member
                join pg_roles g on g.oid = am.roleid
                where m.rolname = :member and g.rolname = :granted
                """
            ),
            {
                "member": EXPECTED_OWNER_MEMBERSHIP.member,
                "granted": EXPECTED_OWNER_MEMBERSHIP.granted,
            },
        ).one_or_none()
    if row is None:
        return MembershipState(exists=False)
    return MembershipState(
        exists=True,
        admin=bool(row.admin_option),
        inherit=bool(row.inherit_option),
        set=bool(row.set_option),
    )


def apply_owner_membership(
    obj: Engine | Connection, state: MembershipState
) -> None:
    """Converge ``app_owner -> app_maintenance`` to an explicit option state."""
    member = EXPECTED_OWNER_MEMBERSHIP.member
    granted = EXPECTED_OWNER_MEMBERSHIP.granted
    with _connect(obj) as conn:
        if state.exists:
            conn.execute(
                text(
                    f"grant {granted} to {member} with "
                    f"admin {str(state.admin).lower()}, "
                    f"inherit {str(state.inherit).lower()}, "
                    f"set {str(state.set).lower()}"
                )
            )
        else:
            conn.execute(text(f"revoke {granted} from {member}"))
        conn.commit()


def preflight_exact_state_violations(obj: Engine | Connection) -> list[Violation]:
    """Exact expected preflight contract: revision, extensions, role topology."""
    return [
        *preflight_revision_violations(obj),
        *preflight_extension_violations(obj),
        *preflight_role_violations(obj),
        *missing_client_role_violations(obj),
    ]


def run_preflight(admin_url: str, owner_url: str) -> Report:
    report = Report("preflight")
    engine = _engine(admin_url)
    report.violations += preflight_exact_state_violations(engine)
    report.violations += inventory_violations(engine, LEGACY_0006_APPLICATION_TABLES)
    report.violations += exact_row_count_violations(
        engine, LEGACY_0006_APPLICATION_TABLES
    )
    report.violations += platform_count_violations(engine)
    report.violations += owner_readonly_preflight(owner_url)
    return report


def post_upgrade_violations(obj: Engine | Connection) -> list[Violation]:
    """Catalog/security checks for the rebuilt schema; client roles are required."""
    return [
        *missing_client_role_violations(obj),
        *ownership_violations(obj),
        *rls_violations(obj),
        *maintenance_function_violations(obj),
        *client_privilege_violations(obj),
        *function_default_acl_violations(obj),
    ]


def run_post_upgrade(admin_url: str) -> Report:
    report = Report("post-upgrade")
    report.violations += post_upgrade_violations(_engine(admin_url))
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
    report.violations += final_foreign_key_violations(engine)
    report.violations += platform_count_violations(engine)
    with _connect(engine) as conn:
        revision = conn.execute(
            text("select version_num from public.alembic_version")
        ).scalar_one_or_none()
    if revision != FINAL_REVISION:
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
