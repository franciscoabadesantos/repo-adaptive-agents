import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from repo_adaptive_agents.cli import main
from repo_adaptive_agents.multi_cli import (
    TeamError,
    recommend_team,
    validate_team_proposal,
    write_team_proposal,
)
from repo_adaptive_agents.profiler import profile_repository

FIXTURES = Path(__file__).parent / "fixtures"

# fixture -> (required roles, forbidden roles, consolidator)
EXPECTED = {
    "team-api-openapi": (
        {"repo_explorer", "api_contract_agent"},
        {"browser_qa", "design_director", "accessibility_performance_reviewer"},
        None,
    ),
    "team-frontend-react": (
        {"repo_explorer", "browser_qa", "accessibility_performance_reviewer"},
        {"api_contract_agent", "design_director"},
        "independent_reviewer",
    ),
    "team-frontend-design": (
        {"repo_explorer", "browser_qa", "accessibility_performance_reviewer", "design_director"},
        {"api_contract_agent"},
        "independent_reviewer",
    ),
    "team-cli-tool": (
        {"repo_explorer"},
        {"api_contract_agent", "browser_qa", "design_director", "accessibility_performance_reviewer", "independent_reviewer"},
        None,
    ),
    "team-fullstack": (
        {"repo_explorer", "api_contract_agent", "browser_qa", "accessibility_performance_reviewer", "design_director", "independent_reviewer"},
        set(),
        "independent_reviewer",
    ),
}


def _plan(fixture: str):
    path = FIXTURES / fixture
    return recommend_team(profile_repository(path), path)


def _tree_bytes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


class TeamRecommendationTests(unittest.TestCase):
    def test_each_fixture_selects_expected_roles(self):
        for fixture, (required, forbidden, consolidator) in EXPECTED.items():
            with self.subTest(fixture=fixture):
                plan = _plan(fixture)
                selected = set(plan.selected_ids)
                self.assertTrue(required.issubset(selected), f"{fixture}: missing {required - selected}")
                self.assertEqual(forbidden & selected, set(), f"{fixture}: unexpected {forbidden & selected}")
                self.assertNotIn("implementation_agent", selected)
                self.assertEqual(plan.consolidator, consolidator)

    def test_empty_repo_selects_nothing_and_warns(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = recommend_team(profile_repository(Path(temporary)), Path(temporary))
            self.assertEqual(plan.selected_ids, ())
            self.assertIn("insufficient information to recommend specialized roles", plan.warnings)
            self.assertTrue(any(rec.role_id == "implementation_agent" for rec in plan.excluded_roles))

    def test_implementation_agent_is_always_excluded_with_reason(self):
        plan = _plan("team-fullstack")
        impl = next(rec for rec in plan.excluded_roles if rec.role_id == "implementation_agent")
        self.assertIn("explicit brief and write scope", impl.reasons[0])

    def test_execution_plan_orders_explorer_first_then_parallel_specialists(self):
        plan = _plan("team-fullstack")
        self.assertEqual(plan.parallel_groups[0], ("repo_explorer",))
        self.assertEqual(
            plan.parallel_groups[1],
            ("api_contract_agent", "browser_qa", "accessibility_performance_reviewer", "design_director"),
        )
        self.assertEqual(plan.consolidator, "independent_reviewer")

    def test_api_fixture_has_no_consolidator_single_specialist(self):
        plan = _plan("team-api-openapi")
        self.assertIsNone(plan.consolidator)
        self.assertEqual(plan.parallel_groups, (("repo_explorer",), ("api_contract_agent",)))

    def test_reasons_and_evidence_are_deterministic(self):
        self.assertEqual(_plan("team-frontend-design"), _plan("team-frontend-design"))
        design = next(rec for rec in _plan("team-frontend-design").selected_roles if rec.role_id == "design_director")
        self.assertEqual(design.evidence, (".storybook", "design-tokens.json", "tailwind.config.js"))
        self.assertTrue(all("design-tooling signal" in reason for reason in design.reasons))

    def test_accessibility_role_never_claims_executed_tooling(self):
        a11y = next(rec for rec in _plan("team-frontend-react").selected_roles if rec.role_id == "accessibility_performance_reviewer")
        joined = " ".join(a11y.reasons).lower()
        self.assertIn("no browser, lighthouse, or performance tooling is executed", joined)

    def test_include_and_exclude_roles(self):
        path = FIXTURES / "team-frontend-react"
        plan = recommend_team(
            profile_repository(path), path,
            include_roles=["api_contract_agent"], exclude_roles=["browser_qa"],
        )
        self.assertIn("api_contract_agent", plan.selected_ids)
        self.assertNotIn("browser_qa", plan.selected_ids)

    def test_include_rejects_implementation_agent_and_unknown(self):
        path = FIXTURES / "team-api-openapi"
        profile = profile_repository(path)
        with self.assertRaisesRegex(TeamError, "implementation_agent"):
            recommend_team(profile, path, include_roles=["implementation_agent"])
        with self.assertRaisesRegex(TeamError, "Unknown role"):
            recommend_team(profile, path, include_roles=["does_not_exist"])


class TeamProposalWritingTests(unittest.TestCase):
    def test_renders_all_selected_roles_and_validates(self):
        for fixture, (required, _forbidden, _c) in EXPECTED.items():
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "team"
                written, plan, manifest = write_team_proposal(FIXTURES / fixture, None, output)
                self.assertEqual(validate_team_proposal(output), [])
                self.assertEqual(manifest["kind"], "team")
                self.assertEqual(manifest["schema_version"], 2)
                for role_id in plan.selected_ids:
                    self.assertTrue((output / "roles" / role_id / "manifest.json").is_file())
                self.assertTrue((output / "team" / "AGENTS.fragment.md").is_file())

    def test_aggregated_manifest_hashes_and_relative_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "team"
            _written, _plan, manifest = write_team_proposal(FIXTURES / "team-fullstack", None, output)
            declared = []
            for section in manifest["roles"].values():
                declared.append(section["manifest"])
                declared.extend(section["files"])
                declared.extend(section.get("artifacts", {}).values())
            declared.extend(manifest["team"]["files"])
            for entry in declared:
                self.assertFalse(entry["path"].startswith("/"))
                self.assertTrue((output / entry["path"]).is_file())

    def test_two_generations_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "a"
            second = Path(temporary) / "b"
            write_team_proposal(FIXTURES / "team-fullstack", None, first)
            write_team_proposal(FIXTURES / "team-fullstack", None, second)
            self.assertEqual(_tree_bytes(first), _tree_bytes(second))

    def test_flag_order_does_not_change_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "a"
            second = Path(temporary) / "b"
            write_team_proposal(FIXTURES / "team-frontend-react", ["skill", "codex", "claude", "copilot"], first,
                                include_roles=["api_contract_agent", "design_director"], exclude_roles=["browser_qa"])
            write_team_proposal(FIXTURES / "team-frontend-react", ["copilot", "claude", "codex", "skill"], second,
                                include_roles=["design_director", "api_contract_agent"], exclude_roles=["browser_qa"])
            self.assertEqual(_tree_bytes(first), _tree_bytes(second))

    def test_compare_to_is_read_only_and_recorded(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "team"
            destination = Path(temporary) / "dest"
            destination.mkdir()
            before = list(destination.rglob("*"))
            _written, _plan, manifest = write_team_proposal(FIXTURES / "team-api-openapi", ["codex"], output, compare_to=destination)
            self.assertIn("compare", manifest)
            self.assertIn(".codex/agents/api_contract_agent.toml", manifest["compare"]["additions"])
            self.assertEqual(manifest["compare"]["changes"], [])
            self.assertEqual(list(destination.rglob("*")), before)  # destination untouched
            for path in manifest["compare"]["additions"]:
                self.assertFalse(path.startswith("/"))

    def test_output_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            existing = Path(temporary) / "team"
            existing.mkdir()
            (existing / "keep.txt").write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(Exception, "already exists"):
                write_team_proposal(FIXTURES / "team-api-openapi", None, existing)
            self.assertEqual((existing / "keep.txt").read_text(), "preserve")

            repo = Path(temporary) / "repo"
            repo.mkdir()
            with self.assertRaisesRegex(Exception, "inside the protected repository"):
                write_team_proposal(FIXTURES / "team-api-openapi", None, repo / "team", protected_root=repo)

    def test_nonexistent_or_file_repo_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(Exception, "not a directory"):
                write_team_proposal(Path(temporary) / "missing", None, Path(temporary) / "out")
            a_file = Path(temporary) / "file.txt"
            a_file.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(Exception, "not a directory"):
                write_team_proposal(a_file, None, Path(temporary) / "out2")

    def test_does_not_write_into_analyzed_repo_or_home(self):
        repo = FIXTURES / "team-fullstack"
        repo_before = _tree_bytes(repo)
        home = Path.home()
        home_before = sorted(p.name for p in home.iterdir()) if home.is_dir() else []
        with tempfile.TemporaryDirectory() as temporary:
            write_team_proposal(repo, None, Path(temporary) / "team")
        self.assertEqual(_tree_bytes(repo), repo_before)
        home_after = sorted(p.name for p in home.iterdir()) if home.is_dir() else []
        self.assertEqual(home_before, home_after)


class TeamCliTests(unittest.TestCase):
    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_is_available(self):
        with self.assertRaises(SystemExit) as ctx:
            self._run(["propose-team", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_valid_command_writes_and_reports(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "team"
            code, out, err = self._run([
                "propose-team", str(FIXTURES / "team-fullstack"),
                "--targets", "skill,codex,claude,copilot", "--output", str(output),
            ])
            self.assertEqual(code, 0, err)
            self.assertIn("Selected roles:", out)
            self.assertIn("Consolidator: independent_reviewer", out)
            self.assertEqual(validate_team_proposal(output), [])

    def test_invalid_target_include_and_impl_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            for extra in (
                ["--targets", "bogus"],
                ["--include-role", "does_not_exist"],
                ["--include-role", "implementation_agent"],
                ["--exclude-role", "implementation_agent"],
            ):
                out_dir = Path(temporary) / ("out_" + "_".join(extra))
                code, out, err = self._run([
                    "propose-team", str(FIXTURES / "team-api-openapi"),
                    "--output", str(out_dir), *extra,
                ])
                self.assertEqual(code, 2, f"{extra} -> {out}")
                self.assertTrue(err.startswith("error: "))
                self.assertNotIn("Traceback", err)
                self.assertFalse(out_dir.exists())

    def test_missing_repo_directory_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, out, err = self._run(["propose-team", str(Path(temporary) / "nope"), "--output", str(Path(temporary) / "out")])
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertIn("not a directory", err)

    def test_output_inside_repo_is_rejected(self):
        code, _out, err = self._run([
            "propose-team", str(FIXTURES / "team-api-openapi"),
            "--output", str(Path(os.getcwd()) / "would-be-team"),
        ])
        self.assertEqual(code, 2)
        self.assertIn("protected repository", err)


if __name__ == "__main__":
    unittest.main()
