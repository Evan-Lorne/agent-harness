import re
from pathlib import Path

from harness.tools.registry import ToolDefinition

SKIP = {"node_modules", ".git", "dist", ".venv", "__pycache__"}
BIN_EXT = {".png", ".jpg", ".gif", ".woff", ".woff2", ".ico", ".lock"}


async def _glob(args: dict) -> str:
    base = Path(args.get("path", ".")).resolve()
    results: list[str] = []
    for item in base.rglob("*"):
        if any(part in SKIP for part in item.parts):
            continue
        relative = item.relative_to(base)
        pattern = args["pattern"]
        matches = relative.match(pattern) or (pattern.startswith("**/") and relative.match(pattern[3:]))
        if item.is_file() and matches:
            results.append(relative.as_posix())
            if len(results) >= 100:
                break
    return "\n".join(sorted(results)) if results else f'没有找到匹配 "{args["pattern"]}" 的文件'


async def _grep(args: dict) -> str:
    base = Path(args.get("path", ".")).resolve()
    regex = re.compile(args["pattern"], re.IGNORECASE)
    matches: list[str] = []
    files = [base] if base.is_file() else base.rglob("*")
    for file in files:
        if len(matches) >= 50:
            break
        if not file.is_file() or file.suffix in BIN_EXT or any(part in SKIP for part in file.parts):
            continue
        try:
            lines = file.read_text(encoding="utf-8").split("\n")
        except (OSError, UnicodeDecodeError):
            continue
        relative = file.relative_to(base).as_posix() if base.is_dir() else file.name
        for index, line in enumerate(lines, 1):
            if regex.search(line):
                matches.append(f"{relative}:{index}: {line.rstrip()}")
                if len(matches) >= 50:
                    break
    if not matches:
        return f'没有找到匹配 "{args["pattern"]}" 的内容'
    return "\n".join(matches) + ("\n... (结果已截断)" if len(matches) >= 50 else "")


glob_tool = ToolDefinition(
    "glob",
    '按模式搜索文件。支持 * 和 ** 通配符，如 "harness/**/*.py"',
    {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": '搜索模式，如 "**/*.py"'},
            "path": {"type": "string", "description": "搜索起始目录，默认当前目录"},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    },
    _glob,
    True,
    True,
)
grep_tool = ToolDefinition(
    "grep",
    "在文件中搜索匹配指定模式的内容。返回匹配的行号和内容",
    {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "搜索模式（正则表达式）"},
            "path": {"type": "string", "description": "搜索路径，默认当前目录"},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    },
    _grep,
    True,
    True,
    3000,
)
