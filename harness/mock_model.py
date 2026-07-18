from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from harness.context.tool_output import tool_output_to_text
from harness.types import Message, ModelStep, ModelUsage, StreamPart

_retry_test_count = 0
_last_prefix_hash: int | None = None
_cache_enabled = True

TEXT_RESPONSES = {
    "default": "你好！我是 Agent Harness v1.0，现在支持 Plugin 动态加载了。试试 /plugin 看看已加载的插件，或者让我帮你查数据库。",
    "greeting": "你好！我是 Agent Harness v1.0，支持 Plugin 扩展。试试让我查数据库或者 /plugin 管理插件 :) ",
    "memorySaved": "好的，我已经把这条信息存到记忆里了。下次你重新打开对话，我还会记得这件事。",
    "lintFinished": "记忆库 lint 跑完了，详细情况看上面的报告。建议清理掉那些路径已经不存在的条目，或者把同名的合并一下。",
    "dreamFinished": "记忆整理完成！这次做了以下操作：\n\n- 删除了 old-build-config（webpack.config.js 已不存在，854 天没读过）\n- 删除了 deploy-process-2（与 deploy-process 重名的早期版本）\n- 保留了 legacy-auth-module（路径过期但内容可能还有参考价值，建议手动更新）\n- 保留了 deploy-process（路径需要更新但部署流程本身还有用）\n- typescript-preference 健康，无需处理\n\n记忆库从 5 条精简到 3 条。",
}


def set_cache_enabled(enabled: bool) -> None:
    global _cache_enabled, _last_prefix_hash
    _cache_enabled = enabled
    if not enabled:
        _last_prefix_hash = None


def _extract_user_text(messages: list[Message]) -> str:
    users = [message for message in messages if message.get("role") == "user"]
    if not users:
        return ""
    content = users[-1].get("content", "")
    if isinstance(content, str):
        return content.lower()
    return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict)).lower()


def _has_tool_results(messages: list[Message]) -> bool:
    for message in reversed(messages):
        if message.get("role") == "tool":
            return True
        if message.get("role") == "user":
            return False
    return False


def _tool_results(messages: list[Message]) -> str:
    results: list[str] = []
    for message in reversed(messages):
        if message.get("role") == "user":
            break
        if message.get("role") != "tool" or not isinstance(message.get("content"), list):
            continue
        for part in message["content"]:
            if isinstance(part, dict):
                results.append(tool_output_to_text(part.get("output", part.get("result", ""))))
    return "\n".join(results)


def _tool_search_called(messages: list[Message]) -> bool:
    for message in reversed(messages):
        if message.get("role") == "user":
            return False
        if message.get("role") == "assistant" and isinstance(message.get("content"), list):
            if any(
                isinstance(part, dict) and part.get("type") == "tool-call" and part.get("toolName") == "tool_search"
                for part in message["content"]
            ):
                return True
    return False


def _tool_called_since_user(messages: list[Message], tool_name: str) -> bool:
    for message in reversed(messages):
        if message.get("role") == "user":
            return False
        if message.get("role") != "assistant" or not isinstance(message.get("content"), list):
            continue
        if any(
            isinstance(part, dict) and part.get("type") == "tool-call" and part.get("toolName") == tool_name
            for part in message["content"]
        ):
            return True
    return False


def _parallel_intents(text: str) -> list[tuple[str, dict[str, Any]]] | None:
    if "测试并发" in text or "test parallel" in text:
        return [("get_weather", {"city": "北京"}), ("get_weather", {"city": "上海"}), ("list_directory", {"path": "."})]
    return None


def _detect_intent(messages: list[Message]) -> tuple[str, dict[str, Any]] | None:
    text = _extract_user_text(messages)
    results = _tool_results(messages)
    has_results = _has_tool_results(messages)
    if "测试死循环" in text:
        return "get_weather", {"city": "北京"}
    if ("阶段 1" in text and "阶段 2" in text and "记忆整理" in text) or "dream" in text:
        if not has_results:
            return "memory", {"action": "list"}
        if "记忆列表" in results and "lint 报告" not in results:
            return "memory", {"action": "lint"}
        deleted_old = "project_old-build-config" in results
        deleted_duplicate = "project_deploy-process-2" in results
        if "lint 报告" in results and not deleted_old:
            return "memory", {"action": "delete", "filename": "project_old-build-config.md"}
        if deleted_old and not deleted_duplicate:
            return "memory", {"action": "delete", "filename": "project_deploy-process-2.md"}
        return None
    if any(value in text for value in ("lint 记忆", "检查记忆", "记忆体检")) or text == "lint":
        return None if has_results else ("memory", {"action": "lint"})
    if ("记住" in text or "remember" in text) and not has_results:
        content = re.sub(r"记住|remember", "", text).strip()
        memory_type = (
            "feedback"
            if any(value in content for value in ("不要", "别", "don't"))
            else "user"
            if any(value in content for value in ("喜欢", "偏好", "prefer"))
            else "project"
        )
        return "memory", {
            "action": "save",
            "name": content[:30],
            "description": content[:60],
            "type": memory_type,
            "content": content,
        }
    if any(value in text for value in ("我的记忆", "记忆列表")) or text == "memory list":
        return None if has_results else ("memory", {"action": "list"})
    if any(value in text for value in ("搜记忆", "搜索记忆", "找记忆", "memory search")) and not has_results:
        query = re.sub(r"搜记忆|搜索记忆|找记忆|memory search", "", text)
        query = re.sub(r"^[关于的有]+", "", query).strip() or "all"
        return "memory", {"action": "search", "query": query}
    if ("导入" in text or "ingest" in text) and ("文档" in text or ".md" in text) and not has_results:
        match = re.search(r"([\w/.-]+\.md)", text)
        return "rag_ingest", {"path": match.group(1) if match else "docs/deployment-guide.md"}
    direct = [
        (("有哪些表", "表列表", "list table"), "supabase__list_tables", {}),
        (("查用户", "用户数据", "query user"), "supabase__query", {"table": "users"}),
        (("查帖子", "文章列表", "query post"), "supabase__query", {"table": "posts"}),
    ]
    if not has_results:
        for keywords, name, arguments in direct:
            if any(value in text for value in keywords):
                return name, arguments
        if any(value in text for value in ("插入", "新增", "insert")):
            return "supabase__insert", {
                "table": "users",
                "data": {"name": "赵六", "email": "zhao@example.com", "role": "user"},
            }
        if any(value in text for value in ("数据库", "database", "supabase", "sql")):
            return "supabase__list_tables", {}
        if any(
            value in text
            for value in ("部署", "deploy", "事故", "回滚", "监控", "迁移", "知识库", "搜索知识", "查资料")
        ):
            return "rag_search", {"query": text}
    if has_results and _tool_search_called(messages):
        if ("list_issues" in results or "mcp__github" in results) and not _tool_called_since_user(
            messages, "mcp__github__list_issues"
        ):
            match = re.search(r"(\w+)/(\w[\w-]*)", text)
            return "mcp__github__list_issues", {
                "owner": match.group(1) if match else "vercel",
                "repo": match.group(2) if match else "ai",
            }
        if ("search_pages" in results or "mcp__notion" in results) and not _tool_called_since_user(
            messages, "mcp__notion__search_pages"
        ):
            return "mcp__notion__search_pages", {"query": "project roadmap"}
        if ("navigate" in results or "mcp__browser" in results) and not _tool_called_since_user(
            messages, "mcp__browser__navigate"
        ):
            return "mcp__browser__navigate", {"url": "https://example.com"}
        return None
    if has_results:
        return None
    delayed = [
        (("issue", "issues", "github"), "mcp__github__list_issues"),
        (("notion", "笔记"), "mcp__notion__search_pages"),
        (("浏览器", "browser", "网页"), "mcp__browser__navigate"),
    ]
    for keywords, name in delayed:
        if any(value in text for value in keywords):
            return "tool_search", {"query": name}
    cases = [
        (("测试截断", "test truncation"), "read_file", {"path": "sample-data.txt"}),
        (
            ("测试编辑", "test edit"),
            "edit_file",
            {"path": "sample-data.txt", "old_string": "一、工具注册机制", "new_string": "一、工具注册机制（已更新）"},
        ),
        (("测试搜索", "test grep"), "grep", {"pattern": "def", "path": "harness"}),
        (("测试glob", "test glob"), "glob", {"pattern": "**/*.py"}),
        (("测试bash", "test bash"), "bash", {"command": 'echo "Hello from bash!" && date'}),
        (("测试危险", "dangerous", "删除所有"), "bash", {"command": "rm -rf /tmp/test-data"}),
        (("测试写文件", "test write"), "write_file", {"path": "test-output.txt", "content": "Hello from hook test"}),
    ]
    for keywords, name, arguments in cases:
        if any(value in text for value in keywords):
            return name, arguments
    if any(value in text for value in ("目录", "文件列表", "ls")):
        return "list_directory", {"path": "."}
    file_match = re.search(r"(\S+\.[\w]+)", text)
    if file_match and any(value in text for value in ("读", "read", "看看", "查看", "打开", "文件", "file")):
        return "read_file", {"path": file_match.group(1)}
    cities = re.findall(r"北京|上海|深圳|广州|杭州|成都", text)
    if cities and any(value in text for value in ("天气", "weather", "温度", "热", "冷", "气温")):
        return "get_weather", {"city": cities[0]}
    calculation = re.search(r"(\d+)\s*([+\-*/加减乘除])\s*(\d+)", text)
    if calculation:
        operator = {"加": "+", "减": "-", "乘": "*", "除": "/"}.get(calculation.group(2), calculation.group(2))
        return "calculator", {"expression": f"{calculation.group(1)} {operator} {calculation.group(3)}"}
    return None


def _pick_response(messages: list[Message]) -> str:
    text = _extract_user_text(messages)
    if _has_tool_results(messages):
        combined = _tool_results(messages)
        if "已保存到记忆" in combined or "saved to memory" in combined:
            return TEXT_RESPONSES["memorySaved"]
        if ("dream" in text or "记忆整理" in text) and "project_deploy-process-2" in combined:
            return TEXT_RESPONSES["dreamFinished"]
        if "lint 报告" in combined or "记忆库健康" in combined:
            return f"{TEXT_RESPONSES['lintFinished']}\n\n{combined}"
        if "BM25 搜索结果" in combined:
            return f"给你按相关度排好的搜索结果：\n{combined}"
        if "记忆列表" in combined or "条记忆" in combined:
            return f"这是你目前的记忆：\n{combined}"
        if "tables" in combined and "users" in combined:
            return f"数据库里有这些表：\n{combined}"
        if '"table"' in combined and '"rows"' in combined:
            return f"查询结果如下：\n{combined}"
        if "已导入" in combined and "文档片段" in combined:
            return f"文档已导入知识库。{combined}"
        if "综合分" in combined or "来源:" in combined:
            return f"根据知识库的检索结果：\n\n{combined}"
        if "搜索结果" in combined or "没有找到" in combined or "知识库为空" in combined:
            return combined
        if "[DIR]" in combined or "[FILE]" in combined:
            return f"当前目录的文件列表：\n{combined}"
        if "°C" in combined or "天气" in combined:
            return f"根据查询结果：{combined}"
        return f"工具返回了以下信息：\n{combined}"
    if any(value in text for value in ("你好", "hello", "hi")):
        return TEXT_RESPONSES["greeting"]
    return TEXT_RESPONSES["default"]


def _usage(system: str, messages: list[Message], output_chars: int = 80) -> ModelUsage:
    global _last_prefix_hash
    prefix_tokens = math.ceil(len(system) / 3.5)
    message_tokens = math.ceil(sum(len(json.dumps(message, ensure_ascii=False)) for message in messages) / 3.5)
    output_tokens = math.ceil(output_chars / 3.5)
    if _cache_enabled and prefix_tokens >= 512:
        prefix_hash = hash(system)
        cache_read = prefix_tokens if _last_prefix_hash == prefix_hash else 0
        cache_write = 0 if cache_read else prefix_tokens
        _last_prefix_hash = prefix_hash
        return ModelUsage(message_tokens, output_tokens, cache_read, cache_write)
    _last_prefix_hash = None
    return ModelUsage(message_tokens + prefix_tokens, output_tokens)


class MockModel:
    model_id = "mock-model"

    async def run_step(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: dict[str, Any],
        tool_choice: str = "auto",
        on_text_delta: Callable[[str], None] | None = None,
        max_output_tokens: int | None = None,
    ) -> ModelStep:
        global _retry_test_count
        text = _extract_user_text(messages)
        if "测试重试" in text or "test retry" in text:
            _retry_test_count += 1
            if _retry_test_count <= 2:
                raise RuntimeError("429 Too Many Requests - Rate limit exceeded")
            _retry_test_count = 0
            return self._text_step(system, messages, "重试成功！", on_text_delta)
        if "测试预算" in text or "test budget" in text:
            return self._text_step(
                system,
                messages,
                "本轮模拟消耗 4500 tokens。",
                on_text_delta,
                ModelUsage(input_tokens=3000, output_tokens=1500),
            )
        intents = None if tool_choice == "none" else _parallel_intents(text)
        if intents and _has_tool_results(messages):
            intents = None
        if intents is None and tool_choice != "none":
            intent = _detect_intent(messages)
            intents = [intent] if intent else []
        if intents:
            return await self._tool_step(system, messages, tools, intents)
        return self._text_step(system, messages, _pick_response(messages), on_text_delta)

    @staticmethod
    def _text_step(
        system: str,
        messages: list[Message],
        text: str,
        on_text_delta: Callable[[str], None] | None = None,
        usage: ModelUsage | None = None,
    ) -> ModelStep:
        if on_text_delta:
            on_text_delta(text)
        message = {"role": "assistant", "content": [{"type": "text", "text": text}]}
        return ModelStep([message], usage or _usage(system, messages, len(text)), [StreamPart("text-delta", text=text)])

    @staticmethod
    async def _tool_step(
        system: str, messages: list[Message], tools: dict[str, Any], intents: list[tuple[str, dict[str, Any]]]
    ) -> ModelStep:
        calls = [
            (f"call-{int(time.time() * 1000)}-{uuid.uuid4().hex[:4]}", name, arguments) for name, arguments in intents
        ]
        assistant_content = [
            {"type": "tool-call", "toolCallId": call_id, "toolName": name, "input": arguments}
            for call_id, name, arguments in calls
        ]
        parts = [
            StreamPart("tool-call", tool_name=name, tool_call_id=call_id, input=arguments)
            for call_id, name, arguments in calls
        ]

        async def execute(call: tuple[str, str, dict[str, Any]]) -> tuple[str, str, dict[str, Any], Any]:
            call_id, name, arguments = call
            tool = tools.get(name)
            output = await tool["execute"](arguments) if tool else f"工具不存在: {name}"
            return call_id, name, arguments, output

        results = await asyncio.gather(*(execute(call) for call in calls))
        tool_content = []
        for call_id, name, arguments, output in results:
            tool_content.append({"type": "tool-result", "toolCallId": call_id, "toolName": name, "output": output})
            parts.append(
                StreamPart("tool-result", tool_name=name, tool_call_id=call_id, input=arguments, output=output)
            )
        response_messages = [
            {"role": "assistant", "content": assistant_content},
            {"role": "tool", "content": tool_content},
        ]
        return ModelStep(response_messages, _usage(system, messages), parts)

    async def generate(self, *, system: str, prompt: str) -> str:
        if "对话压缩系统" in system or "压缩成一份结构化摘要" in system:
            return "## 用户意图\n继续当前对话任务。\n\n## 已完成的操作\n已执行前序工具调用。\n\n## 关键发现\n详见对话内容。\n\n## 当前状态\n等待继续处理。\n\n## 需要保留的细节\n保留文件路径和配置值。"
        return TEXT_RESPONSES["default"]


def create_mock_model() -> MockModel:
    return MockModel()
