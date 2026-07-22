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

from ..providers import ProviderResolutionError, parse_provider_resolution

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


def validate_codex_registration(path: Path) -> list[str]:
    """Validate a manual Codex agent-registration fragment."""
    if not path.is_file():
        return [f"codex registration: missing file {path.name}"]
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        return [f"codex registration: invalid TOML ({error})"]

    issues: list[str] = []
    if set(data) != {"agents"} or not isinstance(data.get("agents"), dict):
        issues.append("codex registration: expected only an [agents.<role>] table")
        return issues
    if len(data["agents"]) != 1:
        issues.append("codex registration: expected exactly one agent")
        return issues
    role_id, entry = next(iter(data["agents"].items()))
    if role_id != path.stem:
        issues.append(f"codex registration: table role must match filename {path.stem!r}")
    if not isinstance(entry, dict):
        issues.append("codex registration: agent entry must be a table")
        return issues
    if set(entry) != {"description", "config_file"}:
        issues.append("codex registration: only description and config_file are allowed")
    if not str(entry.get("description", "")).strip():
        issues.append("codex registration: missing description")
    expected = f".codex/agents/{role_id}.toml"
    if entry.get("config_file") != expected:
        issues.append(f"codex registration: config_file must be {expected!r}")
    if _ABSOLUTE_PATH.search(text):
        issues.append("codex registration: contains an absolute path")
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
        declared.extend(section.get("artifacts", {}).values())
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
            path = proposal / entry["path"]
            if target == "codex" and "/.codex/config.fragments/" in f"/{entry['path']}":
                issues.extend(validate_codex_registration(path))
            else:
                issues.extend(validator(path))
    return issues


def _declared_adapter_files(manifest: dict) -> list[dict]:
    declared: list[dict] = []
    artifacts = manifest.get("artifacts")
    if isinstance(artifacts, list):
        declared.extend(artifacts)
    roles = manifest.get("roles")
    for section in roles.values() if isinstance(roles, dict) else []:
        if not isinstance(section, dict):
            continue
        manifest_entry = section.get("manifest")
        if isinstance(manifest_entry, dict):
            declared.append(manifest_entry)
        files = section.get("files")
        if isinstance(files, list):
            declared.extend(files)
        role_artifacts = section.get("artifacts")
        if isinstance(role_artifacts, dict):
            declared.extend(role_artifacts.values())
    return [entry for entry in declared if entry]


def _contains_symlink(root: Path, relative: str) -> bool:
    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def _validate_adapter_semantics(output: Path, manifest: dict) -> list[str]:
    """Cross-check proposal metadata against every rendered role proposal."""
    issues: list[str] = []
    provider_resolution = manifest.get("provider_resolution")
    provider_proposals = manifest.get("provider_gap_proposals")
    if not isinstance(provider_proposals, list):
        issues.append("adapter manifest: provider_gap_proposals must be a list")
        provider_proposals = []
    if provider_resolution is None:
        if provider_proposals:
            issues.append(
                "adapter manifest: provider proposals require provider_resolution"
            )
    elif isinstance(provider_resolution, dict):
        raw_capabilities = provider_resolution.get("capabilities", [])
        capability_ids = [
            item.get("capability_id")
            for item in raw_capabilities
            if isinstance(item, dict) and isinstance(item.get("capability_id"), str)
        ]
        try:
            normalized, proposals = parse_provider_resolution(
                provider_resolution,
                capability_ids,
                require_catalog_for_selection=False,
            )
        except ProviderResolutionError as error:
            issues.append(f"adapter manifest: invalid provider_resolution ({error})")
        else:
            expected_proposals = [
                {
                    "capability_id": proposal.capability_id,
                    "outcome": proposal.outcome,
                    "provider_id": proposal.provider_id,
                }
                for proposal in proposals
            ]
            if normalized != provider_resolution:
                issues.append("adapter manifest: provider_resolution is not canonical")
            if provider_proposals != expected_proposals:
                issues.append(
                    "adapter manifest: provider_gap_proposals do not match provider_resolution"
                )
    else:
        issues.append("adapter manifest: provider_resolution must be an object or null")
    requested = manifest.get("requested_targets")
    if not isinstance(requested, list) or not requested:
        issues.append("adapter manifest: requested_targets must be a non-empty list")
        requested_targets: list[str] = []
    else:
        requested_targets = [item for item in requested if isinstance(item, str)]
        if len(requested_targets) != len(requested):
            issues.append("adapter manifest: requested_targets must contain only strings")
        if len(set(requested_targets)) != len(requested_targets):
            issues.append("adapter manifest: requested_targets contains duplicates")
        unknown_targets = sorted(set(requested_targets).difference(_TARGET_VALIDATORS))
        if unknown_targets:
            issues.append(f"adapter manifest: unknown requested targets {unknown_targets}")

    roles = manifest.get("roles")
    if not isinstance(roles, dict) or not roles:
        issues.append("adapter manifest: roles must be a non-empty object")
        return issues

    selected = manifest.get("selected_adapters")
    if not isinstance(selected, list):
        issues.append("adapter manifest: selected_adapters must be a list")
        selected = []
    selected_by_role: dict[str, dict] = {}
    for item in selected:
        if not isinstance(item, dict) or not isinstance(item.get("role_id"), str):
            issues.append("adapter manifest: selected_adapters contains an invalid entry")
            continue
        role_id = item["role_id"]
        if item.get("selection_source") != "tool_proposal":
            issues.append(
                f"adapter manifest: selected adapter {role_id!r} has an invalid selection_source"
            )
        if role_id in selected_by_role:
            issues.append(f"adapter manifest: duplicate selected adapter {role_id!r}")
            continue
        selected_by_role[role_id] = item
    if set(selected_by_role) != set(roles):
        issues.append("adapter manifest: selected_adapters role ids do not match roles keys")

    for role_id, section in roles.items():
        if not isinstance(role_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", role_id):
            continue
        if not isinstance(section, dict):
            issues.append(f"adapter manifest: role section {role_id!r} is not an object")
            continue
        if section.get("selection") != selected_by_role.get(role_id):
            issues.append(
                f"adapter manifest: role {role_id!r} selection does not match selected_adapters"
            )

        prefix = f"roles/{role_id}/"
        expected_manifest_path = prefix + "manifest.json"
        manifest_entry = section.get("manifest")
        if not isinstance(manifest_entry, dict) or manifest_entry.get("path") != expected_manifest_path:
            issues.append(f"adapter manifest: role {role_id!r} has an invalid manifest path")
            continue
        role_manifest_path = output / expected_manifest_path
        if _contains_symlink(output, expected_manifest_path) or not role_manifest_path.is_file():
            continue
        try:
            role_manifest = json.loads(role_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if role_manifest.get("canonical_role_id") != role_id:
            issues.append(
                f"adapter manifest: role {role_id!r} canonical_role_id does not match"
            )
        if role_manifest.get("targets_requested") != requested_targets:
            issues.append(
                f"adapter manifest: role {role_id!r} targets do not match requested_targets"
            )
        target_sections = role_manifest.get("targets")
        if not isinstance(target_sections, dict) or set(target_sections) != set(requested_targets):
            issues.append(
                f"adapter manifest: role {role_id!r} rendered targets do not match requested_targets"
            )

        expected_files = {expected_manifest_path}
        shared = role_manifest.get("shared")
        if isinstance(shared, dict):
            for entry in shared.get("files", []):
                if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                    expected_files.add(prefix + entry["path"])
        if isinstance(target_sections, dict):
            for target in target_sections.values():
                if not isinstance(target, dict):
                    continue
                for entry in target.get("files", []):
                    if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                        expected_files.add(prefix + entry["path"])
        section_files = section.get("files")
        actual_files = (
            {
                entry["path"]
                for entry in section_files
                if isinstance(entry, dict) and isinstance(entry.get("path"), str)
            }
            if isinstance(section_files, list)
            else set()
        )
        if actual_files != expected_files:
            issues.append(
                f"adapter manifest: role {role_id!r} files do not match its role manifest"
            )
    return issues


def validate_adapter_bundle(output_dir: str | Path) -> list[str]:
    """Validate an adapter bundle and each per-role sub-proposal.

    Checks the aggregated manifest's declared files exist with matching hashes and relative
    paths, then runs the single-role validator on every ``roles/<role-id>/`` subtree.
    """
    output = Path(output_dir).expanduser().resolve()
    manifest_path = output / "manifest.json"
    if manifest_path.is_symlink():
        return ["adapter manifest: manifest.json is a symlink"]
    if not manifest_path.is_file():
        return ["adapter manifest: missing manifest.json"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"adapter manifest: invalid JSON ({error})"]

    issues: list[str] = []
    if manifest.get("kind") != "adapter_bundle":
        issues.append("adapter manifest: kind is not 'adapter_bundle'")
    if "execution_plan" in manifest:
        issues.append("adapter manifest: execution_plan is not allowed")
    if manifest.get("schema_version") != 5:
        issues.append("adapter manifest: unsupported schema_version")
    if manifest.get("selection_status") != "tool_proposal":
        issues.append("adapter manifest: invalid or missing selection_status")
    issues.extend(_validate_adapter_semantics(output, manifest))

    for entry in _declared_adapter_files(manifest):
        relative = entry.get("path", "")
        if not relative or relative.startswith("/") or ".." in Path(relative).parts:
            issues.append(f"adapter manifest: non-relative or unsafe path {relative!r}")
            continue
        if _contains_symlink(output, relative):
            issues.append(f"adapter manifest: declared path contains a symlink {relative}")
            continue
        file_path = output / relative
        if not file_path.is_file():
            issues.append(f"adapter manifest: declared file missing {relative}")
            continue
        if _sha256(file_path.read_text(encoding="utf-8")) != entry.get("sha256"):
            issues.append(f"adapter manifest: hash mismatch for {relative}")

    for section in manifest.get("compare", {}).values() if isinstance(manifest.get("compare"), dict) else []:
        for path in section:
            if isinstance(path, str) and path.startswith("/"):
                issues.append(f"adapter manifest: absolute path in compare result {path!r}")

    roles = manifest.get("roles")
    for role_id in roles if isinstance(roles, dict) else {}:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", role_id):
            issues.append(f"adapter manifest: unsafe role id {role_id!r}")
            continue
        try:
            role_issues = validate_proposal(output / "roles" / role_id)
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            role_issues = [f"proposal validation failed ({type(error).__name__})"]
        issues.extend(f"roles/{role_id}: {issue}" for issue in role_issues)
    return issues
