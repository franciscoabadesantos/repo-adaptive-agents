import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from repo_adaptive_agents.cli import main
from repo_adaptive_agents.multi_cli import (
    AdapterSelectionError,
    select_adapters,
    validate_adapter_bundle,
    write_adapter_bundle,
)
from repo_adaptive_agents.profiler import profile_repository
from repo_adaptive_agents.recommender import recommend_infrastructure


FIXTURES = Path(__file__).parent / "fixtures"


def _infrastructure(fixture: str):
    return recommend_infrastructure(profile_repository(FIXTURES / fixture))


def _tree_bytes(root: Path) -> dict:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


class AdapterSelectionTests(unittest.TestCase):
    def test_capability_matches_connect_core_to_canonical_adapters(self):
        plan = select_adapters(
            _infrastructure("team-fullstack"),
            ["repo_explorer", "browser_qa", "api_contract_agent"],
        )
        self.assertEqual(
            plan.eligible_role_ids,
            ("repo_explorer", "api_contract_agent", "browser_qa"),
        )
        selected = {item.role_id: item for item in plan.selected_adapters}
        self.assertEqual(selected["repo_explorer"].matched_available_roles, ("repo_mapper",))
        self.assertEqual(selected["repo_explorer"].matched_capabilities, ("repo_analysis",))
        self.assertEqual(selected["browser_qa"].matched_available_roles, ("browser_qa",))
        self.assertEqual(selected["api_contract_agent"].matched_available_roles, ("api_reviewer",))
        self.assertIn("test_engineer", plan.unmapped_available_roles)

    def test_human_selection_does_not_invent_profiler_evidence(self):
        plan = select_adapters(
            _infrastructure("team-frontend-react"), ["design_director"]
        )
        selection = plan.selected_adapters[0]
        self.assertEqual(selection.matched_available_roles, ())
        self.assertEqual(selection.matched_capabilities, ())

    def test_invalid_or_write_role_is_rejected(self):
        infrastructure = _infrastructure("team-fullstack")
        with self.assertRaisesRegex(AdapterSelectionError, "At least one"):
            select_adapters(infrastructure, [])
        with self.assertRaisesRegex(AdapterSelectionError, "Unknown adapter"):
            select_adapters(infrastructure, ["does_not_exist"])
        with self.assertRaisesRegex(AdapterSelectionError, "explicit write scope"):
            select_adapters(infrastructure, ["implementation_agent"])

    def test_selection_order_is_canonical(self):
        infrastructure = _infrastructure("team-fullstack")
        first = select_adapters(infrastructure, ["browser_qa", "repo_explorer"])
        second = select_adapters(infrastructure, ["repo_explorer", "browser_qa"])
        self.assertEqual(first, second)
        self.assertEqual(first.selected_ids, ("repo_explorer", "browser_qa"))


class AdapterBundleTests(unittest.TestCase):
    def test_bundle_has_no_execution_topology_and_validates(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            _written, plan, manifest = write_adapter_bundle(
                FIXTURES / "team-fullstack",
                ["skill", "codex"],
                ["repo_explorer", "browser_qa"],
                output,
            )
            self.assertEqual(validate_adapter_bundle(output), [])
            self.assertEqual(manifest["kind"], "adapter_bundle")
            self.assertEqual(manifest["schema_version"], 3)
            self.assertEqual(manifest["selection_status"], "tool_proposal")
            self.assertNotIn("execution_plan", manifest)
            self.assertNotIn("parallel_groups", json.dumps(manifest))
            self.assertNotIn("consolidator", json.dumps(manifest))
            self.assertNotIn("team", manifest)
            self.assertEqual(plan.selected_ids, ("repo_explorer", "browser_qa"))
            self.assertTrue((output / "profile.json").is_file())
            self.assertTrue((output / "infrastructure-plan.json").is_file())
            self.assertTrue((output / "roles/repo_explorer/manifest.json").is_file())
            self.assertTrue((output / "roles/browser_qa/manifest.json").is_file())
            self.assertFalse((output / "roles/independent_reviewer").exists())

    def test_bundle_preserves_all_explicit_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            write_adapter_bundle(
                FIXTURES / "team-frontend-react",
                ["skill", "codex", "claude", "copilot"],
                ["browser_qa"],
                output,
            )
            root = output / "roles/browser_qa"
            self.assertTrue((root / "portable/.agents/skills/browser-qa/SKILL.md").is_file())
            self.assertTrue((root / "codex/.codex/agents/browser_qa.toml").is_file())
            self.assertTrue((root / "claude/.claude/agents/browser-qa.md").is_file())
            self.assertTrue((root / "copilot/.github/agents/browser-qa.agent.md").is_file())

    def test_generation_is_deterministic_across_argument_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "a"
            second = Path(temporary) / "b"
            write_adapter_bundle(
                FIXTURES / "team-fullstack",
                ["skill", "codex", "claude", "copilot"],
                ["browser_qa", "repo_explorer"],
                first,
            )
            write_adapter_bundle(
                FIXTURES / "team-fullstack",
                ["copilot", "claude", "codex", "skill"],
                ["repo_explorer", "browser_qa"],
                second,
            )
            self.assertEqual(_tree_bytes(first), _tree_bytes(second))

    def test_compare_is_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            destination = Path(temporary) / "destination"
            destination.mkdir()
            before = _tree_bytes(destination)
            _written, _plan, manifest = write_adapter_bundle(
                FIXTURES / "team-api-openapi",
                ["codex"],
                ["api_contract_agent"],
                output,
                compare_to=destination,
            )
            self.assertIn(
                ".codex/agents/api_contract_agent.toml",
                manifest["compare"]["additions"],
            )
            self.assertEqual(_tree_bytes(destination), before)

    def test_compare_does_not_follow_destination_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "destination"
            destination.mkdir()
            outside = root / "outside"
            (outside / "agents").mkdir(parents=True)
            (outside / "agents/repo_explorer.toml").write_bytes(b"\xff")
            (destination / ".codex").symlink_to(outside, target_is_directory=True)
            output = root / "bundle"

            write_adapter_bundle(
                FIXTURES / "team-fullstack",
                ["codex"],
                ["repo_explorer"],
                output,
                compare_to=destination,
            )

            manifest = json.loads((output / "manifest.json").read_text())
            self.assertIn(
                ".codex/agents/repo_explorer.toml",
                manifest["compare"]["changes"],
            )

    def test_output_guards_preserve_existing_and_protected_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            existing = Path(temporary) / "bundle"
            existing.mkdir()
            marker = existing / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(Exception, "already exists"):
                write_adapter_bundle(
                    FIXTURES / "team-fullstack", ["skill"], ["repo_explorer"], existing
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

            protected = Path(temporary) / "protected"
            protected.mkdir()
            with self.assertRaisesRegex(Exception, "protected repository"):
                write_adapter_bundle(
                    FIXTURES / "team-fullstack",
                    ["skill"],
                    ["repo_explorer"],
                    protected / "bundle",
                    protected_root=protected,
                )

            with self.assertRaisesRegex(Exception, "analyzed repository"):
                write_adapter_bundle(
                    FIXTURES / "team-fullstack",
                    ["skill"],
                    ["repo_explorer"],
                    FIXTURES / "team-fullstack/would-be-bundle",
                )

    def test_validator_rejects_an_execution_plan(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            write_adapter_bundle(
                FIXTURES / "team-fullstack", ["skill"], ["repo_explorer"], output
            )
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["execution_plan"] = {"parallel_groups": [["repo_explorer"]]}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertIn(
                "adapter manifest: execution_plan is not allowed",
                validate_adapter_bundle(output),
            )

    def test_validator_rejects_requested_target_role_manifest_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            write_adapter_bundle(
                FIXTURES / "team-fullstack",
                ["codex"],
                ["repo_explorer"],
                output,
            )
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["requested_targets"] = ["skill"]
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            issues = validate_adapter_bundle(output)

            self.assertTrue(
                any("targets do not match requested_targets" in issue for issue in issues)
            )


class AdapterCliTests(unittest.TestCase):
    @staticmethod
    def _run(argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_valid_command_reports_tool_proposal_without_claiming_user_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            code, stdout, stderr = self._run([
                "propose-adapters",
                str(FIXTURES / "team-fullstack"),
                "--targets", "skill,codex",
                "--role", "repo_explorer",
                "--role", "browser_qa",
                "--output", str(output),
            ])
            self.assertEqual(code, 0, stderr)
            self.assertIn("Proposed adapters: repo_explorer, browser_qa", stdout)
            self.assertIn("Selection status: tool proposal", stdout)
            self.assertIn("No execution order or agent invocation was generated.", stdout)
            self.assertEqual(validate_adapter_bundle(output), [])
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["selection_status"], "tool_proposal")
            self.assertTrue(
                all(
                    item["selection_source"] == "tool_proposal"
                    for item in manifest["selected_adapters"]
                )
            )

    def test_adapter_options_is_read_only_and_requests_user_selection(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([
                "adapter-options",
                str(FIXTURES / "team-fullstack"),
            ])

        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "requires_install_decision")
        self.assertEqual(payload["repository_summary"]["primary_project_types"], ["frontend", "api"])
        self.assertIn("repository_contracts", payload)
        self.assertIn("recommended_capabilities", payload)
        self.assertEqual(payload["available_targets"], ["skill", "codex", "claude", "copilot"])
        self.assertEqual(payload["target_details"]["skill"]["kind"], "portable_artifact")
        self.assertIn("not a harness", payload["target_details"]["skill"]["note"])
        self.assertEqual(payload["target_details"]["codex"]["kind"], "harness_adapter")
        self.assertEqual(
            [item["role_id"] for item in payload["matched_adapters"]],
            ["repo_explorer", "api_contract_agent", "browser_qa"],
        )
        self.assertIn(
            "design_director",
            [item["role_id"] for item in payload["optional_adapters"]],
        )
        self.assertEqual(
            {item["id"] for item in payload["questions"]},
            {"adapter_targets", "adapter_roles"},
        )
        target_question = next(
            item for item in payload["questions"] if item["id"] == "adapter_targets"
        )
        self.assertIn("optional portable artifact", target_question["question"])
        self.assertIn("Present the repository summary", payload["next_action"])

    def test_adapter_options_is_a_complete_decision_packet_for_prefect(self):
        code, stdout, stderr = self._run([
            "adapter-options",
            str(FIXTURES / "prefect-data-ops"),
        ])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        summary = payload["repository_summary"]
        self.assertEqual(summary["primary_project_types"], ["pipeline"])
        self.assertIn("api", summary["secondary_project_types"])
        self.assertEqual(
            [(item["technology"], item["status"]) for item in summary["technology_findings"]],
            [("Prefect", "recognized")],
        )
        capability_ids = {item["capability_id"] for item in payload["recommended_capabilities"]}
        self.assertTrue(
            {"pipeline_review", "operations_review", "ci_cd_review", "api_contract_review"}.issubset(capability_ids)
        )
        self.assertEqual(
            [item["role_id"] for item in payload["matched_adapters"]],
            ["repo_explorer", "api_contract_agent"],
        )
        unmapped_ids = {item["capability_id"] for item in payload["unmapped_capabilities"]}
        self.assertTrue({"pipeline_review", "operations_review", "ci_cd_review"}.issubset(unmapped_ids))
        self.assertIn("pipeline_reviewer", payload["unmapped_available_roles"])
        self.assertTrue(any(item["name"] == "pipeline_reviewer" for item in payload["unmapped_roles"]))

    def test_cli_always_writes_tool_proposal_without_claiming_user_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "bundle"
            code, stdout, stderr = self._run([
                "propose-adapters",
                str(FIXTURES / "team-fullstack"),
                "--targets", "skill,codex",
                "--role", "repo_explorer",
                "--output", str(output),
            ])
            self.assertEqual(code, 0, stderr)
            self.assertIn("tool proposal", stdout)
            self.assertTrue(output.is_dir())
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["selection_status"], "tool_proposal")

    def test_unknown_and_write_roles_fail_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            for role in ("does_not_exist", "implementation_agent"):
                output = Path(temporary) / role
                code, stdout, stderr = self._run([
                    "propose-adapters",
                    str(FIXTURES / "team-fullstack"),
                    "--targets", "skill",
                    "--role", role,
                    "--output", str(output),
                ])
                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr.startswith("error: "))
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
