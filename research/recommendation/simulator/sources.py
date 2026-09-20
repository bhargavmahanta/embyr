"""Raw candidate nomination from the five frozen sources (m3-simulation/v3).

Nomination carries no eligibility and no score. Sources are pure functions of
the validated ``SimulationInput`` and are deterministic (no wall clock, no
randomness, no network).
"""

from __future__ import annotations

import heapq
import math

from .identity import TargetKey, entity_ref

#: Frozen CandidateSource order (§4, §8).
CANDIDATE_SOURCES = (
    "GRAPH",
    "SEMANTIC",
    "EXPLICIT_INTEREST",
    "HISTORY_CONTINUATION",
    "REVISIT",
)

#: Explicit preferences that nominate an EXPLICIT_INTEREST candidate (§8.1).
NOMINATING_PREFERENCES = ("MORE", "LESS", "PAUSED", "NOT_INTERESTED")


def _nomination(target: TargetKey, source: str, provenance: dict) -> dict:
    return {
        "target_entity_id": target[0],
        "target_entity_version": target[1],
        "source": source,
        "provenance": provenance,
    }


def _entity_keys(simulation_input: dict) -> list[TargetKey]:
    return sorted(
        (entity["entity_id"], entity["entity_version"])
        for entity in simulation_input["ontology_snapshot"]["entities"]
    )


def _anchor_keys(simulation_input: dict) -> list[TargetKey]:
    return sorted(
        (anchor["entity_id"], anchor["entity_version"])
        for anchor in simulation_input["generation_context"]["anchor_entities"]
    )


def _related_to_adjacency(simulation_input: dict) -> dict[TargetKey, set[TargetKey]]:
    adjacency: dict[TargetKey, set[TargetKey]] = {}
    for entity in simulation_input["ontology_snapshot"]["entities"]:
        source = (entity["entity_id"], entity["entity_version"])
        adjacency.setdefault(source, set())
        for relationship in entity["relationships"]:
            if relationship["relationship_type"] != "RELATED_TO":
                continue
            target = (
                relationship["target_entity_id"],
                relationship["target_entity_version"],
            )
            adjacency.setdefault(source, set()).add(target)
            adjacency.setdefault(target, set()).add(source)
    return adjacency


def _canonical_paths(
    anchor: TargetKey, adjacency: dict[TargetKey, set[TargetKey]]
) -> dict[TargetKey, tuple[int, tuple[TargetKey, ...]]]:
    """Shortest RELATED_TO path per reachable target, canonical on ties.

    A path is ``(hop_distance, (anchor, ..., target))``. Among equal-length
    paths the lexicographically smallest ordered EntityRef sequence wins.
    """
    best: dict[TargetKey, tuple[int, tuple[TargetKey, ...]]] = {anchor: (0, (anchor,))}
    heap: list[tuple[int, tuple[TargetKey, ...], TargetKey]] = [(0, (anchor,), anchor)]
    while heap:
        distance, path, node = heapq.heappop(heap)
        if best.get(node) != (distance, path):
            continue
        for neighbour in sorted(adjacency.get(node, ())):
            candidate = (distance + 1, path + (neighbour,))
            current = best.get(neighbour)
            if current is None or candidate < current:
                best[neighbour] = candidate
                heapq.heappush(heap, (candidate[0], candidate[1], neighbour))
    return best


def graph_nominations(simulation_input: dict) -> list[dict]:
    """GRAPH: exhaustive RELATED_TO traversal from each anchor (§9.2)."""
    adjacency = _related_to_adjacency(simulation_input)
    anchors = _anchor_keys(simulation_input)
    anchor_set = set(anchors)
    nominations: list[dict] = []
    for anchor in anchors:
        best = _canonical_paths(anchor, adjacency)
        for target in sorted(best):
            if target in anchor_set:
                continue
            distance, path = best[target]
            provenance = {
                "anchor_entity_id": anchor[0],
                "anchor_entity_version": anchor[1],
                "hop_distance": distance,
                "canonical_path": [entity_ref(*ref) for ref in path],
            }
            nominations.append(_nomination(target, "GRAPH", provenance))
    return nominations


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(x * y for x, y in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(x * x for x in left))
    norm_right = math.sqrt(sum(y * y for y in right))
    if norm_left == 0.0 or norm_right == 0.0:
        return 0.0
    return dot / (norm_left * norm_right)


def semantic_nominations(simulation_input: dict) -> list[dict]:
    """SEMANTIC: exhaustive cosine retrieval from each anchored vector (§9.1).

    The candidate set is every semantic vector record other than an anchor, with
    no threshold, no top-K, and no ANN. A vector record whose entity is absent
    from the ontology still nominates and is resolved to INVALID_TARGET later.
    """
    vectors = {
        (vector["entity_id"], vector["entity_version"]): list(vector["vector"])
        for vector in simulation_input["semantic_space"]["vectors"]
    }
    anchor_set = set(_anchor_keys(simulation_input))
    nominations: list[dict] = []
    for anchor in _anchor_keys(simulation_input):
        if anchor not in vectors:
            continue
        anchor_vector = vectors[anchor]
        for target in sorted(vectors):
            if target == anchor or target in anchor_set:
                continue
            provenance = {
                "anchor_entity_id": anchor[0],
                "anchor_entity_version": anchor[1],
                "cosine_similarity": _cosine_similarity(anchor_vector, vectors[target]),
            }
            nominations.append(_nomination(target, "SEMANTIC", provenance))
    return nominations


def explicit_interest_nominations(simulation_input: dict) -> list[dict]:
    """EXPLICIT_INTEREST: non-NEUTRAL preferences nominate, then are filtered."""
    nominations: list[dict] = []
    preferences = sorted(
        simulation_input["preference_snapshot"]["explicit_preferences"],
        key=lambda entry: (entry["entity_id"], entry["entity_version"]),
    )
    for preference in preferences:
        if preference["preference"] not in NOMINATING_PREFERENCES:
            continue
        target = (preference["entity_id"], preference["entity_version"])
        provenance = {
            "entity_id": preference["entity_id"],
            "entity_version": preference["entity_version"],
            "preference": preference["preference"],
            "version": preference["version"],
        }
        nominations.append(_nomination(target, "EXPLICIT_INTEREST", provenance))
    return nominations


def history_continuation_nominations(simulation_input: dict) -> list[dict]:
    """HISTORY_CONTINUATION: direct RELATED_TO neighbours of ACTIVE targets."""
    adjacency = _related_to_adjacency(simulation_input)
    anchor_set = set(_anchor_keys(simulation_input))
    explorations = sorted(
        (
            exploration
            for exploration in simulation_input["exploration_history"]["explorations"]
            if exploration["status"] == "ACTIVE"
        ),
        key=lambda exploration: exploration["exploration_id"],
    )
    nominations: list[dict] = []
    for exploration in explorations:
        seed = (exploration["entity_id"], exploration["entity_version"])
        for neighbour in sorted(adjacency.get(seed, ())):
            if neighbour == seed or neighbour in anchor_set:
                continue
            provenance = {
                "exploration_id": exploration["exploration_id"],
                "status": exploration["status"],
                "learning_intent": exploration["learning_intent"],
                "source_entity_id": seed[0],
                "source_entity_version": seed[1],
            }
            nominations.append(_nomination(neighbour, "HISTORY_CONTINUATION", provenance))
    return nominations


def revisit_nominations(simulation_input: dict) -> list[dict]:
    """REVISIT: the target of each COMPLETED exploration (§8.2)."""
    explorations = sorted(
        (
            exploration
            for exploration in simulation_input["exploration_history"]["explorations"]
            if exploration["status"] == "COMPLETED"
        ),
        key=lambda exploration: exploration["exploration_id"],
    )
    nominations: list[dict] = []
    for exploration in explorations:
        target = (exploration["entity_id"], exploration["entity_version"])
        provenance = {
            "exploration_id": exploration["exploration_id"],
            "status": exploration["status"],
            "completed_at": exploration.get("completed_at"),
        }
        nominations.append(_nomination(target, "REVISIT", provenance))
    return nominations


def generate_nominations(simulation_input: dict) -> list[dict]:
    """Return all raw nominations in frozen CandidateSource order."""
    return [
        *graph_nominations(simulation_input),
        *semantic_nominations(simulation_input),
        *explicit_interest_nominations(simulation_input),
        *history_continuation_nominations(simulation_input),
        *revisit_nominations(simulation_input),
    ]
