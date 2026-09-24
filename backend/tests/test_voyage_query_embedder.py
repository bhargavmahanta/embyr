"""Provider adapter sends versioned query settings and validates results."""
from __future__ import annotations

import asyncio

import httpx

from app.integrations.voyage import VoyageQueryEmbedder


def test_voyage_query_embedding_uses_reviewed_identity_and_dimension():
    captured = {}
    vector = [1.0] + [0.0] * 1023

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"model": "voyage-4", "data": [
            {"index": 0, "embedding": vector},
        ]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await VoyageQueryEmbedder("test-key", client).embed_queries(["Title\n\nSummary"])

    assert asyncio.run(run()) == [vector]
    assert captured["url"] == "https://api.voyageai.com/v1/embeddings"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["payload"] == {
        "input": ["Title\n\nSummary"], "model": "voyage-4",
        "input_type": "query", "output_dimension": 1024,
        "output_dtype": "float", "truncation": False,
    }
