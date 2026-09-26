# M5 Guided Exploration Lifecycle — Reviewed Content Pilot

Accepted implementation brief, 2026-09-26. Baseline: de332683cb54d68afc66bbcb5c5c5629016ed1eb, Alembic 0017_idempotency_key_reuse. The user approved the discovery proposal in chat and requested its implementation.

## Global constraints

Preserve all M3/M4 recommendation semantics, policy identities, endpoints and historical migrations. No recommendation filtering by content coverage or hidden interest creation. No new model/provider, derived learner-state, world, stories, Android, offline, practical artifacts or new tables. Bootstrap and ACCEPT remain unchanged. Online-first backend pilot; reviewed content provisioning is an explicit operator action, never a migration side effect. Completion expresses learner intent, never mastery. No private rubric in public DTOs; no learner-authored content in events, jobs or logs.

Use internal app_users identity, transaction-local RLS and explicit owner predicates. Parent-child identity must match. Operational writes and factual ledger events commit atomically. GETs have no writes/events. POST commands require existing Idempotency-Key semantics (24 hours, fingerprint mismatch 409 IDEMPOTENCY_KEY_REUSED); addressed PATCH/PUT updates use optimistic versions. Natural resource guards prevent duplicates after expiry. Persist reference-only reflection replay results and hydrate the current reflection on replay.

Contract versions: exploration-lifecycle/v1, exploration-delivery/v1, assessment-strategy/v1, assessment-interaction/v1, deterministic-evaluation/v1, assessment-evidence/v1, learning-lifecycle-events/v1, worker-execution/v1. Content and rubric identities are immutable/versioned.

## Task 1: Persistence

Add nullable paired delivery_snapshot JSONB and delivery_contract_version TEXT to Exploration model and a new migration descending 0017. Enforce immutable prepared snapshot and pinned entity identity. Preserve existing rows and account deletion; no historical edits. Grant worker only UPDATE(status, completed_at) on assessment_sessions, no blanket DML or backend evidence grant. Tests: upgrade/downgrade, snapshot guards, privilege boundary, Alembic metadata check.

## Task 2: Reviewed content

Repository package pinned to exact entity/version and objective, work prompt, effort, search nudges, reflection prompt, recognition options including not-sure, four hints (SMALL_NUDGE, STRONG_HINT, MISSING_CONCEPT, EXPLANATION), private option-to-result feedback and rubric version. Validate unique options, complete mappings/feedback/support, objective coherence and contract versions. Safe prerequisite-free pilot corpus and explicit provisioning command, stable UUIDs, graph-connected DOMAIN/AREA/TOPIC starters. Coverage gate for every current REVIEWED/PUBLISHED entity version, without affecting ranking. Retain historical packages. Document content review gate; do not fabricate human review. Test composition, validation, coverage and redaction.

## Task 3: Entry, Exploration and reflection

GET /api/v1/catalog/starter-interests: authenticated canonical reviewed DOMAIN/AREA summaries.
POST /api/v1/me/onboarding/complete: existing contract section 4 body, empty selected interests valid, preferences/motivations/MORE selections/onboarding timestamp atomic with events. Invalid starter 422; already onboarded under a different command 409.
PUT /api/v1/memory/interests/{entity_id}: {base_version,preference}; base 0 creates, optimistic update; explicit-choice event, no derived state.
GET /api/v1/explorations: owned status/cursor/limit page, stable ordering, default 50 max100.
GET /api/v1/explorations/{id}: nullable public delivery, latest reflection and assessment reference; pinned historical content distinct from current canonical summary.
POST /api/v1/explorations/{id}/delivery {}: lock parent, immutable exact-version snapshot/event once. Missing content 503 EXPLORATION_CONTENT_UNAVAILABLE preserving accepted parent; completed without delivery 409; existing snapshot unchanged.
POST /api/v1/explorations/{id}/actions {action:RETURN|PAUSE|RESUME,base_version?}: ACTIVE return/self or pause; PAUSED return/self or resume; no completed reopening. RETURN never resumes. Lock/version check and timestamp/version/event.
POST /api/v1/explorations/{id}/completion {base_version}: ACTIVE/PAUSED -> COMPLETED, repeated terminal result returns even with stale version. Lock parent and unanswered assessment; abandon unanswered session atomically. Pending evaluation may finish later without reopening. Assessment/delivery/pass never required.
POST /api/v1/explorations/{id}/reflections {text}: nonblank <=10000 characters, allowed after completion, atomic event, idempotency reference only.
PATCH /api/v1/reflections/{id} {base_version,text}: optimistic owned edit/event.
Events version 1: ONBOARDING_COMPLETED, EXPLICIT_INTEREST_CHANGED, EXPLORATION_WORK_PREPARED, USER_RETURNED, EXPLORATION_PAUSED, EXPLORATION_RESUMED, REFLECTION_SUBMITTED, REFLECTION_UPDATED, EXPLORATION_COMPLETED, ASSESSMENT_ABANDONED. Event payload refs/versions only; work-prepared never asserts seen.

## Task 4: Assessment and answer recovery

POST /api/v1/explorations/{id}/assessment-sessions {confidence_before}: ACTIVE prepared only, at most one session and exactly one recognition interaction, matching repeated start resolves existing and conflicting start 409. Snapshot exact private prompt/rubric; public whitelist only.
GET /api/v1/assessment-sessions/{id}: interaction, support already delivered, latest feedback/current evaluation and retry availability.
POST /api/v1/assessment-sessions/{id}/support-requests {interaction_id,level}: parent/session/interaction locks, wrong nested id404, answered/inactive409; one persisted support per level/event.
POST /api/v1/assessment-sessions/{id}/responses {interaction_id,response_type:SINGLE_CHOICE,content:{option_id}}: unknown option422, immutable answer, strongest persisted support snapshot, PENDING evaluation+job+response event atomic;202 WAITING_FOR_EVALUATION. Same answer natural replay; conflicting answer409. Original accepted command replay remains PENDING; current status via reads.
GET /api/v1/assessment-responses/{id}: current run, feedback, status, retry_allowed; historical failure never shown as current.
POST /api/v1/assessment-responses/{id}/evaluation-retries {}: FAILED retryable only; new run/job/event, old FAILED immutable; single pending retry by locks, repeated pending resolves; allow after parent completed. No new answer/session.
Assessment ACTIVE -> WAITING_FOR_EVALUATION -> COMPLETED for any valid evaluated option; unanswered session -> ABANDONED on Exploration finish. FAILED run keeps session WAITING with explicit FAILED/read retry state.
Events: ASSESSMENT_STARTED,HINT_REQUESTED,ASSESSMENT_RESPONSE_SUBMITTED,ASSESSMENT_EVALUATION_RETRY_REQUESTED. Never emit raw answers.

## Task 5: Deterministic worker

Existing jobs only: PENDING -> RUNNING claim FOR UPDATE SKIP LOCKED, claim token and attempt counter. Default60s lease,3 attempts, retry delays5/30s. Expired lease reclaim; stale token cannot commit. Compute outside transaction, then owned resource validation and atomic finalization of run/evidence/session/job/events. No parent Exploration mutation. Permanent malformed-content failure immediately terminal; transient failures bounded. FAILED run never -> PENDING; permitted explicit retry creates new run/job. Duplicate finalization no writes. Lock order parent->session->interaction/response->run->job, standalone claim closes transaction before finalization.
Mapping: correct SUPPORTED/confidence1.0; incorrect INSUFFICIENT_EVIDENCE/1.0; not-sure UNCERTAIN/0.0. Only SUPPORTED produces one RECOGNITION/WEAK evidence with support retained. No learner ability estimates, reflection evidence, mastery or inferred preference. Persist exact evaluator/rubric/strategy versions. Events: ASSESSMENT_EVALUATED, ASSESSMENT_COMPLETED, ASSESSMENT_EVALUATION_FAILED (failure category only). Reference-only payloads, safe structured logs/correlation, no tokens/option keys/text. Default worker executable with configuration and graceful polling shutdown.

## Task 6: Integration, documentation and independent closure audit

Freeze complete additive DTOs/examples and recovery fixture contracts. Real PostgreSQL production-role API+worker journeys: new learner onboarding -> recommendation ACCEPT -> delivery -> optional support/answer -> worker -> evidence -> reflection/edit -> learner completion; also unassessed finish, wrong/not-sure, pause/return/resume, no-interest empty Surprise, historical delivery/content gap, ownership, idempotency/conflicts/expiry natural guards, worker restart/stale fencing/duplicate finalization/failure/retry, late evaluation, submit-vs-finish and atomic rollback. Preserve frozen M4 regressions, no provider calls from learning, no raw content leakage.
Run full backend/database/M3 suites, one Alembic head and check, isolated migrations and deletion/security regression. Independent whole-branch review must have zero HIGH/NORMAL blockers. Record actual results, not historical counts. Content assets still require review before production release; no learning-effectiveness or live-provider quality claim.

## Implementation clarification

Public answer integration revealed the original invoker trigger's FOR SHARE row
locks require UPDATE privilege on read-only canonical objectives. Additive
0019_response_lock_security preserves those locks through a revoked, fixed-path
SECURITY DEFINER trigger owned by the trusted maintenance role. Backend and
worker grants remain unchanged; maintenance receives narrow lock privileges.
Historical migrations stay immutable. The prepared Exploration command lock is
NO KEY UPDATE, compatible with worker ledger FK KEY SHARE locks, preventing a
completion/finalization deadlock without expanding worker permissions.
