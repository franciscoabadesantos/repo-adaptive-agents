import io
import json
import os
import tempfile
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from repo_adaptive_agents.cli import main
from repo_adaptive_agents.multi_cli import (
    TARGETS,
    MultiCliError,
    compare_proposal,
    render_role,
    resolve_targets,
    role_ids,
    validate_proposal,
    write_proposal,
)
from repo_adaptive_agents.multi_cli.validator import _parse_frontmatter

ROLE = "independent_reviewer"

# Critical constraints that must survive into every one of the four outputs.
CRITICAL_MARKERS = (
    "Do not edit",
    "Do not commit",
    "Do not push",
    "Do not deploy",
    "Do not access the network",
    "Do not delegate recursively",
)


class MultiCliRenderTests(unittest.TestCase):
    def _render(self, root: Path, name: str = "proposal", targets=None) -> Path:
        output = root / name
        write_proposal(ROLE, targets, output)
        return output

    def test_renders_four_targets_with_expected_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            self.assertTrue((output / "manifest.json").is_file())
            self.assertTrue((output / "portable/.agents/skills/independent-review/SKILL.md").is_file())
            self.assertTrue((output / "codex/.codex/agents/independent_reviewer.toml").is_file())
            self.assertTrue((output / "claude/.claude/agents/independent-review.md").is_file())
            self.assertTrue((output / "copilot/.github/agents/independent-review.agent.md").is_file())
            self.assertTrue((output / "shared/AGENTS.fragment.md").is_file())

    def test_output_is_deterministic_across_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = self._render(Path(temporary), "first")
            second = self._render(Path(temporary), "second")
            first_files = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
            second_files = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
            self.assertEqual(first_files, second_files)

    def test_codex_toml_is_valid_and_only_known_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            data = tomllib.loads((output / "codex/.codex/agents/independent_reviewer.toml").read_text())
            self.assertEqual(data["name"], "independent_reviewer")
            self.assertEqual(data["sandbox_mode"], "read-only")
            self.assertNotIn("model", data)  # runtime-specific; intentionally left unset
            self.assertIn(".agents/skills/independent-review/SKILL.md", data["developer_instructions"])

    def test_claude_and_copilot_frontmatter_are_parseable(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            for relative in (
                "claude/.claude/agents/independent-review.md",
                "copilot/.github/agents/independent-review.agent.md",
            ):
                meta = _parse_frontmatter((output / relative).read_text())
                self.assertIsNotNone(meta)
                self.assertEqual(meta["name"], "independent-review")
                self.assertTrue(meta["description"])

    def test_skill_md_has_required_sections(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            skill = (output / "portable/.agents/skills/independent-review/SKILL.md").read_text()
            for section in ("## When to use", "## Procedure", "## Response format", "## Constraints", "## Evidence requirements"):
                self.assertIn(section, skill)
            meta = _parse_frontmatter(skill)
            self.assertEqual(meta["name"], "independent-review")

    def test_manifest_is_valid_and_hashes_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            self.assertEqual(validate_proposal(output), [])
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["canonical_role_id"], ROLE)
            self.assertEqual(manifest["targets_requested"], list(TARGETS))
            self.assertNotIn("generated_at", manifest)
            self.assertEqual(set(manifest["targets"]), set(TARGETS))
            self.assertEqual(manifest["targets"]["skill"]["portability"], "portable")
            self.assertEqual(manifest["targets"]["codex"]["portability"], "target_specific")

    def test_critical_constraints_present_in_all_four_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            for relative in (
                "portable/.agents/skills/independent-review/SKILL.md",
                "codex/.codex/agents/independent_reviewer.toml",
                "claude/.claude/agents/independent-review.md",
                "copilot/.github/agents/independent-review.agent.md",
            ):
                text = (output / relative).read_text()
                for marker in CRITICAL_MARKERS:
                    self.assertIn(marker, text, f"{marker!r} missing from {relative}")

    def test_no_absolute_paths_in_any_generated_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            for path in output.rglob("*"):
                if not path.is_file():
                    continue
                for line in path.read_text().splitlines():
                    for token in line.split():
                        self.assertFalse(token.startswith("/"), f"absolute-looking token {token!r} in {path.name}")

    def test_manifest_declares_only_existing_relative_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            manifest = json.loads((output / "manifest.json").read_text())
            declared = [e for section in manifest["targets"].values() for e in section["files"]]
            declared.extend(manifest["shared"]["files"])
            for entry in declared:
                self.assertFalse(entry["path"].startswith("/"))
                self.assertTrue((output / entry["path"]).is_file())


class MultiCliSafetyTests(unittest.TestCase):
    def test_unknown_role_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(MultiCliError, "Unknown role"):
                write_proposal("nonexistent", None, Path(temporary) / "out")

    def test_unknown_target_is_rejected(self):
        with self.assertRaisesRegex(MultiCliError, "Unknown target"):
            resolve_targets(["skill", "bogus"])

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(MultiCliError, "already exists"):
                write_proposal(ROLE, None, output)
            self.assertEqual(marker.read_text(), "preserve")

    def test_output_inside_protected_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            with self.assertRaisesRegex(MultiCliError, "inside the protected repository"):
                write_proposal(ROLE, None, root / "proposal", protected_root=root)

    def test_atomic_failure_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            # An invalid target aborts before any file is written.
            with self.assertRaises(MultiCliError):
                write_proposal(ROLE, ["skill", "unknown"], output)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temporary).glob(".out.tmp-*")), [])

    def test_render_writes_nothing_outside_the_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = {p for p in root.rglob("*")}
            output = root / "out"
            write_proposal(ROLE, None, output)
            after_outside = {p for p in root.rglob("*") if not p.is_relative_to(output) and p != output}
            self.assertEqual(before, after_outside)

    def test_render_does_not_write_to_home_or_mutate_codex_config(self):
        repo_config = Path(__file__).resolve().parent.parent / ".codex" / "config.toml"
        home = Path.home()
        config_before = repo_config.read_text()
        home_before = sorted(p.name for p in home.iterdir()) if home.is_dir() else []
        with tempfile.TemporaryDirectory() as temporary:
            write_proposal(ROLE, None, Path(temporary) / "out")
        self.assertEqual(repo_config.read_text(), config_before)
        home_after = sorted(p.name for p in home.iterdir()) if home.is_dir() else []
        self.assertEqual(home_before, home_after)


class MultiCliCompareTests(unittest.TestCase):
    def test_compare_to_reports_additions_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            write_proposal(ROLE, ["codex"], output)
            destination = Path(temporary) / "dest"
            destination.mkdir()
            before = list(destination.rglob("*"))
            report = compare_proposal(output, destination)
            self.assertEqual(report.additions, [".codex/agents/independent_reviewer.toml"])
            self.assertEqual(report.changes, [])
            self.assertEqual(report.conflicts, [])
            self.assertIn("add: .codex/agents/independent_reviewer.toml", report.diff)
            self.assertEqual(list(destination.rglob("*")), before)  # destination untouched

    def test_compare_to_detects_changes_against_existing_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            write_proposal(ROLE, ["codex"], output)
            destination = Path(temporary) / "dest"
            (destination / ".codex/agents").mkdir(parents=True)
            (destination / ".codex/agents/independent_reviewer.toml").write_text("name = 'old'\n", encoding="utf-8")
            report = compare_proposal(output, destination)
            self.assertEqual(report.changes, [".codex/agents/independent_reviewer.toml"])
            self.assertEqual(report.additions, [])


class MultiCliCliTests(unittest.TestCase):
    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_lists_experimental_command(self):
        with self.assertRaises(SystemExit) as exit_ctx:
            self._run(["--help"])
        self.assertEqual(exit_ctx.exception.code, 0)

    def test_render_role_help_is_available(self):
        with self.assertRaises(SystemExit) as exit_ctx:
            self._run(["render-role", "--help"])
        self.assertEqual(exit_ctx.exception.code, 0)

    def test_roles_and_targets_commands(self):
        code, out, _ = self._run(["roles"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip().splitlines(), role_ids())
        code, out, _ = self._run(["targets"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip().splitlines(), list(TARGETS))

    def test_render_role_cli_writes_and_validates(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            code, out, err = self._run(["render-role", ROLE, "--targets", "skill,codex,claude,copilot", "--output", str(output)])
            self.assertEqual(code, 0, err)
            self.assertIn("Wrote", out)
            self.assertEqual(validate_proposal(output), [])

    def test_render_role_cli_unknown_role_exits_nonzero_on_stderr(self):
        with tempfile.TemporaryDirectory() as temporary:
            code, out, err = self._run(["render-role", "bogus", "--output", str(Path(temporary) / "out")])
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertTrue(err.startswith("error: "))
            self.assertNotIn("Traceback", err)

    def test_render_role_cli_rejects_output_inside_repo(self):
        code, out, err = self._run(["render-role", ROLE, "--output", str(Path(os.getcwd()) / "would-be-proposal")])
        self.assertEqual(code, 2)
        self.assertIn("protected repository", err)


if __name__ == "__main__":
    unittest.main()
