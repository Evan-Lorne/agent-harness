from __future__ import annotations

import math
import re
from dataclasses import dataclass

from harness.memory.types import MemoryEntry


@dataclass(slots=True)
class SearchHit:
    entry: MemoryEntry
    score: float


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    buffer = ""
    for character in text.lower():
        if re.match(r"[a-z0-9_]", character):
            buffer += character
        elif "\u4e00" <= character <= "\u9fa5":
            if buffer:
                tokens.append(buffer)
                buffer = ""
            tokens.append(character)
        elif buffer:
            tokens.append(buffer)
            buffer = ""
    if buffer:
        tokens.append(buffer)
    return tokens


def bm25_search(entries: list[MemoryEntry], query: str, top_k: int = 5) -> list[SearchHit]:
    if not entries or not query.strip():
        return []
    query_tokens = tokenize(query)
    if not query_tokens:
        return []
    documents = [
        tokenize(f"{entry.name} {entry.name} {entry.name} {entry.description} {entry.description} {entry.content}")
        for entry in entries
    ]
    count = len(documents)
    average_length = sum(map(len, documents)) / count
    frequencies: dict[str, int] = {}
    for document in documents:
        for token in set(document):
            frequencies[token] = frequencies.get(token, 0) + 1

    hits: list[SearchHit] = []
    for entry, document in zip(entries, documents, strict=True):
        score = 0.0
        for token in query_tokens:
            document_frequency = frequencies.get(token, 0)
            term_frequency = document.count(token)
            if not document_frequency or not term_frequency:
                continue
            inverse = math.log((count - document_frequency + 0.5) / (document_frequency + 0.5) + 1)
            norm = term_frequency * 2.5 / (term_frequency + 1.5 * (0.25 + 0.75 * len(document) / average_length))
            score += inverse * norm
        if score > 0:
            hits.append(SearchHit(entry, score))
    return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]
