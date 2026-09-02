"""Narrow model-owned semantic selectors for canonical Skill routing metadata."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from repo_adaptive_agents.shared_knowledge.catalog import SharedKnowledgeError

from .evidence import RepositoryKnowledgeEvidence


@dataclass(frozen=True)
class SkillRoutingEntry:
    id: str
    name: str
    description: str

    def to_data(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "description": self.description}


@dataclass(frozen=True)
class SkillSelectionEntry:
    id: str
    reason: str | None = None


@dataclass(frozen=True)
class SkillSelection:
    selected: tuple[SkillSelectionEntry, ...]


class SkillSelector(Protocol):
    def select(
        self,
        evidence: RepositoryKnowledgeEvidence,
        skills: tuple[SkillRoutingEntry, ...],
    ) -> SkillSelection: ...


class SelectorUnavailable(SharedKnowledgeError):
    """The configured semantic selector could not be invoked."""


class SelectorResponseError(SharedKnowledgeError):
    """The selector returned malformed structured data."""


OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "selected": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "reason": {"type": ["string", "null"]},
                },
                "required": ["id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["schema_version", "selected"],
    "additionalProperties": False,
}

SELECTOR_NAMES = ("codex", "claude", "copilot")
SELECTION_INSTRUCTION = (
    "Select the supplied team Skills that are reasonably likely to be useful for normal "
    "engineering work in this repository. Optimize for useful recall rather than a perfectly "
    "minimal set. A Skill should have a plausible ongoing relationship to the repository, its "
    "systems, dependencies, deployment or runtime environment, or normal engineering workflows. "
    "Do not invent Skills. Return only supplied IDs. Do not decide approval, lifecycle, revocation, "
    "permissions, or hard eligibility; those are validated separately. Do not inspect the filesystem "
    "or use tools. Respond only with the requested structured JSON."
)


def build_selection_request(
    evidence: RepositoryKnowledgeEvidence,
    skills: tuple[SkillRoutingEntry, ...],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "repository": evidence.data,
        "available_skills": [skill.to_data() for skill in skills],
    }


def build_selection_prompt(request: Mapping[str, object]) -> str:
    return (
        f"{SELECTION_INSTRUCTION}\n\nExact response JSON Schema:\n"
        + json.dumps(OUTPUT_SCHEMA, sort_keys=True, separators=(",", ":"))
        + "\n\nSelector input:\n"
        + json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def _environment() -> dict[str, str]:
    return dict(os.environ)


def _last_error(stderr: str, fallback: str) -> str:
    return stderr.strip().splitlines()[-1] if stderr.strip() else fallback


class CodexSkillSelector:
    def __init__(self, executable: str = "codex", timeout_seconds: int = 300) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def select(
        self,
        evidence: RepositoryKnowledgeEvidence,
        skills: tuple[SkillRoutingEntry, ...],
    ) -> SkillSelection:
        prompt = build_selection_prompt(build_selection_request(evidence, skills))
        with tempfile.TemporaryDirectory(prefix="team-knowledge-selector-") as temporary:
            root = Path(temporary)
            subprocess.run(
                ["git", "init", "-q"],
                cwd=root,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            schema_path = root / "output-schema.json"
            output_path = root / "selection.json"
            schema_path.write_text(json.dumps(OUTPUT_SCHEMA, sort_keys=True), encoding="utf-8")
            command = [
                self.executable,
                "exec",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--ignore-user-config",
                "--ignore-rules",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                prompt,
            ]
            try:
                result = subprocess.run(
                    command,
                    cwd=root,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.timeout_seconds,
                    env=_environment(),
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as error:
                raise SelectorUnavailable(f"Codex Skill selector is unavailable: {error}") from error
            if result.returncode != 0:
                raise SelectorUnavailable(
                    "Codex Skill selector is unavailable: "
                    + _last_error(result.stderr, "Codex exited unsuccessfully")
                )
            try:
                raw = output_path.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                safe = (
                    output_path.read_text(encoding="utf-8", errors="replace")[:1000]
                    if output_path.exists()
                    else "<missing>"
                )
                raise SelectorResponseError(f"Codex returned malformed selection JSON: {safe}") from error
        return parse_selection(data)


class ClaudeSkillSelector:
    def __init__(self, executable: str = "claude", timeout_seconds: int = 300) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def select(
        self,
        evidence: RepositoryKnowledgeEvidence,
        skills: tuple[SkillRoutingEntry, ...],
    ) -> SkillSelection:
        prompt = build_selection_prompt(build_selection_request(evidence, skills))
        schema = json.dumps(OUTPUT_SCHEMA, sort_keys=True, separators=(",", ":"))
        command = [
            self.executable,
            "--safe-mode",
            "-p",
            "--tools",
            "",
            "--disable-slash-commands",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--no-session-persistence",
            "--output-format",
            "json",
            "--json-schema",
            schema,
            prompt,
        ]
        with tempfile.TemporaryDirectory(prefix="team-knowledge-selector-") as temporary:
            try:
                result = subprocess.run(
                    command,
                    cwd=temporary,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.timeout_seconds,
                    env=_environment(),
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as error:
                raise SelectorUnavailable(f"Claude Skill selector is unavailable: {error}") from error
        if result.returncode != 0:
            raise SelectorUnavailable(
                "Claude Skill selector is unavailable: "
                + _last_error(result.stderr, "Claude exited unsuccessfully")
            )
        try:
            envelope = json.loads(result.stdout)
            if not isinstance(envelope, dict) or "structured_output" not in envelope:
                raise ValueError("missing structured_output")
            data = envelope["structured_output"]
        except (json.JSONDecodeError, ValueError) as error:
            raise SelectorResponseError(
                f"Claude returned malformed structured output: {result.stdout[:1000]}"
            ) from error
        return parse_selection(data)


class CopilotSkillSelector:
    def __init__(self, executable: str = "copilot", timeout_seconds: int = 300) -> None:
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def select(
        self,
        evidence: RepositoryKnowledgeEvidence,
        skills: tuple[SkillRoutingEntry, ...],
    ) -> SkillSelection:
        prompt = build_selection_prompt(build_selection_request(evidence, skills))
        try:
            return self._invoke(prompt)
        except SelectorResponseError:
            retry = (
                prompt
                + "\n\nYour previous response was not valid JSON matching the requested "
                "schema. Serialize the same selection again as JSON only; do not reconsider "
                "or change it."
            )
            return self._invoke(retry)

    def _invoke(self, prompt: str) -> SkillSelection:
        command = [
            self.executable,
            "-p",
            prompt,
            "-s",
            "--no-ask-user",
            "--no-custom-instructions",
            "--disable-builtin-mcps",
            "--no-experimental",
            "--available-tools=",
        ]
        environment = _environment()
        environment.update({
            "GITHUB_COPILOT_PROMPT_MODE_EXTENSIONS": "false",
            "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS": "false",
            "GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "false",
        })
        with tempfile.TemporaryDirectory(prefix="team-knowledge-selector-") as temporary:
            try:
                result = subprocess.run(
                    command,
                    cwd=temporary,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.timeout_seconds,
                    env=environment,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired) as error:
                raise SelectorUnavailable(f"Copilot Skill selector is unavailable: {error}") from error
        if result.returncode != 0:
            raise SelectorUnavailable(
                "Copilot Skill selector is unavailable: "
                + _last_error(result.stderr, "Copilot exited unsuccessfully")
            )
        try:
            return parse_selection(json.loads(result.stdout))
        except json.JSONDecodeError as error:
            raise SelectorResponseError(
                f"Copilot returned malformed selection JSON: {result.stdout[:1000]}"
            ) from error


def resolve_selector_name(explicit: str | None, environ: Mapping[str, str] | None = None) -> str:
    environment = os.environ if environ is None else environ
    name = (explicit or environment.get("TEAM_KNOWLEDGE_SELECTOR") or "codex").strip().casefold()
    if name not in SELECTOR_NAMES:
        raise SharedKnowledgeError(f"selector must be one of: {', '.join(SELECTOR_NAMES)}")
    return name


def selector_for(name: str) -> SkillSelector:
    resolved = resolve_selector_name(name, {})
    if resolved == "claude":
        return ClaudeSkillSelector()
    if resolved == "copilot":
        return CopilotSkillSelector()
    return CodexSkillSelector()


def parse_selection(data: object) -> SkillSelection:
    if not isinstance(data, dict) or set(data) != {"schema_version", "selected"} or data.get("schema_version") != 1:
        raise SelectorResponseError("selector response must be a schema version 1 object")
    selected = data.get("selected")
    if not isinstance(selected, list):
        raise SelectorResponseError("selector selected must be an array")
    entries: list[SkillSelectionEntry] = []
    for item in selected:
        if not isinstance(item, dict) or set(item) != {"id", "reason"}:
            raise SelectorResponseError("each selector entry must contain only id and reason")
        resource_id = item.get("id")
        reason = item.get("reason")
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise SelectorResponseError("selector IDs must be non-empty strings")
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise SelectorResponseError("selector reasons must be non-empty strings or null")
        entries.append(SkillSelectionEntry(resource_id.strip(), reason.strip() if isinstance(reason, str) else None))
    return SkillSelection(tuple(entries))
