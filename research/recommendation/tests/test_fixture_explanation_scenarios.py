"""Execute all 27 fixtures through #46 -> #47 -> #48 (#48, §15.1 oracles).

Asserts only the frozen #48 explanation expectations and RecommendationResult
shape. #49 result assembly, metrics, and invariants are not exercised.
"""

from __future__ import annotations

import pytest

from research.recommendation.fixtures import SCENARIOS
from research.recommendation.fixtures.expectations import EXPECTATIONS
from research.recommendation.simulator import (
    build_recommendation_results,
    generate_candidates,
    rank_candidates,
)

SCENARIO_IDS = list(SCENARIOS)

RESULT_FIELDS = {
    "candidate_id",
    "target_entity_id",
    "target_entity_version",
    "target_entity_type",
    "candidate_sources",
    "readiness_summary",
    "score_trace",
    "rerank_trace",
    "ordering_score",
    "deterministic_tiebreak_key",
    "final_rank",
    "explanation_codes",
}


def _results(scenario_id: str) -> list[dict]:
    simulation_input = SCENARIOS[scenario_id]
    ranked = rank_candidates(simulation_input, generate_candidates(simulation_input))
    return build_recommendation_results(ranked)


def _oracles(scenario_id: str) -> dict[str, list[str]]:
    oracles: dict[str, list[str]] = {}
    for expectation in EXPECTATIONS[scenario_id]["hard_expectations"]:
        if "target" not in expectation or "explanation_codes" not in expectation:
            continue
        oracles[expectation["target"]["entity_id"]] = expectation["explanation_codes"]
    return oracles


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_results_have_exact_frozen_shape(scenario_id):
    for result in _results(scenario_id):
        assert set(result) == RESULT_FIELDS, scenario_id
        assert [entry["final_rank"] for entry in _results(scenario_id)] == list(
            range(1, len(_results(scenario_id)) + 1)
        )


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_fixture_explanation_oracles(scenario_id):
    results = {result["target_entity_id"]: result for result in _results(scenario_id)}
    for entity_id, expected in _oracles(scenario_id).items():
        assert entity_id in results, (scenario_id, entity_id)
        assert results[entity_id]["explanation_codes"] == expected, (
            scenario_id,
            entity_id,
        )


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_only_eligible_candidates_receive_results(scenario_id):
    simulation_input = SCENARIOS[scenario_id]
    candidates = generate_candidates(simulation_input)
    eligible = {
        candidate["target_entity_id"]
        for candidate in candidates
        if candidate["eligibility_state"] == "ELIGIBLE"
    }
    results = {result["target_entity_id"] for result in _results(scenario_id)}
    assert results == eligible, scenario_id


@pytest.mark.parametrize(
    "scenario_id",
    ["scn-T-no-eligible-001", "scn-X7-multi-exclusion-empty-001"],
)
def test_all_ineligible_scenarios_return_empty(scenario_id):
    assert _results(scenario_id) == []


def test_explanation_oracles_cover_expected_targets():
    covered = sum(len(_oracles(scenario_id)) for scenario_id in SCENARIO_IDS)
    assert covered >= 20


def test_explicit_less_never_gets_explicit_interest_match():
    from research.recommendation.fixtures import SCENARIO_TARGETS

    results = {
        result["target_entity_id"]: result
        for result in _results("scn-B-explicit-less-001")
    }
    less_id = SCENARIO_TARGETS["scn-B-explicit-less-001"]["target"]["entity_id"]
    assert "EXPLICIT_INTEREST_MATCH" not in results[less_id]["explanation_codes"]
    assert "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED" in results[less_id]["explanation_codes"]


def test_scenario_m_graph_only_context_has_no_graph_code():
    from research.recommendation.fixtures import SCENARIO_TARGETS

    results = {
        result["target_entity_id"]: result
        for result in _results("scn-M-graph-neighbor-001")
    }
    distance_1 = SCENARIO_TARGETS["scn-M-graph-neighbor-001"]["distance_1"]["entity_id"]
    for code in results[distance_1]["explanation_codes"]:
        assert "GRAPH" not in code
