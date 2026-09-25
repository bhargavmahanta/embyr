"""Bounded production nominations with frozen M3 normalization and eligibility.

The caller supplies Voyage query vectors after the input snapshot transaction has
closed. Document vectors came from that same repeatable-read snapshot.
"""
from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from research.recommendation.simulator.eligibility import build_candidate
from research.recommendation.simulator.normalize import normalize_nominations
from research.recommendation.simulator.readiness import evaluate_prerequisites
from research.recommendation.simulator.sources import (
    explicit_interest_nominations,
    history_continuation_nominations,
    revisit_nominations,
)

from app.recommendation.snapshot import ProductionInputSnapshot
from app.recommendation.profile_validation import exact_profile_equal

PROFILE_PATH = Path(__file__).with_name("profiles") / "recommendation-retrieval-v1.json"
FROZEN_RETRIEVAL_POLICY = {
    "policy_version": "recommendation-retrieval/v1",
    "embedding": {
        "provider": "voyage-ai", "model": "voyage-4", "dimension": 1024,
        "metric": "cosine", "document_input_type": "document",
        "query_input_type": "query", "query_input_version": "semantic-query-text/v1",
        "query_text_template": "TITLE: {canonical_title}\nSUMMARY: {canonical_summary}",
        "document_input_version": "ontology-entity/v1",
        "document_text_template": "TITLE: {canonical_title}\nSUMMARY: {canonical_summary}",
    },
    "semantic": {
        "search": "exact", "minimum_cosine_similarity": 0.55,
        "max_candidates": 40, "query_per_anchor": True,
    },
    "graph": {
        "relationship": "RELATED_TO", "bidirectional": True,
        "max_hops": 2, "max_candidates": 100,
        "tie_break": "shortest_hop_then_lexicographic_entity_version_path",
    },
}
Key = tuple[str, int]


def load_retrieval_policy() -> dict[str, Any]:
    policy = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    if not exact_profile_equal(policy, FROZEN_RETRIEVAL_POLICY):
        raise ValueError("unsupported retrieval policy")
    return policy


def _key(entity_id: str, version: int) -> Key:
    return (entity_id, int(version))


def _ref(key: Key) -> dict[str, str | int]:
    return {"entity_id": key[0], "entity_version": key[1]}


def _nomination(target: Key, source: str, provenance: dict) -> dict:
    return {
        "target_entity_id": target[0], "target_entity_version": target[1],
        "source": source, "provenance": provenance,
    }


def _entity_view(snapshot: ProductionInputSnapshot) -> tuple[dict[Key, dict], dict]:
    raw = {_key(e["entity_id"], e["entity_version"]): e for e in snapshot.entities}
    current = {e["entity_id"]: e["current_version"] for e in snapshot.entities}
    domains: dict[str, set[str]] = defaultdict(set)
    for row in snapshot.domains:
        domains[row["entity_id"]].add(row["domain_id"])
    objectives: dict[Key, set[str]] = defaultdict(set)
    objective_keys: set[tuple[str, str, int]] = set()
    for row in snapshot.objectives:
        key = _key(row["entity_id"], row["entity_version"])
        objectives[key].add(row["objective_id"])
        objective_keys.add((row["objective_id"], key[0], key[1]))
    entities = {
        key: {
            "entity_id": key[0], "entity_version": key[1],
            "entity_type": row["entity_type"], "title": row["title"],
            "domain_ids": sorted(domains[key[0]]),
            "objective_ids": sorted(objectives[key]),
            "difficulty_prior": row["difficulty_prior"],
            "estimated_effort_minutes": row["estimated_effort_minutes"],
            "relationships": [],
        }
        for key, row in raw.items()
    }
    for edge in snapshot.edges:
        if edge["status"] != "ACTIVE":
            continue
        relationship = edge["relationship_type"]
        if relationship not in {"RELATED_TO", "REQUIRES"}:
            continue
        if relationship == "REQUIRES":
            source_version = edge["source_entity_version"]
            if source_version is None:
                if edge["source_entity_id"] in current:
                    raise ValueError("current REQUIRES edge lacks source version")
                continue
            source = _key(edge["source_entity_id"], source_version)
            if source not in entities:
                continue  # Historical dependent versions cannot constrain current candidates.
            target_version = edge["target_entity_version"]
            if target_version is None:
                raise ValueError("current REQUIRES edge lacks target version")
            target = _key(edge["target_entity_id"], target_version)
        else:
            source_version = edge["source_entity_version"] or current.get(edge["source_entity_id"])
            target_version = edge["target_entity_version"] or current.get(edge["target_entity_id"])
            source = _key(edge["source_entity_id"], source_version) if source_version else None
            target = _key(edge["target_entity_id"], target_version) if target_version else None
        if source is None or target is None or source not in entities or target not in entities:
            if relationship == "REQUIRES":
                raise ValueError("active REQUIRES edge has unresolved versioned endpoint")
            continue
        entry = {
            "relationship_type": relationship,
            "target_entity_id": target[0],
            "target_entity_version": target[1],
        }
        if relationship == "REQUIRES":
            objective_id = edge["objective_id"]
            if (
                edge["source_entity_version"] is None
                or edge["target_entity_version"] is None
                or (objective_id, target[0], target[1]) not in objective_keys
                or edge["requirement"] not in {"HARD", "SOFT"}
            ):
                raise ValueError("active REQUIRES edge lacks matching objective/version identity")
            entry["objective_id"] = objective_id
            entry["requirement"] = edge["requirement"]
        entities[source]["relationships"].append(entry)
    for entity in entities.values():
        entity["relationships"].sort(key=lambda rel: (
            rel["target_entity_id"], rel["target_entity_version"], rel["relationship_type"]
        ))
    view = {
        "ontology_snapshot": {"entities": list(entities.values())},
        "generation_context": {"anchor_entities": list(snapshot.anchor_entities)},
        "preference_snapshot": {"explicit_preferences": list(snapshot.explicit_preferences)},
        "exploration_history": {"explorations": list(snapshot.explorations)},
        "learner_state_snapshot": {"objective_states": list(snapshot.objective_states)},
    }
    return entities, view


def _adjacency(entities: Mapping[Key, dict]) -> dict[Key, set[Key]]:
    adjacent: dict[Key, set[Key]] = defaultdict(set)
    for source, entity in entities.items():
        for rel in entity["relationships"]:
            if rel["relationship_type"] != "RELATED_TO":
                continue
            target = _key(rel["target_entity_id"], rel["target_entity_version"])
            adjacent[source].add(target)
            adjacent[target].add(source)
    return adjacent


def _graph_nominations(view: dict, entities: Mapping[Key, dict], policy: dict) -> list[dict]:
    anchors = sorted(_key(a["entity_id"], a["entity_version"]) for a in view["generation_context"]["anchor_entities"])
    anchor_set = set(anchors)
    adjacent = _adjacency(entities)
    paths_by_target: dict[Key, list[tuple[Key, int, tuple[Key, ...]]]] = defaultdict(list)
    max_hops = policy["graph"]["max_hops"]
    for anchor in anchors:
        best: dict[Key, tuple[int, tuple[Key, ...]]] = {anchor: (0, (anchor,))}
        heap: list[tuple[int, tuple[Key, ...], Key]] = [(0, (anchor,), anchor)]
        while heap:
            distance, path, node = heapq.heappop(heap)
            if best.get(node) != (distance, path) or distance >= max_hops:
                continue
            for neighbor in sorted(adjacent.get(node, ())):
                next_path = path + (neighbor,)
                candidate = (distance + 1, next_path)
                if neighbor not in best or candidate < best[neighbor]:
                    best[neighbor] = candidate
                    heapq.heappush(heap, (candidate[0], candidate[1], neighbor))
        for target, (distance, path) in best.items():
            if target not in anchor_set:
                paths_by_target[target].append((anchor, distance, path))
    ordered = sorted(paths_by_target, key=lambda target: (
        min((distance, path) for _, distance, path in paths_by_target[target]), target
    ))[:policy["graph"]["max_candidates"]]
    return [
        _nomination(target, "GRAPH", {
            "anchor_entity_id": anchor[0], "anchor_entity_version": anchor[1],
            "hop_distance": distance,
            "canonical_path": [_ref(ref) for ref in path],
        })
        for target in ordered
        for anchor, distance, path in sorted(paths_by_target[target])
    ]


def _vector(raw: Any, dimension: int) -> list[float]:
    values = json.loads(raw) if isinstance(raw, str) else list(raw)
    if len(values) != dimension or not all(math.isfinite(float(value)) for value in values):
        raise ValueError("embedding has invalid dimension or non-finite component")
    return [float(value) for value in values]


def _cosine(left: list[float], right: list[float]) -> float:
    dot = math.fsum(x * y for x, y in zip(left, right, strict=True))
    norms = math.sqrt(math.fsum(x * x for x in left)) * math.sqrt(math.fsum(y * y for y in right))
    return dot / norms if norms else 0.0


def _semantic_nominations(
    snapshot: ProductionInputSnapshot, query_embeddings: Mapping[Key, list[float]],
    policy: dict,
) -> list[dict]:
    dimension = policy["embedding"]["dimension"]
    minimum = policy["semantic"]["minimum_cosine_similarity"]
    anchors = sorted(_key(a["entity_id"], a["entity_version"]) for a in snapshot.anchor_entities)
    anchor_set = set(anchors)
    valid_versions = {_key(e["entity_id"], e["entity_version"]) for e in snapshot.entities}
    documents = {
        _key(row["entity_id"], row["entity_version"]): _vector(row["vector"], dimension)
        for row in snapshot.embeddings
        if _key(row["entity_id"], row["entity_version"]) in valid_versions
    }
    hits: dict[Key, list[tuple[Key, float]]] = defaultdict(list)
    for anchor in anchors:
        raw_query = query_embeddings.get(anchor)
        if raw_query is None:
            continue
        query = _vector(raw_query, dimension)
        for target, document in documents.items():
            if target in anchor_set:
                continue
            cosine = _cosine(query, document)
            if cosine >= minimum:
                hits[target].append((anchor, cosine))
    ordered = sorted(hits, key=lambda target: (-max(value for _, value in hits[target]), target))
    return [
        _nomination(target, "SEMANTIC", {
            "anchor_entity_id": anchor[0], "anchor_entity_version": anchor[1],
            "cosine_similarity": cosine,
        })
        for target in ordered[:policy["semantic"]["max_candidates"]]
        for anchor, cosine in sorted(hits[target])
    ]


def retrieve_candidates(
    snapshot: ProductionInputSnapshot,
    query_embeddings: Mapping[Key, list[float]],
    *, policy: dict | None = None,
) -> list[dict]:
    """Return deterministic M3 Candidate dictionaries from real production inputs."""
    policy = policy or load_retrieval_policy()
    entities, view = _entity_view(snapshot)
    current_revisits = [
        exploration for exploration in snapshot.explorations
        if exploration["status"] == "COMPLETED"
        and _key(exploration["entity_id"], exploration["entity_version"]) in entities
    ]
    revisit_view = {
        **view,
        "exploration_history": {"explorations": current_revisits},
    }
    nominations = [
        *_graph_nominations(view, entities, policy),
        *_semantic_nominations(snapshot, query_embeddings, policy),
        *explicit_interest_nominations(view),
        *history_continuation_nominations(view),
        *revisit_nominations(revisit_view),
    ]
    preferences = {
        _key(p["entity_id"], p["entity_version"]): p["preference"]
        for p in snapshot.explicit_preferences
    }
    candidates = []
    for normalized in normalize_nominations(nominations):
        target = _key(normalized["target_entity_id"], normalized["target_entity_version"])
        entity = entities.get(target)
        prerequisites = evaluate_prerequisites(target, entity, view)
        candidates.append(build_candidate(
            normalized, entity, preferences.get(target), prerequisites,
        ))
    return sorted(candidates, key=lambda candidate: candidate["candidate_id"])
