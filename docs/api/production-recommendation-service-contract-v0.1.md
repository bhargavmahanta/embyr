# Production Recommendation Service Contract v0.1 (M4-1)

## Status and authority

**Frozen M4-1 production mapping (`production-recommendation/v1`, #59).** This document defines the production integration boundary for the frozen `m3-simulation/v5` decision semantics. The owner-reviewed initial retrieval and distance policies are recorded below. Their empirical calibration and implementation belong to later issues; the values and behavior here are effective until a new version is reviewed. It does not revise the M3 contract or the frozen client API in `api-contracts-v0.1.md`.

Authority: `api-contracts-v0.1.md` governs client-visible behavior and enums; `research/recommendation/simulation-contract-v0.1.md` governs candidate, eligibility, ranking, and explanation semantics; this document governs the production mapping between them.

## 1. Service boundary

The first M4 path runs synchronously inside the existing FastAPI modular monolith as authenticated `app_backend`. One PostgreSQL `REPEATABLE READ READ ONLY` transaction, with transaction-local `app.user_id`, assembles every database read needed for one consistent logical recommendation input. After that transaction closes, provider/network calls and candidate processing run; a separate writable command transaction establishes transaction-local `app.user_id` independently, rechecks ownership and target validity, and persists the selected presentation and provenance. The service returns the frozen `Recommendation` DTO. A valid empty result after eligibility or mode filtering returns HTTP 200 with `{"recommendation": null}` and creates no recommendation row; idempotent replay returns the same empty outcome.

`POST /api/v1/recommendations/next` and `POST /api/v1/recommendations/{recommendation_id}/decision` are the only recommendation commands frozen for v0.1. Both require `Idempotency-Key`. A replay with the same authenticated user, command, and request fingerprint returns the same durable logical result; a changed fingerprint conflicts. ACCEPT atomically records the decision, creates a new user-owned Exploration retaining `recommendation_id`, and emits the relevant Experience Ledger events in the existing writable command/idempotency transaction; SKIP records its decision and event. The existing `idempotency_records` and `learning_events.command_id`/`event_ordinal` mechanisms are reused.

The `accept-intent/v1` mapping derives the created Exploration's `learning_intent` solely from the accepted recommendation's persisted `mode`:

| Accepted recommendation `mode` | Exploration `learning_intent` |
|---|---|
| CONTINUE | RELATED_EXPLORATION |
| REVISIT | RETENTION_REVISIT |
| EXPLORE | DIRECT_INTEREST |
| SURPRISE | SERENDIPITY |
| CREATE | PRACTICAL_SUPPORT |

CREATE is reserved and unreachable in initial M4 because CREATE returns an empty result. `PREREQUISITE_SUPPORT` is not inferred from mode. Candidate sources, explanation codes, distance band, and final score do not affect this mapping.

No recommendation job, worker generation path, batch response, refresh/history endpoint, or Android implementation is introduced by this contract. The first release generates learning-entity targets only. Practical-challenge generation is deferred; `CREATE` requests have no eligible production candidate until that capability is added, using the same explicit empty response.

## 2. Production input assembly

| M3 domain | Production source | Required mapping |
|---|---|---|
| `learner` | Authenticated `app_users.id` | Replace synthetic identity; never trust a client-supplied user ID. |
| Ontology entities, versions, domains, objectives | `learning_entities`, `learning_entity_versions`, `entity_domains`, `learning_objectives` | Read one coherent entity/version view in the PostgreSQL `REPEATABLE READ READ ONLY` input transaction; preserve canonical IDs. |
| RELATED_TO and REQUIRES | `ontology_edges` | RELATED_TO nominates bidirectionally; versioned, objective-relative REQUIRES is readiness-only as defined below. |
| Explicit interest | `explicit_interest_preferences` | Preserve MORE, LESS, NEUTRAL, PAUSED, NOT_INTERESTED and attach the selected entity version. |
| Inferred interest | `learner_interest_state` | Preserve recent and long-term affinity separately from explicit interest. |
| Objective state | `learner_objective_state` and `learning_objectives` | Produce SATISFIED, UNSATISFIED, or UNKNOWN without inventing a numeric mastery threshold. |
| Challenge ability | `learner_challenge_state` | Map `area_id` and `ability_estimate`; absence remains absent. |
| Exploration history | `explorations` | ACTIVE supports continuation; COMPLETED supports revisit. |
| Semantic vectors | `entity_embeddings` | Use only Voyage AI `voyage-4` document embeddings at 1024 dimensions for the initial indexed corpus; generate one same-model `input_type=query` embedding per anchor outside the snapshot transaction. |
| Query anchors | ACTIVE `explorations` plus `explicit_interest_preferences` with MORE | Preserve each ACTIVE exploration's historical entity/version, but use it for GRAPH/SEMANTIC only if that exact version is still current and deliverable. Resolve each MORE preference to the current deliverable entity version in the same input snapshot. Deduplicate and sort by entity ID/version. This is an explicit production selection rule, not inference inside M3. |
| Simulation configuration | Checked-in `recommendation-profile/v1` | Never read per-scenario fixtures or treat weights as learner truth. |

`scenario_id`, synthetic flags, fixture vectors, evaluation expectations, and the `SimulationResult` envelope have no production input equivalent.

The v1 recommendation corpus includes only `learning_entities.status` values `REVIEWED` and `PUBLISHED`; any other status is excluded. This is a service policy, while `learning_entities.status` remains schema-level Text. A new recommendation target must have non-null `learning_entities.current_version`, an existing matching `learning_entity_versions` row, and target version exactly equal to `current_version`. A missing current version or version row is not recommendable; there is no fallback to DRAFT or another status. M4 v1 never newly delivers a superseded historical version.

ACTIVE and COMPLETED explorations retain their historical `(entity_id, entity_version)` as provenance; neither is silently upgraded. An ACTIVE exploration supplies a GRAPH/SEMANTIC anchor only if its exact preserved version is still the current deliverable version. Otherwise it remains history but supplies no such anchor. A COMPLETED exploration whose preserved version is superseded cannot nominate a REVISIT target in v1. MORE preferences resolve to the current deliverable version within the same input snapshot. Version migration and historical revisit behavior require a later explicit contract.

## 3. Decision pipeline and invariants

The production sequence is: (1) generate all five M3 source nominations from GRAPH, SEMANTIC, EXPLICIT_INTEREST, HISTORY_CONTINUATION, and REVISIT; (2) normalize duplicate entity/version targets and their complete source provenance; (3) evaluate M3 eligibility and objective-relative prerequisites; (4) score the full eligible population with `recommendation-profile/v1` and the eight M3 features; (5) apply the M3 deterministic tie break and `DOMAIN_COVERAGE` reranking; (6) build M3 explanation codes; (7) apply the requested mode as a stable filter over the fully ranked and explained population; (8) preserve each survivor's existing M3 score, traces, explanation codes, and original M3 `final_rank`, without reranking; (9) apply production `top_k` after filtering. The first surviving result is delivered by the single-item API. Request mode does not change the M3 scoring or reranking population.

The source adapter preserves the frozen M3 source names and provenance fields. GRAPH records anchor, hop count, and canonical shortest path; SEMANTIC records anchor and cosine similarity; EXPLICIT_INTEREST records the explicit preference and version; HISTORY_CONTINUATION records the active exploration; REVISIT records the completed exploration. Each source may nominate the same entity/version, and normalization merges its paths. Production retrieval may bound the nominated set under a separately versioned #61 policy; the adapter must still use the M3 source categories and deterministic order. The recommendation row retains selected source categories only; full paths stay transient.

| M3 exclusion | Production trigger | Outcome |
|---|---|---|
| `PREREQUISITE_UNMET` | At least one HARD REQUIRES objective is UNSATISFIED. | Candidate excluded; never turned into a recommendation reason. |
| `EXPLICITLY_PAUSED` | Explicit preference is PAUSED. | Candidate excluded. |
| `NOT_INTERESTED` | Explicit preference is NOT_INTERESTED. | Candidate excluded. |
| `INVALID_TARGET` | Nominated target is absent from the coherent versioned ontology view. | Candidate excluded. |
| `INSUFFICIENT_STATE` | At least one HARD REQUIRES objective is UNKNOWN. | Candidate excluded. |

All applicable exclusions are collected in M3 canonical order; none is converted to a positive explanation code. Counts by reason may be emitted as bounded telemetry. A no-eligible result is the explicit empty API body, not a synthesized fallback target.

The production mode filter tests each normalized candidate's complete `candidate_sources` set after M3 ranking and explanation. CONTINUE requires HISTORY_CONTINUATION; REVISIT requires REVISIT; EXPLORE requires at least one of GRAPH, SEMANTIC, or EXPLICIT_INTEREST. SURPRISE requires at least one of GRAPH or SEMANTIC **and** no EXPLICIT_INTEREST source. CREATE matches nothing in v1. In particular, SURPRISE does not delete an EXPLICIT_INTEREST path to keep a multi-source candidate. This filter introduces no M3 exclusion reason, no cross-mode fallback, and no rerank. An empty post-filter result is valid. The requested mode is persisted as `mode`.

For every `REQUIRES` edge, `source_entity_id` and `source_entity_version` identify the dependent candidate; `target_entity_id` and `target_entity_version` identify its prerequisite. Thus if B requires A, the edge is source B → target A. Eligibility for B examines **outgoing** REQUIRES edges whose source ID/version exactly matches B. Each such edge must carry both endpoint IDs and versions, `objective_id`, and `requirement` (`HARD` or `SOFT`). `objective_id` must reference a `learning_objectives` row whose entity ID/version exactly matches the edge's target ID/version. Learner objective state is looked up by that exact objective ID and prerequisite entity/version; no unrelated objective state can satisfy it. An incoming REQUIRES edge does not make the current candidate dependent on that prerequisite. REQUIRES never nominates a candidate; RELATED_TO remains bidirectional graph nomination.

`UNDERSTOOD` and `RETAINED` categorical objective states map to SATISFIED; another frozen categorical state maps to UNSATISFIED; absent matching categorical state/evidence maps to UNKNOWN. No `understanding_estimate`, `support_required`, or other numeric threshold decides the state. HARD UNSATISFIED excludes with `PREREQUISITE_UNMET`; HARD UNKNOWN excludes with `INSUFFICIENT_STATE`. SOFT requirements never hard-exclude. The existing entity-only `ontology_edges` schema cannot represent the required endpoint versions and objective identity; a later M4 migration must add them without editing frozen migrations 0001–0013.

PAUSED and NOT_INTERESTED are hard exclusions. An UNSATISFIED hard prerequisite excludes with PREREQUISITE_UNMET; UNKNOWN excludes with INSUFFICIENT_STATE. A score or rerank adjustment cannot lift an ineligible candidate. Explicit/inferred conflict suppresses only the effective inferred contribution while preserving its raw trace. Empty eligibility is a valid outcome.

Production tests must pin the corresponding M3 mechanics without running the full 27-scenario harness on each issue. Cheap runtime safety checks cover ineligible and unmet-hard-prerequisite selection; no second generation run is performed for determinism. The simulator's invariant results and thirteen descriptive metrics are not API fields.

## 4. Embedding and ranking profile decisions

The initial production embedding identity is Voyage AI `voyage-4`, 1024-dimensional float vectors, cosine similarity, with ontology documents embedded using `input_type=document` and retrieval queries embedded using `input_type=query`. The intended database storage is `pgvector vector(1024)`. The embedding is derived and replaceable; provider calls live behind an embedding adapter, outside recommendation decision logic. Persist provider, model, dimension, input version, and input type metadata. Do not mix different model identities in one indexed search space. A model transition requires an explicit re-embedding/version transition; M3's synthetic 4-D vectors are never migrated. Voyage's current documentation confirms `voyage-4` supports 1024 dimensions and both input types: [Voyage text embeddings](https://docs.voyageai.com/docs/embeddings).

The first ranking profile is the immutable checked-in [`recommendation-profile-v1.json`](../../backend/app/recommendation/profiles/recommendation-profile-v1.json), loaded by version. `ranking_model_version` is exactly `recommendation-profile/v1`; the profile records its `m3-simulation/v5` semantic lineage. A change to any weight or rerank parameter requires a new profile version. Its eight feature weights are:

```json
{
  "readiness": 0.14,
  "difficulty_fit": 0.18,
  "explicit_interest": 0.22,
  "inferred_interest": 0.08,
  "graph_proximity": 0.12,
  "semantic_similarity": 0.14,
  "continuation_value": 0.07,
  "revisit_value": 0.05
}
```

Reranking uses `DOMAIN_COVERAGE` with `diversity_weight: 0.08`. These are owner-selected initial values, not empirically calibrated quality claims. `ranking_model_version` must identify this exact profile and the M3 semantic lineage. Production `top_k` is 1 for the single-item API and applies only after stable mode filtering of the full eligible, scored, reranked, and explained population; a survivor keeps its original M3 `final_rank` even when that rank exceeds 1. The initial versioned [`recommendation-retrieval/v1`](../../backend/app/recommendation/profiles/recommendation-retrieval-v1.json) policy uses exact cosine search, minimum similarity 0.55, at most 40 semantic candidates, and bidirectional RELATED_TO traversal to two hops with at most 100 graph candidates. Shortest paths break ties by lexicographic entity/version path. Bounds are initial and uncalibrated; #61 must verify them against production-shaped data and use a new policy version to change them. The semantic cap applies to distinct entity/version targets after merging all per-anchor exact-search results; retain targets by highest cosine similarity descending, then entity ID/version ascending. Preserve every qualifying anchor path for retained targets. The graph cap likewise applies to distinct targets after all anchored two-hop paths are found; retain targets by shortest hop ascending, then canonical path and entity ID/version ascending, while preserving every qualifying path for retained targets. Filtering a bounded production corpus is a declared source-adapter policy and never changes the M3 score/rerank arithmetic on the retained eligible population.

The deterministic v1 semantic query recipe is `semantic-query-text/v1`: build one query text per sorted anchor from the canonical title and summary of its exact selected entity version, formatted exactly as `TITLE: {canonical_title}\nSUMMARY: {canonical_summary}`. The two labeled lines have exactly one newline between them, no blank line, no instructional prefix, no learner-authored or free-form text, and no other anchor. Do not aggregate anchors. The recipe identity participates in generation/config provenance and is persisted as the query input version with embedding metadata. All required logical-input database reads, including the versioned document embeddings needed for exact cosine search, occur in one PostgreSQL `REPEATABLE READ READ ONLY` transaction under RLS. After that transaction closes, provider/network calls generate query embeddings and exact search compares them with the captured document vectors. The separate writable command transaction independently sets transaction-local `app.user_id` and rechecks authenticated ownership and current deliverable target version before persistence.

The independently versioned ontology document recipe is `ontology-entity/v1`: submit the exact selected-version text `TITLE: {canonical_title}\nSUMMARY: {canonical_summary}` with one newline and Voyage `input_type=document`. Persist `sha256:` plus the lowercase SHA-256 hex digest of those exact UTF-8 bytes as `embedding_input_fingerprint`, along with provider, model, dimension, input version, and input type. The query recipe uses the same text layout but retains its separate `semantic-query-text/v1` identity and `input_type=query`. A changed title or summary makes an old document embedding stale: the input snapshot checks its fingerprint against current canonical text and excludes it before computing the recommendation input fingerprint. Missing or stale embeddings contribute no SEMANTIC path. Corpus data is derived and replaceable; a provider/model/dimension/input-version transition requires explicit re-embedding. #61 performs no implicit online backfill. Exact search has O(anchors × documents × 1024) comparison cost and needs a measured scale gate before ANN or larger corpora.

Migration deployment is `0014_objective_categorical_state` → `0015_retrieval_expand` → `0015_recommendation_retrieval`. The expansion adds nullable REQUIRES fields and version/objective identity keys without changing legacy rows. Before enforcing 0015, an ontology operator must explicitly curate each legacy REQUIRES edge's source version, target version, exact target-version objective, and HARD/SOFT requirement; the migration never infers them. The operator must also clear the old *derived* embedding corpus before enforcement, then regenerate Voyage `voyage-4` 1024-D `ontology-entity/v1` document vectors and input fingerprints after enforcement. Existing REQUIRES ontology edges are retained. The final revision refuses unresolved REQUIRES rows or uncleared old vectors. The composite objective foreign key requires the objective to belong to the exact prerequisite entity/version.

A faithful M3 prerequisite mapping cannot be computed from `learner_objective_state.understanding_estimate` or `support_required`: the frozen M3 rule forbids numeric evidence from deciding hard prerequisite state. #60 must provide a categorical objective projection using the frozen vocabulary. Until a matching categorical state exists, the prerequisite is UNKNOWN and a HARD requirement excludes with `INSUFFICIENT_STATE`. #61 must implement the versioned, objective-relative REQUIRES representation defined in §3 through a new reviewed migration, never by editing M1 migrations.

## 5. Persisted recommendation mapping

| Production field | M3 source or production-only meaning |
|---|---|
| `user_id` | Authenticated principal, enforced by RLS and explicit ownership predicates. |
| `entity_id`, `entity_version` or `challenge_id` | Exactly one versioned production target; v1 only delivers an entity at its existing current version with REVIEWED or PUBLISHED status. M3 candidates themselves target entities only. |
| `mode`, `distance_band` | `mode` copies the request. `distance_band` uses the owner-reviewed `distance-band/v1` policy below; neither changes M3 ranking. |
| `ranking_model_version` | Immutable identity of the reviewed ranking/configuration profile, tied to M3 contract lineage. |
| `score_components` | Bounded selected-result scoring provenance, excluding raw learner snapshots and vectors. |
| `reason_code` | First applicable M3 explanation code in canonical order, or NULL if there are no codes. Existing NOT NULL schema requires a reviewed migration in #63. |
| `presentation_version`, `presentation` | `recommendation-copy/v1` static hook/reason for the primary code, plus all machine explanation codes and bounded ranked-versus-shown provenance. Zero codes yield null hook/reason, with no generic fallback. |
| `presented_at` | Time the persisted recommendation is delivered. |
| `decision`, `decided_at` | Optional ACCEPT or SKIP and its time; no other recommendation lifecycle states are frozen. |

The row has no generation-run identity, expiry, viewed state, full candidate set, or full score/rerank trace. The nullable `reason_code` change is necessary because M3 permits zero explanation codes and the owner forbids a generic fallback. The service must not assume that `SimulationResult` can be serialized into this row or returned to clients.

The versioned [`distance-band/v1`](../../backend/app/recommendation/profiles/distance-band-v1.json) mapping uses the closest applicable signal. HISTORY_CONTINUATION, REVISIT, or EXPLICIT_INTEREST gives COMFORT; one GRAPH hop or cosine ≥0.80 gives ADJACENT; two GRAPH hops or cosine in [0.65, 0.80) gives FRONTIER; cosine in [0.55, 0.65) gives WILD. Precedence is COMFORT, ADJACENT, FRONTIER, WILD. If no signal qualifies, use ADJACENT. The band represents curiosity/retrieval distance only and never uses readiness, difficulty fit, score, or final rank. Thresholds are initial and uncalibrated. No band value affects M3 ranking.

## 6. Client boundary

The frozen `Recommendation` DTO exposes ID, target type and summary, mode, distance band, hook, reason, and presentation time. It does not expose `SimulationResult`, raw scores, feature weights, candidate-source paths, exclusion reasons, or invariant reports. The request accepts the documented mode, available minutes, and practical context; no client-supplied learner state, anchors, weights, or config version are accepted.

The API is online-first with idempotent mobile outbox replay. No offline recommendation cache or expiration contract is frozen. All machine explanation codes are retained in compact private presentation provenance, in M3 canonical order. The owner-reviewed templates live in [`recommendation-copy-v1.json`](../../backend/app/recommendation/profiles/recommendation-copy-v1.json). The first applicable code is primary and alone selects the `recommendation-copy/v1` static hook/reason template. With zero codes, hook and reason are null. No LLM, fallback reason, runtime rationale recomputation, or ranking change occurs. Localization may add versioned templates later; client exposure of machine codes requires an API revision.

## 7. Security and observability

All request-path database transactions use `app_backend`, transaction-local `app.user_id`, forced RLS, and explicit ownership checks. The logical-input snapshot transaction is `REPEATABLE READ READ ONLY`; the later command/persistence transaction is separate and writable, independently establishes `app.user_id`, and rechecks relevant ownership and target validity. `app_worker` is not part of this synchronous path; its BYPASSRLS privilege must never be treated as an ownership check. Experience Ledger entries carry references and bounded metadata, not copied private learner content.

Bounded operational telemetry may include request ID, configuration version, candidate and eligible counts, exclusions by reason, selected source mix, latency, and failure category. Do not log raw learner state, vectors, full candidate paths, or the entire M3 metrics object by default.

## 8. Contract verification

M4-1 adds narrow assertions for the owner-reviewed profile and copy, and the production request/response shapes against the existing API and recommendation row. Later issues own mapper, retrieval, ranking-adapter, persistence, endpoint, and end-to-end tests. The full M3 harness runs only after a frozen semantic/shared-simulator change or at the final milestone regression gate.

## 9. Implementation responsibilities and limits

#60 implements the `REPEATABLE READ READ ONLY` input snapshot and objective projection. #61 implements the initial retrieval policy, validates its limits, and freezes the document refresh/input-version process and REQUIRES representation. #62 integrates unchanged M3 scoring and explanation mechanics, followed by stable mode filtering. For each candidate, only matching entity-domain challenge states with finite `ability_estimate` in `[0, 1]` are considered: choose the primary matching domain when its state is valid, otherwise the lexicographically first matching domain with a valid state, otherwise pass no challenge state so M3 gives `difficulty_fit = 0`. Out-of-range stored values remain unchanged and are absent for ranking. `ProductionRanking.ranked` is the full eligible, scored, DOMAIN_COVERAGE-reranked, explained population before mode filtering; `selected` is the first post-filter survivor or null, retaining its original `final_rank`. Production `top_k = 1` applies after filtering. #63 owns the nullable `reason_code` migration and compact selected-result persistence. #64 implements both endpoints, the `accept-intent/v1` and `distance-band/v1` mappings, and separate writable command transactions. #65 validates the targeted flow; #66 documents the final architecture and limits.

The initial retrieval thresholds and ranking weights are not quality-calibrated. The `entity_embeddings` dimension, provider/model/input-version metadata, objective-relative REQUIRES representation, and categorical objective projection still require new reviewed migrations in the relevant implementation issues. No simulator fixture default fills a production gap. A change to M3 semantics requires an explicit M3 contract revision with evidence.
