"""Production retrieval preserves M3 source and hard-eligibility behavior."""
from __future__ import annotations

from uuid import UUID

from app.recommendation.retrieval import retrieve_candidates
from app.recommendation.snapshot import QUERIES, build_production_snapshot

USER = UUID("11111111-1111-1111-1111-111111111111")
A = UUID("22222222-2222-2222-2222-222222222222")
B = UUID("33333333-3333-3333-3333-333333333333")
OBJECTIVE = UUID("44444444-4444-4444-4444-444444444444")
VECTOR = [1.0] + [0.0] * 1023


def _snapshot(*, requires: bool = False, understood: bool = False):
    rows = {name: [] for name in QUERIES}
    rows["entities"] = [
        {"entity_id": key, "entity_version": 1, "current_version": 1,
         "entity_type": "TOPIC", "status": "REVIEWED", "title": str(key),
         "summary": "A topic", "difficulty_prior": 0.4,
         "estimated_effort_minutes": 15}
        for key in (A, B)
    ]
    rows["edges"] = [{
        "edge_id": UUID("55555555-5555-5555-5555-555555555555"),
        "source_entity_id": A, "source_entity_version": None,
        "target_entity_id": B, "target_entity_version": None,
        "relationship_type": "RELATED_TO", "objective_id": None,
        "requirement": None, "status": "ACTIVE",
    }]
    if requires:
        rows["edges"].append({
            "edge_id": UUID("66666666-6666-6666-6666-666666666666"),
            "source_entity_id": B, "source_entity_version": 1,
            "target_entity_id": A, "target_entity_version": 1,
            "relationship_type": "REQUIRES", "objective_id": OBJECTIVE,
            "requirement": "HARD", "status": "ACTIVE",
        })
        rows["objectives"] = [{
            "objective_id": OBJECTIVE, "entity_id": A, "entity_version": 1,
        }]
        rows["objective_states"] = [{
            "objective_id": OBJECTIVE, "entity_id": A, "entity_version": 1,
            "categorical_state": "UNDERSTOOD" if understood else None,
            "understanding_estimate": 1.0,
        }]
    rows["preferences"] = [{
        "entity_id": A, "entity_version": 1, "preference": "MORE", "version": 1,
    }]
    rows["explorations"] = [{
        "exploration_id": UUID("77777777-7777-7777-7777-777777777777"),
        "entity_id": A, "entity_version": 1, "status": "ACTIVE",
        "learning_intent": "DIRECT_INTEREST",
    }, {
        "exploration_id": UUID("88888888-8888-8888-8888-888888888888"),
        "entity_id": B, "entity_version": 1, "status": "COMPLETED",
        "learning_intent": "DIRECT_INTEREST", "completed_at": None,
    }]
    rows["embeddings"] = [{
        "entity_id": B, "entity_version": 1, "vector": str(VECTOR),
        "embedding_provider": "voyage-ai", "embedding_model": "voyage-4",
        "embedding_dimension": 1024, "embedding_input_version": "entity-document/v1",
        "embedding_input_type": "document",
    }]
    return build_production_snapshot(USER, rows)


def _sources(candidates):
    return {
        (candidate["target_entity_id"], source["source"])
        for candidate in candidates for source in candidate["source_paths"]
    }


def test_mode_filter_retains_only_permitted_m3_sources():
    snapshot = _snapshot()
    queries = {(str(A), 1): VECTOR}
    explore = retrieve_candidates(snapshot, queries, mode="EXPLORE")
    assert (str(A), "EXPLICIT_INTEREST") in _sources(explore)
    assert (str(B), "GRAPH") in _sources(explore)
    assert (str(B), "SEMANTIC") in _sources(explore)
    assert _sources(retrieve_candidates(snapshot, queries, mode="SURPRISE")) == {
        (str(B), "GRAPH"), (str(B), "SEMANTIC")
    }
    assert _sources(retrieve_candidates(snapshot, queries, mode="CONTINUE")) == {
        (str(B), "HISTORY_CONTINUATION")
    }
    assert _sources(retrieve_candidates(snapshot, queries, mode="REVISIT")) == {
        (str(B), "REVISIT")
    }
    assert retrieve_candidates(snapshot, queries, mode="CREATE") == []


def test_unknown_hard_prerequisite_excludes_despite_numeric_estimate():
    queries = {(str(A), 1): VECTOR}
    [candidate] = [
        item for item in retrieve_candidates(_snapshot(requires=True), queries, mode="SURPRISE")
        if item["target_entity_id"] == str(B)
    ]
    assert candidate["eligibility_state"] == "INELIGIBLE"
    assert candidate["exclusion_reasons"] == ["INSUFFICIENT_STATE"]
    [satisfied] = [
        item for item in retrieve_candidates(_snapshot(requires=True, understood=True), queries, mode="SURPRISE")
        if item["target_entity_id"] == str(B)
    ]
    assert satisfied["eligibility_state"] == "ELIGIBLE"


def test_graph_bound_keeps_nearest_target_before_two_hop_target():
    from app.recommendation.retrieval import load_retrieval_policy

    C = UUID("99999999-9999-9999-9999-999999999999")
    rows = {name: [] for name in QUERIES}
    rows["entities"] = [
        {"entity_id": key, "entity_version": 1, "current_version": 1,
         "entity_type": "TOPIC", "status": "REVIEWED", "title": str(key),
         "summary": "A topic", "difficulty_prior": 0.4,
         "estimated_effort_minutes": 15}
        for key in (A, B, C)
    ]
    rows["preferences"] = [{
        "entity_id": A, "entity_version": 1, "preference": "MORE", "version": 1,
    }]
    rows["edges"] = [
        {"source_entity_id": source, "source_entity_version": None,
         "target_entity_id": target, "target_entity_version": None,
         "relationship_type": "RELATED_TO", "status": "ACTIVE"}
        for source, target in ((A, B), (B, C))
    ]
    policy = load_retrieval_policy()
    policy["graph"]["max_candidates"] = 1
    candidates = retrieve_candidates(
        build_production_snapshot(USER, rows), {}, mode="SURPRISE", policy=policy
    )
    assert len(candidates) == 1
    assert candidates[0]["target_entity_id"] == str(B)
    assert candidates[0]["source_paths"][0]["provenance"]["hop_distance"] == 1
