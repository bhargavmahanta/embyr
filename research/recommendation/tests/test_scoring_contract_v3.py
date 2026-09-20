"""v3 scoring/diversity contract and fixture-config shape (no runtime engine).

Covers Issue #47 Phase A: the frozen additive scoring vocabulary, explicit
per-scenario feature weights, the DOMAIN_COVERAGE rerank config, scenario
conflict/diversity oracles, and range validation. It does NOT implement or test
a scoring or reranking engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research.recommendation.fixtures import SCENARIOS
from research.recommendation.fixtures.builders import (
    DEFERRED_FEATURES,
    FEATURES,
    RERANK_STRATEGIES,
    TRACE_ONLY_FEATURES,
    rerank_config,
    simulation_config,
)
from research.recommendation.fixtures.expectations import EXPECTATIONS
from research.recommendation.simulator import SimulationInputError
from research.recommendation.simulator.validation import validate_simulation_input
from research.recommendation.tests._candidate_helpers import make_input, topic

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "simulation-contract-v0.1.md"

A = "scn-A-explicit-more-001"
B = "scn-B-explicit-less-001"
E = "scn-E-preference-conflict-001"
G = "scn-G-prereq-satisfied-001"
I = "scn-I-difficulty-too-low-001"
J = "scn-J-difficulty-appropriate-001"
K = "scn-K-difficulty-too-high-001"
L = "scn-L-semantic-neighbor-001"
M = "scn-M-graph-neighbor-001"
N = "scn-N-continuation-001"
O = "scn-O-revisit-001"
P = "scn-P-diversity-pressure-001"
Q = "scn-Q-deterministic-tie-001"
X4 = "scn-X4-diversity-ineligible-001"
X5 = "scn-X5-tie-diversity-001"


def _base_input() -> dict:
    return make_input(entities=[topic("a")], anchors=[("a", 1)])


# ---------------------------------------------------------------------------
# Frozen scoring vocabulary
# ---------------------------------------------------------------------------


def test_scoring_features_are_exactly_eight():
    assert len(FEATURES) == 8
    assert "novelty" not in FEATURES
    assert "diversity_context" not in FEATURES
    assert DEFERRED_FEATURES == ("novelty",)
    assert TRACE_ONLY_FEATURES == ("diversity_context",)


def test_contract_defers_novelty_and_keeps_diversity_context_trace_only():
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    assert "`novelty` is **deferred beyond M3 v3**" in text
    assert "`diversity_context` is **trace-only**" in text


def test_contract_freezes_additive_scoring_and_conflict_reason():
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    assert "pre_rerank_score          = SUM(component_scores[feature])" in text
    assert "EXPLICIT_INFERRED_CONFLICT_SUPPRESSED" in text
    assert "DOMAIN_COVERAGE_ADJUSTMENT" in text
    assert "rank_candidates(simulation_input, candidates)" in text


def test_contract_marks_top_k_owner_as_49():
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    assert "applied by #49" in text
    assert "#47 ranks the ENTIRE eligible candidate set and does not apply `top_k`" in text


# ---------------------------------------------------------------------------
# Feature-weight and rerank config shape (builder level)
# ---------------------------------------------------------------------------


def test_simulation_config_accepts_recognized_weight_keys():
    config = simulation_config(feature_weights={"readiness": 1.0, "revisit_value": 0.5})
    assert config["feature_weights"] == {"readiness": 1.0, "revisit_value": 0.5}


def test_simulation_config_rejects_unknown_weight_key():
    with pytest.raises(ValueError):
        simulation_config(feature_weights={"novelty": 1.0})


def test_simulation_config_rejects_negative_weight():
    with pytest.raises(ValueError):
        simulation_config(feature_weights={"readiness": -0.1})


def test_simulation_config_rejects_non_finite_weight():
    with pytest.raises(ValueError):
        simulation_config(feature_weights={"readiness": float("inf")})


def test_rerank_config_vocabulary_is_domain_coverage_only():
    config = rerank_config(diversity_weight=1.0)
    assert config == {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0}
    assert RERANK_STRATEGIES == ("DOMAIN_COVERAGE",)
    with pytest.raises(ValueError):
        rerank_config("MMR", diversity_weight=1.0)


def test_rerank_diversity_weight_rejects_negative_and_non_finite():
    with pytest.raises(ValueError):
        rerank_config(diversity_weight=-1.0)
    with pytest.raises(ValueError):
        rerank_config(diversity_weight=float("nan"))


# ---------------------------------------------------------------------------
# Runtime validation of the v3 config shape (validation only, no engine)
# ---------------------------------------------------------------------------


def test_validation_accepts_a_v3_scenario_input():
    validate_simulation_input(_base_input())


def test_validation_rejects_unknown_feature_weight_key():
    sim = _base_input()
    sim["simulation_config"]["feature_weights"] = {"novelty": 1.0}
    with pytest.raises(SimulationInputError):
        validate_simulation_input(sim)


def test_validation_rejects_negative_feature_weight():
    sim = _base_input()
    sim["simulation_config"]["feature_weights"] = {"readiness": -1.0}
    with pytest.raises(SimulationInputError):
        validate_simulation_input(sim)


def test_validation_rejects_unknown_rerank_strategy():
    sim = _base_input()
    sim["simulation_config"]["rerank"] = {"strategy": "MMR", "diversity_weight": 1.0}
    with pytest.raises(SimulationInputError):
        validate_simulation_input(sim)


def test_validation_rejects_negative_diversity_weight():
    sim = _base_input()
    sim["simulation_config"]["rerank"] = {
        "strategy": "DOMAIN_COVERAGE",
        "diversity_weight": -1.0,
    }
    with pytest.raises(SimulationInputError):
        validate_simulation_input(sim)


def test_validation_rejects_out_of_range_difficulty_prior():
    sim = make_input(entities=[topic("a", difficulty=1.5)], anchors=[("a", 1)])
    with pytest.raises(SimulationInputError):
        validate_simulation_input(sim)


def test_validation_rejects_out_of_range_ability_estimate():
    sim = _base_input()
    sim["learner_state_snapshot"]["challenge_state"] = {
        "area_id": "area",
        "ability_estimate": 1.5,
    }
    with pytest.raises(SimulationInputError):
        validate_simulation_input(sim)


def test_validation_rejects_non_string_domain_id():
    sim = make_input(entities=[topic("a")])
    sim["ontology_snapshot"]["entities"][0]["domain_ids"] = ["d1", 2]
    with pytest.raises(SimulationInputError):
        validate_simulation_input(sim)


def test_validation_rejects_incomplete_interest_state():
    sim = make_input(entities=[topic("a")])
    sim["learner_state_snapshot"]["interest_states"] = [
        {
            "entity_id": "a",
            "entity_version": 1,
            "recent_affinity": 0.1,
            "long_term_affinity": 0.2,
        }
    ]
    with pytest.raises(SimulationInputError):
        validate_simulation_input(sim)


def test_validation_rejects_out_of_range_inferred_affinity():
    sim = _base_input()
    sim["learner_state_snapshot"]["interest_states"] = [
        {
            "entity_id": "a",
            "entity_version": 1,
            "recent_affinity": 2.0,
            "long_term_affinity": 0.0,
            "user_initiated_strength": 0.0,
            "algorithm_exposure_strength": 0.0,
            "voluntary_revisit_count": 0,
            "last_interaction_at": None,
            "computed_at": "2026-01-01T00:00:00Z",
            "model_version": "fixture-interest-state/v1",
        }
    ]
    with pytest.raises(SimulationInputError):
        validate_simulation_input(sim)


# ---------------------------------------------------------------------------
# Per-scenario explicit configuration (no global weight profile)
# ---------------------------------------------------------------------------


def test_scenarios_configure_only_the_signal_they_exercise():
    expected = {
        A: {"explicit_interest"},
        B: {"explicit_interest"},
        E: {"explicit_interest", "inferred_interest"},
        G: {"readiness"},
        I: {"difficulty_fit"},
        J: {"difficulty_fit"},
        K: {"difficulty_fit"},
        L: {"semantic_similarity"},
        M: {"graph_proximity"},
        N: {"continuation_value"},
        O: {"revisit_value"},
        P: {"semantic_similarity"},
        X5: {"semantic_similarity"},
    }
    for scenario_id, signals in expected.items():
        weights = SCENARIOS[scenario_id]["simulation_config"]["feature_weights"]
        assert set(weights) == signals, scenario_id
        assert all(weight > 0 for weight in weights.values()), scenario_id


def test_unconfigured_scenarios_have_no_feature_weights():
    configured = {
        A, B, E, G, I, J, K, L, M, N, O, P, X5,
    }
    for scenario_id, simulation_input in SCENARIOS.items():
        if scenario_id in configured:
            continue
        assert simulation_input["simulation_config"]["feature_weights"] == {}, scenario_id


def test_no_global_default_feature_weights_in_contract():
    text = CONTRACT_PATH.read_text(encoding="utf-8")
    assert "there is no module-private or global default recommendation profile" in text


# ---------------------------------------------------------------------------
# Diversity scenario configuration
# ---------------------------------------------------------------------------


def test_diversity_scenarios_configure_domain_coverage():
    for scenario_id in (P, X4, X5):
        rerank = SCENARIOS[scenario_id]["simulation_config"]["rerank"]
        assert rerank == {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0}, scenario_id


def test_scenario_q_rerank_is_null_noop():
    assert SCENARIOS[Q]["simulation_config"]["rerank"] is None


# ---------------------------------------------------------------------------
# Scenario E conflict oracles
# ---------------------------------------------------------------------------


def test_scenario_e_conflict_oracles_suppress_inferred_component():
    oracles = EXPECTATIONS[E]["scoring_oracles"]
    conflicts = [o for o in oracles if o["kind"] == "explicit_inferred_conflict"]
    assert len(conflicts) == 2
    assert {o["inferred_interest_sign"] for o in conflicts} == {"negative", "positive"}
    assert {o["explicit_interest"] for o in conflicts} == {1.0, -1.0}
    for oracle in conflicts:
        assert oracle["effective_inferred_component"] == 0.0
        assert oracle["score_reason_code"] == "EXPLICIT_INFERRED_CONFLICT_SUPPRESSED"


def test_scenario_e_does_not_rely_on_weight_dominance():
    weights = SCENARIOS[E]["simulation_config"]["feature_weights"]
    assert weights == {"explicit_interest": 1.0, "inferred_interest": 1.0}


# ---------------------------------------------------------------------------
# Scenario P / X4 / X5 diversity oracles
# ---------------------------------------------------------------------------


def test_scenario_p_has_domain_coverage_reorder_oracle():
    kinds = {oracle["kind"] for oracle in EXPECTATIONS[P]["scoring_oracles"]}
    assert "domain_coverage_reorder" in kinds


def test_scenario_x4_ineligible_excluded_from_diversity_population():
    kinds = {oracle["kind"] for oracle in EXPECTATIONS[X4]["scoring_oracles"]}
    assert "ineligible_excluded_from_diversity_population" in kinds


def test_scenario_x5_has_deterministic_ranking_oracle():
    kinds = {oracle["kind"] for oracle in EXPECTATIONS[X5]["scoring_oracles"]}
    assert "ranking" in kinds


def test_scoring_oracles_are_present_for_frozen_scenarios():
    for scenario_id in (A, B, E, G, I, J, K, L, M, N, O, P, Q, X4, X5):
        assert EXPECTATIONS[scenario_id]["scoring_oracles"], scenario_id


# ---------------------------------------------------------------------------
# Fixture determinism / fingerprint stability under v3
# ---------------------------------------------------------------------------


def test_fixture_fingerprints_are_deterministic():
    from research.recommendation.fixtures.canonical import input_fingerprint

    for scenario_id, simulation_input in SCENARIOS.items():
        assert input_fingerprint(simulation_input) == input_fingerprint(
            SCENARIOS[scenario_id]
        ), scenario_id


def test_every_fixture_is_v3():
    for scenario_id, simulation_input in SCENARIOS.items():
        assert simulation_input["contract_version"] == "m3-simulation/v3", scenario_id
