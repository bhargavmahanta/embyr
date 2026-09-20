"""Shared builders for #46 simulator unit tests (not a test module)."""

from __future__ import annotations

from research.recommendation.fixtures import builders as b

LEARNER_ID = "10000000-0000-4000-8000-000000000001"


def topic(
    entity_id: str,
    *,
    version: int = 1,
    entity_type: str = "TOPIC",
    title: str | None = None,
    relationships=(),
    domains=(),
    objective_ids=(),
    difficulty: float = 0.5,
) -> dict:
    return b.entity(
        entity_id,
        version,
        entity_type,
        title or entity_id,
        domain_ids=list(domains),
        relationships=list(relationships),
        objective_ids=list(objective_ids),
        difficulty_prior=difficulty,
    )


def related(target_id: str, version: int = 1) -> dict:
    return b.relationship("RELATED_TO", target_id, version)


def requires(prerequisite_id: str, objective_id: str, requirement: str = "HARD", version: int = 1) -> dict:
    return b.relationship("REQUIRES", prerequisite_id, version, requirement, objective_id)


def make_input(
    *,
    entities,
    anchors=(),
    vectors=(),
    preferences=(),
    objective_states=(),
    explorations=(),
    interest_states=(),
    challenge=None,
    feature_weights=None,
    rerank=None,
    top_k=5,
) -> dict:
    challenge_state = (
        None if challenge is None else b.challenge_state(challenge[0], challenge[1])
    )
    return b.simulation_input(
        scenario_id="scn-unit-test",
        learner_ref=b.learner(LEARNER_ID),
        ontology_snapshot=b.ontology_snapshot("unit-onto", list(entities)),
        generation_context=b.candidate_generation_context(
            [b.entity_ref(entity_id, version) for entity_id, version in anchors]
        ),
        learner_state_snapshot=b.learner_state_snapshot(
            "unit-state",
            objective_states=list(objective_states),
            interest_states=list(interest_states),
            challenge_state=challenge_state,
        ),
        preference_snapshot=b.preference_snapshot("unit-prefs", list(preferences)),
        exploration_history=b.exploration_history("unit-hist", list(explorations)),
        semantic_space=b.semantic_space("unit-sem", list(vectors)),
        simulation_config=b.simulation_config(
            top_k=top_k, feature_weights=feature_weights, rerank=rerank
        ),
    )


def objective_state(
    objective_id: str,
    entity_id: str,
    state: str,
    understanding: float | None = None,
    entity_version: int = 1,
) -> dict:
    return b.objective_state(
        objective_id, entity_id, state, understanding, entity_version=entity_version
    )


def preference(entity_id: str, value: str, entity_version: int = 1, version: int = 1) -> dict:
    return b.explicit_preference(entity_id, value, version, entity_version=entity_version)


def exploration(exploration_id: str, entity_id: str, status: str, intent: str = "DIRECT_INTEREST", version: int = 1, **kwargs) -> dict:
    return b.exploration(exploration_id, entity_id, version, intent, status, **kwargs)


def vector(entity_id: str, values, version: int = 1) -> dict:
    return b.semantic_vector(entity_id, version, list(values))


def candidate_by_target(candidates: list[dict], entity_id: str, version: int = 1) -> dict:
    for candidate in candidates:
        if candidate["target_entity_id"] == entity_id and candidate["target_entity_version"] == version:
            return candidate
    raise KeyError((entity_id, version))
