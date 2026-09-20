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


def test_contract_version_is_v4():
    assert 'contract_version = "m3-simulation/v4"' in _contract_text()
    for scenario_id, simulation_input in SCENARIOS.items():
        assert simulation_input["contract_version"] == "m3-simulation/v4", scenario_id


def _iter_candidates(value):
    if isinstance(value, dict):
        if isinstance(value.get("source_paths"), list) and "target_entity_id" in value:
            yield value
        for child in value.values():
            yield from _iter_candidates(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_candidates(child)


def _iter_mappings(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _iter_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_mappings(child)


def test_contract_examples_version_learner_references():
    for example in (json.loads(raw) for raw in _json_examples(_contract_text())):
        for mapping in _iter_mappings(example):
            if {"objective_id", "state", "entity_id"} <= set(mapping):
                assert "entity_version" in mapping, mapping
            if {"preference", "entity_id", "version"} <= set(mapping):
                assert "entity_version" in mapping, mapping


def test_contract_examples_are_v4():
    examples = [json.loads(raw) for raw in _json_examples(_contract_text())]
    versions = [ex["contract_version"] for ex in examples if "contract_version" in ex]
    assert versions, "expected versioned worked examples"
    assert all(version == "m3-simulation/v4" for version in versions)


def test_contract_examples_have_no_zero_source_candidate():
    for example in (json.loads(raw) for raw in _json_examples(_contract_text())):
        for candidate in _iter_candidates(example):
            assert candidate["source_paths"], "zero-source candidate in contract example"


def test_minimal_input_example_has_generation_context():
    example = json.loads(_json_examples(_contract_text())[0])
    assert "generation_context" in example
    assert example["generation_context"]["anchor_entities"] == [
        {"entity_id": "20000000-0000-4000-8000-000000000001", "entity_version": 1}
    ]


def test_every_fixture_has_generation_context():
    for scenario_id, simulation_input in SCENARIOS.items():
        generation_context = simulation_input["generation_context"]
        assert set(generation_context) == {"anchor_entities"}, scenario_id
        assert isinstance(generation_context["anchor_entities"], list), scenario_id


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
            assert set(state) <= {"objective_id", "entity_id", "entity_version", "state", "understanding_estimate"}, scenario_id
            assert not (set(state) & AFFINITY_FIELDS), scenario_id
        challenge = simulation_input["learner_state_snapshot"]["challenge_state"]
        if challenge is not None:
            assert set(challenge) == {"area_id", "ability_estimate"}, scenario_id


def test_explicit_preference_stays_in_preference_snapshot():
    for scenario_id, simulation_input in SCENARIOS.items():
        for preference in simulation_input["preference_snapshot"]["explicit_preferences"]:
            assert set(preference) == {"entity_id", "entity_version", "preference", "version"}, scenario_id
        for state in simulation_input["learner_state_snapshot"]["interest_states"]:
            assert "explicit_preference" not in state, scenario_id
            assert "preference" not in state, scenario_id


def test_every_objective_state_carries_entity_version():
    for scenario_id, simulation_input in SCENARIOS.items():
        for state in simulation_input["learner_state_snapshot"]["objective_states"]:
            assert isinstance(state["entity_version"], int), scenario_id


def test_objective_state_logical_keys_are_unique_and_canonical():
    for scenario_id, simulation_input in SCENARIOS.items():
        keys = [
            (state["objective_id"], state["entity_id"], state["entity_version"])
            for state in simulation_input["learner_state_snapshot"]["objective_states"]
        ]
        assert len(keys) == len(set(keys)), scenario_id
        assert keys == sorted(keys), scenario_id


def test_every_explicit_preference_carries_entity_version():
    for scenario_id, simulation_input in SCENARIOS.items():
        for preference in simulation_input["preference_snapshot"]["explicit_preferences"]:
            assert isinstance(preference["entity_version"], int), scenario_id


def test_explicit_preference_logical_keys_are_unique_and_canonical():
    for scenario_id, simulation_input in SCENARIOS.items():
        keys = [
            (preference["entity_id"], preference["entity_version"])
            for preference in simulation_input["preference_snapshot"]["explicit_preferences"]
        ]
        assert len(keys) == len(set(keys)), scenario_id
        assert keys == sorted(keys), scenario_id


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


# ---------------------------------------------------------------------------
# Issue #46 pre-consumer repair: unresolved target representation (Option A).
# Contract/document alignment only; no runtime candidate behavior.
# ---------------------------------------------------------------------------

ENTITY_TYPE_VOCABULARY = ["DOMAIN", "AREA", "TOPIC", "CONCEPT", "SKILL", "TECHNIQUE", "JOURNEY"]
UNRESOLVED_SECTION_HEADING = "### 8.3 Unresolved target representation"


def _candidate_block() -> str:
    match = re.search(r"```text\nCandidate\n(.*?)\n```", _contract_text(), flags=re.DOTALL)
    assert match, "Candidate block missing"
    return match.group(1)


def test_candidate_target_entity_type_is_required_and_nullable():
    line = re.search(r"^- target_entity_type\s+(.+)$", _candidate_block(), flags=re.MULTILINE)
    assert line, "target_entity_type field missing"
    assert line.group(1).strip().startswith("string|null")


def test_contract_freezes_unresolved_target_representation():
    text = _contract_text()
    assert UNRESOLVED_SECTION_HEADING in text
    section = text.split(UNRESOLVED_SECTION_HEADING, 1)[1].split("## 9.", 1)[0]
    for phrase in (
        "target_entity_type = null",
        "INELIGIBLE",
        "INVALID_TARGET",
        "prerequisite_evaluations` MUST be empty",
        "FAILS input validation",
        "(target_entity_id, target_entity_version)",
    ):
        assert phrase in section, phrase


def test_resolved_target_requires_frozen_entity_type_and_forbids_null():
    text = _contract_text()
    assert "`null` is invalid output" in text
    assert "equal to that entity's frozen `entity_type`" in text


def test_no_entity_type_sentinel_introduced():
    text = _contract_text()
    vocabulary = re.search(
        r"^- entity_type\s+string\s+#\s*(DOMAIN[^\n]*)$", text, flags=re.MULTILINE
    )
    assert vocabulary, "EntitySnapshot.entity_type vocabulary missing"
    assert [value.strip() for value in vocabulary.group(1).split("|")] == ENTITY_TYPE_VOCABULARY
    target_line = re.search(
        r"^- target_entity_type\s+(.+)$", _candidate_block(), flags=re.MULTILINE
    )
    assert target_line
    for sentinel in ("UNKNOWN", "INVALID", "MISSING", "UNRESOLVED"):
        assert re.search(rf"\b{sentinel}\b", target_line.group(1)) is None, sentinel


def test_invalid_target_representation_referenced_in_exclusion_contract():
    text = _contract_text()
    assert "`INVALID_TARGET` and `target_entity_type = null` (§8.3)" in text


def test_contract_records_v3_to_v4_migration():
    text = _contract_text()
    assert 'contract_version = "m3-simulation/v4"' in text
    assert "### Erratum — Issue #48 explanation freeze (v3 → v4)" in text
    # v3 history is retained for the #47 erratum.
    assert "### Erratum — Issue #47 scoring and diversity freeze (v2 → v3)" in text
    assert "m3-simulation/v3" in text
    # v2 history is retained for the #46 erratum.
    assert "m3-simulation/v2" in text
