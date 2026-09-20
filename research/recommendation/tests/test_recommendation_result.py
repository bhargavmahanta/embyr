"""#48 RecommendationResult assembly: shape, immutability, ordering (#14.3)."""

from __future__ import annotations

import copy

from research.recommendation.simulator.explain import build_recommendation_results
from research.recommendation.tests._explanation_helpers import ranked_candidate

RESULT_FIELDS = {
    "candidate_id",
    "target_entity_id",
    "target_entity_version",
    "target_entity_type",
    "candidate_sources",
    "readiness_summary",
    "score_trace",
    "rerank_trace",
    "ordering_score",
    "deterministic_tiebreak_key",
    "final_rank",
    "explanation_codes",
}

FORBIDDEN_FIELDS = {
    "source_paths",
    "prerequisite_evaluations",
    "feature_inputs",
    "metrics",
    "top_k",
}


def test_empty_input_returns_empty_list():
    assert build_recommendation_results([]) == []


def test_one_input_returns_one_result_with_rank_preserved():
    candidate = ranked_candidate(final_rank=1)
    results = build_recommendation_results([candidate])
    assert len(results) == 1
    assert results[0]["final_rank"] == 1
    assert results[0]["candidate_id"] == candidate["candidate_id"]


def test_result_has_exact_frozen_shape():
    candidate = ranked_candidate(
        candidate_sources=["GRAPH", "SEMANTIC"],
        feature_values={"semantic_similarity": 0.5},
    )
    result = build_recommendation_results([candidate])[0]
    assert set(result) == RESULT_FIELDS
    assert not (set(result) & FORBIDDEN_FIELDS)
    assert result["explanation_codes"] == ["SEMANTICALLY_RELATED"]


def test_input_is_not_mutated_and_output_does_not_alias_input():
    candidate = ranked_candidate(
        candidate_sources=["SEMANTIC"],
        feature_values={"semantic_similarity": 0.5},
        score_reason_codes=["EXPLICIT_INFERRED_CONFLICT_SUPPRESSED"],
        rerank_reason_codes=["DOMAIN_COVERAGE_ADJUSTMENT"],
    )
    original = copy.deepcopy(candidate)

    result = build_recommendation_results([candidate])[0]

    assert candidate == original

    result["candidate_sources"].append("REVISIT")
    result["readiness_summary"]["state"] = "MUTATED"
    result["score_trace"]["feature_values"]["semantic_similarity"] = 999.0
    result["score_trace"]["reason_codes"].append("MUTATED")
    result["rerank_trace"]["reason_codes"].append("MUTATED")
    result["explanation_codes"].append("MUTATED")

    assert candidate == original


def test_extra_input_keys_are_not_copied():
    candidate = ranked_candidate(extra_keys={"future_field": {"unexpected": True}})
    result = build_recommendation_results([candidate])[0]
    assert "future_field" not in result
    assert set(result) == RESULT_FIELDS


def test_output_is_sorted_by_final_rank_and_values_unchanged():
    first = ranked_candidate(
        candidate_id="cand:1", target_entity_id="a", final_rank=1, ordering_score=3.0
    )
    second = ranked_candidate(
        candidate_id="cand:2", target_entity_id="b", final_rank=2, ordering_score=2.0
    )
    third = ranked_candidate(
        candidate_id="cand:3", target_entity_id="c", final_rank=3, ordering_score=1.0
    )

    results = build_recommendation_results([third, first, second])

    assert [result["final_rank"] for result in results] == [1, 2, 3]
    assert [result["candidate_id"] for result in results] == ["cand:1", "cand:2", "cand:3"]
    assert [result["ordering_score"] for result in results] == [3.0, 2.0, 1.0]
    assert [result["deterministic_tiebreak_key"] for result in results] == [
        first["deterministic_tiebreak_key"],
        second["deterministic_tiebreak_key"],
        third["deterministic_tiebreak_key"],
    ]
