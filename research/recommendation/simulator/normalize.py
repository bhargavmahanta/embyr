"""Candidate normalization: merge raw nominations by logical target (§8, §15)."""

from __future__ import annotations

from .identity import TargetKey, candidate_id, canonical_provenance
from .sources import CANDIDATE_SOURCES

_SOURCE_INDEX = {source: index for index, source in enumerate(CANDIDATE_SOURCES)}


def normalize_nominations(nominations: list[dict]) -> list[dict]:
    """Merge nominations into one normalized candidate per logical target.

    ``source_paths`` retains every distinct provenance path, deduplicates
    identical ``(source, canonical provenance)`` pairs, and is sorted by frozen
    CandidateSource order then canonical provenance.
    """
    grouped: dict[TargetKey, dict] = {}
    for nomination in nominations:
        key = (nomination["target_entity_id"], nomination["target_entity_version"])
        entry = grouped.setdefault(key, {"seen": set(), "paths": []})
        signature = (nomination["source"], canonical_provenance(nomination["provenance"]))
        if signature in entry["seen"]:
            continue
        entry["seen"].add(signature)
        entry["paths"].append(
            {"source": nomination["source"], "provenance": nomination["provenance"]}
        )

    candidates: list[dict] = []
    for key in sorted(grouped):
        paths = grouped[key]["paths"]
        paths.sort(key=lambda path: (_SOURCE_INDEX[path["source"]], canonical_provenance(path["provenance"])))
        candidates.append(
            {
                "candidate_id": candidate_id(*key),
                "target_entity_id": key[0],
                "target_entity_version": key[1],
                "source_paths": paths,
            }
        )
    return candidates
