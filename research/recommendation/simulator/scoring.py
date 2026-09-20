"""Interpretable scoring and candidate ranking (#47, m3-simulation/v5).

Implements the frozen v3 scoring features, additive aggregation, ``ScoreTrace``,
``readiness_summary``, deterministic pre-rerank ordering, and the public
``rank_candidates`` orchestration. It does not emit #48 explanation codes or #49
SimulationResult/metrics/top_k selection.
"""

from __future__ import annotations

import math

from .rerank import apply_rerank
from .sources import CANDIDATE_SOURCES
from .validation import SCORING_FEATURES, SimulationInputError, validate_simulation_input

_SOURCE_INDEX = {source: index for index, source in enumerate(CANDIDATE_SOURCES)}

#: Frozen explicit-preference raw values (§11.2).
_EXPLICIT_VALUES = {"MORE": 1.0, "NEUTRAL": 0.0, "LESS": -1.0}
#: Preferences #46 always hard-excludes; must never reach eligible scoring.
_HARD_EXCLUDING = frozenset({"PAUSED", "NOT_INTERESTED"})
#: #47-owned ScoreTrace reason code (§11.3).
_CONFLICT_REASON = "EXPLICIT_INFERRED_CONFLICT_SUPPRESSED"


def _entities_by_key(simulation_input: dict) -> dict[tuple[str, int], dict]:
    return {
        (entity["entity_id"], entity["entity_version"]): entity
        for entity in simulation_input["ontology_snapshot"]["entities"]
    }


def _interest_states_by_key(simulation_input: dict) -> dict[tuple[str, int], dict]:
    return {
        (state["entity_id"], state["entity_version"]): state
        for state in simulation_input["learner_state_snapshot"]["interest_states"]
    }


def effective_weights(simulation_input: dict) -> dict[str, float]:
    """Return the effective weight for all eight features; missing -> 0.0.

    There are no hidden defaults; weights are not normalized (§8).
    """
    configured = simulation_input["simulation_config"].get("feature_weights", {})
    return {feature: float(configured.get(feature, 0.0)) for feature in SCORING_FEATURES}


def _readiness(candidate: dict) -> float:
    evaluations = candidate["prerequisite_evaluations"]
    if not evaluations:
        return 0.0
    satisfied = sum(1 for evaluation in evaluations if evaluation["state"] == "SATISFIED")
    return satisfied / len(evaluations)


def _difficulty_fit(candidate: dict, entity: dict | None, challenge: dict | None) -> float:
    if entity is None or challenge is None:
        return 0.0
    difficulty_prior = entity.get("difficulty_prior")
    if difficulty_prior is None:
        return 0.0
    if challenge["area_id"] not in entity.get("domain_ids", []):
        return 0.0
    return 1.0 - abs(difficulty_prior - challenge["ability_estimate"])


def _explicit_interest(candidate: dict) -> float:
    preference = candidate["feature_inputs"].get("explicit_preference")
    if preference is None:
        return 0.0
    if preference in _HARD_EXCLUDING:
        raise SimulationInputError(
            f"eligible candidate exposes hard-excluding preference {preference!r}"
        )
    try:
        return _EXPLICIT_VALUES[preference]
    except KeyError:
        raise SimulationInputError(f"unknown explicit preference {preference!r}") from None


def _inferred_interest(state: dict | None) -> float:
    if state is None:
        return 0.0
    return (state["recent_affinity"] + state["long_term_affinity"]) / 2.0


def _graph_proximity(candidate: dict) -> float:
    proximities: list[float] = []
    for path in candidate["source_paths"]:
        if path["source"] != "GRAPH":
            continue
        hop_distance = path["provenance"]["hop_distance"]
        if hop_distance < 1:
            raise SimulationInputError(
                f"GRAPH hop_distance must be >= 1, got {hop_distance!r}"
            )
        proximities.append(1.0 / hop_distance)
    return max(proximities) if proximities else 0.0


def _semantic_similarity(candidate: dict) -> float:
    cosines = [
        path["provenance"]["cosine_similarity"]
        for path in candidate["source_paths"]
        if path["source"] == "SEMANTIC"
    ]
    return max(cosines) if cosines else 0.0


def _has_source(candidate: dict, source: str) -> bool:
    return any(path["source"] == source for path in candidate["source_paths"])


def _assert_hard_prerequisites_satisfied(candidate: dict) -> None:
    """Eligible candidates must have every HARD prerequisite SATISFIED (§14.2).

    An ELIGIBLE candidate with an UNSATISFIED/UNKNOWN HARD prerequisite is
    inconsistent #46 output and must not be silently ranked.
    """
    for evaluation in candidate["prerequisite_evaluations"]:
        if evaluation["requirement"] == "HARD" and evaluation["state"] != "SATISFIED":
            raise SimulationInputError(
                "eligible candidate has non-satisfied HARD prerequisite "
                f"{evaluation['prerequisite_entity_id']!r} "
                f"in state {evaluation['state']!r}"
            )


def _readiness_summary(candidate: dict) -> dict:
    hard = [
        evaluation
        for evaluation in candidate["prerequisite_evaluations"]
        if evaluation["requirement"] == "HARD"
    ]
    return {
        "hard_prerequisites_total": len(hard),
        "hard_prerequisites_satisfied": sum(
            1 for evaluation in hard if evaluation["state"] == "SATISFIED"
        ),
        "state": "SATISFIED",
    }


def _candidate_sources(candidate: dict) -> list[str]:
    sources = {path["source"] for path in candidate["source_paths"]}
    return sorted(sources, key=lambda source: _SOURCE_INDEX[source])


def _tiebreak_key(candidate: dict) -> str:
    entity_type = candidate["target_entity_type"]
    if entity_type is None:
        raise SimulationInputError("eligible candidate has null target_entity_type")
    return (
        f"{entity_type}:{candidate['target_entity_id']}:"
        f"{candidate['target_entity_version']}"
    )


def score_candidate(
    candidate: dict,
    entity: dict | None,
    interest_state: dict | None,
    challenge: dict | None,
    weights: dict[str, float],
) -> dict:
    """Compute the frozen v3 features, components, and ``ScoreTrace`` for one candidate."""
    _assert_hard_prerequisites_satisfied(candidate)
    feature_values = {
        "readiness": _readiness(candidate),
        "difficulty_fit": _difficulty_fit(candidate, entity, challenge),
        "explicit_interest": _explicit_interest(candidate),
        "inferred_interest": _inferred_interest(interest_state),
        "graph_proximity": _graph_proximity(candidate),
        "semantic_similarity": _semantic_similarity(candidate),
        "continuation_value": 1.0
        if _has_source(candidate, "HISTORY_CONTINUATION")
        else 0.0,
        "revisit_value": 1.0 if _has_source(candidate, "REVISIT") else 0.0,
    }

    explicit = feature_values["explicit_interest"]
    inferred = feature_values["inferred_interest"]
    conflict = (explicit > 0 and inferred < 0) or (explicit < 0 and inferred > 0)

    effective = dict(feature_values)
    if conflict:
        effective["inferred_interest"] = 0.0

    component_scores = {
        feature: weights[feature] * effective[feature] for feature in SCORING_FEATURES
    }
    pre_rerank_score = sum(component_scores.values())
    if not math.isfinite(pre_rerank_score):
        raise SimulationInputError("pre_rerank_score is not finite")

    return {
        "candidate_id": candidate["candidate_id"],
        "target_entity_id": candidate["target_entity_id"],
        "target_entity_version": candidate["target_entity_version"],
        "target_entity_type": candidate["target_entity_type"],
        "deterministic_tiebreak_key": _tiebreak_key(candidate),
        "candidate_sources": _candidate_sources(candidate),
        "readiness_summary": _readiness_summary(candidate),
        "score_trace": {
            "feature_values": feature_values,
            "configured_weights": dict(weights),
            "component_scores": component_scores,
            "pre_rerank_score": pre_rerank_score,
            "reason_codes": [_CONFLICT_REASON] if conflict else [],
        },
        "pre_rerank_score": pre_rerank_score,
    }


def rank_candidates(simulation_input: dict, candidates: list[dict]) -> list[dict]:
    """Return the full ranked eligible candidate list (#47, §14.1).

    Inputs are never mutated. Ineligible candidates are ignored and never
    returned; #49 combines them with this ranked list. ``top_k`` is not applied.
    """
    validate_simulation_input(simulation_input)

    eligible = [
        candidate
        for candidate in candidates
        if candidate["eligibility_state"] == "ELIGIBLE"
    ]
    if not eligible:
        return []

    entities = _entities_by_key(simulation_input)
    interest_states = _interest_states_by_key(simulation_input)
    challenge = simulation_input["learner_state_snapshot"].get("challenge_state")
    weights = effective_weights(simulation_input)

    scored: list[dict] = []
    for candidate in eligible:
        key = (candidate["target_entity_id"], candidate["target_entity_version"])
        entity = entities.get(key)
        if entity is None:
            raise SimulationInputError(
                f"eligible candidate {key!r} does not resolve in ontology"
            )
        if entity["entity_type"] != candidate["target_entity_type"]:
            raise SimulationInputError(
                f"eligible candidate {key!r} target_entity_type "
                f"{candidate['target_entity_type']!r} does not match ontology "
                f"entity_type {entity['entity_type']!r}"
            )
        scored.append(
            score_candidate(
                candidate,
                entity,
                interest_states.get(key),
                challenge,
                weights,
            )
        )

    scored.sort(
        key=lambda entry: (
            -entry["pre_rerank_score"],
            entry["deterministic_tiebreak_key"],
        )
    )
    for rank, entry in enumerate(scored, start=1):
        entry["pre_rerank_rank"] = rank

    apply_rerank(scored, entities, simulation_input["simulation_config"].get("rerank"))

    return [_result(entry) for entry in scored]


def _result(entry: dict) -> dict:
    """Project the frozen #47 ``RankedCandidate`` shape (§14.2)."""
    return {
        "candidate_id": entry["candidate_id"],
        "target_entity_id": entry["target_entity_id"],
        "target_entity_version": entry["target_entity_version"],
        "target_entity_type": entry["target_entity_type"],
        "candidate_sources": entry["candidate_sources"],
        "readiness_summary": entry["readiness_summary"],
        "score_trace": entry["score_trace"],
        "rerank_trace": entry["rerank_trace"],
        "ordering_score": entry["ordering_score"],
        "deterministic_tiebreak_key": entry["deterministic_tiebreak_key"],
        "final_rank": entry["final_rank"],
    }
