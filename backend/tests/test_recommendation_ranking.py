"""Production ranking adapter preserves a small frozen M3 ranking case."""
from __future__ import annotations

from research.recommendation.simulator import generate_candidates, rank_candidates
from research.recommendation.tests._candidate_helpers import make_input, preference, topic

from app.recommendation.ranking import load_profile, rank_recommendations
from app.recommendation.snapshot import ProductionInputSnapshot


def _snapshot_from_m3(sim: dict) -> ProductionInputSnapshot:
    entities = tuple(sim["ontology_snapshot"]["entities"])
    domains = tuple(
        {"entity_id": entity["entity_id"], "domain_id": domain,
         "is_primary": index == 0}
        for entity in entities
        for index, domain in enumerate(entity["domain_ids"])
    )
    return ProductionInputSnapshot(
        user_id="learner", input_version="recommendation-input/v1", fingerprint="test",
        entities=entities, domains=domains, objectives=(), edges=(), embeddings=(),
        objective_states=(), interest_states=tuple(sim["learner_state_snapshot"]["interest_states"]),
        challenge_states=(), explicit_preferences=tuple(sim["preference_snapshot"]["explicit_preferences"]),
        explorations=(), anchor_entities=(),
    )


def test_adapter_matches_m3_order_and_explanations_for_saved_small_case():
    profile = load_profile()
    sim = make_input(
        entities=[topic("a"), topic("b")],
        preferences=[preference("a", "MORE"), preference("b", "LESS")],
        feature_weights=profile["feature_weights"],
        rerank=profile["rerank"],
    )
    candidates = generate_candidates(sim)
    expected = rank_candidates(sim, candidates)
    actual = rank_recommendations(_snapshot_from_m3(sim), candidates)
    assert [item["target_entity_id"] for item in actual.ranked] == [
        item["target_entity_id"] for item in expected
    ]
    assert [item["ordering_score"] for item in actual.ranked] == [
        item["ordering_score"] for item in expected
    ]
    assert actual.selected["final_rank"] == 1
    assert actual.selected["explanation_codes"]


def test_empty_eligible_population_stays_empty():
    sim = make_input(entities=[topic("a")], preferences=[preference("a", "PAUSED")])
    result = rank_recommendations(_snapshot_from_m3(sim), generate_candidates(sim))
    assert result.selected is None
    assert result.ranked == ()
    assert result.excluded_count == 1
