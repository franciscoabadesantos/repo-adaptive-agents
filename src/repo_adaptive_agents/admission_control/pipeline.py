"""Guarded semantic-selection pipeline with post-model enforcement."""

from __future__ import annotations

from typing import Protocol

from .admission import evaluate_admission
from .catalog import ResourceCatalog
from .models import AdmissionDecision, AdmissionRun, CandidateSelection, ResolutionContext, ResourceRecord


class SemanticSelector(Protocol):
    def __call__(
        self,
        context: ResolutionContext,
        selectable_resources: tuple[ResourceRecord, ...],
        mandatory_controls: tuple[ResourceRecord, ...],
    ) -> tuple[CandidateSelection, ...]: ...


def run_guarded_selection(
    pre_catalog: ResourceCatalog,
    context: ResolutionContext,
    selector: SemanticSelector,
    *,
    post_catalog: ResourceCatalog | None = None,
) -> AdmissionRun:
    pre_catalog = pre_catalog.validated()
    post_catalog = post_catalog.validated() if post_catalog is not None else None
    pre = evaluate_admission(pre_catalog, context, stage="prefilter")
    if pre.blocked:
        return AdmissionRun(
            1, context, pre_catalog.sha256(), (post_catalog or pre_catalog).sha256(),
            pre.decisions, (), (), (), (), (), (), (), pre.violations, True,
        )

    raw = tuple(selector(context, pre.selectable, pre.mandatory))
    current_catalog = post_catalog or pre_catalog
    post = evaluate_admission(current_catalog, context, stage="post_validation")
    post_decisions_by_id = {item.resource_id: item for item in post.decisions}
    current_records = current_catalog.by_id()
    exposed_ids = {resource.id for resource in pre.selectable}
    accepted: list[str] = []
    seen: set[str] = set()
    validation: list[AdmissionDecision] = []
    violations = list(pre.violations) + list(post.violations)

    for selection in raw:
        reasons: list[str] = []
        current = post_decisions_by_id.get(selection.resource_id)
        resource = current_records.get(selection.resource_id)
        if current is None or resource is None:
            reasons.append("unknown_resource")
        else:
            if not current.admitted:
                reasons.extend(current.reasons)
            if resource.governance.disposition != "selectable":
                reasons.append(f"not_selectable:{resource.governance.disposition}")
            if selection.resource_id not in exposed_ids:
                reasons.append("not_exposed_to_model")
        if selection.resource_id in seen:
            reasons.append("duplicate_selection")
        if reasons:
            unique = tuple(dict.fromkeys(reasons))
            validation.append(AdmissionDecision(selection.resource_id, "post_validation", False, unique))
            violations.append(f"rejected_model_selection:{selection.resource_id}:{'|'.join(unique)}")
        else:
            seen.add(selection.resource_id)
            accepted.append(selection.resource_id)
            validation.append(AdmissionDecision(selection.resource_id, "post_validation", True, ("admitted",)))

    pre_mandatory_ids = tuple(resource.id for resource in pre.mandatory)
    mandatory_ids = tuple(resource.id for resource in post.mandatory)
    if mandatory_ids != pre_mandatory_ids:
        violations.append(
            "mandatory_controls_changed_after_model:"
            f"pre={','.join(pre_mandatory_ids)}:post={','.join(mandatory_ids)}"
        )
    blocked = post.blocked or mandatory_ids != pre_mandatory_ids
    final_selected = () if blocked else tuple(accepted)
    final_exposure = () if blocked else tuple(dict.fromkeys((*mandatory_ids, *final_selected)))
    return AdmissionRun(
        1,
        context,
        pre_catalog.sha256(),
        current_catalog.sha256(),
        pre.decisions,
        pre.selectable,
        pre.mandatory,
        raw,
        tuple(validation),
        mandatory_ids,
        final_selected,
        final_exposure,
        tuple(violations),
        blocked,
    )
