"""Production input mapping preserves the M3 prerequisite and anchor semantics."""
from __future__ import annotations

from uuid import UUID

from app.recommendation.inputs import (
    QUERY_INPUT_VERSION,
    objective_state_entry,
    select_anchors,
    semantic_query_text,
)

A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
O = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def test_numeric_evidence_cannot_satisfy_a_hard_prerequisite():
    row = {
        "objective_id": O, "entity_id": A, "entity_version": 3,
        "categorical_state": None, "understanding_estimate": 1.0,
        "evaluation_confidence": 1.0, "support_required": False,
    }
    assert objective_state_entry(row) is None
    row["categorical_state"] = "UNDERSTOOD"
    assert objective_state_entry(row) == {
        "objective_id": str(O), "entity_id": str(A),
        "entity_version": 3, "state": "UNDERSTOOD",
    }


def test_anchors_use_active_explorations_and_more_preferences_only():
    available = {(A, 3), (B, 1)}
    explorations = [
        {"entity_id": A, "entity_version": 2, "status": "ACTIVE"},
        {"entity_id": B, "entity_version": 1, "status": "COMPLETED"},
    ]
    preferences = [
        {"entity_id": A, "entity_version": 3, "preference": "MORE"},
        {"entity_id": B, "entity_version": 1, "preference": "LESS"},
    ]
    assert select_anchors(available, explorations, preferences) == [
        {"entity_id": str(A), "entity_version": 3},
    ]


def test_semantic_query_is_per_anchor_title_then_summary():
    assert QUERY_INPUT_VERSION == "semantic-query-text/v1"
    assert semantic_query_text("A title", "A summary") == (
        "TITLE: A title\nSUMMARY: A summary"
    )
