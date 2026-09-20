"""Deterministic DOMAIN_COVERAGE reranking (#47, m3-simulation/v3).

Applies the frozen v3 diversity strategy to an already-scored eligible
candidate list. It never changes eligibility and never creates or removes a
candidate. Null rerank is a strict no-op.
"""

from __future__ import annotations

import math

from .validation import SimulationInputError

#: #47-owned RerankTrace reason code (§13.3).
_DIVERSITY_REASON = "DOMAIN_COVERAGE_ADJUSTMENT"


def _canonical_domains(entity: dict | None) -> list[str]:
    if entity is None:
        return []
    return sorted(set(entity.get("domain_ids", [])))


def _domain_frequency(
    scored: list[dict], domains_by_key: dict[tuple[str, int], list[str]]
) -> dict[str, int]:
    frequency: dict[str, int] = {}
    for entry in scored:
        key = (entry["target_entity_id"], entry["target_entity_version"])
        for domain in domains_by_key[key]:
            frequency[domain] = frequency.get(domain, 0) + 1
    return frequency


def _null_rerank(entry: dict) -> None:
    entry["diversity_adjustment"] = 0.0
    entry["ordering_score"] = entry["pre_rerank_score"]
    entry["post_rerank_rank"] = entry["pre_rerank_rank"]
    entry["final_rank"] = entry["pre_rerank_rank"]
    entry["rerank_trace"] = {
        "pre_rerank_rank": entry["pre_rerank_rank"],
        "pre_rerank_score": entry["pre_rerank_score"],
        "diversity_dimensions": {},
        "diversity_adjustment": 0.0,
        "post_rerank_rank": entry["pre_rerank_rank"],
        "reason_codes": [],
    }


def _domain_coverage_rerank(
    scored: list[dict],
    entities: dict[tuple[str, int], dict],
    diversity_weight: float,
) -> None:
    domains_by_key = {
        (entry["target_entity_id"], entry["target_entity_version"]): _canonical_domains(
            entities.get(
                (entry["target_entity_id"], entry["target_entity_version"])
            )
        )
        for entry in scored
    }
    frequency = _domain_frequency(scored, domains_by_key)

    rarity: dict[tuple[str, int], float] = {}
    for entry in scored:
        key = (entry["target_entity_id"], entry["target_entity_version"])
        domains = domains_by_key[key]
        if not domains:
            rarity[key] = 0.0
        else:
            rarity[key] = sum(1.0 / frequency[domain] for domain in domains) / len(domains)

    minimum_rarity = min(rarity.values())

    for entry in scored:
        key = (entry["target_entity_id"], entry["target_entity_version"])
        signal = rarity[key] - minimum_rarity
        adjustment = diversity_weight * signal
        ordering_score = entry["pre_rerank_score"] + adjustment
        if not math.isfinite(ordering_score):
            raise SimulationInputError("ordering_score is not finite")
        entry["diversity_adjustment"] = adjustment
        entry["ordering_score"] = ordering_score
        entry["rerank_trace"] = {
            "pre_rerank_rank": entry["pre_rerank_rank"],
            "pre_rerank_score": entry["pre_rerank_score"],
            "diversity_dimensions": {
                "domain_ids": domains_by_key[key],
                "domain_rarity": rarity[key],
                "minimum_rarity": minimum_rarity,
                "diversity_signal": signal,
            },
            "diversity_adjustment": adjustment,
            "reason_codes": [_DIVERSITY_REASON] if adjustment > 0.0 else [],
            "post_rerank_rank": 0,
        }


def apply_rerank(
    scored: list[dict], entities: dict[tuple[str, int], dict], rerank_config: dict | None
) -> None:
    """Assign ordering/rerank trace/post ranks/final ranks in place.

    ``scored`` must be non-empty. ``rerank_config`` is either ``None`` (no-op)
    or a validated ``DOMAIN_COVERAGE`` config.
    """
    if rerank_config is None:
        for entry in scored:
            _null_rerank(entry)
    else:
        if rerank_config["strategy"] != "DOMAIN_COVERAGE":
            raise SimulationInputError(
                f"unsupported rerank strategy {rerank_config['strategy']!r}"
            )
        _domain_coverage_rerank(scored, entities, rerank_config["diversity_weight"])

    scored.sort(
        key=lambda entry: (
            -entry["ordering_score"],
            entry["deterministic_tiebreak_key"],
        )
    )
    for rank, entry in enumerate(scored, start=1):
        entry["post_rerank_rank"] = rank
        entry["final_rank"] = rank
        entry["rerank_trace"]["post_rerank_rank"] = rank
