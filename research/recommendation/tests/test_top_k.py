"""#49 top_k prefix selection, clipping, zero, and validation."""

from __future__ import annotations

import pytest

from research.recommendation.fixtures import build_scenario
from research.recommendation.simulator import SimulationInputError, run_simulation

P = "scn-P-diversity-pressure-001"
J = "scn-J-difficulty-appropriate-001"


def _with_top_k(scenario_id: str, top_k: int) -> dict:
    simulation_input = build_scenario(scenario_id)
    simulation_input["simulation_config"]["top_k"] = top_k
    return simulation_input


def test_top_k_prefix_selects_only_first_results():
    prefix = run_simulation(_with_top_k(P, 1))
    full = run_simulation(_with_top_k(P, 99))
    assert len(prefix["ranked_recommendations"]) == 1
    assert [entry["final_rank"] for entry in prefix["ranked_recommendations"]] == [1]
    assert len(prefix["candidates_considered"]) == 3
    assert prefix["metrics"]["eligible_candidate_count"] == 3
    assert prefix["metrics"]["candidate_count"] == 3
    # Full-ranked population still observed by the diversity metric.
    assert (
        prefix["metrics"]["rank_change_due_to_diversity"]
        == full["metrics"]["rank_change_due_to_diversity"]
    )
    # Selected population observed by top_k_source_mix.
    assert sum(prefix["metrics"]["top_k_source_mix"].values()) == 1
    assert sum(full["metrics"]["top_k_source_mix"].values()) == 3
    assert sum(prefix["metrics"]["source_coverage"].values()) == 3


def test_top_k_zero_is_empty_but_valid():
    result = run_simulation(_with_top_k(J, 0))
    assert result["ranked_recommendations"] == []
    assert result["metrics"]["eligible_candidate_count"] == 3
    assert result["metrics"]["revisit_share"] == 0.0
    assert result["metrics"]["continuation_share"] == 0.0
    assert result["metrics"]["topic_domain_diversity"] == 0
    assert result["metrics"]["difficulty_distribution"] == {}
    assert result["metrics"]["trace_completeness"] == 0.0
    in10 = next(i for i in result["invariant_results"] if i["invariant_code"] == "IN-10")
    assert in10["status"] == "PASS"


def test_top_k_greater_than_available_selects_all_without_renumbering():
    result = run_simulation(_with_top_k(J, 99))
    ranks = [entry["final_rank"] for entry in result["ranked_recommendations"]]
    assert ranks == [1, 2, 3]
    assert result["metrics"]["eligible_candidate_count"] == 3


def test_negative_top_k_is_rejected():
    with pytest.raises(SimulationInputError):
        run_simulation(_with_top_k(J, -1))


def test_non_selected_eligible_are_not_public():
    prefix = run_simulation(_with_top_k(P, 1))
    forged_keys = {"ranked_candidates_all", "recommendations_all", "non_selected_recommendations"}
    assert not (set(prefix) & forged_keys)
    assert 3 > len(prefix["ranked_recommendations"])
