"""Provider-neutral semantic query embedding boundary."""
from __future__ import annotations

from typing import Protocol


class QueryEmbedder(Protocol):
    async def embed_queries(self, texts: list[str]) -> list[list[float]]: ...
