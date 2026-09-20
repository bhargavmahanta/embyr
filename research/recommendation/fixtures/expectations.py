"""Future-oracle expectation metadata for the M3 fixture corpus.

These manifests describe contract truth that future engine stages (#46-#49) must
satisfy. They are **not** executed results and are never embedded in
``SimulationInput``.

* ``hard_expectations`` -- contract truth that must hold once an engine exists.
  Targets are identified by ``(entity_id, entity_version, entity_type)``; the
  frozen deterministic tiebreak key may also be asserted verbatim.
* ``relative_expectations`` -- ordering claims testable only once a stage
  exists. Every one is grounded in same-scenario controlled comparators.
* ``descriptive_observations`` -- informational metric names; never thresholds.

No ``candidate_id`` encoding is asserted; the frozen contract does not freeze
one.
"""

from __future__ import annotations

from research.recommendation.fixtures.scenarios import SCENARIOS, SCENARIO_TARGETS

OFFLINE_INVARIANT = "IN-9"
ENGINE_STAGES = "#46-#49"


def _target(scenario_id: str, name: str) -> dict:
    try:
        descriptor = SCENARIO_TARGETS[scenario_id][name]
    except KeyError as error:
        raise KeyError(f"scenario {scenario_id!r} has no target {name!r}") from error
    return dict(descriptor)


def _tiebreak_key(target: dict) -> str:
    return f"{target['entity_type']}:{target['entity_id']}:{target['entity_version']}"


def _prerequisite_objective_id(scenario_id: str, target_name: str) -> str:
    """Return the declared ``objective_id`` for a target's REQUIRES prerequisite.

    The objective whose learner state gates the prerequisite is explicit in v2;
    this exposes it as a behavioral oracle without duplicating the fixture.
    """
    target = _target(scenario_id, target_name)
    key = (target["entity_id"], target["entity_version"])
    for entity in SCENARIOS[scenario_id]["ontology_snapshot"]["entities"]:
        if (entity["entity_id"], entity["entity_version"]) != key:
            continue
        for relationship in entity["relationships"]:
            if relationship["relationship_type"] == "REQUIRES":
                return relationship["objective_id"]
    raise KeyError(f"scenario {scenario_id!r} target {target_name!r} has no REQUIRES edge")


def _hard(scenario_id: str, name: str | None = None, **fields) -> dict:
    entry: dict = {}
    if name is not None:
        entry["target"] = _target(scenario_id, name)
    entry.update(fields)
    return entry


def _relative(scenario_id: str, higher: str, lower: str, rationale: str) -> dict:
    return {
        "higher_ranked_target": _target(scenario_id, higher),
        "lower_ranked_target": _target(scenario_id, lower),
        "rationale": rationale,
    }


def _rank(higher: dict, lower: dict) -> dict:
    """#47 ranking oracle (v3-frozen ordering)."""
    return {"kind": "ranking", "higher_ranked_target": higher, "lower_ranked_target": lower}


def _feature(target: dict, feature: str, value: float) -> dict:
    """#47 exact feature-value oracle."""
    return {"kind": "feature_value", "target": target, "feature": feature, "value": value}


def _entry(
    scenario_id: str,
    categories: list[str],
    invariants: list[str],
    hard: list[dict],
    relative: list[dict],
    descriptive: list[str],
    scoring_oracles: list[dict] | None = None,
) -> dict:
    if OFFLINE_INVARIANT not in invariants:
        invariants = [*invariants, OFFLINE_INVARIANT]
    return {
        "scenario_id": scenario_id,
        "categories": categories,
        "invariants_exercised": invariants,
        "hard_expectations": hard,
        "relative_expectations": relative,
        "scoring_oracles": scoring_oracles or [],
        "descriptive_observations": descriptive,
        "engine_stage": ENGINE_STAGES,
    }


E = "ELIGIBLE"
I = "INELIGIBLE"


EXPECTATIONS: dict[str, dict] = {
    "scn-A-explicit-more-001": _entry(
        "scn-A-explicit-more-001",
        ["A"],
        ["IN-1", "IN-4", "IN-5"],
        [
            _hard("scn-A-explicit-more-001", "target", eligibility_state=E, explanation_codes=["EXPLICIT_INTEREST_MATCH", "GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-A-explicit-more-001", "control", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-A-explicit-more-001", explicit_and_inferred_interest_exposed_separately=True),
        ],
        [_relative("scn-A-explicit-more-001", "target", "control", "explicit MORE vs otherwise-equivalent explicit NEUTRAL, inferred held constant positive")],
        ["explicit_interest_coverage", "source_coverage", "top_k_source_mix"],
        scoring_oracles=[
            _feature(_target("scn-A-explicit-more-001", "target"), "explicit_interest", 1.0),
            _feature(_target("scn-A-explicit-more-001", "control"), "explicit_interest", 0.0),
            _rank(_target("scn-A-explicit-more-001", "target"), _target("scn-A-explicit-more-001", "control")),
        ],
    ),
    "scn-B-explicit-less-001": _entry(
        "scn-B-explicit-less-001",
        ["B"],
        ["IN-1", "IN-4"],
        [
            _hard("scn-B-explicit-less-001", "target", eligibility_state=E, exclusion_reasons=[], explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED", "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED"]),
            _hard("scn-B-explicit-less-001", "control", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
        ],
        [_relative("scn-B-explicit-less-001", "control", "target", "explicit LESS is a soft negative, not an exclusion")],
        ["explicit_interest_coverage"],
        scoring_oracles=[
            _feature(_target("scn-B-explicit-less-001", "target"), "explicit_interest", -1.0),
            _feature(_target("scn-B-explicit-less-001", "control"), "explicit_interest", 0.0),
            _rank(_target("scn-B-explicit-less-001", "control"), _target("scn-B-explicit-less-001", "target")),
        ],
    ),
    "scn-C-explicit-paused-001": _entry(
        "scn-C-explicit-paused-001",
        ["C"],
        ["IN-1", "IN-2", "IN-6"],
        [
            _hard("scn-C-explicit-paused-001", "target", eligibility_state=I, exclusion_reasons=["EXPLICITLY_PAUSED"]),
            _hard("scn-C-explicit-paused-001", "control", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-C-explicit-paused-001", inference_cannot_lift_hard_exclusion=True),
        ],
        [],
        ["exclusion_count_by_reason"],
    ),
    "scn-D-not-interested-001": _entry(
        "scn-D-not-interested-001",
        ["D"],
        ["IN-1", "IN-2", "IN-6"],
        [
            _hard("scn-D-not-interested-001", "target", eligibility_state=I, exclusion_reasons=["NOT_INTERESTED"]),
            _hard("scn-D-not-interested-001", "control", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
        ],
        [],
        ["exclusion_count_by_reason"],
    ),
    "scn-E-preference-conflict-001": _entry(
        "scn-E-preference-conflict-001",
        ["E"],
        ["IN-1", "IN-4", "IN-5"],
        [
            _hard("scn-E-preference-conflict-001", "more_target", eligibility_state=E, exclusion_reasons=[], explanation_codes=["EXPLICIT_INTEREST_MATCH", "GOOD_DIFFICULTY_FIT", "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED"]),
            _hard("scn-E-preference-conflict-001", "less_target", eligibility_state=E, exclusion_reasons=[], explanation_codes=["GOOD_DIFFICULTY_FIT", "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED"]),
            _hard("scn-E-preference-conflict-001", override_reason_code="EXPLICIT_PREFERENCE_OVERRIDES_INFERRED"),
        ],
        [],
        ["explicit_interest_coverage"],
        scoring_oracles=[
            {
                "kind": "explicit_inferred_conflict",
                "target": _target("scn-E-preference-conflict-001", "more_target"),
                "explicit_interest": 1.0,
                "inferred_interest_sign": "negative",
                "effective_inferred_component": 0.0,
                "score_reason_code": "EXPLICIT_INFERRED_CONFLICT_SUPPRESSED",
            },
            {
                "kind": "explicit_inferred_conflict",
                "target": _target("scn-E-preference-conflict-001", "less_target"),
                "explicit_interest": -1.0,
                "inferred_interest_sign": "positive",
                "effective_inferred_component": 0.0,
                "score_reason_code": "EXPLICIT_INFERRED_CONFLICT_SUPPRESSED",
            },
            _rank(_target("scn-E-preference-conflict-001", "more_target"), _target("scn-E-preference-conflict-001", "less_target")),
        ],
    ),
    "scn-F-prereq-unmet-001": _entry(
        "scn-F-prereq-unmet-001",
        ["F"],
        ["IN-1", "IN-2", "IN-3", "IN-6"],
        [
            _hard(
                "scn-F-prereq-unmet-001",
                "target",
                eligibility_state=I,
                exclusion_reasons=["PREREQUISITE_UNMET"],
                prerequisite_state="UNSATISFIED",
                prerequisite_objective_id=_prerequisite_objective_id(
                    "scn-F-prereq-unmet-001", "target"
                ),
            ),
            _hard("scn-F-prereq-unmet-001", "control", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
        ],
        [_relative("scn-F-prereq-unmet-001", "control", "target", "otherwise-equivalent control has no unmet hard prerequisite")],
        ["exclusion_count_by_reason"],
    ),
    "scn-G-prereq-satisfied-001": _entry(
        "scn-G-prereq-satisfied-001",
        ["G"],
        ["IN-1", "IN-3", "IN-5"],
        [
            _hard(
                "scn-G-prereq-satisfied-001",
                "target",
                eligibility_state=E,
                prerequisite_state="SATISFIED",
                explanation_codes=["PREREQUISITES_SATISFIED", "GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"],
                prerequisite_objective_id=_prerequisite_objective_id(
                    "scn-G-prereq-satisfied-001", "target"
                ),
            ),
            _hard("scn-G-prereq-satisfied-001", "control", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
        ],
        [_relative("scn-G-prereq-satisfied-001", "target", "control", "satisfied hard prerequisite vs otherwise-equivalent control with none")],
        ["source_coverage"],
        scoring_oracles=[
            _feature(_target("scn-G-prereq-satisfied-001", "target"), "readiness", 1.0),
            _feature(_target("scn-G-prereq-satisfied-001", "control"), "readiness", 0.0),
            _rank(_target("scn-G-prereq-satisfied-001", "target"), _target("scn-G-prereq-satisfied-001", "control")),
        ],
    ),
    "scn-H-prereq-unknown-001": _entry(
        "scn-H-prereq-unknown-001",
        ["H"],
        ["IN-1", "IN-2", "IN-3", "IN-6"],
        [
            _hard(
                "scn-H-prereq-unknown-001",
                "target",
                eligibility_state=I,
                exclusion_reasons=["INSUFFICIENT_STATE"],
                prerequisite_state="UNKNOWN",
                must_not_exclude_as=["PREREQUISITE_UNMET"],
                prerequisite_objective_id=_prerequisite_objective_id(
                    "scn-H-prereq-unknown-001", "target"
                ),
            ),
            _hard("scn-H-prereq-unknown-001", "control", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
        ],
        [],
        ["exclusion_count_by_reason"],
    ),
    "scn-I-difficulty-too-low-001": _entry(
        "scn-I-difficulty-too-low-001",
        ["I"],
        ["IN-1", "IN-5"],
        [
            _hard("scn-I-difficulty-too-low-001", "too_low", eligibility_state=E, explanation_codes=["SEMANTICALLY_RELATED"]),
            _hard("scn-I-difficulty-too-low-001", "appropriate", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-I-difficulty-too-low-001", "too_high", eligibility_state=E, explanation_codes=["SEMANTICALLY_RELATED"]),
        ],
        [_relative("scn-I-difficulty-too-low-001", "appropriate", "too_low", "controlled difficulty: appropriate above too-low")],
        ["difficulty_distribution"],
        scoring_oracles=[
            _feature(_target("scn-I-difficulty-too-low-001", "appropriate"), "difficulty_fit", 1.0),
            _feature(_target("scn-I-difficulty-too-low-001", "too_low"), "difficulty_fit", 0.6),
            _rank(_target("scn-I-difficulty-too-low-001", "appropriate"), _target("scn-I-difficulty-too-low-001", "too_low")),
        ],
    ),
    "scn-J-difficulty-appropriate-001": _entry(
        "scn-J-difficulty-appropriate-001",
        ["J"],
        ["IN-1", "IN-5"],
        [
            _hard("scn-J-difficulty-appropriate-001", "appropriate", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-J-difficulty-appropriate-001", "too_low", eligibility_state=E, explanation_codes=["SEMANTICALLY_RELATED"]),
            _hard("scn-J-difficulty-appropriate-001", "too_high", eligibility_state=E, explanation_codes=["SEMANTICALLY_RELATED"]),
        ],
        [
            _relative("scn-J-difficulty-appropriate-001", "appropriate", "too_low", "controlled difficulty: appropriate above too-low"),
            _relative("scn-J-difficulty-appropriate-001", "appropriate", "too_high", "controlled difficulty: appropriate above too-high"),
        ],
        ["difficulty_distribution"],
        scoring_oracles=[
            _feature(_target("scn-J-difficulty-appropriate-001", "appropriate"), "difficulty_fit", 1.0),
            _feature(_target("scn-J-difficulty-appropriate-001", "too_low"), "difficulty_fit", 0.6),
            _feature(_target("scn-J-difficulty-appropriate-001", "too_high"), "difficulty_fit", 0.6),
            _rank(_target("scn-J-difficulty-appropriate-001", "appropriate"), _target("scn-J-difficulty-appropriate-001", "too_low")),
            _rank(_target("scn-J-difficulty-appropriate-001", "appropriate"), _target("scn-J-difficulty-appropriate-001", "too_high")),
        ],
    ),
    "scn-K-difficulty-too-high-001": _entry(
        "scn-K-difficulty-too-high-001",
        ["K"],
        ["IN-1", "IN-5"],
        [
            _hard("scn-K-difficulty-too-high-001", "too_high", eligibility_state=E, explanation_codes=["SEMANTICALLY_RELATED"]),
            _hard("scn-K-difficulty-too-high-001", "appropriate", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-K-difficulty-too-high-001", "too_low", eligibility_state=E, explanation_codes=["SEMANTICALLY_RELATED"]),
        ],
        [_relative("scn-K-difficulty-too-high-001", "appropriate", "too_high", "controlled difficulty: appropriate above too-high")],
        ["difficulty_distribution"],
        scoring_oracles=[
            _feature(_target("scn-K-difficulty-too-high-001", "appropriate"), "difficulty_fit", 1.0),
            _feature(_target("scn-K-difficulty-too-high-001", "too_high"), "difficulty_fit", 0.6),
            _rank(_target("scn-K-difficulty-too-high-001", "appropriate"), _target("scn-K-difficulty-too-high-001", "too_high")),
        ],
    ),
    "scn-L-semantic-neighbor-001": _entry(
        "scn-L-semantic-neighbor-001",
        ["L"],
        ["IN-1", "IN-5", "IN-8"],
        [
            _hard("scn-L-semantic-neighbor-001", "near", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-L-semantic-neighbor-001", "far", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT"]),
            _hard("scn-L-semantic-neighbor-001", semantic_nomination_signal_present=True),
        ],
        [_relative("scn-L-semantic-neighbor-001", "near", "far", "controlled semantic similarity to seed: near above far")],
        ["semantic_candidate_coverage", "source_coverage"],
        scoring_oracles=[
            {
                "kind": "feature_relation",
                "feature": "semantic_similarity",
                "higher_target": _target("scn-L-semantic-neighbor-001", "near"),
                "lower_target": _target("scn-L-semantic-neighbor-001", "far"),
            },
            _rank(_target("scn-L-semantic-neighbor-001", "near"), _target("scn-L-semantic-neighbor-001", "far")),
        ],
    ),
    "scn-M-graph-neighbor-001": _entry(
        "scn-M-graph-neighbor-001",
        ["M"],
        ["IN-1", "IN-5", "IN-8"],
        [
            _hard("scn-M-graph-neighbor-001", "distance_1", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-M-graph-neighbor-001", "distance_2", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-M-graph-neighbor-001", graph_nomination_signal_present=True),
        ],
        [_relative("scn-M-graph-neighbor-001", "distance_1", "distance_2", "controlled graph distance from seed: one hop above two hops")],
        ["source_coverage"],
        scoring_oracles=[
            _feature(_target("scn-M-graph-neighbor-001", "distance_1"), "graph_proximity", 1.0),
            _feature(_target("scn-M-graph-neighbor-001", "distance_2"), "graph_proximity", 0.5),
            _rank(_target("scn-M-graph-neighbor-001", "distance_1"), _target("scn-M-graph-neighbor-001", "distance_2")),
        ],
    ),
    "scn-N-continuation-001": _entry(
        "scn-N-continuation-001",
        ["N"],
        ["IN-1", "IN-5"],
        [
            _hard("scn-N-continuation-001", "target", eligibility_state=E, explanation_codes=["RELATED_TO_RECENT_EXPLORATION", "GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-N-continuation-001", "control", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
        ],
        [_relative("scn-N-continuation-001", "target", "control", "target relates to an active exploration; control is otherwise equivalent")],
        ["continuation_share"],
        scoring_oracles=[
            _feature(_target("scn-N-continuation-001", "target"), "continuation_value", 1.0),
            _feature(_target("scn-N-continuation-001", "control"), "continuation_value", 0.0),
            _rank(_target("scn-N-continuation-001", "target"), _target("scn-N-continuation-001", "control")),
        ],
    ),
    "scn-O-revisit-001": _entry(
        "scn-O-revisit-001",
        ["O"],
        ["IN-1", "IN-5"],
        [
            _hard("scn-O-revisit-001", "target", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED", "REVISIT_OPPORTUNITY"]),
            _hard("scn-O-revisit-001", "control", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
        ],
        [_relative("scn-O-revisit-001", "target", "control", "target has completed/returned history; control has none")],
        ["revisit_share"],
        scoring_oracles=[
            _feature(_target("scn-O-revisit-001", "target"), "revisit_value", 1.0),
            _feature(_target("scn-O-revisit-001", "control"), "revisit_value", 0.0),
            _rank(_target("scn-O-revisit-001", "target"), _target("scn-O-revisit-001", "control")),
        ],
    ),
    "scn-P-diversity-pressure-001": _entry(
        "scn-P-diversity-pressure-001",
        ["P"],
        ["IN-1", "IN-2"],
        [
            _hard("scn-P-diversity-pressure-001", "cluster_a", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-P-diversity-pressure-001", "cluster_b", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-P-diversity-pressure-001", "spread", eligibility_state=E, explanation_codes=["SEMANTICALLY_RELATED", "DIVERSITY_ADJUSTMENT"]),
            _hard("scn-P-diversity-pressure-001", rerank_only_reorders_eligible=True),
        ],
        [_relative("scn-P-diversity-pressure-001", "spread", "cluster_a", "diversity may lift spread above redundant same-domain cluster")],
        ["topic_domain_diversity", "rank_change_due_to_diversity"],
        scoring_oracles=[
            {
                "kind": "domain_coverage_reorder",
                "lifted_target": _target("scn-P-diversity-pressure-001", "spread"),
                "redundant_target": _target("scn-P-diversity-pressure-001", "cluster_a"),
            },
            _rank(_target("scn-P-diversity-pressure-001", "spread"), _target("scn-P-diversity-pressure-001", "cluster_a")),
        ],
    ),
    "scn-Q-deterministic-tie-001": _entry(
        "scn-Q-deterministic-tie-001",
        ["Q"],
        ["IN-1", "IN-7"],
        [
            _hard("scn-Q-deterministic-tie-001", "target_a", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-Q-deterministic-tie-001", "target_b", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-Q-deterministic-tie-001", symmetric_score_inputs=True),
            _hard("scn-Q-deterministic-tie-001", "target_a", deterministic_tiebreak_key=_tiebreak_key(_target("scn-Q-deterministic-tie-001", "target_a"))),
            _hard("scn-Q-deterministic-tie-001", "target_b", deterministic_tiebreak_key=_tiebreak_key(_target("scn-Q-deterministic-tie-001", "target_b"))),
        ],
        [_relative("scn-Q-deterministic-tie-001", "target_a", "target_b", "equal score inputs resolve by frozen tiebreak key ascending")],
        ["eligible_candidate_count"],
        scoring_oracles=[
            _rank(_target("scn-Q-deterministic-tie-001", "target_a"), _target("scn-Q-deterministic-tie-001", "target_b")),
        ],
    ),
    "scn-R-multisource-duplicate-001": _entry(
        "scn-R-multisource-duplicate-001",
        ["R"],
        ["IN-1", "IN-8"],
        [
            _hard("scn-R-multisource-duplicate-001", "target", eligibility_state=E, explanation_codes=["EXPLICIT_INTEREST_MATCH", "GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-R-multisource-duplicate-001", multi_source_signals_present=True),
        ],
        [],
        ["source_coverage", "top_k_source_mix"],
    ),
    "scn-S-sparse-learner-001": _entry(
        "scn-S-sparse-learner-001",
        ["S"],
        ["IN-1", "IN-5", "IN-6"],
        [
            _hard("scn-S-sparse-learner-001", "target", eligibility_state=E, exclusion_reasons=[], explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-S-sparse-learner-001", sparse_state_does_not_invalidate_target=True),
        ],
        [],
        ["candidate_count", "source_coverage"],
    ),
    "scn-T-no-eligible-001": _entry(
        "scn-T-no-eligible-001",
        ["T"],
        ["IN-2", "IN-6", "IN-10"],
        [
            _hard("scn-T-no-eligible-001", "paused", eligibility_state=I, exclusion_reasons=["EXPLICITLY_PAUSED"]),
            _hard("scn-T-no-eligible-001", "disliked", eligibility_state=I, exclusion_reasons=["NOT_INTERESTED"]),
            _hard("scn-T-no-eligible-001", "dependent", eligibility_state=I, exclusion_reasons=["INSUFFICIENT_STATE"]),
            _hard("scn-T-no-eligible-001", empty_result_is_valid=True),
        ],
        [],
        ["exclusion_count_by_reason"],
    ),
    "scn-X1-more-unmet-prereq-001": _entry(
        "scn-X1-more-unmet-prereq-001",
        ["A", "F"],
        ["IN-1", "IN-2", "IN-3", "IN-4", "IN-6"],
        [
            _hard("scn-X1-more-unmet-prereq-001", "target", eligibility_state=I, exclusion_reasons=["PREREQUISITE_UNMET"], prerequisite_state="UNSATISFIED", prerequisite_objective_id=_prerequisite_objective_id("scn-X1-more-unmet-prereq-001", "target")),
            _hard("scn-X1-more-unmet-prereq-001", "control", eligibility_state=E, explanation_codes=["EXPLICIT_INTEREST_MATCH", "GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-X1-more-unmet-prereq-001", explicit_more_cannot_bypass_hard_prerequisite=True),
        ],
        [],
        ["exclusion_count_by_reason", "explicit_interest_coverage"],
    ),
    "scn-X2-not-interested-inferred-positive-001": _entry(
        "scn-X2-not-interested-inferred-positive-001",
        ["D", "E"],
        ["IN-1", "IN-2", "IN-4", "IN-6"],
        [
            _hard("scn-X2-not-interested-inferred-positive-001", "target", eligibility_state=I, exclusion_reasons=["NOT_INTERESTED"]),
            _hard("scn-X2-not-interested-inferred-positive-001", "control", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-X2-not-interested-inferred-positive-001", strong_inferred_positive_cannot_lift_hard_exclusion=True),
        ],
        [],
        ["exclusion_count_by_reason"],
    ),
    "scn-X3-three-source-duplicate-001": _entry(
        "scn-X3-three-source-duplicate-001",
        ["R", "L", "M"],
        ["IN-1", "IN-5", "IN-8"],
        [
            _hard("scn-X3-three-source-duplicate-001", "target", eligibility_state=E, explanation_codes=["EXPLICIT_INTEREST_MATCH", "GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-X3-three-source-duplicate-001", "graph_only", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-X3-three-source-duplicate-001", target_has_graph_semantic_explicit_signals=True),
        ],
        [],
        ["source_coverage", "top_k_source_mix"],
    ),
    "scn-X4-diversity-ineligible-001": _entry(
        "scn-X4-diversity-ineligible-001",
        ["P", "C"],
        ["IN-1", "IN-2"],
        [
            _hard("scn-X4-diversity-ineligible-001", "cluster_a", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-X4-diversity-ineligible-001", "cluster_b", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-X4-diversity-ineligible-001", "ineligible", eligibility_state=I, exclusion_reasons=["EXPLICITLY_PAUSED"]),
            _hard("scn-X4-diversity-ineligible-001", ineligible_never_becomes_eligible_via_diversity=True),
        ],
        [_relative("scn-X4-diversity-ineligible-001", "cluster_a", "ineligible", "diversity reorders eligible candidates only; paused candidate stays excluded")],
        ["topic_domain_diversity", "exclusion_count_by_reason"],
        scoring_oracles=[
            {
                "kind": "ineligible_excluded_from_diversity_population",
                "excluded_target": _target("scn-X4-diversity-ineligible-001", "ineligible"),
            },
            _rank(_target("scn-X4-diversity-ineligible-001", "cluster_a"), _target("scn-X4-diversity-ineligible-001", "ineligible")),
        ],
    ),
    "scn-X5-tie-diversity-001": _entry(
        "scn-X5-tie-diversity-001",
        ["Q", "P"],
        ["IN-1", "IN-7"],
        [
            _hard("scn-X5-tie-diversity-001", "target_a", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-X5-tie-diversity-001", "target_b", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-X5-tie-diversity-001", "spread", eligibility_state=E, explanation_codes=["SEMANTICALLY_RELATED", "DIVERSITY_ADJUSTMENT"]),
            _hard("scn-X5-tie-diversity-001", symmetric_score_inputs=True),
            _hard("scn-X5-tie-diversity-001", "target_a", deterministic_tiebreak_key=_tiebreak_key(_target("scn-X5-tie-diversity-001", "target_a"))),
            _hard("scn-X5-tie-diversity-001", "target_b", deterministic_tiebreak_key=_tiebreak_key(_target("scn-X5-tie-diversity-001", "target_b"))),
        ],
        [_relative("scn-X5-tie-diversity-001", "target_a", "target_b", "equal score inputs resolve by frozen tiebreak key ascending")],
        ["rank_change_due_to_diversity"],
        scoring_oracles=[
            _rank(_target("scn-X5-tie-diversity-001", "target_a"), _target("scn-X5-tie-diversity-001", "target_b")),
        ],
    ),
    "scn-X6-sparse-semantic-001": _entry(
        "scn-X6-sparse-semantic-001",
        ["S", "L"],
        ["IN-1", "IN-5", "IN-6"],
        [
            _hard("scn-X6-sparse-semantic-001", "near", eligibility_state=E, explanation_codes=["GOOD_DIFFICULTY_FIT", "SEMANTICALLY_RELATED"]),
            _hard("scn-X6-sparse-semantic-001", sparse_semantic_candidate_valid=True),
        ],
        [],
        ["semantic_candidate_coverage", "explicit_interest_coverage"],
    ),
    "scn-X7-multi-exclusion-empty-001": _entry(
        "scn-X7-multi-exclusion-empty-001",
        ["T", "C", "D", "F", "H"],
        ["IN-1", "IN-2", "IN-6", "IN-10"],
        [
            _hard("scn-X7-multi-exclusion-empty-001", "paused", eligibility_state=I, exclusion_reasons=["EXPLICITLY_PAUSED"]),
            _hard("scn-X7-multi-exclusion-empty-001", "disliked", eligibility_state=I, exclusion_reasons=["NOT_INTERESTED"]),
            _hard("scn-X7-multi-exclusion-empty-001", "dependent", eligibility_state=I, exclusion_reasons=["PREREQUISITE_UNMET"], prerequisite_objective_id=_prerequisite_objective_id("scn-X7-multi-exclusion-empty-001", "dependent")),
            _hard("scn-X7-multi-exclusion-empty-001", "unknown_dependent", eligibility_state=I, exclusion_reasons=["INSUFFICIENT_STATE"], prerequisite_objective_id=_prerequisite_objective_id("scn-X7-multi-exclusion-empty-001", "unknown_dependent")),
            _hard("scn-X7-multi-exclusion-empty-001", empty_result_is_valid=True),
        ],
        [],
        ["exclusion_count_by_reason"],
    ),
}
