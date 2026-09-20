"""#49 fixture evaluation harness (m3-simulation/v5).

Compares deterministic ``SimulationResult`` output against the #49 fixture
expectations (§20.3). The harness may import fixture data; the generic engine
(``run.py``) must not. Expected/actual comparison and scenario verdicts live
only here and are never placed inside ``SimulationResult``.
"""

from __future__ import annotations

from research.recommendation.fixtures import SCENARIO_IDS, SCENARIOS
from research.recommendation.fixtures.evaluation_expectations import (
    CONTRACT_VERSION,
    EVALUATION_EXPECTATIONS,
    INVARIANT_CODES,
    METRIC_KEYS,
)

from .run import run_simulation

PASS = "PASS"
FAIL = "FAIL"


def _selected_key(entry: dict) -> tuple[str, int, str]:
    return (
        entry["target_entity_id"],
        entry["target_entity_version"],
        entry["target_entity_type"],
    )


def _candidate_key(entry: dict) -> tuple[str, int, str]:
    return (
        entry["target_entity_id"],
        entry["target_entity_version"],
        entry["target_entity_type"],
    )


def _expectation_failures(scenario_id: str, result: dict) -> list[dict]:
    expectation = EVALUATION_EXPECTATIONS[scenario_id]
    failures: list[dict] = []

    actual_selected = sorted(
        _selected_key(entry) for entry in result["ranked_recommendations"]
    )
    expected_selected = sorted(tuple(target) for target in expectation["expected_selected_targets"])
    if actual_selected != expected_selected:
        failures.append(
            {
                "check": "ranked_recommendations.selected_targets",
                "expected": expected_selected,
                "actual": actual_selected,
            }
        )

    excluded_by_key = {
        _candidate_key(candidate): list(candidate["exclusion_reasons"])
        for candidate in result["candidates_excluded"]
    }
    for target, reasons in expectation["expected_excluded_targets"]:
        key = tuple(target)
        expected_reasons = list(reasons)
        actual_reasons = excluded_by_key.get(key)
        if actual_reasons != expected_reasons:
            failures.append(
                {
                    "check": f"candidates_excluded[{key[0]}].exclusion_reasons",
                    "expected": expected_reasons,
                    "actual": actual_reasons,
                }
            )

    if expectation["empty_result_is_valid"] and result["ranked_recommendations"]:
        failures.append(
            {
                "check": "ranked_recommendations.empty",
                "expected": [],
                "actual": sorted(
                    entry["target_entity_id"]
                    for entry in result["ranked_recommendations"]
                ),
            }
        )

    codes = [entry["invariant_code"] for entry in result["invariant_results"]]
    if codes != list(INVARIANT_CODES):
        failures.append(
            {
                "check": "invariant_results.codes",
                "expected": list(INVARIANT_CODES),
                "actual": codes,
            }
        )

    missing_metrics = sorted(set(METRIC_KEYS) - set(result["metrics"]))
    if missing_metrics:
        failures.append(
            {
                "check": "metrics.keys",
                "expected": list(METRIC_KEYS),
                "actual": sorted(result["metrics"]),
            }
        )

    top_k = SCENARIOS[scenario_id]["simulation_config"]["top_k"]
    eligible = result["metrics"]["eligible_candidate_count"]
    expected_count = min(top_k, eligible)
    selected_count = len(result["ranked_recommendations"])
    if selected_count != expected_count:
        failures.append(
            {
                "check": "top_k.selection",
                "expected": expected_count,
                "actual": selected_count,
            }
        )

    return failures


def evaluate_scenario(scenario_id: str) -> dict:
    """Return a ``ScenarioEvaluation`` for one fixture scenario (§20.3)."""
    simulation_result = run_simulation(SCENARIOS[scenario_id])
    expectation_failures = _expectation_failures(scenario_id, simulation_result)
    invariants_pass = all(
        entry["status"] == PASS for entry in simulation_result["invariant_results"]
    )
    status = PASS if invariants_pass and not expectation_failures else FAIL
    return {
        "scenario_id": scenario_id,
        "status": status,
        "simulation_result": simulation_result,
        "expectation_failures": expectation_failures,
    }


def run_fixture_suite(scenario_ids: list[str] | tuple[str, ...] | None = None) -> dict:
    """Return an ``EvaluationReport`` over the fixture corpus (§20.3).

    Scenarios are evaluated in canonical fixture order (or the given order).
    """
    ids = list(SCENARIO_IDS if scenario_ids is None else scenario_ids)
    scenario_evaluations = [evaluate_scenario(scenario_id) for scenario_id in ids]
    passed_count = sum(
        1 for evaluation in scenario_evaluations if evaluation["status"] == PASS
    )
    failed_count = len(scenario_evaluations) - passed_count
    return {
        "contract_version": CONTRACT_VERSION,
        "status": PASS if failed_count == 0 else FAIL,
        "scenario_count": len(scenario_evaluations),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "scenario_evaluations": scenario_evaluations,
    }


def render_evaluation_summary(report: dict) -> str:
    """Return a concise deterministic summary string for an ``EvaluationReport``."""
    total = report["scenario_count"]
    passed = report["passed_count"]
    failed = report["failed_count"]
    if failed == 0:
        return f"{passed}/{total} scenarios passed; 0 failed."
    failed_ids = [
        evaluation["scenario_id"]
        for evaluation in report["scenario_evaluations"]
        if evaluation["status"] != PASS
    ]
    return f"{passed}/{total} scenarios passed; {failed} failed: {', '.join(failed_ids)}"
