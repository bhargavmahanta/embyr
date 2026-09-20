"""Pipeline-level tests: unresolved targets, collect-all, ordering, scope."""

from __future__ import annotations

from research.recommendation.fixtures.semantic import SEED
from research.recommendation.simulator import generate_candidates
from research.recommendation.tests._candidate_helpers import (
    candidate_by_target,
    exploration,
    make_input,
    objective_state,
    preference,
    requires,
    topic,
    vector,
)

CANDIDATE_FIELDS = {
    "candidate_id",
    "target_entity_id",
    "target_entity_version",
    "target_entity_type",
    "source_paths",
    "prerequisite_evaluations",
    "eligibility_state",
    "exclusion_reasons",
    "feature_inputs",
}


def test_unresolved_semantic_target_is_invalid_target():
    sim = make_input(
        entities=[topic("a")],
        anchors=[("a", 1)],
        vectors=[vector("a", SEED), vector("ghost", [0.0, 1.0, 0.0, 0.0])],
    )
    candidate = candidate_by_target(generate_candidates(sim), "ghost")
    assert candidate["target_entity_type"] is None
    assert candidate["prerequisite_evaluations"] == []
    assert candidate["eligibility_state"] == "INELIGIBLE"
    assert candidate["exclusion_reasons"] == ["INVALID_TARGET"]


def test_unresolved_preference_target_is_invalid_target():
    sim = make_input(entities=[topic("a")], preferences=[preference("ghost", "MORE")])
    candidate = candidate_by_target(generate_candidates(sim), "ghost")
    assert candidate["target_entity_type"] is None
    assert candidate["exclusion_reasons"] == ["INVALID_TARGET"]


def test_unresolved_revisit_target_is_invalid_target():
    sim = make_input(entities=[topic("a")], explorations=[exploration("e1", "ghost", "COMPLETED")])
    candidate = candidate_by_target(generate_candidates(sim), "ghost")
    assert candidate["target_entity_type"] is None
    assert candidate["exclusion_reasons"] == ["INVALID_TARGET"]


def test_unresolved_not_interested_keeps_both_reasons_in_order():
    sim = make_input(entities=[topic("a")], preferences=[preference("ghost", "NOT_INTERESTED")])
    candidate = candidate_by_target(generate_candidates(sim), "ghost")
    assert candidate["exclusion_reasons"] == ["NOT_INTERESTED", "INVALID_TARGET"]


def test_unresolved_paused_keeps_both_reasons_in_order():
    sim = make_input(entities=[topic("a")], preferences=[preference("ghost", "PAUSED")])
    candidate = candidate_by_target(generate_candidates(sim), "ghost")
    assert candidate["exclusion_reasons"] == ["EXPLICITLY_PAUSED", "INVALID_TARGET"]


def test_resolved_target_type_is_exact_ontology_type():
    sim = make_input(
        entities=[topic("t", entity_type="CONCEPT")],
        preferences=[preference("t", "MORE")],
    )
    candidate = candidate_by_target(generate_candidates(sim), "t")
    assert candidate["target_entity_type"] == "CONCEPT"
    assert candidate["eligibility_state"] == "ELIGIBLE"


def test_collect_all_exclusions_on_resolved_target():
    sim = make_input(
        entities=[topic("t", relationships=[requires("p", "OBJ-P")]), topic("p")],
        preferences=[preference("t", "PAUSED")],
        objective_states=[objective_state("OBJ-P", "p", "ENCOUNTERED")],
    )
    candidate = candidate_by_target(generate_candidates(sim), "t")
    assert candidate["eligibility_state"] == "INELIGIBLE"
    assert candidate["exclusion_reasons"] == ["PREREQUISITE_UNMET", "EXPLICITLY_PAUSED"]


def test_output_is_sorted_by_candidate_id():
    sim = make_input(
        entities=[topic("a"), topic("b"), topic("c")],
        preferences=[preference("a", "MORE"), preference("b", "LESS"), preference("c", "PAUSED")],
    )
    candidates = generate_candidates(sim)
    ids = [candidate["candidate_id"] for candidate in candidates]
    assert ids == sorted(ids)


def test_candidate_shape_and_no_scoring_fields():
    sim = make_input(
        entities=[topic("a"), topic("b")],
        anchors=[("a", 1)],
        vectors=[vector("a", SEED), vector("b", [0.0, 1.0, 0.0, 0.0])],
    )
    candidates = generate_candidates(sim)
    assert candidates
    for candidate in candidates:
        assert set(candidate) == CANDIDATE_FIELDS
        for forbidden in (
            "pre_rerank_score",
            "ordering_score",
            "final_rank",
            "score_trace",
            "rerank_trace",
        ):
            assert forbidden not in candidate
