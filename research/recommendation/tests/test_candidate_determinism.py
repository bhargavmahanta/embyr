"""Determinism of the #46 candidate pipeline."""

from __future__ import annotations

import copy

from research.recommendation.fixtures import SCENARIOS, SCENARIO_IDS, build_scenario
from research.recommendation.simulator import generate_candidates
from research.recommendation.simulator.identity import candidate_id, canonical_json


def test_rebuild_produces_identical_candidates():
    for scenario_id in SCENARIO_IDS:
        first = generate_candidates(SCENARIOS[scenario_id])
        rebuilt = generate_candidates(build_scenario(scenario_id))
        assert canonical_json(first) == canonical_json(rebuilt), scenario_id


def test_repeated_execution_is_identical():
    for scenario_id in SCENARIO_IDS:
        simulation_input = SCENARIOS[scenario_id]
        assert canonical_json(generate_candidates(simulation_input)) == canonical_json(
            generate_candidates(simulation_input)
        ), scenario_id


def test_input_key_order_does_not_affect_output():
    simulation_input = copy.deepcopy(SCENARIOS["scn-X3-three-source-duplicate-001"])
    reversed_input = dict(reversed(list(simulation_input.items())))
    assert canonical_json(generate_candidates(simulation_input)) == canonical_json(
        generate_candidates(reversed_input)
    )


def test_candidate_id_is_stable_and_distinct():
    assert candidate_id("a", 1) == candidate_id("a", 1)
    assert candidate_id("a", 1) != candidate_id("b", 1)
    assert candidate_id("a", 1) != candidate_id("a", 2)


def test_candidate_ids_are_unique_per_logical_target():
    for scenario_id in SCENARIO_IDS:
        candidates = generate_candidates(SCENARIOS[scenario_id])
        ids = [candidate["candidate_id"] for candidate in candidates]
        keys = [
            (candidate["target_entity_id"], candidate["target_entity_version"])
            for candidate in candidates
        ]
        assert len(ids) == len(set(ids)), scenario_id
        assert len(keys) == len(set(keys)), scenario_id
