"""Unit tests for hard eligibility, exclusion collection, and feature inputs."""

from __future__ import annotations

from research.recommendation.simulator.eligibility import (
    EXCLUSION_ORDER,
    build_candidate,
    build_feature_inputs,
    collect_exclusion_reasons,
)
from research.recommendation.tests._candidate_helpers import topic


def _evaluation(requirement, state):
    return {
        "objective_id": "OBJ-P",
        "prerequisite_entity_id": "p",
        "requirement": requirement,
        "evidence_summary": {},
        "state": state,
        "reason_codes": [],
    }


def _normalized():
    return {
        "candidate_id": "cand:test",
        "target_entity_id": "t",
        "target_entity_version": 1,
        "source_paths": [{"source": "SEMANTIC", "provenance": {}}],
    }


def test_paused_and_not_interested_hard_exclude():
    assert collect_exclusion_reasons(topic("t"), "PAUSED", []) == ["EXPLICITLY_PAUSED"]
    assert collect_exclusion_reasons(topic("t"), "NOT_INTERESTED", []) == ["NOT_INTERESTED"]


def test_more_less_neutral_do_not_exclude():
    for preference in ("MORE", "LESS", "NEUTRAL", None):
        assert collect_exclusion_reasons(topic("t"), preference, []) == []


def test_hard_prerequisite_states():
    assert collect_exclusion_reasons(topic("t"), None, [_evaluation("HARD", "UNSATISFIED")]) == [
        "PREREQUISITE_UNMET"
    ]
    assert collect_exclusion_reasons(topic("t"), None, [_evaluation("HARD", "UNKNOWN")]) == [
        "INSUFFICIENT_STATE"
    ]
    assert collect_exclusion_reasons(topic("t"), None, [_evaluation("HARD", "SATISFIED")]) == []


def test_soft_prerequisites_never_exclude():
    for state in ("UNSATISFIED", "UNKNOWN", "SATISFIED"):
        assert collect_exclusion_reasons(topic("t"), None, [_evaluation("SOFT", state)]) == []


def test_unresolved_target_is_invalid_target():
    assert collect_exclusion_reasons(None, None, []) == ["INVALID_TARGET"]


def test_collect_all_exclusions_in_frozen_order():
    reasons = collect_exclusion_reasons(
        topic("t"), "PAUSED", [_evaluation("HARD", "UNSATISFIED")]
    )
    assert reasons == ["PREREQUISITE_UNMET", "EXPLICITLY_PAUSED"]


def test_collect_all_deduplicates():
    reasons = collect_exclusion_reasons(
        topic("t"),
        "NOT_INTERESTED",
        [_evaluation("HARD", "UNKNOWN"), _evaluation("HARD", "UNKNOWN")],
    )
    assert reasons == ["NOT_INTERESTED", "INSUFFICIENT_STATE"]


def test_exclusion_order_constant_is_frozen():
    assert EXCLUSION_ORDER == (
        "PREREQUISITE_UNMET",
        "EXPLICITLY_PAUSED",
        "NOT_INTERESTED",
        "INVALID_TARGET",
        "INSUFFICIENT_STATE",
    )


def test_build_candidate_resolved_and_unresolved():
    resolved = build_candidate(_normalized(), topic("t", entity_type="SKILL"), None, [])
    assert resolved["target_entity_type"] == "SKILL"
    assert resolved["eligibility_state"] == "ELIGIBLE"
    assert resolved["exclusion_reasons"] == []

    unresolved = build_candidate(_normalized(), None, None, [])
    assert unresolved["target_entity_type"] is None
    assert unresolved["eligibility_state"] == "INELIGIBLE"
    assert unresolved["exclusion_reasons"] == ["INVALID_TARGET"]
    assert unresolved["prerequisite_evaluations"] == []


def test_feature_inputs_are_raw_only():
    entity = topic("t", difficulty=0.3)
    inputs = build_feature_inputs(entity, "MORE", [_evaluation("HARD", "SATISFIED"), _evaluation("SOFT", "UNKNOWN")])
    assert inputs["difficulty_prior"] == 0.3
    assert inputs["explicit_preference"] == "MORE"
    assert inputs["hard_prerequisite_count"] == 1
    assert inputs["soft_prerequisite_count"] == 1
    assert inputs["satisfied_prerequisite_count"] == 1
    assert inputs["unknown_prerequisite_count"] == 1
    for forbidden in (
        "readiness",
        "difficulty_fit",
        "explicit_interest",
        "inferred_interest",
        "graph_proximity",
        "semantic_similarity",
        "continuation_value",
        "revisit_value",
        "novelty",
        "diversity_context",
    ):
        assert forbidden not in inputs
