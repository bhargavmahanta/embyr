"""Structural validation for the #46 candidate pipeline."""

from __future__ import annotations

import copy

import pytest

from research.recommendation.simulator import SimulationInputError, generate_candidates
from research.recommendation.tests._candidate_helpers import (
    make_input,
    objective_state,
    preference,
    requires,
    related,
    topic,
    vector,
)

SEED = [1.0, 0.0, 0.0, 0.0]


def _valid_input() -> dict:
    return make_input(
        entities=[topic("A")],
        anchors=[("A", 1)],
        vectors=[vector("A", SEED)],
        objective_states=[objective_state("OBJ-A", "A", "EXPLORING")],
    )


def test_valid_input_passes():
    assert generate_candidates(_valid_input()) is not None


def test_wrong_contract_version_rejected():
    sim = _valid_input()
    sim["contract_version"] = "m3-simulation/v1"
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_missing_generation_context_rejected():
    sim = _valid_input()
    del sim["generation_context"]
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_duplicate_anchor_rejected():
    sim = _valid_input()
    sim["generation_context"]["anchor_entities"].append({"entity_id": "A", "entity_version": 1})
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_unknown_anchor_rejected():
    sim = make_input(entities=[topic("A")], anchors=[("Z", 1)])
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_duplicate_ontology_logical_key_rejected():
    sim = make_input(entities=[topic("A"), topic("A")], anchors=[("A", 1)])
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_duplicate_semantic_vector_key_rejected():
    sim = make_input(
        entities=[topic("A")],
        anchors=[("A", 1)],
        vectors=[vector("A", SEED), vector("A", SEED)],
    )
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_invalid_objective_state_enum_rejected():
    sim = _valid_input()
    sim["learner_state_snapshot"]["objective_states"][0]["state"] = "BOGUS"
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_requires_missing_objective_id_rejected():
    sim = make_input(
        entities=[topic("A", relationships=[requires("P", "OBJ-P")]), topic("P")],
        anchors=[("A", 1)],
    )
    sim["ontology_snapshot"]["entities"] = [
        entity for entity in sim["ontology_snapshot"]["entities"] if entity["entity_id"] == "A"
    ]
    sim["ontology_snapshot"]["entities"][0]["relationships"][0]["objective_id"] = None
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_requires_missing_requirement_rejected():
    sim = make_input(
        entities=[topic("A", relationships=[requires("P", "OBJ-P")]), topic("P")],
        anchors=[("A", 1)],
    )
    sim["ontology_snapshot"]["entities"] = [
        entity for entity in sim["ontology_snapshot"]["entities"] if entity["entity_id"] == "A"
    ]
    sim["ontology_snapshot"]["entities"][0]["relationships"][0]["requirement"] = None
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_non_requires_carrying_objective_id_rejected():
    sim = make_input(entities=[topic("A", relationships=[related("B")]), topic("B")], anchors=[("A", 1)])
    sim["ontology_snapshot"]["entities"][0]["relationships"][0]["objective_id"] = "OBJ-X"
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_non_requires_carrying_requirement_rejected():
    sim = make_input(entities=[topic("A", relationships=[related("B")]), topic("B")], anchors=[("A", 1)])
    sim["ontology_snapshot"]["entities"][0]["relationships"][0]["requirement"] = "HARD"
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_malformed_semantic_dimension_rejected():
    sim = _valid_input()
    sim["semantic_space"]["vectors"][0]["vector"] = [1.0, 0.0, 0.0]
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_ambiguous_objective_state_rejected():
    sim = make_input(
        entities=[topic("A")],
        anchors=[("A", 1)],
        objective_states=[
            objective_state("OBJ-A", "A", "EXPLORING"),
            objective_state("OBJ-A", "A", "UNDERSTOOD"),
        ],
    )
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_objective_state_missing_entity_version_rejected():
    sim = _valid_input()
    del sim["learner_state_snapshot"]["objective_states"][0]["entity_version"]
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_explicit_preference_missing_entity_version_rejected():
    sim = make_input(entities=[topic("a")], preferences=[preference("a", "MORE")])
    del sim["preference_snapshot"]["explicit_preferences"][0]["entity_version"]
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_duplicate_explicit_preference_key_rejected():
    sim = make_input(
        entities=[topic("a")],
        preferences=[preference("a", "MORE"), preference("a", "LESS")],
    )
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)


def test_structural_invalidity_is_not_invalid_target():
    sim = copy.deepcopy(_valid_input())
    sim["semantic_space"]["vectors"][0]["vector"] = [1.0, 0.0]
    with pytest.raises(SimulationInputError):
        generate_candidates(sim)
