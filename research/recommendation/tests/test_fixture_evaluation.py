"""#49 fixture evaluation harness: ScenarioEvaluation, EvaluationReport, summary."""

from __future__ import annotations

import copy

from research.recommendation.fixtures import SCENARIOS, SCENARIO_IDS
from research.recommendation.simulator import run_simulation
from research.recommendation.simulator.evaluate import (
    _expectation_failures,
    evaluate_scenario,
    render_evaluation_summary,
    run_fixture_suite,
)

SCENARIO_FIELDS = {
    "scenario_id",
    "status",
    "simulation_result",
    "expectation_failures",
}
REPORT_FIELDS = {
    "contract_version",
    "status",
    "scenario_count",
    "passed_count",
    "failed_count",
    "scenario_evaluations",
}


def test_scenario_evaluation_shape_and_status():
    evaluation = evaluate_scenario("scn-A-explicit-more-001")
    assert set(evaluation) == SCENARIO_FIELDS
    assert evaluation["status"] == "PASS"
    assert evaluation["expectation_failures"] == []
    assert "status" not in evaluation["simulation_result"]
    assert "expectation_failures" not in evaluation["simulation_result"]


def test_empty_scenarios_evaluate_pass():
    for scenario_id in ("scn-T-no-eligible-001", "scn-X7-multi-exclusion-empty-001"):
        evaluation = evaluate_scenario(scenario_id)
        assert evaluation["status"] == "PASS"
        assert evaluation["simulation_result"]["ranked_recommendations"] == []


def test_fixture_suite_covers_corpus_in_canonical_order():
    report = run_fixture_suite()
    assert set(report) == REPORT_FIELDS
    assert report["contract_version"] == "m3-simulation/v5"
    assert report["scenario_count"] == 27
    assert report["passed_count"] == 27
    assert report["failed_count"] == 0
    assert report["status"] == "PASS"
    assert [e["scenario_id"] for e in report["scenario_evaluations"]] == list(SCENARIO_IDS)


def test_fixture_suite_accepts_explicit_subset_order():
    subset = ["scn-T-no-eligible-001", "scn-A-explicit-more-001"]
    report = run_fixture_suite(subset)
    assert [e["scenario_id"] for e in report["scenario_evaluations"]] == subset
    assert report["scenario_count"] == 2


def test_summary_is_concise_and_deterministic():
    report = run_fixture_suite()
    assert render_evaluation_summary(report) == "27/27 scenarios passed; 0 failed."
    assert render_evaluation_summary(report) == render_evaluation_summary(report)


def test_summary_lists_failed_scenarios():
    report = {
        "scenario_count": 27,
        "passed_count": 25,
        "failed_count": 2,
        "scenario_evaluations": [
            {"scenario_id": "scn-A-explicit-more-001", "status": "PASS"},
            {"scenario_id": "scn-X3-three-source-duplicate-001", "status": "FAIL"},
            {"scenario_id": "scn-X7-multi-exclusion-empty-001", "status": "FAIL"},
        ],
    }
    assert (
        render_evaluation_summary(report)
        == "25/27 scenarios passed; 2 failed: scn-X3-three-source-duplicate-001, scn-X7-multi-exclusion-empty-001"
    )


def test_report_has_no_aggregate_quality_score():
    report = run_fixture_suite()
    forbidden = {"score", "quality", "percentage", "metric_averages", "average"}
    assert not (set(report) & forbidden)


def test_descriptive_metrics_cannot_gate_scenario_status():
    scenario_id = "scn-A-explicit-more-001"
    result = run_simulation(SCENARIOS[scenario_id])
    corrupted = copy.deepcopy(result)
    corrupted["metrics"]["eligible_candidate_count"] = 999
    del corrupted["metrics"]["source_coverage"]

    failures = _expectation_failures(scenario_id, corrupted)

    assert failures == []


def test_top_k_expectation_uses_structural_eligible_count():
    scenario_id = "scn-J-difficulty-appropriate-001"
    result = run_simulation(SCENARIOS[scenario_id])
    structural_eligible = sum(
        1
        for candidate in result["candidates_considered"]
        if candidate["eligibility_state"] == "ELIGIBLE"
    )
    assert structural_eligible == 3

    corrupted = copy.deepcopy(result)
    corrupted["metrics"]["eligible_candidate_count"] = 999
    assert not any(
        failure["check"] == "top_k.selection"
        for failure in _expectation_failures(scenario_id, corrupted)
    )

    truncated = copy.deepcopy(result)
    truncated["ranked_recommendations"] = truncated["ranked_recommendations"][:2]
    selection_failures = [
        failure
        for failure in _expectation_failures(scenario_id, truncated)
        if failure["check"] == "top_k.selection"
    ]
    assert selection_failures
    assert selection_failures[0]["expected"] == min(
        SCENARIOS[scenario_id]["simulation_config"]["top_k"], structural_eligible
    )
