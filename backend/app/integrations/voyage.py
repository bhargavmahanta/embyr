"""Voyage AI adapter for the versioned M4 query embedding policy."""
from __future__ import annotations

import json
import math

import httpx

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
MODEL = "voyage-4"
DIMENSION = 1024
MAX_BATCH = 64


class EmbeddingProviderError(RuntimeError):
    pass


def _validated_vectors(payload: object, expected_count: int) -> list[list[float]]:
    """Validate a Voyage batch before using provider-controlled fields."""
    if not isinstance(payload, dict):
        raise EmbeddingProviderError("Voyage returned an invalid embedding response")
    if payload.get("model") != MODEL:
        raise EmbeddingProviderError("Voyage returned an unexpected model identity")
    data = payload.get("data")
    if not isinstance(data, list):
        raise EmbeddingProviderError("Voyage returned invalid embedding data")
    if len(data) != expected_count:
        raise EmbeddingProviderError("Voyage returned the wrong number of embeddings")

    ordered: list[list[float] | None] = [None] * expected_count
    for item in data:
        if not isinstance(item, dict):
            raise EmbeddingProviderError("Voyage returned an invalid embedding entry")
        index = item.get("index")
        if type(index) is not int or not 0 <= index < expected_count or ordered[index] is not None:
            raise EmbeddingProviderError("Voyage returned invalid embedding indices")
        embedding = item.get("embedding")
        if not isinstance(embedding, list) or len(embedding) != DIMENSION:
            raise EmbeddingProviderError("Voyage returned invalid embedding dimensions or values")
        vector = []
        for value in embedding:
            if type(value) not in (int, float):
                raise EmbeddingProviderError("Voyage returned invalid embedding dimensions or values")
            try:
                component = float(value)
            except OverflowError as error:
                raise EmbeddingProviderError("Voyage returned invalid embedding dimensions or values") from error
            if not math.isfinite(component):
                raise EmbeddingProviderError("Voyage returned invalid embedding dimensions or values")
            vector.append(component)
        ordered[index] = vector
    if any(vector is None for vector in ordered):
        raise EmbeddingProviderError("Voyage returned invalid embedding indices")
    return [vector for vector in ordered if vector is not None]


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
        except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise EmbeddingProviderError("Voyage query embedding failed") from error
        return _validated_vectors(payload, len(texts))
