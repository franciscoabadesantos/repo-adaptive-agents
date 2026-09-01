"""Minimal local event log for the one-team pilot."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EVENT_TYPES = frozenset(
    {
        "contribution_created",
        "contribution_available",
        "item_exposed",
        "item_selected",
        "validation_accepted",
        "validation_rejected",
        "item_body_returned",
        "item_cited",
        "feedback_recorded",
    }
)
FEEDBACK_VALUES = frozenset({"useful", "outdated", "incorrect"})


class EventError(ValueError):
    pass


class EventLog:
    def __init__(self, path: Path, repository: str) -> None:
        self.path = path
        self.repository = repository

    def actor_id(self, identity: str) -> str:
        """Return a stable repository-scoped pseudonym without storing Git identity."""

        normalized = identity.strip().casefold()
        if not normalized:
            raise EventError("actor identity must be non-empty")
        digest = hashlib.sha256(f"{self.repository}\0{normalized}".encode("utf-8")).hexdigest()
        return f"actor-{digest[:16]}"

    def append(
        self,
        event_type: str,
        item_id: str,
        *,
        revision: str | None,
        actor: str,
        task_id: str | None = None,
        outcome: str | None = None,
        feedback: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        if event_type not in EVENT_TYPES:
            raise EventError(f"unsupported event type: {event_type}")
        if feedback is not None and feedback not in FEEDBACK_VALUES:
            raise EventError("feedback must be useful, outdated, or incorrect")
        if not item_id.strip() or not actor.strip():
            raise EventError("events require item_id and actor")
        timestamp = occurred_at or datetime.now(timezone.utc)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise EventError("event timestamp must be timezone-aware")
        event: dict[str, Any] = {
            "schema_version": 2,
            "event": event_type,
            "occurred_at": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "repository": self.repository,
            "item_id": item_id,
            "revision": revision,
            "actor": self.actor_id(actor),
        }
        if task_id:
            event["task_id"] = task_id
        if outcome:
            event["outcome"] = outcome
        if feedback:
            event["feedback"] = feedback
        encoded = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)
