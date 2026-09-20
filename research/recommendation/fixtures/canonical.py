"""Canonical serialization and stable ordering for simulation fixtures.

Mirrors the frozen contract's array-ordering rules (§4) and fingerprint
contract: ``input_fingerprint`` is ``sha256:<hex>`` over the canonical
serialization of ``SimulationInput``. ``execution_metadata`` is excluded from
``SimulationInput`` entirely, so no exclusion filtering is needed here.

These helpers order fixture snapshots so equivalent inputs serialize to
identical bytes. They are fixture tooling, not a recommendation pipeline stage.
"""

from __future__ import annotations

import hashlib
import json


def sort_entities(entities: list[dict]) -> list[dict]:
    return sorted(entities, key=lambda item: (item["entity_id"], item["entity_version"]))


def sort_relationships(relationships: list[dict]) -> list[dict]:
    return sorted(
        relationships,
        key=lambda item: (
            item["target_entity_id"],
            item["target_entity_version"],
            item["relationship_type"],
        ),
    )


def sort_vectors(vectors: list[dict]) -> list[dict]:
    return sorted(vectors, key=lambda item: (item["entity_id"], item["entity_version"]))


def sort_objective_states(states: list[dict]) -> list[dict]:
    return sorted(states, key=lambda item: item["objective_id"])


def sort_interest_states(states: list[dict]) -> list[dict]:
    return sorted(states, key=lambda item: (item["entity_id"], item["entity_version"]))


def sort_anchor_entities(anchors: list[dict]) -> list[dict]:
    return sorted(anchors, key=lambda item: (item["entity_id"], item["entity_version"]))


def sort_explorations(explorations: list[dict]) -> list[dict]:
    return sorted(explorations, key=lambda item: item["exploration_id"])


def sort_explicit_preferences(preferences: list[dict]) -> list[dict]:
    return sorted(preferences, key=lambda item: item["entity_id"])


def sort_domain_ids(domain_ids: list[str]) -> list[str]:
    return sorted(domain_ids)


def canonical_json(value: object) -> str:
    """Return the canonical JSON serialization: sorted keys, compact separators."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def input_fingerprint(simulation_input: dict) -> str:
    """Return ``sha256:<hex>`` over the canonical ``SimulationInput`` bytes."""
    digest = hashlib.sha256(canonical_json(simulation_input).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
