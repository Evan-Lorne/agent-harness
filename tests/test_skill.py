from __future__ import annotations

from pathlib import Path

from harness.skills.loader import SkillLoader


def test_code_review_skill_loads_with_resolvable_references() -> None:
    loader = SkillLoader(Path.cwd())
    skills = loader.load()
    skill = loader.get("code-review-expert")

    assert any(item.name == "code-review-expert" for item in skills)
    assert skill is not None
    assert skill.dir_path.is_absolute()
    assert (skill.dir_path / "references/solid-checklist.md").exists()
    assert "Do NOT implement" in skill.content

    prompt = loader.build_prompt_section({"code-review-expert"}) or ""
    assert str(skill.dir_path) in prompt
    assert "review-first workflow" in prompt
