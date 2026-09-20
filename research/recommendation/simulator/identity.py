"""Deterministic, opaque target identity helpers for #46.

The authoritative logical target key is ``(target_entity_id,
target_entity_version)``. ``candidate_id`` derives only from that key; the
textual encoding is deliberately not contract-frozen.
"""

from __future__ import annotations

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
