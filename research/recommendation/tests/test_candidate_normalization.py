"""Unit tests for candidate normalization and provenance merging."""

from __future__ import annotations

from research.recommendation.simulator.identity import candidate_id, canonical_provenance
from research.recommendation.simulator.normalize import normalize_nominations
from research.recommendation.simulator.sources import CANDIDATE_SOURCES


def _nomination(target_id, source, provenance, version=1):
    return {
        "target_entity_id": target_id,
        "target_entity_version": version,
        "source": source,
        "provenance": provenance,
    }


def test_same_target_merges_into_one_candidate():
    candidates = normalize_nominations(
        [
            _nomination("t", "GRAPH", {"anchor_entity_id": "a", "anchor_entity_version": 1, "hop_distance": 1, "canonical_path": []}),
            _nomination("t", "SEMANTIC", {"anchor_entity_id": "a", "anchor_entity_version": 1, "cosine_similarity": 0.5}),
        ]
    )
    assert len(candidates) == 1
    assert [path["source"] for path in candidates[0]["source_paths"]] == ["GRAPH", "SEMANTIC"]


def test_three_source_target_merges():
    candidates = normalize_nominations(
        [
            _nomination("t", "EXPLICIT_INTEREST", {"preference": "MORE"}),
            _nomination("t", "GRAPH", {"anchor_entity_id": "a"}),
            _nomination("t", "SEMANTIC", {"anchor_entity_id": "a", "cosine_similarity": 0.5}),
        ]
    )
    assert [path["source"] for path in candidates[0]["source_paths"]] == [
        "GRAPH",
        "SEMANTIC",
        "EXPLICIT_INTEREST",
    ]


def test_identical_path_deduplicated():
    nomination = _nomination("t", "GRAPH", {"anchor_entity_id": "a", "hop_distance": 1})
    candidates = normalize_nominations([nomination, dict(nomination)])
    assert len(candidates[0]["source_paths"]) == 1


def test_different_paths_same_source_retained():
    candidates = normalize_nominations(
        [
            _nomination("t", "GRAPH", {"anchor_entity_id": "a1", "hop_distance": 1}),
            _nomination("t", "GRAPH", {"anchor_entity_id": "a2", "hop_distance": 1}),
        ]
    )
    assert len(candidates[0]["source_paths"]) == 2


def test_frozen_source_order_and_canonical_provenance_order():
    candidates = normalize_nominations(
        [
            _nomination("t", "REVISIT", {"exploration_id": "e1"}),
            _nomination("t", "SEMANTIC", {"anchor_entity_id": "a2"}),
            _nomination("t", "SEMANTIC", {"anchor_entity_id": "a1"}),
            _nomination("t", "GRAPH", {"anchor_entity_id": "a"}),
        ]
    )
    sources = [path["source"] for path in candidates[0]["source_paths"]]
    assert sources == ["GRAPH", "SEMANTIC", "SEMANTIC", "REVISIT"]
    semantic_anchors = [
        path["provenance"]["anchor_entity_id"]
        for path in candidates[0]["source_paths"]
        if path["source"] == "SEMANTIC"
    ]
    assert semantic_anchors == sorted(semantic_anchors, key=lambda value: canonical_provenance({"anchor_entity_id": value}))


def test_one_candidate_per_logical_target():
    candidates = normalize_nominations(
        [
            _nomination("t", "GRAPH", {"anchor_entity_id": "a"}),
            _nomination("t", "SEMANTIC", {"anchor_entity_id": "a", "cosine_similarity": 0.1}),
            _nomination("u", "SEMANTIC", {"anchor_entity_id": "a", "cosine_similarity": 0.2}),
        ]
    )
    assert {candidate["target_entity_id"] for candidate in candidates} == {"t", "u"}
    assert len(candidates) == 2


def test_candidate_id_deterministic_and_type_free():
    first = candidate_id("t", 1)
    second = candidate_id("t", 1)
    assert isinstance(first, str)
    assert first == second
    assert first != candidate_id("t", 2)
    assert first != candidate_id("u", 1)
    # No target_entity_type participates in identity or candidate_id derivation.
    candidates = normalize_nominations([_nomination("t", "GRAPH", {"anchor_entity_id": "a"})])
    assert "target_entity_type" not in candidates[0]
    assert candidates[0]["candidate_id"] == first


def test_source_order_constant_used_for_sorting():
    assert CANDIDATE_SOURCES.index("GRAPH") < CANDIDATE_SOURCES.index("SEMANTIC") < CANDIDATE_SOURCES.index("EXPLICIT_INTEREST")
