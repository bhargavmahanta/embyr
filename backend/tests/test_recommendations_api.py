"""Focused recommendation HTTP contract checks without a database service."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from app.api.deps import get_principal, get_session
from app.api.idempotency import IdempotencyReservation
from app.auth.principal import AuthenticatedPrincipal, ExternalIdentity
from app.config import Settings
from app.main import create_app
from app.recommendation.persistence import DecisionOutcome
from app.recommendation.ranking import ProductionRanking

USER_ID = UUID("22222222-2222-2222-2222-222222222222")
ISSUER = "https://embyr-dev.supabase.co/auth/v1"


class FakeSession:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def scalar(self, statement, params):
        return "Sample topic"


async def _session_dependency():
    yield FakeSession()


def _app():
    app = create_app(
        settings=Settings(database_url="", supabase_auth_issuer=ISSUER),
        session_factory=lambda: None,
    )
    app.dependency_overrides[get_session] = _session_dependency
    app.dependency_overrides[get_principal] = lambda: AuthenticatedPrincipal(
        user_id=USER_ID, identity=ExternalIdentity("SUPABASE", "subject")
    )
    return app


def _reservation(*, replay=False, body=None):
    return IdempotencyReservation(
        record_id=uuid4(), replay=replay, result_type=None,
        result_id=None, response_status=200 if body is not None else None,
        response_body=body,
    )


def test_next_requires_idempotency_key():
    with TestClient(_app()) as client:
        response = client.post("/api/v1/recommendations/next", json={"mode": "CREATE"})
    assert response.status_code == 400
    assert response.json()["code"] == "MISSING_IDEMPOTENCY_KEY"


def test_wrong_query_embedding_count_returns_controlled_503(monkeypatch):
    from types import SimpleNamespace
    import app.api.recommendations as api

    async def find(*args, **kwargs):
        return None

    async def assemble(*args, **kwargs):
        entity_id = str(uuid4())
        return SimpleNamespace(
            anchor_entities=({"entity_id": entity_id, "entity_version": 1},),
            embeddings=({"entity_id": entity_id},),
            entities=({"entity_id": entity_id, "entity_version": 1,
                       "title": "Anchor", "summary": "A topic"},),
        )

    class WrongCountEmbedder:
        async def embed_queries(self, texts):
            assert texts == ["TITLE: Anchor\nSUMMARY: A topic"]
            return []

    monkeypatch.setattr(api, "find_idempotent_result", find)
    monkeypatch.setattr(api, "assemble_production_snapshot", assemble)
    app = _app()
    app.state.query_embedder = WrongCountEmbedder()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/recommendations/next", json={"mode": "CONTINUE"},
            headers={"Idempotency-Key": "bad-vectors"},
        )
    assert response.status_code == 503
    assert response.json()["code"] == "RECOMMENDATION_GENERATION_UNAVAILABLE"


def test_empty_result_is_persisted_as_replayable_200(monkeypatch):
    import app.api.recommendations as api

    stored = []

    async def find(*args, **kwargs):
        return None

    async def assemble(*args, **kwargs):
        return object()

    async def generate(*args, **kwargs):
        return ProductionRanking(None, (), 0, 0, 0, "recommendation-profile/v1"), None

    async def reserve(*args, **kwargs):
        return _reservation()

    async def save(*args, **kwargs):
        stored.append(kwargs)

    async def current_user(*args, **kwargs):
        pass

    monkeypatch.setattr(api, "find_idempotent_result", find)
    monkeypatch.setattr(api, "assemble_production_snapshot", assemble)
    monkeypatch.setattr(api, "generate_recommendation", generate)
    monkeypatch.setattr(api, "reserve_idempotent_command", reserve)
    monkeypatch.setattr(api, "store_idempotent_result", save)
    monkeypatch.setattr(api, "set_current_user", current_user)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/recommendations/next", json={"mode": "CREATE"},
            headers={"Idempotency-Key": "empty-1"},
        )
    assert response.status_code == 200
    assert response.json() == {"recommendation": None}
    assert stored[0]["response_body"] == {"recommendation": None}
    assert stored[0]["result_type"] == "EMPTY_RECOMMENDATION"


def test_accept_returns_new_exploration_and_replay(monkeypatch):
    import app.api.recommendations as api

    recommendation_id, exploration_id, entity_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    recommendation = {
        "id": recommendation_id, "user_id": USER_ID, "entity_id": entity_id,
        "entity_version": 2, "challenge_id": None, "mode": "CONTINUE", "decision": None,
    }
    stored = []

    async def reserve(*args, **kwargs):
        return _reservation()

    async def load(*args, **kwargs):
        return recommendation

    async def decide(*args, **kwargs):
        return DecisionOutcome(recommendation_id, "ACCEPT", exploration_id, now)

    async def save(*args, **kwargs):
        stored.append(kwargs)

    monkeypatch.setattr(api, "reserve_idempotent_command", reserve)
    monkeypatch.setattr(api, "load_recommendation", load)
    monkeypatch.setattr(api, "persist_decision", decide)
    monkeypatch.setattr(api, "store_idempotent_result", save)
    with TestClient(_app()) as client:
        response = client.post(
            f"/api/v1/recommendations/{recommendation_id}/decision",
            json={"decision": "ACCEPT"}, headers={"Idempotency-Key": "accept-1"},
        )
    assert response.status_code == 200
    assert response.json()["id"] == str(exploration_id)
    assert response.json()["learning_intent"] == "RELATED_EXPLORATION"
    assert response.json()["started_at"] == now.isoformat()
    assert stored[0]["result_type"] == "EXPLORATION"

    async def replay(*args, **kwargs):
        return _reservation(replay=True, body=response.json())

    monkeypatch.setattr(api, "reserve_idempotent_command", replay)
    with TestClient(_app()) as client:
        repeated = client.post(
            f"/api/v1/recommendations/{recommendation_id}/decision",
            json={"decision": "ACCEPT"}, headers={"Idempotency-Key": "accept-1"},
        )
    assert repeated.json() == response.json()


def test_decision_cannot_address_other_users_recommendation(monkeypatch):
    import app.api.recommendations as api

    async def reserve(*args, **kwargs):
        return _reservation()

    async def load(*args, **kwargs):
        return None

    monkeypatch.setattr(api, "reserve_idempotent_command", reserve)
    monkeypatch.setattr(api, "load_recommendation", load)
    with TestClient(_app()) as client:
        response = client.post(
            f"/api/v1/recommendations/{uuid4()}/decision",
            json={"decision": "SKIP"}, headers={"Idempotency-Key": "skip-1"},
        )
    assert response.status_code == 404
    assert response.json()["code"] == "RECOMMENDATION_NOT_FOUND"


@pytest.mark.parametrize("stale", [False, True], ids=["current", "stale"])
def test_next_persists_one_selected_entity_with_reviewed_copy(monkeypatch, stale):
    import app.api.recommendations as api
    from types import SimpleNamespace

    recommendation_id, entity_id = uuid4(), uuid4()
    selected = {
        "candidate_id": "c1", "target_entity_id": str(entity_id),
        "target_entity_version": 3, "explanation_codes": ["EXPLICIT_INTEREST_MATCH"],
        "candidate_sources": ["EXPLICIT_INTEREST"], "final_rank": 1,
        "ordering_score": 0.5,
        "score_trace": {"component_scores": {}, "pre_rerank_score": 0.5},
        "rerank_trace": {"diversity_adjustment": 0.0},
    }
    stored = []

    async def find(*args, **kwargs):
        return None

    async def assemble(*args, **kwargs):
        return SimpleNamespace(entities=({
            "entity_id": str(entity_id), "entity_version": 3,
            "title": "Sample topic",
        },))

    async def generate(*args, **kwargs):
        return ProductionRanking(selected, (selected,), 1, 1, 0, "recommendation-profile/v1"), "COMFORT"

    async def reserve(*args, **kwargs):
        return _reservation()

    async def persist(*args, **kwargs):
        if stale:
            raise api.StaleRecommendationTarget("selected target changed")
        stored.append(kwargs)
        return recommendation_id

    async def save(*args, **kwargs):
        stored.append(kwargs)

    async def current_user(*args, **kwargs):
        pass

    monkeypatch.setattr(api, "find_idempotent_result", find)
    monkeypatch.setattr(api, "assemble_production_snapshot", assemble)
    monkeypatch.setattr(api, "generate_recommendation", generate)
    monkeypatch.setattr(api, "reserve_idempotent_command", reserve)
    monkeypatch.setattr(api, "persist_selected_recommendation", persist)
    monkeypatch.setattr(api, "store_idempotent_result", save)
    monkeypatch.setattr(api, "set_current_user", current_user)
    with TestClient(_app()) as client:
        response = client.post(
            "/api/v1/recommendations/next", json={"mode": "EXPLORE"},
            headers={"Idempotency-Key": "next-1"},
        )
    if stale:
        assert response.status_code == 503
        assert response.json()["code"] == "RECOMMENDATION_GENERATION_UNAVAILABLE"
        assert stored == []
        return
    assert response.status_code == 200
    assert response.json()["id"] == str(recommendation_id)
    assert response.json()["hook"] == "Something you asked to explore"
    assert response.json()["reason"] == "You said you wanted to explore more around this."
    assert response.json()["distance_band"] == "COMFORT"
    assert stored[0]["ranking_model_version"] == "recommendation-profile/v1"
    assert stored[1]["result_id"] == recommendation_id
