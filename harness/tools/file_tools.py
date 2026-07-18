from harness.tools.registry import ToolDefinition
from harness.workspace import resolve_path


async def _read(args: dict) -> str:
    path = resolve_path(args["path"])
    if not path.exists():
        return f"文件不存在: {args['path']}"
    return path.read_text(encoding="utf-8")


async def _write(args: dict) -> str:
    path = resolve_path(args["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args["content"], encoding="utf-8")
    return f"已写入 {len(args['content'])} 字符到 {args['path']}"


async def _edit(args: dict) -> str:
    path = resolve_path(args["path"])
    if not path.exists():
        return f"文件不存在: {args['path']}"
    content = path.read_text(encoding="utf-8")
    count = content.count(args["old_string"])
    if count == 0:
        return "未找到匹配内容。请检查 old_string 是否与文件中的文本完全一致"
    if count > 1:
        return f"找到 {count} 处匹配，请提供更多上下文让 old_string 唯一"
    path.write_text(content.replace(args["old_string"], args["new_string"], 1), encoding="utf-8")
    return f"已替换 {args['path']} 中的内容（{len(args['old_string'])} → {len(args['new_string'])} 字符）"


async def _list_directory(args: dict) -> str:
    raw_path = args.get("path", ".")
    path = resolve_path(raw_path)
    if not path.exists():
        return f"目录不存在: {raw_path}"
    values: list[str] = []
    for item in path.iterdir():
        try:
            values.append(f"{'[DIR]' if item.is_dir() else '[FILE]'} {item.name}")
        except OSError:
            values.append(f"[?] {item.name}")
    return "\n".join(values)


read_file_tool = ToolDefinition(
    "read_file",
    "读取指定路径的文件内容",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "文件路径"}},
        "required": ["path"],
        "additionalProperties": False,
    },
    _read,
    True,
    True,
    3000,
)
write_file_tool = ToolDefinition(
    "write_file",
    "写入内容到指定文件。如果文件已存在则覆盖",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的内容"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    _write,
)
edit_file_tool = ToolDefinition(
    "edit_file",
    "精确替换文件中的指定内容。用 old_string 定位要替换的文本，用 new_string 替换它",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "old_string": {"type": "string", "description": "要被替换的原始文本（必须精确匹配）"},
            "new_string": {"type": "string", "description": "替换后的新文本"},
        },
        "required": ["path", "old_string", "new_string"],
        "additionalProperties": False,
    },
    _edit,
)
list_directory_tool = ToolDefinition(
    "list_directory",
    "列出指定目录下的文件和子目录",
    {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "目录路径，默认为当前目录"}},
        "required": [],
        "additionalProperties": False,
    },
    _list_directory,
    True,
    True,
)
