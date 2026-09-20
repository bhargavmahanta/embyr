"""Referential and vocabulary integrity for every fixture scenario."""

from __future__ import annotations

import pytest

from research.recommendation.fixtures import SCENARIO_IDS, SCENARIOS
from research.recommendation.fixtures.builders import (
    CANDIDATE_SOURCES,
    ENTITY_TYPES,
    EXPLANATION_CODES,
    EXPLICIT_PREFERENCES,
    EXPLORATION_STATUSES,
    FEATURES,
    LEARNING_INTENTS,
    OBJECTIVE_STATES,
    PREREQUISITE_REQUIREMENTS,
    RELATIONSHIP_TYPES,
)
from research.recommendation.fixtures.ids import (
    CANONICAL_SCENARIO_IDS,
    COMPOUND_SCENARIO_IDS,
)
from research.recommendation.fixtures.semantic import VECTOR_DIMENSION
from research.recommendation.fixtures.timestamps import SIM_EPOCH

DOMAIN_LIKE_TYPES = {"DOMAIN", "AREA"}

SCENARIO_ORDER = list(SCENARIO_IDS)


def test_scenario_ids_are_unique_and_complete():
    assert len(SCENARIO_IDS) == 27
    assert len(set(SCENARIO_IDS)) == 27
    assert len(CANONICAL_SCENARIO_IDS) == 20
    assert len(COMPOUND_SCENARIO_IDS) == 7
    assert set(SCENARIO_IDS) == set(SCENARIOS)


@pytest.mark.parametrize("scenario_id", SCENARIO_ORDER)
def test_scenario_shape(scenario_id):
    snapshot = SCENARIOS[scenario_id]
    assert snapshot["scenario_id"] == scenario_id
    assert snapshot["contract_version"] == "m3-simulation/v2"
    assert snapshot["learner"]["synthetic"] is True
    assert snapshot["simulation_config"]["unknown_prerequisite_policy"] == "CONSERVATIVE_INELIGIBLE"


@pytest.mark.parametrize("scenario_id", SCENARIO_ORDER)
def test_entity_references_and_vocabulary(scenario_id):
    snapshot = SCENARIOS[scenario_id]
    entities = snapshot["ontology_snapshot"]["entities"]
    by_id = {entity["entity_id"]: entity for entity in entities}

    assert len(by_id) == len(entities), f"duplicate entity id in {scenario_id}"
    for entity in entities:
        assert entity["entity_type"] in ENTITY_TYPES
        assert 0.0 <= entity["difficulty_prior"] <= 1.0
        assert entity["estimated_effort_minutes"] > 0
        for domain_id in entity["domain_ids"]:
            assert domain_id in by_id, f"{scenario_id}: unknown domain {domain_id}"
            assert by_id[domain_id]["entity_type"] in DOMAIN_LIKE_TYPES
        for relationship in entity["relationships"]:
            assert relationship["relationship_type"] in RELATIONSHIP_TYPES
            target = relationship["target_entity_id"]
            assert target in by_id, f"{scenario_id}: unknown relationship target {target}"
            if relationship["relationship_type"] == "REQUIRES":
                assert relationship["requirement"] in PREREQUISITE_REQUIREMENTS
            else:
                assert relationship["requirement"] is None
        for objective_id in entity["objective_ids"]:
            assert objective_id


@pytest.mark.parametrize("scenario_id", SCENARIO_ORDER)
def test_learner_signal_domains_are_separate(scenario_id):
    snapshot = SCENARIOS[scenario_id]
    learner_state = snapshot["learner_state_snapshot"]
    entities = {
        entity["entity_id"]
        for entity in snapshot["ontology_snapshot"]["entities"]
    }

    # objective state: understanding/readiness evidence only.
    for state in learner_state["objective_states"]:
        assert state["state"] in OBJECTIVE_STATES
        assert state["entity_id"] in entities

    # interest state: inferred interest/affinity, a distinct field.
    for interest in learner_state["interest_states"]:
        assert interest["entity_id"] in entities
        assert interest["model_version"]
        assert interest["voluntary_revisit_count"] >= 0

    # explicit preference: separate snapshot, frozen vocabulary only.
    for preference in snapshot["preference_snapshot"]["explicit_preferences"]:
        assert preference["preference"] in EXPLICIT_PREFERENCES
        assert preference["entity_id"] in entities
        assert preference["version"] >= 1

    challenge = learner_state["challenge_state"]
    if challenge is not None:
        assert challenge["area_id"] in entities
        assert 0.0 <= challenge["ability_estimate"] <= 1.0


@pytest.mark.parametrize("scenario_id", SCENARIO_ORDER)
def test_exploration_history_and_semantic_space(scenario_id):
    snapshot = SCENARIOS[scenario_id]
    entities = {
        entity["entity_id"]
        for entity in snapshot["ontology_snapshot"]["entities"]
    }

    for exploration in snapshot["exploration_history"]["explorations"]:
        assert exploration["entity_id"] in entities
        assert exploration["learning_intent"] in LEARNING_INTENTS
        assert exploration["status"] in EXPLORATION_STATUSES

    space = snapshot["semantic_space"]
    assert space["vector_dimension"] == VECTOR_DIMENSION
    assert space["embedding_model"] == "fixture-basis-4d"
    for vector in space["vectors"]:
        assert len(vector["vector"]) == VECTOR_DIMENSION
        assert vector["entity_id"] in entities


def test_frozen_vocabulary_constants_match_contract():
    assert CANDIDATE_SOURCES == (
        "GRAPH",
        "SEMANTIC",
        "EXPLICIT_INTEREST",
        "HISTORY_CONTINUATION",
        "REVISIT",
    )
    assert len(EXPLANATION_CODES) == 8
    assert len(FEATURES) == 10
    assert SIM_EPOCH == "2026-01-01T00:00:00Z"


def test_every_entity_id_is_deterministic_uuid_shape():
    for scenario_id in SCENARIO_ORDER:
        for entity in SCENARIOS[scenario_id]["ontology_snapshot"]["entities"]:
            entity_id = entity["entity_id"]
            parts = entity_id.split("-")
            assert len(parts) == 5
            assert parts[2].startswith("4")  # version nibble
            assert entity_id == entity_id.lower()
