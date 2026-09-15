# PostgreSQL Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the PostgreSQL schema, migration harness, database security boundary, and persistence invariants required by API Contracts v0.1 and the frozen core LLD.

**Architecture:** PostgreSQL is the single transactional store for canonical ontology data, operational learner data, the Experience Ledger, derived Learner State, recommendation provenance, and the semantic WorldModel. Migrations use Alembic with explicit SQLAlchemy 2.x metadata plus deliberate hand-written SQL for PostgreSQL-specific features such as `pgvector`, row-level security, partial indexes, and security roles. The FastAPI application uses a non-owner `app_backend` database role with row-level security enforced through a transaction-local `app.user_id` setting.

**Tech Stack:** PostgreSQL, pgvector, Python, SQLAlchemy 2.x, Alembic, psycopg/asyncpg-compatible SQLAlchemy driver, pytest, Testcontainers for PostgreSQL.

**Spec:** `docs/api/api-contracts-v0.1.md` and `docs/architecture/core-data-model-lld-v0.1.md`

## Global Constraints

- PostgreSQL is the primary and authoritative application database.
- Canonical ontology data and learner-owned data remain separate.
- Learner State is derived and must be recomputable.
- Interest, understanding, retention, confidence, and challenge are separate state dimensions.
- Experience Ledger events record facts, never psychological conclusions.
- Assessment responses are immutable; evaluation runs are versioned and may be superseded or revoked.
- All learner-owned rows carry `user_id` directly where practical. Learner-owned parent tables referenced by children expose `UNIQUE(user_id, id)` so composite ownership foreign keys can prevent cross-user attachment.
- Client mutations are idempotent at the command level; one command may emit multiple Experience Ledger events.
- Internal application user IDs are provider-independent; authentication subjects are mapped to them.
- Runtime roles are separated: request backend, background worker, maintenance/deletion, and migration owner.
- Every migration supplies a development downgrade when structurally safe; production recovery is forward-fix/restore rather than rewriting merged migration history.
- Sensitive user content is referenced from events rather than duplicated into event metadata.
- No graph database, separate vector database, Kafka, or Redis is introduced in this plan.
- No table partitioning is introduced until measured scale requires it.
- The first canonical corpus is small enough for exact pgvector search; no ANN index is created until an embedding model/dimension and measured need are fixed.

---

## File Structure

Create this persistence structure inside the governed monorepo:

```text
backend/
├── pyproject.toml                  # minimal Python persistence package/dependencies; no FastAPI app yet
└── app/
    └── db/
        ├── base.py                 # SQLAlchemy declarative base and naming convention
        ├── session.py              # engine/session + transaction-local user context
        ├── types.py                # shared DB values where needed
        └── models/                 # mappings grouped by domain
            ├── identity.py
            ├── ontology.py
            ├── exploration.py
            ├── assessment.py
            ├── artifacts.py
            ├── events.py
            ├── learner_state.py
            ├── recommendations.py
            ├── world.py
            └── stories.py

database/
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/
│       ├── 0001_foundation.py
│       ├── 0002_ontology.py
│       ├── 0003_preferences.py
│       ├── 0004_exploration.py
│       ├── 0005_assessment.py
│       ├── 0006_artifacts.py
│       ├── 0007_events.py
│       ├── 0008_learner_state.py
│       ├── 0009_recommendations.py
│       ├── 0010_world.py
│       ├── 0011_stories_and_exports.py
│       └── 0012_rls_and_security.py
└── tests/
    ├── conftest.py
    ├── test_migrations.py
    ├── test_foundation_schema.py
    ├── test_ontology_schema.py
    ├── test_assessment_schema.py
    ├── test_event_idempotency.py
    ├── test_evaluation_supersession.py
    ├── test_world_revision.py
    └── test_rls.py
```

The database package may use `EMBYR_TEST_DATABASE_URL` when supplied; otherwise the test harness starts PostgreSQL with Testcontainers. The migration suite must use real PostgreSQL because pgvector, RLS, partial indexes, and PostgreSQL triggers are part of the contract.

---

### Task 1: Migration Harness and Foundation Schema

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/session.py`
- Create: `backend/app/db/models/identity.py`
- Create: `database/alembic.ini`
- Create: `database/migrations/env.py`
- Create: `database/migrations/versions/0001_foundation.py`
- Create: `database/tests/conftest.py`
- Create: `database/tests/test_migrations.py`
- Create: `database/tests/test_foundation_schema.py`

**Interfaces:**
- Produces: `Base`, `async_session_factory`, `set_current_user(session, user_id)`, and tables `app_users`, `user_devices`, `idempotency_records`, `jobs`.
- Later tasks rely on the provider-independent `app_users.id` and the Alembic/PostgreSQL test harness.

- [ ] **Step 1: Create the minimal persistence Python package**

`backend/pyproject.toml` declares Python 3.12+ and only the persistence/test dependencies required by M1: SQLAlchemy 2.x, Alembic, psycopg, pgvector, pytest, pytest-asyncio, and Testcontainers PostgreSQL. Do not add FastAPI yet.

- [ ] **Step 2: Write the failing migration smoke test**

```python
from sqlalchemy import text


def test_upgrade_head_creates_foundation(migrated_connection):
    names = {
        row[0]
        for row in migrated_connection.execute(
            text("select tablename from pg_tables where schemaname = 'public'")
        )
    }
    assert "app_users" in names
    assert "jobs" in names
```

- [ ] **Step 3: Run the test and verify it fails**

```bash
pytest database/tests/test_migrations.py -v
```

Expected: FAIL because the migration harness/foundation tables do not exist.

- [ ] **Step 4: Implement SQLAlchemy naming convention and Alembic environment**

```python
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
```

`database/migrations/env.py` uses `Base.metadata` and reads the database URL from the environment/test harness.

- [ ] **Step 5: Implement migration `0001_foundation.py`**

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
```

Create:

```text
app_users(
  id uuid primary key default gen_random_uuid(),
  auth_provider text not null,
  auth_subject text not null,
  onboarding_completed_at timestamptz null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(auth_provider, auth_subject)
)

user_devices(
  id uuid primary key,
  user_id uuid not null references app_users(id) on delete cascade,
  platform text not null check (platform in ('ANDROID','IOS')),
  push_token text null,
  app_version text null,
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  unique(user_id, id)
)

idempotency_records(
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_users(id) on delete cascade,
  idempotency_key text not null check (length(idempotency_key) between 1 and 128),
  command_name text not null,
  request_fingerprint text not null,
  result_type text null,
  result_id uuid null,
  response_status integer null,
  response_body jsonb null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null,
  unique(user_id, idempotency_key)
)

jobs(
  id uuid primary key default gen_random_uuid(),
  user_id uuid null references app_users(id) on delete cascade,
  job_type text not null,
  payload jsonb not null default '{}'::jsonb,
  status text not null check (status in ('PENDING','RUNNING','SUCCEEDED','RETRYABLE_FAILURE','FAILED')),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  available_at timestamptz not null default now(),
  locked_at timestamptz null,
  locked_by text null,
  created_at timestamptz not null default now(),
  completed_at timestamptz null
)
```

Create:

```sql
CREATE INDEX ix_jobs_available_pending
ON jobs (available_at, created_at)
WHERE status IN ('PENDING', 'RETRYABLE_FAILURE');
```

Idempotency replay compares `request_fingerprint`. Same key + different fingerprint maps to `409 IDEMPOTENCY_KEY_REUSED`. `response_body` is optional and never stores signed URLs, access tokens, or other reusable credentials.

- [ ] **Step 6: Add foundation integrity tests**

Test `(auth_provider, auth_subject)` uniqueness, idempotency uniqueness per user, and same idempotency key being valid for two different users.

- [ ] **Step 7: Verify disposable downgrade path**

```bash
alembic -c database/alembic.ini upgrade head
alembic -c database/alembic.ini downgrade base
alembic -c database/alembic.ini upgrade head
```

- [ ] **Step 8: Run tests and commit**

```bash
pytest database/tests/test_migrations.py database/tests/test_foundation_schema.py -v
git add backend/pyproject.toml backend/app/db database/alembic.ini database/migrations database/tests
git commit -m "feat(db): add migration harness and foundation schema"
```

---

### Task 2: Canonical Ontology and Vector Schema

**Files:**
- Create: `backend/app/db/models/ontology.py`
- Create: `database/migrations/versions/0002_ontology.py`
- Create: `database/tests/test_ontology_schema.py`

**Interfaces:**
- Produces canonical IDs used by every learning subsystem: `learning_entities.id`, `learning_entity_versions.id`, `learning_objectives.id`, `practical_challenges.id` is intentionally deferred to Task 6.
- Produces `ontology_edges` and `entity_embeddings` for recommendation candidate generation.

- [ ] **Step 1: Write failing ontology relationship test**

```python
from sqlalchemy import text


def test_ontology_edge_requires_distinct_entities(migrated_connection, seeded_entity_id):
    try:
        migrated_connection.execute(text("""
            insert into ontology_edges
            (source_entity_id, target_entity_id, relationship_type, confidence, provenance)
            values (:e, :e, 'RELATED_TO', 0.8, '{}'::jsonb)
        """), {"e": seeded_entity_id})
    except Exception:
        return
    raise AssertionError("self-edge should be rejected")
```

- [ ] **Step 2: Run it and verify failure**

```bash
pytest database/tests/test_ontology_schema.py -v
```

Expected: FAIL because ontology tables do not exist.

- [ ] **Step 3: Implement `0002_ontology.py`**

Create:

```text
learning_entities
learning_entity_versions
entity_domains
ontology_edges
learning_objectives
misconceptions
claims
entity_embeddings
```

Critical constraints:

```sql
CHECK (source_entity_id <> target_entity_id)
CHECK (confidence >= 0 AND confidence <= 1)
UNIQUE(entity_id, version)
UNIQUE(entity_id, embedding_model, entity_version)
```

`entity_embeddings.embedding` uses unconstrained `vector` in v0.1. `embedding_model` and `entity_version` are stored on every row, and callers only compare rows produced by the same model/dimension. The first corpus is small enough for exact nearest-neighbor search; ANN indexing is deliberately deferred until an embedding model/dimension and measured need are fixed.

Indexes:

```text
ontology_edges(source_entity_id, relationship_type)
ontology_edges(target_entity_id, relationship_type)
learning_objectives(entity_id, entity_version)
entity_domains(domain_id, is_primary)
```

Do not create HNSW/IVFFlat in this migration. Add a partial unique index enforcing at most one primary domain per entity:

```sql
CREATE UNIQUE INDEX uq_entity_domains_one_primary
ON entity_domains(entity_id)
WHERE is_primary;
```

A later immutable migration may add an ANN index after the embedding model/dimension is frozen and profiling shows exact search is insufficient.

- [ ] **Step 4: Add graph/version integrity tests**

Test that:

```text
- entity version numbers are unique per entity
- an entity can belong to multiple domains but at most one membership is primary
- edge confidence outside [0,1] fails
- objectives remain tied to the entity version used to define them
```

- [ ] **Step 5: Run tests**

```bash
pytest database/tests/test_ontology_schema.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models/ontology.py database/migrations/versions/0002_ontology.py database/tests/test_ontology_schema.py
git commit -m "feat(db): add canonical learning ontology"
```

---

### Task 3: Learner Preferences and Onboarding State

**Files:**
- Modify: `backend/app/db/models/identity.py`
- Create: `database/migrations/versions/0003_preferences.py`
- Create: `database/tests/test_preferences_schema.py`

**Interfaces:**
- Produces `learner_preferences`, `user_motivations`, and `explicit_interest_preferences` consumed by cold-start recommendations.

- [ ] **Step 1: Write failing explicit-interest uniqueness test**

```python
def test_one_explicit_interest_row_per_user_entity(db_helpers):
    db_helpers.insert_explicit_interest(preference="MORE")
    assert db_helpers.insert_explicit_interest(preference="LESS", expect_conflict=True)
```

- [ ] **Step 2: Implement migration**

Create:

```text
learner_preferences(
  user_id uuid primary key references app_users(id) on delete cascade,
  adventure_preference text not null,
  preferred_effort text not null,
  support_style text not null,
  practical_opt_in boolean not null default false,
  version integer not null default 1,
  updated_at timestamptz not null default now()
)

user_motivations(
  user_id uuid not null references app_users(id) on delete cascade,
  motivation_code text not null,
  free_text text null,
  primary key(user_id, motivation_code)
)

explicit_interest_preferences(
  user_id uuid not null references app_users(id) on delete cascade,
  entity_id uuid not null references learning_entities(id),
  preference text not null check (preference in ('NEUTRAL','MORE','LESS','PAUSED','NOT_INTERESTED')),
  version integer not null default 1,
  updated_at timestamptz not null default now(),
  primary key(user_id, entity_id)
)
```

- [ ] **Step 3: Test optimistic version increments in repository-level tests**

The SQL update used by the repository must follow:

```sql
UPDATE learner_preferences
SET adventure_preference = :value,
    version = version + 1,
    updated_at = now()
WHERE user_id = :user_id
  AND version = :base_version
RETURNING *;
```

A zero-row update maps to `409 VERSION_CONFLICT` at the API layer.

- [ ] **Step 4: Run and commit**

```bash
pytest database/tests/test_preferences_schema.py -v
git add backend/app/db/models/identity.py database/migrations/versions/0003_preferences.py database/tests/test_preferences_schema.py
git commit -m "feat(db): add learner onboarding preferences"
```

---

### Task 4: Exploration and Reflection Lifecycle

**Files:**
- Create: `backend/app/db/models/exploration.py`
- Create: `database/migrations/versions/0004_exploration.py`
- Create: `database/tests/test_exploration_schema.py`

**Interfaces:**
- Produces `explorations` and versioned `reflections`.
- Assessment sessions in Task 5 consume `explorations.id`.

- [ ] **Step 1: Write failing lifecycle constraint test**

```python
def test_completed_exploration_requires_completed_at(db_helpers):
    assert db_helpers.insert_exploration(status="COMPLETED", completed_at=None, expect_conflict=True)
```

- [ ] **Step 2: Implement schema**

Create:

```text
explorations(
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_users(id) on delete cascade,
  entity_id uuid not null references learning_entities(id),
  entity_version integer not null,
  recommendation_id uuid null,
  practical_challenge_id uuid null, -- FK added by migration 0006 after challenge table exists
  learning_intent text not null,
  status text not null check (status in ('ACTIVE','PAUSED','COMPLETED')),
  started_at timestamptz not null,
  returned_at timestamptz null,
  paused_at timestamptz null,
  completed_at timestamptz null,
  version integer not null default 1
)

reflections(
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_users(id) on delete cascade,
  exploration_id uuid not null references explorations(id) on delete cascade,
  entity_id uuid not null references learning_entities(id),
  text text not null,
  version integer not null default 1,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
)
```

Enforce the historical canonical version with a composite foreign key:

```sql
FOREIGN KEY (entity_id, entity_version)
REFERENCES learning_entity_versions(entity_id, version)
```

Add indexes:

```text
explorations(user_id, status, started_at desc)
reflections(user_id, exploration_id)
```

- [ ] **Step 3: Add lifecycle and ownership tests**

Verify an exploration cannot reference another user's reflection through repository queries, that status/timestamp combinations remain valid, and add `UNIQUE(user_id, id)` on learner-owned parent resources that later child tables reference with composite ownership FKs.

- [ ] **Step 4: Run and commit**

```bash
pytest database/tests/test_exploration_schema.py -v
git add backend/app/db/models/exploration.py database/migrations/versions/0004_exploration.py database/tests/test_exploration_schema.py
git commit -m "feat(db): add exploration and reflection lifecycle"
```

---

### Task 5: Assessment, Versioned Evaluation, Support, and Evidence

**Files:**
- Create: `backend/app/db/models/assessment.py`
- Create: `database/migrations/versions/0005_assessment.py`
- Create: `database/tests/test_assessment_schema.py`
- Create: `database/tests/test_evaluation_supersession.py`

**Interfaces:**
- Produces immutable `assessment_responses`, operational `assessment_support_requests`, versioned `evaluation_runs`, and `learning_evidence`.
- Learner State projectors consume only ACTIVE evidence.

- [ ] **Step 1: Write failing evaluation supersession and response-immutability tests**

Test that only one evaluation is current for a response, that a replacement supersedes the previous evaluation/evidence atomically, and that ordinary runtime roles cannot UPDATE/DELETE an assessment response.

- [ ] **Step 2: Implement assessment schema**

```text
assessment_sessions(
  id, user_id, exploration_id, entity_version, strategy_version,
  confidence_before, status, started_at, completed_at
)
assessment_interactions(
  id, user_id, assessment_session_id, objective_id,
  interaction_type, prompt_definition jsonb, rubric_version, sequence
)
assessment_support_requests(
  id, user_id, assessment_session_id, interaction_id,
  requested_level, delivered_content jsonb, support_source, created_at
)
assessment_responses(
  id, user_id, assessment_session_id, interaction_id,
  response_type, response_content jsonb, support_used, submitted_at
)
evaluation_runs(
  id, user_id, response_id, evaluator_type, evaluator_version,
  rubric_version, result, confidence, status, supersedes_id, created_at
)
learning_evidence(
  id, user_id, entity_id, objective_id, source_type, source_id,
  evidence_type, evidence_strength, support_level,
  evaluation_confidence, evaluation_run_id, status, created_at
)
```

Add CHECK constraints matching the API status/result values. Add composite ownership FKs so redundant `user_id` cannot disagree with the parent resource.

```sql
CREATE UNIQUE INDEX uq_evaluation_runs_active_response
ON evaluation_runs(response_id)
WHERE status = 'SUCCEEDED';
```

A SUCCEEDED evaluation may have result `UNCERTAIN`; it creates no positive/negative learning evidence and should cause clarification.

- [ ] **Step 3: Protect immutable responses**

Create a trigger rejecting UPDATE/DELETE for ordinary backend/worker roles. Only the maintenance role may physically delete immutable learner history during account deletion.

- [ ] **Step 4: Test support persistence**

Persist every support request before the next response and snapshot the effective support level on the submitted response.

- [ ] **Step 5: Test evaluation correction**

In one transaction: mark old evaluation `SUPERSEDED`, mark old evidence `SUPERSEDED`, insert replacement evaluation, and create replacement ACTIVE evidence. Never mutate the original learner response.

- [ ] **Step 6: Run and commit**

```bash
pytest database/tests/test_assessment_schema.py database/tests/test_evaluation_supersession.py -v
git add backend/app/db/models/assessment.py database/migrations/versions/0005_assessment.py database/tests
git commit -m "feat(db): add versioned assessment evidence model"
```

---

### Task 6: Practical Challenges, Upload Validation, Media, and Artifacts

**Files:**
- Create: `backend/app/db/models/artifacts.py`
- Create: `database/migrations/versions/0006_artifacts.py`
- Create: `database/tests/test_artifact_schema.py`

**Interfaces:**
- Produces reviewed `practical_challenges`, learner-owned `upload_sessions`, `media_objects`, `artifacts`, and `artifact_analyses`.
- Object bytes remain in private object storage; PostgreSQL stores server-owned keys/trusted metadata only.

- [ ] **Step 1: Write failing validation/ownership tests**

Test that an artifact cannot reference an upload that is not `VALIDATED`, and that a learner cannot attach another learner's upload or exploration.

- [ ] **Step 2: Implement canonical practical challenges**

```text
practical_challenges(
  id uuid primary key,
  entity_id uuid not null references learning_entities(id),
  version integer not null,
  prompt text not null,
  target_techniques jsonb not null,
  estimated_effort_minutes integer not null,
  materials jsonb not null,
  environment_constraints jsonb not null,
  physical_requirements jsonb not null,
  evidence_requirements jsonb not null,
  status text not null,
  created_at timestamptz not null default now()
)
```

A changed reviewed challenge is published as a new immutable row/version rather than rewriting a challenge already referenced by learner history.

- [ ] **Step 3: Close the deferred exploration challenge FK**

```sql
ALTER TABLE explorations
ADD CONSTRAINT fk_explorations_practical_challenge
FOREIGN KEY (practical_challenge_id)
REFERENCES practical_challenges(id) ON DELETE SET NULL;
```

CREATE-mode recommendation acceptance creates an exploration for `practical_challenges.entity_id` and sets `practical_challenge_id`.

- [ ] **Step 4: Implement upload/media/artifact schema**

```text
upload_sessions(
  id, user_id, purpose, declared_content_type, declared_size_bytes,
  object_key, status, created_at, completed_at
)
media_objects(
  id, user_id, upload_id, object_key, validated_content_type,
  validated_size_bytes, sha256, metadata_stripped, created_at
)
artifacts(
  id, user_id, practical_challenge_id, exploration_id,
  media_object_id, reflection_id, created_at
)
artifact_analyses(
  id, user_id, artifact_id, analyzer_version, status,
  analysis jsonb, created_at
)
```

Upload status CHECK: `AUTHORIZED | UPLOADED_UNVALIDATED | VALIDATED | REJECTED`.

`/uploads/{id}/complete` moves `AUTHORIZED -> UPLOADED_UNVALIDATED`, verifies object metadata, then validates synchronously or queues validation. Only a VALIDATED session may produce media attached to an artifact. `POST /artifacts` atomically creates the learner reflection row from the request text (using the artifact exploration/entity) and stores its `reflection_id` on the artifact. Add `UNIQUE(upload_id)` on `media_objects` and use composite ownership FKs throughout.

- [ ] **Step 5: Add indexes, run, and commit**

```text
artifacts(user_id, created_at desc)
media_objects(user_id, created_at desc)
upload_sessions(user_id, status, created_at desc)
```

```bash
pytest database/tests/test_artifact_schema.py -v
git add backend/app/db/models/artifacts.py database/migrations/versions/0006_artifacts.py database/tests/test_artifact_schema.py
git commit -m "feat(db): add practical artifact persistence"
```

---

### Task 7: Experience Ledger

**Files:**
- Create: `backend/app/db/models/events.py`
- Create: `database/migrations/versions/0007_events.py`
- Create: `database/tests/test_event_idempotency.py`

**Interfaces:**
- Produces append-only `learning_events` consumed by learner-state projectors/analytics.
- Idempotency belongs to `idempotency_records`; one command may emit multiple ordered events.

- [ ] **Step 1: Write the command-to-many-events test**

Create one idempotency command and two events with ordinals 0 and 1. Both succeed. Reusing ordinal 1 for the same command fails.

- [ ] **Step 2: Implement ledger schema**

```text
learning_events(
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_users(id) on delete cascade,
  device_id uuid null,
  command_id uuid null references idempotency_records(id) on delete set null,
  event_ordinal smallint null,
  event_type text not null,
  entity_id uuid null references learning_entities(id),
  exploration_id uuid null references explorations(id),
  assessment_session_id uuid null references assessment_sessions(id),
  artifact_id uuid null references artifacts(id),
  learning_intent text null,
  occurred_at timestamptz not null,
  received_at timestamptz not null default now(),
  schema_version integer not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
)
```

```sql
CREATE UNIQUE INDEX uq_learning_events_command_ordinal
ON learning_events(command_id, event_ordinal)
WHERE command_id IS NOT NULL;
```

Require `(command_id IS NULL AND event_ordinal IS NULL) OR (command_id IS NOT NULL AND event_ordinal IS NOT NULL)`. Use composite FK `(user_id, device_id)` -> `user_devices(user_id, id)` for non-null devices.

Indexes:

```text
learning_events(user_id, occurred_at desc)
learning_events(user_id, event_type, occurred_at desc)
learning_events(entity_id, occurred_at desc)
```

- [ ] **Step 3: Make ledger runtime-append-only**

Reject UPDATE/DELETE for `app_backend` and `app_worker`; physical deletion is reserved for `app_maintenance` during account deletion.

- [ ] **Step 4: Test offline timestamps**

Verify `occurred_at < received_at` is valid, learner history orders by `occurred_at`, and ingestion monitoring may use `received_at`.

- [ ] **Step 5: Run and commit**

```bash
pytest database/tests/test_event_idempotency.py -v
git add backend/app/db/models/events.py database/migrations/versions/0007_events.py database/tests/test_event_idempotency.py
git commit -m "feat(db): add append-only experience ledger"
```

---

### Task 8: Derived Learner State

**Files:**
- Create: `backend/app/db/models/learner_state.py`
- Create: `database/migrations/versions/0008_learner_state.py`
- Create: `database/tests/test_learner_state_schema.py`

**Interfaces:**
- Produces separate current interest, objective-understanding, retention, confidence, and challenge states.
- Recommendation/World projectors read these tables; clients never write them.

- [ ] **Step 1: Write current-state uniqueness tests**

Each dimension has exactly one current row per logical key, regardless of model version. Example: `(user_id, objective_id)` is unique for objective state. `model_version` records which projector produced the current estimate and is not part of the uniqueness key.

- [ ] **Step 2: Implement state tables**

```text
learner_interest_state       unique(user_id, entity_id)
learner_objective_state      unique(user_id, objective_id)
learner_retention_state      unique(user_id, entity_id)
learner_confidence_state     unique(user_id, entity_id)
learner_challenge_state      unique(user_id, area_id)
state_evidence_links
```

Every state row has `computed_at` and `model_version`. Interest state keeps `user_initiated_strength` separate from `algorithm_exposure_strength`. Recompute atomically replaces/updates the current row.

- [ ] **Step 3: Implement provenance links**

`state_evidence_links` contains `user_id`, `state_dimension`, the dimension's logical target ID, and exactly one nullable source: `learning_evidence_id` or `learning_event_id`. Add a CHECK requiring exactly one source. Revocation schedules targeted recomputation rather than deleting current state in-place.

- [ ] **Step 4: Run and commit**

```bash
pytest database/tests/test_learner_state_schema.py -v
git add backend/app/db/models/learner_state.py database/migrations/versions/0008_learner_state.py database/tests/test_learner_state_schema.py
git commit -m "feat(db): add recomputable learner state"
```

---

### Task 9: Recommendation Provenance

**Files:**
- Create: `backend/app/db/models/recommendations.py`
- Create: `database/migrations/versions/0009_recommendations.py`
- Create: `database/tests/test_recommendation_schema.py`

**Interfaces:**
- Produces persisted recommendation targets, ranking traces, and exact user-facing presentation required by `/recommendations/next`.

- [ ] **Step 1: Write target exclusivity and presentation tests**

A recommendation targets exactly one entity or practical challenge and persists the hook/reason shown to the learner before API presentation.

- [ ] **Step 2: Implement schema**

```text
recommendations(
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_users(id) on delete cascade,
  entity_id uuid null references learning_entities(id),
  challenge_id uuid null references practical_challenges(id),
  mode text not null,
  distance_band text not null,
  ranking_model_version text not null,
  score_components jsonb not null,
  reason_code text not null,
  presentation_version text not null,
  presentation jsonb not null,
  presented_at timestamptz not null,
  decided_at timestamptz null,
  decision text null,
  check (((entity_id is not null)::int + (challenge_id is not null)::int) = 1)
)
```

`presentation` stores exact bounded hook/reason/target presentation metadata and never hidden learner-state scores. Add CHECKs tying `decision` to `decided_at` and limiting allowed decisions.

- [ ] **Step 3: Close deferred exploration recommendation FK**

```sql
ALTER TABLE explorations
ADD CONSTRAINT fk_explorations_recommendation_id_recommendations
FOREIGN KEY (recommendation_id) REFERENCES recommendations(id) ON DELETE SET NULL;

CREATE INDEX ix_recommendations_user_presented
ON recommendations(user_id, presented_at DESC);
```

- [ ] **Step 4: Run and commit**

```bash
pytest database/tests/test_recommendation_schema.py -v
git add backend/app/db/models/recommendations.py database/migrations/versions/0009_recommendations.py database/tests/test_recommendation_schema.py
git commit -m "feat(db): add recommendation provenance"
```

---

### Task 10: Semantic WorldModel and Revision Log

**Files:**
- Create: `backend/app/db/models/world.py`
- Create: `database/migrations/versions/0010_world.py`
- Create: `database/tests/test_world_revision.py`

**Interfaces:**
- Produces `learner_worlds`, `world_regions`, `world_nodes`, `world_connections`, `world_artifacts`, and `world_changes` consumed by `/world` and paginated `/world/changes`.

- [ ] **Step 1: Write revision/ownership tests**

Verify duplicate `(world_id, revision)` fails, repository-generated revisions are contiguous, and cross-user world children cannot be attached to another user's world.

- [ ] **Step 2: Implement schema**

Every learner-owned world table carries `user_id` directly for RLS and composite ownership FKs.

```text
learner_worlds: id uuid primary key, user_id unique, generation_seed, layout_version, current_revision
world_regions: user_id, world_id, region_key, logical coordinates
world_nodes: user_id, world_id, entity_id, region_id, logical coordinates, depth, visual state, revision
world_connections: user_id, world_id, source/target node IDs, importance, is_visible, revision
world_artifacts: user_id, world_id, artifact_id unique-per-world, placement, revision
world_changes: user_id, world_id, revision, change_type, object_type, object_id, payload
```

Constraints:

```sql
UNIQUE(world_id, revision)
UNIQUE(world_id, entity_id)
```

- [ ] **Step 3: Implement atomic revision advancement**

```sql
SELECT current_revision
FROM learner_worlds
WHERE user_id = :user_id
FOR UPDATE;

UPDATE learner_worlds
SET current_revision = current_revision + 1,
    updated_at = now()
WHERE user_id = :user_id
RETURNING current_revision;
```

Insert the corresponding `world_changes` row before commit.

- [ ] **Step 4: Test paginated delta queries**

Repository query accepts `after_revision`/`limit`, returns the last returned revision separately from world head, and can signal resync if a future retention policy prunes needed deltas.

- [ ] **Step 5: Run and commit**

```bash
pytest database/tests/test_world_revision.py -v
git add backend/app/db/models/world.py database/migrations/versions/0010_world.py database/tests/test_world_revision.py
git commit -m "feat(db): add semantic world model"
```

---

### Task 11: Curiosity Stories, Export Jobs, and Deletion State

**Files:**
- Create: `backend/app/db/models/stories.py`
- Create: `database/migrations/versions/0011_stories_and_exports.py`
- Create: `database/tests/test_account_jobs.py`

**Interfaces:**
- Produces persisted Curiosity Stories and the operation resource backing `/me/export`, `/me/deletion`, and `/me/operations/{operation_id}`.

- [ ] **Step 1: Implement story persistence**

```text
curiosity_stories(
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_users(id) on delete cascade,
  story_type text not null,
  covered_from date not null,
  covered_to date not null,
  content jsonb not null,
  generator_version text not null,
  created_at timestamptz not null default now(),
  unique(user_id, story_type, covered_from, covered_to, generator_version)
)
```

Stories are generated outputs and never evidence for Learner State.

- [ ] **Step 2: Implement account operation requests**

```text
account_operation_requests(
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references app_users(id) on delete cascade,
  idempotency_record_id uuid not null references idempotency_records(id),
  operation_type text not null check (operation_type in ('EXPORT','DELETE')),
  status text not null check (status in ('PENDING','RUNNING','SUCCEEDED','FAILED')),
  result_object_key text null,
  error_code text null,
  created_at timestamptz not null default now(),
  started_at timestamptz null,
  completed_at timestamptz null,
  unique(idempotency_record_id)
)
```

An export stores only a private result object key; `/me/operations/{id}` generates a short-lived download URL after success. A DELETE operation prevents new learning mutations once status becomes `RUNNING`. When deletion finally removes `app_users`, the operation row may cascade away; the authenticated account is no longer expected to poll after physical deletion completes.

- [ ] **Step 3: Add operation tests**

Test user scoping, idempotent retry returning the same operation, export result key never being a public/signed URL, and mutation blocking while deletion is RUNNING.

- [ ] **Step 4: Run and commit**

```bash
pytest database/tests/test_account_jobs.py -v
git add backend/app/db/models/stories.py database/migrations/versions/0011_stories_and_exports.py database/tests/test_account_jobs.py
git commit -m "feat(db): add stories and account operations"
```

---

### Task 12: Row-Level Security and Database Roles

**Files:**
- Modify: `backend/app/db/session.py`
- Create: `database/migrations/versions/0012_rls_and_security.py`
- Create: `database/tests/test_rls.py`
- Modify: `database/README.md`

**Interfaces:**
- Produces the database security boundary for request, worker, and maintenance execution.

**Roles are provisioned by privileged environment bootstrap rather than assumed creatable by ordinary Alembic credentials on every hosted PostgreSQL provider:**

```text
app_owner       migration/table owner; never request/worker runtime
app_backend     request runtime; NOBYPASSRLS
app_worker      background runtime; BYPASSRLS with required DML grants, no DDL
app_maintenance account deletion/physical cleanup; tightly restricted, no request traffic
```

Tests create equivalent temporary roles. Migration `0012` applies grants/policies to the configured role names.

- [ ] **Step 1: Write failing role/RLS tests**

Test cross-user SELECT/INSERT/UPDATE/DELETE isolation for `app_backend`; verify `app_worker` can claim/process cross-user jobs but immutable-source triggers still prevent it altering assessment responses/events; verify only `app_maintenance` may physically delete immutable history.

- [ ] **Step 2: Enable and force RLS**

```sql
ALTER TABLE reflections ENABLE ROW LEVEL SECURITY;
ALTER TABLE reflections FORCE ROW LEVEL SECURITY;

CREATE POLICY reflections_user_policy ON reflections
USING (user_id = current_setting('app.user_id', true)::uuid)
WITH CHECK (user_id = current_setting('app.user_id', true)::uuid);
```

All learner-owned child tables carry `user_id`, so use the same direct policy pattern. Canonical ontology/practical-challenge tables remain globally readable to `app_backend` and writable only by privileged content/migration roles.

- [ ] **Step 3: Apply least-privilege grants**

- `app_backend`: request-path DML subject to RLS; no DDL; no direct writes to derived Learner State/World projection tables.
- `app_worker`: DML needed for job claiming, evaluation completion, Learner State/World projections, stories, and export generation; no DDL; immutable-source triggers remain enforced.
- `app_maintenance`: minimum privileges needed to delete an `app_users` row and allow cascaded account cleanup.

- [ ] **Step 4: Implement transaction-local user context**

```python
from sqlalchemy import text

async def set_current_user(session, user_id: str) -> None:
    await session.execute(
        text("select set_config('app.user_id', :user_id, true)"),
        {"user_id": user_id},
    )
```

Request transactions set this before learner-owned queries. Worker jobs use the worker role and derive their target user from trusted persisted job data, never client-controlled impersonation input.

- [ ] **Step 5: Run security/persistence suite**

```bash
pytest database/tests -v
alembic -c database/alembic.ini upgrade head
alembic -c database/alembic.ini current
```

Expected head: `0012_rls_and_security`.

- [ ] **Step 6: Verify disposable downgrade path**

```bash
alembic -c database/alembic.ini downgrade base
alembic -c database/alembic.ini upgrade head
```

Do not use downgrade as the normal production rollback after data-bearing migrations ship; production recovery uses forward migrations/backups.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/session.py database/migrations/versions/0012_rls_and_security.py database/tests/test_rls.py database/README.md
git commit -m "feat(db): enforce row-level security"
```

---

## Final Verification Gate

Before API implementation starts, run:

```bash
pytest database/tests -v
alembic -c database/alembic.ini upgrade head
```

Then manually verify these invariants against a fresh PostgreSQL instance:

```text
1. duplicate command idempotency keys do not duplicate writes, while one command may emit multiple ordered events;
2. reusing an idempotency key with a different request fingerprint is rejected;
3. ontology versions coexist without rewriting history;
4. assessment responses cannot be mutated;
5. support/hint requests are independently persisted;
6. corrected evaluations supersede old evidence rather than overwriting it;
7. Experience Ledger rows are append-only for backend/worker roles;
8. derived learner-state rows expose one unambiguous current row per logical key;
9. recommendation rows preserve both score provenance and exact presentation copy;
10. world revisions are monotonic, paginatable, and delta-addressable;
11. runtime RLS blocks cross-user access while worker/maintenance privileges remain separated;
12. deleting a user through maintenance cascades user-owned data without deleting canonical ontology rows.
```

## Implementation Boundary After This Plan

When this plan passes, the next plan should implement FastAPI repositories/services and the API endpoints in `api-contracts-v0.1.md`. Do not start Android client implementation until the OpenAPI contract tests and the first backend vertical slice (`onboarding -> recommendation -> exploration -> reflection -> assessment -> world delta`) pass end-to-end.

