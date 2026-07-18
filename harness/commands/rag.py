from __future__ import annotations

from harness.commands import CommandContext, CommandHandler


async def rag_handler(command: str, context: CommandContext) -> bool:
    if command not in {"/rag", "rag"}:
        return False
    print(f"\n[知识库] {context.vector_store.size()} 个片段")
    if context.vector_store.sources():
        print(f"  来源: {', '.join(context.vector_store.sources())}")
    print()
    return True


async def ingest_handler(command: str, context: CommandContext) -> bool:
    if not command.startswith("ingest "):
        return False
    path = command[len("ingest ") :].strip()
    print(f"\n[导入] 正在处理 {path}...")
    tool = context.registry.get("rag_ingest")
    print(f"  {await tool.execute({'path': path}) if tool else 'rag_ingest 工具未启用'}\n")
    return True


rag_commands: list[CommandHandler] = [rag_handler, ingest_handler]
