from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol

from harness.rag.chunker import Chunk


class VectorStoreProtocol(Protocol):
    def add_batch(self, items: list[tuple[Chunk, list[float]]]) -> None: ...
    def size(self) -> int: ...
    def clear(self) -> None: ...
    def sources(self) -> list[str]: ...
    async def search(self, embed_fn: Any, query: str, top_k: int = 5) -> list[Any]: ...
    def close(self) -> None: ...


@dataclass(slots=True)
class StoredChunk(Chunk):
    embedding: list[float]
    added_at: int


class VectorStore:
    def __init__(self) -> None:
        self.chunks: list[StoredChunk] = []

    def add(self, chunk: Chunk, embedding: list[float]) -> None:
        stored = StoredChunk(
            chunk.id, chunk.text, chunk.source, chunk.index, chunk.token_estimate, embedding, int(time.time() * 1000)
        )
        for index, existing in enumerate(self.chunks):
            if existing.id == chunk.id:
                self.chunks[index] = stored
                return
        self.chunks.append(stored)

    def add_batch(self, items: list[tuple[Chunk, list[float]]]) -> None:
        for chunk, embedding in items:
            self.add(chunk, embedding)

    def get_all(self) -> list[StoredChunk]:
        return self.chunks

    def size(self) -> int:
        return len(self.chunks)

    def clear(self) -> None:
        self.chunks.clear()

    def sources(self) -> list[str]:
        return list(dict.fromkeys(chunk.source for chunk in self.chunks))

    async def search(self, embed_fn: Any, query: str, top_k: int = 5) -> list[Any]:
        from harness.rag.search import hybrid_search

        return await hybrid_search(self, embed_fn, query, top_k)

    def close(self) -> None:
        return None
