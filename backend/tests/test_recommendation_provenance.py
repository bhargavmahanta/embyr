"""Selected-result persistence keeps the reviewed reason and a compact trace."""
from __future__ import annotations
from uuid import uuid4

import pytest

from app.recommendation.persistence import (
    persist_decision, persist_selected_recommendation, selected_provenance,
)


def test_primary_copy_and_private_codes_are_selected_without_full_trace():
    selected = {
        "explanation_codes": ["EXPLICIT_INTEREST_MATCH", "GOOD_DIFFICULTY_FIT"],
        "candidate_sources": ["EXPLICIT_INTEREST", "SEMANTIC"],
        "final_rank": 1, "ordering_score": 0.42,
        "score_trace": {
            "component_scores": {"explicit_interest": 0.22},
            "pre_rerank_score": 0.40,
            "feature_values": {"raw": 1}, "configured_weights": {"secret": 1},
        },
        "rerank_trace": {
            "diversity_adjustment": 0.02,
            "diversity_dimensions": {"raw": "omit"},
        },
    }
    provenance = selected_provenance(selected)
    assert provenance.reason_code == "EXPLICIT_INTEREST_MATCH"
    assert provenance.presentation["hook"] == "Something you asked to explore"
    assert provenance.presentation["reason"] == "You said you wanted to explore more around this."
    assert provenance.presentation["explanation_codes"] == selected["explanation_codes"]
    assert provenance.score_components["component_scores"] == {"explicit_interest": 0.22}
    assert "feature_values" not in provenance.score_components
    assert "configured_weights" not in provenance.score_components
    assert "diversity_dimensions" not in provenance.score_components


def test_zero_codes_produces_null_copy_and_nullable_reason():
    selected = {
        "explanation_codes": [], "candidate_sources": [], "final_rank": 1,
        "ordering_score": 0.0,
        "score_trace": {"component_scores": {}, "pre_rerank_score": 0.0},
        "rerank_trace": {"diversity_adjustment": 0.0},
    }
    provenance = selected_provenance(selected)
    assert provenance.reason_code is None
    assert provenance.presentation["hook"] is None
    assert provenance.presentation["reason"] is None


class _Rows:
    def first(self):
        from uuid import uuid4
        return (uuid4(),)


class _Session:
    def __init__(self):
        self.writes = []

    async def execute(self, statement, params):
        self.writes.append((str(statement), params))
        return _Rows()


@pytest.mark.asyncio
async def test_persistence_accepts_reviewed_profile_and_rejects_false_identity():
    selected = {
        "target_entity_id": str(uuid4()), "target_entity_version": 2,
        "explanation_codes": [], "candidate_sources": ["GRAPH"],
        "final_rank": 3, "ordering_score": 0.4,
        "score_trace": {"component_scores": {}, "pre_rerank_score": 0.4},
        "rerank_trace": {"diversity_adjustment": 0.0},
    }
    session = _Session()
    with pytest.raises(ValueError, match="ranking profile"):
        await persist_selected_recommendation(
            session, user_id=uuid4(), selected=selected, mode="EXPLORE",
            distance_band="ADJACENT", ranking_model_version="fake-profile/v99",
        )
    assert session.writes == []
    await persist_selected_recommendation(
        session, user_id=uuid4(), selected=selected, mode="EXPLORE",
        distance_band="ADJACENT", ranking_model_version="recommendation-profile/v1",
    )
    assert session.writes[0][1]["ranking_model_version"] == "recommendation-profile/v1"


@pytest.mark.asyncio
@pytest.mark.parametrize("decision, mode, expected_intent, expected_events", [
    ("ACCEPT", "CONTINUE", "RELATED_EXPLORATION", ["RECOMMENDATION_ACCEPTED", "EXPLORATION_STARTED"]),
    ("SKIP", "REVISIT", "RETENTION_REVISIT", ["RECOMMENDATION_SKIPPED"]),
])
async def test_decision_writes_atomic_outcome_shape(decision, mode, expected_intent, expected_events):
    user_id, recommendation_id, entity_id, command_id = (uuid4() for _ in range(4))
    recommendation = {
        "id": recommendation_id, "user_id": user_id,
        "entity_id": entity_id, "entity_version": 3,
        "challenge_id": None, "mode": mode, "decision": None,
    }
    session = _Session()
    outcome = await persist_decision(
        session, user_id=user_id, recommendation=recommendation,
        decision=decision, command_id=command_id,
    )
    events = [params for sql, params in session.writes if "public.learning_events" in sql]
    explorations = [params for sql, params in session.writes if "public.explorations" in sql]
    assert [event["event_type"] for event in events] == expected_events
    assert [event["event_ordinal"] for event in events] == list(range(len(events)))
    assert all(event["command_id"] == command_id for event in events)
    assert all(event["learning_intent"] == expected_intent for event in events)
    assert len(explorations) == (1 if decision == "ACCEPT" else 0)
    assert outcome.exploration_id == (explorations[0]["id"] if explorations else None)
