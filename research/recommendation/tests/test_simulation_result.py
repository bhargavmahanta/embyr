"""#49 SimulationResult shape, ordering, fingerprint, and immutability."""

from __future__ import annotations

import copy

from research.recommendation.fixtures import SCENARIOS
from research.recommendation.simulator import generate_candidates, run_simulation

RESULT_FIELDS = (
    "contract_version",
    "scenario_id",
    "config_version",
    "input_fingerprint",
    "candidates_considered",
    "candidates_excluded",
    "ranked_recommendations",
    "invariant_results",
    "metrics",
    "execution_metadata",
)

HARNESS_FIELDS = {"expectation_failures", "status", "scenario_evaluations"}


def test_result_has_exact_frozen_shape_and_metadata():
    result = run_simulation(SCENARIOS["scn-A-explicit-more-001"])
    assert list(result) == list(RESULT_FIELDS)
    assert not (set(result) & HARNESS_FIELDS)
    assert result["execution_metadata"] == {}
    assert result["contract_version"] == "m3-simulation/v5"
    assert result["scenario_id"] == "scn-A-explicit-more-001"
    assert result["config_version"] == "m3-sim-config/v1"


def test_fingerprint_shape():
    result = run_simulation(SCENARIOS["scn-S-sparse-learner-001"])
    fingerprint = result["input_fingerprint"]
    assert fingerprint.startswith("sha256:")
    digest = fingerprint[len("sha256:") :]
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(character in "0123456789abcdef" for character in digest)


def test_candidates_considered_matches_candidate_pipeline_and_is_ordered():
    simulation_input = SCENARIOS["scn-R-multisource-duplicate-001"]
    result = run_simulation(simulation_input)
    expected = generate_candidates(simulation_input)
    assert result["candidates_considered"] == expected
    ids = [candidate["candidate_id"] for candidate in result["candidates_considered"]]
    assert ids == sorted(ids)


def test_candidates_excluded_is_overlapping_subset_in_order():
    result = run_simulation(SCENARIOS["scn-T-no-eligible-001"])
    considered_ids = {
        candidate["candidate_id"] for candidate in result["candidates_considered"]
    }
    excluded = result["candidates_excluded"]
    assert excluded
    assert all(
        candidate["eligibility_state"] == "INELIGIBLE" for candidate in excluded
    )
    assert all(candidate["candidate_id"] in considered_ids for candidate in excluded)
    assert [c["candidate_id"] for c in excluded] == sorted(
        c["candidate_id"] for c in excluded
    )


def test_ranked_recommendations_are_ordered_prefix():
    result = run_simulation(SCENARIOS["scn-J-difficulty-appropriate-001"])
    ranks = [entry["final_rank"] for entry in result["ranked_recommendations"]]
    assert ranks == list(range(1, len(ranks) + 1))


def test_invariant_results_are_all_ten_in_order():
    result = run_simulation(SCENARIOS["scn-A-explicit-more-001"])
    codes = [entry["invariant_code"] for entry in result["invariant_results"]]
    assert codes == [f"IN-{index}" for index in range(1, 11)]
    assert all(entry["status"] in {"PASS", "FAIL"} for entry in result["invariant_results"])


def test_run_simulation_does_not_mutate_input():
    simulation_input = SCENARIOS["scn-P-diversity-pressure-001"]
    original = copy.deepcopy(simulation_input)
    run_simulation(simulation_input)
    assert simulation_input == original
