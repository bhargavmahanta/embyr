"""Fixture alignment with the amended frozen contract.

Covers the Issue #45 erratum: the required ``interest_states`` carrier for
inferred interest, its canonical ordering, and its separation from explicit
preferences and objective/readiness state.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from research.recommendation.fixtures import SCENARIOS
from research.recommendation.fixtures.canonical import canonical_json

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "simulation-contract-v0.1.md"

INTEREST_STATE_FIELDS = {
    "entity_id",
    "entity_version",
    "recent_affinity",
    "long_term_affinity",
    "user_initiated_strength",
    "algorithm_exposure_strength",
    "voluntary_revisit_count",
    "last_interaction_at",
    "computed_at",
    "model_version",
}

AFFINITY_FIELDS = INTEREST_STATE_FIELDS - {"entity_id", "entity_version", "model_version"}

SCENARIOS_WITH_INFERRED_STATE = (
    "scn-A-explicit-more-001",
    "scn-B-explicit-less-001",
    "scn-E-preference-conflict-001",
    "scn-X2-not-interested-inferred-positive-001",
)


def _contract_text() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def _json_examples(text: str) -> list[str]:
    return re.findall(r"```json\n(.*?)\n```", text, flags=re.DOTALL)


def test_contract_json_examples_all_parse():
    examples = _json_examples(_contract_text())
    assert len(examples) == 7
    for index, example in enumerate(examples):
        json.loads(example)  # raises on invalid JSON


def test_contract_examples_carry_interest_states():
    learner_snapshots = [
        example["learner_state_snapshot"]
        for example in (json.loads(raw) for raw in _json_examples(_contract_text()))
        if "learner_state_snapshot" in example
    ]
    assert learner_snapshots, "expected at least one SimulationInput example"
    for snapshot in learner_snapshots:
        assert "interest_states" in snapshot
        assert snapshot["interest_states"] == []


def test_contract_freezes_interest_state_type_fields():
    text = _contract_text()
    block_match = re.search(
        r"LearnerInterestStateSnapshot\n(.*?)\n```", text, flags=re.DOTALL
    )
    assert block_match, "LearnerInterestStateSnapshot block missing"
    frozen_fields = set(re.findall(r"^- (\w+)", block_match.group(1), flags=re.MULTILINE))
    assert frozen_fields == INTEREST_STATE_FIELDS


def test_contract_version_unchanged():
    assert 'contract_version = "m3-simulation/v1"' in _contract_text()
    for scenario_id, simulation_input in SCENARIOS.items():
        assert simulation_input["contract_version"] == "m3-simulation/v1", scenario_id


def test_every_fixture_has_interest_states():
    for scenario_id, simulation_input in SCENARIOS.items():
        snapshot = simulation_input["learner_state_snapshot"]
        assert "interest_states" in snapshot, scenario_id
        assert isinstance(snapshot["interest_states"], list), scenario_id


def test_empty_interest_states_canonicalize_as_empty_list():
    empty = [s for s in SCENARIOS.values() if not s["learner_state_snapshot"]["interest_states"]]
    assert empty, "expected scenarios with no inferred-interest state"
    for simulation_input in empty:
        assert '"interest_states":[]' in canonical_json(simulation_input)


def test_interest_states_reference_valid_entities_and_unique_keys():
    for scenario_id, simulation_input in SCENARIOS.items():
        by_id = {
            (entity["entity_id"], entity["entity_version"]): entity
            for entity in simulation_input["ontology_snapshot"]["entities"]
        }
        keys = [
            (state["entity_id"], state["entity_version"])
            for state in simulation_input["learner_state_snapshot"]["interest_states"]
        ]
        assert len(keys) == len(set(keys)), scenario_id
        for key in keys:
            assert key in by_id, (scenario_id, key)


def test_interest_states_sorted_by_entity_id_and_version():
    for scenario_id, simulation_input in SCENARIOS.items():
        keys = [
            (state["entity_id"], state["entity_version"])
            for state in simulation_input["learner_state_snapshot"]["interest_states"]
        ]
        assert keys == sorted(keys), scenario_id


def test_interest_state_entries_use_exact_frozen_fields():
    for scenario_id, simulation_input in SCENARIOS.items():
        for state in simulation_input["learner_state_snapshot"]["interest_states"]:
            assert set(state) == INTEREST_STATE_FIELDS, scenario_id


def test_inferred_interest_never_leaks_into_objective_states():
    for scenario_id, simulation_input in SCENARIOS.items():
        for state in simulation_input["learner_state_snapshot"]["objective_states"]:
            assert set(state) <= {"objective_id", "entity_id", "state", "understanding_estimate"}, scenario_id
            assert not (set(state) & AFFINITY_FIELDS), scenario_id
        challenge = simulation_input["learner_state_snapshot"]["challenge_state"]
        if challenge is not None:
            assert set(challenge) == {"area_id", "ability_estimate"}, scenario_id


def test_explicit_preference_stays_in_preference_snapshot():
    for scenario_id, simulation_input in SCENARIOS.items():
        for preference in simulation_input["preference_snapshot"]["explicit_preferences"]:
            assert set(preference) == {"entity_id", "preference", "version"}, scenario_id
        for state in simulation_input["learner_state_snapshot"]["interest_states"]:
            assert "explicit_preference" not in state, scenario_id
            assert "preference" not in state, scenario_id


def test_target_scenarios_exercise_inferred_state():
    for scenario_id in SCENARIOS_WITH_INFERRED_STATE:
        states = SCENARIOS[scenario_id]["learner_state_snapshot"]["interest_states"]
        assert states, f"{scenario_id} should exercise inferred interest"


def test_no_universal_learner_score_introduced():
    forbidden = ("curiosity_score", "mastery_score", "learner_score", "learner_rating")
    contract_text = _contract_text().lower()
    for term in forbidden:
        assert term not in contract_text, term
    for scenario_id, simulation_input in SCENARIOS.items():
        serialized = canonical_json(simulation_input).lower()
        for term in forbidden:
            assert term not in serialized, (scenario_id, term)
