"""Native deterministic admission and post-model validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .catalog import ResourceCatalog
from .models import (
    AdmissionContext,
    AdmissionSnapshot,
    CandidateSelection,
    ControlEffect,
    ControlRef,
    DeterministicReason,
    ExposurePolicy,
    ExposureReceipt,
    FactPredicate,
    LifecycleState,
    PredicateOperator,
    ReasonCode,
    ResourceDecision,
    ResourceRecord,
    RuleDecision,
    SelectionDecision,
    ValidationResult,
)


_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


@dataclass(frozen=True)
class _RuleState:
    resource_id: str
    rule_id: str
    effect: ControlEffect
    authority: int
    condition_active: bool
    suppressed_by: ControlRef | None = None
    unresolved: tuple[ControlRef, ...] = ()


def _version(value: str) -> tuple[int, ...] | None:
    return tuple(int(part) for part in value.split(".")) if _VERSION.fullmatch(value) else None


def predicate_matches(predicate: FactPredicate, context: AdmissionContext) -> bool:
    """Evaluate a declared predicate against authoritative facts, never task text."""

    actual = tuple(context.facts.get(predicate.key, ()))
    expected = predicate.values
    if predicate.operator == PredicateOperator.EQUALS:
        return len(actual) == 1 and actual[0] == expected[0]
    if predicate.operator == PredicateOperator.ONE_OF:
        return len(actual) == 1 and actual[0] in expected
    if predicate.operator == PredicateOperator.CONTAINS_ALL:
        return set(expected).issubset(actual)
    if predicate.operator == PredicateOperator.INTERSECTS:
        return bool(set(expected).intersection(actual))
    if len(actual) != 1:
        return False
    current = _version(actual[0])
    minimum = _version(expected[0])
    return current is not None and minimum is not None and current >= minimum


def _path_applies(prefix: str, paths: tuple[str, ...]) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for path in paths)


def _base_reasons(resource: ResourceRecord, context: AdmissionContext) -> list[DeterministicReason]:
    reasons: list[DeterministicReason] = []
    lifecycle = resource.admission.lifecycle
    if lifecycle.state == LifecycleState.REVOKED:
        reasons.append(DeterministicReason(ReasonCode.REVOKED))
    elif lifecycle.state != LifecycleState.APPROVED:
        reasons.append(DeterministicReason(ReasonCode.NOT_APPROVED, actual=(lifecycle.state.value,)))
    if lifecycle.revoked_at is not None and context.effective_at >= lifecycle.revoked_at:
        reasons.append(DeterministicReason(ReasonCode.REVOKED))
    if lifecycle.effective_at is not None and context.effective_at < lifecycle.effective_at:
        reasons.append(DeterministicReason(ReasonCode.NOT_EFFECTIVE, expected=(lifecycle.effective_at.isoformat(),)))
    if lifecycle.expires_at is not None and context.effective_at >= lifecycle.expires_at:
        reasons.append(DeterministicReason(ReasonCode.EXPIRED, expected=(lifecycle.expires_at.isoformat(),)))

    scope = resource.admission.scope
    if scope.organization is not None and scope.organization != context.organization:
        reasons.append(DeterministicReason(ReasonCode.SCOPE_ORGANIZATION, expected=(scope.organization,), actual=(context.organization,)))
    if scope.team is not None and scope.team != context.team:
        reasons.append(DeterministicReason(ReasonCode.SCOPE_TEAM, expected=(scope.team,), actual=(context.team,)))
    if scope.repository is not None and scope.repository != context.repository:
        reasons.append(DeterministicReason(ReasonCode.SCOPE_REPOSITORY, expected=(scope.repository,), actual=(context.repository,)))
    if scope.path is not None and not _path_applies(scope.path, context.affected_paths):
        reasons.append(DeterministicReason(ReasonCode.SCOPE_PATH, expected=(scope.path,), actual=context.affected_paths))

    for predicate in resource.admission.compatibility:
        actual = tuple(context.facts.get(predicate.key, ()))
        if not actual:
            reasons.append(DeterministicReason(ReasonCode.COMPATIBILITY_UNKNOWN, fact_key=predicate.key, expected=predicate.values))
        elif not predicate_matches(predicate, context):
            reasons.append(
                DeterministicReason(
                    ReasonCode.COMPATIBILITY_MISMATCH,
                    fact_key=predicate.key,
                    expected=predicate.values,
                    actual=actual,
                )
            )
    for dependency in resource.admission.dependencies:
        if not predicate_matches(dependency.predicate, context):
            reasons.append(
                DeterministicReason(
                    ReasonCode.DEPENDENCY_UNSATISFIED,
                    related_rule_id=dependency.name,
                    fact_key=dependency.predicate.key,
                    expected=dependency.predicate.values,
                    actual=tuple(context.facts.get(dependency.predicate.key, ())),
                )
            )
    return list(dict.fromkeys(reasons))


def _resolve_rules(catalog: ResourceCatalog, context: AdmissionContext) -> tuple[tuple[RuleDecision, ...], tuple[DeterministicReason, ...]]:
    rule_map: dict[tuple[str, str], _RuleState] = {}
    conflict_pairs: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    for resource in catalog.resources:
        for rule in resource.admission.control_rules:
            key = (resource.content.id, rule.id)
            rule_map[key] = _RuleState(
                resource.content.id,
                rule.id,
                rule.effect,
                rule.authority,
                all(predicate_matches(predicate, context) for predicate in rule.when),
            )
            for reference in rule.conflicts_with:
                conflict_pairs.add(tuple(sorted((key, (reference.resource_id, reference.rule_id)))))

    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {key: set() for key in rule_map}
    for left_key, right_key in conflict_pairs:
        adjacency[left_key].add(right_key)
        adjacency[right_key].add(left_key)

    mutable = dict(rule_map)
    global_reasons: list[DeterministicReason] = []
    # Resolve explicit higher authority first. Equal-authority conflicts only
    # block when neither clause has already lost to a higher authority.
    for key, state in sorted(rule_map.items()):
        if not state.condition_active:
            continue
        higher = sorted(
            (
                other_key for other_key in adjacency[key]
                if rule_map[other_key].condition_active and rule_map[other_key].authority > state.authority
            ),
            key=lambda other_key: (-rule_map[other_key].authority, other_key),
        )
        if higher:
            winner = higher[0]
            mutable[key] = replace(state, suppressed_by=ControlRef(*winner))
            global_reasons.append(
                DeterministicReason(
                    ReasonCode.PRECEDENCE_LOST,
                    related_resource_id=state.resource_id,
                    related_rule_id=state.rule_id,
                    expected=winner,
                )
            )

    for left_key, right_key in sorted(conflict_pairs):
        left = mutable[left_key]
        right = mutable[right_key]
        if (
            not left.condition_active
            or not right.condition_active
            or left.suppressed_by is not None
            or right.suppressed_by is not None
            or left.authority != right.authority
        ):
            continue
        else:
            left_ref = ControlRef(*left_key)
            right_ref = ControlRef(*right_key)
            mutable[left_key] = replace(left, unresolved=tuple(dict.fromkeys((*left.unresolved, right_ref))))
            mutable[right_key] = replace(right, unresolved=tuple(dict.fromkeys((*right.unresolved, left_ref))))
            global_reasons.append(
                DeterministicReason(
                    ReasonCode.UNRESOLVED_CONFLICT,
                    related_resource_id=left.resource_id,
                    related_rule_id=left.rule_id,
                    expected=(right.resource_id, right.rule_id),
                )
            )

    decisions = tuple(
        RuleDecision(
            state.resource_id,
            state.rule_id,
            state.effect,
            state.authority,
            state.condition_active,
            state.suppressed_by,
            state.unresolved,
        )
        for _key, state in sorted(mutable.items())
    )
    return decisions, tuple(dict.fromkeys(global_reasons))


def admit(context: AdmissionContext, catalog: ResourceCatalog) -> AdmissionSnapshot:
    """Determine final eligibility and the separately governed exposable universe."""

    catalog = catalog.validated()
    reasons = {resource.content.id: _base_reasons(resource, context) for resource in catalog.resources}
    rule_decisions, global_reasons = _resolve_rules(catalog, context)

    for rule in rule_decisions:
        if not rule.active or rule.suppressed_by is not None or rule.unresolved_conflict_with:
            continue
        if rule.effect == ControlEffect.FORBIDDEN:
            reasons[rule.resource_id].append(
                DeterministicReason(ReasonCode.FORBIDDEN_CONTROL, related_resource_id=rule.resource_id, related_rule_id=rule.rule_id)
            )

    for successor in catalog.resources:
        if reasons[successor.content.id]:
            continue
        for predecessor_id in successor.admission.supersedes:
            reasons[predecessor_id].append(
                DeterministicReason(ReasonCode.SUPERSEDED, related_resource_id=successor.content.id)
            )

    mandatory_ids = tuple(
        dict.fromkeys(
            rule.resource_id
            for rule in rule_decisions
            if rule.active
            and rule.effect == ControlEffect.MANDATORY
            and rule.suppressed_by is None
            and not rule.unresolved_conflict_with
        )
    )
    snapshot_reasons = list(global_reasons)
    for resource_id in mandatory_ids:
        if reasons[resource_id]:
            snapshot_reasons.append(
                DeterministicReason(
                    ReasonCode.MANDATORY_RESOURCE_INADMISSIBLE,
                    related_resource_id=resource_id,
                )
            )

    decisions: list[ResourceDecision] = []
    exposable = []
    for resource in catalog.resources:
        resource_reasons = tuple(dict.fromkeys(reasons[resource.content.id]))
        final_eligible = not resource_reasons
        exposure_allowed = (
            resource.admission.exposure_policy == ExposurePolicy.ALLOW_WHEN_INADMISSIBLE
            or final_eligible
        )
        decisions.append(
            ResourceDecision(
                resource.content.identity,
                final_eligible,
                exposure_allowed,
                resource.admission.selectable,
                resource_reasons,
            )
        )
        if exposure_allowed:
            exposable.append(resource.content)

    blocked = any(reason.code in {ReasonCode.UNRESOLVED_CONFLICT, ReasonCode.MANDATORY_RESOURCE_INADMISSIBLE} for reason in snapshot_reasons)
    return AdmissionSnapshot(
        context,
        catalog.revision,
        catalog.sha256(),
        tuple(decisions),
        rule_decisions,
        tuple(exposable),
        mandatory_ids,
        tuple(dict.fromkeys(snapshot_reasons)),
        blocked,
    )


def validate(
    selections: tuple[CandidateSelection, ...],
    exposure: ExposureReceipt,
    context: AdmissionContext,
    current_catalog: ResourceCatalog,
) -> ValidationResult:
    """Validate raw semantic choices against authoritative current state."""

    if context != exposure.context:
        raise ValueError("validation context must exactly match the exposure context")
    current_catalog = current_catalog.validated()
    current = admit(context, current_catalog)
    records = current_catalog.by_id()
    decisions_by_id = {decision.identity.resource_id: decision for decision in current.decisions}
    exposed_by_id = {identity.resource_id: identity for identity in exposure.resources}
    selection_decisions: list[SelectionDecision] = []
    accepted: list[str] = []
    seen: set[str] = set()

    for index, selection in enumerate(selections):
        reasons: list[DeterministicReason] = []
        record = records.get(selection.resource_id)
        decision = decisions_by_id.get(selection.resource_id)
        exposed_identity = exposed_by_id.get(selection.resource_id)
        if record is None or decision is None:
            reasons.append(DeterministicReason(ReasonCode.UNKNOWN_RESOURCE))
        if exposed_identity is None:
            reasons.append(DeterministicReason(ReasonCode.NOT_EXPOSED))
        if record is not None and exposed_identity is not None and record.content.identity != exposed_identity:
            reasons.append(
                DeterministicReason(
                    ReasonCode.RESOURCE_CHANGED,
                    expected=(exposed_identity.revision, exposed_identity.payload_sha256),
                    actual=(record.content.revision, record.content.payload_sha256),
                )
            )
        if decision is not None:
            reasons.extend(decision.reasons)
            if not decision.selectable:
                reasons.append(DeterministicReason(ReasonCode.NOT_SELECTABLE))
        if selection.resource_id in seen:
            reasons.append(DeterministicReason(ReasonCode.DUPLICATE_SELECTION))
        seen.add(selection.resource_id)
        unique = tuple(dict.fromkeys(reasons))
        admitted = not unique
        selection_decisions.append(SelectionDecision(index, selection.resource_id, admitted, unique))
        if admitted:
            accepted.append(selection.resource_id)

    added_mandatory = tuple(resource_id for resource_id in current.mandatory_resource_ids if resource_id not in accepted)
    final_ids = tuple(dict.fromkeys((*accepted, *current.mandatory_resource_ids)))
    blocked = current.blocked
    if blocked:
        final_ids = ()
    final_resources = tuple(records[resource_id].content.identity for resource_id in final_ids)
    return ValidationResult(
        exposure,
        context,
        current_catalog.revision,
        current_catalog.sha256(),
        selections,
        tuple(selection_decisions),
        current.rule_decisions,
        added_mandatory,
        final_resources,
        current.reasons,
        blocked,
    )
