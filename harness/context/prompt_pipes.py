from __future__ import annotations

from harness.context.prompt_builder import Pipe, PromptContext
from harness.memory.store import MemoryStore
from harness.rag.store import VectorStoreProtocol


def memory_context(memory_store: MemoryStore) -> Pipe:
    return lambda _context: memory_store.build_prompt_section()


def rag_context(vector_store: VectorStoreProtocol) -> Pipe:
    def build(_context: PromptContext) -> str | None:
        if not vector_store.size():
            return None
        return f"[知识库] 已导入 {vector_store.size()} 个文档片段（来源: {', '.join(vector_store.sources())}）。使用 rag_search 工具搜索知识库。"

    return build
