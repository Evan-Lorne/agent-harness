from __future__ import annotations

import math
import re
from dataclasses import dataclass

TARGET_CHARS = 512 * 4


@dataclass(slots=True)
class Chunk:
    id: str
    text: str
    source: str
    index: int
    token_estimate: int


def _make_chunk(source: str, text: str, index: int) -> Chunk:
    return Chunk(f"{source}#{index}", text, source, index, math.ceil(len(text) / 4))


def chunk_document(source: str, text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    current = ""
    index = 0
    for paragraph in re.split(r"\n{2,}", text):
        trimmed = paragraph.strip()
        if not trimmed:
            continue
        if len(current) + len(trimmed) + 2 > TARGET_CHARS and current:
            chunks.append(_make_chunk(source, current.strip(), index))
            index += 1
            current = ""
        if len(trimmed) > TARGET_CHARS:
            if current:
                chunks.append(_make_chunk(source, current.strip(), index))
                index += 1
                current = ""
            sentences = re.split(r"(?<=[。！？.!?])\s*", trimmed)
            sentence_buffer = ""
            for sentence in sentences:
                if len(sentence_buffer) + len(sentence) + 1 > TARGET_CHARS and sentence_buffer:
                    chunks.append(_make_chunk(source, sentence_buffer.strip(), index))
                    index += 1
                    sentence_buffer = ""
                sentence_buffer += (" " if sentence_buffer else "") + sentence
            if sentence_buffer.strip():
                current = sentence_buffer.strip()
        else:
            current += ("\n\n" if current else "") + trimmed
    if current.strip():
        chunks.append(_make_chunk(source, current.strip(), index))
    return chunks
