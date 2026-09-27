"""Pure deterministic World identities, public objects and canonical JSON."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from uuid import UUID, uuid5

NAMESPACE = UUID("a6a18892-0247-5a64-adc3-1161194e67be")
WORLD_VERSION = "world-projection/v1"


def canonical_json(value) -> str:
    """Shortest round-trip finite binary64 numbers, independent of dict order."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NONFINITE")
        if value == 0:
            return "-0" if math.copysign(1, value) < 0 else "0"
        dec = Decimal(repr(value))
        fixed = format(dec, "f")
        if "." in fixed:
            fixed = fixed.rstrip("0").rstrip(".")
        mantissa, exponent = format(dec.normalize(), "e").split("e")
        scientific = mantissa + "e" + str(int(exponent))
        return min([fixed, scientific], key=lambda s: (len(s), s))
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return (
            "{"
            + ",".join(
                canonical_json(k) + ":" + canonical_json(value[k])
                for k in sorted(value)
            )
            + "}"
        )
    raise ValueError("CANONICAL_TYPE")


def fingerprint(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def world_id(user_id) -> UUID:
    return uuid5(NAMESPACE, "world:" + str(UUID(str(user_id))))


def world_seed(world) -> str:
    return hashlib.sha256(f"{WORLD_VERSION}:{world}".encode()).hexdigest()


def region_object(user_id) -> dict:
    return {
        "id": str(uuid5(world_id(user_id), "region:discovery")),
        "region_key": "discovery",
        "primary_domain_id": None,
        "logical_x": 0.0,
        "logical_y": 0.0,
        "logical_width": 1.0,
        "logical_height": 1.0,
        "visual_archetype": "grove",
    }


def node_object(user_id, entity, version, growth, revision=0) -> dict:
    node = uuid5(world_id(user_id), "entity:" + str(UUID(str(entity))))
    digest = hashlib.sha256(str(node).encode()).digest()
    return {
        "id": str(node),
        "entity_id": str(entity),
        "entity_version": version,
        "region_id": region_object(user_id)["id"],
        "logical_x": int.from_bytes(digest[:8], "big") / 2**64,
        "logical_y": int.from_bytes(digest[8:16], "big") / 2**64,
        "depth": 0,
        "visual_archetype": "branching_tree",
        "visual_seed": world_seed(node),
        "growth_state": growth,
        "revision": revision,
    }


def semantic_node(node):
    return {key: value for key, value in node.items() if key != "revision"}
