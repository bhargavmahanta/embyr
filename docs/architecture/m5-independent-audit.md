# M5 independent whole-branch final review

Review date: 2026-09-26. Reviewer: independent `m5_final_audit` agent.

**Disposition: zero HIGH and zero NORMAL blockers. Zero open LOW findings at the final reviewed revision.**

No security vulnerabilities found in the reviewed scope.

This is an integration, security and contract code review. It does not certify learning effectiveness, human content review, deployment readiness of external infrastructure, or live provider quality. The external digest-bound HUMAN content approval and explicit provisioning/coverage check remain intentional production release gates.

## Frozen scope

- Repository: `/home/bhargav/.codex/worktrees/m5-exploration/embyr`.
- Mode: explicit commit range; all changed paths, no path filter.
- Base: `de332683cb54d68afc66bbcb5c5c5629016ed1eb` (explicit frozen main).
- Initial reviewed implementation: `fa2d60528c1a6f6b1f9cd078795c22f6a94e57ef`.
- Parent explicitly authorized final delta review through `684941fcb54f16389b7d73860e651fe78123d27f`; that complete delta was inspected. The only runtime delta is cursor shape validation; remaining delta is test coverage.
- Parent additionally authorized the complete `684941f..8fd824056aa0f246c2143f8f3181fecafe629712` delta. It adds only server-generated correlation IDs and positive-whitelist reference/version log fields, plus a formatter privacy test. All callers provide trusted references/versions; no answer, reflection, token or diagnostic field was added. No findings in this delta.
- Final reviewed HEAD: `8fd824056aa0f246c2143f8f3181fecafe629712`.
- Final scope ID: `embyr:range:de332683cb54d68afc66bbcb5c5c5629016ed1eb:8fd824056aa0f246c2143f8f3181fecafe629712:all`.
- Ordered `git diff --name-status` SHA-256: `34d4ad6e56fd0b05d07cc95380a2acd64bf935fe9c6690a6d439bbe437b9ae27` (43 changed paths).
- Worktree implementation changes: excluded. Commit OIDs identify reviewed bytes. Untracked task reports and this report are not implementation scope.
- Authority: accepted `docs/plans/m5-implementation.md`, `docs/api/learning-lifecycle-v1.md`, and honest release gate in `docs/content/pilot-review.md`.
- Method: independent source/diff/database-guard/test inspection. No implementation edits, suite reruns, exploit execution, external posting or subagent dispatch. Security categories were completed serially under the parent's explicit no-delegation instruction.

## Resolved LOW finding

`M5-CURSOR-SHAPE`, LOW, non-security contract refinement, confidence 10/10: initial `backend/app/api/learning.py:327-332` unpacked arbitrary decoded JSON and passed its second member directly to `UUID`. A signed-in caller could supply base64url JSON `["2026-09-26T00:00:00+00:00",1]`; Python's UUID constructor calls `.replace()` on its positional hex input, producing an uncaught `AttributeError` instead of `422 INVALID_CURSOR`. This did not permit unauthorized reads or writes. It was introduced by the new listing route (absent at base).

Final revision validates an exact two-element list of strings before parsing (`backend/app/api/learning.py:327-341`). The delta adds malformed integer/list/object and timezone cases in `backend/tests/test_learning_contracts.py`. Source inspection confirms the identified path is closed. No remaining finding or remediation request.

## Contract and security conclusions

- **Ownership and identity:** all new routes use the shared authenticated internal principal and the original request session; `get_learning_session` wraps that session rather than replacing its transaction-local RLS identity. ORM resource lookups have explicit owner predicates. Addressed interaction IDs are checked against the session; read joins repeat owner/parent predicates. Worker context validates owned session, response, run, interaction, Exploration and exact historical objective. Existing composite FKs and immutable-history triggers remain intact.
- **Delivery:** exact entity/version selection, objective checks, private snapshot and immutable delivery guard are coherent. Canonical summaries can change independently of historical delivery. Missing approval/content fails closed while preserving an accepted Exploration. Public delivery and recognition interaction use positive whitelists; undisclosed support and option-result mappings are omitted.
- **Optional completion and races:** learner commands serialize with a parent NO KEY UPDATE lock, then the session lock. An unanswered ACTIVE session is abandoned atomically with completion; submitted WAITING sessions remain evaluable. Worker finalization does not update the Exploration and uses a session lock, with parent reads and compatible ledger FK KEY SHARE locks. This permits completion/finalization without the former lock inversion. RETURN preserves PAUSED; completion cannot reopen a parent and does not require delivery, assessment or success.
- **Answer and support facts:** answer, strongest persisted support snapshot, evaluation run, job, session transition and factual event share one transaction. Same-answer replay returns the original pending acknowledgment; conflicting answers fail. Parent/session/interaction locking prevents support delivery racing past answer acceptance. Immutable answer/history guards protect the pinned material consumed outside the worker transaction.
- **Recovery and durable acknowledgment:** new POST commands use the existing path/body fingerprint and 24-hour key implementation. Natural delivery, start, answer, retry and completion guards survive key expiry. Reflection stores only a replay reference and hydrates its current owned version. `common.finish` explicitly commits result and effects before acknowledgment; addressed interest/reflection updates also commit before returning. Lost commit acknowledgment can replay the stored durable answer.
- **Failed history:** retry creates a new later run/job, retains the old FAILED run, and serializes under the session/current-run locks. Reads select the latest run before checking visibility, so historical failure/revoked feedback is not presented as current. Pending retries resolve the existing run. Evaluation is allowed after Exploration completion.
- **Worker execution:** claim uses SKIP LOCKED, committed fresh claim token, database lease time, and bounded attempt count. Finalization checks both token and actual unexpired lease using `clock_timestamp`, not merely absence of a replacement claimant. Expired third-attempt claims finalize terminal failure without a fourth evaluation. Success/failure outcomes, policy-eligible RECOGNITION/WEAK evidence, session, job and ledger events are one transaction. Duplicate/stale finalization does not duplicate facts. Evaluation mapping is exact and provider-free; only SUPPORTED emits weak evidence with support retained.
- **Privacy failure boundary:** SQLAlchemy failures from new learning operations are reduced to a safe 503 category without exception text or parameters. Worker failures are similarly categorized. Jobs/events contain references, versions and bounded categories; reflection replay excludes raw text, and acknowledgments exclude answers. Public DTOs forbid extra fields and omit private rubric mappings. No learner-state, world or story writes were introduced.
- **0019 privileged trigger:** compared to the original 0005 validation, exact owner/parent/objective joins and FOR SHARE locks are retained. The definer is the existing trusted NOLOGIN BYPASSRLS maintenance role; tables and role catalog are schema-qualified, search path fixed, direct PUBLIC/backend/worker execution revoked, and backend/member inserts require transaction identity matching. Narrow maintenance SELECT/object-id UPDATE grants supply lock authority without granting backend ontology writes or evidence writes. Existing outer RLS and FK checks remain in force. Upgrade/downgrade coverage and the temporary `pg_roles` shadow test support this boundary.
- **Frozen behavior:** historical migrations through 0017, recommendation runtime/policies/research, bootstrap and ACCEPT implementation have no scoped changes. New head assertions in regression tests track 0019; historical target assertions remain. There is no automatic provisioning, hidden interest creation, coverage-based ranking filter, model/provider addition or state projection.

## Scope coverage ledger

All rows complete. Added files are absent at base; modified files were compared against the pinned base. Relevant unchanged callers/guards were context only, not additional scope.

| Changed paths | Relevance and inspected context |
|---|---|
| `backend/app/api/learning.py`, `assessments.py`, `learning_dtos.py` | All new routes, request/response schemas, owner predicates, nested resources, SQL reads, lifecycle writes and replay. Context: auth/session dependencies, idempotency and errors. |
| `backend/app/learning/common.py`, `transactions.py`, `telemetry.py`, `lifecycle.py`, `__init__.py` | Commit/event boundary, RLS session reuse, error/log privacy, transitions; no unsafe execution sinks. |
| `backend/app/learning/content.py`, `provision_content.py`, `packages/pilot-v1.json` | Digest approval, immutable package identity, schema validation, public whitelist, explicit operator transaction and global coverage. Operator environment and attestation are trusted deployment inputs, not public request inputs. Draft provenance remains truthful. |
| `backend/app/learning/evaluation.py`, `worker.py` | Owned immutable context, deterministic results, queue trust boundary, claims/lease/attempts, atomic finalization, failure recovery and logging. Context: existing assessment/job models and guards. |
| `backend/app/db/models/exploration.py`, `database/migrations/versions/0018_exploration_delivery.py`, `0019_response_lock_security.py` | ORM/schema pairing, immutable delivery/identity, column grants, privileged trigger and downgrade. Context: 0005, 0007, 0011a, 0012 and 0017 preserved guard/role contracts. |
| `backend/app/main.py`, `backend/pyproject.toml`, `backend/README.md` | Additive route registration and package inclusion; documented runtime/worker/content gates and operational recovery. |
| `backend/tests/test_deterministic_evaluation.py`, `test_learning_content.py`, `test_learning_contracts.py`, `test_learning_lifecycle.py` | Classification/redaction/approval/fixture/transition evidence; final cursor regression delta. |
| `database/tests/test_assessment_api.py`, `test_learning_entry_api.py`, `test_learning_journey.py`, `test_evaluation_worker.py` | Production-role journeys, nested ownership, replay/history, failure/commit injection, optional completion, worker lease/fencing/retries, final deterministic race and interest additions. |
| `database/tests/test_learning_content_provision.py`, `test_exploration_delivery_migration.py`, `test_assessment_response_privileges.py` | Explicit coverage/rollback, graph connectivity, delivery immutability, privilege boundaries, trigger shadow/owner/FK attacks, upgrade/downgrade. |
| `database/tests/test_assessment_schema.py`, `test_rls.py`, `test_account_deletion_maintenance.py`, `test_alembic_marker_autogenerate.py`, `test_default_acl_hardening.py`, `test_idempotency_key_reuse.py`, `test_issue33_hosted_verifier.py` | Retained historical assertions, tightened immediate Exploration immutability, backend row-lock race, approved definer ownership, current-head updates; no bypassed security checks. |
| `docs/api/api-contracts-v0.1.md`, `docs/api/learning-lifecycle-v1.md`, `docs/api/fixtures/learning-lifecycle-v1.json`, `docs/content/pilot-review.md`, `docs/plans/m5-implementation.md`, `.superpowers/sdd/m5/task1-report.md` | Contract and release-scope consistency, runnable public fixtures, honest content approval and evidence provenance. |

## Security category ledger

| Category | Status / disposition |
|---|---|
| Input validation/injection | Complete, no security candidate: bound SQL parameters; constant trusted provisioning identifiers; strict bodies and DTOs. LOW cursor contract issue resolved. |
| Authentication/authorization | Complete, no candidate: original principal/RLS transaction, owner predicates, parent matching, narrow worker/maintenance privileges. |
| Crypto/secrets | Complete, no candidate: no introduced live credentials or crypto changes; local test credentials/markers are inert; content digest identifies operator-approved bytes. |
| Unsafe execution/deserialization | Complete, no candidate: JSON parsing only; no new eval/pickle/shell/template execution from public input. |
| Data exposure | Complete, no candidate: positive public whitelists, reference-only events/jobs/replay and sanitized failure logging. |
| Concurrency/state | Complete, no candidate: parent/session locks, immutable facts, natural guards, actual-lease/token fencing and atomic outcome/event transaction. |
| Trust boundaries | Complete, no candidate: reviewed operator content gate, worker owned aggregate validation, secured 0019 trigger and preserved outer RLS/FKs. |

All categories executed in reviewer serial fallback, no failed handoffs or unresolved candidates. No reportable security candidate required filter/exploit-stage recovery. The sole non-security LOW candidate was source-validated and then reviewed as resolved in the authorized final delta.

## Verification evidence and limits

I inspected existing logs; I did not rerun suites:

- `/tmp/embyr-m5-final-unit.log`: **1195 passed, 1 warning in 14.11s**, after final correlation/privacy delta (cursor-fix revision: 1194 passed; initial reviewed implementation: 1190 passed).
- `/tmp/embyr-m5-final-integrated.log`: **18 passed, 1 warning**. Includes real public assessed journeys for correct/wrong/not-sure outcomes, worker, history, deletion, loss of commit acknowledgment and failure atomicity.
- `/tmp/embyr-m5-final-database.log`: **460 passed, 1 skipped, 1 warning** at initial frozen implementation.
- `/tmp/embyr-m5-final-pg17.log`: **464 passed, zero skipped, 1 warning in 121.51s**. The completed final PostgreSQL 17 database run includes the final explicit-interest and both answer/completion race orderings, security and Alembic checks, and the previously environment-specific skipped check. I read the completed log after the parent reported completion. Intermediate disposable-database startup and test-verification-SQL failures were superseded by this successful run; no runtime race failure remains.

Warnings observed are the existing Starlette TestClient deprecation warning. Final automated verification is complete in the inspected logs, including the final race tests and environment-specific skipped-check closure. The source-review disposition remains zero HIGH/NORMAL blockers and zero open LOW findings. Human content approval and explicit production provisioning/coverage remain separate release gates; no production approval is inferred from automated tests.
