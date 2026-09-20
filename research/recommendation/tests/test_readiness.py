"""Unit tests for objective-relative readiness evaluation."""

from __future__ import annotations

import pytest

from research.recommendation.simulator import SimulationInputError
from research.recommendation.simulator.readiness import (
    REASON_CODES,
    SATISFIED,
    UNSATISFIED,
    UNKNOWN,
    classify_objective_state,
    evaluate_prerequisites,
)
from research.recommendation.tests._candidate_helpers import make_input, objective_state, requires, topic

MAPPING = {
    "UNDERSTOOD": SATISFIED,
    "RETAINED": SATISFIED,
    "ENCOUNTERED": UNSATISFIED,
    "EXPLORING": UNSATISFIED,
    "DEVELOPING": UNSATISFIED,
    "REVISITING": UNSATISFIED,
    "PAUSED": UNSATISFIED,
    None: UNKNOWN,
}


@pytest.mark.parametrize("state,expected", list(MAPPING.items()))
def test_objective_state_mapping(state, expected):
    assert classify_objective_state(state) == expected


def _prerequisite_input(state, requirement="HARD", understanding=None):
    entity = topic("a", relationships=[requires("p", "OBJ-P", requirement)])
    states = [] if state is None else [objective_state("OBJ-P", "p", state, understanding)]
    sim = make_input(entities=[entity, topic("p")], anchors=[("a", 1)], objective_states=states)
    return entity, sim


@pytest.mark.parametrize(
    "state,requirement,expected_state",
    [
        ("UNDERSTOOD", "HARD", SATISFIED),
        ("ENCOUNTERED", "HARD", UNSATISFIED),
        (None, "HARD", UNKNOWN),
        ("UNDERSTOOD", "SOFT", SATISFIED),
        ("ENCOUNTERED", "SOFT", UNSATISFIED),
        (None, "SOFT", UNKNOWN),
    ],
)
def test_evaluate_prerequisites_states(state, requirement, expected_state):
    entity, sim = _prerequisite_input(state, requirement)
    evaluations = evaluate_prerequisites(("a", 1), entity, sim)
    assert len(evaluations) == 1
    evaluation = evaluations[0]
    assert evaluation["objective_id"] == "OBJ-P"
    assert evaluation["prerequisite_entity_id"] == "p"
    assert evaluation["requirement"] == requirement
    assert evaluation["state"] == expected_state
    assert evaluation["reason_codes"] == [REASON_CODES[expected_state]]


def test_evaluate_prerequisites_uses_prerequisite_entity_not_candidate():
    entity = topic("a", relationships=[requires("p", "OBJ-P")])
    sim = make_input(
        entities=[entity, topic("p")],
        anchors=[("a", 1)],
        objective_states=[
            objective_state("OBJ-A", "a", "UNDERSTOOD"),
            objective_state("OBJ-P", "p", "ENCOUNTERED"),
        ],
    )
    evaluation = evaluate_prerequisites(("a", 1), entity, sim)[0]
    assert evaluation["state"] == UNSATISFIED


def test_numeric_evidence_does_not_decide_state():
    entity, sim = _prerequisite_input("ENCOUNTERED", understanding=0.99)
    assert evaluate_prerequisites(("a", 1), entity, sim)[0]["state"] == UNSATISFIED
    entity, sim = _prerequisite_input("UNDERSTOOD", understanding=0.0)
    assert evaluate_prerequisites(("a", 1), entity, sim)[0]["state"] == SATISFIED


def test_unresolved_target_has_no_prerequisite_evaluations():
    sim = make_input(entities=[topic("a")], anchors=[("a", 1)])
    assert evaluate_prerequisites(("missing", 1), None, sim) == []


def test_no_requires_edge_yields_empty_evaluations():
    entity = topic("a")
    sim = make_input(entities=[entity], anchors=[("a", 1)])
    assert evaluate_prerequisites(("a", 1), entity, sim) == []


def test_readiness_matches_prerequisite_version():
    entity = topic("a", relationships=[requires("p", "OBJ-P", version=2)])
    sim = make_input(
        entities=[entity, topic("p", version=1), topic("p", version=2)],
        anchors=[("a", 1)],
        objective_states=[
            objective_state("OBJ-P", "p", "UNDERSTOOD", entity_version=1),
            objective_state("OBJ-P", "p", "ENCOUNTERED", entity_version=2),
        ],
    )
    evaluation = evaluate_prerequisites(("a", 1), entity, sim)[0]
    assert evaluation["state"] == UNSATISFIED


def test_readiness_other_version_evidence_is_unknown():
    entity = topic("a", relationships=[requires("p", "OBJ-P", version=2)])
    sim = make_input(
        entities=[entity, topic("p", version=1), topic("p", version=2)],
        anchors=[("a", 1)],
        objective_states=[objective_state("OBJ-P", "p", "UNDERSTOOD", entity_version=1)],
    )
    evaluation = evaluate_prerequisites(("a", 1), entity, sim)[0]
    assert evaluation["state"] == UNKNOWN


def test_readiness_rejects_ambiguous_full_key():
    entity = topic("a", relationships=[requires("p", "OBJ-P")])
    sim = make_input(
        entities=[entity, topic("p")],
        anchors=[("a", 1)],
        objective_states=[
            objective_state("OBJ-P", "p", "UNDERSTOOD"),
            objective_state("OBJ-P", "p", "ENCOUNTERED"),
        ],
    )
    with pytest.raises(SimulationInputError):
        evaluate_prerequisites(("a", 1), entity, sim)


def test_prerequisite_evaluations_sorted_by_objective_then_prerequisite():
    entity = topic(
        "a",
        relationships=[requires("p_b", "OBJ-A"), requires("p_a", "OBJ-Z")],
    )
    sim = make_input(
        entities=[entity, topic("p_a"), topic("p_b")],
        anchors=[("a", 1)],
        objective_states=[
            objective_state("OBJ-A", "p_b", "UNDERSTOOD"),
            objective_state("OBJ-Z", "p_a", "UNDERSTOOD"),
        ],
    )
    evaluations = evaluate_prerequisites(("a", 1), entity, sim)
    assert [(e["objective_id"], e["prerequisite_entity_id"]) for e in evaluations] == [
        ("OBJ-A", "p_b"),
        ("OBJ-Z", "p_a"),
    ]
