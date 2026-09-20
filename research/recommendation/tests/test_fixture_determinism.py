"""Deterministic IDs, timestamps, serialization, fingerprint, and semantics."""

from __future__ import annotations

import copy

from research.recommendation.fixtures import SCENARIO_IDS, SCENARIOS, build_scenario
from research.recommendation.fixtures.canonical import (
    canonical_json,
    input_fingerprint,
    sort_entities,
    sort_relationships,
)
from research.recommendation.fixtures.semantic import (
    FAR,
    MID,
    NEAR,
    OPPOSITE,
    SEED,
    cosine_similarity,
    ordering_by_seed,
)
from research.recommendation.fixtures.timestamps import SIM_EPOCH, sim_time


def test_rebuild_is_byte_identical_and_same_fingerprint():
    for scenario_id in SCENARIO_IDS:
        first = build_scenario(scenario_id)
        second = build_scenario(scenario_id)
        assert canonical_json(first) == canonical_json(second), scenario_id
        assert input_fingerprint(first) == input_fingerprint(second), scenario_id
        assert canonical_json(SCENARIOS[scenario_id]) == canonical_json(first), scenario_id


def test_canonical_json_is_key_order_independent():
    scenario_id = "scn-R-multisource-duplicate-001"
    original = SCENARIOS[scenario_id]
    shuffled = copy.deepcopy(original)
    # Reverse top-level insertion order; canonical form must not change.
    reversed_items = dict(reversed(list(shuffled.items())))
    assert canonical_json(reversed_items) == canonical_json(original)


def test_canonical_sort_helpers_follow_contract_order():
    entities = [
        {"entity_id": "b", "entity_version": 2},
        {"entity_id": "a", "entity_version": 3},
        {"entity_id": "a", "entity_version": 1},
    ]
    assert sort_entities(entities) == [
        {"entity_id": "a", "entity_version": 1},
        {"entity_id": "a", "entity_version": 3},
        {"entity_id": "b", "entity_version": 2},
    ]
    relationships = [
        {"target_entity_id": "b", "target_entity_version": 1, "relationship_type": "REQUIRES"},
        {"target_entity_id": "a", "target_entity_version": 2, "relationship_type": "REQUIRES"},
        {"target_entity_id": "a", "target_entity_version": 2, "relationship_type": "BUILDS_ON"},
    ]
    assert sort_relationships(relationships) == [
        {"target_entity_id": "a", "target_entity_version": 2, "relationship_type": "BUILDS_ON"},
        {"target_entity_id": "a", "target_entity_version": 2, "relationship_type": "REQUIRES"},
        {"target_entity_id": "b", "target_entity_version": 1, "relationship_type": "REQUIRES"},
    ]


def test_semantic_ordering_seed_near_mid_far_opposite():
    assert ordering_by_seed() == ["seed", "near", "mid", "far", "opposite"]
    ordered = [SEED, NEAR, MID, FAR, OPPOSITE]
    similarities = [cosine_similarity(SEED, vector) for vector in ordered]
    assert similarities == sorted(similarities, reverse=True)
    assert len(set(similarities)) == len(similarities)


def test_timestamps_are_fixed_offsets_from_epoch():
    assert sim_time(0) == SIM_EPOCH
    assert sim_time(60) == "2026-01-01T01:00:00Z"
    assert sim_time(0, 30) == "2026-01-01T00:00:30Z"


def test_ids_are_stable_across_runs():
    for scenario_id in SCENARIO_IDS:
        first_ids = [entity["entity_id"] for entity in SCENARIOS[scenario_id]["ontology_snapshot"]["entities"]]
        second_ids = [entity["entity_id"] for entity in build_scenario(scenario_id)["ontology_snapshot"]["entities"]]
        assert first_ids == second_ids
        assert len(set(first_ids)) == len(first_ids)
