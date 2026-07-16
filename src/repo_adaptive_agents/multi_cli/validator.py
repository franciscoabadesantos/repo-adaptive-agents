"""Local, offline validators for a generated proposal.

Validators never invoke the external CLIs. They check structural properties of the
generated files and the manifest: parseability, required metadata, presence of critical
content, relative paths, and hash agreement. Each ``validate_*`` returns a list of human
-readable issues (empty means valid).
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

_CODEX_KNOWN_FIELDS = {
    "name",
    "description",
    "model_reasoning_effort",
    "sandbox_mode",
    "nickname_candidates",
    "developer_instructions",
}
# Tokens that look like absolute filesystem paths (POSIX root, home, or Windows drive).
_ABSOLUTE_PATH = re.compile(r"(?:^|\s)(?:/[^\s]+|~[/\w]|[A-Za-z]:\\)")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Parse a leading ``---`` YAML frontmatter block into a flat string map."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        fields[key.strip()] = value
    return fields


def _body_after_frontmatter(text: str) -> str:
    end = text.find("\n---\n", 4)
    return text[end + 5 :] if text.startswith("---\n") and end != -1 else text


def validate_skill(path: Path) -> list[str]:
    issues: list[str] = []
    if not path.is_file():
        return [f"skill: missing file {path.name}"]
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        issues.append("skill: file is empty")
    meta = _parse_frontmatter(text)
    if meta is None:
        issues.append("skill: missing or unterminated frontmatter")
    else:
        for key in ("name", "description"):
            if not meta.get(key):
                issues.append(f"skill: missing metadata '{key}'")
    if "## Constraints" not in text:
        issues.append("skill: missing Constraints section")
    if "## Evidence requirements" not in text:
        issues.append("skill: missing Evidence requirements section")
    if _ABSOLUTE_PATH.search(text):
        issues.append("skill: contains an absolute path")
    return issues


def validate_codex(path: Path) -> list[str]:
    if not path.is_file():
        return [f"codex: missing file {path.name}"]
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        return [f"codex: invalid TOML ({error})"]
    issues: list[str] = []
    unknown = set(data) - _CODEX_KNOWN_FIELDS
    if unknown:
        issues.append(f"codex: unknown fields {sorted(unknown)}")
    if not str(data.get("name", "")).strip():
        issues.append("codex: missing name")
    if not str(data.get("developer_instructions", "")).strip():
        issues.append("codex: missing developer_instructions")
    if _ABSOLUTE_PATH.search(text):
        issues.append("codex: contains an absolute path")
    return issues


def _validate_markdown_agent(path: Path, label: str) -> list[str]:
    if not path.is_file():
        return [f"{label}: missing file {path.name}"]
    text = path.read_text(encoding="utf-8")
    issues: list[str] = []
    meta = _parse_frontmatter(text)
    if meta is None:
        issues.append(f"{label}: missing or unterminated frontmatter")
    else:
        for key in ("name", "description"):
            if not meta.get(key):
                issues.append(f"{label}: missing metadata '{key}'")
    if not _body_after_frontmatter(text).strip():
        issues.append(f"{label}: empty body")
    if "## Constraints" not in text:
        issues.append(f"{label}: missing Constraints section")
    if _ABSOLUTE_PATH.search(text):
        issues.append(f"{label}: contains an absolute path")
    return issues


def validate_claude(path: Path) -> list[str]:
    return _validate_markdown_agent(path, "claude")


def validate_copilot(path: Path) -> list[str]:
    return _validate_markdown_agent(path, "copilot")


def validate_manifest(proposal_dir: Path) -> list[str]:
    manifest_path = proposal_dir / "manifest.json"
    if not manifest_path.is_file():
        return ["manifest: missing manifest.json"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"manifest: invalid JSON ({error})"]

    issues: list[str] = []
    declared: list[dict] = []
    for section in manifest.get("targets", {}).values():
        declared.extend(section.get("files", []))
    declared.extend(manifest.get("shared", {}).get("files", []))

    for entry in declared:
        relative = entry.get("path", "")
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            issues.append(f"manifest: non-relative or unsafe path {relative!r}")
            continue
        file_path = proposal_dir / relative
        if not file_path.is_file():
            issues.append(f"manifest: declared file missing {relative}")
            continue
        actual = _sha256(file_path.read_text(encoding="utf-8"))
        if actual != entry.get("sha256"):
            issues.append(f"manifest: hash mismatch for {relative}")
    return issues


# Maps a target name to (relative-path-under-proposal-derived-from-manifest, validator).
_TARGET_VALIDATORS = {
    "skill": validate_skill,
    "codex": validate_codex,
    "claude": validate_claude,
    "copilot": validate_copilot,
}


def validate_proposal(proposal_dir: str | Path) -> list[str]:
    """Validate every generated target and the manifest. Returns all issues found."""
    proposal = Path(proposal_dir).expanduser().resolve()
    issues = list(validate_manifest(proposal))

    manifest_path = proposal / "manifest.json"
    if not manifest_path.is_file():
        return issues
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for target, section in manifest.get("targets", {}).items():
        validator = _TARGET_VALIDATORS.get(target)
        if validator is None:
            issues.append(f"manifest: unknown target {target!r}")
            continue
        for entry in section.get("files", []):
            issues.extend(validator(proposal / entry["path"]))
    return issues
