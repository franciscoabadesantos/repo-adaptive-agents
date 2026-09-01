"""Install the single repository-local Codex Agent Skill for v0.1."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from .catalog import SharedKnowledgeError


CODEX_SKILL_PATH = Path(".agents/skills/team-knowledge/SKILL.md")


def skill_text() -> str:
    resource = files("repo_adaptive_agents.shared_knowledge").joinpath(
        "skill_template", "team-knowledge", "SKILL.md"
    )
    return resource.read_text(encoding="utf-8")


def install_codex_skill(root: Path) -> tuple[Path, bool]:
    destination = root / CODEX_SKILL_PATH
    current = root
    for part in CODEX_SKILL_PATH.parent.parts:
        current = current / part
        if current.is_symlink():
            raise SharedKnowledgeError(f"refusing to install Codex Skill through symlink: {current}")
    expected = skill_text()
    if destination.exists() or destination.is_symlink():
        if destination.is_file() and not destination.is_symlink() and destination.read_text(encoding="utf-8") == expected:
            return destination, False
        raise SharedKnowledgeError(f"refusing to overwrite existing Codex Skill: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(expected)
    return destination, True
