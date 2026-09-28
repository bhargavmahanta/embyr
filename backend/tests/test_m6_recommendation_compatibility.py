"""Final M6 guard for the already frozen M3/M4 recommendation boundary."""

import pytest
from app.recommendation.inputs import objective_state_entry
from app.recommendation.ranking import load_profile

from research.recommendation.simulator.eligibility import collect_exclusion_reasons
from research.recommendation.simulator.readiness import classify_objective_state


@pytest.mark.parametrize(
    "category,expected",
    [
        (None, "UNKNOWN"),
        ("DEVELOPING", "UNSATISFIED"),
        ("UNDERSTOOD", "SATISFIED"),
        ("RETAINED", "SATISFIED"),
    ],
)
@pytest.mark.parametrize("estimate", [None, 0.0, 0.5, 1.0])
def test_m6_objective_state_does_not_promote_numeric_estimates(
    category,
    expected,
    estimate,
):
    row = {
        "objective_id": "11111111-1111-4111-8111-111111111111",
        "entity_id": "22222222-2222-4222-8222-222222222222",
        "entity_version": 1,
        "categorical_state": category,
        "understanding_estimate": estimate,
    }
    mapped = objective_state_entry(row)
    assert classify_objective_state(mapped["state"] if mapped else None) == expected


def test_hard_prerequisite_reasons_remain_distinct():
    for state, reason in [
        ("UNSATISFIED", "PREREQUISITE_UNMET"),
        ("UNKNOWN", "INSUFFICIENT_STATE"),
    ]:
        assert collect_exclusion_reasons(
            {"id": "target"},
            None,
            [{"requirement": "HARD", "state": state}],
        ) == [reason]


def test_m4_profile_identity_and_weights_are_frozen():
    assert load_profile() == {
        "profile_version": "recommendation-profile/v1",
        "semantic_contract": "m3-simulation/v5",
        "top_k": 1,
        "feature_weights": {
            "readiness": 0.14,
            "difficulty_fit": 0.18,
            "explicit_interest": 0.22,
            "inferred_interest": 0.08,
            "graph_proximity": 0.12,
            "semantic_similarity": 0.14,
            "continuation_value": 0.07,
            "revisit_value": 0.05,
        },
        "rerank": {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 0.08},
    }
