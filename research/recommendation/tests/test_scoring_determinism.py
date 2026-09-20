"""Determinism tests for #47 ranking: no input-order or map-order dependence."""

from __future__ import annotations

import pytest

from research.recommendation.fixtures import SCENARIOS
from research.recommendation.fixtures.canonical import canonical_json
from research.recommendation.simulator import generate_candidates, rank_candidates
from research.recommendation.tests._candidate_helpers import (
    make_input,
    preference,
    topic,
)

SCENARIO_IDS = list(SCENARIOS)


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_repeated_execution_is_byte_equivalent(scenario_id):
    simulation_input = SCENARIOS[scenario_id]
    first = rank_candidates(simulation_input, generate_candidates(simulation_input))
    second = rank_candidates(simulation_input, generate_candidates(simulation_input))
    assert canonical_json(first) == canonical_json(second)


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_candidate_input_order_does_not_matter(scenario_id):
    simulation_input = SCENARIOS[scenario_id]
    candidates = generate_candidates(simulation_input)
    forward = rank_candidates(simulation_input, candidates)
    reverse = rank_candidates(simulation_input, list(reversed(candidates)))
    assert canonical_json(forward) == canonical_json(reverse)


def test_feature_weight_map_order_does_not_matter():
    entities = [topic("a"), topic("b")]
    preferences = [preference("a", "MORE"), preference("b", "MORE")]
    forward_weights = {"explicit_interest": 1.0, "revisit_value": 2.0}
    reversed_weights = {"revisit_value": 2.0, "explicit_interest": 1.0}
    first = make_input(
        entities=entities, preferences=preferences, feature_weights=forward_weights
    )
    second = make_input(
        entities=entities, preferences=preferences, feature_weights=reversed_weights
    )
    assert canonical_json(
        rank_candidates(first, generate_candidates(first))
    ) == canonical_json(rank_candidates(second, generate_candidates(second)))


def test_domain_id_order_does_not_matter():
    simulation_input = make_input(
        entities=[topic("a"), topic("b")],
        preferences=[preference("a", "MORE"), preference("b", "MORE")],
        rerank={"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    for entity in simulation_input["ontology_snapshot"]["entities"]:
        if entity["entity_id"] == "a":
            entity["domain_ids"] = ["d2", "d1"]
        elif entity["entity_id"] == "b":
            entity["domain_ids"] = ["d1", "d2"]

    def _ranked():
        return rank_candidates(simulation_input, generate_candidates(simulation_input))

    first = _ranked()
    for entity in simulation_input["ontology_snapshot"]["entities"]:
        if entity["domain_ids"]:
            entity["domain_ids"] = list(reversed(entity["domain_ids"]))
    second = _ranked()
    assert canonical_json(first) == canonical_json(second)


def test_source_path_order_does_not_matter():
    simulation_input = SCENARIOS["scn-X3-three-source-duplicate-001"]
    candidates = generate_candidates(simulation_input)
    forward = rank_candidates(simulation_input, candidates)

    reversed_candidates = []
    for candidate in candidates:
        clone = dict(candidate)
        clone["source_paths"] = list(reversed(candidate["source_paths"]))
        reversed_candidates.append(clone)
    reversed_ranked = rank_candidates(simulation_input, reversed_candidates)
    assert canonical_json(forward) == canonical_json(reversed_ranked)
