"""Install one portable user-level onboarding Skill for supported coding agents."""

from __future__ import annotations

import os
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Iterable, Mapping

from .catalog import SharedKnowledgeError


ONBOARDING_SKILL_NAME = "team-knowledge-prepare"
_CONSUMERS = ("codex", "claude", "copilot")
_CONSUMER_EXECUTABLES = {"codex": "codex", "claude": "claude", "copilot": "copilot"}


def onboarding_skill_text() -> str:
    return files("repo_adaptive_agents.shared_knowledge").joinpath(
        "skill_template", ONBOARDING_SKILL_NAME, "SKILL.md"
    ).read_text(encoding="utf-8")


def onboarding_destinations(
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Path]:
    """Return standard user-level Skill locations without creating them."""
    user_home = Path.home() if home is None else home
    environment = os.environ if environ is None else environ
    codex_home = Path(environment.get("CODEX_HOME", str(user_home / ".codex"))).expanduser()
    return {
        "codex": codex_home / "skills" / ONBOARDING_SKILL_NAME / "SKILL.md",
        "claude": user_home / ".claude" / "skills" / ONBOARDING_SKILL_NAME / "SKILL.md",
        "copilot": user_home / ".agents" / "skills" / ONBOARDING_SKILL_NAME / "SKILL.md",
    }


def onboarding_readiness(
    consumers: Iterable[str] = _CONSUMERS,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[tuple[str, bool], ...]:
    """Report whether the selected agent CLIs are on PATH without changing the machine."""
    requested = tuple(dict.fromkeys(consumers))
    unknown = tuple(consumer for consumer in requested if consumer not in _CONSUMER_EXECUTABLES)
    if unknown:
        raise SharedKnowledgeError(f"unknown onboarding consumer: {unknown[0]}")
    environment = os.environ if environ is None else environ
    path = environment.get("PATH")
    return tuple(
        (consumer, shutil.which(_CONSUMER_EXECUTABLES[consumer], path=path) is not None)
        for consumer in requested
    )


def install_onboarding_skills(
    consumers: Iterable[str] = _CONSUMERS,
    *,
    dry_run: bool = False,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> tuple[tuple[str, Path, bool], ...]:
    """Install without overwriting a distinct user Skill; return (consumer, path, created)."""
    destinations = onboarding_destinations(home=home, environ=environ)
    requested = tuple(dict.fromkeys(consumers))
    unknown = tuple(consumer for consumer in requested if consumer not in destinations)
    if unknown:
        raise SharedKnowledgeError(f"unknown onboarding consumer: {unknown[0]}")
    expected = onboarding_skill_text()
    already_current: set[str] = set()
    for consumer in requested:
        destination = destinations[consumer]
        if destination.exists() or destination.is_symlink():
            if (
                destination.is_file()
                and not destination.is_symlink()
                and destination.read_text(encoding="utf-8") == expected
            ):
                already_current.add(consumer)
                continue
            raise SharedKnowledgeError(
                f"refusing to overwrite existing {consumer} onboarding Skill: {destination}"
            )
    if dry_run:
        return tuple((consumer, destinations[consumer], consumer not in already_current) for consumer in requested)
    for consumer in requested:
        if consumer in already_current:
            continue
        destination = destinations[consumer]
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(expected)
    return tuple((consumer, destinations[consumer], consumer not in already_current) for consumer in requested)
