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
from repo_adaptive_agents.multi_cli.roles import INDEPENDENT_REVIEWER, ROLES
from repo_adaptive_agents.multi_cli.validator import _parse_frontmatter

ROLE = "independent_reviewer"
ROLE_IDS = (
    "independent_reviewer",
    "repo_explorer",
    "api_contract_agent",
    "accessibility_performance_reviewer",
)

# The four primary role wrapper files (Codex, Claude, Copilot, Skill).
WRAPPER_FILES = (
    "portable/.agents/skills/independent-review/SKILL.md",
    "codex/.codex/agents/independent_reviewer.toml",
    "claude/.claude/agents/independent-review.md",
    "copilot/.github/agents/independent-review.agent.md",
)


def _canonical_strings(role):
    """Every human-readable canonical string that reaches a rendered file."""
    strings = [role.title, role.description, role.purpose]
    strings.extend(role.capabilities)
    strings.extend(role.when_to_use)
    strings.extend(role.procedure)
    strings.extend(role.response_format)
    strings.extend(role.evidence_requirements)
    strings.extend(role.critical_constraints())
    return strings


def _glued_bigrams(role):
    """Concatenations of adjacent alphabetic canonical words, e.g. 'risks without'->'riskswithout'.

    This is the conservative, dictionary-free guard: the canonical text itself is the
    ground truth. Pairs where the first token ends in punctuation are skipped, so no
    linguistic heuristic is involved — only that two clean words must never appear fused.
    """
    glued = set()
    for text in _canonical_strings(role):
        words = text.split()
        for first, second in zip(words, words[1:]):
            if first[-1:].isalpha() and second[:1].isalpha():
                glued.add(first + second)
    return glued

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
            self.assertTrue((output / "codex/.codex/config.fragments/independent_reviewer.toml").is_file())
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
            self.assertEqual(
                set(manifest["targets"]["codex"]["artifacts"]),
                {"agent_wrapper", "registration_fragment"},
            )

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


class MultiCliWordBoundaryRegressionTests(unittest.TestCase):
    """Regression coverage for word-gluing at wrapping/concatenation boundaries."""

    def _render(self, root: Path) -> Path:
        output = root / "proposal"
        write_proposal(ROLE, None, output)
        return output

    def test_reported_glued_fragments_are_absent_in_all_four_targets(self):
        forbidden = ("byseverity", "riskswithout", "codeonly", "notpush")
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            for relative in WRAPPER_FILES:
                text = (output / relative).read_text()
                for fragment in forbidden:
                    self.assertNotIn(fragment, text, f"{fragment!r} glued in {relative}")

    def test_correct_spaced_phrases_are_present(self):
        expected = ("ordered by severity", "risks without", "adjacent code only", "Do not push")
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            for relative in WRAPPER_FILES:
                text = (output / relative).read_text()
                for phrase in expected:
                    self.assertIn(phrase, text, f"{phrase!r} missing from {relative}")

    def test_no_canonical_words_are_fused_at_any_boundary(self):
        glued = _glued_bigrams(INDEPENDENT_REVIEWER)
        self.assertIn("riskswithout", glued)  # guard is actually exercising real boundaries
        self.assertIn("adjacentcode", glued)
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            for relative in WRAPPER_FILES:
                text = (output / relative).read_text()
                offenders = sorted(fragment for fragment in glued if fragment in text)
                self.assertEqual(offenders, [], f"fused words in {relative}: {offenders}")

    def test_formats_still_valid_after_boundary_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            # TOML parseable, frontmatter parseable, manifest hashes match.
            tomllib.loads((output / "codex/.codex/agents/independent_reviewer.toml").read_text())
            for relative in (
                "claude/.claude/agents/independent-review.md",
                "copilot/.github/agents/independent-review.agent.md",
                "portable/.agents/skills/independent-review/SKILL.md",
            ):
                self.assertIsNotNone(_parse_frontmatter((output / relative).read_text()))
            self.assertEqual(validate_proposal(output), [])

    def test_output_remains_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "a"
            second = Path(temporary) / "b"
            write_proposal(ROLE, None, first)
            write_proposal(ROLE, None, second)
            first_files = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
            second_files = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
            self.assertEqual(first_files, second_files)


class MultiCliEnforcementMetadataTests(unittest.TestCase):
    """Guidance-vs-enforcement must be explicit in prose and in the manifest."""

    GUIDANCE_LINE = "These constraints are behavioral guidance, not technical enforcement."
    ENFORCE_LINE = "Enforce them through the host tool's permissions, approvals, sandbox, and repository policy."

    def _render(self, root: Path) -> Path:
        output = root / "proposal"
        write_proposal(ROLE, None, output)
        return output

    def test_markdown_wrappers_declare_guidance_not_enforcement(self):
        markdown_files = (
            "portable/.agents/skills/independent-review/SKILL.md",
            "claude/.claude/agents/independent-review.md",
            "copilot/.github/agents/independent-review.agent.md",
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            for relative in markdown_files:
                text = (output / relative).read_text()
                self.assertIn(self.GUIDANCE_LINE, text, relative)
                self.assertIn(self.ENFORCE_LINE, text, relative)
                # The note appears immediately before the constraints list.
                constraints = text.index("## Constraints")
                first_bullet = text.index("- Do not edit", constraints)
                self.assertIn(self.GUIDANCE_LINE, text[constraints:first_bullet], relative)

    def test_codex_keeps_readonly_sandbox_and_no_prose_only_disclaimer_needed(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            data = tomllib.loads((output / "codex/.codex/agents/independent_reviewer.toml").read_text())
            self.assertEqual(data["sandbox_mode"], "read-only")

    def test_manifest_enforcement_metadata_is_correct(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            manifest = json.loads((output / "manifest.json").read_text())
            targets = manifest["targets"]
            for advisory in ("skill", "claude", "copilot"):
                self.assertEqual(
                    targets[advisory]["enforcement"],
                    {"mode": "advisory", "runtime_controls_generated": False},
                    advisory,
                )
            self.assertEqual(
                targets["codex"]["enforcement"],
                {"mode": "sandboxed", "runtime_controls_generated": True, "controls": ["sandbox_mode"]},
            )

    def test_formats_and_hashes_remain_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            self.assertEqual(validate_proposal(output), [])

    def test_output_stays_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "a", Path(temporary) / "b"
            write_proposal(ROLE, None, first)
            write_proposal(ROLE, None, second)
            first_files = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
            second_files = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
            self.assertEqual(first_files, second_files)


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
            self.assertEqual(
                report.additions,
                [
                    ".codex/agents/independent_reviewer.toml",
                    ".codex/config.fragments/independent_reviewer.toml",
                ],
            )
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
            self.assertEqual(report.additions, [".codex/config.fragments/independent_reviewer.toml"])


class MultiCliRoleBatchTests(unittest.TestCase):
    def test_role_registry_is_exact_and_deterministic(self):
        self.assertEqual(role_ids(), list(ROLE_IDS))
        self.assertEqual(list(ROLES), list(ROLE_IDS))

    def test_source_evidence_paths_exist_or_use_explicit_non_path_reference(self):
        repository_root = Path(__file__).resolve().parent.parent
        non_path_prefix = "implementation contract: "

        for role_id, role in ROLES.items():
            for evidence in role.source_evidence:
                with self.subTest(role=role_id, evidence=evidence):
                    if evidence.startswith(non_path_prefix):
                        self.assertTrue(evidence.removeprefix(non_path_prefix).strip())
                        continue
                    self.assertTrue(
                        (repository_root / evidence).is_file(),
                        f"{role_id} source evidence path does not exist: {evidence}",
                    )

    def test_all_roles_render_all_targets_and_registration_fragments(self):
        with tempfile.TemporaryDirectory() as temporary:
            for role_id in ROLE_IDS:
                with self.subTest(role=role_id):
                    output = Path(temporary) / role_id
                    write_proposal(role_id, list(TARGETS), output)
                    role = ROLES[role_id]
                    self.assertEqual(validate_proposal(output), [])
                    self.assertTrue((output / f"portable/.agents/skills/{role.slug}/SKILL.md").is_file())
                    self.assertTrue((output / f"codex/.codex/agents/{role.id}.toml").is_file())
                    self.assertTrue((output / f"codex/.codex/config.fragments/{role.id}.toml").is_file())
                    self.assertTrue((output / f"claude/.claude/agents/{role.slug}.md").is_file())
                    self.assertTrue((output / f"copilot/.github/agents/{role.slug}.agent.md").is_file())

    def test_all_roles_are_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            for role_id in ROLE_IDS:
                with self.subTest(role=role_id):
                    first = Path(temporary) / f"{role_id}-first"
                    second = Path(temporary) / f"{role_id}-second"
                    write_proposal(role_id, None, first)
                    write_proposal(role_id, None, second)
                    first_files = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
                    second_files = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
                    self.assertEqual(first_files, second_files)

    def test_role_specific_semantics_are_preserved_in_every_target(self):
        expected = {
            "repo_explorer": ("architecture_mapping", "component_discovery", "entrypoint_discovery", "facts", "inferences", "evidence paths"),
            "api_contract_agent": ("compatibility_analysis", "schema_review", "error_contract_review", "Do not make real API calls", "runtime endpoint"),
            "accessibility_performance_reviewer": ("accessibility_review", "frontend_performance_review", "static evidence", "runtime validation", "Lighthouse", "browser"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            for role_id, markers in expected.items():
                with self.subTest(role=role_id):
                    output = Path(temporary) / role_id
                    write_proposal(role_id, None, output)
                    for relative in (
                        f"portable/.agents/skills/{ROLES[role_id].slug}/SKILL.md",
                        f"codex/.codex/agents/{role_id}.toml",
                        f"claude/.claude/agents/{ROLES[role_id].slug}.md",
                        f"copilot/.github/agents/{ROLES[role_id].slug}.agent.md",
                    ):
                        text = (output / relative).read_text(encoding="utf-8").lower()
                        for marker in markers:
                            self.assertIn(marker.lower(), text, f"{marker!r} missing from {relative}")

    def test_codex_fragments_are_valid_manual_registrations(self):
        with tempfile.TemporaryDirectory() as temporary:
            for role_id in ROLE_IDS:
                with self.subTest(role=role_id):
                    output = Path(temporary) / role_id
                    write_proposal(role_id, ["codex"], output)
                    fragment = output / f"codex/.codex/config.fragments/{role_id}.toml"
                    data = tomllib.loads(fragment.read_text(encoding="utf-8"))
                    entry = data["agents"][role_id]
                    self.assertEqual(entry["config_file"], f".codex/agents/{role_id}.toml")
                    self.assertNotIn("model", entry)
                    self.assertNotIn("max_threads", entry)
                    self.assertNotIn("max_depth", entry)

    def test_generated_paths_are_relative_and_enforcement_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            for role_id in ROLE_IDS:
                with self.subTest(role=role_id):
                    output = Path(temporary) / role_id
                    write_proposal(role_id, None, output)
                    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
                    self.assertTrue(manifest["source"]["role_hash"].isalnum())
                    for target in TARGETS:
                        self.assertEqual(
                            manifest["targets"][target]["enforcement"]["mode"],
                            "sandboxed" if target == "codex" else "advisory",
                        )
                    for path in output.rglob("*"):
                        if path.is_file():
                            self.assertFalse(path.relative_to(output).is_absolute())
                            self.assertNotIn("/home/", path.read_text(encoding="utf-8"))


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
