# M6 — Implementation plan after contract freeze

Status: M6-01 complete; **proposed issues only**, none created by this document.
Baseline: `d5015398b494aa8df33b94392007a60ad72f026a`.
Worktree: `/home/bhargav/orca/workspaces/embyr/m6-memory-world`.
Branch: `bhargav/m6-memory-world`; sole owner Codex.

The [M6 frozen contract](../api/m6-projection-memory-world-v1.md),
[strict schemas](../api/schemas/m6-v1.schema.json) and
[deterministic fixtures](../api/fixtures/m6-v1.json) govern every issue below.
The additive authority note in the historical LLD resolves its current-row,
explicit-interest and change_ordinal divergences. Changing these contracts
requires review; implementation is not authorization to invent new semantics.

## Dependency and scope

M6-01 -> M6-02 -> M6-03 -> M6-04 -> M6-05. M6-02 installs capture before any
bootstrap. M6-03 implements baseline publication support and its worker gate;
M6-05 supplies the explicit operator bootstrap/replay tooling and final audit.
Each implementation issue includes focused tests for its own boundary.
M6-05 assembles end-to-end checks rather than postponing local verification.
No hosted backfill, deployment, Android work, ranking changes or new external
export/delete endpoint is authorized by this plan.

## M6-02 — Immutable ordered capture and projection metadata

Dependencies: frozen M6-01. Planned changes: additive revision
`0020_learner_projection_foundation` with parent `0019_response_lock_security`,
ORM metadata, strict input parser/storage guards, transaction-local ledger and
evidence capture, PostgreSQL LEARNER_PROJECTION job references, deletion extension.

Acceptance criteria:

- Match all 0020 table/column/FK/nullability/unique/preflight/RLS/grant contracts.
  Historical migrations remain byte-identical. Existing numeric values and
  unknown World pins are preserved; conflicting regions abort preflight.
- Enforce UNIQUE(user_id,source_kind,source_key), exact lowercase event keys,
  evidence UUID:STATUS keys and bootstrap marker key. Facts are closed, <=8 KiB,
  immutable and free of all forbidden content. Repeated captures allocate no
  new sequence; contradictory identities fail atomically.
- Head row locking produces committed gap-free per-user sequences and complete
  contiguous transaction groups. Group identity never determines ordering.
  Rolled-back sources leave no receipts, sequence increments or orphan jobs.
- M4 acceptance/start without M5 markers remains valid; metadata values are
  validated owner-scoped, never copied wholesale. All supported M5 ledger types
  and evidence status-only corrections capture exactly once.
- Final transaction evidence/run status snapshots are coherent, including
  retire-and-replace in the same transaction. Preserve M5 source lock order.
- Existing users default bootstrap REQUIRED; demonstrably fresh users READY.
  Bootstrap metadata cannot be set by request role. Job payloads carry only
  owned group/range references and projection-worker/v1.
- Real app_backend cannot write checkpoint/Learner State/World or mutate/delete
  receipts; direct client roles cannot access metadata. Worker must validate
  owners despite bypass RLS. Trusted deletion removes all new facts/jobs and
  metadata with the correct owner and source deletion order.

Focused validation: disposable-DB migration upgrade/downgrade/head/drift and
historical checksums; duplicate/rollback/concurrent-source capture; complete
group loading across 500-row pages; evidence correction snapshots; real-role
isolation/grants; deletion races and sentinel privacy probes. No inferred
publication or routes in this issue.

## M6-03 — Deterministic Learner State and World publisher

Dependencies: M6-02. Planned changes: pure prefix reducer, provenance replacement,
dedicated existing-PostgreSQL worker, deterministic semantic publisher, baseline
gate/reduction, bounded recovery and telemetry.

Acceptance criteria:

- Implement learner-projection/v1's entire eligible-source predicate and exact
  DEVELOPING/null/count/min-confidence/any-support/latest-source-time output.
  Response deduplication, absent-row/link cleanup and version lineage hold.
  Interest/retention/confidence/challenge tables remain untouched; weak evidence
  never emits UNDERSTOOD/RETAINED or interprets self-report numerically.
- Corrections contribute zero current understanding, immutable history remains,
  same-transaction replacement produces no jitter, and late evaluation cannot
  reopen a completed Exploration.
- Identity namespace, UUID derivations, UTF-8 SHA-256 encodings and binary64
  coordinate rule match fixtures. First placement pins entity version for v1;
  later-version evidence cannot promote the pin. Region appears with first node,
  never from explicit preference alone; root can remain revision zero.
- Highest factual SEED/SPROUT/YOUNG growth only, correction-only regression,
  ESTABLISHED unreachable, stable placement, empty connections/artifacts.
- Canonical region additions/node additions/growth changes each allocate one
  revision; add new nodes directly at final growth. Complete replacement
  world-delta/v1 objects reconstruct exact snapshots; no-op allocates none.
- Baseline REQUIRED gate prevents earlier live publication. Exact C/B cutoff,
  unique-key overlap and current evidence status reduction publish the prefix
  once without fabricated historical revisions. Refuse unknown provenance.
- SKIP LOCKED, fresh claim tokens, 60-second lease, three attempts and 5/30
  delays match contract. Validate actual expiry after finalization locks;
  expired/stale/token-replaced/generation-replaced workers publish nothing.
- State/provenance/objects/deltas/head/checkpoint/job success commit atomically.
  Out-of-order jobs cannot skip groups, duplicate delivery is a no-op, terminal
  earliest-group failure blocks only that owner. No mutable source lock beneath
  publication locks; deletion prevents resurrection.
- Input/output fingerprints and same-history replay are deterministic across
  job scheduling; page size does not change source group boundaries. Quantify
  complete-prefix recomputation on small/large synthetic histories without
  asserting an unmeasured latency SLA. Logs contain only bounded public metadata.

Focused validation: pure reducer matrix; supported/insufficient/uncertain/failed
and corrupt-lineage cases; min/any/max/dedup; revoked/superseded replacement;
multi-version pinning; bootstrap overlap; repeated/out-of-order jobs; exact
lease-boundary tests; atomic fault injection; canonical delta/replay snapshots;
deletion concurrency; no mutation of historic sources or other state dimensions.

## M6-04 — Private bounded Memory and World reads

Dependencies: M6-03. Planned changes: strict public DTOs/OpenAPI fixtures,
authenticated owner-scoped read repositories/routes, freshness and resync.

Acceptance criteria:

- Implement memory-summary/v1's exact keys, 20/10/10 bounds, all five explicit
  values, current authoritative preferences while lagging, exact sort order and
  truncation after filtering. Fixed neutral recognition copy, empty unsupported
  lists, no extra score/private/content/provenance fields.
- Distinct entity/version activity uses latest_activity_at from starts, returns,
  first reflection submission and completion. Counts deduplicate resources and
  events; GET/preparation/hints/evaluation/reflection edits never advance activity.
- Safety filtering can only remove checkpoint-included evidence; replacement
  awaiting publication is not added. Recalculate public subset aggregates;
  PENDING remains PENDING, FAILED takes precedence, processed <= captured head.
- Empty and populated World snapshots match schemas; pre-material GET has no
  side effects and profile world_revision stays null until the physical root.
- Delta default500/cap1000, integer validation422, zero/head/ahead cursors,
  complete suffix continuity (including beyond page), 409 strict resync shape,
  from/to/current/has_more invariants match contract. No partial page on holes.
- Every Memory/World read is one owner-scoped REPEATABLE READ, READ ONLY
  transaction. Concurrent publication cannot mix object/head horizons.
  No GET inserts events, receipts, jobs, state or World rows.
- Renderer consumes complete replacement semantics; no Android or rendering
  implementation is included. Only these routes expose the reviewed public DTOs.

Focused validation: strict DTO/schema/OpenAPI compatibility; auth/ownership
isolation under production roles; sparse/lag/failed users; sort tie cases and
latest-return beats older-start case; all caps/truncated flags; partial/all
evidence invalidation; immediate explicit suppression; no-read writes; integer
and cursor matrix; prefix/interior/tail-hole detection; stable continuation with
growing head; delta-to-snapshot equality and concurrent transaction snapshots;
sentinel private content absent from responses/logs/errors.

## M6-05 — Replay, correction, deletion and compatibility final gate

Dependencies: M6-02 through M6-04. Planned changes: explicit bootstrap/import
preflight and dry-run operator tooling, safe same-group requeue, end-to-end
verification, operational documentation and independent contract/security audit.
No automatic hosted invocation or production rollout is included.

Acceptance criteria:

- Execute install-capture-first bootstrap on disposable existing histories.
  Source commits before C, during head lock and after B are all represented once.
  Duplicate baseline is a no-op; failed baseline rolls back; pre-C live jobs
  never publish early. Reconstruct only known facts/current evidence, with no
  fabricated ACTIVE dates or historical correction revisions. Refuse unknown
  state/World provenance without destroying rows.
- Identical baseline/live receipts with repeated/shuffled job delivery reproduce
  identical objective state/provenance, Memory ordering/counts, identity/pins,
  geometry/growth and canonical full delta stream. Live replay adds no duplicate
  revisions and never resets a public head. Unsupported corruption requires a
  reviewed repair/resync policy.
- Real API plus workers complete accept -> explore -> reflect -> assess ->
  supported evidence -> projected state/Memory/World. Stop/restart, lease loss,
  terminal failure and requeue retain factual success and coherent publication.
  Late completion and corrected equivalent replacement retain Exploration status.
- Trusted deletion is owner-isolated, idempotent and atomic; capture/bootstrap/
  finalization races never recreate a deleted user. Full rollback restores
  sources and new metadata. Eventual export requirements acknowledge new facts
  without claiming an export/delete HTTP workflow already exists.
- Freeze M3/M4 compatibility with tests of the existing objective_state_entry:
  DEVELOPING + null estimate -> UNSATISFIED; absent objective -> UNKNOWN;
  UNDERSTOOD/RETAINED existing fixtures -> SATISFIED. Varying a stored numeric
  estimate cannot change readiness or ranking through this categorical adapter.
  Hard prerequisite unmet/unknown both remain excluded with existing respective
  PREREQUISITE_UNMET/INSUFFICIENT_STATE reasons.
- Existing candidate-source, feature/weight, diversity, ranking/reranking,
  explanation-order, MORE/LESS/NEUTRAL/PAUSED/NOT_INTERESTED suppression,
  policy-identity and no-result fixtures remain unchanged. No readiness
  algorithm, inferred interest model or ranking feature is added.
- Run assembled focused regressions and migration/package checks only after
  the implementation exists. Independent review covers grants/bypass ownership,
  parser privacy, correction atomicity, sequence/checkpoint invariants and
  snapshot/delta reconstruction. Document remaining performance limits.

## M6-01 validation and concern record

Contract-only gate: JSON parses; Draft 2020-12 schemas and all examples validate;
closed objects reject extra/private keys; enum/boundary examples reject invalid
values; version identities and local links resolve; UUID namespace/IDs/seeds/
coordinates recompute; fixtures' delta sequence reconstructs populated snapshot;
freshness/count/order constraints agree; git scope is documentation-only and
historical migrations unchanged. No full M6 suite exists or runs at this stage.

M6-01 verification on 2026-09-26 passed using Python's installed jsonschema
Draft202012Validator with FormatChecker and focused, temporary validation code
outside the repository: 12 public cases, four internal receipt examples, one
job example, and 12 invalid-shape rejection probes. UUID namespace, all derived
IDs/seeds/coordinates, four-change snapshot reconstruction, two-page/empty
cursor invariants, Memory count/order/freshness examples, receipt identity/size,
public forbidden-field checks and 21 local Markdown links passed. Baseline and
branch matched; git scope was exactly eight documentation files, all existing
migration bytes matched HEAD, 0020 was absent, and `git diff --check` passed.
These checks validate the contract artifacts; worker, concurrency, API and
database behavior tests remain the implementation issues' acceptance work.

| Concern | Classification | Severity | Disposition |
| --- | --- | --- | --- |
| Discovery sorted recent activity by original start only | STALE | NORMAL | Superseded by latest_activity_at contract and explicit acceptance cases |
| Bootstrap/live overlap could double-count or publish invented transitions | VALID | HIGH | Freeze gated prefix baseline, unique source keys, C/B cutoff and race tests |
| Treat node pin as immutable under all future versions | STALE | NORMAL | Freeze only world-projection/v1; reviewed future evolution remains possible |
| Unrecorded historical correction timing | VALID | NORMAL | Keep unknown; import current supported evidence status without fabricated history |
| Bootstrap head lock and O(history) reduction may be expensive | VALID | NORMAL | Explicit per-user operation and measured implementation limit; no latency promise |
| Rich topology, retention/ability/interest inference, artifact projection | FUTURE-SCOPE | LOW | Excluded from v1 |

No unresolved contract question remains for M6-02 through M6-05. This document
does not create issues, implement migration/capture/routes or open a PR.
