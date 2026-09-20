"""Descriptive simulation metrics (#49, m3-simulation/v5).

Implements the thirteen frozen v5 metrics (§20.1). Metrics are descriptive only:
they never gate scenario or invariant status and carry no thresholds. Counts are
integers, shares are finite floats, and a zero denominator yields ``0.0``. Map
metrics always carry every frozen enum key, in canonical enum order, even when a
count is zero.
"""

from __future__ import annotations

from .eligibility import EXCLUSION_ORDER
from .identity import canonical_json
from .sources import CANDIDATE_SOURCES

#: Frozen #46 Candidate trace carriers for trace-completeness (§29).
CANDIDATE_TRACE_FIELDS = (
    "source_paths",
    "prerequisite_evaluations",
    "feature_inputs",
    "exclusion_reasons",
)

#: Frozen #48 RecommendationResult downstream trace carriers (§29).
RESULT_TRACE_FIELDS = (
    "candidate_sources",
    "readiness_summary",
    "score_trace",
    "rerank_trace",
    "ordering_score",
    "deterministic_tiebreak_key",
    "final_rank",
    "explanation_codes",
)


def _source_map() -> dict[str, int]:
    return {source: 0 for source in CANDIDATE_SOURCES}


def _exclusion_map() -> dict[str, int]:
    return {reason: 0 for reason in EXCLUSION_ORDER}


def _candidate_source_set(candidate: dict) -> set[str]:
    return {path["source"] for path in candidate["source_paths"]}


def result_is_trace_complete(rec: dict, candidate_by_id: dict[str, dict]) -> bool:
    """Return whether one RecommendationResult carries its full frozen trace.

    Shared by ``trace_completeness`` and IN-5. ``explanation_codes`` need not be
    non-empty. Absence of fields is the only failure condition.
    """
    candidate = candidate_by_id.get(rec["candidate_id"])
    if candidate is None:
        return False
    if any(field not in candidate for field in CANDIDATE_TRACE_FIELDS):
        return False
    return all(field in rec for field in RESULT_TRACE_FIELDS)


def compute_metrics(
    considered: list[dict],
    excluded: list[dict],
    full_ranked: list[dict],
    selected: list[dict],
) -> dict:
    """Return the thirteen frozen descriptive metrics for one simulation."""
    candidate_count = len(considered)
    eligible_candidate_count = sum(
        1 for candidate in considered if candidate["eligibility_state"] == "ELIGIBLE"
    )

    exclusion_count_by_reason = _exclusion_map()
    for candidate in excluded:
        for reason in set(candidate["exclusion_reasons"]):
            if reason in exclusion_count_by_reason:
                exclusion_count_by_reason[reason] += 1

    source_coverage = _source_map()
    for candidate in considered:
        for source in _candidate_source_set(candidate):
            source_coverage[source] += 1

    top_k_source_mix = _source_map()
    for result in selected:
        for source in set(result.get("candidate_sources", [])):
            top_k_source_mix[source] += 1

    domain_ids: set[str] = set()
    for result in selected:
        dimensions = result.get("rerank_trace", {}).get("diversity_dimensions") or {}
        domain_ids.update(dimensions.get("domain_ids", []))

    candidate_by_id = {candidate["candidate_id"]: candidate for candidate in considered}
    difficulty_distribution: dict[str, int] = {}
    for result in selected:
        candidate = candidate_by_id.get(result["candidate_id"])
        difficulty_prior = (
            candidate["feature_inputs"].get("difficulty_prior")
            if candidate is not None
            else None
        )
        key = canonical_json(difficulty_prior)
        difficulty_distribution[key] = difficulty_distribution.get(key, 0) + 1

    explicit_interest_coverage = _coverage(
        sum(1 for c in considered if "EXPLICIT_INTEREST" in _candidate_source_set(c)),
        candidate_count,
    )
    semantic_candidate_coverage = _coverage(
        sum(1 for c in considered if "SEMANTIC" in _candidate_source_set(c)),
        candidate_count,
    )
    revisit_share = _coverage(
        sum(
            1
            for r in selected
            if "REVISIT" in set(r.get("candidate_sources", []))
        ),
        len(selected),
    )
    continuation_share = _coverage(
        sum(
            1
            for r in selected
            if "HISTORY_CONTINUATION" in set(r.get("candidate_sources", []))
        ),
        len(selected),
    )

    rank_change_due_to_diversity = sum(
        1
        for entry in full_ranked
        if entry["rerank_trace"]["pre_rerank_rank"]
        != entry["rerank_trace"]["post_rerank_rank"]
    )

    trace_completeness = _coverage(
        sum(1 for r in selected if result_is_trace_complete(r, candidate_by_id)),
        len(selected),
    )

    return {
        "candidate_count": candidate_count,
        "eligible_candidate_count": eligible_candidate_count,
        "exclusion_count_by_reason": exclusion_count_by_reason,
        "source_coverage": source_coverage,
        "top_k_source_mix": top_k_source_mix,
        "topic_domain_diversity": len(domain_ids),
        "difficulty_distribution": difficulty_distribution,
        "explicit_interest_coverage": explicit_interest_coverage,
        "semantic_candidate_coverage": semantic_candidate_coverage,
        "revisit_share": revisit_share,
        "continuation_share": continuation_share,
        "rank_change_due_to_diversity": rank_change_due_to_diversity,
        "trace_completeness": trace_completeness,
    }


def _coverage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
