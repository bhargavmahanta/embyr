# M5 implementation and verification

Verified 2026-09-26 on branch `bhargav/m5-exploration`, based on frozen main
`de332683cb54d68afc66bbcb5c5c5629016ed1eb`. Runtime implementation reviewed through
`8fd824056aa0f246c2143f8f3181fecafe629712`; subsequent changes contain only this
verification record, the saved audit and scratch-file cleanup.

## Implemented behavior

The backend closes the accepted Exploration loop: public minimal onboarding and
explicit interests; reviewed, immutable historical delivery; owned recovery and
pause/return/resume; private editable reflection; one optional recognition check
with four persisted support levels; immutable answers and recoverable evaluation;
and learner-chosen completion. Assessment success and delivery are not required
to finish. An unanswered check is abandoned when the learner finishes; submitted
evaluation may finish afterward without reopening the Exploration.

The PostgreSQL worker evaluates the pinned reviewed mapping, produces only weak
recognition evidence for supported responses, and commits evaluation, evidence,
assessment completion, job outcome and ledger facts atomically. Claims use
SKIP LOCKED, fenced 60-second leases, three attempts and 5/30-second retry delays.
Explicit retry preserves the failed run and immutable answer.

The [additive API contract](../api/learning-lifecycle-v1.md) and executable client
fixtures freeze the eight M5 contract identities. Operator provisioning, content
coverage, worker execution and alert queries are documented in the
[backend operations guide](../../backend/README.md).

## Final validation

All commands ran in the isolated implementation worktree with Python 3.12 and
`PYTHONPATH=backend:.`. Database suites use disposable real PostgreSQL, pgvector
and the production `app_backend` / `app_worker` role boundaries. No live model or
external authentication service was required.

| Gate | Result |
|---|---|
| Full backend and frozen research/M3 suites: `python -m pytest backend/tests research -q` | **1,195 passed**, 14.11s |
| Full database suite on PostgreSQL 17: `python -m pytest database/tests -q` with a dedicated disposable test URL | **464 passed**, zero skipped, 121.51s |
| Earlier assembled full database regression on PostgreSQL 16 | **460 passed, 1 skipped**; the PostgreSQL 17 MAINTAIN privilege check subsequently passed in the final PG17 run |
| Real API + worker journeys | Included in the final database suite; correct, wrong and not-sure outcomes, all hints, new learner entry without private learner SQL setup, frozen revisit |
| Concurrency and recovery | Both answer-versus-completion orderings, completion-versus-worker lock ordering, claim interruption/reclamation, actual lease expiry, stale token, duplicate finalization, exhausted/permanent failures, explicit retry and lost commit acknowledgment |
| Ownership, privacy and atomicity | Production-role/nested-resource checks, pooled identity, public rubric redaction, safe log formatter, reference-only jobs/events/reflection replay, event failure rollback, historical delivery, content gaps and account deletion |
| Migration verification | Exactly one head: `0019_response_lock_security`; isolated upgrades/downgrades, preservation of old rows, immutable snapshots, narrow grants and real `alembic check` included in the database suite |
| Packaging | Source distribution and wheel built; final packaged learning files match source bytes; installed wheel loads all three pilot definitions outside the checkout |
| Frozen baseline compatibility | No diff in historical migrations through 0017, M3 research, M4 recommendation implementation, bootstrap/profile routes or policy identities; full regression passes |
| Independent whole-branch audit | **Zero HIGH, NORMAL or open LOW findings**; [saved audit](m5-independent-audit.md) |
| Whitespace | `git diff --check` passed |

The suites emitted the existing Starlette TestClient deprecation warning.
Intermediate failures are not final validation: new race assertions initially
used an incorrect SQL column name, then were corrected and passed in the full
PG17 run; another disposable PG16 startup briefly refused connections. Neither
is hidden as a passing run. Final logs were captured at
`/tmp/embyr-m5-final-unit.log`, `/tmp/embyr-m5-final-pg17.log` and
`/tmp/embyr-m5-final-build.log` on the implementation host.

## Architectural rulings

The configured leading-slash branch prefix is not a valid Git ref; the branch
uses `bhargav/m5-exploration`. Only the isolated checkout was changed.

The existing response-validation trigger needs row-lock privileges on canonical
objectives. Additive revision 0019 retains its identity checks and FOR SHARE
locks through a revoked, fixed-search-path SECURITY DEFINER trigger owned by
trusted maintenance, with narrow lock privileges. Backend canonical data remains
read-only; no backend evidence authority or blanket worker operational grant was
added. The independent audit inspected this boundary.

Exploration commands use NO KEY UPDATE to serialize learner intent while allowing
worker event FK KEY SHARE locks. This resolves completion/finalization lock
inversion without worker Exploration write permission. Prepared entity identity
is already immutable; deterministic barrier tests exercise the original ordering.

## Production release gate and deferred scope

The three pilot content assets are honestly marked **draft**. Production
provisioning and new delivery require an external, named HUMAN approval bound to
the exact package digest, followed by the global coverage check. Explicit TEST
attestations are restricted to isolated test configuration. Automated structural
validation and independent code review do not substitute for human asset review
or establish learning effectiveness. Follow the
[content review procedure](../content/pilot-review.md) before releasing the pilot.
This record verifies implementation; it does not claim production release or
GitHub milestone closure.

M4 remains closed and unchanged. Full learner-state/Memory projection, world
growth, stories, Android implementation, generative AI, practical artifacts,
offline synchronization and account-operation APIs remain deferred. The stable
client contracts now permit Android work to begin separately. No deployment,
remote publication or GitHub mutation was performed.
