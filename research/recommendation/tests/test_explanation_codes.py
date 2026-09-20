"""Unit tests for deterministic v4 explanation-code derivation (#48, §15.1)."""

from __future__ import annotations

from research.recommendation.fixtures.builders import EXPLANATION_CODES as FIXTURE_CODES
from research.recommendation.simulator.explain import (
    EXPLANATION_CODES,
    build_recommendation_results,
)
from research.recommendation.tests._explanation_helpers import ranked_candidate

EXPECTED_VOCABULARY = (
    "EXPLICIT_INTEREST_MATCH",
    "RELATED_TO_RECENT_EXPLORATION",
    "PREREQUISITES_SATISFIED",
    "GOOD_DIFFICULTY_FIT",
    "SEMANTICALLY_RELATED",
    "REVISIT_OPPORTUNITY",
    "DIVERSITY_ADJUSTMENT",
    "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED",
)


def _codes(**overrides) -> list[str]:
    return build_recommendation_results([ranked_candidate(**overrides)])[0][
        "explanation_codes"
    ]


def test_vocabulary_is_exactly_eight_and_canonically_ordered():
    assert EXPLANATION_CODES == EXPECTED_VOCABULARY
    assert len(EXPLANATION_CODES) == 8
    # Runtime authority and fixture oracle must not drift.
    assert EXPLANATION_CODES == FIXTURE_CODES


def test_explicit_interest_match_only_for_positive():
    assert _codes(feature_values={"explicit_interest": 1.0}) == ["EXPLICIT_INTEREST_MATCH"]
    assert _codes(feature_values={"explicit_interest": 0.0}) == []
    assert _codes(feature_values={"explicit_interest": -1.0}) == []


def test_history_continuation_maps_to_related_to_recent_exploration():
    assert _codes(candidate_sources=["HISTORY_CONTINUATION"]) == [
        "RELATED_TO_RECENT_EXPLORATION"
    ]


def test_prerequisites_satisfied_requires_nonzero_hard_prerequisites():
    assert _codes(
        hard_prerequisites_total=2, hard_prerequisites_satisfied=2
    ) == ["PREREQUISITES_SATISFIED"]
    # Vacuous 0/0 SATISFIED hard-gate summary must not emit.
    assert _codes(hard_prerequisites_total=0, hard_prerequisites_satisfied=0) == []
    # Not all HARD satisfied must not emit (defensive; invalid #47 output).
    assert _codes(
        hard_prerequisites_total=2, hard_prerequisites_satisfied=1
    ) == []


def test_good_difficulty_fit_is_inclusive_at_point_eight():
    assert _codes(feature_values={"difficulty_fit": 1.0}) == ["GOOD_DIFFICULTY_FIT"]
    assert _codes(feature_values={"difficulty_fit": 0.8}) == ["GOOD_DIFFICULTY_FIT"]
    assert _codes(feature_values={"difficulty_fit": 0.799}) == []
    assert _codes(feature_values={"difficulty_fit": 0.6}) == []


def test_semantically_related_only_for_positive_similarity():
    assert _codes(feature_values={"semantic_similarity": 0.5}) == ["SEMANTICALLY_RELATED"]
    assert _codes(feature_values={"semantic_similarity": 0.0}) == []
    assert _codes(feature_values={"semantic_similarity": -0.9}) == []


def test_revisit_maps_to_revisit_opportunity():
    assert _codes(candidate_sources=["REVISIT"]) == ["REVISIT_OPPORTUNITY"]


def test_diversity_adjustment_maps_from_machine_reason():
    assert _codes(rerank_reason_codes=["DOMAIN_COVERAGE_ADJUSTMENT"]) == [
        "DIVERSITY_ADJUSTMENT"
    ]
    # Numeric data alone is not the authority.
    assert _codes(diversity_adjustment=0.5) == []


def test_override_maps_from_machine_reason():
    assert _codes(score_reason_codes=["EXPLICIT_INFERRED_CONFLICT_SUPPRESSED"]) == [
        "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED"
    ]
    # Raw conflicting-looking signs alone are not the authority.
    assert _codes(
        feature_values={"explicit_interest": 1.0, "inferred_interest": -0.5}
    ) == ["EXPLICIT_INTEREST_MATCH"]


def test_all_eight_codes_emitted_once_in_canonical_order():
    candidate = ranked_candidate(
        candidate_sources=["GRAPH", "HISTORY_CONTINUATION", "REVISIT"],
        hard_prerequisites_total=1,
        hard_prerequisites_satisfied=1,
        feature_values={
            "explicit_interest": 1.0,
            "inferred_interest": -0.5,
            "difficulty_fit": 1.0,
            "semantic_similarity": 0.9,
        },
        score_reason_codes=["EXPLICIT_INFERRED_CONFLICT_SUPPRESSED"],
        rerank_reason_codes=["DOMAIN_COVERAGE_ADJUSTMENT"],
    )
    codes = build_recommendation_results([candidate])[0]["explanation_codes"]
    assert codes == list(EXPECTED_VOCABULARY)
    assert len(codes) == len(set(codes))


def test_zero_code_candidate_is_valid():
    candidate = ranked_candidate(
        candidate_sources=["GRAPH"],
        hard_prerequisites_total=0,
        feature_values={"difficulty_fit": 0.5},
    )
    assert build_recommendation_results([candidate])[0]["explanation_codes"] == []


def test_contextual_semantics_ignore_zero_configured_weight():
    candidate = ranked_candidate(
        feature_values={"semantic_similarity": 0.5, "explicit_interest": 1.0},
        configured_weights={"semantic_similarity": 0.0, "explicit_interest": 0.0},
        component_scores={"semantic_similarity": 0.0, "explicit_interest": 0.0},
    )
    assert build_recommendation_results([candidate])[0]["explanation_codes"] == [
        "EXPLICIT_INTEREST_MATCH",
        "SEMANTICALLY_RELATED",
    ]


def test_prerequisite_summary_authority_over_readiness_feature():
    # readiness feature 1.0 but zero HARD prerequisites must not emit.
    assert _codes(
        feature_values={"readiness": 1.0},
        hard_prerequisites_total=0,
        hard_prerequisites_satisfied=0,
    ) == []


def test_no_graph_or_inferred_interest_codes_exist():
    candidate = ranked_candidate(
        candidate_sources=["GRAPH"],
        feature_values={"graph_proximity": 1.0, "inferred_interest": 0.9},
    )
    assert build_recommendation_results([candidate])[0]["explanation_codes"] == []
