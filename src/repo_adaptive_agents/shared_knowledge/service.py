"""Product-facing shared-knowledge service over the native admission boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import repo_adaptive_agents.admission_control as native

from .catalog import KnowledgeStore
from .events import FEEDBACK_VALUES
from .sessions import ExposureSession, ExposureSessions


@dataclass(frozen=True)
class KnowledgeIndexEntry:
    id: str
    revision: str
    title: str
    summary: str


@dataclass(frozen=True)
class KnowledgeExposure:
    id: str
    index: tuple[KnowledgeIndexEntry, ...]
    receipt: native.ExposureReceipt
    context: native.AdmissionContext
    task_id: str | None


@dataclass(frozen=True)
class ValidatedKnowledge:
    id: str
    revision: str
    title: str
    body: str


@dataclass(frozen=True)
class KnowledgeResolution:
    items: tuple[ValidatedKnowledge, ...]
    citations: tuple[str, ...]
    binding_additions: tuple[str, ...]
    validation: native.ValidationResult


@dataclass(frozen=True)
class KnowledgeCheck:
    total: int
    active: int
    revoked: int
    exposable: int


class SharedKnowledgeService:
    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    @classmethod
    def open(cls, path: str | Path = ".") -> "SharedKnowledgeService":
        return cls(KnowledgeStore.open(path))

    def _context(
        self,
        *,
        effective_at: datetime | None = None,
        affected_paths: tuple[str, ...] = (),
    ) -> native.AdmissionContext:
        return native.AdmissionContext(
            organization=self.store.config.organization,
            team=self.store.config.team,
            repository=self.store.config.repository,
            affected_paths=affected_paths,
            effective_at=effective_at or datetime.now(timezone.utc),
            facts={},
        )

    def check(self, *, effective_at: datetime | None = None) -> KnowledgeCheck:
        catalog, items = self.store.native_catalog()
        snapshot = native.admit(self._context(effective_at=effective_at), catalog)
        return KnowledgeCheck(
            total=len(items),
            active=sum(item.state == "active" for item in items),
            revoked=sum(item.state == "revoked" for item in items),
            exposable=len(snapshot.exposable_resources),
        )

    def expose_index(
        self,
        *,
        actor: str | None = None,
        task_id: str | None = None,
        effective_at: datetime | None = None,
        affected_paths: tuple[str, ...] = (),
    ) -> KnowledgeExposure:
        catalog, _items = self.store.native_catalog()
        context = self._context(effective_at=effective_at, affected_paths=affected_paths)
        snapshot = native.admit(context, catalog)
        receipt = snapshot.record_exposure(snapshot.exposable_resources)
        index = tuple(
            KnowledgeIndexEntry(resource.id, resource.revision, resource.title, resource.summary)
            for resource in snapshot.exposable_resources
        )
        session = ExposureSessions(self.store).save(receipt, task_id=task_id)
        event_actor = actor or self.store.current_identity()
        for entry in index:
            self.store.events.append(
                "item_exposed",
                entry.id,
                revision=entry.revision,
                actor=event_actor,
                task_id=session.task_id,
            )
        return KnowledgeExposure(session.id, index, receipt, context, session.task_id)

    def load_exposure(self, exposure_id: str) -> ExposureSession:
        return ExposureSessions(self.store).load(exposure_id)

    def validate_ids(
        self,
        exposure: KnowledgeExposure | ExposureSession,
        selected_ids: tuple[str, ...],
        *,
        actor: str | None = None,
        task_id: str | None = None,
    ) -> KnowledgeResolution:
        current_catalog, current_items = self.store.native_catalog()
        selections = tuple(native.CandidateSelection(item_id) for item_id in selected_ids)
        event_actor = actor or self.store.current_identity()
        event_task_id = task_id or exposure.task_id
        exposed_revisions = {
            identity.resource_id: identity.revision for identity in exposure.receipt.resources
        }
        for item_id in selected_ids:
            self.store.events.append(
                "item_selected",
                item_id,
                revision=exposed_revisions.get(item_id),
                actor=event_actor,
                task_id=event_task_id,
            )
        result = native.validate(
            selections,
            exposure.receipt,
            exposure.receipt.context,
            current_catalog,
        )
        accepted = set(result.final_resource_ids)
        for decision in result.selection_decisions:
            self.store.events.append(
                "validation_accepted" if decision.admitted else "validation_rejected",
                decision.resource_id,
                revision=exposed_revisions.get(decision.resource_id),
                actor=event_actor,
                task_id=event_task_id,
                outcome="accepted" if decision.admitted else "rejected",
            )
        items_by_id = {item.id: item for item in current_items}
        resolved = tuple(
            ValidatedKnowledge(
                item_id,
                str(items_by_id[item_id].revision),
                items_by_id[item_id].title,
                items_by_id[item_id].body,
            )
            for item_id in result.final_resource_ids
            if item_id in accepted
        )
        for item in resolved:
            self.store.events.append(
                "item_body_returned",
                item.id,
                revision=item.revision,
                actor=event_actor,
                task_id=event_task_id,
            )
        return KnowledgeResolution(
            items=resolved,
            citations=tuple(item.title for item in resolved),
            binding_additions=result.added_mandatory_ids,
            validation=result,
        )

    def record_feedback(
        self,
        item_id: str,
        feedback: str,
        *,
        actor: str | None = None,
        task_id: str | None = None,
    ) -> None:
        if feedback not in FEEDBACK_VALUES:
            raise ValueError("feedback must be useful, outdated, or incorrect")
        item = self.store.get(item_id)
        self.store.events.append(
            "feedback_recorded",
            item.id,
            revision=str(item.revision),
            actor=actor or self.store.current_identity(),
            task_id=task_id,
            feedback=feedback,
        )
