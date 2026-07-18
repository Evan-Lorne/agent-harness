from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from harness.agent.loop import BudgetState, ContextState, agent_loop
from harness.agents.registry import SubAgentRegistry
from harness.agents.spawn import SpawnContext
from harness.agents.types import SubAgentConfig
from harness.channels.feishu import FeishuChannel
from harness.channels.gateway import ChannelGateway, GatewayOptions
from harness.commands import CommandContext, create_dispatcher
from harness.commands.agent import create_agent_commands
from harness.commands.channel import create_channel_commands
from harness.commands.context import context_commands
from harness.commands.cron import create_cron_commands
from harness.commands.debug import debug_commands
from harness.commands.dream import dream_commands
from harness.commands.memory import memory_commands
from harness.commands.plugin import create_plugin_commands
from harness.commands.rag import rag_commands
from harness.commands.security import create_security_commands
from harness.commands.skill import create_skill_commands
from harness.config.loader import load_config
from harness.config.schema import MCPServerConfig, ModelConfig, RagConfig
from harness.context.compact_tool import compact_tool
from harness.context.defense import estimate_message_tokens
from harness.context.prompt_builder import (
    PromptBuilder,
    PromptContext,
    core_rules,
    deferred_tools,
    session_context,
    tool_guide,
)
from harness.context.prompt_pipes import memory_context, rag_context
from harness.cron.service import CronExecutor, CronService
from harness.memory.store import MemoryStore
from harness.mock_model import create_mock_model
from harness.model import OpenAIModel
from harness.plugins.manager import PluginManager
from harness.plugins.supabase_plugin import supabase_plugin
from harness.rag.chunker import chunk_document
from harness.rag.embedder import create_dashscope_embedder, create_mock_embedder, embed
from harness.rag.sqlite_store import SqliteVectorStore
from harness.rag.store import VectorStore, VectorStoreProtocol
from harness.security.hooks import HookPipeline, HookResult
from harness.session.store import SessionStore
from harness.skills.loader import SkillLoader, create_load_skill_tool
from harness.tasks.store import TaskStore
from harness.tasks.tools import create_task_tools
from harness.teams.manager import TeamManager
from harness.teams.tools import create_team_tools
from harness.tools.cron_tools import create_cron_tool
from harness.tools.index import all_tools
from harness.tools.mcp import MockMCPClient, StdioMCPClient
from harness.tools.mcp_tools import create_connect_mcp_tool
from harness.tools.memory_tools import create_memory_tool
from harness.tools.rag_tools import create_rag_tools
from harness.tools.registry import ToolRegistry
from harness.tools.spawn_tools import create_spawn_tool
from harness.tools.todo_tools import TodoStore, create_todo_tool
from harness.tools.tool_search import create_tool_search_tool
from harness.types import Message, Model, content_to_text
from harness.usage.tracker import UsageTracker
from harness.worktrees.manager import WorktreeManager
from harness.worktrees.tools import create_worktree_tools


async def async_input(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[str] = loop.create_future()

    def on_readable() -> None:
        line = sys.stdin.readline()
        if not future.done():
            future.set_result(line)

    print(prompt, end="", flush=True)
    loop.add_reader(sys.stdin.fileno(), on_readable)
    try:
        line = await future
    finally:
        loop.remove_reader(sys.stdin.fileno())

    if line == "":
        raise EOFError
    return line.removesuffix("\n")


def create_model(config: ModelConfig) -> Model:
    if not config.api_key or config.api_key.startswith("${"):
        return create_mock_model()
    return OpenAIModel(config.name, api_key=config.api_key, base_url=config.base_url)


def create_vector_store(config: RagConfig) -> VectorStoreProtocol:
    if config.enabled and config.store == "sqlite":
        return SqliteVectorStore(config.database_path)
    return VectorStore()


async def register_configured_mcp(registry: ToolRegistry, servers: list[MCPServerConfig]) -> list[str]:
    enabled = [server for server in servers if server.enabled]
    if not enabled:
        tools = await registry.register_mcp_server("github", MockMCPClient())
        print(f"  已注册 {len(tools)} 个 Mock MCP 工具")
        return tools

    registered: list[str] = []
    for server in enabled:
        client = StdioMCPClient(server.command, server.args, server.env)
        try:
            tools = await registry.register_mcp_server(server.name, client)
        except Exception as error:
            print(f"  ✗ MCP {server.name} 连接失败: {error}")
            continue
        registered.extend(tools)
        print(f"  ✓ MCP {server.name} — {len(tools)} 个工具")
    return registered


async def start_agent(*, continue_session: bool = False) -> None:
    config = load_config()
    model = create_model(config.model)
    registry = ToolRegistry()
    registry.set_role(config.security.default_role)
    registry.register(*all_tools)
    registry.register(compact_tool)
    registry.register(create_tool_search_tool(registry))
    registry.register(create_todo_tool(TodoStore()))

    task_store = TaskStore(".")
    task_store.init()
    registry.register(*create_task_tools(task_store))
    worktrees = WorktreeManager(".", task_store)
    registry.register(*create_worktree_tools(worktrees))

    memory_store = MemoryStore(config.memory.data_dir)
    memory_store.init()
    registry.register(create_memory_tool(memory_store))

    vector_store = create_vector_store(config.rag)
    embed_fn = (
        create_dashscope_embedder(config.rag.api_key)
        if config.rag.api_key and not config.rag.api_key.startswith("${")
        else create_mock_embedder()
    )
    if config.rag.enabled:
        registry.register(*create_rag_tools(vector_store, embed_fn))

    if any(server.enabled for server in config.mcp_servers):
        registry.register(create_connect_mcp_tool(registry, config.mcp_servers))
    else:
        await register_configured_mcp(registry, config.mcp_servers)

    skill_loader = SkillLoader(".")
    skill_loader.load()
    active_skills: set[str] = set()
    registry.register(create_load_skill_tool(skill_loader))

    plugin_manager = PluginManager(registry)
    available_plugins = {"supabase": supabase_plugin}
    configured_plugins = {plugin.name: plugin.config for plugin in config.plugins}

    hooks = HookPipeline()
    if config.security.audit_log:

        def audit(tool_name: str, input_value: dict) -> HookResult:
            if tool_name in {"write_file", "edit_file"}:
                print(f"  [audit] 文件写入操作: {tool_name} → {input_value.get('path', 'unknown')}")
            return HookResult("allow")

        hooks.register_pre("audit-log", audit)
    if config.security.bash_timestamp:

        def timestamp(tool_name: str, _input: dict, output: str) -> HookResult:
            return (
                HookResult(
                    "modify", modified_output=f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}]\n{output}"
                )
                if tool_name == "bash"
                else HookResult("allow")
            )

        hooks.register_post("bash-timestamp", timestamp)
    registry.set_hook_pipeline(hooks)

    hooks.register_user("workspace-context", lambda _query: HookResult("allow"))
    hooks.register_stop("turn-finished", lambda _messages: HookResult("allow"))

    async def approve(tool_name: str, input_value: dict, reason: str) -> bool:
        print(f"\n  [审批] {reason}\n  工具: {tool_name}\n  参数: {input_value}")
        try:
            answer = await async_input("  允许执行? [y/N] ")
        except EOFError:
            return False
        return answer.strip().lower() in {"y", "yes"}

    registry.set_approval_handler(approve)

    cron_service = CronService(config.cron.data_dir) if config.cron.enabled else None
    if cron_service:
        registry.register(create_cron_tool(cron_service))
    agent_registry = SubAgentRegistry(
        SubAgentConfig(config.agents.max_spawn_depth, config.agents.max_concurrent, config.agents.default_timeout)
    )
    team_manager = TeamManager(model, registry, task_store, worktrees)
    registry.register(*create_team_tools(team_manager))
    registry.register_notification_provider(team_manager.collect_lead_inbox)

    session_store = SessionStore(config.session.id)
    messages: list[Message] = session_store.load() if continue_session else []
    timestamps = {index: int(time.time() * 1000) for index in range(len(messages))}
    tracker = UsageTracker(config.usage.tracking_file)
    budget = BudgetState()
    context_state = ContextState()
    agent_lock = asyncio.Lock()

    def make_prompt_context() -> PromptContext:
        return PromptContext(
            len(registry.get_active_tools()), registry.get_deferred_tool_summary(), len(messages), config.session.id
        )

    builder = (
        PromptBuilder()
        .pipe("coreRules", core_rules())
        .pipe("toolGuide", tool_guide())
        .pipe("deferredTools", deferred_tools())
        .pipe("memoryContext", memory_context(memory_store))
    )
    if config.rag.enabled:
        builder.pipe("ragContext", rag_context(vector_store))
    builder.pipe("skillContext", lambda _context: skill_loader.build_prompt_section(active_skills)).pipe(
        "sessionContext", session_context()
    )

    def spawn_context() -> SpawnContext:
        return SpawnContext(model, registry, agent_registry, lambda: builder.build(make_prompt_context()), 0)

    registry.register(create_spawn_tool(agent_registry, spawn_context))

    gateway = ChannelGateway(GatewayOptions(model, registry, lambda: builder.build(make_prompt_context()), agent_lock))
    if config.channels.feishu.enabled:
        gateway.register(
            FeishuChannel(config.channels.feishu.app_id, config.channels.feishu.app_secret, config.channels.feishu.port)
        )

    handlers = [*debug_commands, *context_commands, *memory_commands]
    if config.rag.enabled:
        handlers.extend(rag_commands)
    handlers.extend(dream_commands)
    handlers.extend(create_skill_commands(skill_loader, active_skills))
    handlers.extend(create_plugin_commands(plugin_manager, available_plugins, configured_plugins))
    handlers.extend(create_channel_commands(gateway))
    handlers.extend(create_security_commands(registry, hooks))
    if cron_service:
        handlers.extend(create_cron_commands(cron_service))
    handlers.extend(create_agent_commands(agent_registry))
    dispatch = create_dispatcher(handlers)

    for plugin_config in config.plugins:
        definition = available_plugins.get(plugin_config.name)
        if not definition:
            print(f"  ✗ {plugin_config.name} — 未知插件")
        elif not plugin_config.enabled:
            print(f"  - {plugin_config.name} — 已禁用")
        else:
            try:
                tools = await plugin_manager.load(definition, plugin_config.config)
            except Exception as error:
                print(f"  ✗ {plugin_config.name} — 加载失败: {error}")
            else:
                print(f"  ✓ {plugin_config.name} — {len(tools)} 个工具")

    print("  启动 Channel...")
    await gateway.start_all()
    if cron_service:

        async def run_cron_prompt(prompt: str, _timeout: int | None) -> str:
            cron_messages: list[Message] = [{"role": "user", "content": prompt}]
            async with agent_lock:
                await agent_loop(
                    model, registry, cron_messages, builder.build(make_prompt_context()), memory_store=memory_store
                )
            last = cron_messages[-1] if cron_messages else None
            return content_to_text(last.get("content")) if last else "(无输出)"

        cron_service.load()
        cron_service.set_executor(CronExecutor(run_cron_prompt, lambda value: print(f"\n{value}")))
        cron_service.start()

    await _ingest_docs(config.rag.docs_dir, vector_store, embed_fn) if config.rag.enabled else None
    _print_banner(registry, agent_registry, cron_service is not None, continue_session and bool(messages))

    context = CommandContext(
        messages=messages,
        timestamps=timestamps,
        registry=registry,
        builder=builder,
        tracker=tracker,
        session_store=session_store,
        model=model,
        make_prompt_context=make_prompt_context,
        memory_store=memory_store,
        budget=budget,
        context_state=context_state,
        vector_store=vector_store,
    )
    try:
        while True:
            try:
                value = await async_input("\nYou: ")
            except EOFError:
                value = "exit"
            command = value.strip()
            if not command or command == "exit":
                print("Bye!")
                break
            if await dispatch(command, context):
                continue
            submitted = await hooks.run_user(command)
            if submitted.action == "block":
                continue
            final_command = submitted.modified_input if isinstance(submitted.modified_input, str) else command
            user_message = {"role": "user", "content": final_command}
            messages.append(user_message)
            timestamps[len(messages) - 1] = int(time.time() * 1000)
            session_store.append(user_message)
            async with agent_lock:
                await agent_loop(
                    model,
                    registry,
                    messages,
                    builder.build(make_prompt_context()),
                    tracker,
                    budget,
                    timestamps,
                    context_state,
                    memory_store,
                )
            session_store.replace_all(messages)
            print(f"  [Token] ~{estimate_message_tokens(messages)} tokens")
    finally:
        if cron_service:
            cron_service.stop()
        for name, close in (
            ("team", team_manager.close),
            ("gateway", gateway.stop_all),
            ("plugins", plugin_manager.unload_all),
            ("mcp", registry.close_all_mcp),
        ):
            try:
                await close()
            except Exception as error:
                print(f"  [cleanup] {name} 清理失败: {error}")
        try:
            vector_store.close()
        except Exception as error:
            print(f"  [cleanup] vector store 清理失败: {error}")


async def _ingest_docs(directory: str, store: VectorStoreProtocol, embed_fn: object) -> None:
    path = Path(directory)
    files = list(path.glob("*.md")) if path.exists() else []
    if not files:
        return
    print(f"  发现 {len(files)} 个文档，自动导入知识库...")
    for file in files:
        try:
            chunks = chunk_document(str(file), file.read_text(encoding="utf-8"))
            embeddings = await embed(embed_fn, [chunk.text for chunk in chunks])  # type: ignore[arg-type]
            store.add_batch(list(zip(chunks, embeddings, strict=True)))
        except Exception as error:
            print(f"  [RAG] 导入 {file} 失败，跳过知识库初始化: {error}")
            return
    print(f"  知识库就绪，共 {store.size()} 个片段\n")


def _print_banner(registry: ToolRegistry, agents: SubAgentRegistry, cron_enabled: bool, resumed: bool) -> None:
    print('Agent Harness v1.0 (type "exit" to quit)')
    print("快捷命令：\n  /agents           — 查看子 Agent 记录")
    if cron_enabled:
        print("  /cron             — 查看定时任务")
    print("  /role [角色]      — 查看/切换角色")
    print(f"\n  当前角色: {registry.get_role()}，可用工具: {len(registry.get_active_tools())} 个")
    print(f"  Sub-Agent: 最大深度 {agents.config.max_spawn_depth}，最大并发 {agents.config.max_concurrent}")
    if resumed:
        print("  已恢复历史会话")
    print(
        "\n  试试：\n    帮我对比 FastAPI、Litestar 和 Django Ninja 的性能和生态\n    /agents       — 查看子 Agent 执行记录\n"
    )
