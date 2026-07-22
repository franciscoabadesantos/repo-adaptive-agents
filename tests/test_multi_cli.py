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
    ScopeError,
    build_scope,
    compare_proposal,
    normalize_path,
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
    "browser_qa",
    "design_director",
    "implementation_agent",
)
# Read-only roles render without a scope; write roles require one.
READ_ONLY_ROLE_IDS = tuple(r for r in ROLE_IDS if r != "implementation_agent")


def scope_for(role_id):
    """A valid scope for write roles, or None for read-only roles."""
    if ROLES[role_id].constraints.require_explicit_scope:
        return build_scope("Implement the approved change", ["src/", "tests/"], ["src/generated/"])
    return None

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
            self.assertNotIn(".agents/skills/", data["developer_instructions"])
            self.assertNotIn("Complementary context", data["developer_instructions"])
            self.assertIn("Procedure:", data["developer_instructions"])
            self.assertIn("Evidence requirements:", data["developer_instructions"])

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

    def test_harness_only_wrappers_do_not_depend_on_portable_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(
                Path(temporary),
                targets=["codex", "claude", "copilot"],
            )
            self.assertFalse((output / "portable").exists())
            for relative in (
                "codex/.codex/agents/independent_reviewer.toml",
                "claude/.claude/agents/independent-review.md",
                "copilot/.github/agents/independent-review.agent.md",
            ):
                self.assertNotIn(".agents/skills/", (output / relative).read_text())

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
            self.assertEqual(manifest["schema_version"], 2)
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

    def test_compare_to_does_not_follow_destination_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            write_proposal(ROLE, ["codex"], output)
            destination = root / "dest"
            (destination / ".codex/agents").mkdir(parents=True)
            outside = root / "outside.txt"
            outside.write_text("REVIEW_SENTINEL_OUTSIDE_REPOSITORY\n", encoding="utf-8")
            (destination / ".codex/agents/independent_reviewer.toml").symlink_to(outside)

            report = compare_proposal(output, destination)

            self.assertEqual(report.changes, [".codex/agents/independent_reviewer.toml"])
            self.assertNotIn("REVIEW_SENTINEL_OUTSIDE_REPOSITORY", report.diff)
            self.assertIn("comparison unavailable: destination path is a symlink", report.diff)


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
                    write_proposal(role_id, list(TARGETS), output, scope=scope_for(role_id))
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
                    write_proposal(role_id, None, first, scope=scope_for(role_id))
                    write_proposal(role_id, None, second, scope=scope_for(role_id))
                    first_files = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
                    second_files = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
                    self.assertEqual(first_files, second_files)

    def test_role_specific_semantics_are_preserved_in_every_target(self):
        expected = {
            "repo_explorer": ("architecture_mapping", "component_discovery", "entrypoint_discovery", "facts", "inferences", "evidence paths"),
            "api_contract_agent": ("compatibility_analysis", "schema_review", "error_contract_review", "Do not make real API calls", "runtime endpoint"),
            "accessibility_performance_reviewer": ("accessibility_review", "frontend_performance_review", "static evidence", "runtime validation", "Lighthouse", "browser"),
            "browser_qa": ("interaction_review", "responsive_review", "browser validation required", "unavailable tooling", "did not occur"),
            "design_director": ("visual_hierarchy_review", "design_system_review", "typography", "spacing", "runtime validation", "Do not invent design requirements"),
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
                    write_proposal(role_id, ["codex"], output, scope=scope_for(role_id))
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
                    write_proposal(role_id, None, output, scope=scope_for(role_id))
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


class MultiCliBrowserQaTests(unittest.TestCase):
    """browser_qa must represent browser tooling honestly and never claim it ran."""

    def _wrapper_files(self, output: Path) -> list[Path]:
        return [
            output / "portable/.agents/skills/browser-qa/SKILL.md",
            output / "codex/.codex/agents/browser_qa.toml",
            output / "claude/.claude/agents/browser-qa.md",
            output / "copilot/.github/agents/browser-qa.agent.md",
        ]

    def test_separates_performed_required_and_unavailable_browser_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "browser_qa"
            write_proposal("browser_qa", None, output)
            for path in self._wrapper_files(output):
                text = path.read_text(encoding="utf-8").lower()
                self.assertIn("browser validation performed", text, path.name)
                self.assertIn("browser validation required", text, path.name)
                self.assertIn("unavailable tooling", text, path.name)

    def test_forbids_claiming_unexecuted_interactions_and_assumed_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "browser_qa"
            write_proposal("browser_qa", None, output)
            for path in self._wrapper_files(output):
                text = path.read_text(encoding="utf-8").lower()
                # Never claim interactions/metrics/screenshots that did not occur.
                self.assertIn("did not occur", text, path.name)
                # Browser is not assumed available; no unauthorized auth/network.
                self.assertIn("do not assume a browser is available", text, path.name)
                self.assertIn("authenticate, or submit data without explicit authorization", text, path.name)
                self.assertIn("do not access the network", text, path.name)

    def test_includes_interaction_responsive_and_error_state_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "browser_qa"
            write_proposal("browser_qa", None, output)
            for path in self._wrapper_files(output):
                text = path.read_text(encoding="utf-8").lower()
                self.assertIn("interaction_review", text, path.name)
                self.assertIn("responsive_review", text, path.name)
                self.assertIn("frontend_error_state_review", text, path.name)


class MultiCliDesignDirectorTests(unittest.TestCase):
    """design_director must review visual coherence without editing or inventing requirements."""

    def _wrapper_files(self, output: Path) -> list[Path]:
        return [
            output / "portable/.agents/skills/design-director/SKILL.md",
            output / "codex/.codex/agents/design_director.toml",
            output / "claude/.claude/agents/design-director.md",
            output / "copilot/.github/agents/design-director.agent.md",
        ]

    def test_covers_hierarchy_spacing_typography_and_tokens_components(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "design_director"
            write_proposal("design_director", None, output)
            for path in self._wrapper_files(output):
                text = path.read_text(encoding="utf-8").lower()
                for marker in ("hierarchy", "spacing", "typography", "tokens", "component"):
                    self.assertIn(marker, text, f"{marker} missing from {path.name}")

    def test_distinguishes_evidence_inference_and_runtime_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "design_director"
            write_proposal("design_director", None, output)
            for path in self._wrapper_files(output):
                text = path.read_text(encoding="utf-8").lower()
                self.assertIn("evidence from source", text, path.name)
                self.assertIn("visual inference", text, path.name)
                self.assertIn("runtime validation", text, path.name)

    def test_does_not_edit_or_invent_design_requirements(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "design_director"
            write_proposal("design_director", None, output)
            for path in self._wrapper_files(output):
                text = path.read_text(encoding="utf-8").lower()
                self.assertIn("do not modify assets or code", text, path.name)
                self.assertIn("do not invent design requirements", text, path.name)
                # read-only edit prohibition is preserved too.
                self.assertIn("do not edit, create, or delete files", text, path.name)


class MultiCliScopeValidationTests(unittest.TestCase):
    """Lexical path validation and deterministic scope construction."""

    def test_rejects_absolute_parent_empty_dot_and_git_paths(self):
        for bad in ("/etc/passwd", "../secrets", "", "   ", ".", "./", ".git", ".git/config"):
            with self.subTest(path=bad):
                with self.assertRaises(ScopeError):
                    normalize_path(bad)

    def test_rejects_backslash_and_nul(self):
        with self.assertRaises(ScopeError):
            normalize_path("src\\generated")
        with self.assertRaises(ScopeError):
            normalize_path("src/\x00evil")

    def test_normalizes_trailing_and_duplicate_slashes_and_dot_components(self):
        self.assertEqual(normalize_path("src/"), "src")
        self.assertEqual(normalize_path("src//app/./mod/"), "src/app/mod")

    def test_build_scope_dedups_sorts_and_is_order_independent(self):
        first = build_scope("brief", ["tests/", "src/", "src"], ["src/generated/"])
        second = build_scope("brief", ["src", "tests"], ["src/generated"])
        self.assertEqual(first.allowed_paths, ("src", "tests"))
        self.assertEqual(first, second)

    def test_build_scope_requires_description_and_allow_path(self):
        with self.assertRaises(ScopeError):
            build_scope("", ["src"], [])
        with self.assertRaises(ScopeError):
            build_scope("brief", [], [])


class MultiCliImplementationAgentTests(unittest.TestCase):
    """implementation_agent is the only write role and only renders with an explicit scope."""

    def _scope(self):
        return build_scope("Implement the approved parser change", ["src/", "tests/"], ["src/generated/"])

    def _render(self, root: Path) -> Path:
        output = root / "impl"
        write_proposal("implementation_agent", None, output, scope=self._scope())
        return output

    def test_registry_lists_implementation_agent_last_and_deterministically(self):
        self.assertEqual(role_ids()[-1], "implementation_agent")

    def test_renders_all_four_targets_with_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            self.assertEqual(validate_proposal(output), [])
            for relative in (
                "portable/.agents/skills/implementation-agent/SKILL.md",
                "codex/.codex/agents/implementation_agent.toml",
                "codex/.codex/config.fragments/implementation_agent.toml",
                "claude/.claude/agents/implementation-agent.md",
                "copilot/.github/agents/implementation-agent.agent.md",
            ):
                self.assertTrue((output / relative).is_file(), relative)

    def test_missing_scope_is_rejected_at_api(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(MultiCliError, "requires an explicit invocation scope"):
                write_proposal("implementation_agent", None, Path(temporary) / "out")

    def test_scope_on_read_only_role_is_rejected_at_api(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(MultiCliError, "read-only role"):
                write_proposal("independent_reviewer", None, Path(temporary) / "out", scope=self._scope())

    def test_codex_wrapper_is_workspace_write_with_no_invented_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            toml_text = (output / "codex/.codex/agents/implementation_agent.toml").read_text()
            data = tomllib.loads(toml_text)
            self.assertEqual(data["sandbox_mode"], "workspace-write")
            self.assertNotIn("model", data)
            self.assertNotIn("writable_roots", data)
            self.assertNotIn("allowed_paths", data)
            self.assertNotIn("writable_paths", data)

    def test_manifest_schema_2_and_scope_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["schema_version"], 2)

            codex = manifest["targets"]["codex"]
            self.assertEqual(codex["enforcement"], {"mode": "sandboxed", "runtime_controls_generated": True, "controls": ["sandbox_mode"]})
            self.assertEqual(codex["sandbox"], {"mode": "workspace-write", "scope": "workspace", "path_scope_enforced": False})
            self.assertFalse(codex["sandbox"]["path_scope_enforced"])
            self.assertFalse(codex["path_validation"]["filesystem_resolved"])
            self.assertFalse(codex["path_validation"]["symlink_escape_checked"])
            self.assertTrue(codex["validation_required"])

            # blocked and allowed are serialized on every target; write_scope is not enforced.
            for target in TARGETS:
                write_scope = manifest["targets"][target]["write_scope"]
                self.assertEqual(write_scope["allowed_paths"], ["src", "tests"])
                self.assertEqual(write_scope["blocked_paths"], ["src/generated"])
                self.assertFalse(write_scope["enforced"])
                self.assertEqual(write_scope["mode"], "explicit-advisory")

            # Non-Codex targets stay advisory with no technical sandbox.
            for target in ("skill", "claude", "copilot"):
                section = manifest["targets"][target]
                self.assertEqual(section["enforcement"]["mode"], "advisory")
                self.assertFalse(section["enforcement"]["runtime_controls_generated"])
                self.assertEqual(section["sandbox"]["mode"], "none")

    def test_mandatory_advisory_warnings_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            warnings = json.loads((output / "manifest.json").read_text())["warnings"]
            self.assertIn("path scope is advisory and not technically enforced", warnings)
            self.assertIn("symlink/filesystem validation was not performed", warnings)
            self.assertIn("Codex workspace-write limits the workspace, not allowed_paths", warnings)

    def test_scope_prose_and_destructive_prohibitions_in_all_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = self._render(Path(temporary))
            for relative in (
                "portable/.agents/skills/implementation-agent/SKILL.md",
                "codex/.codex/agents/implementation_agent.toml",
                "claude/.claude/agents/implementation-agent.md",
                "copilot/.github/agents/implementation-agent.agent.md",
            ):
                text = (output / relative).read_text().lower()
                self.assertIn("implement the approved parser change", text, relative)
                self.assertIn("blocked paths override allowed paths", text, relative)
                self.assertIn("src/generated", text, relative)
                self.assertIn("preserve pre-existing local changes", text, relative)
                self.assertIn("destructive deletes or renames", text, relative)
                self.assertIn("do not commit", text, relative)

    def test_output_is_byte_deterministic_with_reordered_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "a"
            second = Path(temporary) / "b"
            write_proposal("implementation_agent", None, first, scope=build_scope("brief", ["tests/", "src/"], ["src/generated"]))
            write_proposal("implementation_agent", None, second, scope=build_scope("brief", ["src", "tests"], ["src/generated/"]))
            first_files = {p.relative_to(first).as_posix(): p.read_bytes() for p in first.rglob("*") if p.is_file()}
            second_files = {p.relative_to(second).as_posix(): p.read_bytes() for p in second.rglob("*") if p.is_file()}
            self.assertEqual(first_files, second_files)

    def test_render_writes_nothing_outside_output_and_leaves_codex_config(self):
        repo_config = Path(__file__).resolve().parent.parent / ".codex" / "config.toml"
        config_before = repo_config.read_text()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "impl"
            write_proposal("implementation_agent", None, output, scope=self._scope())
            outside = {p for p in root.rglob("*") if not p.is_relative_to(output) and p != output}
            self.assertEqual(outside, set())
        self.assertEqual(repo_config.read_text(), config_before)

    def test_scope_does_not_change_canonical_role_hash(self):
        # The scope is not part of the canonical role, so the role_hash is scope-independent.
        with tempfile.TemporaryDirectory() as temporary:
            a = Path(temporary) / "a"
            b = Path(temporary) / "b"
            write_proposal("implementation_agent", ["skill"], a, scope=build_scope("one", ["src"], []))
            write_proposal("implementation_agent", ["skill"], b, scope=build_scope("two different", ["tests"], ["tests/x"]))
            hash_a = json.loads((a / "manifest.json").read_text())["source"]["role_hash"]
            hash_b = json.loads((b / "manifest.json").read_text())["source"]["role_hash"]
            self.assertEqual(hash_a, hash_b)


class MultiCliImplementationAgentCliTests(unittest.TestCase):
    """CLI-level scope contract for the write role."""

    def _run(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_valid_command_writes_and_validates(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            code, out, err = self._run([
                "render-role", "implementation_agent",
                "--allow-path", "src/", "--allow-path", "tests/",
                "--block-path", "src/generated/",
                "--scope-description", "Implement the approved parser change",
                "--output", str(output),
            ])
            self.assertEqual(code, 0, err)
            self.assertIn("Wrote", out)
            self.assertEqual(validate_proposal(output), [])

    def test_missing_allow_path_fails_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            code, out, err = self._run([
                "render-role", "implementation_agent",
                "--scope-description", "x", "--output", str(output),
            ])
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertIn("at least one --allow-path and a non-empty --scope-description", err)
            self.assertFalse(output.exists())

    def test_missing_scope_description_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            code, _, err = self._run([
                "render-role", "implementation_agent",
                "--allow-path", "src/", "--output", str(output),
            ])
            self.assertEqual(code, 2)
            self.assertIn("at least one --allow-path and a non-empty --scope-description", err)
            self.assertFalse(output.exists())

    def test_scope_flags_rejected_on_read_only_role(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            code, _, err = self._run([
                "render-role", "independent_reviewer",
                "--allow-path", "src/", "--output", str(output),
            ])
            self.assertEqual(code, 2)
            self.assertIn("read-only", err)
            self.assertFalse(output.exists())

    def test_absolute_allow_path_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out"
            code, _, err = self._run([
                "render-role", "implementation_agent",
                "--allow-path", "/etc", "--scope-description", "x", "--output", str(output),
            ])
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())


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

    def test_global_role_and_target_catalog_commands_are_not_public(self):
        for command in ("roles", "targets"):
            with self.assertRaises(SystemExit) as exit_ctx:
                self._run([command])
            self.assertEqual(exit_ctx.exception.code, 2)

    def test_raw_provider_decision_flag_is_not_accepted(self):
        fixture = Path(__file__).parent / "fixtures/python-ml"
        with self.assertRaises(SystemExit) as exit_ctx:
            self._run([
                "adapter-options",
                str(fixture),
                "--provider-decision",
                "ml_reproducibility=leave_unresolved",
            ])
        self.assertEqual(exit_ctx.exception.code, 2)

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
