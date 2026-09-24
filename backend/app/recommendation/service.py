"""Production recommendation generation from a detached, versioned snapshot."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from app.integrations.voyage import EmbeddingProviderError
from app.recommendation.inputs import semantic_query_text
from app.recommendation.ranking import ProductionRanking, rank_recommendations
from app.recommendation.retrieval import retrieve_candidates
from app.recommendation.snapshot import ProductionInputSnapshot

BAND_PATH = Path(__file__).with_name("profiles") / "distance-band-v1.json"


class QueryEmbedder(Protocol):
    async def embed_queries(self, texts: list[str]) -> list[list[float]]: ...


def distance_band(source_paths: list[dict]) -> str:
    """Apply distance-band/v1 to the selected candidate's transient source paths."""
    policy = json.loads(BAND_PATH.read_text(encoding="utf-8"))
    if policy["policy_version"] != "distance-band/v1":
        raise ValueError("unsupported distance-band policy")
    bands: set[str] = set()
    for path in source_paths:
        source, provenance = path["source"], path["provenance"]
        if source in policy["comfort_sources"]:
            bands.add("COMFORT")
        elif source == "GRAPH":
            hops = provenance["hop_distance"]
            if hops == 1:
                bands.add("ADJACENT")
            elif hops == 2:
                bands.add("FRONTIER")
        elif source == "SEMANTIC":
            similarity = provenance["cosine_similarity"]
            if similarity >= policy["adjacent"]["minimum_cosine_similarity"]:
                bands.add("ADJACENT")
            elif similarity >= policy["frontier"]["minimum_cosine_similarity"]:
                bands.add("FRONTIER")
            elif similarity >= policy["wild"]["minimum_cosine_similarity"]:
                bands.add("WILD")
    return next((band for band in policy["precedence"] if band in bands), policy["no_qualifying_signal"])


async def generate_recommendation(
    snapshot: ProductionInputSnapshot, *, mode: str,
    embedder: QueryEmbedder | None,
) -> tuple[ProductionRanking, str | None]:
    """Call an external embedder only after the snapshot transaction has closed."""
    vectors = {}
    if snapshot.anchor_entities and snapshot.embeddings:
        if embedder is None:
            raise RuntimeError("semantic query embedder is unavailable")
        entities = {
            (row["entity_id"], row["entity_version"]): row
            for row in snapshot.entities
        }
        anchors = [
            (anchor["entity_id"], anchor["entity_version"])
            for anchor in snapshot.anchor_entities
        ]
        texts = [
            semantic_query_text(entities[key]["title"], entities[key]["summary"])
            for key in anchors
        ]
        embedded = await embedder.embed_queries(texts)
        if len(embedded) != len(anchors):
            raise EmbeddingProviderError("query embedding count mismatch")
        vectors = dict(zip(anchors, embedded, strict=True))
    candidates = retrieve_candidates(snapshot, vectors)
    ranking = rank_recommendations(snapshot, candidates, mode=mode)
    if ranking.selected is None:
        return ranking, None
    selected_candidate = next(
        candidate for candidate in candidates
        if candidate["candidate_id"] == ranking.selected["candidate_id"]
    )
    return ranking, distance_band(selected_candidate["source_paths"])
