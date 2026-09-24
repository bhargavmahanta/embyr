"""Voyage AI adapter for the versioned M4 query embedding policy."""
from __future__ import annotations

import math

import httpx

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
MODEL = "voyage-4"
DIMENSION = 1024
MAX_BATCH = 64


class EmbeddingProviderError(RuntimeError):
    pass


class VoyageQueryEmbedder:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None):
        if not api_key:
            raise ValueError("Voyage API key is required")
        self._api_key = api_key
        self._client = client

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not text for text in texts):
            raise ValueError("empty semantic query")
        output: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH):
            batch = texts[start : start + MAX_BATCH]
            output.extend(await self._embed_batch(batch))
        return output

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        async def send(client: httpx.AsyncClient) -> httpx.Response:
            return await client.post(
                VOYAGE_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "input": texts, "model": MODEL, "input_type": "query",
                    "output_dimension": DIMENSION, "output_dtype": "float",
                    "truncation": False,
                },
            )

        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await send(client)
            else:
                response = await send(self._client)
            response.raise_for_status()
            payload = response.json()
            if payload.get("model") != MODEL:
                raise EmbeddingProviderError("Voyage returned an unexpected model identity")
            data = payload["data"]
            if len(data) != len(texts):
                raise EmbeddingProviderError("Voyage returned the wrong number of embeddings")
            ordered = sorted(data, key=lambda item: item["index"])
            if [item["index"] for item in ordered] != list(range(len(texts))):
                raise EmbeddingProviderError("Voyage returned invalid embedding indices")
            vectors = [item["embedding"] for item in ordered]
            if any(
                len(vector) != DIMENSION
                or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector)
                for vector in vectors
            ):
                raise EmbeddingProviderError("Voyage returned invalid embedding dimensions or values")
            return [[float(value) for value in vector] for vector in vectors]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise EmbeddingProviderError("Voyage query embedding failed") from error
