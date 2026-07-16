"""Render a reversible, local Codex proposal and a diff against existing config."""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import tempfile
import tomllib
from pathlib import Path

from .models import RepoProfile, TeamPlan, to_jsonable


class ProposalError(ValueError):
    """Raised when a proposal cannot be created without risking existing files."""


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _config(plan: TeamPlan) -> str:
    names = ", ".join(_toml_string(agent.name) for agent in plan.agents)
    lines = ["# Generated proposal; review before copying into .codex/.", 'model = "gpt-5.6-luna"', 'model_reasoning_effort = "medium"', "", "[agents]", f"max_threads = {min(8, max(1, len(plan.agents)))}", "max_depth = 1", "interrupt_message = true", ""]
    lines.append(f"# agents = [{names}]")
    for agent in plan.agents:
        lines.extend([f"[agents.{agent.name}]", f"description = {_toml_string(agent.title + ': ' + agent.purpose)}", f"config_file = {_toml_string('agents/' + agent.name + '.toml')}", ""])
    return "\n".join(lines)


def _agent(agent) -> str:
    capability_text = ", ".join(agent.capabilities)
    return "\n".join([
        f"name = {_toml_string(agent.name)}",
        f"description = {_toml_string(agent.title + ': ' + agent.purpose)}",
        'model = "gpt-5.6-luna"',
        'model_reasoning_effort = "medium"',
        'sandbox_mode = "read-only"',
        "nickname_candidates = [\"Advisor\"]",
        "developer_instructions = " + _toml_string(
            f"Own capabilities: {capability_text}. {agent.rationale} Return evidence, uncertainty, and recommendations. Do not edit, commit, push, deploy, install integrations, or access external systems."
        ),
        "",
    ])


def _validate_rendered(path: Path, content: str) -> None:
    try:
        if path.suffix == ".toml":
            tomllib.loads(content)
        elif path.suffix == ".json":
            json.loads(content)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        raise ProposalError(f"Generated file is invalid: {path.name} ({type(error).__name__})") from error


def _validate_agent_name(name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ProposalError(f"Unsafe generated agent name: {name!r}")


def write_proposal(profile: RepoProfile, plan: TeamPlan, output_dir: str | Path) -> list[Path]:
    repo_root = Path(profile.path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if output == repo_root:
        raise ProposalError("Proposal output cannot be the analyzed repository root")
    if output == repo_root / ".codex":
        raise ProposalError("Proposal output cannot be the analyzed repository's .codex directory")
    if output.is_relative_to(repo_root):
        raise ProposalError("Proposal output cannot be inside the analyzed repository")
    if output.exists() or output.is_symlink():
        raise ProposalError(f"Proposal output already exists; refusing to overwrite: {output}")

    for agent in plan.agents:
        _validate_agent_name(agent.name)
    rendered = {
        "config.toml": _config(plan),
        "profile.json": json.dumps(to_jsonable(profile), indent=2, sort_keys=True) + "\n",
        "team-plan.json": json.dumps(to_jsonable(plan), indent=2, sort_keys=True) + "\n",
    }
    rendered.update({f"agents/{agent.name}.toml": _agent(agent) for agent in plan.agents})
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        for relative, content in rendered.items():
            path = temporary / relative
            _validate_rendered(path, content)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return [output / relative for relative in rendered]


def proposal_diff(proposal_dir: str | Path, existing_dir: str | Path) -> str:
    proposal = Path(proposal_dir).expanduser().resolve()
    existing = Path(existing_dir).expanduser().resolve()
    proposal_files = sorted(path for path in proposal.rglob("*") if path.is_file())
    proposal_by_relative = {path.relative_to(proposal).as_posix(): path for path in proposal_files}
    existing_files = {path.relative_to(existing).as_posix(): path for path in existing.rglob("*") if path.is_file()} if existing.is_dir() else {}
    chunks: list[str] = []
    for relative in sorted(proposal_by_relative):
        path = proposal_by_relative[relative]
        old = existing_files.get(relative)
        old_lines = old.read_text(encoding="utf-8").splitlines(keepends=True) if old else []
        new_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        if old and old_lines == new_lines:
            continue
        kind = "add" if old is None else "change/conflict"
        chunks.append(f"# {kind}: {relative}\n")
        chunks.extend(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/.codex/{relative}" if old else "/dev/null",
            tofile=f"b/.codex/{relative}",
        ))
    return "".join(chunks)
