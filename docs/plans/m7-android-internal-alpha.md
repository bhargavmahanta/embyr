# M7 — Android MVP / Internal Alpha

- **Status:** CONTRACT / ARCHITECTURE FROZEN FOR M7-02
- **Parent:** [#115](https://github.com/bhargavmahanta/embyr/issues/115)
- **M7-01:** [#116](https://github.com/bhargavmahanta/embyr/issues/116)
- **Authoritative backend baseline:** `6ccedc366f35de9da5814104a4dfc0add127e173`
- **Migration head:** `0020_learner_projection_foundation`

Android has **not** been initialized. [M7-02 / #117](https://github.com/bhargavmahanta/embyr/issues/117) owns Android foundation initialization after this freeze merges.

## 1. Status and authoritative baseline

This document freezes the M7 Internal Alpha product and client contract against the stated backend commit. It authorizes implementation planning, not a claim that an Android build or hosted alpha environment exists. The sole Alembic head is `0020_learner_projection_foundation`; M6 backend work is complete. M7-01 changes documentation only.

## 2. Product boundary

M7 delivers a native Kotlin/Jetpack Compose Android client for Supabase sign-in, session bootstrap, onboarding, curated starter interests, recommendation or explicit no-result, ACCEPT/SKIP, Exploration list/detail and reviewed delivery, RETURN/PAUSE/RESUME, reflection create/edit, optional single-choice assessment and support, asynchronous evaluation/poll/retry, learner completion, bounded factual Memory, World snapshot/deltas/resync, native forest rendering, process-death and idempotency recovery, and Internal Alpha release validation.

Stories/Weekly Wrapped, practical/artifact journeys, catalog search/detail/connections, direct Exploration start, push/device registration, full offline synchronization, editable account preferences, user-facing export/deletion, iOS, M8 telemetry/beta hardening, recommendation redesign, and changes to M3–M6 semantics are outside M7.

## 3. Architectural authority and source precedence

- [ADR-0001](../adr/0001-native-mobile-clients.md) owns Android-first native delivery, Kotlin and Compose. [ADR-0004](../adr/0004-worldmodel-renderer-boundary.md) owns backend semantic WorldModel and client native rendering authority.
- [API contracts v0.1](../api/api-contracts-v0.1.md) provide general context, including future proposals. [M5 learning lifecycle v1](../api/learning-lifecycle-v1.md) supersedes older v0.1 learning and assessment sketches.
- [M6 projection, Memory and World v1](../api/m6-projection-memory-world-v1.md), its [strict schema](../api/schemas/m6-v1.schema.json) and [public fixtures](../api/fixtures/m6-v1.json) govern Memory/World. [M5 fixtures](../api/fixtures/learning-lifecycle-v1.json) govern learning examples.
- For Android runtime availability, the registered handlers in [`backend/app/api`](../../backend/app/api/) and their tests in [`backend/tests`](../../backend/tests/) prevail. A v0.1 mention alone does not establish an implemented endpoint. The allowlist below is the complete M7 client runtime surface.

## 4. Runtime Android API allowlist

All 23 paths have prefix `/api/v1`. `B` = verified bearer; `M` = bearer plus mapped internal learner (bootstrap first). `K` = required `Idempotency-Key`; `V` = send observed `base_version` (`V*` is accepted as optional by the action handler but required by the Android client); `T` = typed OpenAPI response; `G` = generic OpenAPI response requiring a reviewed Android DTO. A dash means no key/version requirement. Unless stated otherwise, success is HTTP 200. Common failures include 401 for auth, owned-resource 404, 409 for command/version/state conflicts, and 422 for invalid input. Retain the server error code and request ID for recovery; never infer success from a timeout.

| Method and path | Purpose | Auth | K/V | Success | Schema | Important error or recovery |
| --- | --- | :---: | :---: | :---: | :---: | --- |
| POST `/session/bootstrap` | Resolve/create learner profile | B | — | 200 | G | Repeat after auth restore; internal UUID is not a credential |
| GET `/me` | Profile and onboarding state | M | — | 200 | G | `world_revision` may be null |
| GET `/catalog/starter-interests` | Reviewed DOMAIN/AREA starters | M | — | 200 | T | Treat empty curated set honestly |
| POST `/me/onboarding/complete` | Complete onboarding | M | K | 200 | T | Empty starter selection valid; invalid starter 422; already completed 409 |
| PUT `/memory/interests/{entity_id}` | Explicit interest | M | V | 200 | T | `base_version: 0` creates; 409 refetch current Memory |
| POST `/recommendations/next` | Request recommendation or null | M | K | 200 | G | Durable no-result replay; explicit user action only |
| POST `/recommendations/{id}/decision` | ACCEPT/SKIP | M | K | 200 | G | ACCEPT yields Exploration identity; normalize by subsequent GET |
| GET `/explorations` | Owned history | M | — | 200 | T | Opaque cursor; default limit 50, max 100 |
| GET `/explorations/{id}` | Current detail | M | — | 200 | T | Owner-scoped 404; authoritative status/version |
| POST `/explorations/{id}/delivery` | Immutable reviewed work | M | K | 200 | T | Content 503 leaves accepted Exploration intact |
| POST `/explorations/{id}/actions` | RETURN/PAUSE/RESUME | M | K, V* | 200 | T | Conflict: refetch detail and reconcile |
| POST `/explorations/{id}/completion` | Learner finish intent | M | K, V | 200 | T | Completion is not mastery; pending evaluation may continue |
| POST `/explorations/{id}/reflections` | Create reflection | M | K | 200 | T | Keep draft and exact command across ambiguity |
| PATCH `/reflections/{id}` | Edit reflection | M | V | 200 | T | 409: preserve draft, refetch current Reflection |
| POST `/explorations/{id}/assessment-sessions` | Start optional recognition check | M | K | 200 | T | Requires active prepared Exploration; one reviewed interaction |
| GET `/assessment-sessions/{id}` | Current session/feedback | M | — | 200 | T | Read current evaluation and retry state |
| POST `/assessment-sessions/{id}/support-requests` | Persist reviewed support | M | K | 200 | T | Wrong child 404; answered/inactive 409 |
| POST `/assessment-sessions/{id}/responses` | Submit immutable SINGLE_CHOICE answer | M | K | **202** | T | Original PENDING acknowledgment replays; GET current state |
| GET `/assessment-responses/{id}` | Current evaluation run | M | — | 200 | T | PENDING/SUCCEEDED/FAILED and `retry_allowed` |
| POST `/assessment-responses/{id}/evaluation-retries` | Retry eligible failed evaluation | M | K | **202** | T | Only when `retry_allowed`; original answer unchanged |
| GET `/memory/summary` | Bounded factual Memory | M | — | 200 | T | Show CURRENT/PENDING/FAILED freshness |
| GET `/world` | Complete owner World snapshot | M | — | 200 | T | Snapshot and revision must commit together locally |
| GET `/world/changes` | Contiguous revision deltas | M | — | 200 | T | Required integer `after_revision`; 409 `WORLD_RESYNC_REQUIRED` → snapshot |

`GET /world/changes` defaults `limit` to 500 and clamps valid positive values above 1000 to 1000; invalid or out-of-range `after_revision` is 422. The M4 ACCEPT response is **not guaranteed to be an M5 `ExplorationDTO`**: take its Exploration ID and read the current detail. An idempotent assessment answer replay remains its **original HTTP 202 PENDING acknowledgment**, even after the worker finishes: GET the response/session for current state.

## 5. Contract-only and excluded API surface

These **16 v0.1 contract-only routes are absent** from the registered backend and unavailable to Android M7:

| Area | Absent method/path |
| --- | --- |
| Account | PATCH `/me/preferences`; POST `/me/export`; POST `/me/deletion`; GET `/me/operations/{id}` |
| Catalog | GET `/catalog/search`; GET `/catalog/entities/{id}`; GET `/catalog/entities/{id}/connections` |
| Entry | GET `/home` |
| Direct start | POST `/explorations` |
| Practical/artifact | GET `/practical-challenges/{id}`; POST `/artifacts`; GET `/artifacts/{id}` |
| Stories | GET `/stories`; GET `/stories/{id}` |
| Devices | PUT `/devices/{id}`; DELETE `/devices/{id}` |

The three upload routes **are registered**: POST `/uploads`, POST `/uploads/{id}/complete`, GET `/uploads/{id}`. They remain outside M7 because upload authorization/completion exists without a complete practical-artifact creation and validation journey.

**FALSE POSITIVE · NORMAL:** missing `/home` is not an alpha blocker. Entry composes GET `/me`, GET `/explorations`, and optionally GET `/memory/summary`. Recommendation generation follows an explicit learner action. The client must not synthesize a weekly story, suggested revisit, or catalog feed.

## 6. Five frozen Internal Alpha decisions

1. **Application ID:** `app.embyr`; verify identifier ownership/registration before distribution and review a conflict.
2. **Authentication:** Supabase Auth behind app-owned `AuthGateway`; intended alpha method is email OTP/magic link unless the approved alpha project configuration requires another reviewed method.
3. **Environment:** dedicated non-production Embyr backend and Supabase alpha project. Inject URLs and client-safe publishable keys by environment; routine alpha tests do not use production.
4. **Tester data:** disposable alpha accounts; no user-facing export/deletion in M7. A trusted operator mediates deletion. Revisit user-facing policy before M8/private beta.
5. **Operations:** the project owner/operator owns reviewed pilot content, alpha backend, assessment and projection workers, bootstrap/recovery, and release verification.

## 7. Android architecture and dependency policy

Start with one `:app` Gradle module, one Activity, Compose, typed Navigation Compose routes, ViewModels exposing immutable `StateFlow` UI state, coroutines/Flow, repositories, a small journey coordinator, and explicit `AppContainer` with constructor injection. Keep Supabase, transport, persistence and rendering behind narrow interfaces. Do not introduce Hilt or feature modules until measured complexity warrants them.

M7-02 chooses a mutually compatible **stable** Kotlin, Android Gradle Plugin, Compose BOM, Navigation Compose, Lifecycle/ViewModel, coroutines, kotlinx.serialization, Retrofit, OkHttp, Room, DataStore, Supabase Auth and testing set from current official sources. This plan pins no discovery-time versions. Preview dependencies require explicit review. API 26 is the proposed minimum; M7-02 verifies platform and auth-library compatibility before locking it.

## 8. Auth state machine

`SIGNED_OUT → AUTHENTICATING → TOKEN_AVAILABLE → BOOTSTRAPPING → ONBOARDING_REQUIRED | READY`. `AuthGateway` owns OTP/deep-link and protected session restore; an authenticated bearer precedes bootstrap. Bootstrap resolves or creates the mapped learner, then GET `/me` determines onboarding state. Restore/refresh may return to `TOKEN_AVAILABLE`; an expired token gets one coordinated refresh then request replay where safe. Revocation or failed refresh returns to signed out. An unmapped verified identity retries bootstrap, not protected learner routes.

Sign-out and account switch cancel owner-bound in-flight work and select a different cache/outbox namespace before new reads. Process death restores protected auth, then revalidates bearer/profile and durable command state. The internal `app_users.id` is an owner key, never an auth credential.

## 9. Typed API client and error model

Use a handwritten typed Embyr client over Retrofit, OkHttp and kotlinx.serialization because important existing routes expose generic OpenAPI responses. Review DTOs against handler results and public fixtures. Central adapters decode Problem Details (`code`, request ID, status), FastAPI 422 validation shape, nullable recommendation, 202 assessment acknowledgment, strict World integer cursor and 409 `WORLD_RESYNC_REQUIRED`. Preserve unknown server codes as actionable generic errors; do not translate transport timeout into command failure. Supabase token handling stays in `AuthGateway`. Android does not reimplement backend recommendation, learning, Memory or World semantics.

## 10. Idempotency and ambiguous requests

Before each keyed POST network send, persist a durable owner-scoped record containing route, canonical payload, generated key, creation time, state and any known result reference. One logical action uses one key. Replay the **same key and exact path/payload** within the backend's 24-hour window. Never mutate the payload under a key or generate a new command automatically for a timed-out action. Once the replay window expires, use available GET resources to reconcile; if outcome remains ambiguous, show a recoverable unresolved state for user/operator action. This is a contract gap, not a promise of indefinite lookup. Distinguish resource guards from the general 24-hour replay guarantee.

## 11. Version conflict reconciliation

Send observed `base_version` for explicit-interest PUT, reflection PATCH, Exploration action POST (despite runtime optionality), and completion POST (required). On `VERSION_CONFLICT`, refetch authoritative current resource, show what changed and reconcile the learner's intent before a new command. Never silently last-write-wins. Keep local reflection text draft separate from the server Reflection so conflict or process death does not erase it.

## 12. Exploration lifecycle

The server owns Exploration status/version, pinned entity, delivery and completion. ACCEPT creates an identity; GET detail normalizes it. Delivery is reviewed, historical and immutable; a content-generation 503 does not discard the accepted Exploration. RETURN records a return and **does not equal RESUME**; PAUSE/RESUME follow server transitions. Completion records learner intent, not understanding or mastery. It may occur while evaluation is pending; an unanswered active assessment can be abandoned by completion. Reflection may be edited after completion according to M5.

## 13. Assessment 202, polling, and retry

Only one reviewed SINGLE_CHOICE interaction is in M7. POST answer yields HTTP 202/PENDING with immutable answer and queued evaluation. Poll GET `/assessment-responses/{id}` or GET session for current `PENDING → SUCCEEDED | FAILED`; server feedback is authoritative. Show bounded foreground polling with backoff and a persistent waiting state after the bound. Network loss/backgrounding pauses active polling, while saved session/response IDs allow foreground resume after process death. FAILED is a visible terminal state, never an endless spinner. POST evaluation retry only when `retry_allowed`; it creates a new run without changing the original answer. No free-text or synchronous grading assumption.

## 14. Memory presentation

Display projection freshness as `CURRENT`, `PENDING`, or `FAILED`. Present learning preferences, explicit interests with `AVAILABLE`/`UNAVAILABLE`, recently explored entries, recognition evidence and truncation flags factually. Preserve source bounds and unavailable labels; do not convert a delayed projection into a claim about learner progress. Do not infer/display mastery percentage, hidden score, classification confidence as ability, psychological label, long-term interests, or voluntary revisits. M6 strict schema and fixtures govern fields and empty shape.

## 15. World synchronization

First open GETs `/world`. Persist semantic objects and revision **atomically per owner**. Refresh with GET `/world/changes?after_revision=X` using the locally committed integer revision. Validate page `from_revision`, ascending contiguous change revisions, object ID consistency and supported `layout_version`; apply complete replacement objects by ID atomically. Advance local revision only in the same commit as object updates. Continue paging from `to_revision` while `has_more`, allowing `current_revision` to advance between requests.

On 409 `WORLD_RESYNC_REQUIRED`, missing/corrupt cache, unsupported layout or account switch, discard that owner's derived view and fetch a complete snapshot. Never synthesize semantic growth or topology on the client. Empty revision-zero snapshots are valid.

## 16. Native renderer

Initial forest renderer is Compose Canvas. The backend owns node existence, `growth_state`, entity/version pin, revision, topology, logical coordinates and semantic meaning. Android owns pixel mapping, camera, pan/zoom, animation, culling, hit testing, decorative rendering and visual variation; `visual_seed` controls variation only. Provide focusable, semantic Compose node interactions and an accessible list/alternative because Canvas drawing alone is insufficient for TalkBack.

## 17. Local persistence and owner separation

Room stores the durable keyed command outbox, owner-specific World snapshot/revision and operation recovery state; DataStore stores small non-relational settings. Protect auth/session/refresh material with Android Keystore-backed storage. Key all private caches/drafts/outbox entries to the mapped owner; clear or switch namespace atomically on account change. No cached owner data may render before the new profile is resolved.

## 18. Online/offline boundary

M7 is online first. It may retain a cached World, cached Memory, delivered work, reflection draft and exact pending commands; label stale cached reads visibly. Do not promise general offline task library, offline recommendations, offline semantic progression, full background synchronization or an offline conflict engine. A queued command is an unresolved action until authoritative response/reconciliation.

## 19. Security and privacy

Release traffic uses HTTPS. Package only client-safe configuration: no service-role key, database credential or backend secret. Disable release body logging and redact bearer/refresh tokens, reflection text, assessment answers, signed capabilities/URLs and private payloads from logs and crash metadata. Enforce owner-isolated cache and review sensitive backup/restore policy, including account switching. Do not impose a global `FLAG_SECURE` requirement without a product need.

## 20. Testing architecture

- **Pure unit:** auth transitions, durable idempotency, version reconciliation, assessment state, World reducer and renderer transforms.
- **Repository/network:** fakes plus MockWebServer for 401/refresh, nullable recommendation, 202 replay/poll, Problem Details/422, 409 resync, pagination and ambiguous timeout.
- **Contract fixtures:** decode [M5 public fixtures](../api/fixtures/learning-lifecycle-v1.json) and [M6 strict public fixtures](../api/fixtures/m6-v1.json) against the M6 schema.
- **Compose:** loading/empty/error, navigation, semantics, TalkBack focus and large text.
- **Instrumented:** Room transactions, process recreation, secure session restore and cross-account isolation.
- **Real backend/device:** dedicated alpha backend, operating workers, approved Supabase alpha configuration, second account and physical reference device.

## 21. Operational alpha requirements

**CODE READINESS ≠ ALPHA ENVIRONMENT READINESS.** M7-06 must prove the alpha backend is reachable, Supabase alpha project configured, reviewed pilot content installed, assessment and projection workers running, operator recovery available, reference device identified and release signing configured. None of these are claimed by this documentation freeze or backend unit tests.

## 22. Dependency graph

`#116 → #117 → #118 → #119 → #120 → #121`. M7-06 (#121) also depends on #118, #119 and #120 directly. M7-02 (#117) remains **BLOCKED BY #116** until this documentation merges and #116 completes; opening this PR does not unblock it.

## 23. Internal Alpha exit criteria

- Fresh install authenticates, bootstraps, onboards and obtains a recommendation or explicit no-result.
- ACCEPT/SKIP works without duplicate Exploration under retry; reviewed delivery, RETURN/PAUSE/RESUME, reflection create/edit and completion work.
- Optional support and SINGLE_CHOICE assessment work, with HTTP 202, current-state polling, eligible retry and process-death recovery.
- Memory is truthful, bounded and freshness-aware; World snapshot, deltas, paging and resync work; native forest runs on a real device.
- Exact replay is safe within 24 hours; ambiguous expiry is visible; account switching isolates auth, commands and cached data.
- Critical TalkBack and large-text journeys pass; signed release APK and AAB build; real-device end-to-end journey passes against dedicated alpha backend and operating workers.

## 24. Known risks and deferred decisions

| Classification | Recorded finding or decision |
| --- | --- |
| VALID · HIGH | 23-route runtime slice and ADR authority verified against pinned backend. |
| FALSE POSITIVE · NORMAL | Missing `/home` is not an alpha blocker; Entry composes existing reads. |
| STALE · LOW | Root README pre-implementation wording predates completed M6 backend. |
| FUTURE-SCOPE · NORMAL | Upload handlers exist without complete artifact journey; exclude them. |
| CONTRACT_GAP · NORMAL | No universal command lookup beyond 24-hour replay; reconcile by GET or surface unresolved state. |
| IMPLEMENTATION_DIVERGENCE · HIGH | Old synchronous/free-text assessment examples are obsolete; M5 SINGLE_CHOICE/202 governs. |
| IMPLEMENTATION_DIVERGENCE · NORMAL | Generic OpenAPI responses need reviewed handwritten mobile DTOs. |
| MANUAL_DECISION · NORMAL | Identifier ownership, approved auth config, alpha endpoints, reference device/frame target and signing remain execution/release checks. |
| TEST_OVERREACH · NORMAL | Backend tests do not prove hosted alpha or device readiness. |

## 25. Explicit non-goals

M7-01 adds no Android code, Gradle files, dependency lockfiles, backend feature code, database changes, migrations, new endpoints, recommendation changes, M3–M6 semantic changes, practical-artifact client, Stories, iOS or M8 work. This freeze does not merge its own PR or begin M7-02.
