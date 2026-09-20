"""Unit tests for the frozen v3 DOMAIN_COVERAGE reranker (#47)."""

from __future__ import annotations

import pytest

from research.recommendation.simulator import rerank


def _entry(entity_id: str, pre_score: float, pre_rank: int) -> dict:
    return {
        "target_entity_id": entity_id,
        "target_entity_version": 1,
        "deterministic_tiebreak_key": f"TOPIC:{entity_id}:1",
        "pre_rerank_score": pre_score,
        "pre_rerank_rank": pre_rank,
    }


def _entities(**domains_by_id) -> dict:
    return {
        (entity_id, 1): {"domain_ids": list(domains)}
        for entity_id, domains in domains_by_id.items()
    }


def _ordered(scored: list[dict]) -> list[str]:
    return [entry["target_entity_id"] for entry in scored]


def test_null_rerank_is_strict_noop():
    scored = [_entry("a", 2.0, 1), _entry("b", 1.0, 2)]
    rerank.apply_rerank(scored, _entities(a=["d1"], b=["d1"]), None)
    assert [e["diversity_adjustment"] for e in scored] == [0.0, 0.0]
    assert [e["ordering_score"] for e in scored] == [2.0, 1.0]
    assert [e["post_rerank_rank"] for e in scored] == [1, 2]
    assert [e["final_rank"] for e in scored] == [1, 2]
    assert all(e["rerank_trace"]["reason_codes"] == [] for e in scored)
    assert all(e["rerank_trace"]["diversity_dimensions"] == {} for e in scored)


def test_equal_domain_representation_has_no_signal():
    scored = [_entry("a", 0.0, 1), _entry("b", 0.0, 2)]
    rerank.apply_rerank(
        scored,
        _entities(a=["d1"], b=["d1"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    assert [e["diversity_adjustment"] for e in scored] == [0.0, 0.0]


def test_rare_domain_gets_positive_signal_and_reorders():
    scored = [_entry("a", 0.0, 1), _entry("b", 0.0, 2), _entry("c", 0.0, 3)]
    rerank.apply_rerank(
        scored,
        _entities(a=["d1"], b=["d1"], c=["d2"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    by_id = {e["target_entity_id"]: e for e in scored}
    assert by_id["c"]["diversity_adjustment"] == pytest.approx(0.5)
    assert by_id["a"]["diversity_adjustment"] == 0.0
    assert by_id["b"]["diversity_adjustment"] == 0.0
    assert _ordered(scored) == ["c", "a", "b"]


def test_duplicate_domain_id_does_not_inflate_frequency():
    scored = [_entry("a", 0.0, 1), _entry("b", 0.0, 2)]
    rerank.apply_rerank(
        scored,
        _entities(a=["d1", "d1"], b=["d1"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    a = next(e for e in scored if e["target_entity_id"] == "a")
    dims = a["rerank_trace"]["diversity_dimensions"]
    assert dims["domain_ids"] == ["d1"]
    assert dims["domain_rarity"] == pytest.approx(0.5)


def test_candidate_with_no_domains_has_zero_rarity():
    scored = [_entry("a", 0.0, 1), _entry("b", 0.0, 2)]
    rerank.apply_rerank(
        scored,
        _entities(a=[], b=["d1"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    by_id = {e["target_entity_id"]: e for e in scored}
    assert by_id["a"]["rerank_trace"]["diversity_dimensions"]["domain_rarity"] == 0.0
    assert by_id["b"]["diversity_adjustment"] == pytest.approx(1.0)


def test_one_candidate_has_no_adjustment():
    scored = [_entry("a", 3.0, 1)]
    rerank.apply_rerank(
        scored,
        _entities(a=["d1"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 5.0},
    )
    assert scored[0]["diversity_adjustment"] == 0.0
    assert scored[0]["ordering_score"] == 3.0


def test_multiple_domains_per_candidate_uses_mean():
    scored = [_entry("a", 0.0, 1), _entry("b", 0.0, 2), _entry("c", 0.0, 3)]
    rerank.apply_rerank(
        scored,
        _entities(a=["d1", "d2"], b=["d1"], c=["d2"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    a = next(e for e in scored if e["target_entity_id"] == "a")
    assert a["rerank_trace"]["diversity_dimensions"]["domain_rarity"] == pytest.approx(0.5)
    assert a["diversity_adjustment"] == 0.0


def test_diversity_weight_zero_has_no_adjustment():
    scored = [_entry("a", 0.0, 1), _entry("b", 0.0, 2), _entry("c", 0.0, 3)]
    rerank.apply_rerank(
        scored,
        _entities(a=["d1"], b=["d1"], c=["d2"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 0.0},
    )
    assert all(e["diversity_adjustment"] == 0.0 for e in scored)
    assert _ordered(scored) == ["a", "b", "c"]


def test_pre_rerank_leader_stays_when_adjustment_insufficient():
    scored = [_entry("a", 10.0, 1), _entry("b", 0.0, 2), _entry("c", 0.0, 3)]
    rerank.apply_rerank(
        scored,
        _entities(a=["d1"], b=["d1"], c=["d2"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    # 'a' remains leader; the rare-domain 'c' legitimately overtakes the tied 'b'.
    assert _ordered(scored)[0] == "a"
    assert _ordered(scored) == ["a", "c", "b"]


def test_lower_candidate_overtakes_when_adjustment_sufficient():
    scored = [_entry("a", 0.6, 1), _entry("b", 0.0, 2), _entry("c", 0.0, 3)]
    rerank.apply_rerank(
        scored,
        _entities(a=["d1"], b=["d1"], c=["d2"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 2.0},
    )
    assert _ordered(scored) == ["c", "a", "b"]


def test_adjustment_emits_reason_code_only_when_positive():
    scored = [_entry("a", 0.0, 1), _entry("b", 0.0, 2), _entry("c", 0.0, 3)]
    rerank.apply_rerank(
        scored,
        _entities(a=["d1"], b=["d1"], c=["d2"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    by_id = {e["target_entity_id"]: e for e in scored}
    assert by_id["c"]["rerank_trace"]["reason_codes"] == ["DOMAIN_COVERAGE_ADJUSTMENT"]
    assert by_id["a"]["rerank_trace"]["reason_codes"] == []


def test_deterministic_ties_resolve_by_tiebreak_key():
    scored = [_entry("b", 0.0, 1), _entry("a", 0.0, 2)]
    rerank.apply_rerank(
        scored,
        _entities(a=["d1"], b=["d1"]),
        {"strategy": "DOMAIN_COVERAGE", "diversity_weight": 1.0},
    )
    assert _ordered(scored) == ["a", "b"]
