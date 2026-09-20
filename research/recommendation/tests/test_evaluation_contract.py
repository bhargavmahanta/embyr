"""m3-simulation/v5 evaluation contract and #49 fixture expectations.

Contract/fixture tests only. No runtime runner, metrics, or invariant engine is
exercised here; these tests freeze the v5 semantics and the #49 expectation
manifest so the later implementation has an executable contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from research.recommendation.fixtures.evaluation_expectations import (
    CONTRACT_VERSION,
    ENGINE_API,
    EVALUATION_EXPECTATIONS,
    EVALUATION_REPORT_FIELDS,
    EXCLUSION_KEYS,
    EXPECTATION_FAILURE_FIELDS,
    HARNESS_API,
    INVARIANT_CODES,
    METRIC_KEYS,
    SCENARIO_EVALUATION_FIELDS,
    SOURCE_KEYS,
)
from research.recommendation.fixtures.ids import SCENARIO_IDS
from research.recommendation.fixtures.scenarios import SCENARIOS

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "simulation-contract-v0.1.md"
CONTRACT_TEXT = CONTRACT_PATH.read_text(encoding="utf-8")


def _json_examples() -> list[object]:
    return [
        json.loads(raw)
        for raw in re.findall(r"```json\n(.*?)\n```", CONTRACT_TEXT, flags=re.DOTALL)
    ]


def _simulation_results() -> list[dict]:
    return [
        example
        for example in _json_examples()
        if isinstance(example, dict) and "ranked_recommendations" in example
    ]


# --- version + erratum ------------------------------------------------------


def test_contract_version_is_v5():
    assert 'contract_version = "m3-simulation/v5"' in CONTRACT_TEXT
    assert CONTRACT_VERSION == "m3-simulation/v5"


def test_every_fixture_is_v5():
    for scenario_id, simulation_input in SCENARIOS.items():
        assert simulation_input["contract_version"] == "m3-simulation/v5", scenario_id


def test_v4_to_v5_erratum_documents_scope():
    assert "### Erratum — Issue #49 simulation evaluation freeze (v4 → v5)" in CONTRACT_TEXT
    erratum = CONTRACT_TEXT.split(
        "### Erratum — Issue #49 simulation evaluation freeze (v4 → v5)", 1
    )[1].split("### Erratum — Issue #48", 1)[0]
    for phrase in (
        "top_k",
        "SimulationResult",
        "candidates_considered",
        "candidates_excluded",
        "RecommendationResult[]",
        "no production persistence",
    ):
        assert phrase in erratum, phrase


# --- SimulationResult schema ------------------------------------------------


def test_ranked_recommendations_is_recommendation_result():
    assert "ranked_recommendations      RecommendationResult[]" in CONTRACT_TEXT


def test_non_selected_eligible_are_dropped_publicly():
    assert "ranked_candidates_all" in CONTRACT_TEXT
    assert "non-selected" in CONTRACT_TEXT.lower()
    assert "`candidates_considered`" in CONTRACT_TEXT


def test_candidates_considered_and_excluded_semantics():
    assert "including `ELIGIBLE` and `INELIGIBLE`" in CONTRACT_TEXT
    assert "ordered by `candidate_id` ascending" in CONTRACT_TEXT
    assert 'eligibility_state == "INELIGIBLE"' in CONTRACT_TEXT


def test_top_k_semantics_frozen():
    assert "required integer >= 0" in CONTRACT_TEXT
    assert "selected_count" in CONTRACT_TEXT
    assert "min(top_k, len(full_recommendation_results))" in CONTRACT_TEXT
    assert "MUST NOT raise" in CONTRACT_TEXT


def test_execution_metadata_has_no_mandatory_key():
    assert (
        "For M3 v5 it has **no\n  required key**; the deterministic runner emits"
        in CONTRACT_TEXT
    )


def test_fingerprint_rule_and_engine_ownership():
    assert "input_fingerprint = \"sha256:\" + lowercase_hex" in CONTRACT_TEXT
    assert "simulator/identity.py" in CONTRACT_TEXT
    assert "MUST NOT import fixture" in CONTRACT_TEXT
    assert "no third\ncanonical serializer may be introduced" in CONTRACT_TEXT


# --- metrics ----------------------------------------------------------------


def test_metric_vocabulary_is_exactly_thirteen():
    assert len(METRIC_KEYS) == 13
    for metric in METRIC_KEYS:
        assert metric in CONTRACT_TEXT, metric


def test_every_simulation_result_example_has_all_metrics_and_invariants():
    results = _simulation_results()
    assert len(results) >= 3
    for example in results:
        assert set(example["metrics"]) == set(METRIC_KEYS), example["scenario_id"]
        assert [entry["invariant_code"] for entry in example["invariant_results"]] == list(
            INVARIANT_CODES
        ), example["scenario_id"]


def test_metric_zero_denominator_policy_and_descriptive_only():
    assert "A zero denominator yields\n  `0.0`" in CONTRACT_TEXT
    assert "MUST NOT determine scenario\n  PASS/FAIL" in CONTRACT_TEXT


def test_metric_maps_always_carry_all_keys():
    results = _simulation_results()
    for example in results:
        metrics = example["metrics"]
        assert set(metrics["exclusion_count_by_reason"]) == set(EXCLUSION_KEYS)
        assert set(metrics["source_coverage"]) == set(SOURCE_KEYS)
        assert set(metrics["top_k_source_mix"]) == set(SOURCE_KEYS)


# --- invariants -------------------------------------------------------------


def test_invariant_vocabulary_order_and_failure_behavior():
    assert list(INVARIANT_CODES) == [f"IN-{i}" for i in range(1, 11)]
    assert "does **not** raise" in CONTRACT_TEXT
    assert "IN-1`..`IN-10` order" in CONTRACT_TEXT


def test_in9_static_offline_guard_documented():
    assert "static offline guard" in CONTRACT_TEXT
    assert "external_calls: 0" in CONTRACT_TEXT


def test_scenario_evaluation_and_report_shapes_frozen():
    for field in SCENARIO_EVALUATION_FIELDS:
        assert field in CONTRACT_TEXT, field
    for field in EXPECTATION_FAILURE_FIELDS:
        assert field in CONTRACT_TEXT, field
    for field in EVALUATION_REPORT_FIELDS:
        assert field in CONTRACT_TEXT, field
    assert "Aggregate metric\naverages" in CONTRACT_TEXT


def test_engine_and_harness_boundary():
    for name in ENGINE_API:
        assert name in CONTRACT_TEXT, name
    for name in HARNESS_API:
        assert name in CONTRACT_TEXT, name
    assert "generic engine MUST NOT import fixture scenario IDs" in CONTRACT_TEXT


# --- top_k prefix example ---------------------------------------------------


def test_top_k_prefix_example_preserves_ranks_and_candidates():
    example = next(
        entry
        for entry in _simulation_results()
        if entry["scenario_id"] == "scn-top-k-prefix-001"
    )
    eligible = example["metrics"]["eligible_candidate_count"]
    assert eligible > len(example["ranked_recommendations"])
    ranks = [entry["final_rank"] for entry in example["ranked_recommendations"]]
    assert ranks == list(range(1, len(ranks) + 1))
    assert len(example["candidates_considered"]) == eligible
    assert example["metrics"]["semantic_candidate_coverage"] == 0.5


# --- #49 fixture expectations -----------------------------------------------


def test_evaluation_expectations_cover_all_scenarios():
    assert set(EVALUATION_EXPECTATIONS) == set(SCENARIO_IDS)


def test_empty_scenarios_are_valid_with_no_selected_targets():
    for scenario_id in ("scn-T-no-eligible-001", "scn-X7-multi-exclusion-empty-001"):
        expectation = EVALUATION_EXPECTATIONS[scenario_id]
        assert expectation["expected_selected_targets"] == []
        assert expectation["empty_result_is_valid"] is True
        assert expectation["expected_excluded_targets"]


def test_every_scenario_evaluates_all_ten_invariants():
    for scenario_id, expectation in EVALUATION_EXPECTATIONS.items():
        assert expectation["invariants_evaluated"] == list(INVARIANT_CODES), scenario_id


def test_selected_expectations_match_eligible_hard_oracles():
    for scenario_id, expectation in EVALUATION_EXPECTATIONS.items():
        for selected in expectation["expected_selected_targets"]:
            assert selected[2], scenario_id


# --- fingerprint behavior ---------------------------------------------------


def test_fingerprint_reordered_keys_equal_and_config_change_differs():
    import copy

    from research.recommendation.fixtures.canonical import input_fingerprint

    original = SCENARIOS["scn-R-multisource-duplicate-001"]
    reordered = dict(reversed(list(original.items())))
    assert input_fingerprint(reordered) == input_fingerprint(original)

    changed = copy.deepcopy(original)
    changed["simulation_config"]["top_k"] = original["simulation_config"]["top_k"] + 1
    assert input_fingerprint(changed) != input_fingerprint(original)
