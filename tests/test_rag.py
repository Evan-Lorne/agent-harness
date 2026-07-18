from __future__ import annotations

from harness.rag.chunker import chunk_document
from harness.rag.embedder import create_mock_embedder, embed
from harness.rag.search import hybrid_search
from harness.rag.store import VectorStore


async def test_chunk_embed_and_hybrid_search() -> None:
    embedder = create_mock_embedder()
    chunks = chunk_document(
        "guide.md",
        "部署需要先运行测试。\n\n发生故障时回滚到上一个版本。\n\n监控发布后的错误率。",
    )
    vectors = await embed(embedder, [chunk.text for chunk in chunks])
    store = VectorStore()
    store.add_batch(list(zip(chunks, vectors, strict=True)))

    results = await hybrid_search(store, embedder, "部署回滚", 2)

    assert store.size() == len(chunks)
    assert results
    assert results[0].chunk.source == "guide.md"
    assert 0 <= results[0].score <= 1
