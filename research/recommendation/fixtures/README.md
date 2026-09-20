# M3 Recommendation Simulation Fixtures

Deterministic, offline simulation fixtures for the frozen M3 contract
(`../simulation-contract-v0.1.md`, Issue #44). Built by Issue #45.

The corpus builds `SimulationInput` snapshots only. It does **not** generate
candidates, evaluate eligibility, score, rank, rerank, or produce a
`SimulationResult`; those remain #46-#49.

## Corpus

27 scenarios, all deterministic and synthetic:

- **20 canonical** (`scn-A-…` … `scn-T-…`), one per frozen §21 category A-T.
- **7 compound** (`scn-X1-…` … `scn-X7-…`).

| id | intent |
|----|--------|
| X1 | explicit MORE target that also has an unmet hard prerequisite |
| X2 | NOT_INTERESTED target with strong inferred positive interest |
| X3 | one target carrying GRAPH + SEMANTIC + EXPLICIT_INTEREST signals |
| X4 | diversity pressure plus an explicitly ineligible candidate |
| X5 | deterministic tie inputs plus diversity context |
| X6 | sparse learner plus a semantic candidate |
| X7 | four different exclusion causes producing no eligible result |

`SCENARIOS` maps `scenario_id -> SimulationInput`; `build_scenario(id)` rebuilds
one from scratch; `SCENARIO_TARGETS` exposes each scenario's named targets as
`(entity_id, entity_version, entity_type)`.

## Conventions

- **IDs** (`ids.py`): UUID-shaped synthetic identifiers reusing the contract's
  namespaces (learner `10000000`, entity `20000000`, domain `30000000`,
  objective `40000000`). No `uuid4`, no randomness.
- **Time** (`timestamps.py`): fixed simulation epoch `2026-01-01T00:00:00Z` with
  deterministic offsets. No wall clock.
- **Semantics** (`semantic.py`): simulation-only model `fixture-basis-4d`,
  dimension 4, auditable basis vectors. Cosine to the seed is strictly ordered
  `seed > near > mid > far > opposite`. The dimension is fixture-local and is
  **not** a production embedding dimension.
- **Canonicalization** (`canonical.py`): contract §4 array ordering plus
  `canonical_json` and `input_fingerprint`.
- **Generation context** (`generation_context.anchor_entities`): explicit
  simulation query anchors, sorted by `(entity_id, entity_version)`; part of the
  `SimulationInput` fingerprint.

## Learner-signal domains stay separate

`builders.py` keeps four domains distinct; inferred interest is never read from
objective state and explicit preference is never collapsed into a score input.

| domain | builder field | meaning |
|--------|---------------|---------|
| `explicit_interest_preferences` | `preference_snapshot.explicit_preferences` | explicit user intent |
| `learner_interest_state` (LLD §27) | `learner_state_snapshot.interest_states` | inferred interest / affinity |
| `learner_objective_state` | `learner_state_snapshot.objective_states` | understanding / readiness evidence |
| `learner_challenge_state` | `learner_state_snapshot.challenge_state` | ability / challenge context |

## Expectations

`expectations.py` holds future-oracle metadata, never embedded in
`SimulationInput`:

- `hard_expectations` — contract truth future engines must satisfy
  (eligibility, exclusion reason, prerequisite state, tiebreak key). Targets are
  carried as `(entity_id, entity_version, entity_type)`; no `candidate_id`
  encoding is asserted because the contract does not freeze one.
- `relative_expectations` — ordering claims testable only once a stage exists.
  Every claim uses a same-scenario controlled comparator: the two targets differ
  only in the tested factor. Engine-dependent claims are marked
  `deferred_to: "#47"`.
- `descriptive_observations` — metric names only, never thresholds.

IN-9 (no external model/network) is referenced by every scenario and proven
structurally by `tests/test_fixture_offline.py`.

## Implementation notes (contract clarifications)

1. **No zero-source nominated candidates.** Generation nominates via graph,
   semantic, or explicit signals, so every nominated fixture target carries at
   least one real signal with provenance.
2. **IN-9 is structural.** It cannot be falsified by scenario data; the offline
   test scans the package for forbidden imports and nondeterministic APIs
   instead.
3. **`execution_metadata` is omitted from `SimulationInput`.** It is excluded
   from comparison and fingerprint by the contract, and the input schema does
   not declare it.
4. **`interest_states` implements the explicit v1 erratum.** The original
   `m3-simulation/v1` `LearnerStateSnapshot` enumerated only `objective_states`
   and `challenge_state`, so it had no carrier for inferred interest even though
   the contract already required explicit and inferred interest to remain
   separate. #45 fixture construction exposed the omission, the contract was
   amended (see the §25 erratum), and `interest_states` is now a **required**
   field of the frozen snapshot. It is the simulation analogue of the LLD §27
   `learner_interest_state` domain. This repair is preserved in
   `m3-simulation/v2`.
5. **Generation context is explicit (v2).** Every `SimulationInput` carries a
   required `generation_context.anchor_entities` list: explicit simulation query
   context for GRAPH/SEMANTIC generation. Anchors are never derived from
   learner-state, inferred-interest, preference, or exploration domains, are
   unique by `(entity_id, entity_version)`, resolve in the ontology snapshot, and
   are canonically sorted. Scenario E deliberately uses `[]`; every other
   scenario anchors on its scenario-local `seed`.
6. **`REQUIRES` declares its objective (v2).** A `REQUIRES` relationship carries
   both `requirement` (HARD/SOFT) and `objective_id`, and readiness is looked up
   by `objective_id` AND prerequisite entity identity. Frozen mapping:
   `UNDERSTOOD`/`RETAINED` → `SATISFIED`, no matching state → `UNKNOWN`, other
   frozen objective states → `UNSATISFIED`; no numeric threshold decides it.
7. **Anchors are never self-nominated (v2).** GRAPH and SEMANTIC exclude the
   anchor itself; `RELATED_TO` is the only graph-nominating relation, `REQUIRES`
   is readiness-only, and `PART_OF`/`BUILDS_ON` are non-nominating in M3.
8. **The v2 contract's zero-source example is repaired.** The §24.7
   `INSUFFICIENT_STATE` candidate now carries an `EXPLICIT_INTEREST` (`MORE`)
   source path and an UNKNOWN hard prerequisite, demonstrating that a positive
   preference does not bypass a hard readiness constraint.

## Validation

Pure Python, no new dependency. Run:

```text
python -m pytest research/recommendation/tests
```

The suite covers id/timestamp determinism, canonical bytes and fingerprint
stability, graph/reference integrity, frozen-vocabulary validity, semantic
dimension and ordering, `m3-simulation/v2` generation-context and
`objective_id` migration integrity, expectation coverage (A-T 20/20, IN-* union
10/10), and offline/no-hosted-identifier constraints.
