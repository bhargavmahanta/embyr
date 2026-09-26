# M5 learning lifecycle contracts

These additive contracts preserve the M4 bootstrap, profile, recommendation and ACCEPT DTOs. The earlier API v0.1 document includes future endpoints; only routes described here and existing implemented routes are available. No direct-start, free-text grading, adaptive projection, or practical artifact workflow is added.

## Authority and versions

The server owns Exploration status/version, pinned work, immutable answers, feedback and factual history. Clients retain command keys and recover through GET reads. Completion means the learner chose to finish; it is independent of assessment and does not establish understanding. Reflection remains editable after completion. A submitted answer can finish evaluation after its Exploration completes.

| Boundary | Identity |
|---|---|
| Lifecycle | `exploration-lifecycle/v1` |
| Delivery | `exploration-delivery/v1` |
| Assessment strategy | `assessment-strategy/v1` |
| Interaction | `assessment-interaction/v1` |
| Evaluation | `deterministic-evaluation/v1` |
| Evidence | `assessment-evidence/v1` |
| Ledger payloads | `learning-lifecycle-events/v1` |
| Worker payload | `worker-execution/v1` |

## Common command and privacy rules

All routes require a verified bearer token and bootstrapped internal learner. Another learner's resources return 404. Child resources must belong to the addressed parent. POST commands require `Idempotency-Key`; matching requests replay within the existing 24-hour lifetime, while conflicting reuse returns 409 `IDEMPOTENCY_KEY_REUSED`. PUT/PATCH commands use `base_version` instead. POST fingerprints include path and body; clients must preserve both. Do not promise indefinite command replay.

Delivery, session creation, answer submission, completion and evaluation retry also have resource guards after key expiry. Reflection replay stores a resource reference and returns its current version after edits. Accepted answer command replay preserves the original PENDING acknowledgment; polling returns current progress. GETs never produce events. Raw reflections/answers are confined to owned operational resources; jobs/events contain references and versions, and public DTOs omit private rubrics and unreleased hints.

## Entry

| Route | Input | Outcome |
|---|---|---|
| GET `/api/v1/catalog/starter-interests` | None | `items`: curated current reviewed DOMAIN/AREA IDs, entity type/version, title and summary |
| POST `/api/v1/me/onboarding/complete` | Motivations, starter IDs, adventure preference, effort, support style, practical opt-in as API v0.1 §4 | Preferences/version and completion timestamp; empty starters valid; invalid starter422; already completed under a new command409 |
| PUT `/api/v1/memory/interests/{entity_id}` | `base_version`, `preference` | Addressed explicit preference/version. Base0 creates only; stale409. Preference NEUTRAL/MORE/LESS/PAUSED/NOT_INTERESTED |

An interest-free new learner can receive M4's explicit `{ "recommendation": null }` for Surprise. No synthetic preference or fallback target is introduced. Preferences not consumed by the frozen pipeline create no new ranking behavior.

## Exploration

| Route | Input | Outcome |
|---|---|---|
| GET `/api/v1/explorations` | Optional status, opaque cursor; limit50/max100 | Owned `items`, `next_cursor`; order started_at DESC then ID DESC |
| GET `/api/v1/explorations/{id}` | None | Existing Exploration fields plus lifecycle version, current entity summary, nullable historical delivery, latest reflection and assessment reference |
| POST `/api/v1/explorations/{id}/delivery` | `{}` | Immutable public historical delivery; no private rubric. Missing content503 `EXPLORATION_CONTENT_UNAVAILABLE`, accepted parent remains intact. Completed/unprepared409 |
| POST `/api/v1/explorations/{id}/actions` | `action`, optional `base_version` | Versioned Exploration. RETURN preserves ACTIVE/PAUSED; PAUSE only ACTIVE; RESUME only PAUSED. Completed cannot reopen |
| POST `/api/v1/explorations/{id}/completion` | Required `base_version` | COMPLETED Exploration; an unanswered ACTIVE assessment becomes ABANDONED atomically. Repeated completion returns existing result. A pending evaluation remains pending |
| POST `/api/v1/explorations/{id}/reflections` | Nonblank `text`, max10000 characters | Reflection ID, Exploration/entity IDs, text, version, timestamps |
| PATCH `/api/v1/reflections/{id}` | `base_version`, `text` | Current Reflection; stale409 `VERSION_CONFLICT` |

```json
{"action":"RETURN","base_version":3}
```

```json
{"base_version":4}
```

Preparing work records availability, never that it was seen. Work contains effort guidance, independent search nudges and a reflection prompt. Current canonical metadata may change; historical delivered work cannot change. Revisit uses the unchanged M4 recommendation flow and creates a new Exploration.

## Optional recognition check

| Route | Input | Outcome |
|---|---|---|
| POST `/api/v1/explorations/{id}/assessment-sessions` | `confidence_before`: FUZZY/MAIN_IDEA/COULD_EXPLAIN/CHALLENGE_ME | One session/interaction per Exploration; requires ACTIVE prepared parent. Matching repeated start resolves existing session; conflicting start409 |
| GET `/api/v1/assessment-sessions/{id}` | None | Status, interaction, delivered support, feedback, evaluation state and retry availability |
| POST `/api/v1/assessment-sessions/{id}/support-requests` | `interaction_id`, `level` | Reviewed support persisted once per level before answer; answered/inactive409, wrong child404 |
| POST `/api/v1/assessment-sessions/{id}/responses` | See example | HTTP202 immutable answer accepted; run/job queued atomically; matching answer resolves existing acknowledgment, conflicting answer409 |
| GET `/api/v1/assessment-responses/{id}` | None | Current evaluation/status, feedback and `retry_allowed` |
| POST `/api/v1/assessment-responses/{id}/evaluation-retries` | `{}` | HTTP202 new PENDING run; one pending retry; old FAILED run preserved. Only permitted failure categories are retryable |

```json
{"interaction_id":"00000000-0000-0000-0000-000000000000","response_type":"SINGLE_CHOICE","content":{"option_id":"not_sure"}}
```

```json
{"response_id":"00000000-0000-0000-0000-000000000000","evaluation_status":"PENDING","session_status":"WAITING_FOR_EVALUATION","next_interaction":null}
```

Four support levels are SMALL_NUDGE, STRONG_HINT, MISSING_CONCEPT, EXPLANATION. The strongest persisted level is snapshotted on the answer. Hints never block completion. Initial delivery/session reads exclude option mappings and undisclosed support.

Correct mapping yields SUPPORTED/confidence1; incorrect yields INSUFFICIENT_EVIDENCE/confidence1; not-sure yields UNCERTAIN/confidence0. Confidence describes classification certainty, never learner ability. Only SUPPORTED emits RECOGNITION/WEAK evidence with support retained. Any valid evaluated response completes the assessment. Reflection and completion never produce mastery or inferred interest.

FAILED is explicit in reads with bounded failure category and retry availability. The session can remain WAITING_FOR_EVALUATION with a FAILED run; clients show failure, not an endless pending spinner. Retry never edits or resubmits the answer. Supersession/revocation foundations remain unchanged; no M5 correction API exists.

## Worker and ledger

Evaluation jobs contain owned response/run/session references and `worker-execution/v1`, never learner content. Claiming uses PostgreSQL SKIP LOCKED and a fresh token. Default lease60 seconds, maximum3 attempts, delays5 then30 seconds. Computation occurs outside the claim transaction. Finalization validates the current token and commits run/result, policy-eligible evidence, session completion, job outcome and events together. Expired leases can be reclaimed; stale workers cannot commit. Invalid pinned content fails permanently; transient failures retry and expose terminal recovery. Old FAILED runs cannot return to PENDING.

Ledger schema_version1 payloads include `learning-lifecycle-events/v1`, resource/content IDs and versions. Events: ONBOARDING_COMPLETED, EXPLICIT_INTEREST_CHANGED, EXPLORATION_WORK_PREPARED, USER_RETURNED, EXPLORATION_PAUSED, EXPLORATION_RESUMED, REFLECTION_SUBMITTED, REFLECTION_UPDATED, ASSESSMENT_STARTED, HINT_REQUESTED, ASSESSMENT_RESPONSE_SUBMITTED, ASSESSMENT_EVALUATED, ASSESSMENT_EVALUATION_FAILED, ASSESSMENT_EVALUATION_RETRY_REQUESTED, ASSESSMENT_COMPLETED, ASSESSMENT_ABANDONED, EXPLORATION_COMPLETED. Existing M4 events retain their semantics.

Operational telemetry records correlation/resource IDs, versions, transition/failure categories, latency, replay/conflict, queue age, attempts and lease expiry. Do not record bearer tokens, signed capabilities, raw learner content or answer keys. Operators should alert on terminal failures, stranded runs and missing release content coverage.
