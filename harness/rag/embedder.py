from __future__ import annotations

import math
from collections.abc import Awaitable, Callable

import httpx

DIMS = 128
EmbeddingFn = Callable[[list[str]], Awaitable[list[list[float]]]]
_embed_cache: dict[str, list[float]] = {}


def _mock_embed(text: str) -> list[float]:
    vector = [0.0] * DIMS
    for index, character in enumerate(text):
        code = ord(character)
        vector[index % DIMS] += code
        vector[(index * 7 + 13) % DIMS] += code * 0.3
    norm = math.sqrt(sum(value * value for value in vector)) or 1
    return [value / norm for value in vector]


def create_mock_embedder() -> EmbeddingFn:
    async def embedder(texts: list[str]) -> list[list[float]]:
        return [_mock_embed(text) for text in texts]

    return embedder


def create_dashscope_embedder(api_key: str) -> EmbeddingFn:
    async def embedder(texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "text-embedding-v3", "input": texts, "dimensions": DIMS},
            )
        if not response.is_success:
            raise RuntimeError(f"Embedding API error: {response.status_code} {response.text}")
        return [item["embedding"] for item in response.json()["data"]]

    return embedder


async def embed(function: EmbeddingFn, texts: list[str]) -> list[list[float]]:
    results: list[list[float] | None] = [None] * len(texts)
    uncached: list[tuple[int, str]] = []
    for index, text in enumerate(texts):
        if text in _embed_cache:
            results[index] = _embed_cache[text]
        else:
            uncached.append((index, text))
    if uncached:
        vectors = await function([text for _, text in uncached])
        for (index, text), vector in zip(uncached, vectors, strict=True):
            results[index] = vector
            _embed_cache[text] = vector
    return [value for value in results if value is not None]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm_left = math.sqrt(sum(value * value for value in left))
    norm_right = math.sqrt(sum(value * value for value in right))
    return dot / (norm_left * norm_right or 1)
