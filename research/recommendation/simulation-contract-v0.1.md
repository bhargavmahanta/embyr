# Recommendation Simulation Contract v0.1 (M3)

## Status

Frozen for M3. This document freezes the deterministic, explainable contract and
evaluation rubric that M3 recommendation-simulation work builds against. It is a
simulation-only contract and does not describe, extend, or modify production
recommendation persistence.

`contract_version = "m3-simulation/v2"`

Changes to this contract after Issue #44 require evidence from implementation,
security, performance, cost, or product constraints.

## 1. Purpose and Authority

M3 (#43) must be able to evaluate Embyr's recommendation architecture before any
recommendation reaches a production client. To do that without renegotiating
semantics per issue, this document freezes:

- the simulation pipeline and its stage boundaries;
- the versioned input, candidate, trace, and output contracts;
- prerequisite/readiness and explicit-preference semantics;
- hard invariants (machine-checkable) and descriptive metrics (informational);
- the scenario categories that future fixtures must cover;
- the production-persistence boundary and the limits of what M3 proves.

Authority order when documents appear to conflict:

1. [`docs/api/api-contracts-v0.1.md`](../../docs/api/api-contracts-v0.1.md) for
   externally visible semantics and frozen enums.
2. This document for M3 simulation semantics.
3. [`docs/architecture/core-data-model-lld-v0.1.md`](../../docs/architecture/core-data-model-lld-v0.1.md)
   for conceptual data boundaries not overridden above.
4. Repository ADRs and `CONTRIBUTING.md`.

This contract reuses, rather than redefines, existing frozen vocabulary:
`ExplicitInterestPreference` (`NEUTRAL | MORE | LESS | PAUSED | NOT_INTERESTED`),
prerequisite relationship strength `HARD`, objective-relative prerequisite
evaluation, and the invariant "explicit user preference overrides inference."

## 2. Scope and Non-Goals

In scope for M3-1: freezing semantics, the versioned contract, examples, and
future testability for the simulator.

Explicitly out of scope for this issue:

- runtime candidate generation, scoring, or reranking implementation;
- scenario fixtures or a scenario runner;
- production recommendation API or Android integration;
- database migrations, persistence changes, or hosted Supabase mutation;
- LLM ranking, RL/bandits/GNN, or any external model/network dependency;
- a user-visible curiosity, mastery, or learner-rating score.

Numeric weights, the embedding provider, embedding dimension, and ANN strategy
remain deliberately unfrozen. See §25.

## 3. Frozen Pipeline

The simulation pipeline is fixed and ordered:

```text
candidate generation
        ↓
candidate normalization
        ↓
hard eligibility / prerequisite evaluation
        ↓
feature extraction
        ↓
interpretable scoring
        ↓
diversity reranking
        ↓
final recommendation + decision trace
```

Boundary rules:

- Candidate generation may only nominate candidates. It cannot decide
  eligibility or ordering.
- Candidate normalization merges duplicate targets and provenance (§8). It
  cannot decide eligibility or ordering.
- Hard eligibility/prerequisite evaluation occurs before scoring. Scoring
  operates only on `ELIGIBLE` candidates.
- Reranking only reorders eligible, already-scored candidates. It never creates,
  removes, or makes a candidate eligible.
- Every stage emits deterministic, inspectable data for the final trace.

## 4. Determinism Requirements

The simulator must be deterministic and offline.

- Same `SimulationInput` plus same `simulation_config` produces the same logical
  ordered result.
- Serialization is canonical: object keys sorted ascending, arrays ordered by
  the rules defined in this contract, no locale-dependent formatting.
- `input_fingerprint` is `sha256:<hex>` over the canonical serialization of
  `SimulationInput` **excluding** `execution_metadata`. It is not a function of
  wall-clock time, host, process, or randomness.
- `config_version` identifies the simulation configuration, including weights.
- `execution_metadata` (started/finished timestamps, duration, host, run id) may
  be recorded for operators but is explicitly excluded from equality comparison
  and from the fingerprint.
- Ordering is by `ordering_score` descending, then `deterministic_tiebreak_key`
  ascending (§14).
- Final ranks are unique and contiguous, starting at 1.
- No external model, network, or hosted service may be required to run or
  reproduce a scenario.
- Floating-point values must be serialized deterministically; the contract does
  not require a specific numeric precision beyond reproducibility across runs.

Canonical array ordering (frozen) removes every unordered-array ambiguity:

- Arrays of objects are sorted ascending by their stable identity key:
  `entities` by `(entity_id, entity_version)`; `relationships` by
  `(target_entity_id, target_entity_version, relationship_type)`; `vectors` by
  `(entity_id, entity_version)`; `objective_states` by `objective_id`;
  `interest_states` by `(entity_id, entity_version)`;
  `anchor_entities` by `(entity_id, entity_version)`;
  `explorations` by `exploration_id`; `explicit_preferences` by `entity_id`;
  `prerequisite_evaluations` by `(objective_id, prerequisite_entity_id)`;
  `candidates_considered` by `candidate_id`; `ranked_recommendations` by
  `final_rank`; `invariant_results` by `invariant_code`.
- Vocabularies with a frozen enum order are sorted by that enum order:
  `source_paths` and `candidate_sources` by CandidateSource order (§8, §14);
  `explanation_codes` by ExplanationCode order (§15); `exclusion_reasons` by
  ExclusionCode order (§16).
- Unordered identifier arrays (`domain_ids`, `objective_ids`) are sorted
  ascending lexicographically.
- `SemanticVector.vector` preserves dimension order; it is an ordered tuple, not
  a sortable set.
- Equivalent snapshots must serialize to identical canonical bytes and therefore
  the same `input_fingerprint`.

## 5. SimulationInput

`SimulationInput` is versioned. It uses synthetic, stable learner identity and
must never require real Auth users or hosted identifiers.

```text
SimulationInput
- contract_version            string        # "m3-simulation/v2"
- scenario_id                 string
- learner                     LearnerRef
- ontology_snapshot           OntologySnapshot
- generation_context          CandidateGenerationContext
- learner_state_snapshot      LearnerStateSnapshot
- preference_snapshot         PreferenceSnapshot
- exploration_history         ExplorationHistory
- semantic_space              SemanticSpace
- simulation_config           SimulationConfig
```

```text
LearnerRef
- learner_id                  string        # synthetic, stable
- synthetic                   boolean       # MUST be true in M3
```

```text
SimulationConfig
- config_version              string
- top_k                       integer       # final recommendation count target
- feature_weights             map<string, number>   # optional; simulation-only
- rerank                      RerankConfig          # optional; algorithm-neutral
- unknown_prerequisite_policy string                # MUST be "CONSERVATIVE_INELIGIBLE"
```

`feature_weights` values are simulation configuration. They are never learner
truth and are never presented as a learner attribute.

```text
CandidateGenerationContext
- anchor_entities             EntityRef[]

EntityRef
- entity_id                   string
- entity_version              integer
```

`generation_context` is simulation query context. It declares the anchor
entities that GRAPH and SEMANTIC candidate generation start from. It is
**required** in `m3-simulation/v2`; `anchor_entities` is required and `[]` is
valid. Anchors are unique by `(entity_id, entity_version)`, must resolve in
`ontology_snapshot`, and are canonically sorted by `(entity_id, entity_version)`
(§4).

Anchors are query-context declarations, not learner facts. An implementation
MUST NOT derive anchors implicitly from `objective_states`, `interest_states`,
`explicit_preferences`, or `exploration_history`. An entity MAY appear both as
an anchor and in one of those learner-state domains; those are two explicit
facts in separate domains and neither implies the other.

```text
LearnerStateSnapshot
- snapshot_version            string
- objective_states            ObjectiveStateSnapshot[]
- challenge_state             ChallengeStateSnapshot|null
- interest_states             LearnerInterestStateSnapshot[]

ObjectiveStateSnapshot
- objective_id                string
- entity_id                   string
- state                       string        # derived objective/entity state vocabulary
- understanding_estimate      number|null   # optional, synthetic

ChallengeStateSnapshot
- area_id                     string
- ability_estimate            number

LearnerInterestStateSnapshot
- entity_id                   string
- entity_version              integer
- recent_affinity             number
- long_term_affinity          number
- user_initiated_strength     number
- algorithm_exposure_strength number
- voluntary_revisit_count     integer
- last_interaction_at         string|null
- computed_at                 string
- model_version               string
```

```text
PreferenceSnapshot
- snapshot_version            string
- explicit_preferences        ExplicitPreferenceEntry[]

ExplicitPreferenceEntry
- entity_id                   string
- preference                  string        # NEUTRAL|MORE|LESS|PAUSED|NOT_INTERESTED
- version                     integer
```

```text
ExplorationHistory
- snapshot_version            string
- explorations                ExplorationRecord[]

ExplorationRecord
- exploration_id              string
- entity_id                   string
- entity_version              integer
- learning_intent             string
- status                      string        # ACTIVE|PAUSED|COMPLETED
- started_at                  string|null
- returned_at                 string|null
- completed_at                string|null
- paused_at                   string|null
```

```text
RerankConfig
- strategy                    string        # named deterministic strategy; MMR not required
- parameters                  map<string, number>   # optional; simulation-only
- top_k                       integer|null
```

These referenced types are frozen for M3. Their fields are required unless
marked optional, their enum values reuse the frozen API and LLD vocabularies,
and their arrays follow the canonical ordering in §4. `RerankConfig.strategy`
names a deterministic strategy; it does not freeze MMR or any specific
algorithm.

`LearnerStateSnapshot.interest_states` is the simulation analogue of the LLD §27
`learner_interest_state` domain: derived/inferred learner-interest state. It
stays distinct from `PreferenceSnapshot.explicit_preferences` (explicit user
intent), from `LearnerStateSnapshot.objective_states` (understanding/readiness),
and from `LearnerStateSnapshot.challenge_state` (ability context). Field names
follow the LLD domain; `entity_version` is added because simulation entities are
versioned and the canonical identity key is `(entity_id, entity_version)`. An
input with no inferred-interest state uses `interest_states: []`. The field is
required in `m3-simulation/v2`: a producer MUST emit it, and a validator MUST
reject an input that omits it. Omission carries no separate meaning; it is a
validation error, not an implicit `[]`.

## 6. Ontology Snapshot and Semantic Space

The ontology snapshot must be compatible with existing concepts. Each entry is
versioned and deterministic.

```text
OntologySnapshot
- snapshot_version            string
- entities                    EntitySnapshot[]

EntitySnapshot
- entity_id                   string
- entity_version              integer
- entity_type                 string        # DOMAIN|AREA|TOPIC|CONCEPT|SKILL|TECHNIQUE|JOURNEY
- title                       string
- domain_ids                  string[]
- relationships               RelationshipSnapshot[]
- objective_ids               string[]
- difficulty_prior            number
- estimated_effort_minutes    integer

RelationshipSnapshot
- relationship_type           string        # REQUIRES|BUILDS_ON|PART_OF|RELATED_TO|...
- target_entity_id            string
- target_entity_version       integer
- requirement                 string|null   # HARD|SOFT; required for REQUIRES, null otherwise
- objective_id                string|null   # required for REQUIRES, null otherwise
```

For a `REQUIRES` relationship, `objective_id` is REQUIRED and `requirement` is
REQUIRED. For every other relationship type, `objective_id` MUST be null and
`requirement` MUST be null. `objective_id` identifies the learner objective
whose state is used to evaluate that prerequisite entity (§7).

Prerequisite relationships are evaluated against the target learning objective,
not treated as universal laws.

```text
SemanticSpace
- snapshot_version            string
- embedding_model             string        # deterministic fixture identity only
- vector_dimension            integer       # fixture-declared; NOT contract-frozen
- vectors                     SemanticVector[]

SemanticVector
- entity_id                   string
- entity_version              integer
- vector                      number[]      # fixed, deterministic
```

The contract freezes neither the production embedding provider nor the
dimension. `embedding_model` above names the fixture used by a scenario.

## 7. Prerequisite / Readiness Contract

Readiness is **derived and objective-relative**. There is no persisted
`learner.readiness_score`, and M3 does not introduce one.

```text
PrerequisiteEvaluation
- objective_id                string
- prerequisite_entity_id      string
- requirement                 string        # HARD|SOFT
- evidence_summary            object        # bounded, inspectable, synthetic
- state                       string        # SATISFIED|UNSATISFIED|UNKNOWN
- reason_codes                string[]
```

Prerequisite state vocabulary (minimum for M3):

```text
SATISFIED
UNSATISFIED
UNKNOWN
```

Eligibility is a separate concept:

```text
EligibilityState
- ELIGIBLE
- INELIGIBLE
```

`CONDITIONAL` is deliberately not part of the M3 vocabulary.

Hard prerequisite behavior (frozen):

```text
HARD + SATISFIED     → does not exclude; contributes to readiness feature
HARD + UNSATISFIED   → INELIGIBLE, exclusion reason PREREQUISITE_UNMET
HARD + UNKNOWN       → INELIGIBLE, exclusion reason INSUFFICIENT_STATE
```

UNKNOWN is not conflated with known-unmet evidence: `UNKNOWN` preserves the
absence of deciding evidence in the trace, while `INSUFFICIENT_STATE` records
why no recommendation was produced. `unknown_prerequisite_policy` is frozen to
the conservative behavior above.

Soft prerequisite behavior (frozen):

```text
SOFT + UNSATISFIED / UNKNOWN → does NOT exclude; may inform the readiness feature
```

Hard-filter vs soft-feature distinction:

- The **hard filter** is prerequisite/eligibility evaluation, applied before
  scoring. It can only set `INELIGIBLE` and an exclusion reason.
- A **soft feature** is a scoring input (for example `readiness`). No score,
  weight, or diversity rule may move an `INELIGIBLE` candidate into the final
  recommendation set.

A `PrerequisiteEvaluation` is emitted only when a prerequisite actually exists.
An empty `prerequisite_evaluations` list means no prerequisite evaluations were
required for that candidate. Absence of prerequisites is always represented by
the empty list, never by a placeholder entry with a null prerequisite.

Objective-relative lookup (frozen):

- A `REQUIRES` relationship carries an explicit `objective_id` (§6). The
  prerequisite state is derived from the learner's objective state matched by
  **both** `objective_id` AND the prerequisite entity identity
  (`entity_id`, `entity_version`); it is never inferred from arbitrary
  objective-state rows.
- `PrerequisiteEvaluation.objective_id` copies the `REQUIRES` edge's
  `objective_id`.
- If no matching learner objective state exists → `UNKNOWN`.
- If the input contains duplicate/ambiguous learner objective state for the same
  logical `(objective_id, prerequisite entity identity)` → the input FAILS
  validation.

Readiness state mapping (frozen, no numeric threshold):

```text
objective state UNDERSTOOD      → SATISFIED
objective state RETAINED        → SATISFIED
no matching objective state     → UNKNOWN
all other frozen objective states → UNSATISFIED
```

`understanding_estimate`, `evaluation_confidence`, `support_required`, and any
other numeric evidence MAY be retained inside `evidence_summary` for
inspectability, but they MUST NOT determine the M3 hard prerequisite state.

## 8. Candidate Contract

A normalized candidate represents one target entity. Normalization is
deterministic and merges duplicate targets nominated by multiple sources.

```text
Candidate
- candidate_id                string        # derived deterministically from target identity
- target_entity_id            string
- target_entity_version       integer
- target_entity_type          string|null   # non-null iff target resolves; null iff unresolved (INVALID_TARGET)
- source_paths                SourcePath[] # merged, deterministically ordered
- prerequisite_evaluations    PrerequisiteEvaluation[]
- eligibility_state           string        # ELIGIBLE|INELIGIBLE
- exclusion_reasons           string[]      # reason codes; empty when ELIGIBLE
- feature_inputs              object        # raw inputs for feature extraction

SourcePath
- source                     string        # CandidateSource
- provenance                 object        # inspectable, synthetic
```

Candidate source vocabulary:

```text
GRAPH
SEMANTIC
EXPLICIT_INTEREST
HISTORY_CONTINUATION
REVISIT
```

Normalization rules (frozen):

- All source paths for the same `(target_entity_id, target_entity_version)` merge
  into exactly one `Candidate`; `source_paths` is deduplicated and sorted by
  `(source enum order, canonical provenance)`.
- `candidate_id` is derived deterministically and opaquely from
  `(target_entity_id, target_entity_version)` only; `target_entity_type` is
  metadata and is NOT part of logical identity. The textual encoding is not
  frozen; consumers MUST NOT depend on its exact form.
- Normalization never emits two candidates for the same final target, and never
  changes eligibility.
- `exclusion_reasons` is deterministically ordered and carries one code per
  contract-required exclusion.

### 8.1 Candidate source nomination rules

Nomination is not eligibility and is not ranking value. A nominated candidate is
still subject to hard eligibility evaluation (§7) and may be excluded.

- `GRAPH` and `SEMANTIC` MUST NOT nominate an anchor entity itself. An anchor
  MAY still become a candidate through `EXPLICIT_INTEREST`, `REVISIT`, or
  another legitimate source.
- `RELATED_TO` is candidate-generating (GRAPH). `REQUIRES` is readiness-only and
  never nominates a candidate. `PART_OF` and `BUILDS_ON` are non-nominating in
  M3. No other production ontology relationship type is assigned recommendation
  semantics in M3.
- `EXPLICIT_INTEREST` nominates entries whose preference is `MORE`, `LESS`,
  `PAUSED`, or `NOT_INTERESTED`. `NEUTRAL` does not nominate. `PAUSED` and
  `NOT_INTERESTED` are generated first and then filtered, so the exclusion trace
  retains a real nomination source.
- `HISTORY_CONTINUATION` nominates non-anchor entities reachable by a
  `RELATED_TO` relationship from the target of an `ACTIVE` exploration.
- `REVISIT` nominates the target of a `COMPLETED` exploration.
- A `PAUSED` exploration nominates neither `HISTORY_CONTINUATION` nor `REVISIT`
  in M3.

### 8.2 History continuation and revisit

A `COMPLETED` exploration is sufficient on its own to nominate the same target
via `REVISIT`; M3 imposes no retention-decay requirement and `SimulationInput`
carries no retention state. `HISTORY_CONTINUATION` nominates next entities
related to an `ACTIVE` exploration rather than the exploration target itself.
The contract does not freeze a universal revisit-vs-exploration ranking rule
(§13); nomination and ranking value remain separate.

### 8.3 Unresolved target representation

`Candidate.target_entity_type` is a required but nullable field. It is the only
Candidate field whose nullability is conditional.

- A target that resolves in `ontology_snapshot.entities` MUST have a non-null
  `target_entity_type` equal to that entity's frozen `entity_type`
  (`DOMAIN|AREA|TOPIC|CONCEPT|SKILL|TECHNIQUE|JOURNEY`). `null` is invalid output
  for a resolved target.
- A structurally valid source reference whose `(target_entity_id, target_entity_version)` does NOT resolve in `ontology_snapshot.entities` MUST
  emit a Candidate with `target_entity_type = null`, `eligibility_state =
  INELIGIBLE`, and `exclusion_reasons` including `INVALID_TARGET`.
- This is the ONLY situation in which `target_entity_type` may be null. No
  `UNKNOWN`, `INVALID`, `MISSING`, `UNRESOLVED`, or other sentinel entity type is
  permitted.
- An unresolved target has no ontology `EntitySnapshot`, so its
  `prerequisite_evaluations` MUST be empty (`[]`). Prerequisite reasons
  (`PREREQUISITE_UNMET`, `INSUFFICIENT_STATE`) are not emitted merely because
  ontology metadata is absent; `INVALID_TARGET` describes that failure.
- Collect-all exclusions still apply where directly knowable from an independent
  source. For example, an unresolved target that also carries an explicit
  `NOT_INTERESTED` preference yields `exclusion_reasons` containing both
  `NOT_INTERESTED` and `INVALID_TARGET`, serialized in frozen enum order.
- Structural invalid input (missing required fields, invalid enum, malformed
  shape, duplicate canonical keys where forbidden) still FAILS input validation;
  it is never converted into an `INVALID_TARGET` candidate.
- Target identity, deduplication, and `candidate_id` derivation are unchanged:
  the logical key remains `(target_entity_id, target_entity_version)`, and
  `target_entity_type` is not part of either.

## 9. Semantic Candidate Rule

Semantic similarity has exactly two distinct roles and they must not be
conflated:

1. It may **nominate** a candidate (`CandidateSource.SEMANTIC`).
2. It may contribute a `semantic_similarity` **feature** to scoring.

Nomination does not imply eligibility, ordering, or admission to the final set.
The contract freezes neither an embedding provider, a vector dimension, nor an
ANN strategy.

### 9.1 Semantic anchor retrieval

For each anchor in `generation_context.anchor_entities` that has a semantic
vector:

- compare it to **every other** ontology entity that has a valid vector
  (exhaustive, deterministic comparison);
- exclude the anchor itself (an anchor is never nominated by its own semantic
  retrieval).

M3 applies **no threshold, no top-K, no ANN, and no randomness**. If no anchor
has a semantic vector, SEMANTIC emits no nominations.

Semantic provenance MUST include `anchor_entity_id`, `anchor_entity_version`,
and `cosine_similarity`. The raw cosine value is provenance and a raw input for
later feature extraction; it is NOT a #46 score. Missing vectors simply do not
participate; a mismatched vector dimension is an input validation failure.
Production retrieval limits (provider, dimension, ANN, thresholds, top-K)
remain deliberately unfrozen.

### 9.2 Graph anchor traversal

For each anchor in `generation_context.anchor_entities`:

- traverse `RELATED_TO` edges only, treating adjacency deterministically;
- discover every reachable non-anchor entity (exhaustive connected traversal,
  no artificial maximum depth in M3);
- retain the shortest hop distance;
- if multiple shortest paths exist, choose one canonical path by the
  lexicographically smallest ordered sequence of `(entity_id, entity_version)`.

Graph provenance MUST contain `anchor_entity_id`, `anchor_entity_version`,
`hop_distance`, and `canonical_path`. `canonical_path` is an ordered
`EntityRef[]` from the anchor, through intermediate nodes, to the target; it
includes the anchor and the target, and
`hop_distance == len(canonical_path) - 1`. An anchor is never emitted as a GRAPH
candidate through its own traversal.

This path is simulation provenance/traceability only. It is NOT a production
persistence schema, NOT a ranking feature by itself, and NOT a production
graph-traversal contract; production traversal bounds remain unfrozen.

## 10. Explicit Preference Contract

Explicit preference is represented independently from inferred interest and is
never collapsed into one opaque score input. The frozen vocabulary reuses the
API contract:

```text
NEUTRAL
MORE
LESS
PAUSED
NOT_INTERESTED
```

Frozen semantics:

```text
MORE           explicit positive ranking signal; wins over conflicting inferred negative
LESS           explicit soft-negative ranking signal, NOT exclusion; wins over conflicting inferred positive
NEUTRAL        no explicit adjustment; inferred signals may still contribute
PAUSED         hard, entity-scoped exclusion while paused
NOT_INTERESTED hard, entity-scoped exclusion for that entity
(absent)       inferred signals operate normally
```

Precedence rule (frozen): **explicit preference overrides inferred preference
when they conflict.** This is not a blanket rule that any explicit preference
suppresses all inferred signals.

- When explicit and inferred agree, both may contribute; there is no conflict to
  resolve.
- When explicit and inferred conflict, the explicit signal determines the
  effective `explicit_interest` / `inferred_interest` contribution and the
  conflict is recorded in the trace (see `EXPLICIT_PREFERENCE_OVERRIDES_INFERRED`
  in §15 and `ScoreTrace.reason_codes`).
- `PAUSED` and `NOT_INTERESTED` exclude regardless of inference; inference can
  never lift a hard exclusion.
- Negative explicit preference is entity-scoped. The contract does not suppress
  an entire domain, ancestor, or descendant tree from an entity-level preference
  unless a future contract explicitly defines that broader scope.

The trace exposes `explicit_interest` and `inferred_interest` separately
wherever both apply.

Candidate nomination (frozen): `MORE`, `LESS`, `PAUSED`, and `NOT_INTERESTED`
nominate an `EXPLICIT_INTEREST` candidate; `NEUTRAL` does not. `PAUSED` and
`NOT_INTERESTED` are generated and then hard-excluded, so their exclusion trace
retains a real nomination source. A positive explicit preference never bypasses a
hard readiness constraint (§8.1).

## 11. Feature and Scoring Trace

Scoring is interpretable and operates only on eligible candidates. Features are
named and inspectable.

Feature vocabulary (a candidate need not have every feature):

```text
readiness
difficulty_fit
explicit_interest
inferred_interest
graph_proximity
semantic_similarity
continuation_value
revisit_value
novelty
diversity_context
```

```text
ScoreTrace
- feature_values              map<string, number>   # computed, inspectable
- configured_weights          map<string, number>   # simulation config; omit if unweighted
- component_scores            map<string, number>   # named contributions
- pre_rerank_score            number
- reason_codes                string[]              # trace-level, machine-readable
```

Frozen bounds:

- Weights remain simulation configuration and are never learner truth.
- The contract does not freeze arbitrary numeric production weights.
- The contract does not expose a universal curiosity/mastery score, and the
  ordering score is internal only (§14).

## 12. Difficulty-Fit Representation

`difficulty_fit` is a named, interpretable feature, not a learner attribute.

- It relates the target's `difficulty_prior` to the learner's derived challenge
  state for the relevant area/domain.
- Higher values mean a better fit; both too-low and too-high relative difficulty
  reduce the contribution.
- The exact numeric mapping and any weights are simulation configuration and are
  unfrozen here.
- Scenarios must be able to exercise "too low", "appropriate", and "too high"
  difficulty fit (§21, categories I, J, K).

## 13. Diversity / Rerank Contract

Reranking is algorithm-neutral. MMR is not required.

- Diversity may move a slightly lower-scoring eligible candidate above a
  redundant higher-scoring eligible candidate.
- Diversity must never override eligibility or prerequisite hard constraints.
- Reranking only reorders eligible, scored candidates.

```text
RerankTrace
- pre_rerank_rank             integer
- pre_rerank_score            number
- diversity_dimensions        object        # e.g. topic/domain/source spread
- diversity_adjustment        number
- post_rerank_rank            integer
- reason_codes                string[]
```

Tie-breaking is deterministic. The output schema must accommodate a future
MMR-like or category-spread implementation without change. Revisit and new
exploration are named signals (`revisit_value`, `continuation_value`); the
contract does not freeze a universal revisit-wins rule.

## 14. Final Recommendation Contract

```text
RecommendationResult
- target_entity_id            string
- target_entity_version       integer
- final_rank                  integer       # unique, contiguous, from 1
- ordering_score              number        # internal only
- candidate_sources           string[]      # CandidateSource values, sorted
- readiness_summary           object
- score_trace                 ScoreTrace
- rerank_trace                RerankTrace
- explanation_codes           string[]
- deterministic_tiebreak_key  string
```

Frozen rules:

- `ordering_score` is internal. It is not a curiosity score, mastery score, or
  learner rating, and it is never exposed as a user-visible learner attribute.
- `deterministic_tiebreak_key` is the canonical string
  `"{target_entity_type}:{target_entity_id}:{target_entity_version}"`.
- Ordering: `ordering_score` descending, then `deterministic_tiebreak_key`
  ascending.
- An empty final recommendation set is a valid result (§19, invariant IN-10).

Trace score definitions (frozen normalized representation):

```text
pre_rerank_score       score before diversity reranking
diversity_adjustment   signed scalar delta applied by the reranking trace representation
ordering_score         pre_rerank_score + diversity_adjustment
```

This is a normalized trace representation, not a requirement that the internal
reranking algorithm itself be additive. A reranker may use MMR-like,
category-spread, or another deterministic method; its final scalar ordering
effect is normalized as `diversity_adjustment = ordering_score -
pre_rerank_score`, preserving algorithm-neutrality while keeping the trace
arithmetically self-consistent.

## 15. Explanation Contract

Explanations are machine-readable codes. Codes justified by this contract:

```text
EXPLICIT_INTEREST_MATCH
RELATED_TO_RECENT_EXPLORATION
PREREQUISITES_SATISFIED
GOOD_DIFFICULTY_FIT
SEMANTICALLY_RELATED
REVISIT_OPPORTUNITY
DIVERSITY_ADJUSTMENT
EXPLICIT_PREFERENCE_OVERRIDES_INFERRED   # justified by §10 precedence
```

- Canonical explanations are machine-readable codes.
- Human-readable rendering is optional and, if present, must be deterministic and
  template-based. No LLM is required.
- No psychological, personality, or identity inference is permitted.
- Every final recommendation must carry at least one explanation code.

## 16. Exclusion Contract

```text
PREREQUISITE_UNMET      an UNSATISFIED hard prerequisite (known-unmet evidence)
EXPLICITLY_PAUSED       explicit PAUSED preference for the entity
NOT_INTERESTED          explicit NOT_INTERESTED preference for the entity
INVALID_TARGET          malformed, missing, or unresolvable target
INSUFFICIENT_STATE      a contract-required decision lacks deciding evidence
                        (includes an UNKNOWN hard prerequisite)
```

- Every contract-required exclusion must carry a reason code; an `INELIGIBLE`
  candidate has at least one.
- `INSUFFICIENT_STATE` is not `PREREQUISITE_UNMET`: unknown is not unmet.
- The vocabulary is intentionally minimal and must not be over-expanded.

Invalid-target vs input invalidity (frozen):

- **Structural invalid input FAILS validation.** Examples: missing required
  fields, an invalid enum value, duplicate canonical keys, or a malformed
  required shape.
- A **structurally valid source record whose entity/version is absent from
  `ontology_snapshot`** emits a normalized candidate that is `INELIGIBLE` with
  exclusion reason `INVALID_TARGET` and `target_entity_type = null` (§8.3).
- Eligibility evaluation **collects all applicable exclusion reasons** and does
  not short-circuit; `exclusion_reasons` is serialized in the frozen enum order
  (§4).

## 17. Simulation Output Contract

```text
SimulationResult
- contract_version            string
- scenario_id                 string
- config_version              string
- input_fingerprint           string        # "sha256:<hex>"
- candidates_considered       Candidate[]
- candidates_excluded         Candidate[]    # INELIGIBLE, with exclusion_reasons
- ranked_recommendations      RecommendationResult[]
- invariant_results           InvariantResult[]
- metrics                     object         # descriptive only (§20)
- execution_metadata          object         # excluded from equality/fingerprint

InvariantResult
- invariant_code              string        # IN-1..IN-10
- status                      string        # PASS|FAIL
- diagnostics                 object
```

- `invariant_results` is deterministic and independent of wall-clock time.
- `metrics` never carries pass/fail thresholds.
- Wall-clock timestamps may exist only inside `execution_metadata` and are
  excluded from deterministic comparison.
- `candidates_considered` is every normalized candidate the simulator evaluated,
  including both `ELIGIBLE` and `INELIGIBLE` candidates.
- `candidates_excluded` is the `INELIGIBLE` subset of `candidates_considered`.
  Every excluded candidate also appears in `candidates_considered`; it is a
  diagnostic subset, not a disjoint collection.

## 18. Production Persistence Boundary

The simulation trace carries strictly more detail than the production
recommendation row, but it is **not** a field-for-field strict superset of
production recommendation persistence. Production-only presentation and
lifecycle fields (`mode`, `distance_band`, `ranking_model_version`,
`presentation`, `presented_at`, `decision`) are not simulation concepts, and
simulation-only fields are not persisted. The trace is **not** a new production
schema.

Production recommendations persist:

```text
target (entity_id/entity_version or challenge_id)
mode
distance_band
ranking_model_version
score_components
reason_code
presentation
presented_at
decision
```

Simulation-only fields, which must never be read as a request to migrate:

```text
candidate set
candidate_source provenance (multiple source paths)
exclusion reasons
feature trace
rerank trace
final rank
invariant results
simulation metrics
simulation config and weights
fixed semantic fixture vectors
```

M3-1 adds no migration and changes no persistence schema.

## 19. Hard Invariants

Machine-readable, reported as `PASS` or `FAIL` with diagnostics.

```text
IN-1   same input + config produces the same logical ordered result
IN-2   no INELIGIBLE candidate appears in final recommendations
IN-3   unmet hard prerequisites are never bypassed by score
IN-4   explicit preference override behavior is deterministic
IN-5   every final recommendation has a complete decision trace
IN-6   every contract-required exclusion has a reason code
IN-7   final ranks are unique and contiguous/ordered
IN-8   candidate normalization does not emit duplicate final targets
IN-9   no external model/network dependency is required
IN-10  an empty recommendation set is valid when no candidate is eligible
```

## 20. Descriptive Metrics

Metrics are informational. They are kept separate from hard invariants and are
never assigned arbitrary pass/fail thresholds.

```text
candidate_count
eligible_candidate_count
exclusion_count_by_reason
source_coverage
top_k_source_mix
topic_domain_diversity
difficulty_distribution
explicit_interest_coverage
semantic_candidate_coverage
revisit_share
continuation_share
rank_change_due_to_diversity
trace_completeness
```

Deliberately excluded for M3-1, because no defensible relevance labels exist
yet: `NDCG`, `MAP`, `Recall@K`, `Precision@K`.

## 21. Scenario Categories

Scenario intent, exercised dimensions, and expected invariant behavior are
frozen. Fixtures are **not** built in this issue; they are implemented by #45.

| ID | Category | Intent | Exercised dimensions | Expected invariant behavior |
|----|----------|--------|----------------------|-----------------------------|
| A | Explicit MORE | positive explicit preference | explicit_interest, inferred_interest | IN-1, IN-4, IN-5; eligible and ranked |
| B | Explicit LESS | soft negative preference | explicit_interest, inferred_interest | IN-1, IN-4; remains eligible, not excluded |
| C | Explicit PAUSED | hard entity-scoped exclusion | eligibility, exclusions | IN-2, IN-6; INELIGIBLE with EXPLICITLY_PAUSED |
| D | Explicit NOT_INTERESTED | hard entity-scoped exclusion | eligibility, exclusions | IN-2, IN-6; INELIGIBLE with NOT_INTERESTED |
| E | Explicit vs inferred conflict | precedence | explicit_interest, inferred_interest, trace | IN-1, IN-4, IN-5; explicit wins, both exposed |
| F | Prerequisite unmet | hard filter | prerequisite_evaluations, exclusions | IN-2, IN-3, IN-6; INELIGIBLE with PREREQUISITE_UNMET |
| G | Prerequisite satisfied | hard filter pass | prerequisite_evaluations, readiness | eligible; readiness feature present |
| H | Prerequisite unknown | conservative policy | prerequisite_evaluations, exclusions | IN-2, IN-3, IN-6; INELIGIBLE with INSUFFICIENT_STATE, state UNKNOWN |
| I | Difficulty too low | difficulty fit | difficulty_fit | IN-1, IN-5; eligible, reduced contribution |
| J | Difficulty appropriate | difficulty fit | difficulty_fit | IN-1, IN-5; eligible, favourable contribution |
| K | Difficulty too high | difficulty fit | difficulty_fit | IN-1, IN-5; eligible, reduced contribution |
| L | Semantic-neighbor candidate | semantic nomination | semantic_similarity, source_paths | IN-1, IN-5, IN-8; eligible with SEMANTIC source |
| M | Graph-neighbor candidate | graph nomination | graph_proximity, source_paths | IN-1, IN-5, IN-8; eligible with GRAPH source |
| N | Continuation candidate | history continuation | continuation_value | IN-1, IN-5; eligible |
| O | Revisit candidate | revisit signal | revisit_value | IN-1, IN-5; eligible |
| P | Diversity pressure | rerank | diversity_context, rerank_trace | IN-1, IN-2; rerank of eligible only |
| Q | Deterministic tie | tie-breaking | ordering_score, tiebreak key | IN-1, IN-7; stable deterministic order |
| R | Duplicate candidate from multiple sources | normalization | source_paths, candidate_id | IN-1, IN-8; one candidate, merged sources |
| S | Sparse learner history | insufficient evidence | eligibility, exclusions, metrics | IN-1, IN-6, IN-10; missing evidence handled deterministically |
| T | No eligible candidate | empty set valid | exclusions, invariants | IN-2, IN-6, IN-10; empty result is PASS |

## 22. What M3 Does Not Prove

M3 simulation does **not** prove:

- production recommendation quality;
- engagement improvement;
- long-term learning outcomes;
- optimal ranking weights;
- embedding-model quality;
- online personalization quality;
- causal impact;
- Android UX quality;
- production latency or scalability;
- real-world relevance calibration.

M3 proves only that the frozen architecture behaves deterministically and
explainably under defined synthetic scenarios.

## 23. Privacy and Safety Boundary

- Explanation traces must not expose hidden learner scores as product concepts
  and must not present an ordering score as a learner attribute.
- Traces must not infer identity, personality, or psychology.
- Sensitive content is referenced, not duplicated, and examples use synthetic
  identifiers only.
- No real user IDs, secrets, or hosted identifiers appear in fixtures or output.
- The contract remains compatible with existing ownership, RLS, and privacy
  architecture; it introduces no new persisted learner data.

## 24. Required Examples

Synthetic examples only. No real user IDs, secrets, or hosted identifiers.
Identifiers below are fixed synthetic UUIDs.

### 24.1 Minimal valid SimulationInput

```json
{
  "contract_version": "m3-simulation/v2",
  "scenario_id": "scn-minimal-001",
  "learner": {
    "learner_id": "10000000-0000-4000-8000-000000000001",
    "synthetic": true
  },
  "ontology_snapshot": {
    "snapshot_version": "onto-001",
    "entities": [
      {
        "entity_id": "20000000-0000-4000-8000-000000000001",
        "entity_version": 1,
        "entity_type": "TOPIC",
        "title": "Linear Equations",
        "domain_ids": ["30000000-0000-4000-8000-000000000001"],
        "relationships": [],
        "objective_ids": ["40000000-0000-4000-8000-000000000001"],
        "difficulty_prior": 0.3,
        "estimated_effort_minutes": 15
      }
    ]
  },
  "generation_context": {
    "anchor_entities": [
      {
        "entity_id": "20000000-0000-4000-8000-000000000001",
        "entity_version": 1
      }
    ]
  },
  "learner_state_snapshot": {
    "snapshot_version": "state-001",
    "objective_states": [
      {
        "objective_id": "40000000-0000-4000-8000-000000000001",
        "entity_id": "20000000-0000-4000-8000-000000000001",
        "state": "EXPLORING"
      }
    ],
    "challenge_state": {
      "area_id": "30000000-0000-4000-8000-000000000001",
      "ability_estimate": 0.35
    },
    "interest_states": []
  },
  "preference_snapshot": {
    "snapshot_version": "prefs-001",
    "explicit_preferences": []
  },
  "exploration_history": {
    "snapshot_version": "hist-001",
    "explorations": []
  },
  "semantic_space": {
    "snapshot_version": "sem-001",
    "embedding_model": "fixture-deterministic-8d",
    "vector_dimension": 8,
    "vectors": [
      {
        "entity_id": "20000000-0000-4000-8000-000000000001",
        "entity_version": 1,
        "vector": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
      }
    ]
  },
  "simulation_config": {
    "config_version": "m3-sim-config/v1",
    "top_k": 5,
    "feature_weights": {},
    "unknown_prerequisite_policy": "CONSERVATIVE_INELIGIBLE"
  }
}
```

### 24.2 Eligible candidate with multiple source paths

```json
{
  "candidate_id": "cand:TOPIC:20000000-0000-4000-8000-000000000001:1",
  "target_entity_id": "20000000-0000-4000-8000-000000000001",
  "target_entity_version": 1,
  "target_entity_type": "TOPIC",
  "source_paths": [
    {"source": "GRAPH", "provenance": {"edge_id": "edge-synthetic-01"}},
    {"source": "SEMANTIC", "provenance": {"similarity": 0.81}}
  ],
  "prerequisite_evaluations": [
    {
      "objective_id": "40000000-0000-4000-8000-000000000001",
      "prerequisite_entity_id": "20000000-0000-4000-8000-000000000002",
      "requirement": "HARD",
      "evidence_summary": {"positive_evidence_count": 2},
      "state": "SATISFIED",
      "reason_codes": ["PREREQUISITE_SATISFIED"]
    }
  ],
  "eligibility_state": "ELIGIBLE",
  "exclusion_reasons": [],
  "feature_inputs": {
    "difficulty_prior": 0.3,
    "graph_distance": 1
  }
}
```

### 24.3 Excluded prerequisite candidates (UNSATISFIED and UNKNOWN)

```json
{
  "candidates": [
    {
      "candidate_id": "cand:TOPIC:20000000-0000-4000-8000-000000000003:1",
      "target_entity_id": "20000000-0000-4000-8000-000000000003",
      "target_entity_version": 1,
      "target_entity_type": "TOPIC",
      "source_paths": [
        {"source": "GRAPH", "provenance": {"edge_id": "edge-synthetic-02"}}
      ],
      "prerequisite_evaluations": [
        {
          "objective_id": "40000000-0000-4000-8000-000000000002",
          "prerequisite_entity_id": "20000000-0000-4000-8000-000000000001",
          "requirement": "HARD",
          "evidence_summary": {"negative_evidence_count": 1},
          "state": "UNSATISFIED",
          "reason_codes": ["PREREQUISITE_UNMET"]
        }
      ],
      "eligibility_state": "INELIGIBLE",
      "exclusion_reasons": ["PREREQUISITE_UNMET"],
      "feature_inputs": {}
    },
    {
      "candidate_id": "cand:TOPIC:20000000-0000-4000-8000-000000000004:1",
      "target_entity_id": "20000000-0000-4000-8000-000000000004",
      "target_entity_version": 1,
      "target_entity_type": "TOPIC",
      "source_paths": [
        {"source": "SEMANTIC", "provenance": {"similarity": 0.77}}
      ],
      "prerequisite_evaluations": [
        {
          "objective_id": "40000000-0000-4000-8000-000000000003",
          "prerequisite_entity_id": "20000000-0000-4000-8000-000000000005",
          "requirement": "HARD",
          "evidence_summary": {"positive_evidence_count": 0, "negative_evidence_count": 0},
          "state": "UNKNOWN",
          "reason_codes": ["NO_DECIDING_EVIDENCE"]
        }
      ],
      "eligibility_state": "INELIGIBLE",
      "exclusion_reasons": ["INSUFFICIENT_STATE"],
      "feature_inputs": {}
    }
  ]
}
```

### 24.4 Explicit NOT_INTERESTED exclusion

```json
{
  "candidate_id": "cand:TOPIC:20000000-0000-4000-8000-000000000006:1",
  "target_entity_id": "20000000-0000-4000-8000-000000000006",
  "target_entity_version": 1,
  "target_entity_type": "TOPIC",
  "source_paths": [
    {"source": "SEMANTIC", "provenance": {"similarity": 0.9}}
  ],
  "prerequisite_evaluations": [],
  "eligibility_state": "INELIGIBLE",
  "exclusion_reasons": ["NOT_INTERESTED"],
  "feature_inputs": {
    "explicit_preference": "NOT_INTERESTED"
  }
}
```

### 24.5 Ranked RecommendationResult

```json
{
  "target_entity_id": "20000000-0000-4000-8000-000000000001",
  "target_entity_version": 1,
  "final_rank": 1,
  "ordering_score": 5.36,
  "candidate_sources": ["GRAPH", "SEMANTIC"],
  "readiness_summary": {
    "hard_prerequisites_total": 1,
    "hard_prerequisites_satisfied": 1,
    "state": "SATISFIED"
  },
  "score_trace": {
    "feature_values": {
      "readiness": 1.0,
      "difficulty_fit": 0.8,
      "explicit_interest": 1.0,
      "inferred_interest": 0.3,
      "graph_proximity": 0.5,
      "semantic_similarity": 0.81,
      "novelty": 0.4,
      "diversity_context": 0.0
    },
    "configured_weights": {
      "readiness": 1.0,
      "difficulty_fit": 1.0,
      "explicit_interest": 2.0,
      "inferred_interest": 1.0,
      "graph_proximity": 0.5,
      "semantic_similarity": 1.0,
      "novelty": 0.5
    },
    "component_scores": {
      "readiness": 1.0,
      "difficulty_fit": 0.8,
      "explicit_interest": 2.0,
      "inferred_interest": 0.3,
      "graph_proximity": 0.25,
      "semantic_similarity": 0.81,
      "novelty": 0.2
    },
    "pre_rerank_score": 5.36,
    "reason_codes": []
  },
  "rerank_trace": {
    "pre_rerank_rank": 1,
    "pre_rerank_score": 5.36,
    "diversity_dimensions": {"primary_domain": "30000000-0000-4000-8000-000000000001"},
    "diversity_adjustment": 0.0,
    "post_rerank_rank": 1,
    "reason_codes": []
  },
  "explanation_codes": [
    "EXPLICIT_INTEREST_MATCH",
    "PREREQUISITES_SATISFIED",
    "GOOD_DIFFICULTY_FIT",
    "SEMANTICALLY_RELATED"
  ],
  "deterministic_tiebreak_key": "TOPIC:20000000-0000-4000-8000-000000000001:1"
}
```

### 24.6 SimulationResult with invariants and metrics

```json
{
  "contract_version": "m3-simulation/v2",
  "scenario_id": "scn-explicit-more-001",
  "config_version": "m3-sim-config/v1",
  "input_fingerprint": "sha256:0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f",
  "candidates_considered": [
    {
      "candidate_id": "cand:TOPIC:20000000-0000-4000-8000-000000000001:1",
      "target_entity_id": "20000000-0000-4000-8000-000000000001",
      "target_entity_version": 1,
      "target_entity_type": "TOPIC",
      "source_paths": [
        {"source": "GRAPH", "provenance": {"edge_id": "edge-synthetic-01"}},
        {"source": "SEMANTIC", "provenance": {"similarity": 0.81}}
      ],
      "prerequisite_evaluations": [
        {
          "objective_id": "40000000-0000-4000-8000-000000000001",
          "prerequisite_entity_id": "20000000-0000-4000-8000-000000000002",
          "requirement": "HARD",
          "evidence_summary": {"positive_evidence_count": 2},
          "state": "SATISFIED",
          "reason_codes": ["PREREQUISITE_SATISFIED"]
        }
      ],
      "eligibility_state": "ELIGIBLE",
      "exclusion_reasons": [],
      "feature_inputs": {
        "difficulty_prior": 0.3,
        "graph_distance": 1
      }
    }
  ],
  "candidates_excluded": [],
  "ranked_recommendations": [
    {
      "target_entity_id": "20000000-0000-4000-8000-000000000001",
      "target_entity_version": 1,
      "final_rank": 1,
      "ordering_score": 5.36,
      "candidate_sources": ["GRAPH", "SEMANTIC"],
      "readiness_summary": {
        "hard_prerequisites_total": 1,
        "hard_prerequisites_satisfied": 1,
        "state": "SATISFIED"
      },
      "score_trace": {
        "feature_values": {
          "readiness": 1.0,
          "difficulty_fit": 0.8,
          "explicit_interest": 1.0,
          "inferred_interest": 0.3,
          "graph_proximity": 0.5,
          "semantic_similarity": 0.81,
          "novelty": 0.4,
          "diversity_context": 0.0
        },
        "configured_weights": {
          "readiness": 1.0,
          "difficulty_fit": 1.0,
          "explicit_interest": 2.0,
          "inferred_interest": 1.0,
          "graph_proximity": 0.5,
          "semantic_similarity": 1.0,
          "novelty": 0.5
        },
        "component_scores": {
          "readiness": 1.0,
          "difficulty_fit": 0.8,
          "explicit_interest": 2.0,
          "inferred_interest": 0.3,
          "graph_proximity": 0.25,
          "semantic_similarity": 0.81,
          "novelty": 0.2
        },
        "pre_rerank_score": 5.36,
        "reason_codes": []
      },
      "rerank_trace": {
        "pre_rerank_rank": 1,
        "pre_rerank_score": 5.36,
        "diversity_dimensions": {"primary_domain": "30000000-0000-4000-8000-000000000001"},
        "diversity_adjustment": 0.0,
        "post_rerank_rank": 1,
        "reason_codes": []
      },
      "explanation_codes": [
        "EXPLICIT_INTEREST_MATCH",
        "PREREQUISITES_SATISFIED",
        "GOOD_DIFFICULTY_FIT",
        "SEMANTICALLY_RELATED"
      ],
      "deterministic_tiebreak_key": "TOPIC:20000000-0000-4000-8000-000000000001:1"
    }
  ],
  "invariant_results": [
    {"invariant_code": "IN-1", "status": "PASS", "diagnostics": {}},
    {"invariant_code": "IN-2", "status": "PASS", "diagnostics": {"checked": 1}},
    {"invariant_code": "IN-3", "status": "PASS", "diagnostics": {}},
    {"invariant_code": "IN-4", "status": "PASS", "diagnostics": {}},
    {"invariant_code": "IN-5", "status": "PASS", "diagnostics": {"traces_incomplete": 0}},
    {"invariant_code": "IN-6", "status": "PASS", "diagnostics": {"exclusions_without_reason": 0}},
    {"invariant_code": "IN-7", "status": "PASS", "diagnostics": {"ranks": [1]}},
    {"invariant_code": "IN-8", "status": "PASS", "diagnostics": {"duplicate_targets": 0}},
    {"invariant_code": "IN-9", "status": "PASS", "diagnostics": {"external_calls": 0}},
    {"invariant_code": "IN-10", "status": "PASS", "diagnostics": {"empty_is_valid": true}}
  ],
  "metrics": {
    "candidate_count": 1,
    "eligible_candidate_count": 1,
    "exclusion_count_by_reason": {},
    "source_coverage": {"GRAPH": 1, "SEMANTIC": 1},
    "top_k_source_mix": {"GRAPH": 1, "SEMANTIC": 1},
    "topic_domain_diversity": 1,
    "difficulty_distribution": {"0.3": 1},
    "explicit_interest_coverage": 1.0,
    "semantic_candidate_coverage": 1.0,
    "revisit_share": 0.0,
    "continuation_share": 0.0,
    "rank_change_due_to_diversity": 0,
    "trace_completeness": 1.0
  },
  "execution_metadata": {
    "duration_ms": 12,
    "host": "synthetic-runner",
    "note": "excluded from equality and fingerprint"
  }
}
```

### 24.7 Empty-valid-result scenario

A scenario where every candidate is ineligible, or generation nominates nothing,
must succeed with an empty ranked set and all invariants `PASS`.

```json
{
  "contract_version": "m3-simulation/v2",
  "scenario_id": "scn-no-eligible-001",
  "config_version": "m3-sim-config/v1",
  "input_fingerprint": "sha256:1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e",
  "candidates_considered": [
    {
      "candidate_id": "cand:TOPIC:20000000-0000-4000-8000-000000000003:1",
      "target_entity_id": "20000000-0000-4000-8000-000000000003",
      "target_entity_version": 1,
      "target_entity_type": "TOPIC",
      "source_paths": [
        {
          "source": "EXPLICIT_INTEREST",
          "provenance": {
            "entity_id": "20000000-0000-4000-8000-000000000003",
            "preference": "MORE",
            "version": 1
          }
        }
      ],
      "prerequisite_evaluations": [
        {
          "objective_id": "40000000-0000-4000-8000-000000000009",
          "prerequisite_entity_id": "20000000-0000-4000-8000-000000000008",
          "requirement": "HARD",
          "evidence_summary": {"positive_evidence_count": 0, "negative_evidence_count": 0},
          "state": "UNKNOWN",
          "reason_codes": ["NO_DECIDING_EVIDENCE"]
        }
      ],
      "eligibility_state": "INELIGIBLE",
      "exclusion_reasons": ["INSUFFICIENT_STATE"],
      "feature_inputs": {"explicit_preference": "MORE"}
    }
  ],
  "candidates_excluded": [
    {
      "candidate_id": "cand:TOPIC:20000000-0000-4000-8000-000000000003:1",
      "target_entity_id": "20000000-0000-4000-8000-000000000003",
      "target_entity_version": 1,
      "target_entity_type": "TOPIC",
      "source_paths": [
        {
          "source": "EXPLICIT_INTEREST",
          "provenance": {
            "entity_id": "20000000-0000-4000-8000-000000000003",
            "preference": "MORE",
            "version": 1
          }
        }
      ],
      "prerequisite_evaluations": [
        {
          "objective_id": "40000000-0000-4000-8000-000000000009",
          "prerequisite_entity_id": "20000000-0000-4000-8000-000000000008",
          "requirement": "HARD",
          "evidence_summary": {"positive_evidence_count": 0, "negative_evidence_count": 0},
          "state": "UNKNOWN",
          "reason_codes": ["NO_DECIDING_EVIDENCE"]
        }
      ],
      "eligibility_state": "INELIGIBLE",
      "exclusion_reasons": ["INSUFFICIENT_STATE"],
      "feature_inputs": {"explicit_preference": "MORE"}
    }
  ],
  "ranked_recommendations": [],
  "invariant_results": [
    {"invariant_code": "IN-1", "status": "PASS", "diagnostics": {}},
    {"invariant_code": "IN-2", "status": "PASS", "diagnostics": {}},
    {"invariant_code": "IN-3", "status": "PASS", "diagnostics": {}},
    {"invariant_code": "IN-4", "status": "PASS", "diagnostics": {}},
    {"invariant_code": "IN-5", "status": "PASS", "diagnostics": {"traces_incomplete": 0}},
    {"invariant_code": "IN-6", "status": "PASS", "diagnostics": {"exclusions_without_reason": 0}},
    {"invariant_code": "IN-7", "status": "PASS", "diagnostics": {"ranks": []}},
    {"invariant_code": "IN-8", "status": "PASS", "diagnostics": {"duplicate_targets": 0}},
    {"invariant_code": "IN-9", "status": "PASS", "diagnostics": {"external_calls": 0}},
    {"invariant_code": "IN-10", "status": "PASS", "diagnostics": {"empty_is_valid": true}}
  ],
  "metrics": {
    "candidate_count": 1,
    "eligible_candidate_count": 0,
    "exclusion_count_by_reason": {"INSUFFICIENT_STATE": 1}
  },
  "execution_metadata": {}
}
```

## 25. Frozen for M3

The following are frozen by Issue #44:

- **Pipeline stages** — generation → normalization → eligibility → features →
  scoring → rerank → result + trace (§3).
- **SimulationInput** — versioned, synthetic learner, snapshot domains,
  generation context, and config; no real Auth users (§5, §6).
- **Candidate generation context** — explicit `CandidateGenerationContext`
  anchors that are query context, not learner facts; GRAPH/SEMANTIC self-exclusion;
  `RELATED_TO`-only graph traversal with canonical shortest-path provenance;
  exhaustive deterministic semantic retrieval with no threshold/top-K/ANN
  (§5, §8.1, §9).
- **Prerequisite objective context** — `REQUIRES` carries a required
  `objective_id`; objective-relative lookup matches `objective_id` AND
  prerequisite entity identity; frozen readiness mapping
  `UNDERSTOOD|RETAINED → SATISFIED`, absent → `UNKNOWN`, other states →
  `UNSATISFIED` (§6, §7).
- **Candidate** — normalized, merged, deterministic identity, source enum,
  exclusion reasons, and `target_entity_type` nullable iff the target is
  unresolved/`INVALID_TARGET` (§8, §8.3).
- **Prerequisite/readiness contract** — objective-relative, derived, states
  `SATISFIED|UNSATISFIED|UNKNOWN`, eligibility `ELIGIBLE|INELIGIBLE`, conservative
  UNKNOWN policy, hard-filter vs soft-feature (§7).
- **Explicit preference semantics** — five values, entity-scoped, override on
  conflict, separation from inferred interest (§10).
- **Scoring trace** — named features, `ScoreTrace`, weights as configuration
  (§11, §12).
- **Diversity/rerank trace** — algorithm-neutral `RerankTrace`, deterministic
  tie-breaking, MMR not required (§13).
- **RecommendationResult** — internal `ordering_score`, full trace,
  deterministic tiebreak key (§14).
- **Explanation codes** — machine-readable; template rendering optional (§15).
- **Exclusion codes** — minimal machine-readable vocabulary (§16).
- **SimulationResult** — fingerprint, candidates, recommendations, invariants,
  metrics, excluded execution metadata (§17).
- **Persistence boundary** — simulation trace is richer than production
  recommendation provenance but is not a field-for-field superset, and is not a
  new production schema; no migration (§18).
- **Hard invariants** — IN-1 through IN-10, `PASS|FAIL` with diagnostics (§19).
- **Descriptive metrics** — thirteen informational metrics, no thresholds; NDCG,
  MAP, Recall@K, Precision@K excluded (§20).
- **Scenario categories** — A through T, twenty categories (§21).
- **Determinism requirements** — canonical serialization, fingerprint, stable
  ordering, no wall-clock, offline (§4).
- **Non-goals** — what M3 does not prove (§22) and the privacy boundary (§23).

Deliberately **not** frozen here and deferred to evaluation in later M3 issues:
numeric weights, embedding provider, embedding dimension, ANN strategy, the
diversity algorithm, and any revisit-vs-exploration weighting. Production
semantic-retrieval limits (thresholds, top-K, ANN) and production graph-traversal
bounds also remain unfrozen; M3 simulation uses exhaustive deterministic
retrieval over the scenario fixture space only.

### Erratum — Issue #46 implementation/discovery evidence (v1 → v2)

The v1 input shape could not define candidate generation or prerequisite
evaluation unambiguously. Candidate generation needs explicit anchor/query
context, and a `REQUIRES` relationship needs an explicit objective whose learner
state is evaluated; neither was representable in `m3-simulation/v1`, whose
fixtures were already a merged consumer. The contract version is bumped to
`m3-simulation/v2`.

Changes from v1 to v2:

1. Adds required `CandidateGenerationContext` with `anchor_entities` to
   `SimulationInput` (§5). Anchors are simulation query context and MUST NOT be
   derived from learner-state or history domains.
2. Makes prerequisite-objective context explicit: `RelationshipSnapshot`
   carries `objective_id`, required for `REQUIRES` and null otherwise (§6, §7).
   Readiness lookup matches `objective_id` AND prerequisite entity identity, and
   the frozen state mapping is objective-state-based with no numeric threshold.
3. Clarifies GRAPH/SEMANTIC anchor behavior: anchors are never self-nominated;
   graph traversal is `RELATED_TO`-only, exhaustive, with canonical
   shortest-path provenance; semantic retrieval is exhaustive with no
   threshold/top-K/ANN (§8.1, §9).
4. Fixes the zero-source worked example (§24.7): every considered candidate now
   carries at least one genuine source path. The INSUFFICIENT_STATE candidate is
   nominated by an explicit `MORE` preference and remains INELIGIBLE because its
   hard prerequisite evidence is UNKNOWN, reinforcing that positive preference
   never bypasses a hard readiness constraint.

This is a simulation-only amendment: no production persistence change, no
migration, no API change, no ranking semantics introduced, and no production
retrieval or traversal limits frozen. The Issue #45 `interest_states` repair is
preserved. `contract_version` is now `m3-simulation/v2`.

#### Pre-consumer repair — unresolved target representation (Issue #46, v2)

During Phase B implementation preflight, the `INVALID_TARGET` rule was found to
be unrepresentable: `Candidate.target_entity_type` was non-nullable while an
unresolved target has no ontology-derived type. v2 is repaired so
`target_entity_type` is a required but nullable field, null **iff** the target is
unresolved and carries `INVALID_TARGET` (§8, §8.3). This is a representation
repair only: no candidate-generation semantics, ranking semantics, persistence,
migration, or production API change. `contract_version` remains
`m3-simulation/v2` because v2 exists only on the unmerged #46 branch and no
runtime consumer has read it.

### Erratum — Issue #45 implementation evidence

The original `m3-simulation/v1` `LearnerStateSnapshot` omitted the carrier for
`learner_interest_state` even though §10, §11, and §21 already required explicit
and inferred interest to remain separate. #45 fixture construction exposed the
omission before any recommendation engine (#46-#49) or external consumer read
the contract. The v1 input shape is corrected to require
`interest_states: LearnerInterestStateSnapshot[]` (§5).

This is a representation repair only: no recommendation semantics, ranking
weights, persistence schema, or production migration changed, and
`contract_version` remains `m3-simulation/v1`.

Changes to this contract after Issue #44 require evidence from implementation,
security, performance, cost, or product constraints.
