"""Write a portable, reversible repository-infrastructure proposal."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from .models import InfrastructurePlan, RepoProfile, to_jsonable


class ProposalError(ValueError):
    """Raised when a proposal cannot be created without risking existing files."""


def _validate_rendered(path: Path, content: str) -> None:
    try:
        json.loads(content)
    except json.JSONDecodeError as error:
        raise ProposalError(
            f"Generated file is invalid: {path.name} ({type(error).__name__})"
        ) from error


def write_proposal(
    profile: RepoProfile,
    plan: InfrastructurePlan,
    output_dir: str | Path,
    *,
    provider_discovery: dict[str, object] | None = None,
) -> list[Path]:
    """Write only portable facts and recommendations.

    Harness adapters are rendered separately through the explicit multi-CLI commands.
    The core proposal never chooses a model, concurrency, sandbox, or execution order.
    """
    repo_root = Path(profile.path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if output == repo_root:
        raise ProposalError("Proposal output cannot be the analyzed repository root")
    if output.is_relative_to(repo_root):
        raise ProposalError("Proposal output cannot be inside the analyzed repository")
    if output.exists() or output.is_symlink():
        raise ProposalError(f"Proposal output already exists; refusing to overwrite: {output}")

    rendered = {
        "profile.json": json.dumps(to_jsonable(profile), indent=2, sort_keys=True) + "\n",
        "infrastructure-plan.json": json.dumps(to_jsonable(plan), indent=2, sort_keys=True) + "\n",
    }
    if provider_discovery is not None:
        rendered["provider-discovery.json"] = (
            json.dumps(to_jsonable(provider_discovery), indent=2, sort_keys=True) + "\n"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        for relative, content in rendered.items():
            path = temporary / relative
            _validate_rendered(path, content)
            path.write_text(content, encoding="utf-8")
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return [output / relative for relative in rendered]
