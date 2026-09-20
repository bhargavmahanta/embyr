"""Structural validation for the #46 candidate pipeline (m3-simulation/v2).

Structural invalidity raises :class:`SimulationInputError`. A structurally valid
source reference whose target is absent from the ontology is *not* a validation
failure; it becomes an ``INVALID_TARGET`` candidate later (§16, §8.3).
"""

from __future__ import annotations

CONTRACT_VERSION = "m3-simulation/v2"

ENTITY_TYPES = frozenset(
    {"DOMAIN", "AREA", "TOPIC", "CONCEPT", "SKILL", "TECHNIQUE", "JOURNEY"}
)
RELATIONSHIP_TYPES = frozenset({"REQUIRES", "BUILDS_ON", "PART_OF", "RELATED_TO"})
REQUIREMENTS = frozenset({"HARD", "SOFT"})
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

REQUIRED_TOP_LEVEL = (
    "contract_version",
    "scenario_id",
    "learner",
    "ontology_snapshot",
    "generation_context",
    "learner_state_snapshot",
    "preference_snapshot",
    "exploration_history",
    "semantic_space",
    "simulation_config",
)


class SimulationInputError(ValueError):
    """Raised when a SimulationInput is structurally invalid for #46."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SimulationInputError(message)


def _mapping(value: object, ctx: str) -> dict:
    _require(isinstance(value, dict), f"{ctx} must be an object")
    return value  # type: ignore[return-value]


def _sequence(value: object, ctx: str) -> list:
    _require(isinstance(value, list), f"{ctx} must be an array")
    return value  # type: ignore[return-value]


def _field(obj: object, name: str, ctx: str) -> object:
    _require(isinstance(obj, dict) and name in obj, f"{ctx}.{name} is required")
    return obj[name]  # type: ignore[index]


def _text(value: object, ctx: str) -> str:
    _require(isinstance(value, str) and value != "", f"{ctx} must be a non-empty string")
    return value  # type: ignore[return-value]


def _integer(value: object, ctx: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{ctx} must be an integer")
    return value  # type: ignore[return-value]


def _number(value: object, ctx: str) -> float:
    _require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"{ctx} must be a number",
    )
    return value  # type: ignore[return-value]


def _enum(value: object, allowed: frozenset, ctx: str) -> str:
    _require(value in allowed, f"{ctx} has invalid value {value!r}")
    return value  # type: ignore[return-value]


def _validate_ontology(sim: dict) -> set[tuple[str, int]]:
    ontology = _mapping(_field(sim, "ontology_snapshot", "input"), "ontology_snapshot")
    entities = _sequence(_field(ontology, "entities", "ontology_snapshot"), "ontology_snapshot.entities")
    keys: set[tuple[str, int]] = set()
    for index, raw_entity in enumerate(entities):
        ctx = f"ontology_snapshot.entities[{index}]"
        entity = _mapping(raw_entity, ctx)
        entity_id = _text(_field(entity, "entity_id", ctx), f"{ctx}.entity_id")
        entity_version = _integer(_field(entity, "entity_version", ctx), f"{ctx}.entity_version")
        _enum(_field(entity, "entity_type", ctx), ENTITY_TYPES, f"{ctx}.entity_type")
        _number(_field(entity, "difficulty_prior", ctx), f"{ctx}.difficulty_prior")
        _sequence(_field(entity, "domain_ids", ctx), f"{ctx}.domain_ids")
        _sequence(_field(entity, "objective_ids", ctx), f"{ctx}.objective_ids")
        relationships = _sequence(
            _field(entity, "relationships", ctx), f"{ctx}.relationships"
        )
        key = (entity_id, entity_version)
        _require(key not in keys, f"duplicate ontology entity key {key!r}")
        keys.add(key)
        for rel_index, raw_rel in enumerate(relationships):
            rel_ctx = f"{ctx}.relationships[{rel_index}]"
            relationship = _mapping(raw_rel, rel_ctx)
            relationship_type = _enum(
                _field(relationship, "relationship_type", rel_ctx),
                RELATIONSHIP_TYPES,
                f"{rel_ctx}.relationship_type",
            )
            _text(_field(relationship, "target_entity_id", rel_ctx), f"{rel_ctx}.target_entity_id")
            _integer(
                _field(relationship, "target_entity_version", rel_ctx),
                f"{rel_ctx}.target_entity_version",
            )
            requirement = relationship.get("requirement")
            objective_id = relationship.get("objective_id")
            if relationship_type == "REQUIRES":
                _enum(requirement, REQUIREMENTS, f"{rel_ctx}.requirement")
                _text(objective_id, f"{rel_ctx}.objective_id")
            else:
                _require(
                    requirement is None, f"{rel_ctx}.requirement must be null for {relationship_type}"
                )
                _require(
                    objective_id is None, f"{rel_ctx}.objective_id must be null for {relationship_type}"
                )
    return keys


def _validate_generation_context(sim: dict, ontology_keys: set) -> None:
    context = _mapping(_field(sim, "generation_context", "input"), "generation_context")
    anchors = _sequence(
        _field(context, "anchor_entities", "generation_context"),
        "generation_context.anchor_entities",
    )
    seen: set[tuple[str, int]] = set()
    for index, raw_anchor in enumerate(anchors):
        ctx = f"generation_context.anchor_entities[{index}]"
        anchor = _mapping(raw_anchor, ctx)
        key = (
            _text(_field(anchor, "entity_id", ctx), f"{ctx}.entity_id"),
            _integer(_field(anchor, "entity_version", ctx), f"{ctx}.entity_version"),
        )
        _require(key not in seen, f"duplicate anchor {key!r}")
        _require(key in ontology_keys, f"anchor {key!r} does not resolve in ontology")
        seen.add(key)


def _validate_learner_state(sim: dict) -> None:
    state = _mapping(
        _field(sim, "learner_state_snapshot", "input"), "learner_state_snapshot"
    )
    objective_states = _sequence(
        _field(state, "objective_states", "learner_state_snapshot"),
        "learner_state_snapshot.objective_states",
    )
    seen: set[tuple[str, str]] = set()
    for index, raw_state in enumerate(objective_states):
        ctx = f"learner_state_snapshot.objective_states[{index}]"
        entry = _mapping(raw_state, ctx)
        objective_id = _text(_field(entry, "objective_id", ctx), f"{ctx}.objective_id")
        entity_id = _text(_field(entry, "entity_id", ctx), f"{ctx}.entity_id")
        _enum(_field(entry, "state", ctx), OBJECTIVE_STATES, f"{ctx}.state")
        key = (objective_id, entity_id)
        _require(key not in seen, f"ambiguous learner objective state for {key!r}")
        seen.add(key)
    challenge = state.get("challenge_state")
    if challenge is not None:
        _mapping(challenge, "learner_state_snapshot.challenge_state")
    interest_states = _sequence(
        _field(state, "interest_states", "learner_state_snapshot"),
        "learner_state_snapshot.interest_states",
    )
    for index, raw_interest in enumerate(interest_states):
        _mapping(raw_interest, f"learner_state_snapshot.interest_states[{index}]")


def _validate_preferences(sim: dict) -> None:
    snapshot = _mapping(
        _field(sim, "preference_snapshot", "input"), "preference_snapshot"
    )
    preferences = _sequence(
        _field(snapshot, "explicit_preferences", "preference_snapshot"),
        "preference_snapshot.explicit_preferences",
    )
    seen: set[str] = set()
    for index, raw_preference in enumerate(preferences):
        ctx = f"preference_snapshot.explicit_preferences[{index}]"
        entry = _mapping(raw_preference, ctx)
        entity_id = _text(_field(entry, "entity_id", ctx), f"{ctx}.entity_id")
        _enum(
            _field(entry, "preference", ctx), EXPLICIT_PREFERENCES, f"{ctx}.preference"
        )
        _integer(_field(entry, "version", ctx), f"{ctx}.version")
        _require(entity_id not in seen, f"duplicate explicit preference for {entity_id!r}")
        seen.add(entity_id)


def _validate_explorations(sim: dict) -> None:
    history = _mapping(
        _field(sim, "exploration_history", "input"), "exploration_history"
    )
    explorations = _sequence(
        _field(history, "explorations", "exploration_history"),
        "exploration_history.explorations",
    )
    for index, raw_exploration in enumerate(explorations):
        ctx = f"exploration_history.explorations[{index}]"
        entry = _mapping(raw_exploration, ctx)
        _text(_field(entry, "exploration_id", ctx), f"{ctx}.exploration_id")
        _text(_field(entry, "entity_id", ctx), f"{ctx}.entity_id")
        _integer(_field(entry, "entity_version", ctx), f"{ctx}.entity_version")
        _enum(_field(entry, "learning_intent", ctx), LEARNING_INTENTS, f"{ctx}.learning_intent")
        _enum(_field(entry, "status", ctx), EXPLORATION_STATUSES, f"{ctx}.status")


def _validate_semantic_space(sim: dict) -> None:
    space = _mapping(_field(sim, "semantic_space", "input"), "semantic_space")
    dimension = _integer(
        _field(space, "vector_dimension", "semantic_space"), "semantic_space.vector_dimension"
    )
    _require(dimension > 0, "semantic_space.vector_dimension must be positive")
    _text(_field(space, "embedding_model", "semantic_space"), "semantic_space.embedding_model")
    vectors = _sequence(_field(space, "vectors", "semantic_space"), "semantic_space.vectors")
    seen: set[tuple[str, int]] = set()
    for index, raw_vector in enumerate(vectors):
        ctx = f"semantic_space.vectors[{index}]"
        entry = _mapping(raw_vector, ctx)
        key = (
            _text(_field(entry, "entity_id", ctx), f"{ctx}.entity_id"),
            _integer(_field(entry, "entity_version", ctx), f"{ctx}.entity_version"),
        )
        _require(key not in seen, f"duplicate semantic vector key {key!r}")
        seen.add(key)
        vector = _sequence(_field(entry, "vector", ctx), f"{ctx}.vector")
        _require(
            len(vector) == dimension,
            f"{ctx}.vector must have dimension {dimension}",
        )
        for component in vector:
            _number(component, f"{ctx}.vector component")


def validate_simulation_input(simulation_input: object) -> None:
    """Validate the #46-required structural invariants of a SimulationInput.

    Raises:
        SimulationInputError: on any structural invalidity.
    """
    sim = _mapping(simulation_input, "input")
    for name in REQUIRED_TOP_LEVEL:
        _require(name in sim, f"input.{name} is required")
    _require(
        sim["contract_version"] == CONTRACT_VERSION,
        f"input.contract_version must be {CONTRACT_VERSION!r}",
    )
    _mapping(sim["learner"], "input.learner")
    _mapping(sim["simulation_config"], "input.simulation_config")
    ontology_keys = _validate_ontology(sim)
    _validate_generation_context(sim, ontology_keys)
    _validate_learner_state(sim)
    _validate_preferences(sim)
    _validate_explorations(sim)
    _validate_semantic_space(sim)
