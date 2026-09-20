"""Contract-shaped builders for the M3 simulation fixture corpus.

Four learner-signal domains are kept separate on purpose:

* ``preference_snapshot.explicit_preferences`` -> explicit user intent
  (``explicit_interest_preferences``).
* ``learner_state_snapshot.interest_states`` -> inferred interest / affinity
  (``learner_interest_state``, LLD §27). Never derived from objective state.
* ``learner_state_snapshot.objective_states`` -> understanding / readiness
  evidence (``learner_objective_state``).
* ``learner_state_snapshot.challenge_state`` -> ability / challenge context
  (``learner_challenge_state``).

Builders are pure and deterministic: they read no clock, random source,
network, or database. They return plain contract-shaped dictionaries.

Contract note: the frozen §5 ``LearnerStateSnapshot`` enumerates
``objective_states`` and ``challenge_state`` but does not name an input
representation for inferred interest, even though §10/§11 require explicit and
inferred interest to stay separate. ``interest_states`` is added additively from
the authoritative LLD §27 ``learner_interest_state`` domain; no frozen field or
semantic is altered.
"""

from __future__ import annotations

import math

from .canonical import (
    sort_anchor_entities,
    sort_domain_ids,
    sort_entities,
    sort_explicit_preferences,
    sort_explorations,
    sort_interest_states,
    sort_objective_states,
    sort_relationships,
    sort_vectors,
)
from .semantic import EMBEDDING_MODEL, VECTOR_DIMENSION, semantic_vector
from .timestamps import sim_time

CONTRACT_VERSION = "m3-simulation/v5"
CONFIG_VERSION = "m3-sim-config/v1"
UNKNOWN_PREREQUISITE_POLICY = "CONSERVATIVE_INELIGIBLE"
INTEREST_MODEL_VERSION = "fixture-interest-state/v1"

ENTITY_TYPES = frozenset(
    {"DOMAIN", "AREA", "TOPIC", "CONCEPT", "SKILL", "TECHNIQUE", "JOURNEY"}
)
RELATIONSHIP_TYPES = frozenset({"REQUIRES", "BUILDS_ON", "PART_OF", "RELATED_TO"})
PREREQUISITE_REQUIREMENTS = frozenset({"HARD", "SOFT"})
EXPLICIT_PREFERENCES = frozenset({"NEUTRAL", "MORE", "LESS", "PAUSED", "NOT_INTERESTED"})
OBJECTIVE_STATES = frozenset(
    {"ENCOUNTERED", "EXPLORING", "DEVELOPING", "UNDERSTOOD", "REVISITING", "RETAINED", "PAUSED"}
)
LEARNING_INTENTS = frozenset(
    {
        "DIRECT_INTEREST",
        "PREREQUISITE_SUPPORT",
        "RELATED_EXPLORATION",
        "RETENTION_REVISIT",
        "PRACTICAL_SUPPORT",
        "SERENDIPITY",
    }
)
EXPLORATION_STATUSES = frozenset({"ACTIVE", "PAUSED", "COMPLETED"})

#: Frozen contract vocabularies (§8, §15, §16), in frozen enum order.
CANDIDATE_SOURCES = (
    "GRAPH",
    "SEMANTIC",
    "EXPLICIT_INTEREST",
    "HISTORY_CONTINUATION",
    "REVISIT",
)
EXCLUSION_CODES = (
    "PREREQUISITE_UNMET",
    "EXPLICITLY_PAUSED",
    "NOT_INTERESTED",
    "INVALID_TARGET",
    "INSUFFICIENT_STATE",
)
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
#: v3 scoring features (§11.1). Exactly these eight, in canonical order.
FEATURES = (
    "readiness",
    "difficulty_fit",
    "explicit_interest",
    "inferred_interest",
    "graph_proximity",
    "semantic_similarity",
    "continuation_value",
    "revisit_value",
)

#: Aliases used by the v3 scoring contract.
SCORING_FEATURES = FEATURES
#: Deferred beyond M3 v3; not a scoring feature.
DEFERRED_FEATURES = ("novelty",)
#: Trace-only; not a scoring feature or weight key.
TRACE_ONLY_FEATURES = ("diversity_context",)

#: Frozen rerank strategy vocabulary (§13.1).
RERANK_STRATEGIES = ("DOMAIN_COVERAGE",)
#: #47-owned ScoreTrace reason codes (§11.3).
SCORING_REASON_CODES = ("EXPLICIT_INFERRED_CONFLICT_SUPPRESSED",)
#: #47-owned RerankTrace reason codes (§13.3).
DIVERSITY_REASON_CODES = ("DOMAIN_COVERAGE_ADJUSTMENT",)


def learner(learner_id: str) -> dict:
    return {"learner_id": learner_id, "synthetic": True}


def entity_ref(entity_id: str, entity_version: int) -> dict:
    return {"entity_id": entity_id, "entity_version": int(entity_version)}


def candidate_generation_context(anchor_entities: list[dict] | tuple[dict, ...]) -> dict:
    """Simulation query context: explicit GRAPH/SEMANTIC anchors.

    Anchors are query-context declarations, never learner-state facts. They are
    unique by ``(entity_id, entity_version)`` and canonically sorted.
    """
    anchors = list(anchor_entities)
    keys = [(anchor["entity_id"], anchor["entity_version"]) for anchor in anchors]
    if len(keys) != len(set(keys)):
        raise ValueError("anchor_entities must be unique by (entity_id, entity_version)")
    return {"anchor_entities": sort_anchor_entities(anchors)}


def relationship(
    relationship_type: str,
    target_entity_id: str,
    target_entity_version: int,
    requirement: str | None = None,
    objective_id: str | None = None,
) -> dict:
    if relationship_type not in RELATIONSHIP_TYPES:
        raise ValueError(f"unknown relationship_type: {relationship_type!r}")
    if relationship_type == "REQUIRES":
        if requirement not in PREREQUISITE_REQUIREMENTS:
            raise ValueError("REQUIRES relationships need a HARD or SOFT requirement")
        if not objective_id:
            raise ValueError("REQUIRES relationships need an objective_id")
    else:
        if requirement is not None:
            raise ValueError("requirement is only valid for REQUIRES relationships")
        if objective_id is not None:
            raise ValueError("objective_id is only valid for REQUIRES relationships")
    return {
        "relationship_type": relationship_type,
        "target_entity_id": target_entity_id,
        "target_entity_version": target_entity_version,
        "requirement": requirement,
        "objective_id": objective_id,
    }


def entity(
    entity_id: str,
    entity_version: int,
    entity_type: str,
    title: str,
    *,
    domain_ids: list[str] | tuple[str, ...] = (),
    relationships: list[dict] | tuple[dict, ...] = (),
    objective_ids: list[str] | tuple[str, ...] = (),
    difficulty_prior: float = 0.5,
    estimated_effort_minutes: int = 15,
) -> dict:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unknown entity_type: {entity_type!r}")
    return {
        "entity_id": entity_id,
        "entity_version": entity_version,
        "entity_type": entity_type,
        "title": title,
        "domain_ids": sort_domain_ids(list(domain_ids)),
        "relationships": sort_relationships(list(relationships)),
        "objective_ids": sorted(objective_ids),
        "difficulty_prior": float(difficulty_prior),
        "estimated_effort_minutes": int(estimated_effort_minutes),
    }


def ontology_snapshot(snapshot_version: str, entities: list[dict]) -> dict:
    return {"snapshot_version": snapshot_version, "entities": sort_entities(list(entities))}


def objective_state(
    objective_id: str,
    entity_id: str,
    state: str,
    understanding_estimate: float | None = None,
    *,
    entity_version: int,
) -> dict:
    if state not in OBJECTIVE_STATES:
        raise ValueError(f"unknown objective state: {state!r}")
    if not isinstance(entity_version, int) or entity_version < 1:
        raise ValueError("objective state entity_version must be a positive integer")
    entry: dict = {
        "objective_id": objective_id,
        "entity_id": entity_id,
        "entity_version": int(entity_version),
        "state": state,
    }
    if understanding_estimate is not None:
        entry["understanding_estimate"] = float(understanding_estimate)
    return entry


def interest_state(
    entity_id: str,
    entity_version: int,
    *,
    recent_affinity: float,
    long_term_affinity: float,
    user_initiated_strength: float,
    algorithm_exposure_strength: float,
    voluntary_revisit_count: int = 0,
    last_interaction_at: str | None = None,
    computed_at: str | None = None,
    model_version: str = INTEREST_MODEL_VERSION,
) -> dict:
    """Inferred interest / affinity for one entity.

    Simulation analogue of the LLD §27 ``learner_interest_state`` domain. Field
    names follow the LLD/migration domain; ``entity_version`` is added because
    simulation entities are versioned.
    """
    if voluntary_revisit_count < 0:
        raise ValueError("voluntary_revisit_count must be >= 0")
    return {
        "entity_id": entity_id,
        "entity_version": entity_version,
        "recent_affinity": float(recent_affinity),
        "long_term_affinity": float(long_term_affinity),
        "user_initiated_strength": float(user_initiated_strength),
        "algorithm_exposure_strength": float(algorithm_exposure_strength),
        "voluntary_revisit_count": int(voluntary_revisit_count),
        "last_interaction_at": last_interaction_at,
        "computed_at": computed_at or sim_time(0),
        "model_version": model_version,
    }


def challenge_state(area_id: str, ability_estimate: float) -> dict:
    return {"area_id": area_id, "ability_estimate": float(ability_estimate)}


def learner_state_snapshot(
    snapshot_version: str,
    *,
    objective_states: list[dict] | tuple[dict, ...] = (),
    interest_states: list[dict] | tuple[dict, ...] = (),
    challenge_state: dict | None = None,
) -> dict:
    return {
        "snapshot_version": snapshot_version,
        "objective_states": sort_objective_states(list(objective_states)),
        "interest_states": sort_interest_states(list(interest_states)),
        "challenge_state": challenge_state,
    }


def explicit_preference(
    entity_id: str, preference: str, version: int = 1, *, entity_version: int
) -> dict:
    if preference not in EXPLICIT_PREFERENCES:
        raise ValueError(f"unknown explicit preference: {preference!r}")
    if version < 1:
        raise ValueError("preference version must be >= 1")
    if not isinstance(entity_version, int) or entity_version < 1:
        raise ValueError("explicit preference entity_version must be a positive integer")
    return {
        "entity_id": entity_id,
        "entity_version": int(entity_version),
        "preference": preference,
        "version": int(version),
    }


def preference_snapshot(snapshot_version: str, explicit_preferences: list[dict]) -> dict:
    return {
        "snapshot_version": snapshot_version,
        "explicit_preferences": sort_explicit_preferences(list(explicit_preferences)),
    }


def exploration(
    exploration_id: str,
    entity_id: str,
    entity_version: int,
    learning_intent: str,
    status: str,
    *,
    started_at: str | None = None,
    returned_at: str | None = None,
    completed_at: str | None = None,
    paused_at: str | None = None,
) -> dict:
    if learning_intent not in LEARNING_INTENTS:
        raise ValueError(f"unknown learning_intent: {learning_intent!r}")
    if status not in EXPLORATION_STATUSES:
        raise ValueError(f"unknown exploration status: {status!r}")
    return {
        "exploration_id": exploration_id,
        "entity_id": entity_id,
        "entity_version": entity_version,
        "learning_intent": learning_intent,
        "status": status,
        "started_at": started_at,
        "returned_at": returned_at,
        "completed_at": completed_at,
        "paused_at": paused_at,
    }


def exploration_history(snapshot_version: str, explorations: list[dict]) -> dict:
    return {"snapshot_version": snapshot_version, "explorations": sort_explorations(list(explorations))}


def semantic_space(snapshot_version: str, vectors: list[dict]) -> dict:
    for entry in vectors:
        vector = entry.get("vector", [])
        if len(vector) != VECTOR_DIMENSION:
            raise ValueError(
                f"semantic vectors must have dimension {VECTOR_DIMENSION}, got {len(vector)}"
            )
    return {
        "snapshot_version": snapshot_version,
        "embedding_model": EMBEDDING_MODEL,
        "vector_dimension": VECTOR_DIMENSION,
        "vectors": sort_vectors(list(vectors)),
    }


def rerank_config(strategy: str = "DOMAIN_COVERAGE", *, diversity_weight: float) -> dict:
    """Build a v3 RerankConfig (frozen DOMAIN_COVERAGE strategy, §13.1)."""
    if strategy not in RERANK_STRATEGIES:
        raise ValueError(f"unknown rerank strategy: {strategy!r}")
    if not math.isfinite(diversity_weight) or diversity_weight < 0:
        raise ValueError("diversity_weight must be finite and >= 0")
    return {"strategy": strategy, "diversity_weight": float(diversity_weight)}


def validate_feature_weights(feature_weights: dict[str, float]) -> dict:
    for key, value in feature_weights.items():
        if key not in FEATURES:
            raise ValueError(f"unknown feature weight key: {key!r}")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"feature weight {key!r} must be finite and >= 0")
    return {key: float(value) for key, value in feature_weights.items()}


def simulation_config(
    *,
    top_k: int = 5,
    feature_weights: dict[str, float] | None = None,
    rerank: dict | None = None,
    config_version: str = CONFIG_VERSION,
    unknown_prerequisite_policy: str = UNKNOWN_PREREQUISITE_POLICY,
) -> dict:
    if unknown_prerequisite_policy != UNKNOWN_PREREQUISITE_POLICY:
        raise ValueError("unknown_prerequisite_policy is frozen to CONSERVATIVE_INELIGIBLE")
    if rerank is not None:
        if rerank.get("strategy") not in RERANK_STRATEGIES:
            raise ValueError(f"unknown rerank strategy: {rerank.get('strategy')!r}")
        diversity_weight = rerank.get("diversity_weight")
        if (
            not isinstance(diversity_weight, (int, float))
            or isinstance(diversity_weight, bool)
            or not math.isfinite(diversity_weight)
            or diversity_weight < 0
        ):
            raise ValueError("rerank.diversity_weight must be finite and >= 0")
    return {
        "config_version": config_version,
        "top_k": int(top_k),
        "feature_weights": validate_feature_weights(dict(feature_weights or {})),
        "rerank": rerank,
        "unknown_prerequisite_policy": unknown_prerequisite_policy,
    }


def simulation_input(
    *,
    scenario_id: str,
    learner_ref: dict,
    ontology_snapshot: dict,
    generation_context: dict,
    learner_state_snapshot: dict,
    preference_snapshot: dict,
    exploration_history: dict,
    semantic_space: dict,
    simulation_config: dict,
) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "scenario_id": scenario_id,
        "learner": learner_ref,
        "ontology_snapshot": ontology_snapshot,
        "generation_context": generation_context,
        "learner_state_snapshot": learner_state_snapshot,
        "preference_snapshot": preference_snapshot,
        "exploration_history": exploration_history,
        "semantic_space": semantic_space,
        "simulation_config": simulation_config,
    }
