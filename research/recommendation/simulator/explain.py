"""Deterministic recommendation explanations (#48, m3-simulation/v5).

Implements the frozen v4 explanation contract (§15): contextual explanation-code
derivation from a #47 ``RankedCandidate`` and assembly of the #48
``RecommendationResult``. It reads only fields already present in the
``RankedCandidate``; it never rescores, reranks, applies ``top_k``, recomputes
eligibility, touches learner state/ontology, or produces human-readable prose.

Public API: :func:`build_recommendation_results`.
"""

from __future__ import annotations

import copy

#: Frozen v4 explanation vocabulary, in canonical order (§15). Emission iterates
#: this tuple, so results are deduplicated and canonically ordered by construction.
EXPLANATION_CODES = (
    "EXPLICIT_INTEREST_MATCH",
    "RELATED_TO_RECENT_EXPLORATION",
    "PREREQUISITES_SATISFIED",
    "GOOD_DIFFICULTY_FIT",
    "SEMANTICALLY_RELATED",
    "REVISIT_OPPORTUNITY",
    "DIVERSITY_ADJUSTMENT",
    "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED",
)

#: Inclusive v4 explanation threshold for ``GOOD_DIFFICULTY_FIT`` (§15.1).
_GOOD_DIFFICULTY_FIT_THRESHOLD = 0.8

#: #47-owned machine reason codes #48 maps to explanation codes (§11.3, §13.3).
_CONFLICT_REASON = "EXPLICIT_INFERRED_CONFLICT_SUPPRESSED"
_DIVERSITY_REASON = "DOMAIN_COVERAGE_ADJUSTMENT"

#: Exact frozen RecommendationResult field whitelist (§14). Output is constructed
#: from this whitelist so unrelated caller keys never leak into the schema.
_RESULT_FIELDS = (
    "candidate_id",
    "target_entity_id",
    "target_entity_version",
    "target_entity_type",
    "candidate_sources",
    "readiness_summary",
    "score_trace",
    "rerank_trace",
    "ordering_score",
    "deterministic_tiebreak_key",
    "final_rank",
)


def _applicable_codes(ranked_candidate: dict) -> set[str]:
    """Return the set of v4 explanation codes applicable to one RankedCandidate.

    Every rule is evaluated independently from frozen ``RankedCandidate``
    evidence; no rule short-circuits another. Configured weights and component
    scores are deliberately ignored (contextual, not rank-causal).
    """
    score_trace = ranked_candidate["score_trace"]
    feature_values = score_trace["feature_values"]
    candidate_sources = ranked_candidate["candidate_sources"]
    readiness_summary = ranked_candidate["readiness_summary"]
    score_reason_codes = score_trace["reason_codes"]
    rerank_reason_codes = ranked_candidate["rerank_trace"]["reason_codes"]

    applicable: set[str] = set()

    if feature_values["explicit_interest"] > 0.0:
        applicable.add("EXPLICIT_INTEREST_MATCH")

    if "HISTORY_CONTINUATION" in candidate_sources:
        applicable.add("RELATED_TO_RECENT_EXPLORATION")

    hard_total = readiness_summary["hard_prerequisites_total"]
    hard_satisfied = readiness_summary["hard_prerequisites_satisfied"]
    if (
        hard_total > 0
        and hard_satisfied == hard_total
        and readiness_summary["state"] == "SATISFIED"
    ):
        applicable.add("PREREQUISITES_SATISFIED")

    if feature_values["difficulty_fit"] >= _GOOD_DIFFICULTY_FIT_THRESHOLD:
        applicable.add("GOOD_DIFFICULTY_FIT")

    if feature_values["semantic_similarity"] > 0.0:
        applicable.add("SEMANTICALLY_RELATED")

    if "REVISIT" in candidate_sources:
        applicable.add("REVISIT_OPPORTUNITY")

    if _DIVERSITY_REASON in rerank_reason_codes:
        applicable.add("DIVERSITY_ADJUSTMENT")

    if _CONFLICT_REASON in score_reason_codes:
        applicable.add("EXPLICIT_PREFERENCE_OVERRIDES_INFERRED")

    return applicable


def build_recommendation_results(ranked_candidates: list[dict]) -> list[dict]:
    """Assemble ``RecommendationResult[]`` from ``RankedCandidate[]`` (#48, §14.3).

    Returns one fresh result per input candidate, ordered by ``final_rank``
    ascending. Input is never mutated and nested mutable structures are
    deep-copied, so results do not alias input containers. An empty input returns
    an empty list (IN-10). Ranks, ordering scores, and tiebreak keys are copied
    unchanged; #48 never reranks.
    """
    results: list[dict] = []
    for ranked_candidate in ranked_candidates:
        applicable = _applicable_codes(ranked_candidate)
        result = {
            field: copy.deepcopy(ranked_candidate[field]) for field in _RESULT_FIELDS
        }
        result["explanation_codes"] = [
            code for code in EXPLANATION_CODES if code in applicable
        ]
        results.append(result)

    results.sort(key=lambda result: result["final_rank"])
    return results
