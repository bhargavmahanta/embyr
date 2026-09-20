"""Tiny deterministic fixture semantic space.

``fixture-basis-4d`` uses integer basis vectors so near/far relationships are
human-auditable and require no embedding model, network, or tuning. Dimension 4
is fixture-local and is *not* a production embedding dimension.

Cosine similarity to :data:`SEED` is strictly ordered::

    seed 1.000 > near 0.970 > mid 0.707 > far 0.000 > opposite -1.000
"""

from __future__ import annotations

import math

EMBEDDING_MODEL = "fixture-basis-4d"
VECTOR_DIMENSION = 4

SEED = [1.0, 0.0, 0.0, 0.0]
NEAR = [1.0, 0.25, 0.0, 0.0]
MID = [1.0, 1.0, 0.0, 0.0]
FAR = [0.0, 1.0, 0.0, 0.0]
OPPOSITE = [-1.0, 0.0, 0.0, 0.0]

#: Ordered from most to least similar to the seed, as declared above.
ORDERED_VECTORS = (("seed", SEED), ("near", NEAR), ("mid", MID), ("far", FAR), ("opposite", OPPOSITE))

_NAMED_VECTORS = dict(ORDERED_VECTORS)


def named_vector(name: str) -> list[float]:
    try:
        return list(_NAMED_VECTORS[name])
    except KeyError as error:
        raise ValueError(f"unknown fixture vector: {name!r}") from error


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("vectors must share a dimension")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def semantic_vector(entity_id: str, entity_version: int, vector: list[float]) -> dict:
    if len(vector) != VECTOR_DIMENSION:
        raise ValueError(
            f"semantic vectors must have dimension {VECTOR_DIMENSION}, got {len(vector)}"
        )
    return {
        "entity_id": entity_id,
        "entity_version": entity_version,
        "vector": [float(component) for component in vector],
    }


def ordering_by_seed() -> list[str]:
    """Return vector names ordered by descending cosine similarity to the seed."""
    return [
        name
        for name, _ in sorted(
            ORDERED_VECTORS,
            key=lambda item: cosine_similarity(SEED, item[1]),
            reverse=True,
        )
    ]
