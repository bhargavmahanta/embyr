"""Execute all 27 fixtures through #47 scoring/reranking.

Asserts only frozen #47 behavior: eligibility filtering, ranks, additive score,
trace consistency, and the v3 scoring oracles. #48 explanations and #49 metrics
are not exercised.
"""

from __future__ import annotations

import math

import pytest

from research.recommendation.fixtures import SCENARIOS, SCENARIO_TARGETS
from research.recommendation.fixtures.expectations import EXPECTATIONS
from research.recommendation.simulator import generate_candidates, rank_candidates
from research.recommendation.simulator.validation import SCORING_FEATURES

SCENARIO_IDS = list(SCENARIOS)


def _ranked(scenario_id: str) -> list[dict]:
    simulation_input = SCENARIOS[scenario_id]
    return rank_candidates(simulation_input, generate_candidates(simulation_input))


def _by_id(ranked: list[dict]) -> dict[str, dict]:
    return {entry["target_entity_id"]: entry for entry in ranked}


def _target(scenario_id: str, name: str) -> dict:
    return SCENARIO_TARGETS[scenario_id][name]


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_ranking_returns_exactly_eligible_candidates(scenario_id):
    simulation_input = SCENARIOS[scenario_id]
    candidates = generate_candidates(simulation_input)
    eligible = {
        candidate["target_entity_id"]
        for candidate in candidates
        if candidate["eligibility_state"] == "ELIGIBLE"
    }
    ranked = rank_candidates(simulation_input, candidates)
    assert {entry["target_entity_id"] for entry in ranked} == eligible
    assert [entry["final_rank"] for entry in ranked] == list(range(1, len(ranked) + 1))


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_ranking_traces_are_consistent_and_finite(scenario_id):
    ranked = _ranked(scenario_id)
    pre_ranks = sorted(entry["rerank_trace"]["pre_rerank_rank"] for entry in ranked)
    assert pre_ranks == list(range(1, len(ranked) + 1))
    for entry in ranked:
        trace = entry["score_trace"]
        assert set(trace["component_scores"]) == set(SCORING_FEATURES)
        assert set(trace["configured_weights"]) == set(SCORING_FEATURES)
        assert trace["pre_rerank_score"] == pytest.approx(
            sum(trace["component_scores"].values())
        )
        assert math.isfinite(entry["ordering_score"])
        assert entry["final_rank"] == entry["rerank_trace"]["post_rerank_rank"]
        assert entry["ordering_score"] == pytest.approx(
            entry["score_trace"]["pre_rerank_score"]
            + entry["rerank_trace"]["diversity_adjustment"]
        )
        assert "explanation_codes" not in entry


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_scoring_oracles(scenario_id):
    ranked = _by_id(_ranked(scenario_id))
    for oracle in EXPECTATIONS[scenario_id]["scoring_oracles"]:
        _assert_oracle(oracle, ranked)


def _assert_oracle(oracle: dict, ranked: dict[str, dict]) -> None:
    kind = oracle["kind"]
    if kind == "ranking":
        higher = oracle["higher_ranked_target"]["entity_id"]
        lower = oracle["lower_ranked_target"]["entity_id"]
        if lower not in ranked:
            assert higher in ranked
            return
        assert ranked[higher]["final_rank"] < ranked[lower]["final_rank"]
    elif kind == "feature_value":
        entry = ranked[oracle["target"]["entity_id"]]
        value = entry["score_trace"]["feature_values"][oracle["feature"]]
        assert value == pytest.approx(oracle["value"])
    elif kind == "feature_relation":
        higher = ranked[oracle["higher_target"]["entity_id"]]
        lower = ranked[oracle["lower_target"]["entity_id"]]
        assert (
            higher["score_trace"]["feature_values"][oracle["feature"]]
            > lower["score_trace"]["feature_values"][oracle["feature"]]
        )
    elif kind == "explicit_inferred_conflict":
        entry = ranked[oracle["target"]["entity_id"]]
        trace = entry["score_trace"]
        assert trace["feature_values"]["explicit_interest"] == pytest.approx(
            oracle["explicit_interest"]
        )
        raw_inferred = trace["feature_values"]["inferred_interest"]
        expected_sign = oracle["inferred_interest_sign"]
        assert (raw_inferred > 0) if expected_sign == "positive" else (raw_inferred < 0)
        assert trace["component_scores"]["inferred_interest"] == 0.0
        assert oracle["score_reason_code"] in trace["reason_codes"]
    elif kind == "domain_coverage_reorder":
        lifted = ranked[oracle["lifted_target"]["entity_id"]]
        redundant = ranked[oracle["redundant_target"]["entity_id"]]
        assert lifted["rerank_trace"]["diversity_adjustment"] > 0.0
        assert redundant["rerank_trace"]["diversity_adjustment"] == 0.0
    elif kind == "ineligible_excluded_from_diversity_population":
        assert oracle["excluded_target"]["entity_id"] not in ranked
    else:  # pragma: no cover - guards against unhandled oracle kinds
        raise AssertionError(f"unhandled oracle kind: {kind}")


# --- focused scenarios -----------------------------------------------------


def test_scenario_e_conflict_by_suppression_not_weight_dominance():
    ranked = _by_id(_ranked("scn-E-preference-conflict-001"))
    more = ranked[_target("scn-E-preference-conflict-001", "more_target")["entity_id"]]
    less = ranked[_target("scn-E-preference-conflict-001", "less_target")["entity_id"]]
    for entry in (more, less):
        weights = entry["score_trace"]["configured_weights"]
        assert weights["explicit_interest"] == 1.0
        assert weights["inferred_interest"] == 1.0
        assert all(
            weight == 0.0
            for feature, weight in weights.items()
            if feature not in {"explicit_interest", "inferred_interest"}
        )
        assert "EXPLICIT_INFERRED_CONFLICT_SUPPRESSED" in entry["score_trace"]["reason_codes"]
        assert entry["score_trace"]["component_scores"]["inferred_interest"] == 0.0
    assert more["final_rank"] < less["final_rank"]


def test_scenario_p_domain_coverage_reorders():
    ranked = _ranked("scn-P-diversity-pressure-001")
    by_id = _by_id(ranked)
    spread = by_id[_target("scn-P-diversity-pressure-001", "spread")["entity_id"]]
    cluster_a = by_id[_target("scn-P-diversity-pressure-001", "cluster_a")["entity_id"]]
    assert spread["rerank_trace"]["diversity_adjustment"] > 0.0
    assert "DOMAIN_COVERAGE_ADJUSTMENT" in spread["rerank_trace"]["reason_codes"]
    assert spread["final_rank"] < cluster_a["final_rank"]


def test_scenario_q_tie_breaks_by_key_not_candidate_id():
    ranked = _ranked("scn-Q-deterministic-tie-001")
    a = _target("scn-Q-deterministic-tie-001", "target_a")["entity_id"]
    b = _target("scn-Q-deterministic-tie-001", "target_b")["entity_id"]
    by_id = _by_id(ranked)
    assert by_id[a]["score_trace"]["pre_rerank_score"] == by_id[b]["score_trace"]["pre_rerank_score"]
    assert by_id[a]["final_rank"] < by_id[b]["final_rank"]
    assert by_id[a]["deterministic_tiebreak_key"].startswith("TOPIC:")


@pytest.mark.parametrize("scenario_id", ["scn-T-no-eligible-001", "scn-X7-multi-exclusion-empty-001"])
def test_all_ineligible_scenarios_return_empty(scenario_id):
    assert _ranked(scenario_id) == []


@pytest.mark.parametrize(
    "scenario_id,target_name",
    [
        ("scn-X1-more-unmet-prereq-001", "target"),
        ("scn-X2-not-interested-inferred-positive-001", "target"),
    ],
)
def test_excluded_targets_are_not_resurrected(scenario_id, target_name):
    ranked = _by_id(_ranked(scenario_id))
    assert _target(scenario_id, target_name)["entity_id"] not in ranked


def test_scenario_x3_derives_all_three_signals_independently():
    ranked = _by_id(_ranked("scn-X3-three-source-duplicate-001"))
    target = ranked[_target("scn-X3-three-source-duplicate-001", "target")["entity_id"]]
    values = target["score_trace"]["feature_values"]
    assert values["graph_proximity"] > 0.0
    assert values["semantic_similarity"] > 0.0
    assert values["explicit_interest"] == 1.0
