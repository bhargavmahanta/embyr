# Recommendation Simulation (M3)

The M3 recommendation simulator is Embyr's deterministic, offline research
harness for validating recommendation mechanics before production integration.

It validates **contract behavior** over a frozen synthetic scenario corpus. It
does **not** establish production recommendation quality. Research code under
`research/` does not automatically become production code; adoption requires a
separately scoped and reviewed change.

## Status and scope

- Built by milestone M3 ([#43](https://github.com/bhargavmahanta/embyr/issues/43))
  across issues #44–#50.
- Contract version: **`m3-simulation/v5`**, frozen in
  [`simulation-contract-v0.1.md`](simulation-contract-v0.1.md).
- Simulation-only: no production schema, no migration, no hosted Supabase
  mutation, no network or model provider.
- Observable evidence and limitations are recorded in [`FINDINGS.md`](FINDINGS.md).

Deep detail (full schemas, formulas, worked JSON examples, errata) lives in the
frozen contract. This document is the map, not a copy.

## Architecture

The pipeline is fixed and ordered. Each stage is owned by one issue:

```text
SimulationInput                     # synthetic, versioned snapshot
    |
    v
generate_candidates                 # #46 candidate generation + normalization
    |                               #     + hard eligibility / prerequisites
    v
Candidate[]                         # ELIGIBLE and INELIGIBLE, with provenance
    |
    v
rank_candidates                     # #47 feature extraction, additive scoring,
    |                               #     DOMAIN_COVERAGE rerank (eligible only)
    v
RankedCandidate[]                   # full ranked eligible population
    |
    v
build_recommendation_results        # #48 contextual explanation codes
    |
    v
RecommendationResult[]              # full explained eligible population
    |
    v
top_k                               # #49 prefix selection
    |
    v
SimulationResult                    # #49 candidates + selection + metrics
    |                               #     + invariants + fingerprint
    +--> ScenarioEvaluation         # harness: one scenario vs its oracle
    |
    +--> EvaluationReport           # harness: whole fixture suite
```

Stage ownership rules:

- Generation may only nominate; it cannot decide eligibility or ordering.
- Normalization merges duplicate targets and preserves every provenance path.
- Hard eligibility runs **before** scoring and is authoritative.
- Reranking only reorders eligible, already-scored candidates.
- Explanations read only the `RankedCandidate`; they never rescore or rerank.
- The generic engine is fixture-free; fixture comparison lives only in the
  harness.

## Candidate sources

Candidate nomination uses exactly five sources, in this canonical order:

```text
GRAPH
SEMANTIC
EXPLICIT_INTEREST
HISTORY_CONTINUATION
REVISIT
```

- Multiple nomination paths for the same `(target_entity_id,
  target_entity_version)` normalize into **one** `Candidate`, and source
  provenance survives normalization.
- A single candidate may carry several source categories at once.
- Source membership itself does not bypass eligibility: a nominated candidate is
  still subject to hard eligibility and may be excluded with a reason.
- `PAUSED` / `NOT_INTERESTED` are nominated first and then hard-excluded, so the
  exclusion trace keeps a real nomination source.

See [`fixtures/README.md`](fixtures/README.md) for the corpus and per-scenario
signal details.

## Eligibility and prerequisites

Hard eligibility and prerequisite evaluation run before scoring. Scoring only
ever sees `ELIGIBLE` candidates.

Explicit hard exclusions (entity-scoped):

```text
PAUSED           -> EXPLICITLY_PAUSED
NOT_INTERESTED   -> NOT_INTERESTED
```

Hard prerequisite states are objective-relative and derived (no numeric
threshold):

```text
HARD + SATISFIED     -> does not exclude; contributes to readiness feature
HARD + UNSATISFIED   -> INELIGIBLE, PREREQUISITE_UNMET
HARD + UNKNOWN       -> INELIGIBLE, INSUFFICIENT_STATE
SOFT + unmet/unknown -> does not exclude; may lower readiness feature only
```

`UNKNOWN` is deliberately distinct from `UNSATISFIED`: unknown is not unmet.
An unresolvable target becomes `INVALID_TARGET`. Eligibility collects **all**
applicable reasons (no short-circuit).

Hard exclusions cannot be lifted by score, by inference, or by diversity — no
weight, score, or rerank rule can move an `INELIGIBLE` candidate into the final
recommendation set.

## Scoring model

Scoring is interpretable and operates only on eligible candidates. The eight
frozen features are exactly:

```text
readiness  difficulty_fit  explicit_interest  inferred_interest
graph_proximity  semantic_similarity  continuation_value  revisit_value
```

Aggregation is additive and exactly recomputable:

```text
component_scores[f] = configured_weights[f] * effective_feature_value[f]
pre_rerank_score    = SUM(component_scores[f]) over the eight features
```

Key feature semantics (full formulas are frozen in the contract):

- **readiness** — fraction of prerequisite evaluations in state `SATISFIED`
  (`0.0` when there are none). Counts HARD and SOFT evaluations; SOFT outcomes
  lower readiness without excluding.
- **difficulty_fit** — `1.0 - abs(difficulty_prior - ability_estimate)` when the
  challenge area matches a candidate domain; `0.0` otherwise.
- **explicit_interest** — `MORE` `+1.0`, `LESS` `-1.0`, `NEUTRAL`/absent `0.0`.
- **inferred_interest** — `(recent_affinity + long_term_affinity) / 2.0`.
- **graph_proximity** — `max(1.0 / hop_distance)` over GRAPH paths; `0.0` if none.
- **semantic_similarity** — `max(cosine_similarity)` over SEMANTIC paths, raw
  scale preserved (negatives are not clamped); `0.0` if none.
- **continuation_value** / **revisit_value** — binary `1.0`/`0.0`.

A `configured_weights` key is optional; a missing key means weight `0.0`.
Weights are **per-scenario simulation configuration**, never learner truth, and
they are not calibrated on users. There is no module-private or global default
profile. `ordering_score` is internal only — it is not a curiosity score, a
mastery score, or a learner rating.

### Explicit vs inferred interest

When explicit and inferred interest conflict (opposite signs), the explicit
signal determines the effective contribution and the conflicting inferred
contribution is suppressed:

- the **raw** `inferred_interest` remains visible in `feature_values`;
- its **effective** contribution becomes `0.0`;
- the `ScoreTrace.reason_codes` records the machine reason
  `EXPLICIT_INFERRED_CONFLICT_SUPPRESSED`.

This is deterministic policy (an operational reading of "explicit preference
overrides inference"), not learned conflict resolution. When signs agree, both
may contribute.

### Graph and semantic signals

`graph_proximity` follows the frozen `RELATED_TO` hop relationship.
`semantic_similarity` is raw cosine over the scenario's declared vectors. M3
uses fixed, auditable **synthetic 4-D fixture vectors** (`fixture-basis-4d`),
not a production embedding provider; the dimension is fixture-local.

### Continuation and revisit

`HISTORY_CONTINUATION` and `REVISIT` are independent binary features. There is
no universal "revisit always wins" rule: ranking depends on the configured
feature weights and all other evidence.

## Diversity reranking

The only v3+ strategy is `DOMAIN_COVERAGE` (or `rerank: null`, a strict no-op).
Eligibility is already fixed at this point; diversity **only reorders eligible
candidates** and can never make an ineligible candidate eligible. There is no
MMR, no pairwise semantic-diversity reranking, and no greedy iterative reranker.

Frozen arithmetic over the eligible population:

```text
frequency(d)        = number of eligible candidates whose domain_ids contain d
domain_rarity(c)    = 0.0 if c has no domains
                      else mean(1.0 / frequency(d) for d in c.domain_ids)
minimum_rarity      = min(domain_rarity(c)) over eligible candidates
diversity_signal(c) = domain_rarity(c) - minimum_rarity
diversity_adjustment(c) = diversity_weight * diversity_signal(c)
ordering_score(c)       = pre_rerank_score(c) + diversity_adjustment(c)
```

When `diversity_adjustment > 0.0`, the rerank trace carries
`DOMAIN_COVERAGE_ADJUSTMENT`. Ineligible candidates are never part of the
frequency population. Scenario **P** demonstrates the reorder (see below).

## Explanation model

Explanations are machine-readable codes, **contextual rather than
rank-causal**: a code is emitted from genuine evidence in the `RankedCandidate`
and does not require the corresponding feature to have a positive weight or
component score. They are derived only from `RankedCandidate` fields — never from
`SimulationInput`, raw learner state, or an LLM.

The eight frozen codes, in canonical order:

```text
EXPLICIT_INTEREST_MATCH
RELATED_TO_RECENT_EXPLORATION
PREREQUISITES_SATISFIED
GOOD_DIFFICULTY_FIT
SEMANTICALLY_RELATED
REVISIT_OPPORTUNITY
DIVERSITY_ADJUSTMENT
EXPLICIT_PREFERENCE_OVERRIDES_INFERRED
```

Rules: all applicable codes are emitted, deduplicated, and serialized in
canonical order; cardinality is `0..8` and an empty list `[]` is legal and
contract-permitted. There is no fallback code, no human-readable prose, and no
generated rationale. Because a zero-weight signal can still produce a
contextual explanation, a selected result may carry codes even with a
`pre_rerank_score` of `0.0` (scenario **X3**).

## top_k and SimulationResult

`top_k` is applied **after** the full eligible population has been ranked and
explained, and after metrics/invariants that need the full population:

```text
top_k is a required integer >= 0
selected_count         = min(top_k, len(full_recommendation_results))
ranked_recommendations = full_recommendation_results[:selected_count]
```

- Prefix selection only; `final_rank` values are preserved and never renumbered.
- `top_k == 0` yields an empty list; a shortfall selects all available and does
  not raise.
- Eligible results below `top_k` are not publicly retained (their Candidate-level
  trace remains in `candidates_considered`).

`SimulationResult` fields:

```text
contract_version
scenario_id
config_version
input_fingerprint
candidates_considered     # every normalized candidate (ELIGIBLE and INELIGIBLE)
candidates_excluded       # the INELIGIBLE subset, with exclusion reasons
ranked_recommendations    # top_k-selected RecommendationResult[]
invariant_results         # IN-1..IN-10
metrics                   # descriptive only
execution_metadata        # {} for the deterministic runner
```

## Determinism

The simulator is deterministic and offline:

- The engine canonicalizes the order-insensitive `SimulationInput` arrays before
  identity is computed, then serializes with one engine-owned canonical JSON
  serializer.
- `input_fingerprint` is `sha256:<hex>` over that canonical input (excluding
  `execution_metadata`).
- Candidate, pre-rerank, and final orderings are stable and fully specified
  (`ordering_score` descending, then `deterministic_tiebreak_key` ascending).
- No wall clock, no randomness, no UUID generation during execution, and no
  model, network, or database dependency.
- `execution_metadata == {}` in M3 v5 and is excluded from logical equality.

This gives **repeatable M3 experiments**. It does not claim distributed-system
determinism or production reproducibility guarantees.

## Metrics

Thirteen descriptive metrics are emitted for every result, including empty ones.
All map-type metrics always carry every frozen key, even at zero.

| Metric | Population | Meaning |
|---|---|---|
| `candidate_count` | considered | number of normalized candidates |
| `eligible_candidate_count` | considered | candidates that passed hard eligibility |
| `exclusion_count_by_reason` | excluded | per-code counts (multi-reason candidates increment multiple counters) |
| `source_coverage` | considered | candidates carrying each source at least once |
| `top_k_source_mix` | selected | selected recommendations carrying each source |
| `topic_domain_diversity` | selected | distinct domain IDs across selected rerank traces |
| `difficulty_distribution` | selected | histogram of candidate `difficulty_prior` by canonical value |
| `explicit_interest_coverage` | considered | share with an `EXPLICIT_INTEREST` source |
| `semantic_candidate_coverage` | considered | share with a `SEMANTIC` source |
| `revisit_share` | selected | share with a `REVISIT` source |
| `continuation_share` | selected | share with a `HISTORY_CONTINUATION` source |
| `rank_change_due_to_diversity` | full ranked | count where pre-rerank rank changed |
| `trace_completeness` | selected | share of selected results with a complete trace |

A zero denominator yields `0.0`.

> **Metrics are descriptive only. They do not gate recommendation ranking,
> invariant status, scenario status, or evaluation status.** Metric values are
> not learner-quality scores.

## Invariants

All ten invariants are emitted for every scenario, in canonical order, with a
`PASS` or `FAIL` status and machine-readable diagnostics.

| Code | Check |
|---|---|
| IN-1 | same input + config produces the same logical ordered result |
| IN-2 | no `INELIGIBLE` candidate appears in final recommendations |
| IN-3 | hard prerequisites are never bypassed by score |
| IN-4 | explicit/inferred override behavior is deterministic |
| IN-5 | every final recommendation has a complete decision trace |
| IN-6 | every contract-required exclusion has a reason code |
| IN-7 | full ranks are contiguous/ordered and the selection is their prefix |
| IN-8 | no duplicate final targets after normalization |
| IN-9 | no external model/network dependency is required |
| IN-10 | an empty recommendation set is valid when nothing is eligible |

An invariant failure is **returned**, not raised: the `SimulationResult` stays
inspectable with `FAIL` entries. Structurally invalid `SimulationInput` may still
raise a validation error.

## Fixture model

The corpus is 27 deterministic, offline, synthetic scenarios:

- **20 canonical** (`A`–`T`), one per frozen contract category.
- **7 compound** (`X1`–`X7`), combining multiple mechanisms.

Canonical scenarios isolate one behavior; compound scenarios exercise
interactions (for example, explicit `MORE` against an unmet hard prerequisite,
or diversity pressure alongside an ineligible candidate).

Fixture properties: deterministic synthetic IDs, a fixed simulation epoch,
fixed auditable 4-D vectors, and explicit expectation manifests kept outside
`SimulationInput`. The full corpus, conventions, and oracle model are documented
in [`fixtures/README.md`](fixtures/README.md).

## How to run

Run the recommendation test suite from the repository root:

```text
python -m pytest research/recommendation/tests -q
```

Run the full fixture suite and print the deterministic summary:

```python
from research.recommendation.simulator.evaluate import (
    render_evaluation_summary,
    run_fixture_suite,
)

report = run_fixture_suite()
print(render_evaluation_summary(report))
```

The simulator is pure Python and needs no additional runtime dependency beyond
the test runner. No CLI exists; the callable APIs below are the interface.

## Public API

Engine APIs (frozen contract boundaries):

| API | Input | Output |
|---|---|---|
| `generate_candidates(simulation_input)` | `SimulationInput` dict | normalized `Candidate[]` |
| `rank_candidates(simulation_input, candidates)` | input + `Candidate[]` | full `RankedCandidate[]` |
| `build_recommendation_results(ranked_candidates)` | `RankedCandidate[]` | `RecommendationResult[]` |
| `run_simulation(simulation_input)` | `SimulationInput` dict | `SimulationResult` dict |

Fixture-harness APIs (research/evaluation infrastructure, not production):

| API | Purpose |
|---|---|
| `evaluate_scenario(scenario_id)` | evaluate one scenario against its oracle |
| `run_fixture_suite(scenario_ids=None)` | evaluate the whole corpus |
| `render_evaluation_summary(report)` | deterministic one-line summary string |

Internal helpers (normalization, prerequisite evaluation, per-candidate scoring,
reranking, metrics, invariant evaluation) are implementation details and are not
supported public API.

## Representative output

Abbreviated, deterministic runtime evidence. Full values are regenerated by the
commands above.

**Scenario P — diversity reranking reorders eligible candidates only.**

```text
spread:    pre_rerank_rank 3 -> final_rank 1   (diversity_adjustment 0.5)
cluster_a: pre_rerank_rank 1 -> final_rank 2
cluster_b: pre_rerank_rank 2 -> final_rank 3
rank_change_due_to_diversity: 3
topic_domain_diversity: 2
spread explanation_codes: [SEMANTICALLY_RELATED, DIVERSITY_ADJUSTMENT]
```

**Scenario T — empty result is valid.**

```text
eligible_candidate_count: 0
ranked_recommendations: []
candidates_excluded: 3
  exclusion reasons: EXPLICITLY_PAUSED, NOT_INTERESTED, INSUFFICIENT_STATE
invariant_results: IN-1..IN-10 all PASS
metrics: all 13 keys emitted
```

No fallback recommendation is fabricated.

**Scenario X3 — contextual explanations, not rank-causal.**

```text
one candidate merges sources: GRAPH + SEMANTIC + EXPLICIT_INTEREST
pre_rerank_score: 0.0
explanation_codes: [EXPLICIT_INTEREST_MATCH, GOOD_DIFFICULTY_FIT, SEMANTICALLY_RELATED]
```

## Path to production

M3 is a research harness. Moving toward a production recommendation service
requires separately scoped and reviewed work. #50 does **not** implement any of
the following:

- real learner-state ingestion (replacing synthetic snapshots);
- production candidate retrieval (graph service, ANN/vector store, thresholds,
  `top_k` policy, provider and dimension choices);
- online API/job orchestration and recommendation delivery;
- recommendation persistence and provenance;
- telemetry and feedback capture;
- empirical weight calibration;
- experimentation infrastructure;
- real-world relevance/outcome evaluation;
- latency, throughput, and scale validation;
- safety and privacy review;
- human-readable explanation copy.

The frozen contract deliberately leaves production weights, the embedding
provider, dimension, ANN strategy, and retrieval limits unfrozen.

## Contract version history

```text
v1  contract foundation
v2  candidate generation / readiness
v3  scoring / reranking
v4  explanations
v5  runner / evaluation
```

Each version is an additive, simulation-only freeze recorded in the contract's
errata; the current version is `m3-simulation/v5`.

## References

- [Recommendation Simulation Contract v0.1 (M3)](simulation-contract-v0.1.md) —
  frozen `m3-simulation/v5` semantics, schemas, formulas, and worked examples.
- [M3 fixture corpus](fixtures/README.md) — scenarios, conventions, and oracles.
- [M3 simulation findings](FINDINGS.md) — deterministic evidence, limitations,
  and what M3 does not prove.
