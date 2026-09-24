"""Small production snapshot through retrieval, ranking, and API band selection."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.recommendation.service import generate_recommendation
from app.recommendation.snapshot import QUERIES, build_production_snapshot


@pytest.mark.asyncio
async def test_more_preference_reaches_one_entity_recommendation_and_create_is_empty():
    user_id, entity_id = uuid4(), uuid4()
    rows = {name: [] for name in QUERIES}
    rows["entities"] = [{
        "entity_id": entity_id, "canonical_key": "test-topic",
        "entity_type": "TOPIC", "status": "REVIEWED", "current_version": 1,
        "entity_version": 1, "title": "Curiosity topic", "summary": "A topic summary",
        "difficulty_prior": 0.5, "estimated_effort_minutes": 15,
    }]
    rows["preferences"] = [{
        "entity_id": entity_id, "entity_version": 1,
        "preference": "MORE", "version": 1,
    }]
    snapshot = build_production_snapshot(user_id, rows)
    assert snapshot.anchor_entities == ({"entity_id": str(entity_id), "entity_version": 1},)
    ranking, band = await generate_recommendation(snapshot, mode="EXPLORE", embedder=None)
    assert ranking.selected is not None
    assert ranking.selected["target_entity_id"] == str(entity_id)
    assert ranking.selected["candidate_sources"] == ["EXPLICIT_INTEREST"]
    assert band == "COMFORT"
    empty, empty_band = await generate_recommendation(snapshot, mode="CREATE", embedder=None)
    assert empty.selected is None and empty_band is None
