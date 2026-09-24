"""Versioned, owner-selected initial retrieval and distance policy values."""
from __future__ import annotations

import json
from pathlib import Path

PROFILES = Path(__file__).resolve().parents[3] / "backend/app/recommendation/profiles"


def _load(name: str) -> dict:
    return json.loads((PROFILES / name).read_text(encoding="utf-8"))


def test_retrieval_v1_has_the_reviewed_identity_and_initial_bounds():
    policy = _load("recommendation-retrieval-v1.json")
    assert policy["policy_version"] == "recommendation-retrieval/v1"
    assert policy["embedding"] == {
        "provider": "voyage-ai", "model": "voyage-4", "dimension": 1024,
        "metric": "cosine", "document_input_type": "document",
        "query_input_type": "query", "query_input_version": "semantic-query-text/v1",
        "query_text_template": "TITLE: {canonical_title}\nSUMMARY: {canonical_summary}",
        "document_input_version": "ontology-entity/v1",
        "document_text_template": "TITLE: {canonical_title}\nSUMMARY: {canonical_summary}",
    }
    assert policy["semantic"] == {
        "search": "exact", "minimum_cosine_similarity": 0.55,
        "max_candidates": 40, "query_per_anchor": True,
    }
    assert policy["graph"] == {
        "relationship": "RELATED_TO", "bidirectional": True, "max_hops": 2,
        "max_candidates": 100,
        "tie_break": "shortest_hop_then_lexicographic_entity_version_path",
    }


def test_distance_band_v1_matches_reviewed_precedence_and_boundaries():
    policy = _load("distance-band-v1.json")
    assert policy["policy_version"] == "distance-band/v1"
    assert policy["precedence"] == ["COMFORT", "ADJACENT", "FRONTIER", "WILD"]
    assert set(policy["comfort_sources"]) == {
        "HISTORY_CONTINUATION", "REVISIT", "EXPLICIT_INTEREST"
    }
    assert policy["adjacent"] == {"graph_hops": 1, "minimum_cosine_similarity": 0.80}
    assert policy["frontier"] == {
        "graph_hops": 2, "minimum_cosine_similarity": 0.65,
        "maximum_cosine_similarity_exclusive": 0.80,
    }
    assert policy["wild"] == {
        "minimum_cosine_similarity": 0.55,
        "maximum_cosine_similarity_exclusive": 0.65,
    }
    assert policy["no_qualifying_signal"] == "ADJACENT"
    assert not any(policy[key] for key in (
        "uses_readiness", "uses_difficulty_fit", "uses_final_score_or_rank"
    ))
