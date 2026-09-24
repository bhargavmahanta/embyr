"""Production retrieval preserves M3 source and hard-eligibility behavior."""
from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from app.recommendation.retrieval import retrieve_candidates
from app.recommendation.inputs import ontology_document_text
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
        "embedding_dimension": 1024, "embedding_input_version": "ontology-entity/v1",
        "embedding_input_type": "document",
        "embedding_input_fingerprint": "sha256:" + hashlib.sha256(
            ontology_document_text(str(B), "A topic").encode("utf-8")
        ).hexdigest(),
    }]
    return build_production_snapshot(USER, rows)


def _sources(candidates):
    return {
        (candidate["target_entity_id"], source["source"])
        for candidate in candidates for source in candidate["source_paths"]
    }


def test_retrieval_collects_all_five_sources_without_a_mode_parameter():
    snapshot = _snapshot()
    queries = {(str(A), 1): VECTOR}
    candidates = retrieve_candidates(snapshot, queries)
    assert _sources(candidates) == {
        (str(A), "EXPLICIT_INTEREST"),
        (str(B), "GRAPH"), (str(B), "SEMANTIC"),
        (str(B), "HISTORY_CONTINUATION"), (str(B), "REVISIT"),
    }
    assert len(candidates) == 2


def test_unknown_hard_prerequisite_excludes_despite_numeric_estimate():
    queries = {(str(A), 1): VECTOR}
    [candidate] = [
        item for item in retrieve_candidates(_snapshot(requires=True), queries)
        if item["target_entity_id"] == str(B)
    ]
    assert candidate["eligibility_state"] == "INELIGIBLE"
    assert candidate["exclusion_reasons"] == ["INSUFFICIENT_STATE"]
    [satisfied] = [
        item for item in retrieve_candidates(_snapshot(requires=True, understood=True), queries)
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
        build_production_snapshot(USER, rows), {}, policy=policy
    )
    graph = [item for item in candidates if any(
        path["source"] == "GRAPH" for path in item["source_paths"]
    )]
    assert len(graph) == 1
    assert graph[0]["target_entity_id"] == str(B)
    assert next(path for path in graph[0]["source_paths"]
                if path["source"] == "GRAPH")["provenance"]["hop_distance"] == 1


def _entity_row(entity_id, *, version=1, difficulty=0.4):
    return {
        "entity_id": entity_id, "entity_version": version,
        "current_version": version, "entity_type": "TOPIC",
        "status": "REVIEWED", "title": str(entity_id), "summary": "A topic",
        "difficulty_prior": difficulty, "estimated_effort_minutes": 15,
    }


def _embedding_row(entity_id, vector=VECTOR):
    return {
        "entity_id": entity_id, "entity_version": 1, "vector": str(vector),
        "embedding_provider": "voyage-ai", "embedding_model": "voyage-4",
        "embedding_dimension": 1024, "embedding_input_version": "ontology-entity/v1",
        "embedding_input_type": "document",
        "embedding_input_fingerprint": "sha256:" + hashlib.sha256(
            ontology_document_text(str(entity_id), "A topic").encode("utf-8")
        ).hexdigest(),
    }


def test_semantic_threshold_global_cap_and_multi_anchor_provenance():
    from app.recommendation.retrieval import load_retrieval_policy

    targets = [UUID(int=1000 + index) for index in range(41)]
    rows = {name: [] for name in QUERIES}
    rows["entities"] = [_entity_row(key) for key in (A, B, *targets)]
    rows["preferences"] = [
        {"entity_id": key, "entity_version": 1, "preference": "MORE", "version": 1}
        for key in (A, B)
    ]
    rows["embeddings"] = [_embedding_row(key) for key in targets]
    snapshot = build_production_snapshot(USER, rows)
    policy = load_retrieval_policy()
    candidates = retrieve_candidates(
        snapshot, {(str(A), 1): VECTOR, (str(B), 1): VECTOR}, policy=policy,
    )
    semantic = [item for item in candidates if any(
        path["source"] == "SEMANTIC" for path in item["source_paths"]
    )]
    assert len(semantic) == 40
    assert {item["target_entity_id"] for item in semantic} == {
        str(key) for key in targets[:40]
    }
    first_candidate = next(item for item in semantic if item["target_entity_id"] == str(targets[0]))
    similarities = [path["provenance"]["cosine_similarity"]
                    for path in first_candidate["source_paths"]
                    if path["source"] == "SEMANTIC"]
    assert len(similarities) == 2
    assert similarities == [1.0, 1.0]
    assert len({item["target_entity_id"] for item in candidates}) == len(candidates)


def test_semantic_rejects_just_below_threshold_and_keeps_strongest_path():
    import math

    C, D, E = UUID(int=4000), UUID(int=4001), UUID(int=4002)
    rows = {name: [] for name in QUERIES}
    rows["entities"] = [_entity_row(key) for key in (A, B, C, D, E)]
    rows["preferences"] = [
        {"entity_id": key, "entity_version": 1, "preference": "MORE", "version": 1}
        for key in (A, B)
    ]
    rows["embeddings"] = [
        _embedding_row(C, VECTOR),
        _embedding_row(D, [0.54, -math.sqrt(1 - 0.54**2)] + [0.0] * 1022),
        _embedding_row(E, [0.55, math.sqrt(1 - 0.55**2)] + [0.0] * 1022),
    ]
    candidates = retrieve_candidates(build_production_snapshot(USER, rows), {
        (str(A), 1): VECTOR,
        (str(B), 1): [0.8, 0.6] + [0.0] * 1022,
    })
    semantic = {item["target_entity_id"]: [path for path in item["source_paths"]
                if path["source"] == "SEMANTIC"] for item in candidates}
    assert len(semantic[str(C)]) == 2
    assert max(path["provenance"]["cosine_similarity"] for path in semantic[str(C)]) == 1.0
    assert str(D) not in semantic
    assert any(path["provenance"]["anchor_entity_id"] == str(A)
               and path["provenance"]["cosine_similarity"] >= 0.55
               for path in semantic[str(E)])


def test_graph_two_hop_bound_is_global_after_anchor_merge():
    from app.recommendation.retrieval import load_retrieval_policy

    C, D, E = (UUID(int=value) for value in (5000, 5001, 5002))
    rows = {name: [] for name in QUERIES}
    rows["entities"] = [_entity_row(key) for key in (A, B, C, D, E)]
    rows["preferences"] = [
        {"entity_id": key, "entity_version": 1, "preference": "MORE", "version": 1}
        for key in (A, B)
    ]
    rows["edges"] = [
        {"source_entity_id": source, "source_entity_version": None,
         "target_entity_id": target, "target_entity_version": None,
         "relationship_type": "RELATED_TO", "status": "ACTIVE"}
        for source, target in ((A, C), (B, C), (C, D), (D, E))
    ]
    policy = load_retrieval_policy()
    policy["graph"]["max_candidates"] = 2
    candidates = retrieve_candidates(build_production_snapshot(USER, rows), {}, policy=policy)
    graph = {item["target_entity_id"]: [path for path in item["source_paths"]
             if path["source"] == "GRAPH"] for item in candidates}
    assert set(key for key, paths in graph.items() if paths) == {str(C), str(D)}
    assert len(graph[str(C)]) == 2
    assert {path["provenance"]["hop_distance"] for path in graph[str(C)]} == {1}
    assert {path["provenance"]["hop_distance"] for path in graph[str(D)]} == {2}


def test_missing_embeddings_and_explicit_hard_exclusions():
    from dataclasses import replace

    original = _snapshot()
    for preference, reason in (("PAUSED", "EXPLICITLY_PAUSED"),
                               ("NOT_INTERESTED", "NOT_INTERESTED")):
        snapshot = replace(
            original, embeddings=(),
            explicit_preferences=({**original.explicit_preferences[0],
                                   "preference": preference},),
        )
        candidates = retrieve_candidates(snapshot, {(str(A), 1): VECTOR})
        assert not any(source == "SEMANTIC" for _, source in _sources(candidates))
        target = next(item for item in candidates if item["target_entity_id"] == str(A))
        assert (str(A), "EXPLICIT_INTEREST") in _sources(candidates)
        assert reason in target["exclusion_reasons"]


def test_superseded_completed_revisit_does_not_nominate_or_upgrade():
    from dataclasses import replace

    snapshot = _snapshot()
    entities = tuple({**row, "entity_version": 2, "current_version": 2}
                     if row["entity_id"] == str(B) else row for row in snapshot.entities)
    snapshot = replace(snapshot, entities=entities)
    candidates = retrieve_candidates(snapshot, {})
    assert all(source != "REVISIT" for _, source in _sources(candidates))
    assert all(not (item["target_entity_id"] == str(B) and
                    item["target_entity_version"] == 1) for item in candidates)


def test_null_difficulty_keeps_current_target_resolved():
    from dataclasses import replace

    snapshot = _snapshot()
    snapshot = replace(snapshot, entities=tuple(
        {**row, "difficulty_prior": None} if row["entity_id"] == str(B) else row
        for row in snapshot.entities
    ))
    target = next(item for item in retrieve_candidates(snapshot, {})
                  if item["target_entity_id"] == str(B))
    assert target["target_entity_type"] == "TOPIC"
    assert "INVALID_TARGET" not in target["exclusion_reasons"]
    assert target["feature_inputs"]["difficulty_prior"] is None


def test_historical_source_requires_is_ignored_for_current_candidates():
    from dataclasses import replace

    snapshot = _snapshot()
    entities = tuple({**row, "entity_version": 2, "current_version": 2}
                     if row["entity_id"] == str(B) else row for row in snapshot.entities)
    old_edge = {
        "source_entity_id": str(B), "source_entity_version": 1,
        "target_entity_id": str(A), "target_entity_version": 1,
        "relationship_type": "REQUIRES", "objective_id": str(OBJECTIVE),
        "requirement": "HARD", "status": "ACTIVE",
    }
    snapshot = replace(snapshot, entities=entities, edges=(*snapshot.edges, old_edge))
    candidates = retrieve_candidates(snapshot, {})
    assert any(item["target_entity_id"] == str(B) and
               item["target_entity_version"] == 2 for item in candidates)


def test_current_source_requires_with_unresolved_target_fails_closed():
    from dataclasses import replace

    snapshot = _snapshot()
    malformed_edge = {
        "source_entity_id": str(B), "source_entity_version": 1,
        "target_entity_id": str(A), "target_entity_version": None,
        "relationship_type": "REQUIRES", "objective_id": str(OBJECTIVE),
        "requirement": "HARD", "status": "ACTIVE",
    }
    snapshot = replace(snapshot, edges=(*snapshot.edges, malformed_edge))

    with pytest.raises(ValueError, match="lacks target version"):
        retrieve_candidates(snapshot, {})
