"""Deterministic, opaque target identity helpers for #46.

The authoritative logical target key is ``(target_entity_id,
target_entity_version)``. ``candidate_id`` derives only from that key; the
textual encoding is deliberately not contract-frozen.
"""

from __future__ import annotations

import copy
import hashlib
import json

TargetKey = tuple[str, int]


def target_key(entity_id: str, entity_version: int) -> TargetKey:
    return (entity_id, entity_version)


def canonical_json(value: object) -> str:
    """Return canonical JSON: sorted keys, compact separators, ASCII-only."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def candidate_id(entity_id: str, entity_version: int) -> str:
    """Return an opaque, deterministic id for a logical target.

    Derives only from ``(entity_id, entity_version)``. The encoding is not
    frozen; callers must not depend on its exact form.
    """
    payload = canonical_json([entity_id, entity_version])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"cand:{digest}"


def entity_ref(entity_id: str, entity_version: int) -> dict:
    return {"entity_id": entity_id, "entity_version": entity_version}


def canonical_provenance(provenance: dict) -> str:
    return canonical_json(provenance)


def canonicalize_simulation_input_for_identity(simulation_input: dict) -> dict:
    """Return a fresh ``SimulationInput`` with §4 order-insensitive arrays ordered.

    Only arrays whose ordering the contract defines as canonical/order-insensitive
    are normalized (contract §4): ontology entities and their nested
    relationships/domain_ids/objective_ids, semantic vectors, generation-context
    anchors, learner objective/interest states, explicit preferences, and
    explorations. Semantically ordered arrays (for example ``SemanticVector.vector``)
    are preserved. The caller's input is never mutated.

    This is engine-owned identity canonicalization; it uses only the existing
    ``canonical_json`` serializer and never imports fixture canonicalization.
    """
    normalized = copy.deepcopy(simulation_input)

    ontology = normalized.get("ontology_snapshot")
    if isinstance(ontology, dict):
        entities = ontology.get("entities")
        if isinstance(entities, list):
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                relationships = entity.get("relationships")
                if isinstance(relationships, list):
                    entity["relationships"] = sorted(
                        relationships,
                        key=lambda item: (
                            item["target_entity_id"],
                            item["target_entity_version"],
                            item["relationship_type"],
                        ),
                    )
                for field in ("domain_ids", "objective_ids"):
                    values = entity.get(field)
                    if isinstance(values, list):
                        entity[field] = sorted(values)
            ontology["entities"] = sorted(
                entities, key=lambda item: (item["entity_id"], item["entity_version"])
            )

    semantic_space = normalized.get("semantic_space")
    if isinstance(semantic_space, dict):
        vectors = semantic_space.get("vectors")
        if isinstance(vectors, list):
            semantic_space["vectors"] = sorted(
                vectors, key=lambda item: (item["entity_id"], item["entity_version"])
            )

    generation_context = normalized.get("generation_context")
    if isinstance(generation_context, dict):
        anchors = generation_context.get("anchor_entities")
        if isinstance(anchors, list):
            generation_context["anchor_entities"] = sorted(
                anchors, key=lambda item: (item["entity_id"], item["entity_version"])
            )

    learner_state = normalized.get("learner_state_snapshot")
    if isinstance(learner_state, dict):
        objective_states = learner_state.get("objective_states")
        if isinstance(objective_states, list):
            learner_state["objective_states"] = sorted(
                objective_states,
                key=lambda item: (
                    item["objective_id"],
                    item["entity_id"],
                    item["entity_version"],
                ),
            )
        interest_states = learner_state.get("interest_states")
        if isinstance(interest_states, list):
            learner_state["interest_states"] = sorted(
                interest_states,
                key=lambda item: (item["entity_id"], item["entity_version"]),
            )

    preference_snapshot = normalized.get("preference_snapshot")
    if isinstance(preference_snapshot, dict):
        preferences = preference_snapshot.get("explicit_preferences")
        if isinstance(preferences, list):
            preference_snapshot["explicit_preferences"] = sorted(
                preferences,
                key=lambda item: (item["entity_id"], item["entity_version"]),
            )

    exploration_history = normalized.get("exploration_history")
    if isinstance(exploration_history, dict):
        explorations = exploration_history.get("explorations")
        if isinstance(explorations, list):
            exploration_history["explorations"] = sorted(
                explorations, key=lambda item: item["exploration_id"]
            )

    return normalized
