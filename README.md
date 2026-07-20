# 项目结构说明

> 本文档基于当前 `harness/` 目录的实际结构生成，用于快速了解 Agent Harness 各模块的职责划分。
>
> 当前版本：v1.0.0，已集成 Agent Loop、工具系统、上下文管理、Memory/RAG、Sub-Agent、Team、Worktree、Cron、Channel、权限与 Hook 管线等能力。

---

## 目录概览

```text
.
├── .env.example                 # 环境变量模板，不含真实密钥
├── .env                         # 本地密钥与服务配置（不提交 Git）
├── .skills/                     # 本地 Skill 目录
│   └── code-review-expert/      # 代码审查 Skill 及检查表
├── .memory/                     # Markdown 长期记忆（运行后生成）
├── .sessions/                   # JSONL 会话记录（运行后生成）
├── .usage/                      # Token 与成本日志（运行后生成）
├── .cron/                       # Cron 任务和执行日志（运行后生成）
├── .tasks/                      # 持久化任务图（运行后生成）
├── .team/                       # Team 文件收件箱（运行后生成）
├── .worktrees/                  # 队友隔离工作区（运行后生成）
├── .transcripts/                # 上下文压缩前的记录（运行后生成）
├── .task_outputs/               # 较大的工具输出（运行后生成）
├── docs/                        # RAG 默认导入的 Markdown 资料
│   ├── api-design.md
│   └── deployment-guide.md
├── sample-project/              # 用于代码分析演示的示例项目
│   ├── api.py
│   ├── auth.py
│   └── utils.py
├── harness/                     # 主源码目录
│   ├── __main__.py             # CLI 入口
│   ├── main.py                 # 运行时组装与交互循环
│   ├── model.py                # OpenAI 兼容模型适配器
│   ├── mock_model.py           # 无 API Key 的 Mock 模型
│   ├── agent/                  # Agent Loop、重试与循环检测
│   ├── agents/                 # Sub-Agent 调度与运行记录
│   ├── background/             # 后台工具任务
│   ├── channels/               # Channel Gateway 与飞书接入
│   ├── commands/               # 终端快捷命令
│   ├── config/                 # 配置 Schema、加载和初始化
│   ├── context/                # Prompt Pipeline 与上下文防线
│   ├── cron/                   # 定时任务调度
│   ├── memory/                 # 长期记忆与整理
│   ├── plugins/                # Plugin 生命周期
│   ├── rag/                    # 文档分块、Embedding 与检索
│   ├── security/               # 角色、Hooks 与 Bash 风险检测
│   ├── session/                # 会话持久化
│   ├── skills/                 # Skill 发现与加载
│   ├── tasks/                  # 任务图与依赖解锁
│   ├── teams/                  # 持久队友与通信协议
│   ├── tools/                  # Tool Registry、内置工具与 MCP
│   ├── usage/                  # Token、Cache 与成本追踪
│   └── worktrees/              # Git Worktree 隔离
├── tests/                       # pytest 模块测试与跨模块测试
├── agent-harness.config.json    # 主配置文件
├── knowledge.db                 # 可选 SQLite 知识库（不提交 Git）
├── pyproject.toml               # 依赖、CLI 和开发工具配置
└── uv.lock                      # 依赖锁定文件
```

---

## `harness/` 目录详解

### 入口与模型

| 文件 | 职责 |
| --- | --- |
| `harness/__main__.py` | CLI 入口。处理 `init` 初始化和 `--continue` 会话恢复，其余情况启动 Agent。 |
| `harness/main.py` | Agent 组合根。加载配置、初始化模型、注册工具、导入 RAG 文档、启动 Channel/Cron，然后进入交互循环。 |
| `harness/model.py` | OpenAI 兼容模型适配器。转换内部消息与工具定义，处理流式输出、用量和备用模型切换。 |
| `harness/mock_model.py` | Mock 模型。在未配置 `OPENAI_API_KEY` 时模拟文本、工具调用、Cache 和预算流程。 |
| `harness/types.py` | 内部协议。定义 Message、Model、ModelStep、StreamPart 和 ModelUsage 等类型。 |
| `harness/workspace.py` | 当前工作目录与路径解析。队友进入 Worktree 时会切换该上下文。 |

### `harness/agent/` - Agent Loop

| 文件 | 职责 |
| --- | --- |
| `harness/agent/loop.py` | Agent 主循环。处理流式文本、工具调用与结果、15 步上限、跨轮 Token 预算、输出续写、Reactive Compact、完成通知和记忆提取。 |
| `harness/agent/detection.py` | 循环检测。记录近期工具调用与结果，识别重复调用、乒乓循环和无进展状态。 |
| `harness/agent/retry.py` | 错误恢复。识别 429、5xx、网络、超时和上下文超限错误，处理 Retry-After 与退避延迟。 |

### `harness/agents/` - Sub-Agent

| 文件 | 职责 |
| --- | --- |
| `harness/agents/types.py` | 定义 SubAgentConfig、SpawnRequest 和 SubAgentRun 等子 Agent 类型。 |
| `harness/agents/registry.py` | 管理 Sub-Agent 运行记录、ID、嵌套深度、并发上限和状态流转。 |
| `harness/agents/spawn.py` | 执行单个或并行子任务。每个 Sub-Agent 使用独立消息历史，具有超时、步数限制和最终文本收敛。 |

### `harness/background/` - 后台任务

| 文件 | 职责 |
| --- | --- |
| `harness/background/manager.py` | 跟踪后台工具任务的 ID、状态和输出，完成后生成 `<task_notification>` 供主循环注入。 |

### `harness/channels/` - 多渠道接入

| 文件 | 职责 |
| --- | --- |
| `harness/channels/types.py` | 定义 IncomingMessage、OutgoingMessage 和 ChannelDefinition 协议。 |
| `harness/channels/gateway.py` | 统一管理 Channel 的注册、启停和消息分发，使用全局锁避免多渠道同时驱动 Agent。 |
| `harness/channels/feishu.py` | 飞书长连接与 FastAPI Dashboard 接入，需要可选 `feishu` 依赖和应用凭据。 |

### `harness/config/` - 配置系统

| 文件 | 职责 |
| --- | --- |
| `harness/config/schema.py` | 使用 Pydantic 定义模型、Plugin、Channel、Agent、Security、Memory、RAG、MCP、Cron、Session 和 Usage 配置。 |
| `harness/config/loader.py` | 读取 `agent-harness.config.json`，替换 `${ENV_VAR}` 占位符并执行 Pydantic 校验。 |
| `harness/config/init.py` | 交互式初始化向导。生成主配置和 `.env`，并在覆盖已有配置前进行确认。 |

### `harness/commands/` - 终端快捷命令

| 文件 | 职责 |
| --- | --- |
| `harness/commands/__init__.py` | 命令上下文和调度器。按顺序将输入交给各个 CommandHandler。 |
| `harness/commands/agent.py` | `/agents` 命令，查看 Sub-Agent 记录、活跃数、并发和深度配置。 |
| `harness/commands/channel.py` | `/channel` 和 `/channel list` 渠道列表命令。 |
| `harness/commands/context.py` | `/context` 上下文视图与 `/usage` 用量视图。 |
| `harness/commands/cron.py` | `/cron` 定时任务列表与 `/cron logs` 执行日志。 |
| `harness/commands/debug.py` | `sim`、`defend`、`status` 和 `/cache on|off` 调试命令。 |
| `harness/commands/dream.py` | `/dream` 记忆整理流程。 |
| `harness/commands/memory.py` | `/memory`、`/lint` 和 `/memory search <query>` 等记忆命令。 |
| `harness/commands/plugin.py` | `/plugin` 列表与 Plugin 加载/卸载命令。 |
| `harness/commands/rag.py` | `/rag` 知识库状态和 `ingest <path>` 文档导入。 |
| `harness/commands/security.py` | `/role [owner|collaborator|guest]` 和 `/hooks` 安全状态命令。 |
| `harness/commands/skill.py` | Skill 列表、加载、卸载与 `/<skill-name>` 直接执行。 |

### `harness/context/` - Prompt 与上下文管理

| 文件 | 职责 |
| --- | --- |
| `harness/context/prompt_builder.py` | Prompt Builder 与 Pipe 机制。按顺序组装核心规则、工具说明、延迟工具和会话信息。 |
| `harness/context/prompt_pipes.py` | Memory 和 RAG 等动态 Prompt Pipe。 |
| `harness/context/defense.py` | 上下文防线。执行工具结果截断、预算清理与 TTL 软/硬修剪。 |
| `harness/context/compressor.py` | Microcompact、Snip、Reactive Compact、LLM 摘要和完整 Transcript 落盘。 |
| `harness/context/compact_tool.py` | 向模型提供主动 `compact` 工具。 |
| `harness/context/tool_output.py` | 统一读写不同形式的工具结果文本。 |
| `harness/context/view.py` | 构建和渲染 Context/Usage 快照。 |

### `harness/cron/` - 定时任务

| 文件 | 职责 |
| --- | --- |
| `harness/cron/types.py` | 定义 CronJobConfig 和 RunLog。 |
| `harness/cron/parser.py` | 解析原始 cron 表达式、`every 10m` 类间隔和 ISO 时间，计算下次执行时间。 |
| `harness/cron/store.py` | 持久化任务配置与 JSONL 执行日志。 |
| `harness/cron/service.py` | 加载、调度和执行定时 Agent 任务，跟踪失败并自动停用问题任务。 |

### `harness/memory/` - 长期记忆

| 文件 | 职责 |
| --- | --- |
| `harness/memory/types.py` | 定义 MemoryEntry 数据结构。 |
| `harness/memory/store.py` | 基于 Markdown/frontmatter 的记忆读写、索引生成和分阶段原子替换。 |
| `harness/memory/search.py` | 对记忆条目执行 BM25 检索。 |
| `harness/memory/validator.py` | 检查过期路径、重复和其他记忆健康问题。 |
| `harness/memory/automation.py` | 在轮次开始时选择相关记忆，在轮次结束时提取并合并记忆。 |

### `harness/plugins/` - Plugin 架构

| 文件 | 职责 |
| --- | --- |
| `harness/plugins/types.py` | 定义 PluginDefinition 和 PluginApi。 |
| `harness/plugins/manager.py` | 管理 Plugin 配置、加载、卸载、工具注册与回收。 |
| `harness/plugins/supabase_plugin.py` | Supabase 示例 Plugin。提供 `list_tables`、`query` 和 `insert` 演示工具。 |

### `harness/rag/` - 检索增强生成

| 文件 | 职责 |
| --- | --- |
| `harness/rag/chunker.py` | 将 Markdown 文档按标题与长度分块，生成稳定 Chunk ID。 |
| `harness/rag/embedder.py` | 提供 DashScope 与 Mock Embedding，包含批量嵌入和余弦相似度。 |
| `harness/rag/store.py` | 定义 VectorStoreProtocol 和默认内存 VectorStore。 |
| `harness/rag/search.py` | 将向量相似度与 BM25 按 70%/30% 合并，再用 MMR 减少重复结果。 |
| `harness/rag/sqlite_store.py` | 可选 sqlite-vec + FTS5 持久化 Store，实现向量/关键词混合检索。 |

### `harness/security/` - 权限、Hook 与风险检测

| 文件 | 职责 |
| --- | --- |
| `harness/security/roles.py` | `owner`、`collaborator`、`guest` 三级角色与工具可见性过滤。 |
| `harness/security/bash_classifier.py` | 按规则将 Bash 命令分为 safe、moderate 和 dangerous。 |
| `harness/security/hooks.py` | UserPromptSubmit、PreToolUse、PostToolUse 和 Stop 四阶段 Hook 管线。 |

### `harness/session/` - 会话持久化

| 文件 | 职责 |
| --- | --- |
| `harness/session/store.py` | 以 JSONL 保存、追加、替换和恢复会话消息，为 `--continue` 提供数据。 |

### `harness/skills/` - 领域 Skill

| 文件 | 职责 |
| --- | --- |
| `harness/skills/loader.py` | 扫描 `.skills/*/SKILL.md`，解析 frontmatter，生成 Skill 摘要和已激活 Skill 的 Prompt 段落。 |

### `harness/tasks/` - 持久化任务图

| 文件 | 职责 |
| --- | --- |
| `harness/tasks/types.py` | 定义 Task 的 ID、主题、状态、依赖、所有者和 Worktree 等字段。 |
| `harness/tasks/store.py` | 持久化任务，处理创建、依赖校验、认领、完成、解锁、释放与 Worktree 绑定。 |
| `harness/tasks/tools.py` | 将任务图操作暴露为 Agent 工具。 |

### `harness/teams/` - 持久队友与协作协议

| 文件 | 职责 |
| --- | --- |
| `harness/teams/types.py` | 定义 TeammateState 和关机/计划审批协议状态。 |
| `harness/teams/bus.py` | 基于 `.team/` JSONL 收件箱的点对点消息总线。 |
| `harness/teams/manager.py` | 启动持久队友，处理自治认领、计划审批、关机协议、Worktree 目录绑定与结果回传。 |
| `harness/teams/tools.py` | 提供创建队友、发送消息、请求计划/关机和审批计划等 Agent 工具。 |

### `harness/tools/` - 工具系统

| 文件 | 职责 |
| --- | --- |
| `harness/tools/registry.py` | Tool Registry。管理内置/MCP/Plugin 工具，负责 Profile、延迟发现、角色过滤、审批、读写锁、Hooks、后台执行和大结果落盘。 |
| `harness/tools/index.py` | 汇总并导出所有默认内置工具。 |
| `harness/tools/file_tools.py` | `read_file`、`write_file`、`edit_file` 和 `list_directory`。 |
| `harness/tools/search_tools.py` | `glob` 文件匹配和 `grep` 文本搜索。 |
| `harness/tools/shell_tools.py` | `bash` Shell 执行，支持超时与后台任务参数。 |
| `harness/tools/web_search.py` | Tavily/Serper `web_search` 与网页 `web_fetch`。 |
| `harness/tools/utility_tools.py` | `get_weather` 和 `calculator` 通用示例工具。 |
| `harness/tools/tool_search.py` | 根据工具名称发现 Deferred Tool，并将其完整定义暴露给模型。 |
| `harness/tools/mcp.py` | Mock MCP Client 和可选的真实 stdio MCP Client。 |
| `harness/tools/mcp_tools.py` | `connect_mcp` 工具，按配置连接 Server 并动态注册工具。 |
| `harness/tools/memory_tools.py` | Memory 列表、读取、搜索、保存、删除与 lint 工具。 |
| `harness/tools/rag_tools.py` | RAG 文档导入和混合检索工具。 |
| `harness/tools/cron_tools.py` | Cron 列表、创建和删除工具。 |
| `harness/tools/spawn_tools.py` | `spawn_agent` 工具，支持单任务和并行子任务。 |
| `harness/tools/todo_tools.py` | 内存 Todo 列表与 `todo_write` 工具，保证最多一个进行中任务。 |

### `harness/usage/` - Token 与成本追踪

| 文件 | 职责 |
| --- | --- |
| `harness/usage/tracker.py` | 归一化不同模型的 Usage，估算输入/输出/Cache 成本，追加 JSONL 记录并生成每日汇总。 |

### `harness/worktrees/` - Git Worktree 隔离

| 文件 | 职责 |
| --- | --- |
| `harness/worktrees/manager.py` | 校验名称，创建和删除 `wt/<name>` Worktree/分支，记录基准提交，并防止未确认地删除未提交或未合并改动。 |
| `harness/worktrees/tools.py` | 将 Worktree 创建、移除和保留操作暴露给 Agent。 |

---

## 模块依赖关系

```text
┌──────────────────┐
│ harness/__main__.py │
└────────┬─────────┘
         ▼
┌──────────────────┐
│   harness/main.py  │
└─┬─────┬──────┬───────┘
  ▼       ▼       ▼
config/   context/   commands/
  │       │       │
  └───┬───┴───┬───┘
      ▼       ▼
   agent/ ◄──► tools/
      │       │
      │       ├── security/
      │       ├── background/
      │       ├── plugins/
      │       └── MCP
      │
      ├── memory/ ── rag/ ── skills/
      ├── session/ ── usage/
      ├── cron/ ── channels/
      └── agents/ ── teams/ ── tasks/ ── worktrees/
```

---

## 食用阶段

仓库按知识点保留了五个递进 tag：

| Tag | 内容 |
| --- | --- |
| `stage-01-runtime` | 模型协议、Agent Loop、Tool Registry、上下文压缩、Memory 和 Session |
| `stage-02-knowledge` | Prompt Pipeline、RAG、Skills 和知识检索 |
| `stage-03-orchestration` | Todo/Task、后台任务、Cron 和 Plugin |
| `stage-04-multi-agent` | Sub-Agent、Team 协议、Worktree 和 Channel |
| `stage-05-complete` | 配置、CLI、MCP、组合根和完整测试 |

```bash
git checkout stage-01-runtime
```

---

## 常用脚本

```bash
# 克隆项目
git clone https://github.com/Evan-Lorne/agent-harness.git
cd agent-harness

# 安装基础依赖
uv sync --no-editable

# 生成本地环境变量文件
cp .env.example .env

# 交互式初始化配置
uv run --no-sync agent-harness init

# 直接启动
uv run --no-sync agent-harness

# 恢复上次会话
uv run --no-sync agent-harness --continue
```

未配置 `OPENAI_API_KEY` 时会使用 MockModel。飞书、MCP 和 sqlite-vec 需要按需安装对应 extra：

```bash
uv sync --no-editable --extra feishu
uv sync --no-editable --extra mcp
uv sync --no-editable --extra sqlite-vec
```

质量检查：

```bash
uv run --no-sync ruff format --check harness tests
uv run --no-sync ruff check harness tests
uv run --no-sync pyright
uv run --no-sync pytest
```

---

## 环境变量

环境变量模板位于 [`.env.example`](.env.example)，不要将真实 `.env` 提交到 Git。

| 变量 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI 兼容模型 API Key；留空时使用 MockModel。 |
| `OPENAI_BASE_URL` | OpenAI 兼容服务的 Base URL。 |
| `FALLBACK_MODEL_ID` | 可选备用模型 ID，用于连续过载时切换。 |
| `ALIYUN_API_KEY` | DashScope Embedding API Key。 |
| `TAVILY_API_KEY` / `SERPER_API_KEY` | 网络搜索工具凭据。 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书 Channel 凭据。 |
| `SUPABASE_URL` / `SUPABASE_KEY` | Supabase 示例 Plugin 配置。 |
| `GITHUB_TOKEN` | 在 MCP Server 配置中引用的 GitHub Token。 |

---

## 快捷命令

运行 `uv run --no-sync agent-harness` 后，终端中可以使用以下命令：

| 命令 | 说明 |
| --- | --- |
| `/role [owner\|collaborator\|guest]` | 查看或切换当前工具角色。 |
| `/hooks` | 查看 User/Pre/Post/Stop Hook 管线。 |
| `/memory` / `/memory search <query>` / `/lint` | 查看、检索和检查长期记忆。 |
| `/rag` / `ingest <path>` | 查看知识库或导入文档。 |
| `/dream` | 触发记忆整理流程。 |
| `/skill list` / `/skill load <name>` | 查看和激活 Skill。 |
| `/plugin` / `/plugin load <name>` | 查看和加载 Plugin。 |
| `/channel` / `/channel list` | 查看已注册的消息渠道。 |
| `/cron` / `/cron logs` | 查看定时任务和执行日志。 |
| `/agents` | 查看 Sub-Agent 运行记录、深度和并发配置。 |
| `/context` / `/usage` | 查看上下文构成、Token、Cache 和成本。 |
| `sim` / `defend` / `status` | 注入测试上下文、手动执行防线和查看运行状态。 |
| `/cache on` / `/cache off` | 开启或关闭 MockModel 的 Cache 模拟。 |

---

> 注：本结构文档根据当前代码目录生成。新增、删除或重命名模块时，应同步更新文档。
