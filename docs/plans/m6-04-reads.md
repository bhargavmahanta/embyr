# M6-04 — Private bounded Memory and recoverable World reads

Issue #107 implements three owner-only GETs at `/api/v1/memory/summary`,
`/api/v1/world`, and `/api/v1/world/changes`. Their authority is the
[frozen M6 contract](../api/m6-projection-memory-world-v1.md),
[closed schema](../api/schemas/m6-v1.schema.json), and
[public fixtures](../api/fixtures/m6-v1.json). All six version identities stay
unchanged. No contract/schema/fixture amendment accompanies this implementation.

## Baseline and ownership

Authoritative baseline: `0f2f373e30b8062f06994d8ef5496acd21729561`.
Orca confirmed the dedicated #107 worktree at
`\\wsl.localhost\Ubuntu\home\bhargav\orca\workspaces\embyr\m6-04-memory-world-reads`,
which maps to `/home/bhargav/orca/workspaces/embyr/m6-04-memory-world-reads`.
Branch: `bhargav/m6-04-memory-world-reads`; sole writer Codex.
Orca worktree instance: `119b69a2-7706-4a25-a24b-642501c74f59`.
The #106 worktree was inspected read-only and is not reused.

## Read transaction and privacy

Bearer verification has no database I/O. Each read opens one AsyncSession from
the configured factory. Its first statement sets REPEATABLE READ and READ ONLY;
it then resolves the verified external identity to an existing `app_users.id`
inside that snapshot. An unmapped identity returns 401 without a virtual read.
The same transaction sets transaction-local `app.user_id` before owner-scoped
queries. Teardown rolls back and closes the session. No repair, initialization
or publication occurs on a GET.

Database exceptions and invalid read-model DTOs become bounded
`M6_READ_UNAVAILABLE` application errors. SQL, parameters and learner content
are not logged or included in errors. The World resync error uses the existing
Problem Details handler with the frozen 409 shape and only cursor/head details.

## Memory

The checkpoint describes the processed receipt horizon; the source head
supplies the captured horizon. CURRENT means equality, PENDING means lag, and
an unprocessed terminal projection job makes lag FAILED. Missing checkpoints
mean zero; a processed horizon beyond the head fails. Evidence omission never
changes freshness.

Current preferences and explicit choices are authoritative immediately during
lag. Onboarding-marker/preferences disagreement fails. Explicit choices retain
all five codes and their stored version/time. Public current-version display
is AVAILABLE only for a REVIEWED/PUBLISHED entity with its claimed version.
Null current versions and nonpublic status return UNAVAILABLE with null title
and entity_version. Missing entities or claimed version rows fail. Public titles
are sliced at 512 Unicode characters without changing persistence.

Recent activity aggregates only processed immutable receipt facts. Distinct
starts/completions count Explorations and returns count event IDs. Only starts,
returns, first reflection submissions and completions advance activity time.
Titles resolve exact historical entity/version pairs. Recognition starts from
current published OBJECTIVE provenance and checkpoint-included sources; current
owned evidence/run lineage can only remove an invalid source. An unprocessed
replacement is never admitted. Counts, support and latest time are recomputed
from the surviving projected subset, with neutral fixed summary text.

SQL aggregates and orders before caps: 20 explicit choices, 10 recent pairs,
10 recognition objectives. Window counts determine truncation; recognition
filtering precedes counting and capping. Unsupported long-term interest and
voluntary-revisit sections remain empty. DTO allowlists exclude owner IDs,
source IDs, confidence, scores, reflections, answers and rubric content.

## World

An absent physical root produces a deterministic revision-zero empty snapshot
without an INSERT. `/me` remains unchanged: virtual Worlds leave world_revision
null, physical roots expose their revision including zero. Snapshots read their
head and objects in one transaction and sort regions by `(region_key,id)` and
nodes by `(entity_id,id)`. Connections and artifacts remain empty.

Cursor parsing accepts only ASCII decimal digits, rejects negatives,
non-integers, booleans and BIGINT overflow. Positive limits default to 500 and
clamp to 1000 before database binding, even for very long integer strings.
At-head cursors return empty pages; ahead cursors require resync. A bounded
range count plus the existing unique World/revision constraint validates the
entire requested suffix before loading a page, including gaps beyond 500.
Accepted pages return ordered complete public replacements; continuation uses
to_revision and has_more compares against the same transaction head. Old
history at or before the accepted cursor is irrelevant.

## Verification

The current backend plus M6-04 run passed 464 tests: 422 backend tests
(including 32 M6-04 contract/DTO checks) and 42 M6-04 database integration
tests. The focused M6-04 total is 74. The full selected regression batch
passed 1,599 tests after the single-transaction and OpenAPI fixes: 422 backend,
856 frozen M3, 145 existing M4/M5 database checks, 84 capture-foundation
checks, 50 publisher checks and 42 M6-04 database checks.
M6-03 coverage totals 94 (44 reducer plus 50 publisher). Both runs reported
one upstream Starlette TestClient deprecation warning and zero test failures.
Alembic check passed with no new upgrade operations; all 22 migration files
are byte-identical to the baseline. Ruff, local links and git diff --check pass.
Tests use
local disposable PostgreSQL 16.15 with pgvector, direct `SET SESSION
AUTHORIZATION app_backend`, and existing migration/grant policy. They do not
contact hosted databases. Native test provisioning is separate from the
production TLS engine policy, which is unchanged.

The integration matrix includes single-connection route reads with a pool of
one, actual isolation/read-only settings, resolved owner context, deleted-user
401 behavior, attempted write rejection, pooled owner-context cleanup, strict
empty reads, freshness,
authoritative preferences/choices, availability integrity, Unicode title
bounds, historical activity, safety-only recognition omission, support/latest
recomputation, bounds/ties, privacy, cross-user isolation, full-suffix history
gaps, 705-change pagination/reconstruction, concurrent publisher barriers,
profile revisions, and unchanged before/after state across 14 owned tables.
Corruption-only probes deliberately bypass test-database triggers; ordinary
retirement and replacement scenarios use legal immutable source transitions.
No production persistence or privilege rule is weakened for those probes.

The contract suite validates all 12 frozen public examples, strict nested DTOs,
UTC-aware times and rejection of booleans in numeric constants,
integer OpenAPI query schemas, the strict 409 response model, ASCII query
grammar, large limit clamping, and actual
representative responses against the frozen JSON schema.

## Local performance characterization

Initial candidate characterization, before the single-transaction follow-up;
query counts included separate principal authentication and read transactions
and therefore do not describe the current request flow. Retained as historical
measurements without an SLA. Rows are returned public entries; continuity
scans do not load payloads.

| Scenario | Queries | Public entries | Elapsed ms |
| --- | ---: | ---: | ---: |
| Memory empty | 10 | 0 | 187.38 |
| Memory near caps | 10 | 40 | 139.84 |
| World empty | 5 | 0 | 9.97 |
| World populated | 7 | 12 | 12.68 |
| Delta one page | 7 | 12 | 12.40 |
| Delta, 705-change suffix / first 500 | 7 | 500 | 32.25 |

The paging test consumes both pages and reconstructs the snapshot. These
measurements characterize one local run, including connection warm-up; they
are not production latency guarantees.

## Scope and migration integrity

Head remains `0020_learner_projection_foundation`. No 0021 or new grant is
introduced. Historical migrations, runtime capture/reducer/worker/publisher,
recommendation/readiness/ranking, M5 commands and `/me` implementation are
unchanged. M6-05 (#108), Android, hosted operations, backfill and replay tooling
are outside this PR. The stale #107 dependency and active implementation-plan
header are updated while preserving historical M6-03 evidence.

## Exact file scope

- `backend/app/main.py`
- `backend/app/api/m6_reads.py`
- `backend/app/api/m6_read_dtos.py`
- `backend/app/learning/memory_read.py`
- `backend/app/learning/world_read.py`
- `backend/app/learning/read_transactions.py`
- `backend/tests/test_m6_read_contracts.py`
- `database/tests/test_m6_reads.py`
- `docs/plans/m6-04-reads.md`
- `docs/plans/m6-implementation.md`

## Review findings

The dependency text and active plan header were STALE · LOW and are corrected,
with historical evidence retained. Internal source review found one
IMPLEMENTATION_DIVERGENCE · LOW: Pydantic numeric Literal fields admitted and
normalized bool values that the frozen schema rejects. A shared before-validator
and three previously failing probes resolve it. The reviewer verified rejection
and unchanged public fixture round-trips. Independent PR review then found the
two-session pool-starvation risk (VALID · NORMAL) and string OpenAPI parameters
(IMPLEMENTATION_DIVERGENCE · LOW). This follow-up resolves them with one
read-only transaction and integer public query schemas; both review threads
remain open for independent re-review. This operation does not merge.
