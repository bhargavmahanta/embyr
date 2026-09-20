"""#49 end-to-end runner over the full 27-scenario fixture corpus."""

from __future__ import annotations

import pytest

from research.recommendation.fixtures import (
    CANONICAL_SCENARIO_IDS,
    COMPOUND_SCENARIO_IDS,
    SCENARIOS,
)
from research.recommendation.simulator import run_simulation

SCENARIO_IDS = list(SCENARIOS)
EMPTY_SCENARIOS = ("scn-T-no-eligible-001", "scn-X7-multi-exclusion-empty-001")

METRIC_KEYS = {
    "candidate_count",
    "eligible_candidate_count",
    "exclusion_count_by_reason",
    "source_coverage",
    "top_k_source_mix",
    "topic_domain_diversity",
    "difficulty_distribution",
    "explicit_interest_coverage",
    "semantic_candidate_coverage",
    "revisit_share",
    "continuation_share",
    "rank_change_due_to_diversity",
    "trace_completeness",
}


def test_corpus_shape():
    assert len(SCENARIO_IDS) == 27
    assert len(CANONICAL_SCENARIO_IDS) == 20
    assert len(COMPOUND_SCENARIO_IDS) == 7


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_runner_emits_full_result_for_every_scenario(scenario_id):
    result = run_simulation(SCENARIOS[scenario_id])
    assert result["contract_version"] == "m3-simulation/v5"
    assert set(result["metrics"]) == METRIC_KEYS
    codes = [entry["invariant_code"] for entry in result["invariant_results"]]
    assert codes == [f"IN-{index}" for index in range(1, 11)]
    assert {entry["status"] for entry in result["invariant_results"]} == {"PASS"}
    assert result["candidates_considered"]
    assert result["execution_metadata"] == {}


@pytest.mark.parametrize("scenario_id", EMPTY_SCENARIOS)
def test_empty_scenarios_are_valid(scenario_id):
    result = run_simulation(SCENARIOS[scenario_id])
    assert result["ranked_recommendations"] == []
    assert result["candidates_considered"]
    assert result["candidates_excluded"]
    assert set(result["metrics"]) == METRIC_KEYS
    assert all(entry["status"] == "PASS" for entry in result["invariant_results"])
