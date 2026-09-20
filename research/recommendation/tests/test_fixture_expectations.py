"""Coverage and reference integrity for the expectation manifests."""

from __future__ import annotations

from research.recommendation.fixtures import SCENARIO_IDS, SCENARIO_TARGETS, SCENARIOS
from research.recommendation.fixtures.expectations import EXPECTATIONS
from research.recommendation.fixtures.ids import (
    CANONICAL_SCENARIO_IDS,
    CATEGORY_BY_SCENARIO_ID,
    COMPOUND_SCENARIO_IDS,
)

CATEGORY_LETTERS = set("ABCDEFGHIJKLMNOPQRST")
INVARIANTS = {f"IN-{index}" for index in range(1, 11)}


def test_every_scenario_has_expectations():
    assert set(EXPECTATIONS) == set(SCENARIO_IDS)
    assert set(EXPECTATIONS) == set(SCENARIOS)


def test_canonical_and_compound_counts():
    assert len(CANONICAL_SCENARIO_IDS) == 20
    assert len(COMPOUND_SCENARIO_IDS) == 7
    assert len(SCENARIO_IDS) == 27


def test_a_to_t_categories_fully_covered():
    covered: set[str] = set()
    for scenario_id, manifest in EXPECTATIONS.items():
        assert set(manifest["categories"]) <= CATEGORY_LETTERS, scenario_id
        covered.update(manifest["categories"])
    assert covered == CATEGORY_LETTERS
    for scenario_id, category in CATEGORY_BY_SCENARIO_ID.items():
        assert category in EXPECTATIONS[scenario_id]["categories"], scenario_id


def test_invariant_union_fully_covered():
    covered: set[str] = set()
    for scenario_id, manifest in EXPECTATIONS.items():
        assert set(manifest["invariants_exercised"]) <= INVARIANTS, scenario_id
        covered.update(manifest["invariants_exercised"])
    assert covered == INVARIANTS


def _resolve(scenario_id: str, descriptor: dict) -> None:
    targets = SCENARIO_TARGETS[scenario_id]
    match = [t for t in targets.values() if t == descriptor]
    assert match, (scenario_id, descriptor)


def test_hard_expectation_targets_resolve_to_scenario_entities():
    for scenario_id, manifest in EXPECTATIONS.items():
        for expectation in manifest["hard_expectations"]:
            target = expectation.get("target")
            if target is not None:
                _resolve(scenario_id, target)


def test_relative_expectations_use_same_scenario_controlled_targets():
    for scenario_id, manifest in EXPECTATIONS.items():
        for expectation in manifest["relative_expectations"]:
            _resolve(scenario_id, expectation["higher_ranked_target"])
            _resolve(scenario_id, expectation["lower_ranked_target"])
            assert expectation["higher_ranked_target"] != expectation["lower_ranked_target"]


def test_tiebreak_keys_are_frozen_format():
    for scenario_id in ("scn-Q-deterministic-tie-001", "scn-X5-tie-diversity-001"):
        keys = [
            expectation["deterministic_tiebreak_key"]
            for expectation in EXPECTATIONS[scenario_id]["hard_expectations"]
            if "deterministic_tiebreak_key" in expectation
        ]
        assert len(keys) == 2, scenario_id
        for key in keys:
            entity_type, entity_id, entity_version = key.split(":")
            assert entity_type == "TOPIC"
            assert entity_id
            assert entity_version == "1"


def test_expectation_metadata_absent_from_simulation_input():
    for scenario_id, simulation_input in SCENARIOS.items():
        serialized = str(simulation_input)
        for forbidden in ("hard_expectations", "relative_expectations", "descriptive_observations", "categories"):
            assert forbidden not in serialized, (scenario_id, forbidden)


def test_descriptive_observations_are_metric_names_not_thresholds():
    forbidden_tokens = ("PASS", "FAIL", ">=", "<=", "threshold")
    for scenario_id, manifest in EXPECTATIONS.items():
        for observation in manifest["descriptive_observations"]:
            for token in forbidden_tokens:
                assert token not in observation, (scenario_id, observation)
