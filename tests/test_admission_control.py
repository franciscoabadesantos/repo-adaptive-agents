"""Development regressions for the native admission boundary; not blind evidence."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

import repo_adaptive_agents.admission_control as native
from repo_adaptive_agents.admission_control.writer import AuditWriteError, write_audit_bundle


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _predicate(key: str, value: str, operator=native.PredicateOperator.EQUALS):
    return native.FactPredicate(key, operator, (value,))


def _context(
    *, organization="example-org", team="payments", repository="service",
    paths=("src/payment.py",), effective_at=NOW, facts=None,
):
    return native.AdmissionContext(
        organization, team, repository, paths, effective_at,
        facts or {"runtime": ("python",), "python_version": ("3.12",)},
    )


def _payload(kind):
    if kind == native.ResourceKind.AGENT_SKILL:
        return native.SkillPayload(("codex",), "SKILL.md")
    if kind == native.ResourceKind.REPOSITORY_INSTRUCTION:
        return native.RepositoryInstructionPayload("AGENTS.md")
    if kind in {native.ResourceKind.MCP_TOOL, native.ResourceKind.MCP_RESOURCE}:
        return native.MCPPayload("tools", "read", ("repository:read",))
    if kind == native.ResourceKind.ORGANIZATIONAL_POLICY:
        return native.PolicyPayload("change-control")
    return native.EnvironmentContractPayload("runtime")


def _resource(
    resource_id, *, revision="1", kind=native.ResourceKind.AGENT_SKILL,
    state=native.LifecycleState.APPROVED, effective_at=None, expires_at=None,
    revoked_at=None, scope=None, compatibility=(), dependencies=(),
    exposure_policy=native.ExposurePolicy.ALLOW_WHEN_INADMISSIBLE,
    selectable=True, supersedes=(), rules=(), body=None,
):
    content = native.build_content(
        resource_id, revision, kind, resource_id.replace("-", " ").title(),
        f"Summary for {resource_id}", body or f"Body for {resource_id}", _payload(kind),
    )
    return native.ResourceRecord(
        content,
        native.AdmissionEnvelope(
            native.Lifecycle(state, effective_at, expires_at, revoked_at),
            scope or native.Scope(organization="example-org"), compatibility,
            dependencies, exposure_policy, selectable, supersedes, rules,
        ),
    )


def _catalog(*resources, revision="catalog-1"):
    return native.ResourceCatalog(revision, resources).validated()


def _reason_codes(snapshot, resource_id):
    decision = next(item for item in snapshot.decisions if item.identity.resource_id == resource_id)
    return {reason.code for reason in decision.reasons}


def _select(*resource_ids):
    return tuple(native.CandidateSelection(item, "external semantic judgment", 0.8) for item in resource_ids)


class TestLifecycleScopeAndApplicability:
    def test_approved_current_resource_is_eligible_and_exposable(self):
        snapshot = native.admit(_context(), _catalog(_resource("current")))
        assert snapshot.decisions[0].final_eligible
        assert snapshot.decisions[0].exposure_allowed
        assert tuple(item.id for item in snapshot.exposable_resources) == ("current",)

    def test_expired_and_revoked_resources_are_rejected(self):
        snapshot = native.admit(_context(), _catalog(
            _resource("expired", expires_at=NOW),
            _resource("revoked-state", state=native.LifecycleState.REVOKED),
            _resource("revoked-time", revoked_at=NOW),
        ))
        assert native.ReasonCode.EXPIRED in _reason_codes(snapshot, "expired")
        assert native.ReasonCode.REVOKED in _reason_codes(snapshot, "revoked-state")
        assert native.ReasonCode.REVOKED in _reason_codes(snapshot, "revoked-time")

    def test_activation_is_inclusive_and_expiry_is_exclusive(self):
        active = _resource("boundary", effective_at=NOW, expires_at=NOW.replace(hour=13))
        assert native.admit(_context(), _catalog(active)).decisions[0].final_eligible
        before = native.admit(_context(effective_at=NOW.replace(hour=11)), _catalog(active))
        at_expiry = native.admit(_context(effective_at=NOW.replace(hour=13)), _catalog(active))
        assert native.ReasonCode.NOT_EFFECTIVE in _reason_codes(before, "boundary")
        assert native.ReasonCode.EXPIRED in _reason_codes(at_expiry, "boundary")

    @pytest.mark.parametrize(("scope", "reason"), [
        (native.Scope(organization="other"), native.ReasonCode.SCOPE_ORGANIZATION),
        (native.Scope(organization="example-org", team="other"), native.ReasonCode.SCOPE_TEAM),
        (native.Scope(organization="example-org", repository="other"), native.ReasonCode.SCOPE_REPOSITORY),
        (native.Scope(organization="example-org", path="db"), native.ReasonCode.SCOPE_PATH),
    ])
    def test_each_scope_dimension_is_enforced(self, scope, reason):
        snapshot = native.admit(_context(), _catalog(_resource("scoped", scope=scope)))
        assert reason in _reason_codes(snapshot, "scoped")

    def test_paths_normalize_safely_and_cannot_escape_repository_root(self):
        context = _context(paths=("src/./billing/../payment.py",))
        assert context.affected_paths == ("src/payment.py",)
        scoped = _resource("scoped", scope=native.Scope(organization="example-org", path="src/./billing/.."))
        assert native.admit(context, _catalog(scoped)).decisions[0].final_eligible
        with pytest.raises(ValueError, match="escape"):
            _context(paths=("../outside",))
        with pytest.raises(ValueError, match="escape"):
            native.Scope(path="src/../../outside")

    def test_compatibility_unknown_mismatch_and_dependency_are_typed(self):
        resource = _resource(
            "constrained",
            compatibility=(_predicate("runtime", "python"), _predicate("region", "eu")),
            dependencies=(native.Dependency("database", _predicate("service", "postgres")),),
        )
        snapshot = native.admit(
            _context(facts={"runtime": ("node",), "service": ("mysql",)}), _catalog(resource),
        )
        codes = _reason_codes(snapshot, "constrained")
        assert native.ReasonCode.COMPATIBILITY_MISMATCH in codes
        assert native.ReasonCode.COMPATIBILITY_UNKNOWN in codes
        assert native.ReasonCode.DEPENDENCY_UNSATISFIED in codes

    def test_effective_timestamp_is_required_and_serialized_exactly(self):
        with pytest.raises(ValueError, match="timezone-aware"):
            _context(effective_at=datetime(2026, 9, 1, 12, 0))
        context = _context(effective_at=datetime.fromisoformat("2026-09-01T13:00:00+01:00"))
        assert context.effective_at == NOW
        assert context.model_facing_data()["effective_at"] == "2026-09-01T12:00:00Z"
        with pytest.raises(TypeError):
            context.facts["runtime"] = ("node",)


class TestExposureAndValidation:
    def test_sensitive_invalid_is_absent_but_ordinary_invalid_may_be_visible(self):
        sensitive = _resource(
            "sensitive", state=native.LifecycleState.DRAFT,
            exposure_policy=native.ExposurePolicy.REQUIRE_ADMISSIBLE,
        )
        ordinary = _resource("ordinary", state=native.LifecycleState.DRAFT)
        catalog = _catalog(sensitive, ordinary)
        snapshot = native.admit(_context(), catalog)
        assert tuple(item.id for item in snapshot.exposable_resources) == ("ordinary",)
        receipt = snapshot.record_exposure(snapshot.exposable_resources)
        result = native.validate(_select("ordinary"), receipt, _context(), catalog)
        assert result.final_resource_ids == ()
        assert native.ReasonCode.NOT_APPROVED in {r.code for r in result.selection_decisions[0].reasons}

    def test_receipt_rejects_outside_duplicate_and_altered_content(self):
        resource = _resource("shown")
        snapshot = native.admit(_context(), _catalog(resource))
        with pytest.raises(native.ExposureError, match="outside"):
            snapshot.record_exposure((_resource("outside").content,))
        with pytest.raises(native.ExposureError, match="unique"):
            snapshot.record_exposure((resource.content, resource.content))
        with pytest.raises(native.ExposureError, match="differed"):
            snapshot.record_exposure((replace(resource.content, title="Different title"),))

    def test_unknown_unexposed_and_duplicate_model_ids_are_rejected(self):
        first, second = _resource("first"), _resource("second")
        catalog = _catalog(first, second)
        receipt = native.admit(_context(), catalog).record_exposure((first.content,))
        result = native.validate(_select("unknown", "second", "first", "first"), receipt, _context(), catalog)
        codes = [{r.code for r in decision.reasons} for decision in result.selection_decisions]
        assert {native.ReasonCode.UNKNOWN_RESOURCE, native.ReasonCode.NOT_EXPOSED}.issubset(codes[0])
        assert native.ReasonCode.NOT_EXPOSED in codes[1]
        assert codes[2] == set()
        assert native.ReasonCode.DUPLICATE_SELECTION in codes[3]
        assert result.final_resource_ids == ("first",)

    def test_revision_or_payload_change_after_exposure_is_rejected(self):
        original = _resource("changing")
        receipt = native.admit(_context(), _catalog(original)).record_exposure((original.content,))
        changed = _resource("changing", body="Changed visible body")
        result = native.validate(_select("changing"), receipt, _context(), _catalog(changed, revision="catalog-2"))
        assert result.final_resource_ids == ()
        assert native.ReasonCode.RESOURCE_CHANGED in {r.code for r in result.selection_decisions[0].reasons}

    def test_validation_cannot_substitute_a_different_time_or_context(self):
        resource = _resource("resource")
        catalog = _catalog(resource)
        receipt = native.admit(_context(), catalog).record_exposure((resource.content,))
        with pytest.raises(ValueError, match="exactly match"):
            native.validate(
                _select("resource"), receipt,
                _context(effective_at=NOW.replace(hour=13)), catalog,
            )

    def test_revocation_after_model_exposure_removes_selection(self):
        original = _resource("incident")
        receipt = native.admit(_context(), _catalog(original)).record_exposure((original.content,))
        revoked = replace(original, admission=replace(
            original.admission, lifecycle=native.Lifecycle(native.LifecycleState.REVOKED),
        ))
        result = native.validate(_select("incident"), receipt, _context(), _catalog(revoked, revision="catalog-2"))
        assert result.final_resource_ids == ()
        assert native.ReasonCode.REVOKED in {r.code for r in result.selection_decisions[0].reasons}

    def test_nonselectable_content_can_be_visible_but_not_model_selected(self):
        resource = _resource("binding-text", selectable=False)
        catalog = _catalog(resource)
        receipt = native.admit(_context(), catalog).record_exposure((resource.content,))
        result = native.validate(_select("binding-text"), receipt, _context(), catalog)
        assert native.ReasonCode.NOT_SELECTABLE in {r.code for r in result.selection_decisions[0].reasons}


class TestControlsSupersessionAndRaces:
    def test_unconditional_and_conditional_mandatory_controls_are_injected(self):
        unconditional = _resource(
            "global-policy", kind=native.ResourceKind.ORGANIZATIONAL_POLICY, selectable=False,
            rules=(native.ControlRule("always", native.ControlEffect.MANDATORY, (), 100),),
        )
        conditional = _resource(
            "production-policy", kind=native.ResourceKind.ORGANIZATIONAL_POLICY, selectable=False,
            rules=(native.ControlRule(
                "production", native.ControlEffect.MANDATORY,
                (_predicate("environment", "production"),), 100,
            ),),
        )
        skill = _resource("skill")
        catalog = _catalog(unconditional, conditional, skill)
        context = _context(facts={"environment": ("production",)})
        receipt = native.admit(context, catalog).record_exposure((skill.content,))
        result = native.validate(_select("skill"), receipt, context, catalog)
        assert result.added_mandatory_ids == ("global-policy", "production-policy")
        assert result.final_resource_ids == ("skill", "global-policy", "production-policy")

    def test_forbidden_control_rejects_final_selection(self):
        forbidden = _resource(
            "prohibited-tool",
            rules=(native.ControlRule("prohibit", native.ControlEffect.FORBIDDEN, (), 100),),
        )
        catalog = _catalog(forbidden)
        receipt = native.admit(_context(), catalog).record_exposure((forbidden.content,))
        result = native.validate(_select("prohibited-tool"), receipt, _context(), catalog)
        assert native.ReasonCode.FORBIDDEN_CONTROL in {r.code for r in result.selection_decisions[0].reasons}
        assert result.final_resource_ids == ()

    def test_conditional_forbidden_control_uses_declared_facts_only(self):
        resource = _resource(
            "conditional-tool",
            rules=(native.ControlRule(
                "production-prohibit", native.ControlEffect.FORBIDDEN,
                (_predicate("environment", "production"),), 100,
            ),),
        )
        catalog = _catalog(resource)
        development = native.admit(_context(facts={"environment": ("development",)}), catalog)
        production = native.admit(_context(facts={"environment": ("production",)}), catalog)
        assert development.decisions[0].final_eligible
        assert native.ReasonCode.FORBIDDEN_CONTROL in _reason_codes(production, "conditional-tool")

    def test_eligible_successor_supersedes_predecessor(self):
        snapshot = native.admit(_context(), _catalog(_resource("old"), _resource("new", supersedes=("old",))))
        assert native.ReasonCode.SUPERSEDED in _reason_codes(snapshot, "old")
        assert next(d for d in snapshot.decisions if d.identity.resource_id == "new").final_eligible

    def test_equal_authority_binding_conflict_blocks(self):
        left = _resource(
            "left", kind=native.ResourceKind.ORGANIZATIONAL_POLICY,
            rules=(native.ControlRule(
                "clause", native.ControlEffect.MANDATORY, (), 50,
                (native.ControlRef("right", "clause"),),
            ),),
        )
        right = _resource(
            "right", kind=native.ResourceKind.ORGANIZATIONAL_POLICY,
            rules=(native.ControlRule(
                "clause", native.ControlEffect.MANDATORY, (), 50,
                (native.ControlRef("left", "clause"),),
            ),),
        )
        snapshot = native.admit(_context(), _catalog(left, right))
        assert snapshot.blocked
        assert native.ReasonCode.UNRESOLVED_CONFLICT in {r.code for r in snapshot.reasons}

    def test_higher_authority_clause_resolves_conflict(self):
        broad = _resource(
            "broad", kind=native.ResourceKind.ORGANIZATIONAL_POLICY,
            rules=(native.ControlRule(
                "clause", native.ControlEffect.MANDATORY, (), 50,
                (native.ControlRef("narrow", "clause"),),
            ),),
        )
        narrow = _resource(
            "narrow", kind=native.ResourceKind.REPOSITORY_INSTRUCTION,
            rules=(native.ControlRule(
                "clause", native.ControlEffect.MANDATORY, (), 80,
                (native.ControlRef("broad", "clause"),),
            ),),
        )
        snapshot = native.admit(_context(), _catalog(broad, narrow))
        assert not snapshot.blocked
        assert snapshot.mandatory_resource_ids == ("narrow",)
        broad_rule = next(rule for rule in snapshot.rule_decisions if rule.resource_id == "broad")
        assert broad_rule.suppressed_by == native.ControlRef("narrow", "clause")

    def test_broader_and_narrower_nonconflicting_controls_supplement(self):
        broad = _resource(
            "broad", kind=native.ResourceKind.ORGANIZATIONAL_POLICY,
            rules=(native.ControlRule("global", native.ControlEffect.MANDATORY, (), 50),),
        )
        narrow = _resource(
            "narrow", kind=native.ResourceKind.REPOSITORY_INSTRUCTION,
            scope=native.Scope(organization="example-org", repository="service"),
            rules=(native.ControlRule("repository", native.ControlEffect.MANDATORY, (), 80),),
        )
        snapshot = native.admit(_context(), _catalog(broad, narrow))
        assert snapshot.mandatory_resource_ids == ("broad", "narrow")
        assert not snapshot.blocked

    def test_new_mandatory_control_after_model_is_injected_without_blanket_failure(self):
        skill = _resource("skill")
        receipt = native.admit(_context(), _catalog(skill)).record_exposure((skill.content,))
        policy = _resource(
            "new-policy", kind=native.ResourceKind.ORGANIZATIONAL_POLICY, selectable=False,
            rules=(native.ControlRule("new", native.ControlEffect.MANDATORY, (), 100),),
        )
        result = native.validate(
            _select("skill"), receipt, _context(), _catalog(skill, policy, revision="catalog-2"),
        )
        assert not result.blocked
        assert result.added_mandatory_ids == ("new-policy",)
        assert result.final_resource_ids == ("skill", "new-policy")

    def test_new_inadmissible_mandatory_control_blocks(self):
        skill = _resource("skill")
        receipt = native.admit(_context(), _catalog(skill)).record_exposure((skill.content,))
        policy = _resource(
            "bad-policy", kind=native.ResourceKind.ORGANIZATIONAL_POLICY,
            state=native.LifecycleState.DRAFT, selectable=False,
            rules=(native.ControlRule("new", native.ControlEffect.MANDATORY, (), 100),),
        )
        result = native.validate(
            _select("skill"), receipt, _context(), _catalog(skill, policy, revision="catalog-2"),
        )
        assert result.blocked
        assert result.final_resource_ids == ()
        assert native.ReasonCode.MANDATORY_RESOURCE_INADMISSIBLE in {r.code for r in result.reasons}


class TestCatalogTypesAndAudit:
    @pytest.mark.parametrize("kind", list(native.ResourceKind))
    def test_type_specific_payloads_remain_distinct(self, kind):
        resource = _resource(f"resource-{kind.value}", kind=kind)
        assert _catalog(resource).resources[0].content.kind == kind
        if kind != native.ResourceKind.ORGANIZATIONAL_POLICY:
            wrong = replace(resource, content=replace(resource.content, payload=native.PolicyPayload("wrong")))
            with pytest.raises(native.CatalogError, match="payload does not match"):
                native.ResourceCatalog("bad", (wrong,)).validated()

    def test_policies_and_instructions_can_be_selectable_without_becoming_same_type(self):
        policy = _resource("policy", kind=native.ResourceKind.ORGANIZATIONAL_POLICY)
        instruction = _resource("instruction", kind=native.ResourceKind.REPOSITORY_INSTRUCTION)
        catalog = _catalog(policy, instruction)
        snapshot = native.admit(_context(), catalog)
        receipt = snapshot.record_exposure(snapshot.exposable_resources)
        result = native.validate(_select("policy", "instruction"), receipt, _context(), catalog)
        assert result.final_resource_ids == ("policy", "instruction")
        assert type(policy.content.payload) is not type(instruction.content.payload)

    def test_catalog_digest_is_order_independent_and_supersession_cycles_fail(self):
        first, second = _resource("first"), _resource("second")
        assert _catalog(first, second).sha256() == _catalog(second, first).sha256()
        left = _resource("left", supersedes=("right",))
        right = _resource("right", supersedes=("left",))
        with pytest.raises(native.CatalogError, match="cycle"):
            native.ResourceCatalog("bad", (left, right)).validated()

    def test_audit_writer_is_atomic_and_no_overwrite(self, tmp_path):
        resource = _resource("resource")
        catalog = _catalog(resource)
        snapshot = native.admit(_context(), catalog)
        receipt = snapshot.record_exposure((resource.content,))
        result = native.validate(_select("resource"), receipt, _context(), catalog)
        output = tmp_path / "audit"
        paths = write_audit_bundle(snapshot, receipt, result, catalog, catalog, output)
        assert {p.name for p in paths} >= {"manifest.json", "actual_exposure_receipt.json", "validation_result.json"}
        with pytest.raises(AuditWriteError, match="refusing to overwrite"):
            write_audit_bundle(snapshot, receipt, result, catalog, catalog, output)
