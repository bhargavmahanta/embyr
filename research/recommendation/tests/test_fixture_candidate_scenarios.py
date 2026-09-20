"""Execute the #45 fixture corpus through the #46 candidate pipeline.

Asserts only #46-owned behavior: candidate existence, eligibility, exclusion
reasons, prerequisite states, and source provenance. Scoring, ranking,
reranking, and explanation expectations are deliberately not asserted.
"""

from __future__ import annotations

import pytest

from research.recommendation.fixtures import SCENARIOS, SCENARIO_TARGETS
from research.recommendation.fixtures.expectations import EXPECTATIONS
from research.recommendation.simulator import generate_candidates

SCENARIO_IDS = list(SCENARIOS)
CATEGORY_T = "scn-T-no-eligible-001"
SCENARIO_E = "scn-E-preference-conflict-001"


def _by_key(candidates):
    return {
        (candidate["target_entity_id"], candidate["target_entity_version"]): candidate
        for candidate in candidates
    }


def _target_key(scenario_id, name):
    target = SCENARIO_TARGETS[scenario_id][name]
    return (target["entity_id"], target["entity_version"])


def _sources(candidate):
    return {path["source"] for path in candidate["source_paths"]}


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_every_scenario_generates_deterministically(scenario_id):
    first = generate_candidates(SCENARIOS[scenario_id])
    second = generate_candidates(SCENARIOS[scenario_id])
    assert first == second


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_hard_expectations_are_satisfied(scenario_id):
    candidates = _by_key(generate_candidates(SCENARIOS[scenario_id]))
    for expectation in EXPECTATIONS[scenario_id]["hard_expectations"]:
        target = expectation.get("target")
        if target is None or "eligibility_state" not in expectation:
            continue
        key = (target["entity_id"], target["entity_version"])
        assert key in candidates, (scenario_id, key)
        candidate = candidates[key]
        assert candidate["eligibility_state"] == expectation["eligibility_state"], (scenario_id, key)
        if "exclusion_reasons" in expectation:
            assert candidate["exclusion_reasons"] == expectation["exclusion_reasons"], (scenario_id, key)
        if "prerequisite_state" in expectation:
            states = {evaluation["state"] for evaluation in candidate["prerequisite_evaluations"]}
            assert expectation["prerequisite_state"] in states, (scenario_id, key, states)
        for forbidden in expectation.get("must_not_exclude_as", []):
            assert forbidden not in candidate["exclusion_reasons"], (scenario_id, key)


def test_scenario_e_explicit_conflict_targets_only():
    simulation_input = SCENARIOS[SCENARIO_E]
    assert simulation_input["generation_context"]["anchor_entities"] == []
    candidates = _by_key(generate_candidates(simulation_input))
    assert set(candidates) == {
        _target_key(SCENARIO_E, "more_target"),
        _target_key(SCENARIO_E, "less_target"),
    }
    for name in ("more_target", "less_target"):
        candidate = candidates[_target_key(SCENARIO_E, name)]
        assert candidate["eligibility_state"] == "ELIGIBLE"
        assert _sources(candidate) == {"EXPLICIT_INTEREST"}


def test_category_t_all_ineligible_and_anchor_absent():
    simulation_input = SCENARIOS[CATEGORY_T]
    anchor_keys = {
        (anchor["entity_id"], anchor["entity_version"])
        for anchor in simulation_input["generation_context"]["anchor_entities"]
    }
    candidates = generate_candidates(simulation_input)
    assert candidates
    assert all(candidate["eligibility_state"] == "INELIGIBLE" for candidate in candidates)
    assert anchor_keys.isdisjoint(
        {(candidate["target_entity_id"], candidate["target_entity_version"]) for candidate in candidates}
    )


def test_scenario_r_multisource_single_candidate():
    candidates = generate_candidates(SCENARIOS["scn-R-multisource-duplicate-001"])
    assert len(candidates) == 1
    assert _sources(candidates[0]) == {"GRAPH", "SEMANTIC", "EXPLICIT_INTEREST"}


def test_scenario_x3_three_source_single_candidate():
    candidates = _by_key(generate_candidates(SCENARIOS["scn-X3-three-source-duplicate-001"]))
    target = candidates[_target_key("scn-X3-three-source-duplicate-001", "target")]
    assert _sources(target) == {"GRAPH", "SEMANTIC", "EXPLICIT_INTEREST"}


def test_scenario_m_graph_provenance():
    candidates = _by_key(generate_candidates(SCENARIOS["scn-M-graph-neighbor-001"]))
    first = candidates[_target_key("scn-M-graph-neighbor-001", "distance_1")]
    second = candidates[_target_key("scn-M-graph-neighbor-001", "distance_2")]
    assert "GRAPH" in _sources(first) and "GRAPH" in _sources(second)
    first_graph = next(path for path in first["source_paths"] if path["source"] == "GRAPH")
    second_graph = next(path for path in second["source_paths"] if path["source"] == "GRAPH")
    assert first_graph["provenance"]["hop_distance"] == 1
    assert second_graph["provenance"]["hop_distance"] == 2


def test_scenario_n_continuation_and_o_revisit():
    continuation = _by_key(generate_candidates(SCENARIOS["scn-N-continuation-001"]))
    target = continuation[_target_key("scn-N-continuation-001", "target")]
    assert "HISTORY_CONTINUATION" in _sources(target)

    revisit = _by_key(generate_candidates(SCENARIOS["scn-O-revisit-001"]))
    revisited = revisit[_target_key("scn-O-revisit-001", "target")]
    assert "REVISIT" in _sources(revisited)


def test_scenario_l_semantic_targets_nominated():
    candidates = _by_key(generate_candidates(SCENARIOS["scn-L-semantic-neighbor-001"]))
    for name in ("near", "far"):
        candidate = candidates[_target_key("scn-L-semantic-neighbor-001", name)]
        assert "SEMANTIC" in _sources(candidate)
        assert candidate["eligibility_state"] == "ELIGIBLE"


def test_scenario_s_sparse_target_valid():
    candidates = _by_key(generate_candidates(SCENARIOS["scn-S-sparse-learner-001"]))
    target = candidates[_target_key("scn-S-sparse-learner-001", "target")]
    assert target["eligibility_state"] == "ELIGIBLE"
    assert target["exclusion_reasons"] == []


def test_scenario_x1_more_cannot_bypass_prerequisite():
    candidates = _by_key(generate_candidates(SCENARIOS["scn-X1-more-unmet-prereq-001"]))
    target = candidates[_target_key("scn-X1-more-unmet-prereq-001", "target")]
    assert target["eligibility_state"] == "INELIGIBLE"
    assert target["exclusion_reasons"] == ["PREREQUISITE_UNMET"]


def test_scenario_x2_not_interested_beats_inferred():
    candidates = _by_key(generate_candidates(SCENARIOS["scn-X2-not-interested-inferred-positive-001"]))
    target = candidates[_target_key("scn-X2-not-interested-inferred-positive-001", "target")]
    assert target["eligibility_state"] == "INELIGIBLE"
    assert target["exclusion_reasons"] == ["NOT_INTERESTED"]
