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

- [ ] Receipt parsing and pure reduction: create `projection_reducer.py`, `projection_inputs.py` and `world_projection.py`; consume complete owner-scoped contiguous prefixes and produce deterministic objectives/provenance/World semantics. Test eligibility, status replay, sequence pins, identity fixtures, growth, corrections, canonical fingerprints and rejection cases before implementing.
- [ ] Transactional publisher: create `projection_publisher.py`; verify existing state/provenance and World origin before writes, emit canonical complete-object deltas, advance checkpoint and complete the claimed job atomically. Test reconstruction, no-ops, baseline adoption/refusal and rollback at each publication stage.
- [ ] Dedicated worker: create `projection_worker.py`; use existing worker grants and owner-lock RPC. Claim SKIP LOCKED, load pages <=500, validate lineage without source locks, finalize owner/checkpoint/World/job in order with actual lease/generation/horizon/payload fences. Test ordered progress, retries, deletion, concurrency and stale claims.
- [ ] Compatibility and delivery: run focused M6, relevant M4/M5 database, backend and frozen M3 regressions; run Alembic check and historical byte integrity. Characterize small/large prefixes, update active plan metadata, commit reviewable changes and open one PR without merging.

## Verification record

Implementation and validation results will be recorded here after execution.
