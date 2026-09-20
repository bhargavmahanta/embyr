"""Pipeline-level tests for the #47 public ``rank_candidates`` API."""

from __future__ import annotations

import copy

from research.recommendation.simulator import generate_candidates, rank_candidates
from research.recommendation.tests._candidate_helpers import (
    make_input,
    preference,
    topic,
)

RESULT_KEYS = {
    "target_entity_id",
    "target_entity_version",
    "final_rank",
    "ordering_score",
    "candidate_sources",
    "readiness_summary",
    "score_trace",
    "rerank_trace",
    "deterministic_tiebreak_key",
}


def test_empty_eligible_set_returns_empty_list():
    sim = make_input(entities=[topic("a")], preferences=[preference("a", "PAUSED")])
    ranked = rank_candidates(sim, generate_candidates(sim))
    assert ranked == []


def test_mixed_input_returns_only_eligible():
    sim = make_input(
        entities=[topic("a"), topic("b")],
        preferences=[preference("a", "MORE"), preference("b", "NOT_INTERESTED")],
    )
    ranked = rank_candidates(sim, generate_candidates(sim))
    assert [entry["target_entity_id"] for entry in ranked] == ["a"]


def test_ranks_are_contiguous_from_one():
    sim = make_input(
        entities=[topic("a"), topic("b"), topic("c")],
        preferences=[
            preference("a", "MORE"),
            preference("b", "MORE"),
            preference("c", "MORE"),
        ],
        feature_weights={"explicit_interest": 1.0},
    )
    ranked = rank_candidates(sim, generate_candidates(sim))
    assert [entry["final_rank"] for entry in ranked] == [1, 2, 3]
    for entry in ranked:
        assert entry["rerank_trace"]["pre_rerank_rank"] in (1, 2, 3)
        assert set(entry) == RESULT_KEYS
        assert "explanation_codes" not in entry


def test_top_k_is_not_applied_by_47():
    sim = make_input(
        entities=[topic("a"), topic("b"), topic("c")],
        preferences=[
            preference("a", "MORE"),
            preference("b", "MORE"),
            preference("c", "MORE"),
        ],
        top_k=1,
        feature_weights={"explicit_interest": 1.0},
    )
    ranked = rank_candidates(sim, generate_candidates(sim))
    assert len(ranked) == 3
    assert [entry["final_rank"] for entry in ranked] == [1, 2, 3]


def test_rank_candidates_does_not_mutate_inputs():
    sim = make_input(
        entities=[topic("a"), topic("b")],
        preferences=[preference("a", "MORE"), preference("b", "LESS")],
        feature_weights={"explicit_interest": 1.0},
    )
    candidates = generate_candidates(sim)
    sim_before = copy.deepcopy(sim)
    candidates_before = copy.deepcopy(candidates)

    rank_candidates(sim, candidates)

    assert sim == sim_before
    assert candidates == candidates_before


def test_one_eligible_candidate_gets_rank_one():
    sim = make_input(
        entities=[topic("a")],
        preferences=[preference("a", "MORE")],
        feature_weights={"explicit_interest": 1.0},
    )
    ranked = rank_candidates(sim, generate_candidates(sim))
    assert len(ranked) == 1
    entry = ranked[0]
    assert entry["final_rank"] == 1
    assert entry["rerank_trace"]["pre_rerank_rank"] == 1
    assert entry["rerank_trace"]["post_rerank_rank"] == 1
    assert entry["rerank_trace"]["diversity_adjustment"] == 0.0


def test_ineligible_candidate_never_influences_diversity():
    sim = make_input(
        entities=[
            topic("a", domains=["d1"]),
            topic("b", domains=["d1"]),
            topic("c", domains=["d2"]),
        ],
        preferences=[
            preference("a", "MORE"),
            preference("b", "MORE"),
            preference("c", "PAUSED"),
        ],
        rerank={"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    candidates = generate_candidates(sim)
    with_ineligible = rank_candidates(sim, candidates)
    without_ineligible = rank_candidates(
        sim, [candidate for candidate in candidates if candidate["target_entity_id"] != "c"]
    )
    from research.recommendation.fixtures.canonical import canonical_json

    assert canonical_json(with_ineligible) == canonical_json(without_ineligible)
    assert "c" not in {entry["target_entity_id"] for entry in with_ineligible}


def test_ordering_score_equals_pre_plus_adjustment():
    sim = make_input(
        entities=[topic("a"), topic("b")],
        preferences=[preference("a", "MORE"), preference("b", "MORE")],
        feature_weights={"explicit_interest": 1.0},
        rerank={"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    for entry in rank_candidates(sim, generate_candidates(sim)):
        assert entry["ordering_score"] == (
            entry["score_trace"]["pre_rerank_score"]
            + entry["rerank_trace"]["diversity_adjustment"]
        )
