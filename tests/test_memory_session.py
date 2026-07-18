from __future__ import annotations

import json

from harness.memory.store import MemoryStore
from harness.session.store import SessionStore


def test_memory_frontmatter_index_search_and_delete(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    filename = store.save(
        {
            "name": "Python preference",
            "description": "Prefer Python tools",
            "type": "user",
            "content": "用户偏好 Python，并使用 pyproject.toml。",
        }
    )

    entries = store.list()
    assert filename == "user_python-preference.md"
    assert entries[0].name == "Python preference"
    assert entries[0].last_read_at is not None
    assert store.search("Python")[0].entry.name == "Python preference"
    assert "Python preference" in store.load_index()
    assert "pyproject.toml" in (store.load_file(filename) or "")
    assert store.delete(filename)
    assert store.list() == []


def test_session_jsonl_is_compatible_and_skips_malformed_lines(tmp_path) -> None:
    store = SessionStore("review", tmp_path)
    message = {"role": "user", "content": "hello"}
    store.append(message)
    with store.file_path.open("a", encoding="utf-8") as file:
        file.write("not-json\n")

    assert store.load() == [message]
    entry = json.loads(store.file_path.read_text(encoding="utf-8").splitlines()[0])
    assert entry["type"] == "message"
    assert entry["message"] == message


def test_session_replace_all_persists_compacted_history(tmp_path) -> None:
    store = SessionStore("review", tmp_path)
    store.append({"role": "user", "content": "old"})
    compacted = [
        {"role": "user", "content": "[summary]"},
        {"role": "assistant", "content": [{"type": "text", "text": "latest"}]},
    ]

    store.replace_all(compacted)

    assert store.load() == compacted
