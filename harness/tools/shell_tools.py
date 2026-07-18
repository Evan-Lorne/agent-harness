import asyncio
import os
import signal

from harness.tools.registry import ToolDefinition
from harness.workspace import current_workdir

BASH_TIMEOUT_SECONDS = 10


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=1)
    except TimeoutError:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        await process.wait()


async def _bash(args: dict) -> str:
    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_shell(
            args["command"],
            cwd=current_workdir(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=BASH_TIMEOUT_SECONDS)
        output = stdout.decode(errors="replace")
        if process.returncode == 0:
            return output or "(命令执行成功，无输出)"
        error = stderr.decode(errors="replace") or output
        return f"命令执行失败 (exit {process.returncode or 1}):\n{error}"
    except TimeoutError:
        if process is not None:
            await _stop_process(process)
        return "命令执行失败 (exit 1):\n命令执行超时"
    except asyncio.CancelledError:
        if process is not None:
            await asyncio.shield(_stop_process(process))
        raise
    except Exception as error:
        return f"[bash 不可用] 当前环境不支持 shell 命令。运行 uv run agent-harness 可使用 bash 工具。\n{error}"


bash_tool = ToolDefinition(
    "bash",
    "执行 shell 命令并返回输出",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "run_in_background": {"type": "boolean", "description": "后台运行慢命令，并在完成后接收通知"},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
    _bash,
    False,
    False,
    3000,
)
