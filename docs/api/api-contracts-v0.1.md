# API Contracts v0.1

## Status

Frozen implementation contract for the first Android release. The API is online-first, supports idempotent replay from the mobile outbox, and keeps AI evaluation asynchronous where necessary.

## 1. Global Conventions

- Base path: `/api/v1`
- Authentication: `Authorization: Bearer <access-token>`; backend validates the Supabase JWT, then resolves `(auth_provider='SUPABASE', auth_subject=sub)` to the internal `app_users.id`. The application UUID is provider-independent.
- Content type: `application/json` except direct object-storage uploads.
- IDs: UUID strings.
- Timestamps: RFC 3339 UTC timestamps.
- Mutating command endpoints require `Idempotency-Key` unless the endpoint is a deterministic update of an already-addressed resource.
- Idempotency is command-level: reusing the same key with the same authenticated user, command, and request fingerprint returns the same logical result. Reusing a key for a different payload/command returns `409 IDEMPOTENCY_KEY_REUSED`. A single idempotent command may emit multiple Experience Ledger events.
- Idempotency storage must never persist reusable secrets such as signed upload/download URLs; those are regenerated when an idempotent result is replayed.
- Pagination: opaque cursor with `limit <= 100`.
- Mutable resources use integer `version`; clients send `base_version` on conflict-sensitive updates.
- Error body follows Problem Details semantics:

```json
{
  "type": "https://api.example.invalid/problems/version-conflict",
  "title": "Version conflict",
  "status": 409,
  "code": "VERSION_CONFLICT",
  "detail": "The reflection was changed on another device.",
  "request_id": "3fd7f827-9c34-4e34-9724-d6fd5d02ceea",
  "details": {"current_version": 4}
}
```

## 2. Enumerations Used by v0.1

`LearningIntent`: `DIRECT_INTEREST | PREREQUISITE_SUPPORT | RELATED_EXPLORATION | RETENTION_REVISIT | PRACTICAL_SUPPORT | SERENDIPITY`

`RecommendationMode`: `CONTINUE | EXPLORE | CREATE | SURPRISE | REVISIT`

`DistanceBand`: `COMFORT | ADJACENT | FRONTIER | WILD`

`ExplorationStatus`: `ACTIVE | PAUSED | COMPLETED`

`AssessmentStatus`: `ACTIVE | WAITING_FOR_EVALUATION | COMPLETED | ABANDONED`

`EvaluationResult`: `SUPPORTED | PARTIAL | MISCONCEPTION | INSUFFICIENT_EVIDENCE | UNCERTAIN`

`EvaluationStatus`: `PENDING | SUCCEEDED | SUPERSEDED | REVOKED | FAILED`

`ExplicitInterestPreference`: `NEUTRAL | MORE | LESS | PAUSED | NOT_INTERESTED`

`ConfidenceBefore`: `FUZZY | MAIN_IDEA | COULD_EXPLAIN | CHALLENGE_ME`

`SupportLevel`: `SMALL_NUDGE | STRONG_HINT | MISSING_CONCEPT | EXPLANATION`

`UploadStatus`: `AUTHORIZED | UPLOADED_UNVALIDATED | VALIDATED | REJECTED`

## 3. Core DTO Shapes

### EntitySummary

```json
{
  "id": "uuid",
  "canonical_key": "tcp-three-way-handshake",
  "title": "Why does TCP need a three-way handshake?",
  "primary_domain": {"id": "uuid", "title": "Computer Science"},
  "knowledge_types": ["CONCEPTUAL", "PROCEDURAL"],
  "scope": "NORMAL",
  "estimated_effort_minutes": 15
}
```

### Recommendation

```json
{
  "id": "uuid",
  "target_type": "LEARNING_ENTITY",
  "entity": {"id": "uuid", "title": "Why does TCP need a three-way handshake?"},
  "practical_challenge": null,
  "mode": "EXPLORE",
  "distance_band": "ADJACENT",
  "hook": "Before data moves, both machines need to agree that a conversation exists.",
  "reason": "This builds naturally on the networking ideas you have been exploring.",
  "presented_at": "2026-09-15T17:20:00Z"
}
```

For `target_type: PRACTICAL_CHALLENGE`, `entity` may be null and `practical_challenge` contains the reviewed challenge summary. Every practical challenge has an owning canonical learning entity, which is used when acceptance creates its `Exploration`.

### Exploration

```json
{
  "id": "uuid",
  "entity": {"id": "uuid", "title": "Why does TCP need a three-way handshake?"},
  "entity_version": 3,
  "practical_challenge_id": null,
  "learning_intent": "DIRECT_INTEREST",
  "status": "ACTIVE",
  "started_at": "2026-09-15T17:22:00Z",
  "returned_at": null,
  "paused_at": null,
  "completed_at": null,
  "version": 1
}
```

## 4. Bootstrap and Profile

### `POST /api/v1/session/bootstrap`

Called immediately after successful external authentication. It deterministically resolves `(auth_provider, auth_subject)` from the verified token and creates the internal `app_users` row if one does not exist. It is naturally idempotent through the unique auth-subject mapping and does not require an `Idempotency-Key`.

Returns the internal learner ID, onboarding state, preference summary when present, and current world revision when a world exists.

### `GET /api/v1/me`

Returns the authenticated learner profile, onboarding state, preference summary, and current world revision.

### `PATCH /api/v1/me/preferences`

Request:

```json
{
  "base_version": 2,
  "adventure_preference": "BALANCED",
  "preferred_effort": "15_20_MIN",
  "support_style": "SMALL_HINT",
  "practical_opt_in": true
}
```

Returns the updated preferences with incremented `version`. A stale `base_version` returns `409 VERSION_CONFLICT`.

### `POST /api/v1/me/onboarding/complete`

Requires `Idempotency-Key`.

Request:

```json
{
  "motivations": ["LEARN_DAILY", "BECOME_MORE_CURIOUS"],
  "starter_interest_entity_ids": ["uuid", "uuid"],
  "adventure_preference": "BALANCED",
  "preferred_effort": "15_20_MIN",
  "support_style": "SMALL_HINT",
  "practical_opt_in": true
}
```

Returns `200` with learner preferences and onboarding completion timestamp.

### `POST /api/v1/me/export`

Starts an asynchronous account-data export. Requires `Idempotency-Key`. Returns `202` with `operation_id`.

### `GET /api/v1/me/operations/{operation_id}`

Returns the authenticated user's export/deletion operation state. Export operations may return a short-lived download URL only after completion.

### `POST /api/v1/me/deletion`

Starts account deletion. Requires `Idempotency-Key`.

Request:

```json
{"confirmation": "DELETE_MY_ACCOUNT"}
```

Returns `202` with a deletion operation identifier. Replaying the same command returns the same logical deletion request.

## 5. Catalog / Ontology

### `GET /api/v1/catalog/starter-interests`

Returns curated domains/areas used during onboarding.

### `GET /api/v1/catalog/search?q={query}&limit=20&cursor=...`

Searches only the reviewed canonical corpus in v0.1. It does not generate arbitrary topics. Results identify whether an entity is exploration-eligible; eligible results can be started directly as `DIRECT_INTEREST` explorations.

### `GET /api/v1/catalog/entities/{entity_id}`

Returns current canonical entity version, objectives summary, domain memberships, and public metadata. It does not expose private learner state.

### `GET /api/v1/catalog/entities/{entity_id}/connections?limit=20&cursor=...`

Returns curated public ontology edges suitable for discovery, not the entire internal graph.

## 6. Home Query

### `GET /api/v1/home`

Single round-trip composition endpoint for the Android home screen.

Response:

```json
{
  "active_explorations": [],
  "suggested_revisit": null,
  "weekly_story": null,
  "world_revision": 215,
  "recommended_modes": ["CONTINUE", "EXPLORE", "CREATE", "SURPRISE"]
}
```

This endpoint is read-only composition; source-of-truth mutations still use domain endpoints.

## 7. Recommendations

### `POST /api/v1/recommendations/next`

Requires `Idempotency-Key` because a persisted recommendation with provenance is created.

Request:

```json
{
  "mode": "SURPRISE",
  "available_minutes": 20,
  "practical_context": {
    "available_material_codes": ["PHONE_CAMERA"]
  }
}
```

Returns one persisted `Recommendation`.

### `POST /api/v1/recommendations/{recommendation_id}/decision`

Requires `Idempotency-Key`.

Accept request:

```json
{"decision": "ACCEPT"}
```

An accepted recommendation always returns a newly created `Exploration` atomically. For a practical recommendation, the exploration is created for the challenge's owning learning entity and includes `practical_challenge_id`; no separate `PracticalActivity` resource exists in v0.1.

Skip request:

```json
{"decision": "SKIP", "reason": "NOT_TODAY"}
```

The skip is recorded as an event but does not become strong negative-interest evidence by itself.

## 8. Explorations and Reflections

### `POST /api/v1/explorations`

Starts an exploration directly from a canonical entity, primarily for user-initiated catalog search or a deep link. Requires `Idempotency-Key`.

```json
{
  "entity_id": "uuid",
  "learning_intent": "DIRECT_INTEREST"
}
```

The backend resolves and stores the current canonical `entity_version`.

### `GET /api/v1/explorations?status=ACTIVE&limit=50&cursor=...`

Returns learner-owned explorations.

### `GET /api/v1/explorations/{exploration_id}`

Returns exploration state and the current canonical entity summary while preserving the exploration's historical `entity_version`.

### `POST /api/v1/explorations/{exploration_id}/actions`

Requires `Idempotency-Key`.

Request:

```json
{"action": "RETURN"}
```

Allowed v0.1 actions: `RETURN | PAUSE | RESUME`.

### `POST /api/v1/explorations/{exploration_id}/reflections`

Requires `Idempotency-Key`.

Request:

```json
{"text": "I did not realize both sides had to prove that communication worked in both directions."}
```

Returns a versioned `Reflection`.

### `PATCH /api/v1/reflections/{reflection_id}`

Request:

```json
{
  "base_version": 1,
  "text": "Updated reflection text"
}
```

Returns `409 VERSION_CONFLICT` when stale.

## 9. Assessments

### `POST /api/v1/explorations/{exploration_id}/assessment-sessions`

Requires `Idempotency-Key`.

Request:

```json
{"confidence_before": "COULD_EXPLAIN"}
```

Returns a session containing exactly one next interaction.

### `GET /api/v1/assessment-sessions/{session_id}`

Returns status, latest feedback, pending-evaluation state, and next interaction when available.

### `POST /api/v1/assessment-sessions/{session_id}/responses`

Requires `Idempotency-Key`.

Request:

```json
{
  "interaction_id": "uuid",
  "response_type": "FREE_TEXT",
  "content": {"text": "The final ACK confirms the client received the server response."}
}
```

Synchronous deterministic response example:

```json
{
  "response_id": "uuid",
  "evaluation_status": "SUCCEEDED",
  "evaluation": {
    "result": "SUPPORTED",
    "feedback": "Yes — that is the important part.",
    "confidence": 0.98
  },
  "session_status": "ACTIVE",
  "next_interaction": {"id": "uuid", "type": "APPLICATION", "prompt": "..."}
}
```

AI evaluation may instead return HTTP `202 Accepted` with:

```json
{
  "response_id": "uuid",
  "evaluation_status": "PENDING",
  "session_status": "WAITING_FOR_EVALUATION",
  "next_interaction": null
}
```

### `GET /api/v1/assessment-responses/{response_id}`

Returns current evaluation status and active evaluation result. Superseded evaluations are never exposed as the current result.

### `POST /api/v1/assessment-sessions/{session_id}/support-requests`

Requires `Idempotency-Key`.

Request:

```json
{"interaction_id": "uuid", "level": "SMALL_NUDGE"}
```

Returns the generated or canonical support text and records support usage.

## 10. Practical Challenges and Artifacts

### `GET /api/v1/practical-challenges/{challenge_id}`

Returns requirements, estimated effort, feasibility constraints, and prompt.

### `POST /api/v1/uploads`

Requires `Idempotency-Key`.

Request:

```json
{
  "purpose": "ARTIFACT",
  "content_type": "image/jpeg",
  "size_bytes": 2145221
}
```

Returns an upload session with a short-lived signed destination and server-generated object key. Client filenames are not storage identifiers. Replaying the same idempotent command returns the same upload session and may regenerate a fresh signed destination rather than replaying an expired credential.

### `POST /api/v1/uploads/{upload_id}/complete`

Requires `Idempotency-Key`.

Called after the client finishes the direct object-storage upload. The backend verifies that the expected object exists, records trusted storage metadata, transitions the upload out of `AUTHORIZED`, and starts validation/scanning/metadata stripping.

Returns either:

- `200` with `status: VALIDATED` when validation completed synchronously; or
- `202` with `status: UPLOADED_UNVALIDATED` when validation continues asynchronously.

A rejected object returns/settles as `REJECTED`; it can never be attached to an artifact.

### `GET /api/v1/uploads/{upload_id}`

Returns the learner-owned upload session status:

`AUTHORIZED | UPLOADED_UNVALIDATED | VALIDATED | REJECTED`

It never returns another learner's storage key or reusable provider credential.

### `POST /api/v1/artifacts`

Requires `Idempotency-Key`.

Request:

```json
{
  "challenge_id": "uuid",
  "exploration_id": "uuid",
  "upload_id": "uuid",
  "reflection": "The off-centre version feels less static."
}
```

Requires the referenced upload to be `VALIDATED`; otherwise returns `409 UPLOAD_NOT_VALIDATED`. The supplied reflection is persisted atomically with the artifact and remains learner-owned/editable through the reflection model. Returns artifact metadata and `analysis_status: PENDING | SUCCEEDED | FAILED`.

### `GET /api/v1/artifacts/{artifact_id}`

Returns learner-owned artifact metadata, private signed media preview when authorized, reflection, and current analysis summary.

## 11. Curiosity Memory

### `GET /api/v1/memory/summary`

Returns human-readable, bounded summaries such as recent interests, long-term interests, voluntary revisits, and learning preferences. It never exposes raw hidden scores by default.

### `PUT /api/v1/memory/interests/{entity_id}`

Deterministically creates or replaces the learner's explicit preference for the addressed entity.

Request:

```json
{
  "base_version": 3,
  "preference": "LESS"
}
```

`base_version: 0` means “create only if no explicit preference currently exists.” Existing rows require the current version. A stale/non-matching version returns `409 VERSION_CONFLICT`.

Explicit learner preference overrides inferred affinity in recommendation decisions.

## 12. World

### `GET /api/v1/world`

Returns a complete semantic `WorldSnapshot` for first device login or resynchronization.

```json
{
  "revision": 219,
  "layout_version": 1,
  "generation_seed": "opaque-string",
  "regions": [],
  "nodes": [],
  "connections": [],
  "artifacts": []
}
```

### `GET /api/v1/world/changes?after_revision=215&limit=500`

Returns ordered changes through the current revision.

```json
{
  "from_revision": 215,
  "to_revision": 217,
  "current_revision": 219,
  "has_more": true,
  "changes": [
    {"revision": 216, "type": "NODE_GROWTH_CHANGED", "object_id": "uuid", "payload": {}},
    {"revision": 217, "type": "CONNECTION_ADDED", "object_id": "uuid", "payload": {}}
  ]
}
```

`limit` defaults to 500 and is capped at 1000. `to_revision` is the last revision returned, while `current_revision` is the server head. Clients continue from `to_revision` while `has_more` is true. If the server no longer retains the requested delta range, return `409 WORLD_RESYNC_REQUIRED`; the client fetches `/world`.

## 13. Stories

### `GET /api/v1/stories?type=WEEKLY&limit=20&cursor=...`

Lists generated Curiosity Stories.

### `GET /api/v1/stories/{story_id}`

Returns structured scenes plus display copy. Stories are generated outputs, not learner-state truth.

## 14. Device Registration

### `PUT /api/v1/devices/{device_id}`

Request:

```json
{
  "platform": "ANDROID",
  "push_token": "opaque-token",
  "app_version": "1.0.0"
}
```

Upserts the authenticated user's device registration.

### `DELETE /api/v1/devices/{device_id}`

Removes the user's push registration for that device.

## 15. Common v0.1 Error Codes

In addition to standard authentication/authorization/not-found errors, clients must handle:

- `VERSION_CONFLICT` (`409`)
- `IDEMPOTENCY_KEY_REUSED` (`409`)
- `INVALID_STATE_TRANSITION` (`409`)
- `UPLOAD_NOT_VALIDATED` (`409`)
- `WORLD_RESYNC_REQUIRED` (`409`)
- `USER_NOT_BOOTSTRAPPED` (`409`) for learner-domain routes called before session bootstrap
- `EVALUATION_PENDING` only as response state, not a transport failure

## 16. API Invariants

1. No endpoint allows the client or an LLM to write derived Learner State directly.
2. Every learner-owned resource is authorization-checked by `user_id`.
3. Every create/action command is idempotent at the command level; one command may create several append-only events.
4. Canonical ontology reads expose public knowledge only, never another learner's state.
5. Recommendation creation persists provenance before presentation.
6. Assessment responses are immutable; corrections create new `evaluation_runs` and supersede/revoke evidence.
7. World changes are projections of learner state and evidence; clients cannot directly set growth state.
8. Upload completion does not imply trust; server validation precedes AI processing.
9. User deletion/export are asynchronous jobs with explicit status.
10. Short-lived signed storage credentials are regenerated and never treated as the durable idempotent response.
11. External authentication identity and internal learner identity remain separate; learner-domain requests operate on internal `app_users.id`.
12. API additions are backward-compatible within `/v1`; breaking changes require `/v2`.

