from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from pathlib import Path

from harness.context.tool_output import replace_tool_output_text
from harness.types import Message, Model

CLEARABLE_TOOLS = {"read_file", "bash", "grep", "glob", "list_directory", "edit_file", "write_file"}
KEEP_RECENT_TOOL_RESULTS = 3
CONTEXT_TOKEN_THRESHOLD = 300
KEEP_RECENT_MESSAGES = 6
MAX_MESSAGES = 50
COMPRESS_PROMPT = """你是一个对话压缩系统。你的任务是把 Agent 和用户之间的对话历史压缩成一份结构化摘要，确保后续对话能够无缝继续。

请严格按照以下模板输出，每个字段都要填写。如果某个字段没有相关内容，写"无"：

## 用户意图
（用户在这次对话中想要完成什么）

## 已完成的操作
（Agent 执行了哪些工具调用、产生了什么结果）

## 关键发现
（读取的文件内容要点、搜索结果、命令输出中的关键信息）

## 当前状态
（对话进行到哪一步了、还有什么没做完）

## 需要保留的细节
（文件路径、变量名、配置值、错误信息等不能丢失的具体内容）

注意事项：
- 用对话中使用的语言（中文或英文）输出
- 文件路径、UUID、版本号等标识符必须原样保留，不要翻译或改写
- 不要写笼统的概述，只保留具体的、可操作的信息
- 总长度控制在 800 字以内"""


def estimate_tokens(messages: list[Message]) -> int:
    characters = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            characters += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    characters += len(part["text"])
                elif isinstance(part, dict) and "output" in part:
                    characters += len(json.dumps(part["output"], ensure_ascii=False))
    return (characters + 3) // 4


def microcompact(messages: list[Message]) -> tuple[list[Message], int]:
    tool_indices = [
        index
        for index, message in enumerate(messages)
        if message.get("role") == "tool" and isinstance(message.get("content"), list)
    ]
    to_clear = set(tool_indices[: max(0, len(tool_indices) - KEEP_RECENT_TOOL_RESULTS)])
    result = copy.deepcopy(messages)
    cleared = 0
    for index in to_clear:
        content = result[index]["content"]
        tool_name = content[0].get("toolName", "unknown") if content else "unknown"
        if tool_name not in CLEARABLE_TOOLS:
            continue
        cleared += 1
        for part in content:
            part["output"] = replace_tool_output_text(part.get("output"), "[tool result cleared]")
    return result, cleared


def snip_compact(messages: list[Message], max_messages: int = MAX_MESSAGES) -> list[Message]:
    if len(messages) <= max_messages:
        return messages
    head_end = 3
    original_tail_start = len(messages) - (max_messages - head_end)
    tail_start = original_tail_start
    while tail_start > 0 and messages[tail_start].get("role") == "tool":
        tail_start -= 1
    if tail_start <= head_end:
        tail_start = original_tail_start
        while tail_start < len(messages) and messages[tail_start].get("role") == "tool":
            tail_start += 1
    removed = tail_start - head_end
    return [
        *messages[:head_end],
        {"role": "user", "content": f"[snipped {removed} messages from conversation middle]"},
        *messages[tail_start:],
    ]


def reactive_compact(messages: list[Message]) -> list[Message]:
    original_tail_start = max(0, len(messages) - 5)
    tail_start = original_tail_start
    while tail_start > 0 and messages[tail_start].get("role") == "tool":
        tail_start -= 1
    if original_tail_start > 0 and tail_start < max(1, original_tail_start - 5):
        tail_start = original_tail_start
        while tail_start < len(messages) and messages[tail_start].get("role") == "tool":
            tail_start += 1
    return [
        {"role": "user", "content": "[Reactive compact: older context removed after provider rejected prompt size.]"},
        *messages[tail_start:],
    ]


def write_transcript(messages: list[Message]) -> None:
    directory = Path(".transcripts")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"compact-{int(time.time() * 1000)}.jsonl"
        path.write_text(
            "\n".join(json.dumps(message, ensure_ascii=False) for message in messages) + "\n", encoding="utf-8"
        )
    except OSError as error:
        print(f"[Compaction] transcript 保存失败: {error}")


@dataclass(slots=True)
class CompactionResult:
    messages: list[Message]
    summary: str
    compressed_count: int


def _message_text(message: Message) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or json.dumps(part.get("output", ""), ensure_ascii=False))
            for part in content
            if isinstance(part, dict)
        )
    return ""


async def summarize(
    model: Model, messages: list[Message], existing_summary: str = "", *, force: bool = False
) -> CompactionResult:
    if not force and (estimate_tokens(messages) < CONTEXT_TOKEN_THRESHOLD or len(messages) <= KEEP_RECENT_MESSAGES):
        return CompactionResult(messages, existing_summary, 0)
    aligned = max(0, len(messages) - KEEP_RECENT_MESSAGES)
    while aligned > 0 and messages[aligned].get("role") != "user":
        aligned -= 1
    if not aligned and force and len(messages) > 1:
        aligned = len(messages) - 1
    if not aligned:
        return CompactionResult(messages, existing_summary, 0)
    compressed, kept = messages[:aligned], messages[aligned:]
    conversation = "\n\n".join(
        f"**{message.get('role')}**: {text}" for message in compressed if (text := _message_text(message))
    )
    if not conversation.strip():
        return CompactionResult(messages, existing_summary, 0)
    prompt = (
        f"## 已有摘要（上一次压缩的结果）\n\n{existing_summary}\n\n## 需要压缩的新对话\n\n{conversation}"
        if existing_summary
        else conversation
    )
    try:
        write_transcript(messages)
        summary = await model.generate(system=COMPRESS_PROMPT, prompt=prompt)
    except Exception as error:
        print(f"[Compaction] LLM 摘要失败: {error}")
        return CompactionResult(messages, existing_summary, 0)
    summary_message = {
        "role": "user",
        "content": f"[以下是之前对话的压缩摘要]\n\n{summary}\n\n[摘要结束，以下是最近的对话]",
    }
    return CompactionResult([summary_message, *kept], summary, len(compressed))
