"""Shared synthetic ``RankedCandidate`` builder for #48 explanation tests.

Builds a complete, schema-shaped #47 ``RankedCandidate`` dictionary with sensible
neutral defaults so individual tests can override only the evidence they
exercise. This is a contract-test fixture, not a recommendation engine.
"""

from __future__ import annotations

FEATURE_DEFAULTS = {
    "readiness": 0.0,
    "difficulty_fit": 0.0,
    "explicit_interest": 0.0,
    "inferred_interest": 0.0,
    "graph_proximity": 0.0,
    "semantic_similarity": 0.0,
    "continuation_value": 0.0,
    "revisit_value": 0.0,
}


def ranked_candidate(
    *,
    candidate_id: str = "cand:TOPIC:20000000-0000-4000-8000-000000000001:1",
    target_entity_id: str = "20000000-0000-4000-8000-000000000001",
    target_entity_version: int = 1,
    target_entity_type: str = "TOPIC",
    candidate_sources: list[str] | None = None,
    hard_prerequisites_total: int = 0,
    hard_prerequisites_satisfied: int = 0,
    readiness_state: str = "SATISFIED",
    feature_values: dict | None = None,
    configured_weights: dict | None = None,
    component_scores: dict | None = None,
    score_reason_codes: list[str] | None = None,
    rerank_reason_codes: list[str] | None = None,
    diversity_adjustment: float = 0.0,
    final_rank: int = 1,
    ordering_score: float = 0.0,
    deterministic_tiebreak_key: str | None = None,
    extra_keys: dict | None = None,
) -> dict:
    features = dict(FEATURE_DEFAULTS)
    features.update(feature_values or {})
    weights = {name: 0.0 for name in FEATURE_DEFAULTS}
    weights.update(configured_weights or {})
    components = {name: 0.0 for name in FEATURE_DEFAULTS}
    components.update(component_scores or {})
    pre_rerank_score = sum(components.values())
    tiebreak = (
        deterministic_tiebreak_key
        if deterministic_tiebreak_key is not None
        else f"{target_entity_type}:{target_entity_id}:{target_entity_version}"
    )

    candidate = {
        "candidate_id": candidate_id,
        "target_entity_id": target_entity_id,
        "target_entity_version": target_entity_version,
        "target_entity_type": target_entity_type,
        "candidate_sources": list(candidate_sources or []),
        "readiness_summary": {
            "hard_prerequisites_total": hard_prerequisites_total,
            "hard_prerequisites_satisfied": hard_prerequisites_satisfied,
            "state": readiness_state,
        },
        "score_trace": {
            "feature_values": features,
            "configured_weights": weights,
            "component_scores": components,
            "pre_rerank_score": pre_rerank_score,
            "reason_codes": list(score_reason_codes or []),
        },
        "rerank_trace": {
            "pre_rerank_rank": final_rank,
            "pre_rerank_score": pre_rerank_score,
            "diversity_dimensions": {},
            "diversity_adjustment": diversity_adjustment,
            "post_rerank_rank": final_rank,
            "reason_codes": list(rerank_reason_codes or []),
        },
        "ordering_score": ordering_score,
        "deterministic_tiebreak_key": tiebreak,
        "final_rank": final_rank,
    }
    if extra_keys:
        candidate.update(extra_keys)
    return candidate
