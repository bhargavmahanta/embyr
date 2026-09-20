"""#46 pipeline: validate -> generate -> normalize -> readiness -> eligibility."""

from __future__ import annotations

from .eligibility import build_candidate
from .normalize import normalize_nominations
from .readiness import evaluate_prerequisites
from .sources import generate_nominations
from .validation import validate_simulation_input


def _entities_by_key(simulation_input: dict) -> dict[tuple[str, int], dict]:
    return {
        (entity["entity_id"], entity["entity_version"]): entity
        for entity in simulation_input["ontology_snapshot"]["entities"]
    }


def _preferences_by_key(simulation_input: dict) -> dict[tuple[str, int], str]:
    return {
        (preference["entity_id"], preference["entity_version"]): preference["preference"]
        for preference in simulation_input["preference_snapshot"]["explicit_preferences"]
    }


def generate_candidates(simulation_input: dict) -> list[dict]:
    """Return deterministic normalized candidates for a SimulationInput.

    Runs only the #46-owned stages. The returned order is deterministic
    serialization order (``candidate_id`` ascending), not recommendation rank.
    """
    validate_simulation_input(simulation_input)

    entities = _entities_by_key(simulation_input)
    preferences = _preferences_by_key(simulation_input)

    normalized = normalize_nominations(generate_nominations(simulation_input))

    candidates: list[dict] = []
    for entry in normalized:
        key = (entry["target_entity_id"], entry["target_entity_version"])
        entity = entities.get(key)
        prerequisite_evaluations = evaluate_prerequisites(key, entity, simulation_input)
        explicit_preference = preferences.get(key)
        candidates.append(
            build_candidate(
                entry, entity, explicit_preference, prerequisite_evaluations
            )
        )

    candidates.sort(key=lambda candidate: candidate["candidate_id"])
    return candidates
