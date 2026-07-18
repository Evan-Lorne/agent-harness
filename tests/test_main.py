from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Coroutine
from typing import Any

import harness.__main__ as cli
from harness.main import async_input


async def test_async_input_reads_stdin_without_executor(monkeypatch, capsys) -> None:
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", reader)

    async def unexpected_to_thread(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("async_input must not use an executor thread")

    monkeypatch.setattr(asyncio, "to_thread", unexpected_to_thread)
    os.write(write_fd, b"hello\n")
    try:
        assert await async_input("You: ") == "hello"
    finally:
        os.close(write_fd)
        reader.close()

    assert capsys.readouterr().out == "You: "


def test_cli_treats_keyboard_interrupt_as_normal_exit(monkeypatch, capsys) -> None:
    def interrupt(coroutine: Coroutine[Any, Any, Any]) -> None:
        coroutine.close()
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.asyncio, "run", interrupt)
    monkeypatch.setattr(cli.sys, "argv", ["agent-harness"])

    cli.main()

    assert capsys.readouterr().out == "\n"
