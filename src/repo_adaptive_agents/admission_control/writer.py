"""Atomic audit-trail persistence for an admission-control run."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from .catalog import ResourceCatalog
from .models import AdmissionRun, to_data


class AuditWriteError(ValueError):
    pass


def _json(value) -> str:
    return json.dumps(to_data(value), indent=2, sort_keys=True) + "\n"


def write_audit_bundle(
    run: AdmissionRun,
    pre_catalog: ResourceCatalog,
    output_dir: str | Path,
    *,
    post_catalog: ResourceCatalog | None = None,
) -> tuple[Path, ...]:
    output = Path(output_dir).expanduser().resolve()
    if output.exists() or output.is_symlink():
        raise AuditWriteError(f"output already exists; refusing to overwrite: {output}")
    pre_catalog = pre_catalog.validated()
    current_catalog = (post_catalog or pre_catalog).validated()
    if pre_catalog.sha256() != run.pre_catalog_sha256 or current_catalog.sha256() != run.post_catalog_sha256:
        raise AuditWriteError("catalogs do not match the admission run digests")
    current = current_catalog.by_id()
    final_records = [current[resource_id] for resource_id in run.final_exposure_ids]
    rendered = {
        "catalog_snapshot.json": _json({
            "pre": {"sha256": pre_catalog.sha256(), "catalog": pre_catalog.canonical_data()},
            "post": {"sha256": current_catalog.sha256(), "catalog": current_catalog.canonical_data()},
        }),
        "resolution_context.json": _json(run.context),
        "prefilter_decisions.json": _json(run.prefilter_decisions),
        "exposed_resources.json": _json({
            "selectable": run.exposed_selectable_resources,
            "mandatory_controls": run.exposed_mandatory_controls,
        }),
        "raw_model_selections.json": _json(run.raw_model_selections),
        "post_validation_decisions.json": _json({
            "decisions": run.post_validation_decisions,
            "violations": run.violations,
            "blocked": run.blocked,
        }),
        "mandatory_controls.json": _json(run.mandatory_control_ids),
        "final_exposure_set.json": _json({
            "selected_ids": run.final_selected_ids,
            "mandatory_control_ids": run.mandatory_control_ids,
            "final_exposure_ids": run.final_exposure_ids,
            "resources": final_records,
        }),
    }
    manifest = {
        "schema_version": 1,
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
