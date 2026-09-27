# M6-03 publisher implementation plan

**Goal:** Publish deterministic objective state, provenance and World deltas from complete immutable receipt prefixes.

**Architecture:** A strict receipt parser and loader feed a pure prefix reducer. A dedicated PostgreSQL worker claims briefly, computes without publication locks, then publishes under owner/checkpoint/World/job fences in one transaction.

**Tech stack:** Python, SQLAlchemy async sessions, PostgreSQL 16 and existing migration 0020 only.

**Spec:** [Frozen M6 contract](../api/m6-projection-memory-world-v1.md) and [M6 acceptance plan](m6-implementation.md).

Baseline: `0ef91dcff36e94097b2ff13575cce2aca0e14d1c`.
Branch: `bhargav/m6-03-state-world-publisher`; retained sole-owner Codex worktree.
Execution: native in this session, test first for each component, then independent branch review.

## Constraints and review focus

No migrations, grant expansion, source mutation, recommendation policy changes, public read routes, operator bootstrap tooling or hosted operations. Minimum canonical EXPLORATION_STARTED source sequence pins a node; validate duplicate starts before ranking. Clock and claim metadata never affect semantic output.

Review especially: corrupt receipt lineage; baseline/live overlap; expired leases while waiting for checkpoint locks; owner deletion during detached computation; unknown existing projection provenance. Integration tests must exercise these using real PostgreSQL and the worker identity.

## Tasks

- [x] Receipt parsing and pure reduction: create `projection_reducer.py`, `projection_inputs.py` and `world_projection.py`; consume complete owner-scoped contiguous prefixes and produce deterministic objectives/provenance/World semantics. Test eligibility, status replay, sequence pins, identity fixtures, growth, corrections, canonical fingerprints and rejection cases before implementing.
- [x] Transactional publisher: create `projection_publisher.py`; verify existing state/provenance and World origin before writes, emit canonical complete-object deltas, advance checkpoint and complete the claimed job atomically. Test reconstruction, no-ops, baseline adoption/refusal and rollback at each publication stage.
- [x] Dedicated worker: create `projection_worker.py`; use existing worker grants and owner-lock RPC. Claim SKIP LOCKED, load pages <=500, validate lineage without source locks, finalize owner/checkpoint/World/job in order with actual lease/generation/horizon/payload fences. Test ordered progress, retries, deletion, concurrency and stale claims.
- [x] Compatibility and delivery preparation: run focused M6, relevant M4/M5 database, backend and frozen M3 regressions; run Alembic check and historical byte integrity. Characterize small/large prefixes, update active plan metadata, prepare reviewable commits and one PR without merging.

## Verification record

The pure reducer consumes normalized, contiguous, closed `projection-input/v1` receipts only. The database loader validates immutable owned references without taking operational source locks; current run/evidence status and operational timestamps cannot replace receipt history. Rows are fetched in pages of at most 500, with group completeness checked across page boundaries.

Objective output is exactly DEVELOPING/null estimate, distinct response count, minimum eligible classification confidence, any source support and latest evidence source time. Current OBJECTIVE provenance is replaced in the publication transaction. Unsupported/retired evidence cannot promote a node; corrections can withdraw state and regress recognition growth without editing source history.

World placement uses minimum canonical EXPLORATION_STARTED source sequence. UUID/seed/coordinate helpers match the frozen fixtures. Root-only publication has revision zero. New nodes publish their final group growth directly; subsequent material changes emit complete object replacements in UUID order. The publisher checks both current semantic objects and the entire delta stream, including historical growth values, against compatible receipt-derived output before writing. Unknown provenance, pins, IDs, seeds, regions, topology or history are refused without repair.

The dedicated worker claims LEARNER_PROJECTION with SKIP LOCKED and a fresh UUID token, a 60-second lease and three attempts with 5/30-second retry delays. Finalization locks owner, checkpoint, existing World and job in that order, then reads actual database clock time. Valid covered jobs acknowledge without rewriting state/checkpoint, including exhausted deliveries. Exhausted unpublished jobs terminalize without another complete reduction. REQUIRED gates ordinary jobs; trusted test-only baseline metadata/markers exercise 1..B publication, final-growth additions and covered old jobs. There is no import operator.

Canonical SHA-256 input fingerprints include all six frozen identities and the exact normalized immutable prefix. Output fingerprints include objective semantics, provenance and canonical World collections; World delta revisions, internal state-row IDs, claim metadata and wall-clock persistence fields are excluded. A factual no-op advances input fingerprint/checkpoint only. Execution uses `python -m app.learning.projection_worker --once` (or continuous mode without `--once`) with the separately provisioned app_worker TLS database credential in EMBYR_DATABASE_URL. No public endpoint is added.

### Validation environment and results

Local disposable PostgreSQL 16.15 with pgvector 0.6.0, Python 3.13.15 and SQLAlchemy async sessions. Publisher tests use actual `session_user = current_user = app_worker`, BYPASSRLS with explicit owner predicates, rather than relying on role membership. The local cluster uses fsync off; rollback/concurrency results establish logical transaction behavior, not crash durability.

- Pure reducer: 38 tests passed, including frozen identity fixtures, corrections, response dedup, crossed/equal factual times, unchanged pins, unsupported promotions and canonical fingerprints.
- Publisher/worker: 48 tests passed. Covers all nine rollback stages; claim fences; expiry while blocked on the checkpoint; SKIP LOCKED; next-group ordering; independent owners; retries; baseline support/refusal; covered delivery; multi-object revision ordering and exact reconstruction; same-group supersession without jitter; receipt-time status replay; and deletion during load, reduction and finalization.
- M6-02 foundation: 84 tests passed; existing projection authority and immutable capture boundary preserved.
- Relevant M4/M5 database and migration regression: 145 tests passed, including evaluation/correction/retry, assessment responses, event provenance/idempotency, readiness and deletion.
- Combined regression: 1516 tests passed; final affected reducer/publisher run: 86 tests passed, including one additional exhausted-budget regression. Backend: 384 tests passed. Frozen M3: 856 tests passed. Categorical DEVELOPING remains UNSATISFIED; absent objectives remain UNKNOWN; numeric estimate remains unread.
- Alembic CLI `alembic -c database/alembic.ini check` and `command.check` passed on the real migrated database (`test_real_marker_is_preserved_by_alembic_check`), with no new upgrade operations. The single head remains `0020_learner_projection_foundation`.
- All 22 historical migration files (0001 through 0019 plus 0020) are byte-identical to baseline; no 0021 exists.
- Targeted Ruff checks and `git diff --check` pass. Local document links validated before publication.

Relevant DB regression modules: learning_entry_api, assessment_api, evaluation_worker, learning_journey, recommendation_persistence, recommendation_api_flow, recommendation_input_snapshot, assessment_response_privileges, auth_identity_binding, alembic_marker_autogenerate, evaluation_supersession, event_idempotency, event_provenance and account_deletion_maintenance.

### Complete-prefix characterization

Measured loader plus reducer, after connection warmup, excluding migration and synthetic-history generation. No publication timing or SLA is inferred. Receipts are factual USER_RETURNED events after a canonical start, distributed in complete transaction groups; receipt lineage validation is included in the query count.

| History | Receipts | Source groups | Pages | Queries | Elapsed seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Small | 25 | 5 | 1 | 4 | 0.018164 |
| Larger | 2001 | 41 | 5 | 16 | 0.725748 |

Full-prefix recomputation is proportional to history; finalization also validates prior World change history. These local samples do not establish a maximum supported history size. The 60-second lease remains a publication fence; no semantic optimization or lease-policy change was introduced.

### Review record and scope

Independent read-only reviews found an exhausted covered-delivery blocking bug, optional response/run loader indexing, and an overwritten invalid historical growth value (VALID · NORMAL). Each received a failing regression test before its correction. The stricter-than-schema ASSESSMENT_COMPLETED response/run requirement was corrected (IMPLEMENTATION_DIVERGENCE · NORMAL). Active baseline/branch plan metadata was corrected (STALE · LOW), preserving historical references.

No unresolved HIGH/NORMAL/LOW finding in the final independent review. No migration/grant expansion, source-history changes, existing recommendation implementation changes, hosted/production operation, M6-04 route, Android, operator tooling or merge. #106 remains open pending independent PR review/merge; #107 is not started.
