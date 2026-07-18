from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from harness.tools.registry import ToolDefinition


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str
    content: str
    dir_path: Path
    when_to_use: str | None = None


class SkillLoader:
    def __init__(self, base_dir: str | Path = ".") -> None:
        self.base_dir = Path(base_dir)
        self.skills: dict[str, SkillDefinition] = {}

    @property
    def skills_dir(self) -> Path:
        return self.base_dir / ".skills"

    def load(self) -> list[SkillDefinition]:
        self.skills.clear()
        if not self.skills_dir.exists():
            return []
        for directory in self.skills_dir.iterdir():
            skill_file = directory / "SKILL.md"
            if not directory.is_dir() or not skill_file.exists():
                continue
            description, when_to_use, content = self._parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            self.skills[directory.name] = SkillDefinition(
                directory.name, description, content, directory.resolve(), when_to_use
            )
        return self.list()

    def list(self) -> list[SkillDefinition]:
        return list(self.skills.values())

    def get(self, name: str) -> SkillDefinition | None:
        return self.skills.get(name)

    def build_prompt_section(self, active_skills: set[str]) -> str | None:
        if not self.skills:
            return None
        lines: list[str] = []
        for name in active_skills:
            skill = self.skills.get(name)
            if skill:
                lines.extend([f"[激活的 Skill: {skill.name}]", f"[Skill 根目录: {skill.dir_path}]", skill.content, ""])
        available = []
        for skill in self.list():
            if skill.name in active_skills:
                continue
            hint = f" (适用场景: {skill.when_to_use})" if skill.when_to_use else ""
            available.append(f"  /{skill.name} — {skill.description}{hint}")
        if available:
            lines.extend(["可用的 Skills（需要完整内容时调用 load_skill）：", *available])
        return "\n".join(lines) if lines else None

    @staticmethod
    def _parse_frontmatter(raw: str) -> tuple[str, str | None, str]:
        match = re.match(r"^---\n([\s\S]*?)\n---\n([\s\S]*)$", raw)
        if not match:
            return "", None, raw
        metadata: dict[str, str] = {}
        for line in match.group(1).splitlines():
            key, separator, value = line.partition(":")
            if separator:
                metadata[key.strip()] = value.strip().strip("\"'")
        return metadata.get("description", ""), metadata.get("when_to_use"), match.group(2).strip()


def create_load_skill_tool(loader: SkillLoader) -> ToolDefinition:
    async def execute(args: dict) -> str:
        skill = loader.get(args.get("name", ""))
        if not skill:
            return f"Skill not found: {args.get('name', '')}"
        return f"[Skill 根目录: {skill.dir_path}]\n\n{skill.content}"

    return ToolDefinition(
        "load_skill",
        "按名称加载 Skill 的完整说明。先从 system prompt 的目录选择 Skill，再调用本工具。",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        execute,
        True,
        True,
    )
