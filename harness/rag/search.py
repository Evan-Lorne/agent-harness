from __future__ import annotations

import math
import re
from dataclasses import dataclass

from harness.rag.embedder import EmbeddingFn, cosine_similarity, embed
from harness.rag.store import StoredChunk, VectorStore


@dataclass(slots=True)
class SearchResult:
    chunk: StoredChunk
    score: float
    vector_score: float
    keyword_score: float


def _tokenize(text: str) -> list[str]:
    return [token for token in re.sub(r"[^\w一-鿿]+", " ", text.lower()).split() if len(token) > 1]


def _bm25_score(terms: list[str], text: str, documents: list[StoredChunk]) -> float:
    document_tokens = _tokenize(text)
    count = len(documents)
    average_length = sum(len(_tokenize(item.text)) for item in documents) / (count or 1)
    score = 0.0
    for term in terms:
        term_frequency = document_tokens.count(term)
        document_frequency = sum(term in _tokenize(item.text) for item in documents)
        inverse = math.log((count - document_frequency + 0.5) / (document_frequency + 0.5) + 1)
        denominator = (
            term_frequency + 1.2 * (0.25 + 0.75 * len(document_tokens) / average_length) if average_length else 1
        )
        score += inverse * term_frequency * 2.2 / denominator
    return score


def _minmax(scores: list[float]) -> list[float]:
    if not scores:
        return []
    minimum, maximum = min(scores), max(scores)
    value_range = maximum - minimum or 1
    return [(score - minimum) / value_range for score in scores]


def _jaccard(left: str, right: str) -> float:
    a, b = set(_tokenize(left)), set(_tokenize(right))
    union = a | b
    return len(a & b) / len(union) if union else 0


def mmr_select(results: list[SearchResult], top_k: int) -> list[SearchResult]:
    if len(results) <= top_k:
        return results
    selected = [results[0]]
    remaining = results[1:]
    while len(selected) < top_k and remaining:
        best_index = max(
            range(len(remaining)),
            key=lambda index: (
                0.7 * remaining[index].score
                - 0.3 * max(_jaccard(item.chunk.text, remaining[index].chunk.text) for item in selected)
            ),
        )
        selected.append(remaining.pop(best_index))
    return selected


async def hybrid_search(store: VectorStore, embed_fn: EmbeddingFn, query: str, top_k: int = 5) -> list[SearchResult]:
    documents = store.get_all()
    if not documents:
        return []
    candidate_count = min(top_k * 4, len(documents))
    query_vector = (await embed(embed_fn, [query]))[0]
    vectors = sorted(
        ((chunk, cosine_similarity(query_vector, chunk.embedding)) for chunk in documents),
        key=lambda item: item[1],
        reverse=True,
    )[:candidate_count]
    keywords = sorted(
        ((chunk, _bm25_score(_tokenize(query), chunk.text, documents)) for chunk in documents),
        key=lambda item: item[1],
        reverse=True,
    )[:candidate_count]
    vector_norm = _minmax([score for _, score in vectors])
    keyword_norm = [1 / (1 + math.exp(-score)) for _, score in keywords]
    candidates: dict[str, SearchResult] = {}
    for (chunk, _), score in zip(vectors, vector_norm, strict=True):
        candidates[chunk.id] = SearchResult(chunk, score * 0.7, score, 0)
    for (chunk, _), score in zip(keywords, keyword_norm, strict=True):
        if chunk.id in candidates:
            candidates[chunk.id].keyword_score = score
            candidates[chunk.id].score += score * 0.3
        else:
            candidates[chunk.id] = SearchResult(chunk, score * 0.3, 0, score)
    return mmr_select(sorted(candidates.values(), key=lambda item: item.score, reverse=True), top_k)
