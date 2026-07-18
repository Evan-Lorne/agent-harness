from __future__ import annotations

from pathlib import Path

from harness.rag.chunker import chunk_document
from harness.rag.embedder import EmbeddingFn, embed
from harness.rag.store import VectorStoreProtocol
from harness.tools.registry import ToolDefinition


def create_rag_tools(vector_store: VectorStoreProtocol, embed_fn: EmbeddingFn) -> list[ToolDefinition]:
    async def ingest(args: dict) -> str:
        try:
            path = args["path"]
            chunks = chunk_document(path, Path(path).read_text(encoding="utf-8"))
            embeddings = await embed(embed_fn, [chunk.text for chunk in chunks])
            vector_store.add_batch(list(zip(chunks, embeddings, strict=True)))
            return f"已导入 {len(chunks)} 个文档片段（来源: {path}）。知识库共 {vector_store.size()} 个片段。"
        except Exception as error:
            return f"导入失败: {error}"

    async def search(args: dict) -> str:
        if not vector_store.size():
            return "知识库为空，请先使用 rag_ingest 导入文档。"
        query = args["query"]
        results = await vector_store.search(embed_fn, query, args.get("top_k") or 5)
        if not results:
            return f'没有找到与 "{query}" 相关的内容。'
        return "\n\n---\n\n".join(
            f"[{index}] 来源: {result.chunk.source} | 综合分: {result.score:.3f} (向量: {result.vector_score:.2f}, 关键词: {result.keyword_score:.2f})\n{result.chunk.text[:500]}"
            for index, result in enumerate(results, 1)
        )

    ingest_tool = ToolDefinition(
        "rag_ingest",
        "将文档导入知识库。path 为文件路径，内容会被分块、向量化后存储。",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文档路径"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        ingest,
    )
    search_tool = ToolDefinition(
        "rag_search",
        "从知识库中搜索相关信息。返回最相关的文档片段。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询"},
                "top_k": {"type": "number", "description": "返回结果数量（默认 5）"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        search,
        True,
        True,
    )
    return [ingest_tool, search_tool]
