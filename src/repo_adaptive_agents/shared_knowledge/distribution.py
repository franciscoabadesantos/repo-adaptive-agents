"""Plan-then-apply cross-repository canonical Skill distribution."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import repo_adaptive_agents.admission_control as native

from repo_adaptive_agents.shared_knowledge.catalog import (
    SharedKnowledgeError,
    find_repository,
    repository_identity,
)

from .canonical import CanonicalCatalog, CanonicalSkill, directory_digest, load_canonical_catalog
from .consumer import (
    CONFIG_FILE,
    LOCK_FILE,
    STATE_DIR,
    ConsumerConfig,
    ConsumerLock,
    ConsumerSource,
    LockedResource,
    _atomic_text,
    assert_bootstrap_available,
    ensure_consumer_layout,
    git_exclude_path,
    load_consumer_config,
    load_consumer_lock,
    managed_exclude_content,
    validate_catalog_path,
    validate_source_url,
    write_json_atomic,
)
from .evidence import RepositoryKnowledgeEvidence, collect_skill_bootstrap_evidence
from .selector import (
    SelectorUnavailable,
    SkillRoutingEntry,
    SkillSelection,
    SkillSelector,
)
from .source import GitKnowledgeSource, SourceUnavailable


@dataclass(frozen=True)
class DistributionAction:
    action: str
    id: str
    name: str
    materialized_path: str
    previous_revision: str | None
    revision: str | None


@dataclass(frozen=True)
class DistributionPlan:
    operation: str
    root: Path
    source_id: str
    source_commit: str
    repository_id: str
    actions: tuple[DistributionAction, ...]
    possibly_no_longer_relevant: tuple[str, ...]
    rejected_ids: tuple[str, ...]
    selection_reasons: tuple[tuple[str, str | None], ...]
    semantic_pending: bool
    offline: bool
    config: ConsumerConfig
    lock: ConsumerLock
    desired_skills: tuple[CanonicalSkill, ...]
    previous_lock: ConsumerLock | None


def _native_catalog(catalog: CanonicalCatalog) -> native.ResourceCatalog:
    records = []
    for skill in catalog.skills:
        content = native.build_content(
            skill.id,
            skill.revision,
            native.ResourceKind.AGENT_SKILL,
            skill.name,
            skill.description,
            skill.skill_text,
            native.SkillPayload(("codex",), f"{skill.source_path}/SKILL.md"),
        )
        records.append(
            native.ResourceRecord(
                content,
                native.AdmissionEnvelope(
                    lifecycle=native.Lifecycle(
                        native.LifecycleState.APPROVED
                        if skill.state == "active"
                        else native.LifecycleState.REVOKED
                    ),
                    scope=native.Scope(
                        organization=catalog.descriptor.organization,
                        team=catalog.descriptor.team,
                    ),
                    compatibility=(),
                    dependencies=(),
                    exposure_policy=native.ExposurePolicy.REQUIRE_ADMISSIBLE,
                    selectable=True,
                ),
            )
        )
    return native.ResourceCatalog(catalog.source_commit, tuple(records)).validated()


def _context(catalog: CanonicalCatalog, repository_id: str, now: datetime | None = None) -> native.AdmissionContext:
    return native.AdmissionContext(
        organization=catalog.descriptor.organization,
        team=catalog.descriptor.team,
        repository=repository_id,
        affected_paths=(),
        effective_at=now or datetime.now(timezone.utc),
        facts={},
    )


def _read_catalog(
    source: GitKnowledgeSource,
    commit: str,
    catalog_path: str,
) -> CanonicalCatalog:
    with source.snapshot(commit, catalog_path=catalog_path) as snapshot:
        return load_canonical_catalog(
            snapshot,
            commit,
            lambda path: source.revision_for(
                commit,
                path,
                catalog_path=catalog_path,
            ),
        )


def _select(
    selector: SkillSelector,
    evidence: RepositoryKnowledgeEvidence,
    snapshot: native.AdmissionSnapshot,
) -> tuple[SkillSelection, native.ExposureReceipt]:
    exposed = snapshot.exposable_resources
    receipt = snapshot.record_exposure(exposed)
    routing = tuple(
        SkillRoutingEntry(resource.id, resource.title, resource.summary) for resource in exposed
    )
    return selector.select(evidence, routing), receipt


def _validate(
    ids: tuple[str, ...],
    receipt: native.ExposureReceipt,
    context: native.AdmissionContext,
    catalog: native.ResourceCatalog,
) -> native.ValidationResult:
    return native.validate(
        tuple(native.CandidateSelection(resource_id) for resource_id in ids),
        receipt,
        context,
        catalog,
    )


def _locked(
    skill: CanonicalSkill,
    evidence_sha256: str,
    *,
    source_id: str,
    source_url: str,
    source_ref: str,
    source_catalog_path: str,
    source_commit: str,
) -> LockedResource:
    return LockedResource(
        source_id,
        source_url,
        source_ref,
        source_commit,
        skill.id,
        skill.name,
        skill.source_path,
        skill.revision,
        skill.digest_sha256,
        skill.materialized_path,
        evidence_sha256,
        source_catalog_path,
    )


def _assert_safe_destination(root: Path, relative: str) -> Path:
    target = root / relative
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise SharedKnowledgeError(f"refusing to manage Agent Skill through symlink: {current}")
    return target


def _preflight(plan: DistributionPlan, *, require_present: bool = False) -> None:
    old_by_path = {
        resource.materialized_path: resource
        for resource in (() if plan.previous_lock is None else plan.previous_lock.resources)
    }
    desired_paths = {skill.materialized_path for skill in plan.desired_skills}
    for path, previous in old_by_path.items():
        target = _assert_safe_destination(plan.root, path)
        if not target.exists():
            if require_present:
                raise SharedKnowledgeError(f"locked managed Agent Skill is missing: {path}")
            continue
        if directory_digest(target) != previous.digest_sha256:
            raise SharedKnowledgeError(
                f"locally modified managed Agent Skill will not be overwritten or removed: {path}"
            )
    for path in desired_paths - set(old_by_path):
        target = _assert_safe_destination(plan.root, path)
        if target.exists() or target.is_symlink():
            raise SharedKnowledgeError(
                f"refusing to overwrite unmanaged existing Agent Skill: {path}"
            )


def _actions(
    root: Path,
    old: ConsumerLock | None,
    desired: tuple[CanonicalSkill, ...],
) -> tuple[DistributionAction, ...]:
    old_by_id = {item.id: item for item in (() if old is None else old.resources)}
    desired_by_id = {item.id: item for item in desired}
    actions: list[DistributionAction] = []
    for resource_id in sorted(set(old_by_id) - set(desired_by_id)):
        item = old_by_id[resource_id]
        actions.append(DistributionAction("remove", item.id, item.name, item.materialized_path, item.revision, None))
    for skill in desired:
        previous = old_by_id.get(skill.id)
        if previous is None:
            action = "add"
        elif not (root / skill.materialized_path).is_dir():
            action = "restore"
        elif (
            previous.revision != skill.revision
            or previous.digest_sha256 != skill.digest_sha256
            or previous.materialized_path != skill.materialized_path
        ):
            action = "update"
        else:
            action = "keep"
        actions.append(
            DistributionAction(
                action,
                skill.id,
                skill.name,
                skill.materialized_path,
                previous.revision if previous else None,
                skill.revision,
            )
        )
    return tuple(actions)


class TeamKnowledgeDistributionService:
    def __init__(self, selector: SkillSelector) -> None:
        self.selector = selector

    def bootstrap_plan(
        self,
        repository: str | Path,
        *,
        source: ConsumerSource | None = None,
        source_url: str | None = None,
        ref: str = "main",
    ) -> DistributionPlan:
        root = find_repository(repository)
        assert_bootstrap_available(root)
        if source is not None and source_url is not None:
            raise SharedKnowledgeError("provide either a source specification or source_url, not both")
        if source is None:
            if source_url is None:
                raise SharedKnowledgeError("a canonical team knowledge source is required")
            source = ConsumerSource(source_url, ref, ".")
        if source.type != "git":
            raise SharedKnowledgeError("consumer source type must be git")
        source_url = validate_source_url(source.url)
        ref = source.ref.strip()
        catalog_path = validate_catalog_path(source.catalog_path)
        if not ref or ref.startswith("-"):
            raise SharedKnowledgeError("source ref must be a non-empty Git ref")
        source_spec = ConsumerSource(source_url, ref, catalog_path)
        ensure_consumer_layout(root)
        git_source = GitKnowledgeSource(root)
        commit = git_source.acquire(source_url, ref, catalog_path=catalog_path)
        canonical = _read_catalog(git_source, commit, catalog_path)
        repository_id = repository_identity(root)
        evidence = collect_skill_bootstrap_evidence(root, repository_id)
        catalog = _native_catalog(canonical)
        context = _context(canonical, repository_id)
        snapshot = native.admit(context, catalog)
        selection, receipt = _select(self.selector, evidence, snapshot)
        selected_ids = tuple(item.id for item in selection.selected)
        validation = _validate(selected_ids, receipt, context, catalog)
        accepted = set(validation.final_resource_ids)
        desired = tuple(skill for skill in canonical.skills if skill.id in accepted)
        rejected = tuple(
            decision.resource_id for decision in validation.selection_decisions if not decision.admitted
        )
        config = ConsumerConfig(repository_id, source_spec)
        lock = ConsumerLock(
            canonical.descriptor.source_id,
            source_url,
            ref,
            commit,
            repository_id,
            evidence.sha256,
            commit,
            evidence.sha256,
            tuple(
                _locked(
                    skill,
                    evidence.sha256,
                    source_id=canonical.descriptor.source_id,
                    source_url=source_url,
                    source_ref=ref,
                    source_catalog_path=catalog_path,
                    source_commit=commit,
                )
                for skill in desired
            ),
            catalog_path,
        )
        plan = DistributionPlan(
            "bootstrap",
            root,
            canonical.descriptor.source_id,
            commit,
            repository_id,
            _actions(root, None, desired),
            (),
            rejected,
            tuple((item.id, item.reason) for item in selection.selected),
            False,
            False,
            config,
            lock,
            desired,
            None,
        )
        _preflight(plan)
        return plan

    def sync_plan(self, repository: str | Path, *, offline: bool = False) -> DistributionPlan:
        root = find_repository(repository)
        config = load_consumer_config(root)
        previous = load_consumer_lock(root)
        if (
            config.repository != previous.repository_id
            or config.source.url != previous.source_url
            or config.source.ref != previous.source_ref
            or config.source.catalog_path != previous.catalog_path
        ):
            raise SharedKnowledgeError("consumer config and lock disagree")
        if repository_identity(root) != config.repository:
            raise SharedKnowledgeError("current Git repository identity does not match team knowledge config")
        source = GitKnowledgeSource(root)
        try:
            commit = source.acquire(
                config.source.url,
                config.source.ref,
                catalog_path=config.source.catalog_path,
                offline=offline,
                commit=previous.resolved_commit,
            )
        except SourceUnavailable as error:
            raise SourceUnavailable(
                f"{error}. Current locked Skills remain available from {previous.resolved_commit}; no local state was changed"
            ) from error
        canonical = _read_catalog(source, commit, config.source.catalog_path)
        if canonical.descriptor.source_id != previous.source_id:
            raise SharedKnowledgeError("canonical source_id changed; current local state was left unchanged")
        current_by_id = canonical.by_id()
        missing = sorted({item.id for item in previous.resources} - set(current_by_id))
        if missing:
            raise SharedKnowledgeError(
                f"canonical source no longer contains locked Skill {missing[0]!r} without explicit revocation; current local state was left unchanged"
            )
        repository_id = config.repository
        evidence = collect_skill_bootstrap_evidence(
            root,
            repository_id,
            excluded_paths=(
                ".team-knowledge",
                *(resource.materialized_path for resource in previous.resources),
            ),
        )
        catalog = _native_catalog(canonical)
        context = _context(canonical, repository_id)
        snapshot = native.admit(context, catalog)
        decisions = {decision.identity.resource_id: decision for decision in snapshot.decisions}
        revoked = {
            resource.id
            for resource in previous.resources
            if native.ReasonCode.REVOKED in {reason.code for reason in decisions[resource.id].reasons}
        }
        active_previous = tuple(resource for resource in previous.resources if resource.id not in revoked)
        for resource in active_previous:
            decision = decisions[resource.id]
            if not decision.final_eligible:
                raise SharedKnowledgeError(
                    f"locked Skill {resource.id!r} is no longer admissible without explicit revocation; current local state was left unchanged"
                )
        if offline:
            desired = tuple(current_by_id[item.id] for item in active_previous)
            lock = previous
            plan = DistributionPlan(
                "sync",
                root,
                previous.source_id,
                previous.resolved_commit,
                repository_id,
                _actions(root, previous, desired),
                (),
                (),
                (),
                previous.evaluated_source_commit != previous.resolved_commit
                or evidence.sha256 != previous.evaluated_evidence_sha256,
                True,
                config,
                lock,
                desired,
                previous,
            )
            _preflight(plan, require_present=True)
            return plan

        old_canonical = _read_catalog(
            source,
            previous.evaluated_source_commit,
            config.source.catalog_path,
        )
        old_by_id = old_canonical.by_id()
        new_active = {
            skill.id
            for skill in canonical.skills
            if skill.state == "active"
            and (skill.id not in old_by_id or old_by_id[skill.id].state != "active")
        }
        routing_changed = any(
            skill.id in old_by_id
            and skill.state == "active"
            and old_by_id[skill.id].state == "active"
            and (skill.name, skill.description)
            != (old_by_id[skill.id].name, old_by_id[skill.id].description)
            for skill in canonical.skills
        )
        assessment_required = bool(
            new_active
            or routing_changed
            or evidence.sha256 != previous.evaluated_evidence_sha256
            or previous.evaluated_source_commit != previous.resolved_commit
        )
        receipt = snapshot.record_exposure(snapshot.exposable_resources)
        semantic_pending = False
        selection: SkillSelection | None = None
        if assessment_required:
            routing = tuple(
                SkillRoutingEntry(resource.id, resource.title, resource.summary)
                for resource in snapshot.exposable_resources
            )
            try:
                selection = self.selector.select(evidence, routing)
            except SelectorUnavailable:
                semantic_pending = True
        selected_ids = tuple(item.id for item in selection.selected) if selection else ()
        existing_ids = tuple(resource.id for resource in active_previous)
        validation_ids = tuple(dict.fromkeys((*existing_ids, *selected_ids)))
        validation = _validate(validation_ids, receipt, context, catalog)
        accepted = set(validation.final_resource_ids)
        rejected = tuple(
            decision.resource_id for decision in validation.selection_decisions if not decision.admitted
        )
        rejected_existing = sorted(set(existing_ids).intersection(rejected))
        if rejected_existing:
            raise SharedKnowledgeError(
                f"native validation rejected locked Skill {rejected_existing[0]!r}; current local state was left unchanged"
            )
        desired_ids = set(existing_ids)
        desired_ids.update(resource_id for resource_id in selected_ids if resource_id in accepted)
        desired = tuple(skill for skill in canonical.skills if skill.id in desired_ids)
        possibly = (
            tuple(sorted(set(existing_ids) - set(selected_ids))) if selection is not None else ()
        )
        evaluated_commit = previous.evaluated_source_commit if semantic_pending else commit
        evaluated_evidence = previous.evaluated_evidence_sha256 if semantic_pending else evidence.sha256
        lock = ConsumerLock(
            previous.source_id,
            config.source.url,
            config.source.ref,
            commit,
            repository_id,
            evidence.sha256,
            evaluated_commit,
            evaluated_evidence,
            tuple(
                _locked(
                    skill,
                    evidence.sha256,
                    source_id=previous.source_id,
                    source_url=config.source.url,
                    source_ref=config.source.ref,
                    source_catalog_path=config.source.catalog_path,
                    source_commit=commit,
                )
                for skill in desired
            ),
            config.source.catalog_path,
        )
        plan = DistributionPlan(
            "sync",
            root,
            previous.source_id,
            commit,
            repository_id,
            _actions(root, previous, desired),
            possibly,
            rejected,
            tuple((item.id, item.reason) for item in selection.selected) if selection else (),
            semantic_pending,
            False,
            config,
            lock,
            desired,
            previous,
        )
        _preflight(plan)
        return plan

    def apply(self, plan: DistributionPlan) -> None:
        if plan.previous_lock is None:
            assert_bootstrap_available(plan.root)
        else:
            if load_consumer_config(plan.root) != plan.config or load_consumer_lock(plan.root) != plan.previous_lock:
                raise SharedKnowledgeError(
                    "consumer config or lock changed after planning; rerun team-knowledge sync"
                )
        _preflight(plan, require_present=plan.offline)
        if plan.offline:
            return
        root = plan.root
        state = root / STATE_DIR
        transaction = state / "runtime" / "transactions" / uuid.uuid4().hex
        staged = transaction / "staged"
        backups = transaction / "backups"
        staged.mkdir(parents=True)
        backups.mkdir(parents=True)
        old_by_id = {
            item.id: item for item in (() if plan.previous_lock is None else plan.previous_lock.resources)
        }
        desired_by_id = {item.id: item for item in plan.desired_skills}
        actions = {item.id: item.action for item in plan.actions}
        for skill in plan.desired_skills:
            if actions[skill.id] == "keep" and (root / skill.materialized_path).is_dir():
                continue
            destination = staged / skill.name
            destination.mkdir(parents=True)
            for relative, content in skill.files:
                path = destination / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            if directory_digest(destination) != skill.digest_sha256:
                raise SharedKnowledgeError(f"staged Agent Skill digest mismatch: {skill.id}")

        config_path = state / CONFIG_FILE
        lock_path = state / LOCK_FILE
        exclude_path = git_exclude_path(root)
        originals = {
            path: path.read_bytes() if path.exists() else None
            for path in (config_path, lock_path, exclude_path)
        }
        moved: dict[str, Path] = {}
        installed: list[Path] = []
        try:
            for resource_id, previous in old_by_id.items():
                desired = desired_by_id.get(resource_id)
                replace = (
                    desired is None
                    or desired.materialized_path != previous.materialized_path
                    or actions[resource_id] in {"update", "restore"}
                )
                target = root / previous.materialized_path
                if replace and target.exists():
                    backup = backups / resource_id
                    os.replace(target, backup)
                    moved[previous.materialized_path] = backup
            for skill in plan.desired_skills:
                destination = root / skill.materialized_path
                if actions[skill.id] == "keep" and destination.is_dir():
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged / skill.name, destination)
                installed.append(destination)
            existing_exclude = originals[exclude_path].decode("utf-8") if originals[exclude_path] is not None else ""
            exclude_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_text(
                exclude_path,
                managed_exclude_content(
                    existing_exclude,
                    tuple(skill.materialized_path for skill in plan.desired_skills),
                ),
            )
            write_json_atomic(config_path, plan.config.to_data())
            write_json_atomic(lock_path, plan.lock.to_data())
        except Exception:
            for destination in reversed(installed):
                if destination.exists():
                    shutil.rmtree(destination)
            for relative, backup in moved.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if backup.exists():
                    os.replace(backup, target)
            for path, content in originals.items():
                if content is None:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(content)
                    os.replace(temporary, path)
            raise
        finally:
            shutil.rmtree(transaction, ignore_errors=True)
