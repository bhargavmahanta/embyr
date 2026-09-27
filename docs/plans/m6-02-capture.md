# M6-02 capture implementation plan

> **For agentic workers:** Execute the authorized #105 work with test-first
> verification, keeping each migration and capture boundary reviewable.

**Goal:** Capture immutable owned facts and complete ordered transaction groups,
without publishing Learner State or World meaning.

**Architecture:** A single additive Alembic revision installs forced-RLS tables
and deferred source triggers. Trigger-only security-definer routines validate
typed operational references, lock the source head after source writes, allocate
transactional sequences and upsert one strict job reference per owned group.
Application roles cannot submit arbitrary receipt facts. Deferred evidence
capture retains each transition snapshot and reads the final evaluation run.
The existing maintenance function locks the owner before deleting jobs, inputs,
checkpoints, heads and historical owned sources.

**Tech stack:** PostgreSQL 16, Alembic, SQLAlchemy, pytest, real runtime roles.

Baseline: `2b8d8a315ca880da874f178602ffc413c89418b9`.
Contract authority: [M6 v1](../api/m6-projection-memory-world-v1.md).

1. Write database tests for old/new user bootstrap metadata, migration roundtrip,
   historical numeric values and null World pins, duplicate-region preflight and
   exact version FK. Observe failure before implementing revision 0020 and ORM.
2. Write tests for strict ledger/evidence receipts, final transaction coherence,
   grouped jobs, source rollback, equivalent duplicate capture and contradictions.
   Implement trigger-only capture and the narrow application receipt reader.
3. Exercise real role denial, immutable receipts, poisoned search paths and
   ownership arguments. Extend trusted deletion with owner locking, then test
   isolation, repeated deletion, pending/claimed jobs, rollback and late writers.
4. Test same-user serialization, independent users, gap-free rollback and groups
   spanning 500-receipt pages. Run relevant M4/M5 and frozen M3 regressions.
5. Check one Alembic head, 0019/0020 roundtrip, autogenerate drift and unchanged
   0001–0019 checksums. Update only stale baseline metadata in the frozen plan.
6. Commit, push and open one review PR closing #105 and referencing #103. Record
   exact head/base, files, checks and unresolved review threads; do not merge.

No reducer, publisher, GET routes, bootstrap operator, hosted migration or data
backfill belongs to this change.

Source-writer lock order: request commands reserve their owned idempotency record
(owner FK lock) before mutable aggregates. Evaluation finalization calls
`lock_source_owner` before session/run/job locks. Any future trusted correction
writer must call that helper before locking or updating existing sources; direct
SQL updates are not a replacement for the source transaction boundary. Capture
obtains the head last and never adds source row locks afterward.

Deferred constraints must remain deferred until source writes are finished.
If a caller forces capture immediate and later changes a captured run status,
the source transaction fails with `M6_FINAL_STATUS_CHANGED`; facts are never
rewritten to repair an intermediate snapshot.

Receipt timestamps must be finite UTC instants within years 0001–9999 so they
can serialize under the frozen date-time contract. Bootstrap markers accept
only a UTC `Z` cutoff matching their source time.

Migration rollback refuses existing null understanding estimates rather than
inventing historical numbers. Alembic's revision column remains widened to 64
characters on rollback because Alembic writes the preceding revision only after
the downgrade completes.

Verification: 84 focused foundation tests, 145 targeted database regressions,
346 backend tests and 856 frozen M3 tests passed on disposable local PostgreSQL
16 with pgvector. Frozen fixture/schema checks and all 21 historical migration
byte comparisons passed. Review findings on job shape, final run snapshots,
timestamp bounds and non-superuser downgrade cleanup were resolved.

The independent job-lifecycle finding adds 29 real-role regressions. The job
guard rejects direct backend projection INSERT/UPDATE using `current_user`,
including direct-login semantics where the role setting is `none`. Trusted
capture creates only PENDING, unclaimed jobs and can extend their payload only
inside the original source group; it cannot change lifecycle fields. Worker
lifecycle updates remain allowed. Conversion into or out of the projection job
type is rejected, while other job types retain their existing queue behavior.
The independent review thread remains open for re-review after this patch.
