from __future__ import annotations

import importlib
import json
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any

from harness.rag.chunker import Chunk
from harness.rag.embedder import EmbeddingFn, embed
from harness.rag.search import SearchResult, mmr_select
from harness.rag.store import StoredChunk


class SqliteVectorStore:
    """Optional sqlite-vec backed store. Install the ``sqlite-vec`` extra before constructing it."""

    def __init__(self, db_path: str | Path = "knowledge.db") -> None:
        try:
            sqlite_vec = importlib.import_module("sqlite_vec")
        except ImportError as error:
            raise RuntimeError("SqliteVectorStore requires: uv sync --extra sqlite-vec") from error
        self.db = sqlite3.connect(db_path)
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self._create_tables()

    def _create_tables(self) -> None:
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (id TEXT PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL, chunk_index INTEGER NOT NULL, embedding TEXT NOT NULL, model TEXT NOT NULL DEFAULT 'text-embedding-v3', updated_at INTEGER NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[128]);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, id UNINDEXED, source UNINDEXED);
        """)

    @staticmethod
    def _blob(vector: list[float]) -> bytes:
        return struct.pack(f"{len(vector)}f", *vector)

    def add(self, chunk: Chunk, embedding: list[float]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO chunks (id,text,source,chunk_index,embedding,updated_at) VALUES (?,?,?,?,?,?)",
            (chunk.id, chunk.text, chunk.source, chunk.index, json.dumps(embedding), int(time.time() * 1000)),
        )
        self.db.execute(
            "INSERT OR REPLACE INTO chunks_vec (id,embedding) VALUES (?,?)", (chunk.id, self._blob(embedding))
        )
        self.db.execute("DELETE FROM chunks_fts WHERE id = ?", (chunk.id,))
        self.db.execute("INSERT INTO chunks_fts (id,text,source) VALUES (?,?,?)", (chunk.id, chunk.text, chunk.source))
        self.db.commit()

    def add_batch(self, items: list[tuple[Chunk, list[float]]]) -> None:
        for chunk, vector in items:
            self.add(chunk, vector)

    @staticmethod
    def _chunk(row: sqlite3.Row | tuple[Any, ...]) -> StoredChunk:
        return StoredChunk(
            str(row[0]), str(row[2]), str(row[3]), int(row[4]), math_ceil_quarter(str(row[2])), json.loads(row[5]), 0
        )

    def vector_search(self, query: list[float], top_k: int) -> list[tuple[StoredChunk, float]]:
        rows = self.db.execute(
            "SELECT v.id,v.distance,c.text,c.source,c.chunk_index,c.embedding FROM chunks_vec v JOIN chunks c ON c.id=v.id WHERE v.embedding MATCH ? ORDER BY v.distance LIMIT ?",
            (self._blob(query), top_k),
        ).fetchall()
        return [(self._chunk(row), 1 - float(row[1])) for row in rows]

    def keyword_search(self, query: str, top_k: int) -> list[tuple[StoredChunk, float]]:
        rows = self.db.execute(
            "SELECT f.id,bm25(chunks_fts),c.text,c.source,c.chunk_index,c.embedding FROM chunks_fts f JOIN chunks c ON c.id=f.id WHERE chunks_fts MATCH ? ORDER BY 2 LIMIT ?",
            (query, top_k),
        ).fetchall()
        return [
            (self._chunk(row), -float(row[1]) / (1 - float(row[1])) if float(row[1]) < 0 else 1 / (1 + float(row[1])))
            for row in rows
        ]

    def size(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def clear(self) -> None:
        self.db.executescript("DELETE FROM chunks; DELETE FROM chunks_vec; DELETE FROM chunks_fts;")
        self.db.commit()

    def sources(self) -> list[str]:
        return [str(row[0]) for row in self.db.execute("SELECT DISTINCT source FROM chunks")]

    async def hybrid_search(self, embed_fn: EmbeddingFn, query: str, top_k: int = 5) -> list[SearchResult]:
        count = min(top_k * 4, self.size())
        if not count:
            return []
        vector = (await embed(embed_fn, [query]))[0]
        vector_results, keyword_results = self.vector_search(vector, count), self.keyword_search(query, count)
        vector_scores, keyword_scores = (
            _minmax([score for _, score in vector_results]),
            _minmax([score for _, score in keyword_results]),
        )
        candidates: dict[str, SearchResult] = {}
        for (chunk, _), score in zip(vector_results, vector_scores, strict=True):
            candidates[chunk.id] = SearchResult(chunk, score * 0.7, score, 0)
        for (chunk, _), score in zip(keyword_results, keyword_scores, strict=True):
            if chunk.id in candidates:
                candidates[chunk.id].keyword_score = score
                candidates[chunk.id].score += score * 0.3
            else:
                candidates[chunk.id] = SearchResult(chunk, score * 0.3, 0, score)
        return mmr_select(sorted(candidates.values(), key=lambda item: item.score, reverse=True), top_k)

    async def search(self, embed_fn: EmbeddingFn, query: str, top_k: int = 5) -> list[SearchResult]:
        return await self.hybrid_search(embed_fn, query, top_k)

    def close(self) -> None:
        self.db.close()


def math_ceil_quarter(text: str) -> int:
    return (len(text) + 3) // 4


def _minmax(scores: list[float]) -> list[float]:
    if not scores:
        return []
    minimum, maximum = min(scores), max(scores)
    value_range = maximum - minimum or 1
    return [(value - minimum) / value_range for value in scores]
