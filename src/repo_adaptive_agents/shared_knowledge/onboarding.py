"""Install one portable user-level onboarding Skill for supported coding agents."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Iterable, Mapping

from .repository import SharedKnowledgeError


ONBOARDING_SKILL_NAME = "team-knowledge-prepare"
_CONSUMERS = ("codex", "claude", "copilot")
_CONSUMER_EXECUTABLES = {"codex": "codex", "claude": "claude", "copilot": "copilot"}
_MANAGED_MARKER = ".team-knowledge-managed.json"
_KNOWN_MANAGED_DIGESTS = {
    "ddff2de0fd31b82a47791e74d0245e9ca7453ec2bc4ac0636ea29641fd8660c2",
}


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
    expected_digest = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    already_current: set[str] = set()
    managed_updates: set[str] = set()
    for consumer in requested:
        destination = destinations[consumer]
        if destination.exists() or destination.is_symlink():
            if not destination.is_file() or destination.is_symlink():
                raise SharedKnowledgeError(
                    f"refusing to overwrite existing {consumer} onboarding Skill: {destination}"
                )
            try:
                current = destination.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise SharedKnowledgeError(f"cannot read existing {consumer} onboarding Skill: {error}") from error
            current_digest = hashlib.sha256(current.encode("utf-8")).hexdigest()
            if current == expected:
                already_current.add(consumer)
                continue
            marker = destination.parent / _MANAGED_MARKER
            recorded_digest = None
            if marker.exists() or marker.is_symlink():
                if not marker.is_file() or marker.is_symlink():
                    raise SharedKnowledgeError(f"managed onboarding marker is unsafe: {marker}")
                try:
                    marker_data = json.loads(marker.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise SharedKnowledgeError(f"cannot read managed onboarding marker: {error}") from error
                if (
                    not isinstance(marker_data, dict)
                    or set(marker_data) != {"schema_version", "digest_sha256"}
                    or marker_data.get("schema_version") != 1
                    or not isinstance(marker_data.get("digest_sha256"), str)
                ):
                    raise SharedKnowledgeError(f"managed onboarding marker is invalid: {marker}")
                recorded_digest = marker_data["digest_sha256"]
            if current_digest in _KNOWN_MANAGED_DIGESTS or recorded_digest == current_digest:
                managed_updates.add(consumer)
                continue
            raise SharedKnowledgeError(
                f"refusing to overwrite existing {consumer} onboarding Skill: {destination}"
            )
    if dry_run:
        return tuple((consumer, destinations[consumer], consumer not in already_current) for consumer in requested)
    for consumer in requested:
        destination = destinations[consumer]
        destination.parent.mkdir(parents=True, exist_ok=True)
        marker = destination.parent / _MANAGED_MARKER
        if consumer not in already_current:
            if consumer in managed_updates:
                temporary = destination.with_name(f".{destination.name}.tmp")
                temporary.write_text(expected, encoding="utf-8", newline="\n")
                temporary.replace(destination)
            else:
                with destination.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(expected)
        marker_temporary = marker.with_name(f".{marker.name}.tmp")
        marker_temporary.write_text(
            json.dumps({"schema_version": 1, "digest_sha256": expected_digest}, indent=2) + "\n",
            encoding="utf-8",
        )
        marker_temporary.replace(marker)
    return tuple((consumer, destinations[consumer], consumer not in already_current) for consumer in requested)
