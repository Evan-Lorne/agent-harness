from __future__ import annotations

import json
import re
from pathlib import Path

from harness.memory.store import MemoryStore
from harness.types import Message, Model, content_to_text

MEMORY_TYPES = {"user", "feedback", "project", "reference"}
CONSOLIDATE_THRESHOLD = 10


def _recent_text(messages: list[Message], limit: int = 10) -> str:
    return "\n".join(
        f"{message.get('role')}: {content_to_text(message.get('content'))}" for message in messages[-limit:]
    )[:6000]


def _parse_json_array(raw: str) -> list[dict]:
    match = re.search(r"\[[\s\S]*\]", raw)
    if not match:
        return []
    try:
        value = json.loads(match.group(0))
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


async def load_relevant_memories(model: Model, store: MemoryStore, messages: list[Message], max_items: int = 5) -> str:
    entries = store.list()
    if not entries:
        return ""
    catalog = "\n".join(f"{index}: {entry.name} — {entry.description}" for index, entry in enumerate(entries))
    prompt = f"Select up to {max_items} relevant memory indices for the conversation. Return only a JSON array of integers.\n\nConversation:\n{_recent_text(messages)}\n\nCatalog:\n{catalog}"
    selected: list[int] = []
    try:
        raw = await model.generate(system="Select relevant long-term memories conservatively.", prompt=prompt)
        match = re.search(r"\[[\d,\s]*\]", raw)
        if match:
            selected = [value for value in json.loads(match.group(0)) if isinstance(value, int)]
    except Exception:
        selected = []
    if not selected:
        query = _recent_text(messages, 3)
        hits = store.search(query, max_items)
        selected = [entries.index(hit.entry) for hit in hits if hit.entry in entries]
    contents = []
    for index in selected[:max_items]:
        if 0 <= index < len(entries):
            filename = Path(entries[index].file_path).name
            if content := store.load_file(filename):
                contents.append(content)
    return "\n\n".join(contents)


async def extract_memories(model: Model, store: MemoryStore, messages: list[Message]) -> int:
    existing = "\n".join(f"- {entry.name}: {entry.description}" for entry in store.list())
    prompt = (
        "Extract only durable user preferences, corrections, project decisions, or external references that cannot be derived from files. "
        "Return JSON array items with name, type, description, content. Return [] when nothing is new.\n\n"
        f"Existing:\n{existing}\n\nConversation:\n{_recent_text(messages)}"
    )
    try:
        values = _parse_json_array(
            await model.generate(system="Extract durable memories without speculation.", prompt=prompt)
        )
    except Exception:
        return 0
    saved = 0
    existing_names = {entry.name.lower() for entry in store.list()}
    for value in values:
        if value.get("type") not in MEMORY_TYPES or not all(
            value.get(key) for key in ("name", "description", "content")
        ):
            continue
        if str(value["name"]).lower() in existing_names:
            continue
        store.save(value)
        existing_names.add(str(value["name"]).lower())
        saved += 1
    return saved


async def consolidate_memories(model: Model, store: MemoryStore) -> int:
    entries = store.list()
    if len(entries) < CONSOLIDATE_THRESHOLD:
        return 0
    payload = [
        {"name": item.name, "type": item.type, "description": item.description, "content": item.content}
        for item in entries
    ]
    try:
        values = _parse_json_array(
            await model.generate(
                system="Deduplicate memories while preserving current facts.",
                prompt=json.dumps(payload, ensure_ascii=False),
            )
        )
    except Exception:
        return 0
    valid = [
        value
        for value in values
        if value.get("type") in MEMORY_TYPES and all(value.get(key) for key in ("name", "description", "content"))
    ]
    if not valid:
        return 0
    try:
        store.replace_all(valid)
    except (OSError, ValueError):
        return 0
    return len(entries) - len(valid)
