"""Production adapter over frozen M3 scoring, rerank, and explanation logic.

SimulationInput validation and SimulationResult generation are intentionally not
used: production identity and request context are not synthetic fixtures.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from research.recommendation.simulator.explain import build_recommendation_results
from research.recommendation.simulator.rerank import apply_rerank
from research.recommendation.simulator.scoring import score_candidate
from research.recommendation.simulator.validation import SCORING_FEATURE_SET

from app.recommendation.snapshot import ProductionInputSnapshot

PROFILE_PATH = Path(__file__).with_name("profiles") / "recommendation-profile-v1.json"


def load_profile() -> dict[str, Any]:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    if (
        profile["profile_version"] != "recommendation-profile/v1"
        or profile["semantic_contract"] != "m3-simulation/v5"
        or profile["top_k"] != 1
        or set(profile["feature_weights"]) != SCORING_FEATURE_SET
    ):
        raise ValueError("unsupported production ranking profile")
    return profile


@dataclass(frozen=True)
class ProductionRanking:
    selected: dict[str, Any] | None
    ranked: tuple[dict[str, Any], ...]
    candidate_count: int
    eligible_count: int
    excluded_count: int
    profile_version: str


def _entities(snapshot: ProductionInputSnapshot) -> dict[tuple[str, int], dict]:
    domains: dict[str, set[str]] = {}
    for row in snapshot.domains:
        domains.setdefault(row["entity_id"], set()).add(row["domain_id"])
    entities = {}
    for row in snapshot.entities:
        key = (row["entity_id"], row["entity_version"])
        entity = dict(row)
        entity["domain_ids"] = sorted(set(row.get("domain_ids", [])) | domains.get(key[0], set()))
        entities[key] = entity
    return entities


def _challenge_for(snapshot: ProductionInputSnapshot, entity: dict) -> dict | None:
    states = {row["area_id"]: row for row in snapshot.challenge_states}
    domains = entity["domain_ids"]
    primary = sorted(
        row["domain_id"] for row in snapshot.domains
        if row["entity_id"] == entity["entity_id"] and row["is_primary"]
    )
    for area_id in [*primary, *domains]:
        if area_id in states:
            return dict(states[area_id])
    return None


def _ranked_shape(entry: dict) -> dict:
    return {
        field: entry[field]
        for field in (
            "candidate_id", "target_entity_id", "target_entity_version",
            "target_entity_type", "candidate_sources", "readiness_summary",
            "score_trace", "rerank_trace", "ordering_score",
            "deterministic_tiebreak_key", "final_rank",
        )
    }


def rank_recommendations(
    snapshot: ProductionInputSnapshot,
    candidates: list[dict],
    *, profile: dict | None = None,
) -> ProductionRanking:
    """Score once, rerank once, and select the one-item M3 ordered prefix."""
    profile = profile or load_profile()
    eligible = [item for item in candidates if item["eligibility_state"] == "ELIGIBLE"]
    if not eligible:
        return ProductionRanking(
            selected=None, ranked=(), candidate_count=len(candidates),
            eligible_count=0, excluded_count=len(candidates),
            profile_version=profile["profile_version"],
        )
    entities = _entities(snapshot)
    interests = {
        (row["entity_id"], row["entity_version"]): row
        for row in snapshot.interest_states
    }
    scored = []
    for candidate in eligible:
        key = (candidate["target_entity_id"], candidate["target_entity_version"])
        entity = entities.get(key)
        if entity is None or entity["entity_type"] != candidate["target_entity_type"]:
            raise ValueError("eligible candidate has no matching ontology target")
        scored.append(score_candidate(
            candidate, entity, interests.get(key), _challenge_for(snapshot, entity),
            profile["feature_weights"],
        ))
    scored.sort(key=lambda item: (
        -item["pre_rerank_score"], item["deterministic_tiebreak_key"]
    ))
    for rank, item in enumerate(scored, start=1):
        item["pre_rerank_rank"] = rank
    apply_rerank(scored, entities, profile["rerank"])
    results = build_recommendation_results([_ranked_shape(item) for item in scored])
    selected = results[0]
    selected_candidate = next(
        item for item in eligible if item["candidate_id"] == selected["candidate_id"]
    )
    if any(
        evaluation["requirement"] == "HARD" and evaluation["state"] != "SATISFIED"
        for evaluation in selected_candidate["prerequisite_evaluations"]
    ):
        raise ValueError("ineligible hard prerequisite reached recommendation selection")
    return ProductionRanking(
        selected=selected, ranked=tuple(results), candidate_count=len(candidates),
        eligible_count=len(eligible), excluded_count=len(candidates) - len(eligible),
        profile_version=profile["profile_version"],
    )
