"""Shared synthetic ``CoreExecution`` builders for #49 runner tests.

These build minimal contract-shaped populations directly, so invariant and metric
unit tests can force specific outcomes without corrupting #46/#47/#48 code. This
is a contract-test helper, not a simulation engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from research.recommendation.simulator.run import CoreExecution


def candidate(
    candidate_id: str,
    entity_id: str = "e1",
    *,
    entity_type: str = "TOPIC",
    eligibility: str = "ELIGIBLE",
    exclusion_reasons=(),
    prerequisite_evaluations=(),
    sources=("GRAPH",),
    difficulty_prior: float | None = 0.5,
) -> dict:
    feature_inputs: dict = {}
    if difficulty_prior is not None:
        feature_inputs["difficulty_prior"] = difficulty_prior
    return {
        "candidate_id": candidate_id,
        "target_entity_id": entity_id,
        "target_entity_version": 1,
        "target_entity_type": entity_type,
        "source_paths": [
            {"source": source, "provenance": {}} for source in sources
        ],
        "prerequisite_evaluations": list(prerequisite_evaluations),
        "eligibility_state": eligibility,
        "exclusion_reasons": list(exclusion_reasons),
        "feature_inputs": feature_inputs,
    }


def hard_prerequisite(state: str, prerequisite_entity_id: str = "p1") -> dict:
    return {
        "objective_id": "o1",
        "prerequisite_entity_id": prerequisite_entity_id,
        "requirement": "HARD",
        "evidence_summary": {},
        "state": state,
        "reason_codes": [],
    }


def ranked(
    candidate_id: str,
    entity_id: str = "e1",
    *,
    rank: int = 1,
    pre_rerank_rank: int | None = None,
    post_rerank_rank: int | None = None,
    sources=("GRAPH",),
) -> dict:
    return {
        "candidate_id": candidate_id,
        "target_entity_id": entity_id,
        "target_entity_version": 1,
        "target_entity_type": "TOPIC",
        "candidate_sources": list(sources),
        "final_rank": rank,
        "score_trace": {
            "feature_values": {},
            "configured_weights": {},
            "component_scores": {"inferred_interest": 0.0},
            "pre_rerank_score": 0.0,
            "reason_codes": [],
        },
        "rerank_trace": {
            "pre_rerank_rank": rank if pre_rerank_rank is None else pre_rerank_rank,
            "pre_rerank_score": 0.0,
            "diversity_dimensions": {},
            "diversity_adjustment": 0.0,
            "post_rerank_rank": rank if post_rerank_rank is None else post_rerank_rank,
            "reason_codes": [],
        },
        "deterministic_tiebreak_key": f"TOPIC:{entity_id}:1",
    }


def explanation(
    candidate_id: str,
    entity_id: str = "e1",
    *,
    rank: int = 1,
    pre_rerank_rank: int | None = None,
    post_rerank_rank: int | None = None,
    sources=("GRAPH",),
    explanation_codes=(),
    conflict: bool = False,
) -> dict:
    entry = ranked(
        candidate_id,
        entity_id,
        rank=rank,
        pre_rerank_rank=pre_rerank_rank,
        post_rerank_rank=post_rerank_rank,
        sources=sources,
    )
    entry["readiness_summary"] = {
        "hard_prerequisites_total": 0,
        "hard_prerequisites_satisfied": 0,
        "state": "SATISFIED",
    }
    entry["ordering_score"] = 0.0
    entry["explanation_codes"] = list(explanation_codes)
    if conflict:
        entry["score_trace"]["reason_codes"] = ["EXPLICIT_INFERRED_CONFLICT_SUPPRESSED"]
    return entry


def core(
    considered: list[dict],
    *,
    full_ranked: list[dict] | None = None,
    explanations: list[dict] | None = None,
    selected: list[dict] | None = None,
    eligible_count: int | None = None,
) -> "CoreExecution":
    from research.recommendation.simulator.run import CoreExecution

    excluded = [
        item for item in considered if item["eligibility_state"] == "INELIGIBLE"
    ]
    explanations = [] if explanations is None else explanations
    selected = explanations if selected is None else selected
    if eligible_count is None:
        eligible_count = sum(
            1 for item in considered if item["eligibility_state"] == "ELIGIBLE"
        )
    return CoreExecution(
        candidates_considered=considered,
        candidates_excluded=excluded,
        full_ranked_candidates=[] if full_ranked is None else full_ranked,
        full_recommendation_results=explanations,
        selected_recommendations=selected,
        metrics={"eligible_candidate_count": eligible_count},
    )
