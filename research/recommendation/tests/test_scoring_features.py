"""Unit tests for the frozen v3 scoring feature computations (#47)."""

from __future__ import annotations

import pytest

from research.recommendation.simulator import SimulationInputError, scoring


def _candidate(**overrides) -> dict:
    candidate = {
        "prerequisite_evaluations": [],
        "feature_inputs": {},
        "source_paths": [],
    }
    candidate.update(overrides)
    return candidate


# --- readiness -------------------------------------------------------------


def test_readiness_no_prerequisites_is_zero():
    assert scoring._readiness(_candidate()) == 0.0


def test_readiness_all_satisfied_is_one():
    candidate = _candidate(
        prerequisite_evaluations=[{"requirement": "HARD", "state": "SATISFIED"}]
    )
    assert scoring._readiness(candidate) == 1.0


def test_readiness_mixed_soft_evaluations_is_fraction():
    candidate = _candidate(
        prerequisite_evaluations=[
            {"requirement": "SOFT", "state": "SATISFIED"},
            {"requirement": "SOFT", "state": "UNSATISFIED"},
        ]
    )
    assert scoring._readiness(candidate) == 0.5


def test_readiness_unknown_counts_against_fraction():
    candidate = _candidate(
        prerequisite_evaluations=[{"requirement": "SOFT", "state": "UNKNOWN"}]
    )
    assert scoring._readiness(candidate) == 0.0


# --- difficulty fit --------------------------------------------------------


def test_difficulty_exact_match_is_one():
    entity = {"difficulty_prior": 0.5, "domain_ids": ["area"]}
    challenge = {"area_id": "area", "ability_estimate": 0.5}
    assert scoring._difficulty_fit(_candidate(), entity, challenge) == 1.0


def test_difficulty_distance_point_two_is_point_eight():
    entity = {"difficulty_prior": 0.3, "domain_ids": ["area"]}
    challenge = {"area_id": "area", "ability_estimate": 0.5}
    assert scoring._difficulty_fit(_candidate(), entity, challenge) == pytest.approx(0.8)


def test_difficulty_endpoints_are_zero():
    entity = {"difficulty_prior": 0.0, "domain_ids": ["area"]}
    challenge = {"area_id": "area", "ability_estimate": 1.0}
    assert scoring._difficulty_fit(_candidate(), entity, challenge) == 0.0


def test_difficulty_missing_challenge_is_zero():
    entity = {"difficulty_prior": 0.5, "domain_ids": ["area"]}
    assert scoring._difficulty_fit(_candidate(), entity, None) == 0.0


def test_difficulty_missing_difficulty_prior_is_zero():
    entity = {"difficulty_prior": None, "domain_ids": ["area"]}
    challenge = {"area_id": "area", "ability_estimate": 0.5}
    assert scoring._difficulty_fit(_candidate(), entity, challenge) == 0.0


def test_difficulty_unmatched_area_is_zero():
    entity = {"difficulty_prior": 0.5, "domain_ids": ["other"]}
    challenge = {"area_id": "area", "ability_estimate": 0.5}
    assert scoring._difficulty_fit(_candidate(), entity, challenge) == 0.0


# --- explicit interest -----------------------------------------------------


def test_explicit_values():
    assert scoring._explicit_interest(_candidate()) == 0.0
    assert (
        scoring._explicit_interest(
            _candidate(feature_inputs={"explicit_preference": "MORE"})
        )
        == 1.0
    )
    assert (
        scoring._explicit_interest(
            _candidate(feature_inputs={"explicit_preference": "LESS"})
        )
        == -1.0
    )
    assert (
        scoring._explicit_interest(
            _candidate(feature_inputs={"explicit_preference": "NEUTRAL"})
        )
        == 0.0
    )


@pytest.mark.parametrize("preference", ["PAUSED", "NOT_INTERESTED"])
def test_explicit_hard_excluding_on_eligible_is_invariant_violation(preference):
    candidate = _candidate(feature_inputs={"explicit_preference": preference})
    with pytest.raises(SimulationInputError):
        scoring._explicit_interest(candidate)


def test_explicit_unknown_preference_raises():
    candidate = _candidate(feature_inputs={"explicit_preference": "MAYBE"})
    with pytest.raises(SimulationInputError):
        scoring._explicit_interest(candidate)


# --- inferred interest -----------------------------------------------------


def test_inferred_missing_is_zero():
    assert scoring._inferred_interest(None) == 0.0


def test_inferred_average_of_recent_and_long_term():
    assert scoring._inferred_interest(
        {"recent_affinity": 0.4, "long_term_affinity": 0.2}
    ) == pytest.approx(0.3)
    assert scoring._inferred_interest(
        {"recent_affinity": -0.6, "long_term_affinity": -0.4}
    ) == pytest.approx(-0.5)


# --- graph proximity -------------------------------------------------------


def test_graph_proximity_absent_is_zero():
    assert scoring._graph_proximity(_candidate()) == 0.0


def test_graph_proximity_reciprocal_hop():
    one_hop = [{"source": "GRAPH", "provenance": {"hop_distance": 1}}]
    two_hop = [{"source": "GRAPH", "provenance": {"hop_distance": 2}}]
    assert scoring._graph_proximity(_candidate(source_paths=one_hop)) == 1.0
    assert scoring._graph_proximity(_candidate(source_paths=two_hop)) == 0.5


def test_graph_proximity_multiple_paths_takes_max():
    paths = [
        {"source": "GRAPH", "provenance": {"hop_distance": 3}},
        {"source": "GRAPH", "provenance": {"hop_distance": 1}},
    ]
    assert scoring._graph_proximity(_candidate(source_paths=paths)) == 1.0


def test_graph_proximity_rejects_zero_hop():
    paths = [{"source": "GRAPH", "provenance": {"hop_distance": 0}}]
    with pytest.raises(SimulationInputError):
        scoring._graph_proximity(_candidate(source_paths=paths))


# --- semantic similarity ---------------------------------------------------


def test_semantic_similarity_absent_is_zero():
    assert scoring._semantic_similarity(_candidate()) == 0.0


def test_semantic_similarity_preserves_negative_cosine():
    paths = [{"source": "SEMANTIC", "provenance": {"cosine_similarity": -0.4}}]
    assert scoring._semantic_similarity(_candidate(source_paths=paths)) == -0.4


def test_semantic_similarity_multiple_paths_takes_max():
    paths = [
        {"source": "SEMANTIC", "provenance": {"cosine_similarity": 0.2}},
        {"source": "SEMANTIC", "provenance": {"cosine_similarity": 0.8}},
    ]
    assert scoring._semantic_similarity(_candidate(source_paths=paths)) == pytest.approx(0.8)


# --- continuation / revisit ------------------------------------------------


def test_continuation_and_revisit_are_binary_presence():
    continuation = _candidate(
        source_paths=[{"source": "HISTORY_CONTINUATION", "provenance": {}}]
    )
    assert scoring._has_source(continuation, "HISTORY_CONTINUATION") is True
    assert scoring._has_source(continuation, "REVISIT") is False

    revisit = _candidate(source_paths=[{"source": "REVISIT", "provenance": {}}])
    assert scoring._has_source(revisit, "REVISIT") is True
    assert scoring._has_source(revisit, "HISTORY_CONTINUATION") is False


# --- effective weights -----------------------------------------------------


# --- readiness summary (HARD gate) ----------------------------------------


def test_readiness_summary_exact_hard_gate_shape():
    candidate = _candidate(
        prerequisite_evaluations=[
            {"requirement": "HARD", "state": "SATISFIED", "prerequisite_entity_id": "h"},
            {"requirement": "SOFT", "state": "UNSATISFIED", "prerequisite_entity_id": "s"},
        ]
    )
    assert scoring._readiness_summary(candidate) == {
        "hard_prerequisites_total": 1,
        "hard_prerequisites_satisfied": 1,
        "state": "SATISFIED",
    }
    # SOFT outcomes affect only the numeric scoring feature, not the summary.
    assert scoring._readiness(candidate) == 0.5


def test_readiness_summary_no_hard_prerequisites_is_vacuously_satisfied():
    assert scoring._readiness_summary(_candidate()) == {
        "hard_prerequisites_total": 0,
        "hard_prerequisites_satisfied": 0,
        "state": "SATISFIED",
    }


@pytest.mark.parametrize("bad_state", ["UNSATISFIED", "UNKNOWN"])
def test_non_satisfied_hard_prerequisite_on_eligible_is_invariant_violation(bad_state):
    candidate = _candidate(
        prerequisite_evaluations=[
            {
                "requirement": "HARD",
                "state": bad_state,
                "prerequisite_entity_id": "h",
            }
        ]
    )
    with pytest.raises(SimulationInputError):
        scoring._assert_hard_prerequisites_satisfied(candidate)


# --- effective weights -----------------------------------------------------


def test_effective_weights_fill_missing_with_zero():
    sim = {
        "simulation_config": {
            "feature_weights": {"readiness": 2.0},
        }
    }
    weights = scoring.effective_weights(sim)
    assert set(weights) == set(scoring.SCORING_FEATURES)
    assert weights["readiness"] == 2.0
    assert weights["inferred_interest"] == 0.0
