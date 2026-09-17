# M1 — Database Foundation

## Goal

Implement Embyr's approved PostgreSQL persistence architecture as twelve
immutable Alembic migrations backed by SQLAlchemy 2.x metadata and real
PostgreSQL integration tests.

## Authority

When the frozen documents differ, implementation follows this order:

1. [API Contracts v0.1](../api/api-contracts-v0.1.md) for externally visible
   semantics and status values.
2. [SQL Migrations Implementation Plan v0.1](sql-migrations-implementation-plan-v0.1.md)
   for migration structure and tooling.
3. [Core Data Model LLD v0.1](../architecture/core-data-model-lld-v0.1.md)
   for conceptual details not overridden by the preceding documents.
4. Repository ADRs and governance rules.

## Delivery sequence

1. Migration harness and `0001_foundation`.
2. `0002_ontology`.
3. `0003_preferences` and `0004_exploration`.
4. `0005_assessment`.
5. `0006_artifacts`.
6. `0007_events`.
7. `0008_learner_state`.
8. `0009_recommendations`.
9. `0010_world`.
10. `0011_stories_and_exports`.
11. `0011a_account_deletion` and the trusted account-deletion maintenance path.
12. `0012_rls_and_security` and the final verification gate.

Each unit is implemented on a short-lived branch tied to its M1 issue. Before
merge, it must pass its focused tests, the complete migration chain to its new
head, and a disposable downgrade/re-upgrade. Once merged, migration files are
immutable; corrections use a later migration.

## Tooling and environment

- Python 3.12+, SQLAlchemy 2.x, Alembic, psycopg 3, pgvector, pytest,
  pytest-asyncio, and Testcontainers PostgreSQL.
- `EMBYR_DATABASE_URL` selects the development/migration database.
- `EMBYR_TEST_DATABASE_URL` may select a dedicated disposable test database;
  otherwise tests start PostgreSQL 16 with pgvector through Testcontainers.
- A Docker-compatible daemon is a test prerequisite, not repository deployment
  infrastructure. M1 adds no Dockerfile or Compose configuration.
- Environment administrators create database roles and enable extensions when
  hosted-provider permissions do not allow the migration owner to do so.

## Persistence invariants

- Domain records reference provider-independent `app_users.id` values.
- Idempotency is command-level; one command may emit several ledger events,
  uniquely ordered by `(command_id, event_ordinal)`.
- Events are immutable facts and reference sensitive content rather than
  duplicating it in metadata.
- Canonical entities have stable identities and versioned definitions;
  historical exploration and assessment data retain their active versions.
- Assessment responses are immutable. Evaluations and evidence are versioned
  and use supersession or revocation instead of historical rewrites.
- Interest, understanding, retention, confidence, and challenge remain separate
  recomputable state dimensions.
- Recommendations retain the target version, ranking provenance, and exact
  presentation required for later explanation.
- WorldModel is a derived projection with monotonically ordered revisions.
- User-owned rows carry `user_id` directly where practical and are protected by
  composite ownership constraints and row-level security.

## Security boundary

- `app_owner`: migration and object owner; never a request runtime role.
- `app_backend`: request-path DML under forced RLS; `NOBYPASSRLS` and no DDL.
- `app_worker`: cross-user job/projection work; `BYPASSRLS`, least-privilege DML,
  no DDL, and still subject to immutable-source triggers.
- `app_maintenance`: tightly restricted account deletion and physical cleanup.

Production role creation and credentials are provisioning responsibilities.
Migration `0012` verifies the roles and applies grants and policies; it must not
silently skip security when provisioning is incomplete.

Migration `0011a_account_deletion` adds `public.maintenance_delete_account(uuid)`
as a `SECURITY DEFINER` routine plus one narrow DELETE exception for the
Experience Ledger guard. It leaves EXECUTE revoked from PUBLIC and does not
transfer ownership, so the routine stays inert to application roles until
`0012` provisions `app_maintenance`, transfers ownership, and grants the
trusted worker. Migrations `0001`-`0011` remain immutable.

## Reconciliations

- M1 follows the SQL plan's `app_users(auth_provider, auth_subject)` mapping for
  the Supabase v0.1 identity while retaining a provider-independent UUID.
- Evaluation runs use the API statuses `PENDING`, `SUCCEEDED`, `SUPERSEDED`,
  `REVOKED`, and `FAILED`; evidence uses `ACTIVE`, `SUPERSEDED`, and `REVOKED`.
- Uploads use `AUTHORIZED`, `UPLOADED_UNVALIDATED`, `VALIDATED`, and `REJECTED`.
- M1 retains one current derived-state row per logical key; historical facts
  remain in the ledger and evidence tables.
- World changes use one monotonically increasing revision per change. A batch
  allocates sequential revisions within one transaction.
- Historical canonical linkage uses `(entity_id, entity_version)` rather than
  resolving through a mutable current version.
- Vocabularies not frozen by the contracts remain text and do not receive
  invented closed constraints.

## Completion gate

M1 is complete only when all thirteen migrations are merged in order, Alembic has
exactly one head (`0012_rls_and_security`), an empty PostgreSQL/pgvector database
upgrades to head, a disposable database completes `head -> base -> head`, every
database and RLS test passes, role responsibilities are documented, and no
FastAPI endpoint, Android code, ranking/evaluation algorithm, rendering logic,
or deployment infrastructure has entered scope.
