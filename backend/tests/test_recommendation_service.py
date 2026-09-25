from __future__ import annotations

import pytest
from uuid import UUID

from app.integrations.voyage import EmbeddingProviderError
from app.recommendation.inputs import ontology_document_text, semantic_query_text
from app.recommendation.snapshot import QUERIES, build_production_snapshot
from app.recommendation.service import generate_recommendation
from app.recommendation.service import distance_band


@pytest.mark.parametrize("paths, expected", [
    ([{"source": "HISTORY_CONTINUATION", "provenance": {}}], "COMFORT"),
    ([{"source": "GRAPH", "provenance": {"hop_distance": 1}}], "ADJACENT"),
    ([{"source": "GRAPH", "provenance": {"hop_distance": 2}}], "FRONTIER"),
    ([{"source": "SEMANTIC", "provenance": {"cosine_similarity": 0.55}}], "WILD"),
    ([{"source": "SEMANTIC", "provenance": {"cosine_similarity": 0.8}},
      {"source": "REVISIT", "provenance": {}}], "COMFORT"),
    ([], "ADJACENT"),
])
def test_distance_band_v1(paths, expected):
    assert distance_band(paths) == expected


def _production_snapshot(*, anchor_title="Anchor", anchor_summary="A topic"):
    anchor = UUID("22222222-2222-2222-2222-222222222222")
    target = UUID("33333333-3333-3333-3333-333333333333")
    rows = {name: [] for name in QUERIES}
    rows["entities"] = [
        {"entity_id": entity_id, "entity_version": 1, "current_version": 1,
         "entity_type": "TOPIC", "status": "REVIEWED", "title": title,
         "summary": "A topic", "difficulty_prior": 0.4,
         "estimated_effort_minutes": 15}
        for entity_id, title in ((anchor, "Anchor"), (target, "Target"))
    ]
    rows["entities"][0]["title"] = anchor_title
    rows["entities"][0]["summary"] = anchor_summary
    rows["preferences"] = [
        {"entity_id": anchor, "entity_version": 1, "preference": "MORE", "version": 1}
    ]
    rows["explorations"] = [
        {"exploration_id": UUID("44444444-4444-4444-4444-444444444444"),
         "entity_id": anchor, "entity_version": 1, "status": "ACTIVE",
         "learning_intent": "DIRECT_INTEREST"},
        {"exploration_id": UUID("55555555-5555-5555-5555-555555555555"),
         "entity_id": target, "entity_version": 1, "status": "COMPLETED",
         "learning_intent": "DIRECT_INTEREST"},
    ]
    rows["edges"] = [
        {"source_entity_id": anchor, "source_entity_version": None,
         "target_entity_id": target, "target_entity_version": None,
         "relationship_type": "RELATED_TO", "status": "ACTIVE"}
    ]
    # Use the real versioned document recipe to pass snapshot freshness checks.
    import hashlib
    from app.recommendation.inputs import ontology_document_text
    rows["embeddings"] = [{
        "entity_id": target, "entity_version": 1,
        "vector": [1.0] + [0.0] * 1023,
        "embedding_input_fingerprint": "sha256:" + hashlib.sha256(
            ontology_document_text("Target", "A topic").encode()
        ).hexdigest(),
    }]
    return build_production_snapshot(UUID("11111111-1111-1111-1111-111111111111"), rows)


class _Embedder:
    def __init__(self, count=None):
        self.calls = []
        self.count = count

    async def embed_queries(self, texts):
        self.calls.append(texts)
        return [[1.0] + [0.0] * 1023 for _ in range(
            len(texts) if self.count is None else self.count
        )]


@pytest.mark.asyncio
async def test_real_retrieval_and_ranking_are_mode_independent_until_selection():
    snapshot = _production_snapshot()
    embedder = _Embedder()
    results = {}
    for mode in ("CONTINUE", "REVISIT", "EXPLORE", "SURPRISE", "CREATE"):
        results[mode] = await generate_recommendation(
            snapshot, mode=mode, embedder=embedder
        )
    assert len(embedder.calls) == 5
    assert all(call == ["TITLE: Anchor\nSUMMARY: A topic"] for call in embedder.calls)
    assert all(result[0].ranked == results["EXPLORE"][0].ranked
               for result in results.values())
    assert results["CREATE"][0].selected is None
    assert results["CREATE"][1] is None
    for mode in ("CONTINUE", "REVISIT", "SURPRISE"):
        assert results[mode][0].selected["target_entity_id"] == str(
            UUID("33333333-3333-3333-3333-333333333333")
        )
        assert results[mode][1] == "COMFORT"
    assert results["EXPLORE"][0].selected is not None


@pytest.mark.asyncio
async def test_wrong_query_vector_count_is_provider_failure():
    with pytest.raises(EmbeddingProviderError, match="count mismatch"):
        await generate_recommendation(
            _production_snapshot(), mode="CONTINUE", embedder=_Embedder(count=0)
        )


@pytest.mark.parametrize(("title", "summary", "expected"), [
    ("", "A topic", "TITLE: \nSUMMARY: A topic"),
    ("Anchor", "", "TITLE: Anchor\nSUMMARY: "),
    ("", "", "TITLE: \nSUMMARY: "),
])
@pytest.mark.asyncio
async def test_empty_anchor_text_uses_exact_query_recipe(title, summary, expected):
    embedder = _Embedder()
    ranking, _ = await generate_recommendation(
        _production_snapshot(anchor_title=title, anchor_summary=summary),
        mode="EXPLORE", embedder=embedder,
    )
    assert semantic_query_text(title, summary) == expected
    assert ontology_document_text(title, summary) == expected
    assert embedder.calls == [[expected]]
    assert ranking.selected is not None


@pytest.mark.parametrize(("title", "summary"), [(None, "Summary"), ("Title", 42)])
def test_semantic_query_rejects_non_string_fields(title, summary):
    with pytest.raises(TypeError, match="must be strings"):
        semantic_query_text(title, summary)
