"""Hard eligibility and exclusion collection (§16, §22-§25).

Collects every applicable exclusion reason (no short-circuit) and serializes in
the frozen enum order. Does not compute #47 scoring features.
"""

from __future__ import annotations

#: Frozen exclusion-reason order (§4, §16).
EXCLUSION_ORDER = (
    "PREREQUISITE_UNMET",
    "EXPLICITLY_PAUSED",
    "NOT_INTERESTED",
    "INVALID_TARGET",
    "INSUFFICIENT_STATE",
)

#: Explicit preferences that hard-exclude the entity (§10, §22).
HARD_EXCLUDING_PREFERENCES = {"PAUSED": "EXPLICITLY_PAUSED", "NOT_INTERESTED": "NOT_INTERESTED"}


def collect_exclusion_reasons(
    entity: dict | None,
    explicit_preference: str | None,
    prerequisite_evaluations: list[dict],
) -> list[str]:
    reasons: set[str] = set()
    if entity is None:
        reasons.add("INVALID_TARGET")
    hard_reason = (
        HARD_EXCLUDING_PREFERENCES.get(explicit_preference)
        if explicit_preference is not None
        else None
    )
    if hard_reason is not None:
        reasons.add(hard_reason)
    for evaluation in prerequisite_evaluations:
        if evaluation["requirement"] != "HARD":
            continue
        if evaluation["state"] == "UNSATISFIED":
            reasons.add("PREREQUISITE_UNMET")
        elif evaluation["state"] == "UNKNOWN":
            reasons.add("INSUFFICIENT_STATE")
    return [reason for reason in EXCLUSION_ORDER if reason in reasons]


def build_feature_inputs(
    entity: dict | None,
    explicit_preference: str | None,
    prerequisite_evaluations: list[dict],
) -> dict:
    """Raw #46-owned inputs only; no #47 scoring features."""
    feature_inputs: dict = {}
    if entity is not None:
        feature_inputs["difficulty_prior"] = entity["difficulty_prior"]
    if explicit_preference is not None:
        feature_inputs["explicit_preference"] = explicit_preference
    if prerequisite_evaluations:
        feature_inputs["hard_prerequisite_count"] = sum(
            1 for evaluation in prerequisite_evaluations if evaluation["requirement"] == "HARD"
        )
        feature_inputs["soft_prerequisite_count"] = sum(
            1 for evaluation in prerequisite_evaluations if evaluation["requirement"] == "SOFT"
        )
        feature_inputs["satisfied_prerequisite_count"] = sum(
            1 for evaluation in prerequisite_evaluations if evaluation["state"] == "SATISFIED"
        )
        feature_inputs["unsatisfied_prerequisite_count"] = sum(
            1 for evaluation in prerequisite_evaluations if evaluation["state"] == "UNSATISFIED"
        )
        feature_inputs["unknown_prerequisite_count"] = sum(
            1 for evaluation in prerequisite_evaluations if evaluation["state"] == "UNKNOWN"
        )
    return feature_inputs


def build_candidate(
    normalized: dict,
    entity: dict | None,
    explicit_preference: str | None,
    prerequisite_evaluations: list[dict],
) -> dict:
    """Assemble a normalized Candidate with eligibility (§8, §8.3)."""
    exclusion_reasons = collect_exclusion_reasons(
        entity, explicit_preference, prerequisite_evaluations
    )
    return {
        "candidate_id": normalized["candidate_id"],
        "target_entity_id": normalized["target_entity_id"],
        "target_entity_version": normalized["target_entity_version"],
        "target_entity_type": entity["entity_type"] if entity is not None else None,
        "source_paths": normalized["source_paths"],
        "prerequisite_evaluations": prerequisite_evaluations,
        "eligibility_state": "ELIGIBLE" if not exclusion_reasons else "INELIGIBLE",
        "exclusion_reasons": exclusion_reasons,
        "feature_inputs": build_feature_inputs(
            entity, explicit_preference, prerequisite_evaluations
        ),
    }
