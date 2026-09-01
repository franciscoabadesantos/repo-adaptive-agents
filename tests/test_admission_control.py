"""Non-blind development/regression tests for the narrower guardrail thesis."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from repo_adaptive_agents.admission_control.admission import evaluate_admission
from repo_adaptive_agents.admission_control.catalog import (
    CatalogError,
    ResourceCatalog,
    content_sha256,
    parse_catalog,
)
from repo_adaptive_agents.admission_control.models import (
    CandidateSelection,
    CompatibilityConstraint,
    EnvironmentContractSemantics,
    Governance,
    Lifecycle,
    MCPSemantics,
    PolicySemantics,
    RepositoryInstructionSemantics,
    ResolutionContext,
    ResourceRecord,
    Scope,
    SkillSemantics,
)
from repo_adaptive_agents.admission_control.pipeline import run_guarded_selection
from repo_adaptive_agents.admission_control.writer import AuditWriteError, write_audit_bundle


ROOT = Path(__file__).parents[1]


def _semantics(kind: str):
    if kind == "agent_skill":
        return SkillSemantics(("codex",), "SKILL.md")
    if kind == "repository_instruction":
        return RepositoryInstructionSemantics("AGENTS.md")
    if kind in {"mcp_tool", "mcp_resource"}:
        return MCPSemantics("company-tools", "lookup", ("read",), True)
    if kind == "organizational_policy":
        return PolicySemantics("engineering-change")
    return EnvironmentContractSemantics("runtime")


def _resource(
    resource_id: str,
    *,
    kind: str = "agent_skill",
    disposition: str = "selectable",
    approval: str = "approved",
    effective_from: str | None = None,
    expires_at: str | None = None,
    revoked_at: str | None = None,
    scope: Scope = Scope(organization="acme"),
    compatibility: tuple[CompatibilityConstraint, ...] = (),
    authority: int = 10,
    supersedes: tuple[str, ...] = (),
    conflicts_with: tuple[str, ...] = (),
    body: str | None = None,
) -> ResourceRecord:
    content = body or f"Knowledge body for {resource_id}."
    return ResourceRecord(
        resource_id,
        kind,  # type: ignore[arg-type]
        resource_id,
        f"Summary for {resource_id}",
        content,
        f"test://{resource_id}",
        "1",
        content_sha256(content),
        Lifecycle(approval, effective_from, expires_at, revoked_at),
        scope,
        compatibility,
        Governance(disposition, authority, supersedes, conflicts_with),  # type: ignore[arg-type]
        _semantics(kind),
    )


def _catalog(*resources: ResourceRecord) -> ResourceCatalog:
    return ResourceCatalog(1, tuple(sorted(resources, key=lambda resource: resource.id)))


def _context(*, team: str = "checkout-experience", paths: tuple[str, ...] = ("src/payment.py",), compatibility=None, task="Change payment behavior"):
    return ResolutionContext(
        task,
        "acme",
        team,
        "checkout-web",
        paths,
        "2026-09-01",
        {"harness": "codex", "network": "allowed", "platform": "linux"} if compatibility is None else compatibility,
    )


class RevealedHoldoutRegressionTests(unittest.TestCase):
    """Known C03/C07/C26-style failures; development evidence only, never blind metrics."""

    def test_expired_unapproved_wrong_team_and_forbidden_resources_are_not_exposed(self):
        valid = _resource("valid-skill")
        expired = _resource("expired-relevant", expires_at="2025-01-01", body="Exact semantic match payment behavior")
        draft = _resource("draft-relevant", approval="draft", body="Exact semantic match payment behavior")
        wrong_team = _resource("wrong-team", scope=Scope(organization="acme", team="payments-core"), body="Exact semantic match payment behavior")
        forbidden = _resource("forbidden", disposition="forbidden", body="Exact semantic match payment behavior")
        observed: list[set[str]] = []

        def adversarial_selector(context, selectable, mandatory):
            del context, mandatory
            observed.append({item.id for item in selectable})
            # Simulates a hallucinated/out-of-band selection such as C07/K013.
            return tuple(CandidateSelection(item, "raw model choice", 0.9) for item in (
                "valid-skill", "expired-relevant", "draft-relevant", "wrong-team", "forbidden",
            ))

        run = run_guarded_selection(_catalog(valid, expired, draft, wrong_team, forbidden), _context(), adversarial_selector)
        self.assertEqual(observed, [{"valid-skill"}])
        self.assertEqual(run.final_selected_ids, ("valid-skill",))
        rejected = {item.resource_id: item.reasons for item in run.post_validation_decisions if not item.admitted}
        self.assertIn("expired_at:2025-01-01", rejected["expired-relevant"])
        self.assertIn("approval:draft", rejected["draft-relevant"])
        self.assertIn("scope:team", rejected["wrong-team"])
        self.assertIn("governance:forbidden", rejected["forbidden"])
        self.assertTrue(all("not_exposed_to_model" in reasons for reasons in rejected.values()))
        self.assertTrue(run.violations)

    def test_broader_policy_supplements_selected_repository_knowledge(self):
        policy = _resource("payments-policy", kind="organizational_policy", disposition="mandatory", authority=100)
        procedure = _resource("refund-procedure", scope=Scope(organization="acme", repository="checkout-web"))

        def selector(context, selectable, mandatory):
            del context
            self.assertEqual([item.id for item in mandatory], ["payments-policy"])
            self.assertEqual([item.id for item in selectable], ["refund-procedure"])
            return (CandidateSelection("refund-procedure", "semantically relevant", 0.95),)

        run = run_guarded_selection(_catalog(policy, procedure), _context(), selector)
        self.assertEqual(run.mandatory_control_ids, ("payments-policy",))
        self.assertEqual(run.final_selected_ids, ("refund-procedure",))
        self.assertEqual(run.final_exposure_ids, ("payments-policy", "refund-procedure"))

    def test_narrow_environment_exception_and_broader_procedure_accumulate(self):
        procedure = _resource("replay-procedure")
        exception = _resource(
            "dev-exception",
            kind="environment_contract",
            disposition="mandatory",
            scope=Scope(organization="acme", path="environments/dev"),
        )
        context = _context(paths=("environments/dev/replay.py",), task="Replay synthetic development data")
        run = run_guarded_selection(
            _catalog(procedure, exception),
            context,
            lambda _context, _selectable, _mandatory: (CandidateSelection("replay-procedure", "relevant", 0.9),),
        )
        self.assertEqual(run.final_exposure_ids, ("dev-exception", "replay-procedure"))

    def test_global_mandatory_policy_and_repository_knowledge_are_separate(self):
        global_policy = _resource("ci-policy", kind="organizational_policy", disposition="mandatory", authority=100)
        repository_skill = _resource("docs-validation", scope=Scope(organization="acme", repository="checkout-web"))
        run = run_guarded_selection(
            _catalog(global_policy, repository_skill),
            _context(task="Update an executable documentation example"),
            lambda _context, _selectable, _mandatory: (CandidateSelection("docs-validation", "relevant", 0.9),),
        )
        self.assertEqual(run.mandatory_control_ids, ("ci-policy",))
        self.assertEqual(run.final_selected_ids, ("docs-validation",))

    def test_zero_resource_and_ambiguous_tasks_are_not_forced_by_guardrail(self):
        skill = _resource("available-but-irrelevant")
        for task in ("Rename one response header", "Make sign-in safer"):
            with self.subTest(task=task):
                run = run_guarded_selection(
                    _catalog(skill),
                    _context(task=task),
                    lambda _context, _selectable, _mandatory: (),
                )
                self.assertEqual(run.final_exposure_ids, ())
                self.assertFalse(run.violations)


class LifecycleAndPrecedenceTests(unittest.TestCase):
    def test_explicit_compatibility_is_fail_closed(self):
        resource = _resource(
            "linux-only",
            compatibility=(CompatibilityConstraint("platform", ("linux",)),),
        )
        mismatched = evaluate_admission(_catalog(resource), _context(compatibility={"platform": "windows"}))
        unknown = evaluate_admission(_catalog(resource), _context(compatibility={}))
        self.assertIn("compatibility_mismatch:platform:windows", mismatched.decisions[0].reasons)
        self.assertIn("compatibility_unknown:platform", unknown.decisions[0].reasons)

    def test_type_specific_skill_and_mcp_compatibility_is_enforced(self):
        skill = _resource("codex-skill")
        mcp = _resource("network-tool", kind="mcp_tool")
        evaluation = evaluate_admission(
            _catalog(skill, mcp),
            _context(compatibility={"harness": "claude", "network": "denied"}),
        )
        decisions = {item.resource_id: item.reasons for item in evaluation.decisions}
        self.assertIn("compatibility_mismatch:harness:claude", decisions["codex-skill"])
        self.assertIn("compatibility_mismatch:network:denied", decisions["network-tool"])
        self.assertEqual(evaluation.selectable, ())

    def test_scope_dimensions_and_future_effective_date_are_enforced(self):
        resources = (
            _resource("wrong-org", scope=Scope(organization="other")),
            _resource("wrong-repo", scope=Scope(organization="acme", repository="ledger")),
            _resource("wrong-path", scope=Scope(organization="acme", path="database")),
            _resource("future", effective_from="2026-10-01"),
        )
        evaluation = evaluate_admission(_catalog(*resources), _context())
        decisions = {item.resource_id: item.reasons for item in evaluation.decisions}
        self.assertIn("scope:organization", decisions["wrong-org"])
        self.assertIn("scope:repository", decisions["wrong-repo"])
        self.assertIn("scope:path", decisions["wrong-path"])
        self.assertIn("not_effective_until:2026-10-01", decisions["future"])

    def test_revocation_between_prefilter_and_post_validation_rejects_raw_selection(self):
        active = _resource("incident-skill")
        revoked = replace(active, lifecycle=replace(active.lifecycle, revoked_at="2026-09-01"))
        run = run_guarded_selection(
            _catalog(active),
            _context(),
            lambda _context, selectable, _mandatory: (CandidateSelection(selectable[0].id, "selected before revocation", 0.99),),
            post_catalog=_catalog(revoked),
        )
        self.assertEqual(run.raw_model_selections[0].resource_id, "incident-skill")
        self.assertEqual(run.final_exposure_ids, ())
        self.assertIn("revoked_at:2026-09-01", run.post_validation_decisions[0].reasons)
        self.assertNotEqual(run.pre_catalog_sha256, run.post_catalog_sha256)
        self.assertTrue(run.violations)

    def test_mandatory_control_change_after_model_blocks_the_run(self):
        active_policy = _resource(
            "change-policy", kind="organizational_policy", disposition="mandatory",
        )
        revoked_policy = replace(
            active_policy,
            lifecycle=replace(active_policy.lifecycle, revoked_at="2026-09-01"),
        )
        skill = _resource("change-skill")
        run = run_guarded_selection(
            _catalog(active_policy, skill),
            _context(),
            lambda _context, selectable, _mandatory: (
                CandidateSelection(selectable[0].id, "relevant", 0.9),
            ),
            post_catalog=_catalog(revoked_policy, skill),
        )
        self.assertTrue(run.blocked)
        self.assertEqual(run.final_exposure_ids, ())
        self.assertIn(
            "mandatory_controls_changed_after_model:pre=change-policy:post=",
            run.violations,
        )

    def test_explicit_supersession_removes_old_resource_before_model(self):
        old = _resource("old-procedure")
        new = _resource("new-procedure", supersedes=("old-procedure",))
        evaluation = evaluate_admission(_catalog(old, new), _context())
        self.assertEqual([item.id for item in evaluation.selectable], ["new-procedure"])
        decision = next(item for item in evaluation.decisions if item.resource_id == "old-procedure")
        self.assertEqual(decision.reasons, ("superseded_by:new-procedure",))

    def test_higher_explicit_authority_wins_policy_conflict(self):
        team = _resource(
            "team-policy", kind="organizational_policy", disposition="mandatory", authority=50,
            conflicts_with=("org-policy",),
        )
        organization = _resource(
            "org-policy", kind="organizational_policy", disposition="mandatory", authority=100,
            conflicts_with=("team-policy",),
        )
        evaluation = evaluate_admission(_catalog(team, organization), _context())
        self.assertEqual([item.id for item in evaluation.mandatory], ["org-policy"])
        losing = next(item for item in evaluation.decisions if item.resource_id == "team-policy")
        self.assertEqual(losing.reasons, ("precedence_lost_to:org-policy",))

    def test_equal_authority_policy_conflict_blocks_before_semantic_reasoning(self):
        left = _resource(
            "left-policy", kind="organizational_policy", disposition="mandatory", authority=100,
            conflicts_with=("right-policy",),
        )
        right = _resource(
            "right-policy", kind="organizational_policy", disposition="mandatory", authority=100,
            conflicts_with=("left-policy",),
        )
        called = False

        def selector(*_args):
            nonlocal called
            called = True
            return ()

        run = run_guarded_selection(_catalog(left, right), _context(), selector)
        self.assertTrue(run.blocked)
        self.assertFalse(called)
        self.assertEqual(run.final_exposure_ids, ())
        self.assertIn("unresolved_conflict:left-policy:right-policy", run.violations)


class CatalogAndAuditTests(unittest.TestCase):
    def test_supersession_cycles_are_rejected(self):
        left = _resource("left", supersedes=("right",))
        right = _resource("right", supersedes=("left",))
        with self.assertRaisesRegex(CatalogError, "supersession cycle"):
            parse_catalog(_catalog(left, right).canonical_data())

    def test_strict_catalog_preserves_type_specific_semantics_and_content_digest(self):
        resources = (
            _resource("skill"),
            _resource("instructions", kind="repository_instruction", disposition="mandatory"),
            _resource("tool", kind="mcp_tool"),
            _resource("data", kind="mcp_resource"),
            _resource("policy", kind="organizational_policy", disposition="mandatory"),
            _resource("environment", kind="environment_contract", disposition="mandatory"),
        )
        payload = ResourceCatalog(1, resources).canonical_data()
        parsed = parse_catalog(payload)
        self.assertEqual({item.kind for item in parsed.resources}, {
            "agent_skill", "repository_instruction", "mcp_tool", "mcp_resource",
            "organizational_policy", "environment_contract",
        })
        self.assertIsInstance(parsed.by_id()["skill"].semantics, SkillSemantics)
        self.assertIsInstance(parsed.by_id()["instructions"].semantics, RepositoryInstructionSemantics)
        self.assertIsInstance(parsed.by_id()["tool"].semantics, MCPSemantics)
        self.assertIsInstance(parsed.by_id()["policy"].semantics, PolicySemantics)
        self.assertIsInstance(parsed.by_id()["environment"].semantics, EnvironmentContractSemantics)
        payload["resources"][0]["content_sha256"] = "0" * 64
        with self.assertRaisesRegex(CatalogError, "does not match body"):
            parse_catalog(payload)

    def test_rankable_and_binding_resource_types_cannot_be_interchanged(self):
        policy = _resource("policy", kind="organizational_policy", disposition="mandatory")
        payload = ResourceCatalog(1, (policy,)).canonical_data()
        payload["resources"][0]["governance"]["disposition"] = "selectable"
        with self.assertRaisesRegex(CatalogError, "cannot be ranked as selectable"):
            parse_catalog(payload)

        skill = _resource("skill")
        payload = ResourceCatalog(1, (skill,)).canonical_data()
        payload["resources"][0]["governance"]["disposition"] = "mandatory"
        with self.assertRaisesRegex(CatalogError, "cannot be a mandatory control"):
            parse_catalog(payload)

    def test_audit_bundle_is_complete_hashed_and_refuses_overwrite(self):
        policy = _resource("policy", kind="organizational_policy", disposition="mandatory")
        skill = _resource("skill")
        catalog = _catalog(policy, skill)
        run = run_guarded_selection(
            catalog,
            _context(),
            lambda _context, _selectable, _mandatory: (CandidateSelection("skill", "relevant", 0.9),),
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "audit"
            files = write_audit_bundle(run, catalog, output)
            self.assertEqual(len(files), 9)
            expected = {
                "catalog_snapshot.json", "resolution_context.json", "prefilter_decisions.json",
                "exposed_resources.json", "raw_model_selections.json", "post_validation_decisions.json",
                "mandatory_controls.json", "final_exposure_set.json", "manifest.json",
            }
            self.assertEqual({path.name for path in files}, expected)
            manifest = json.loads((output / "manifest.json").read_text())
            for entry in manifest["files"]:
                self.assertEqual(
                    entry["sha256"],
                    hashlib.sha256((output / entry["path"]).read_bytes()).hexdigest(),
                )
            exposed = json.loads((output / "exposed_resources.json").read_text())
            self.assertEqual([item["id"] for item in exposed["selectable"]], ["skill"])
            self.assertEqual([item["id"] for item in exposed["mandatory_controls"]], ["policy"])
            with self.assertRaises(AuditWriteError):
                write_audit_bundle(run, catalog, output)

    def test_audit_bundle_rejects_catalogs_other_than_the_evaluated_snapshot(self):
        skill = _resource("skill")
        catalog = _catalog(skill)
        run = run_guarded_selection(catalog, _context(), lambda *_args: ())
        changed = _catalog(replace(skill, revision="2"))
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(AuditWriteError, "do not match"):
                write_audit_bundle(run, changed, Path(temporary) / "audit")

    def test_experimental_package_has_no_semantic_requirement_or_legacy_planning_dependencies(self):
        package = ROOT / "src" / "repo_adaptive_agents" / "admission_control"
        source = "\n".join(path.read_text() for path in package.glob("*.py"))
        for forbidden in (
            "derive_requirements", "Requirement", "CoverageAssessment", "ResidualGap",
            "InfrastructurePlan", "AgentPlan", "CanonicalRole", "ProviderDefinition",
            "knowledge_resolution",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
