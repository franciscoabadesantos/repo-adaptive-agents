"""Atomic audit persistence for native admission and validation results."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .catalog import ResourceCatalog
from .models import AdmissionSnapshot, ExposureReceipt, ValidationResult, to_data


class AuditWriteError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(to_data(value), indent=2, sort_keys=True) + "\n"


def write_audit_bundle(
    snapshot: AdmissionSnapshot,
    exposure: ExposureReceipt,
    result: ValidationResult,
    admission_catalog: ResourceCatalog,
    current_catalog: ResourceCatalog,
    output_dir: str | Path,
) -> tuple[Path, ...]:
    requested_output = Path(output_dir).expanduser()
    if requested_output.exists() or requested_output.is_symlink():
        raise AuditWriteError(f"output already exists; refusing to overwrite: {requested_output}")
    output = requested_output.resolve()
    if output.exists():
        raise AuditWriteError(f"output already exists; refusing to overwrite: {output}")
    admission_catalog = admission_catalog.validated()
    current_catalog = current_catalog.validated()
    if snapshot.catalog_sha256 != admission_catalog.sha256():
        raise AuditWriteError("admission catalog does not match snapshot")
    if result.current_catalog_sha256 != current_catalog.sha256() or result.exposure != exposure:
        raise AuditWriteError("current catalog or exposure does not match validation result")

    rendered = {
        "admission_context.json": _json(snapshot.context.model_facing_data()),
        "catalog_snapshots.json": _json({
            "admission": {"revision": admission_catalog.revision, "sha256": admission_catalog.sha256(), "catalog": admission_catalog.canonical_data()},
            "current": {"revision": current_catalog.revision, "sha256": current_catalog.sha256(), "catalog": current_catalog.canonical_data()},
        }),
        "admission_decisions.json": _json({"resources": snapshot.decisions, "rules": snapshot.rule_decisions, "reasons": snapshot.reasons, "blocked": snapshot.blocked}),
        "exposable_content.json": _json(snapshot.exposable_resources),
        "actual_exposure_receipt.json": _json(exposure),
        "raw_selections.json": _json(result.raw_selections),
        "validation_result.json": _json(result),
    }
    manifest = {
        "schema_version": 2,
        "files": [
            {"path": name, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
            for name, content in sorted(rendered.items())
        ],
    }
    rendered["manifest.json"] = _json(manifest)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        for name, content in rendered.items():
            json.loads(content)
            (temporary / name).write_text(content, encoding="utf-8")
        os.replace(temporary, output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return tuple(output / name for name in sorted(rendered))
