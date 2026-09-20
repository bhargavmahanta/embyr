"""Determinism of #48 explanation derivation and RecommendationResult output."""

from __future__ import annotations

import copy

from research.recommendation.fixtures import SCENARIOS
from research.recommendation.fixtures.canonical import canonical_json
from research.recommendation.simulator import (
    build_recommendation_results,
    generate_candidates,
    rank_candidates,
)
from research.recommendation.tests._explanation_helpers import ranked_candidate


def _ranked(scenario_id: str) -> list[dict]:
    simulation_input = SCENARIOS[scenario_id]
    return rank_candidates(simulation_input, generate_candidates(simulation_input))


def test_repeated_build_is_byte_identical():
    ranked = _ranked("scn-X3-three-source-duplicate-001")
    assert canonical_json(build_recommendation_results(ranked)) == canonical_json(
        build_recommendation_results(ranked)
    )


def test_input_list_order_does_not_change_output():
    ranked = _ranked("scn-P-diversity-pressure-001")
    assert canonical_json(build_recommendation_results(ranked)) == canonical_json(
        build_recommendation_results(list(reversed(ranked)))
    )


def test_reason_code_order_does_not_change_explanation_codes():
    candidate = ranked_candidate(
        feature_values={"semantic_similarity": 0.5},
        score_reason_codes=["EXPLICIT_INFERRED_CONFLICT_SUPPRESSED", "OTHER_REASON"],
        rerank_reason_codes=["DOMAIN_COVERAGE_ADJUSTMENT", "OTHER_REASON"],
    )
    permuted = copy.deepcopy(candidate)
    permuted["score_trace"]["reason_codes"].reverse()
    permuted["rerank_trace"]["reason_codes"].reverse()

    first = build_recommendation_results([candidate])[0]["explanation_codes"]
    second = build_recommendation_results([permuted])[0]["explanation_codes"]
    assert first == second == [
        "SEMANTICALLY_RELATED",
        "DIVERSITY_ADJUSTMENT",
        "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED",
    ]


def test_explanation_codes_are_always_canonical_for_all_fixtures():
    from research.recommendation.simulator.explain import EXPLANATION_CODES

    index = {code: position for position, code in enumerate(EXPLANATION_CODES)}
    for scenario_id in SCENARIOS:
        for result in build_recommendation_results(_ranked(scenario_id)):
            codes = result["explanation_codes"]
            assert codes == sorted(codes, key=index.__getitem__), scenario_id
            assert len(codes) == len(set(codes)), scenario_id
