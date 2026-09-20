"""Aggregation and ScoreTrace tests for the frozen v3 additive scoring (#47)."""

from __future__ import annotations

import pytest

import research.recommendation.fixtures.builders as b
from research.recommendation.fixtures.semantic import NEAR, SEED
from research.recommendation.simulator import generate_candidates, rank_candidates
from research.recommendation.simulator.validation import SCORING_FEATURES
from research.recommendation.tests._candidate_helpers import (
    make_input,
    preference,
    topic,
    vector,
)


def _ranked(simulation_input: dict) -> dict[str, dict]:
    candidates = generate_candidates(simulation_input)
    return {
        entry["target_entity_id"]: entry
        for entry in rank_candidates(simulation_input, candidates)
    }


def _interest(entity_id: str, recent: float, long_term: float) -> dict:
    return b.interest_state(
        entity_id,
        1,
        recent_affinity=recent,
        long_term_affinity=long_term,
        user_initiated_strength=0.0,
        algorithm_exposure_strength=0.0,
    )


def test_empty_weights_give_zero_pre_score():
    sim = make_input(entities=[topic("a")], preferences=[preference("a", "MORE")])
    trace = _ranked(sim)["a"]["score_trace"]
    assert trace["pre_rerank_score"] == 0.0
    assert trace["feature_values"]["explicit_interest"] == 1.0
    assert trace["component_scores"]["explicit_interest"] == 0.0


def test_missing_key_has_zero_effective_weight():
    sim = make_input(
        entities=[topic("a")],
        preferences=[preference("a", "MORE")],
        feature_weights={"readiness": 1.0},
    )
    weights = _ranked(sim)["a"]["score_trace"]["configured_weights"]
    assert set(weights) == set(SCORING_FEATURES)
    assert weights["readiness"] == 1.0
    assert weights["explicit_interest"] == 0.0


def test_single_weighted_feature_and_full_component_map():
    sim = make_input(
        entities=[topic("a")],
        preferences=[preference("a", "MORE")],
        feature_weights={"explicit_interest": 2.0},
    )
    trace = _ranked(sim)["a"]["score_trace"]
    assert trace["component_scores"]["explicit_interest"] == 2.0
    assert trace["pre_rerank_score"] == 2.0
    assert set(trace["component_scores"]) == set(SCORING_FEATURES)
    for feature in SCORING_FEATURES:
        if feature != "explicit_interest":
            assert trace["component_scores"][feature] == 0.0


def test_additive_recomputation_exact():
    sim = make_input(
        entities=[topic("a")],
        preferences=[preference("a", "MORE")],
        feature_weights={"explicit_interest": 1.5, "revisit_value": 2.0},
    )
    trace = _ranked(sim)["a"]["score_trace"]
    assert trace["pre_rerank_score"] == pytest.approx(sum(trace["component_scores"].values()))


def test_negative_feature_with_nonnegative_weight():
    sim = make_input(
        entities=[topic("a")],
        preferences=[preference("a", "LESS")],
        feature_weights={"explicit_interest": 1.0},
    )
    trace = _ranked(sim)["a"]["score_trace"]
    assert trace["feature_values"]["explicit_interest"] == -1.0
    assert trace["component_scores"]["explicit_interest"] == -1.0
    assert trace["pre_rerank_score"] == -1.0


def test_aligned_signs_both_contribute():
    sim = make_input(
        entities=[topic("a")],
        preferences=[preference("a", "MORE")],
        interest_states=[_interest("a", 0.4, 0.6)],
        feature_weights={"explicit_interest": 1.0, "inferred_interest": 1.0},
    )
    trace = _ranked(sim)["a"]["score_trace"]
    assert trace["feature_values"]["inferred_interest"] == pytest.approx(0.5)
    assert trace["component_scores"]["inferred_interest"] == pytest.approx(0.5)
    assert trace["pre_rerank_score"] == pytest.approx(1.5)
    assert trace["reason_codes"] == []


def test_conflict_suppresses_inferred_component_but_keeps_raw():
    sim = make_input(
        entities=[topic("a")],
        preferences=[preference("a", "MORE")],
        interest_states=[_interest("a", -0.6, -0.4)],
        feature_weights={"explicit_interest": 1.0, "inferred_interest": 1.0},
    )
    trace = _ranked(sim)["a"]["score_trace"]
    assert trace["feature_values"]["inferred_interest"] == pytest.approx(-0.5)
    assert trace["component_scores"]["inferred_interest"] == 0.0
    assert trace["reason_codes"] == ["EXPLICIT_INFERRED_CONFLICT_SUPPRESSED"]
    assert trace["pre_rerank_score"] == pytest.approx(1.0)


def test_no_conflict_when_explicit_is_zero():
    sim = make_input(
        entities=[topic("seed"), topic("a")],
        anchors=[("seed", 1)],
        vectors=[vector("seed", SEED), vector("a", NEAR)],
        interest_states=[_interest("a", 0.4, 0.6)],
        feature_weights={"inferred_interest": 1.0},
    )
    trace = _ranked(sim)["a"]["score_trace"]
    assert trace["feature_values"]["explicit_interest"] == 0.0
    assert trace["component_scores"]["inferred_interest"] == pytest.approx(0.5)
    assert trace["reason_codes"] == []


def test_weights_are_not_normalized():
    sim = make_input(
        entities=[topic("a")],
        preferences=[preference("a", "MORE")],
        feature_weights={"explicit_interest": 3.0},
    )
    trace = _ranked(sim)["a"]["score_trace"]
    assert trace["configured_weights"]["explicit_interest"] == 3.0
    assert trace["pre_rerank_score"] == 3.0
