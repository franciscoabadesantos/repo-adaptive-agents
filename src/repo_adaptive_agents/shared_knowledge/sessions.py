"""Private persistence for exact native exposure receipts between CLI calls."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import repo_adaptive_agents.admission_control as native

from .catalog import KnowledgeStore, SharedKnowledgeError


EXPOSURE_ID = re.compile(r"^exp-[0-9a-f]{24}$")


@dataclass(frozen=True)
class ExposureSession:
    id: str
    receipt: native.ExposureReceipt
    task_id: str | None


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SharedKnowledgeError(f"stored exposure has invalid {field}")
    return value


def _timestamp(value: object, field: str) -> datetime:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise SharedKnowledgeError(f"stored exposure has invalid {field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SharedKnowledgeError(f"stored exposure has invalid {field}")
    return parsed.astimezone(timezone.utc)


class ExposureSessions:
    def __init__(self, store: KnowledgeStore) -> None:
        self.directory = store.runtime_directory() / "exposures"

    def save(self, receipt: native.ExposureReceipt, *, task_id: str | None = None) -> ExposureSession:
        exposure_id = f"exp-{uuid.uuid4().hex[:24]}"
        effective_task_id = task_id or exposure_id
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        data = {
            "schema_version": 1,
            "exposure_id": exposure_id,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "task_id": effective_task_id,
            "context": receipt.context.model_facing_data(),
            "catalog_revision": receipt.catalog_revision,
            "catalog_sha256": receipt.catalog_sha256,
            "resources": [
                {
                    "id": identity.resource_id,
                    "revision": identity.revision,
                    "payload_sha256": identity.payload_sha256,
                }
                for identity in receipt.resources
            ],
        }
        path = self.directory / f"{exposure_id}.json"
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
        except Exception:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            raise
        return ExposureSession(exposure_id, receipt, effective_task_id)

    def load(self, exposure_id: str) -> ExposureSession:
        if not EXPOSURE_ID.fullmatch(exposure_id):
            raise SharedKnowledgeError(f"invalid exposure ID: {exposure_id}")
        path = self.directory / f"{exposure_id}.json"
        if path.is_symlink() or not path.is_file():
            raise SharedKnowledgeError(f"knowledge exposure not found: {exposure_id}; run 'team-knowledge index --json' again")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SharedKnowledgeError(f"cannot read stored knowledge exposure {exposure_id}: {error}") from error
        if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("exposure_id") != exposure_id:
            raise SharedKnowledgeError(f"stored knowledge exposure is invalid: {exposure_id}")
        context_data = data.get("context")
        resources_data = data.get("resources")
        if not isinstance(context_data, dict) or not isinstance(resources_data, list):
            raise SharedKnowledgeError(f"stored knowledge exposure is invalid: {exposure_id}")
        facts_data = context_data.get("facts", {})
        affected_paths = context_data.get("affected_paths", [])
        if (
            not isinstance(facts_data, dict)
            or any(
                not isinstance(key, str)
                or not isinstance(value, list)
                or any(not isinstance(item, str) for item in value)
                for key, value in facts_data.items()
            )
            or not isinstance(affected_paths, list)
            or any(not isinstance(item, str) for item in affected_paths)
        ):
            raise SharedKnowledgeError(f"stored knowledge exposure is invalid: {exposure_id}")
        try:
            context = native.AdmissionContext(
                organization=_text(context_data.get("organization"), "context organization"),
                team=_text(context_data.get("team"), "context team"),
                repository=_text(context_data.get("repository"), "context repository"),
                affected_paths=tuple(affected_paths),
                effective_at=_timestamp(context_data.get("effective_at"), "context effective_at"),
                facts={str(key): tuple(value) for key, value in facts_data.items()},
            )
            resources = tuple(
                native.ResourceIdentity(
                    _text(item.get("id"), "resource id"),
                    _text(item.get("revision"), "resource revision"),
                    _text(item.get("payload_sha256"), "resource payload_sha256"),
                )
                for item in resources_data
                if isinstance(item, dict)
            )
        except (TypeError, ValueError) as error:
            raise SharedKnowledgeError(f"stored knowledge exposure is invalid: {exposure_id}") from error
        if len(resources) != len(resources_data):
            raise SharedKnowledgeError(f"stored knowledge exposure is invalid: {exposure_id}")
        receipt = native.ExposureReceipt(
            context,
            _text(data.get("catalog_revision"), "catalog_revision"),
            _text(data.get("catalog_sha256"), "catalog_sha256"),
            resources,
        )
        task_id = data.get("task_id")
        if task_id is not None and not isinstance(task_id, str):
            raise SharedKnowledgeError(f"stored knowledge exposure is invalid: {exposure_id}")
        return ExposureSession(exposure_id, receipt, task_id)
