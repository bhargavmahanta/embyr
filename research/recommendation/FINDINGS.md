# M3 Recommendation Simulation Findings

Deterministic evidence recorded by milestone M3 for the frozen
`m3-simulation/v5` contract. These findings describe the behavior of Embyr's
own simulator; they are not production recommendation-quality results.

- Architecture and how to run: [`README.md`](README.md)
- Authoritative semantics: [`simulation-contract-v0.1.md`](simulation-contract-v0.1.md)
- Corpus: [`fixtures/README.md`](fixtures/README.md)

## Scope of evidence

Every claim below is derived from the actual simulator over the frozen
27-scenario synthetic corpus. Claims are either:

- **Established by simulation** — behavior proven by the frozen contract,
  implementation, and executed scenarios (including the hard invariants).
- **Observed in the corpus** — a fact about the current corpus that the contract
  does not make universal.

Evidence comes from deterministic scenario runs and the `PASS`/`FAIL` status of
the ten hard invariants. No external data, model, or network is involved.

## Established by the deterministic simulator

Each claim names the scenarios and/or invariant IDs that support it.

1. **`PAUSED` hard-excludes.** A `PAUSED` explicit preference yields
   `INELIGIBLE` with `EXPLICITLY_PAUSED` (scenarios C, T, X4; IN-2, IN-6).
2. **`NOT_INTERESTED` hard-excludes.** It excludes regardless of strong inferred
   positive interest (scenarios D, T, X2, X7; IN-2, IN-6).
3. **Unmet and unknown hard prerequisites stay distinct.** `UNSATISFIED` maps to
   `PREREQUISITE_UNMET`; `UNKNOWN` maps to `INSUFFICIENT_STATE`, not
   `PREREQUISITE_UNMET` (scenarios F, H, T, X7; IN-3, IN-6).
4. **Explicit `MORE` cannot bypass a hard prerequisite.** A liked target with an
   unmet hard prerequisite stays `INELIGIBLE` while an otherwise-equivalent ready
   control is recommended (scenario X1; IN-3).
5. **Inference cannot lift a hard exclusion.** Strong inferred positive interest
   does not rescue `NOT_INTERESTED` or `PAUSED` candidates (scenarios C, D, X2,
   X4; IN-2).
6. **Diversity cannot lift ineligible candidates.** Only eligible candidates
   enter the `DOMAIN_COVERAGE` population and its ordering; a paused candidate
   stays excluded under diversity pressure (scenario X4; IN-2).
7. **Explicit preference feature semantics are deterministic.** `MORE` = `+1.0`,
   `LESS` = `-1.0`, `NEUTRAL`/absent = `0.0`; on explicit/inferred conflict the
   raw inferred value is preserved but its effective contribution is suppressed
   and `EXPLICIT_INFERRED_CONFLICT_SUPPRESSED` is recorded (scenarios A, B, E;
   IN-4). This is fixed policy, not learned conflict resolution.
8. **Graph and semantic signals keep their frozen behavior.** `graph_proximity`
   decays with hop distance (`1.0` at one hop, `0.5` at two) and
   `semantic_similarity` preserves raw cosine (near-neighbor above far-neighbor)
   over fixed synthetic vectors (scenarios M, L).
9. **Continuation and revisit are independent features.** `HISTORY_CONTINUATION`
   and `REVISIT` each contribute independently as binary features, with no
   universal recency or revisit-wins rule (scenarios N, O).
10. **`DOMAIN_COVERAGE` can reorder eligible candidates.** A lower-scoring
    candidate from an underrepresented domain can be lifted above redundant
    higher-scoring candidates; the pre/post rank trace is preserved (scenarios P,
    X5; IN-1, IN-2).
11. **Explanations are contextual and trace-derived.** Codes are emitted from
    `RankedCandidate` evidence and do not require a positive weight or component
    score (scenario X3 selects a `0.0`-scoring candidate that still carries
    `EXPLICIT_INTEREST_MATCH`, `GOOD_DIFFICULTY_FIT`, `SEMANTICALLY_RELATED`).
    Machine reasons are translated, not recomputed (scenarios B, E, P). No LLM
    or generated prose is involved.
12. **Empty recommendation sets are valid.** When nothing is eligible, the
    simulator returns an empty ranked set without fabricating a fallback
    (scenarios T, X7; IN-10).
13. **`top_k` runs after full ranking and explanation.** The prefix is taken from
    the full explained population, ranks are preserved, and eligible results
    below `top_k` are not publicly retained (contract §17.1; exercised by the
    `top_k` invariant IN-7).
14. **The simulator is deterministic and offline.** The same input and config
    produce the same logical ordered result, `execution_metadata == {}`, and no
    model/network/database dependency exists (IN-1, IN-9; fingerprint rebuild
    equality).

## Observed in the synthetic fixture corpus

These are facts about the current 27-scenario corpus, **not** universal
guarantees.

- 27/27 fixture evaluations `PASS` (20 canonical A–T, 7 compound X1–X7).
- All 10 invariants `PASS` across the current scenarios.
- 46 selected recommendations across the corpus.
- All 8 explanation codes appear somewhere in the corpus.
- Every selected recommendation in this corpus currently carries at least one
  explanation code.
- Every non-empty scenario has `trace_completeness == 1.0`.

The contract still permits `explanation_codes == []`; the current corpus simply
does not surface a zero-code selected result. Emitting no code is legal whenever
no frozen emission condition holds.

## Representative cases

- **P — diversity reranking.** `spread` moves from pre-rerank rank 3 to
  `final_rank` 1 with `diversity_adjustment` `0.5`; the two same-domain clusters
  move down to ranks 2 and 3; `rank_change_due_to_diversity` is `3` and
  `topic_domain_diversity` is `2`. This is reordering of eligible candidates
  only.
- **T — valid empty result.** `eligible_candidate_count` is `0`,
  `ranked_recommendations` is `[]`, and `candidates_excluded` retains three
  inspectable exclusions (`EXPLICITLY_PAUSED`, `NOT_INTERESTED`,
  `INSUFFICIENT_STATE`) with all ten invariants `PASS` and all thirteen metrics
  emitted.
- **X3 — contextual explanations.** One candidate merges `GRAPH`, `SEMANTIC`, and
  `EXPLICIT_INTEREST` sources with a `pre_rerank_score` of `0.0`, yet carries
  three contextual explanation codes. Explanations describe context, not the
  causal rank contribution.

## Traceability

Every selected recommendation is traceable through the frozen stages:

```text
Candidate            -> nomination source + prerequisite + exclusion evidence
RankedCandidate      -> feature values + score components + rerank trace
RecommendationResult -> contextual explanation codes
SimulationResult     -> considered + excluded + selected + metrics + invariants
```

Under IN-5, every selected result in the frozen corpus has a complete decision
trace, and `trace_completeness == 1.0` for every non-empty scenario. This is
**simulation traceability**; production observability does not exist yet.

## What M3 does not prove

M3 does **not** establish:

- real-world recommendation quality;
- improved learning outcomes;
- improved engagement;
- optimal ranking weights;
- embedding-model quality;
- real-world relevance calibration;
- production personalization quality;
- causal impact;
- fairness or bias properties;
- production latency;
- throughput;
- scalability;
- Android UX quality;
- online experimentation results.

`27/27` scenario `PASS` means the frozen deterministic simulator behaves
consistently with the frozen synthetic contract corpus. It does **not** mean the
recommender is production-optimal or universally good.

## Known limitations

Tied to the current implementation:

- **Synthetic learner state.** All inputs are synthetic; no production or real
  user data is used.
- **Small corpus.** 27 hand-built scenarios, not a large sampled workload.
- **Fixed 4-D vectors.** `fixture-basis-4d` is auditable fixture data, not a
  production embedding provider or dimension.
- **No online feedback loop.** The simulator cannot learn from outcomes.
- **No RL / bandits / GNN.** No learned policy is evaluated.
- **No LLM ranking.** Scoring is additive and interpretable.
- **No production load testing.** Latency, throughput, and scale are not
  measured here.
- **Weights not empirically calibrated.** Per-scenario weights are simulation
  configuration, not user-tuned values.
- **No fairness study.** Bias and fairness are out of scope for M3.
- **Descriptive metrics are not quality scores.** Metric values describe a run;
  they do not measure recommendation quality or learner outcomes.

## Production validation still required

Before production integration, separately scoped work is required in at least
these categories (no dates or milestone IDs are implied):

1. **Data realism** — real learner-state ingestion and realistic distributions.
2. **Retrieval quality** — production graph and vector retrieval, provider,
   dimension, ANN, thresholds, and `top_k` policy.
3. **Weight calibration** — empirical tuning and re-validation of weights.
4. **User relevance** — relevance labels and quality evaluation.
5. **Learning outcomes** — whether recommendations improve learning.
6. **Performance** — latency, throughput, and scale validation.
7. **Privacy and safety** — review of production data handling and traces.
8. **Experimentation** — online experimentation infrastructure.
9. **Explanation quality** — human-readable explanation copy.
10. **Production integration** — online API/job orchestration, persistence,
    telemetry, and rollout.

## Conclusion

M3 demonstrates that Embyr's frozen recommendation architecture behaves
deterministically, traceably, and as specified across a frozen synthetic
scenario corpus. It validates mechanics and contract behavior — eligibility and
prerequisites, interpretable scoring, domain-coverage reranking, contextual
explanations, and deterministic evaluation — under the hard invariants.

It does not validate recommendation quality, learning impact, production
performance, or fairness. Those remain future, separately scoped work.
