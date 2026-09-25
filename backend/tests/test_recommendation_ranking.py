"""Production ranking adapter preserves a small frozen M3 ranking case."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from research.recommendation.fixtures import builders as b
from research.recommendation.simulator import (
    build_recommendation_results, generate_candidates, rank_candidates,
)
from research.recommendation.tests._candidate_helpers import (
    make_input, preference, related, topic,
)

from app.recommendation import ranking
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
        challenge_states=(sim["learner_state_snapshot"]["challenge_state"],)
        if sim["learner_state_snapshot"]["challenge_state"] is not None else (),
        explicit_preferences=tuple(sim["preference_snapshot"]["explicit_preferences"]),
        explorations=(), anchor_entities=(),
    )


def test_adapter_matches_m3_scoring_rerank_and_explanations():
    profile = load_profile()
    sim = make_input(
        entities=[
            topic("a", domains=("common",)),
            topic("b", domains=("common",)),
            topic("c", domains=("rare",)),
        ],
        preferences=[
            preference("a", "MORE"), preference("b", "LESS"),
            preference("c", "MORE"),
        ],
        interest_states=[b.interest_state(
            "b", 1, recent_affinity=0.8, long_term_affinity=0.6,
            user_initiated_strength=0.0, algorithm_exposure_strength=0.0,
        )],
        challenge=("common", 0.7),
        feature_weights=profile["feature_weights"],
        rerank=profile["rerank"],
    )
    candidates = generate_candidates(sim)
    expected = build_recommendation_results(rank_candidates(sim, candidates))
    actual = rank_recommendations(_snapshot_from_m3(sim), candidates, mode="EXPLORE")
    assert actual.ranked == tuple(expected)
    assert actual.selected == expected[0]
    assert any(item["rerank_trace"]["diversity_adjustment"] > 0
               and "DIVERSITY_ADJUSTMENT" in item["explanation_codes"]
               for item in actual.ranked)
    conflicted = next(item for item in actual.ranked if item["target_entity_id"] == "b")
    assert conflicted["score_trace"]["feature_values"]["inferred_interest"] == 0.7
    assert conflicted["score_trace"]["component_scores"]["inferred_interest"] == 0.0
    assert "EXPLICIT_INFERRED_CONFLICT_SUPPRESSED" in conflicted["score_trace"]["reason_codes"]
    assert "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED" in conflicted["explanation_codes"]


def _candidate(entity_id: str, *sources: str, preference_value: str | None = None) -> dict:
    provenance = {
        "GRAPH": {"hop_distance": 1},
        "SEMANTIC": {"cosine_similarity": 0.7},
    }
    return {
        "candidate_id": entity_id,
        "target_entity_id": entity_id,
        "target_entity_version": 1,
        "target_entity_type": "TOPIC",
        "source_paths": [
            {"source": source, "provenance": provenance.get(source, {})}
            for source in sources
        ],
        "prerequisite_evaluations": [],
        "eligibility_state": "ELIGIBLE",
        "exclusion_reasons": [],
        "feature_inputs": {"difficulty_prior": 0.5, **(
            {"explicit_preference": preference_value} if preference_value else {}
        )},
    }


def test_mode_filter_selects_from_full_explained_ranking_without_rerank():
    sim = make_input(entities=[
        topic("mixed", domains=("common",)),
        topic("explicit", domains=("common",)),
        topic("graph", domains=("rare",)),
        topic("semantic", domains=("common",)),
        topic("continuation", domains=("common",)),
        topic("revisit", domains=("common",)),
    ])
    snapshot = _snapshot_from_m3(sim)
    candidates = [
        _candidate("mixed", "GRAPH", "EXPLICIT_INTEREST", preference_value="MORE"),
        _candidate("explicit", "EXPLICIT_INTEREST", preference_value="MORE"),
        _candidate("graph", "GRAPH"),
        _candidate("semantic", "SEMANTIC"),
        _candidate("continuation", "HISTORY_CONTINUATION"),
        _candidate("revisit", "REVISIT"),
        {**_candidate("blocked", "EXPLICIT_INTEREST"),
         "eligibility_state": "INELIGIBLE", "exclusion_reasons": ["EXPLICITLY_PAUSED"]},
    ]
    expected_targets = {
        "CONTINUE": "continuation",
        "REVISIT": "revisit",
        "EXPLORE": "mixed",
        "SURPRISE": "graph",
        "CREATE": None,
    }
    baseline = rank_recommendations(snapshot, candidates, mode="EXPLORE")
    assert any(item["rerank_trace"]["diversity_adjustment"] > 0
               for item in baseline.ranked)
    for mode, target in expected_targets.items():
        result = rank_recommendations(snapshot, candidates, mode=mode)
        assert result.ranked == baseline.ranked
        assert (result.selected["target_entity_id"] if result.selected else None) == target
        assert (result.candidate_count, result.eligible_count, result.excluded_count) == (7, 6, 1)
        if result.selected:
            assert result.selected == next(item for item in result.ranked
                                           if item["target_entity_id"] == target)
    surprise = rank_recommendations(snapshot, candidates, mode="SURPRISE")
    assert surprise.selected["final_rank"] > 1
    assert "EXPLICIT_INTEREST" not in surprise.selected["candidate_sources"]
    with pytest.raises(ValueError, match="mode"):
        rank_recommendations(snapshot, candidates, mode="UNKNOWN")


def test_explore_accepts_each_of_its_three_sources():
    for source in ("GRAPH", "SEMANTIC", "EXPLICIT_INTEREST"):
        sim = make_input(entities=[topic("a")])
        candidate = _candidate(
            "a", source, preference_value="MORE" if source == "EXPLICIT_INTEREST" else None
        )
        result = rank_recommendations(_snapshot_from_m3(sim), [candidate], mode="EXPLORE")
        assert result.selected is not None


@pytest.mark.parametrize(("domains", "states", "expected_fit"), [
    (("primary", "secondary"), (("primary", 0.7), ("secondary", 0.4)), 0.8),
    (("primary", "secondary"), (("primary", 1200.0), ("secondary", 0.4)), 0.9),
    (("primary", "secondary"), (("primary", float("nan")), ("secondary", 0.4)), 0.9),
    (("primary", "secondary"), (("primary", float("inf")), ("secondary", 0.4)), 0.9),
    (("primary", "secondary"), (("primary", float("-inf")), ("secondary", 0.4)), 0.9),
    (("primary", "secondary"), (("primary", float("nan")),
                                ("secondary", float("inf"))), 0.0),
    (("primary", "secondary"), (("primary", 1200.0), ("secondary", -3.0)), 0.0),
    (("primary", "secondary"), (("unrelated", 0.7),), 0.0),
    (("primary", "z-secondary", "a-secondary"),
     (("z-secondary", 0.8), ("a-secondary", 0.4)), 0.9),
])
def test_challenge_mapping_uses_only_valid_matching_state(domains, states, expected_fit):
    sim = make_input(entities=[topic("a", domains=domains)],
                     preferences=[preference("a", "MORE")])
    snapshot = replace(_snapshot_from_m3(sim), challenge_states=tuple(
        {"area_id": area_id, "ability_estimate": ability}
        for area_id, ability in states
    ))
    [candidate] = generate_candidates(sim)
    result = rank_recommendations(snapshot, [candidate], mode="EXPLORE")
    assert result.selected["score_trace"]["feature_values"]["difficulty_fit"] == pytest.approx(
        expected_fit
    )


def test_zero_explanation_codes_remain_empty():
    sim = make_input(entities=[
        topic("a", relationships=(related("b"),)), topic("b"),
    ], anchors=[("a", 1)], feature_weights=load_profile()["feature_weights"],
        rerank=load_profile()["rerank"])
    candidates = generate_candidates(sim)
    expected = build_recommendation_results(rank_candidates(sim, candidates))
    result = rank_recommendations(_snapshot_from_m3(sim), candidates, mode="EXPLORE")
    assert result.ranked == tuple(expected)
    assert result.selected["explanation_codes"] == []


@pytest.mark.parametrize(("violation", "message"), [
    ("missing", "no matching ontology target"),
    ("type", "no matching ontology target"),
    ("hard", "non-satisfied HARD prerequisite"),
])
def test_internal_candidate_inconsistency_fails_before_create_filter(violation, message):
    sim = make_input(entities=[topic("a")])
    candidate = _candidate("a", "GRAPH")
    if violation == "missing":
        candidate["target_entity_id"] = "missing"
    elif violation == "type":
        candidate["target_entity_type"] = "AREA"
    else:
        candidate["prerequisite_evaluations"] = [{
            "requirement": "HARD", "state": "UNKNOWN", "prerequisite_entity_id": "other",
        }]
    with pytest.raises(ValueError, match=message):
        rank_recommendations(_snapshot_from_m3(sim), [candidate], mode="CREATE")


@pytest.mark.parametrize(("path", "value"), [
    (("feature_weights", "readiness"), 0.99),
    (("feature_weights", "readiness"), -0.14),
    (("rerank", "diversity_weight"), 0.2),
    (("top_k",), 2),
    (("top_k",), True),
    (("rerank", "strategy"), "OTHER"),
])
def test_v1_profile_rejects_mutated_values(monkeypatch, tmp_path, path, value):
    profile = load_profile()
    target = profile
    for field in path[:-1]:
        target = target[field]
    target[path[-1]] = value
    path_on_disk = tmp_path / "profile.json"
    path_on_disk.write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(ranking, "PROFILE_PATH", path_on_disk)
    with pytest.raises(ValueError, match="profile"):
        load_profile()


def test_empty_eligible_population_stays_empty():
    sim = make_input(entities=[topic("a")], preferences=[preference("a", "PAUSED")])
    result = rank_recommendations(_snapshot_from_m3(sim), generate_candidates(sim), mode="EXPLORE")
    assert result.selected is None
    assert result.ranked == ()
    assert result.excluded_count == 1
