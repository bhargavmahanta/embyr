"""Objective-relative prerequisite/readiness evaluation (§7, §19-§21)."""

from __future__ import annotations

from .identity import TargetKey
from .validation import SimulationInputError

#: Frozen readiness state vocabulary.
SATISFIED = "SATISFIED"
UNSATISFIED = "UNSATISFIED"
UNKNOWN = "UNKNOWN"

#: Objective states that satisfy a prerequisite (no numeric threshold).
SATISFYING_OBJECTIVE_STATES = frozenset({"UNDERSTOOD", "RETAINED"})

#: Frozen prerequisite evaluation reason codes (§20).
REASON_CODES = {
    SATISFIED: "PREREQUISITE_SATISFIED",
    UNSATISFIED: "PREREQUISITE_UNMET",
    UNKNOWN: "NO_DECIDING_EVIDENCE",
}


def classify_objective_state(state: str | None) -> str:
    """Map a matched learner objective state to a prerequisite state."""
    if state is None:
        return UNKNOWN
    if state in SATISFYING_OBJECTIVE_STATES:
        return SATISFIED
    return UNSATISFIED


def _find_objective_state(
    objective_states: list[dict],
    objective_id: str,
    prerequisite_entity_id: str,
    prerequisite_entity_version: int,
) -> dict | None:
    matches = [
        state
        for state in objective_states
        if state["objective_id"] == objective_id
        and state["entity_id"] == prerequisite_entity_id
        and state["entity_version"] == prerequisite_entity_version
    ]
    if len(matches) > 1:
        raise SimulationInputError(
            "ambiguous learner objective state for "
            f"({objective_id!r}, {prerequisite_entity_id!r}, {prerequisite_entity_version!r})"
        )
    return matches[0] if matches else None


def evaluate_prerequisites(
    target: TargetKey, entity: dict | None, simulation_input: dict
) -> list[dict]:
    """Return one PrerequisiteEvaluation per applicable REQUIRES edge.

    An unresolved target has no ontology entity and therefore no REQUIRES edges:
    its prerequisite evaluations are empty (contract §8.3).
    """
    if entity is None:
        return []

    objective_states = simulation_input["learner_state_snapshot"]["objective_states"]
    relationships = sorted(
        entity["relationships"],
        key=lambda relationship: (
            relationship["target_entity_id"],
            relationship["target_entity_version"],
            relationship["relationship_type"],
        ),
    )
    evaluations: list[dict] = []
    for relationship in relationships:
        if relationship["relationship_type"] != "REQUIRES":
            continue
        objective_id = relationship["objective_id"]
        prerequisite_entity_id = relationship["target_entity_id"]
        prerequisite_entity_version = relationship["target_entity_version"]
        matched = _find_objective_state(
            objective_states,
            objective_id,
            prerequisite_entity_id,
            prerequisite_entity_version,
        )
        state = classify_objective_state(matched["state"] if matched else None)
        evidence_summary: dict = {"objective_state": matched["state"] if matched else None}
        if matched is not None and matched.get("understanding_estimate") is not None:
            evidence_summary["understanding_estimate"] = matched["understanding_estimate"]
        evaluations.append(
            {
                "objective_id": objective_id,
                "prerequisite_entity_id": prerequisite_entity_id,
                "requirement": relationship["requirement"],
                "evidence_summary": evidence_summary,
                "state": state,
                "reason_codes": [REASON_CODES[state]],
            }
        )
    evaluations.sort(key=lambda evaluation: (evaluation["objective_id"], evaluation["prerequisite_entity_id"]))
    return evaluations
