# Production Recommendation Service Contract v0.1 (M4-1)

## Status and authority

**Frozen M4-1 production mapping (`production-recommendation/v1`, #59).** This document defines the production integration boundary for the frozen `m3-simulation/v5` decision semantics. The owner-reviewed initial retrieval and distance policies are recorded below. Their empirical calibration and implementation belong to later issues; the values and behavior here are effective until a new version is reviewed. It does not revise the M3 contract or the frozen client API in `api-contracts-v0.1.md`.

Authority: `api-contracts-v0.1.md` governs client-visible behavior and enums; `research/recommendation/simulation-contract-v0.1.md` governs candidate, eligibility, ranking, and explanation semantics; this document governs the production mapping between them.

## 1. Service boundary

The first M4 path runs synchronously inside the existing FastAPI modular monolith under authenticated `app_backend` transactions and transaction-local `app.user_id`. The input snapshot transaction closes before a provider call; a later write transaction rechecks the target. It reads a consistent production input snapshot, retrieves and normalizes candidates, excludes ineligible candidates, ranks eligible candidates, applies `DOMAIN_COVERAGE` if configured, builds contextual explanation codes, selects the first result, persists its presentation and provenance, and returns the frozen `Recommendation` DTO. A valid empty eligible set returns HTTP 200 with `{"recommendation": null}` and creates no recommendation row; idempotent replay returns the same empty outcome.

`POST /api/v1/recommendations/next` and `POST /api/v1/recommendations/{recommendation_id}/decision` are the only recommendation commands frozen for v0.1. Both require `Idempotency-Key`. A replay with the same authenticated user, command, and request fingerprint returns the same durable logical result; a changed fingerprint conflicts. ACCEPT atomically records the decision, creates a new user-owned Exploration, and emits the relevant Experience Ledger events; SKIP records its decision and event. The existing `idempotency_records` and `learning_events.command_id`/`event_ordinal` mechanisms are reused.

No recommendation job, worker generation path, batch response, refresh/history endpoint, or Android implementation is introduced by this contract. The first release generates learning-entity targets only. Practical-challenge generation is deferred; `CREATE` requests have no eligible production candidate until that capability is added, using the same explicit empty response.

## 2. Production input assembly

| M3 domain | Production source | Required mapping |
|---|---|---|
| `learner` | Authenticated `app_users.id` | Replace synthetic identity; never trust a client-supplied user ID. |
| Ontology entities, versions, domains, objectives | `learning_entities`, `learning_entity_versions`, `entity_domains`, `learning_objectives` | Read one coherent entity/version view in a PostgreSQL REPEATABLE READ transaction; preserve canonical IDs. |
| RELATED_TO and REQUIRES | `ontology_edges` | Adapt entity-level edges to versioned targets; preserve M3 RELATED_TO bidirectionality and objective-relative prerequisite semantics. |
| Explicit interest | `explicit_interest_preferences` | Preserve MORE, LESS, NEUTRAL, PAUSED, NOT_INTERESTED and attach the selected entity version. |
| Inferred interest | `learner_interest_state` | Preserve recent and long-term affinity separately from explicit interest. |
| Objective state | `learner_objective_state` and `learning_objectives` | Produce SATISFIED, UNSATISFIED, or UNKNOWN without inventing a numeric mastery threshold. |
| Challenge ability | `learner_challenge_state` | Map `area_id` and `ability_estimate`; absence remains absent. |
| Exploration history | `explorations` | ACTIVE supports continuation; COMPLETED supports revisit. |
| Semantic vectors | `entity_embeddings` | Use only Voyage AI `voyage-4` document embeddings at 1024 dimensions for the initial versioned corpus; generate one same-model `input_type=query` embedding per anchor outside the snapshot transaction. |
| Query anchors | Active `explorations` plus `explicit_interest_preferences` with MORE | Preserve each ACTIVE exploration’s entity/version; resolve each MORE preference to the entity’s current version. Deduplicate and sort by entity ID/version; discard missing or inactive versions. This is an explicit production selection rule, not inference inside M3. |
| Simulation configuration | Checked-in `recommendation-profile/v1` | Never read per-scenario fixtures or treat weights as learner truth. |

`scenario_id`, synthetic flags, fixture vectors, evaluation expectations, and the `SimulationResult` envelope have no production input equivalent.

## 3. Decision pipeline and invariants

The M3 stage order remains: nominate from GRAPH, SEMANTIC, EXPLICIT_INTEREST, HISTORY_CONTINUATION, and REVISIT; retain only nomination paths permitted by the requested mode; normalize duplicate entity/version targets and source provenance; evaluate hard eligibility and objective-relative prerequisites; score only eligible candidates with the eight named features; apply the frozen deterministic tie break and optional `DOMAIN_COVERAGE`; build explanations from the ranked trace; select the first result for the single-item API.

The source adapter preserves the frozen M3 source names and provenance fields. GRAPH records anchor, hop count, and canonical shortest path; SEMANTIC records anchor and cosine similarity; EXPLICIT_INTEREST records the explicit preference and version; HISTORY_CONTINUATION records the active exploration; REVISIT records the completed exploration. Each source may nominate the same entity/version, and normalization merges its paths. Production retrieval may bound the nominated set under a separately versioned #61 policy; the adapter must still use the M3 source categories and deterministic order. The recommendation row retains selected source categories only; full paths stay transient.

| M3 exclusion | Production trigger | Outcome |
|---|---|---|
| `PREREQUISITE_UNMET` | At least one HARD REQUIRES objective is UNSATISFIED. | Candidate excluded; never turned into a recommendation reason. |
| `EXPLICITLY_PAUSED` | Explicit preference is PAUSED. | Candidate excluded. |
| `NOT_INTERESTED` | Explicit preference is NOT_INTERESTED. | Candidate excluded. |
| `INVALID_TARGET` | Nominated target is absent from the coherent versioned ontology view. | Candidate excluded. |
| `INSUFFICIENT_STATE` | At least one HARD REQUIRES objective is UNKNOWN. | Candidate excluded. |

All applicable exclusions are collected in M3 canonical order; none is converted to a positive explanation code. Counts by reason may be emitted as bounded telemetry. A no-eligible result is the explicit empty API body, not a synthesized fallback target.

The production mode filter runs on nomination paths before M3 normalization and eligibility; it is a declared retrieval constraint, not a new M3 exclusion reason. CONTINUE retains HISTORY_CONTINUATION; REVISIT retains REVISIT; EXPLORE retains GRAPH, SEMANTIC, and EXPLICIT_INTEREST; SURPRISE retains GRAPH and SEMANTIC but drops EXPLICIT_INTEREST nomination paths; CREATE has no supported entity-only nominations in v1. An entity nominated through more than one permitted path retains all permitted paths. The requested mode is persisted as `mode`; the score and explanation mechanics remain unchanged.

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

Reranking uses `DOMAIN_COVERAGE` with `diversity_weight: 0.08`. These are owner-selected initial values, not empirically calibrated quality claims. `ranking_model_version` must identify this exact profile and the M3 semantic lineage. `top_k` is internally 1 for the single-item API; the full eligible population is still scored, reranked, and explained before selecting its first result. The initial versioned [`recommendation-retrieval/v1`](../../backend/app/recommendation/profiles/recommendation-retrieval-v1.json) policy uses exact cosine search, minimum similarity 0.55, at most 40 semantic candidates, and bidirectional RELATED_TO traversal to two hops with at most 100 graph candidates. Shortest paths break ties by lexicographic entity/version path. Bounds are initial and uncalibrated; the retrieval adapter enforces them, and a measured scale review must precede any new policy version. The semantic cap applies to distinct entity/version targets after merging all per-anchor exact-search results; retain targets by highest cosine similarity descending, then entity ID/version ascending. Preserve every qualifying anchor path for retained targets. The graph cap likewise applies to distinct targets after all anchored two-hop paths are found; retain targets by shortest hop ascending, then canonical path and entity ID/version ascending, while preserving every qualifying path for retained targets. Filtering a bounded production corpus is a declared source-adapter policy and never changes the M3 score/rerank arithmetic on the retained eligible population.

The v1 semantic query recipe is `semantic-query/v1`: for each sorted anchor, concatenate that anchor's selected-version canonical title, two newline characters, and selected-version canonical summary, with no learner text or other anchors. The `entity-document/v1` corpus recipe uses the same selected-version title, two newline characters, and summary with Voyage `input_type=document`. An ontology version or title/summary change requires refreshing that version's document embedding before it enters the searchable corpus. The corpus is derived and replaceable; a provider/model/dimension/input-version transition requires explicit re-embedding. #61 reads only matching identity rows and makes no implicit online backfill. A missing embedding simply contributes no SEMANTIC path. Exact search currently loads the versioned corpus in the repeatable-read snapshot; this has an O(anchors × documents × 1024) comparison cost and needs a measured scale gate before ANN or larger corpora. Snapshot reads occur in one PostgreSQL REPEATABLE READ transaction under RLS. Provider/network calls occur only after that transaction closes. Use `entity-document/v1` for stored document embedding input and persist that version with embedding metadata; do not aggregate anchors into one query. The write transaction must recheck authenticated ownership, target version existence, and reviewed/published target status before persisting a result.

A faithful M3 prerequisite mapping cannot be computed from `learner_objective_state.understanding_estimate` or `support_required`: the frozen M3 rule explicitly forbids numeric evidence from deciding the hard prerequisite state. #60 must provide a categorical objective projection using the LLD vocabulary (including `UNDERSTOOD` and `RETAINED`) and no arbitrary numeric threshold. Until a matching categorical state exists, the prerequisite is `UNKNOWN` and a HARD requirement excludes with `INSUFFICIENT_STATE`. #61 must add an explicit objective reference and version policy for REQUIRES edges; the existing entity-level `ontology_edges` row lacks both. Any schema change must be a new reviewed migration, never an edit to M1 migrations.

## 5. Persisted recommendation mapping

| Production field | M3 source or production-only meaning |
|---|---|
| `user_id` | Authenticated principal, enforced by RLS and explicit ownership predicates. |
| `entity_id`, `entity_version` or `challenge_id` | Exactly one versioned production target; M3 candidates themselves target entities only. |
| `mode`, `distance_band` | `mode` copies the request. `distance_band` uses the owner-reviewed `distance-band/v1` policy below; neither changes M3 ranking. |
| `ranking_model_version` | Immutable identity of the reviewed ranking/configuration profile, tied to M3 contract lineage. |
| `score_components` | Bounded selected-result scoring provenance, excluding raw learner snapshots and vectors. |
| `reason_code` | First applicable M3 explanation code in canonical order, or NULL if there are no codes. Migration `0016_recommendation_reason` permits the zero-code case. |
| `presentation_version`, `presentation` | `recommendation-copy/v1` static hook/reason for the primary code, plus all machine explanation codes and bounded ranked-versus-shown provenance. Zero codes yield null hook/reason, with no generic fallback. |
| `presented_at` | Time the persisted recommendation is delivered. |
| `decision`, `decided_at` | Optional ACCEPT or SKIP and its time; no other recommendation lifecycle states are frozen. |

The row has no generation-run identity, expiry, viewed state, full candidate set, or full score/rerank trace. The nullable `reason_code` change permits zero explanation codes without the forbidden generic fallback. The service must not assume that `SimulationResult` can be serialized into this row or returned to clients.

The versioned [`distance-band/v1`](../../backend/app/recommendation/profiles/distance-band-v1.json) mapping uses the closest applicable signal. HISTORY_CONTINUATION, REVISIT, or EXPLICIT_INTEREST gives COMFORT; one GRAPH hop or cosine ≥0.80 gives ADJACENT; two GRAPH hops or cosine in [0.65, 0.80) gives FRONTIER; cosine in [0.55, 0.65) gives WILD. Precedence is COMFORT, ADJACENT, FRONTIER, WILD. If no signal qualifies, use ADJACENT. The band represents curiosity/retrieval distance only and never uses readiness, difficulty fit, score, or final rank. Thresholds are initial and uncalibrated. No band value affects M3 ranking.

## 6. Client boundary

The frozen `Recommendation` DTO exposes ID, target type and summary, mode, distance band, hook, reason, and presentation time. It does not expose `SimulationResult`, raw scores, feature weights, candidate-source paths, exclusion reasons, or invariant reports. The request accepts the documented mode, available minutes, and practical context; no client-supplied learner state, anchors, weights, or config version are accepted.

The API is online-first with idempotent mobile outbox replay. No offline recommendation cache or expiration contract is frozen. All machine explanation codes are retained in compact private presentation provenance, in M3 canonical order. The owner-reviewed templates live in [`recommendation-copy-v1.json`](../../backend/app/recommendation/profiles/recommendation-copy-v1.json). The first applicable code is primary and alone selects the `recommendation-copy/v1` static hook/reason template. With zero codes, hook and reason are null. No LLM, fallback reason, runtime rationale recomputation, or ranking change occurs. Localization may add versioned templates later; client exposure of machine codes requires an API revision.

## 7. Security and observability

All request-path reads and writes use `app_backend`, transaction-local `app.user_id`, forced RLS, and explicit target ownership checks. `app_worker` is not part of this synchronous path; its BYPASSRLS privilege must never be treated as an ownership check. Experience Ledger entries carry references and bounded metadata, not copied private learner content.

Bounded operational telemetry may include request ID, configuration version, candidate and eligible counts, exclusions by reason, selected source mix, latency, and failure category. Do not log raw learner state, vectors, full candidate paths, or the entire M3 metrics object by default.

## 8. Contract verification

M4-1 adds narrow assertions for the owner-reviewed profile and copy, and the production request/response shapes against the existing API and recommendation row. Later issues own mapper, retrieval, ranking-adapter, persistence, endpoint, and end-to-end tests. The full M3 harness runs only after a frozen semantic/shared-simulator change or at the final milestone regression gate.

## 9. Implementation responsibilities and limits

#60–#64 implement the snapshot, retrieval adapter, M3 scoring bridge, compact persistence, and API commands. #65 adds the targeted flow gate; its disposable-database execution remains pending in the current environment. #66 records the implementation architecture and limits in the architecture documentation. The domain selection policy for difficulty fit uses the primary domain with challenge state, then the lexicographically first matching domain.

The initial retrieval thresholds and ranking weights are not quality-calibrated; no scale benchmark was run. Migrations `0014`–`0016` implement the categorical objective projection, versioned REQUIRES and embedding identity, and nullable reason. They remain subject to disposable-database verification before production use. No simulator fixture default fills a production gap. A change to M3 semantics requires an explicit M3 contract revision with evidence.
