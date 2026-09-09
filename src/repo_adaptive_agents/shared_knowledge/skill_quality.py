"""Independent, read-only semantic assessment for one proposed Skill package."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .catalog import SharedKnowledgeError
from .skill_validation import SkillCandidate


class SkillAssessmentUnavailable(SharedKnowledgeError):
    """The explicitly chosen isolated evaluator could not be invoked."""


class SkillAssessmentResponseError(SharedKnowledgeError):
    """The evaluator response did not satisfy the independent assessment contract."""


@dataclass(frozen=True)
class SkillAssessment:
    decision: str
    summary: str
    required_changes: tuple[str, ...]
    findings: tuple[str, ...]
    in_scope_exercise: str
    out_of_scope_exercise: str


ASSESSMENT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["ready", "needs_revision", "inconclusive"]},
        "summary": {"type": "string", "minLength": 1},
        "required_changes": {"type": "array", "items": {"type": "string"}},
        "findings": {"type": "array", "items": {"type": "string"}},
        "in_scope_exercise": {"type": "string", "minLength": 1},
        "out_of_scope_exercise": {"type": "string", "minLength": 1},
    },
    "required": ["decision", "summary", "required_changes", "findings", "in_scope_exercise", "out_of_scope_exercise"],
    "additionalProperties": False,
}


def _candidate_payload(candidate: SkillCandidate) -> dict[str, object]:
    return {
        "path_label": candidate.path.name,
        "name": candidate.name,
        "description": candidate.description,
        "files": [
            {"path": path, "content": content.decode("utf-8")}
            for path, content in candidate.files
        ],
    }


def assessment_prompt(candidate: SkillCandidate) -> str:
    payload = {"schema_version": 1, "candidate": _candidate_payload(candidate)}
    return (
        "You are an independent evaluator of exactly one proposed portable Agent Skill. "
        "You receive no repository, tools, credentials, user configuration, or other Skills. "
        "Do not assume facts absent from this package. Assess whether it is generic enough for a "
        "shared catalog, keeps permissions and workspace-dependent facts conditional, and has a "
        "narrow discovery trigger. Put only blocking, concrete fixes in required_changes; put all "
        "other observations in findings. Propose one realistic "
        "in-scope exercise and one nearby out-of-scope exercise that must not activate it. "
        "Return ready only when the package is suitable to propose for human review; this does not "
        "publish or approve it. Respond only with JSON matching this schema:\n"
        + json.dumps(ASSESSMENT_SCHEMA, sort_keys=True, separators=(",", ":"))
        + "\n\nCandidate:\n"
        + json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    )


def _parse_assessment(data: object) -> SkillAssessment:
    if not isinstance(data, dict) or set(data) != set(ASSESSMENT_SCHEMA["required"]):
        raise SkillAssessmentResponseError("evaluator response does not match the assessment schema")
    decision, summary = data.get("decision"), data.get("summary")
    required_changes, findings = data.get("required_changes"), data.get("findings")
    exercises = (data.get("in_scope_exercise"), data.get("out_of_scope_exercise"))
    if decision not in {"ready", "needs_revision", "inconclusive"}:
        raise SkillAssessmentResponseError("evaluator returned an invalid assessment decision")
    if not isinstance(summary, str) or not summary.strip():
        raise SkillAssessmentResponseError("evaluator summary must be non-empty")
    if not isinstance(required_changes, list) or any(not isinstance(item, str) or not item.strip() for item in required_changes):
        raise SkillAssessmentResponseError("evaluator required_changes must be an array of non-empty strings")
    if not isinstance(findings, list) or any(not isinstance(item, str) or not item.strip() for item in findings):
        raise SkillAssessmentResponseError("evaluator findings must be an array of non-empty strings")
    if any(not isinstance(item, str) or not item.strip() for item in exercises):
        raise SkillAssessmentResponseError("evaluator exercises must be non-empty strings")
    return SkillAssessment(decision, summary.strip(), tuple(item.strip() for item in required_changes), tuple(item.strip() for item in findings), exercises[0].strip(), exercises[1].strip())


def assess_with_codex(candidate: SkillCandidate, executable: str = "codex", timeout_seconds: int = 300) -> SkillAssessment:
    """Run one fresh Codex process with no working tree or tool access."""
    prompt = assessment_prompt(candidate)
    with tempfile.TemporaryDirectory(prefix="team-knowledge-skill-assessment-") as temporary:
        root = Path(temporary)
        schema_path, output_path = root / "output-schema.json", root / "assessment.json"
        subprocess.run(
            ["git", "init", "-q"],
            cwd=root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        schema_path.write_text(json.dumps(ASSESSMENT_SCHEMA, sort_keys=True), encoding="utf-8")
        try:
            result = subprocess.run(
                [
                    executable, "exec", "--ephemeral", "--sandbox", "read-only", "--ignore-user-config",
                    "--ignore-rules", "--output-schema", str(schema_path), "--output-last-message",
                    str(output_path), prompt,
                ],
                cwd=root, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                timeout=timeout_seconds,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as error:
            raise SkillAssessmentUnavailable(f"isolated Codex assessment is unavailable: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "Codex exited unsuccessfully"
            raise SkillAssessmentUnavailable(f"isolated Codex assessment is unavailable: {detail}")
        try:
            return _parse_assessment(json.loads(output_path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SkillAssessmentResponseError("Codex returned malformed assessment JSON") from error


def assess_with_claude(candidate: SkillCandidate, executable: str = "claude", timeout_seconds: int = 300) -> SkillAssessment:
    prompt, schema = assessment_prompt(candidate), json.dumps(ASSESSMENT_SCHEMA, sort_keys=True)
    command = [
        executable, "--safe-mode", "-p", "--tools", "", "--disable-slash-commands", "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence", "--output-format", "json",
        "--json-schema", schema, prompt,
    ]
    try:
        result = subprocess.run(command, cwd=tempfile.gettempdir(), check=False, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, timeout=timeout_seconds)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise SkillAssessmentUnavailable(f"isolated Claude assessment is unavailable: {error}") from error
    if result.returncode != 0:
        raise SkillAssessmentUnavailable("isolated Claude assessment is unavailable")
    try:
        return _parse_assessment(json.loads(result.stdout)["structured_output"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise SkillAssessmentResponseError("Claude returned malformed assessment JSON") from error


def assess_with_copilot(candidate: SkillCandidate, executable: str = "copilot", timeout_seconds: int = 300) -> SkillAssessment:
    environment = dict(os.environ)
    environment.update({
        "GITHUB_COPILOT_PROMPT_MODE_EXTENSIONS": "false",
        "GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS": "false",
        "GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": "false",
    })
    command = [executable, "-p", assessment_prompt(candidate), "-s", "--no-ask-user", "--no-custom-instructions",
               "--disable-builtin-mcps", "--no-experimental", "--available-tools="]
    try:
        result = subprocess.run(command, cwd=tempfile.gettempdir(), check=False, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, timeout=timeout_seconds, env=environment)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        raise SkillAssessmentUnavailable(f"isolated Copilot assessment is unavailable: {error}") from error
    if result.returncode != 0:
        raise SkillAssessmentUnavailable("isolated Copilot assessment is unavailable")
    try:
        return _parse_assessment(json.loads(result.stdout))
    except json.JSONDecodeError as error:
        raise SkillAssessmentResponseError("Copilot returned malformed assessment JSON") from error


def assess_candidate(selector: str, candidate: SkillCandidate) -> SkillAssessment:
    if selector == "claude":
        return assess_with_claude(candidate)
    if selector == "copilot":
        return assess_with_copilot(candidate)
    return assess_with_codex(candidate)
