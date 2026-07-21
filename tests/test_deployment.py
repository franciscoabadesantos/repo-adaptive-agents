import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from repo_adaptive_agents.cli import main
from repo_adaptive_agents.multi_cli import (
    AdapterInstallError,
    apply_adapter_install,
    plan_adapter_install,
    validate_adapter_bundle,
    write_adapter_bundle,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _bundle(root: Path, targets=None) -> Path:
    output = root / "bundle"
    write_adapter_bundle(
        FIXTURES / "team-fullstack",
        targets or ["skill"],
        ["repo_explorer"],
        output,
        selection_confirmed=True,
    )
    return output


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


class InstallPlanTests(unittest.TestCase):
    def test_unconfirmed_bundle_cannot_be_previewed_or_installed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            write_adapter_bundle(
                FIXTURES / "team-fullstack",
                ["skill"],
                ["repo_explorer"],
                bundle,
            )
            destination = root / "repo"
            destination.mkdir()

            with self.assertRaisesRegex(AdapterInstallError, "explicit user selection"):
                plan_adapter_install(bundle, destination)
            self.assertEqual(_files(destination), {})

    def test_preview_reports_additions_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = _bundle(root)
            destination = root / "repo"
            destination.mkdir()
            before = _files(destination)

            plan = plan_adapter_install(bundle, destination)

            self.assertEqual(len(plan.additions), 1)
            self.assertEqual(plan.conflicts, ())
            self.assertEqual(plan.unchanged, ())
            self.assertEqual(
                plan.additions[0].destination_path,
                ".agents/skills/repo-explorer/SKILL.md",
            )
            self.assertEqual(_files(destination), before)

    def test_invalid_bundle_and_missing_destination_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = root / "invalid"
            invalid.mkdir()
            destination = root / "repo"
            destination.mkdir()
            with self.assertRaisesRegex(AdapterInstallError, "Invalid adapter bundle"):
                plan_adapter_install(invalid, destination)
            with self.assertRaisesRegex(AdapterInstallError, "not a directory"):
                plan_adapter_install(invalid, root / "missing")

    def test_symlink_parent_is_a_conflict_and_is_never_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = _bundle(root)
            destination = root / "repo"
            outside = root / "outside"
            destination.mkdir()
            outside.mkdir()
            (destination / ".agents").symlink_to(outside, target_is_directory=True)

            plan = plan_adapter_install(bundle, destination)

            self.assertEqual(len(plan.conflicts), 1)
            self.assertIn("symlink", plan.conflicts[0].reason)
            with self.assertRaisesRegex(AdapterInstallError, "blocked by conflicts"):
                apply_adapter_install(bundle, destination)
            self.assertEqual(_files(outside), {})

    def test_symlink_inside_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = _bundle(root)
            destination = root / "repo"
            destination.mkdir()
            source = bundle / "roles/repo_explorer/portable/.agents/skills/repo-explorer/SKILL.md"
            external = root / "external.md"
            external.write_bytes(source.read_bytes())
            source.unlink()
            source.symlink_to(external)

            issues = validate_adapter_bundle(bundle)
            self.assertTrue(any("contains a symlink" in issue for issue in issues))
            with self.assertRaisesRegex(AdapterInstallError, "Invalid adapter bundle"):
                plan_adapter_install(bundle, destination)


class ApplyInstallTests(unittest.TestCase):
    def test_apply_creates_additions_and_second_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = _bundle(root)
            destination = root / "repo"
            destination.mkdir()

            first = apply_adapter_install(bundle, destination)
            second_plan = plan_adapter_install(bundle, destination)
            second = apply_adapter_install(bundle, destination)

            expected = ".agents/skills/repo-explorer/SKILL.md"
            self.assertEqual(first.created, (expected,))
            self.assertTrue((destination / expected).is_file())
            self.assertEqual(second_plan.additions, ())
            self.assertEqual(len(second_plan.unchanged), 1)
            self.assertEqual(second.created, ())
            self.assertEqual(second.unchanged, (expected,))

    def test_one_conflict_blocks_all_additions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = _bundle(root, ["skill", "codex"])
            destination = root / "repo"
            conflict = destination / ".agents/skills/repo-explorer/SKILL.md"
            conflict.parent.mkdir(parents=True)
            conflict.write_text("user-owned", encoding="utf-8")

            plan = plan_adapter_install(bundle, destination)
            self.assertEqual(len(plan.conflicts), 1)
            self.assertEqual(len(plan.additions), 2)
            with self.assertRaisesRegex(AdapterInstallError, "blocked by conflicts"):
                apply_adapter_install(bundle, destination)

            self.assertEqual(conflict.read_text(encoding="utf-8"), "user-owned")
            self.assertFalse((destination / ".codex").exists())

    def test_failure_rolls_back_only_files_created_by_this_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = _bundle(root, ["skill", "codex"])
            destination = root / "repo"
            destination.mkdir()
            keep = destination / "keep.txt"
            keep.write_text("preserve", encoding="utf-8")
            real_open = os.open
            calls = 0

            def flaky_open(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("simulated write failure")
                return real_open(*args, **kwargs)

            with patch("repo_adaptive_agents.multi_cli.deployment.os.open", side_effect=flaky_open):
                with self.assertRaisesRegex(AdapterInstallError, "rolled back"):
                    apply_adapter_install(bundle, destination)

            self.assertEqual(_files(destination), {"keep.txt": b"preserve"})


class InstallCliTests(unittest.TestCase):
    @staticmethod
    def _run(argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_previews_by_default_and_requires_separate_install_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = _bundle(root)
            destination = root / "repo"
            destination.mkdir()

            code, preview, error = self._run([
                "install-adapters", str(bundle), str(destination)
            ])
            self.assertEqual(code, 0, error)
            self.assertIn("1 addition(s)", preview)
            self.assertIn("Preview only; no files were written", preview)
            self.assertIn("request separate installation approval", preview)
            self.assertEqual(_files(destination), {})

            code, unconfirmed, error = self._run([
                "install-adapters", str(bundle), str(destination), "--apply"
            ])
            self.assertEqual(code, 2)
            self.assertEqual(unconfirmed, "")
            self.assertIn("requires --confirm-install", error)
            self.assertEqual(_files(destination), {})

            code, applied, error = self._run([
                "install-adapters", str(bundle), str(destination), "--apply", "--confirm-install"
            ])
            self.assertEqual(code, 0, error)
            self.assertIn("Installed 1 file(s)", applied)
            self.assertIn(".agents/skills/repo-explorer/SKILL.md", _files(destination))

    def test_install_confirmation_without_apply_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = _bundle(root)
            destination = root / "repo"
            destination.mkdir()

            code, stdout, error = self._run([
                "install-adapters", str(bundle), str(destination), "--confirm-install"
            ])
            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertIn("valid only together with --apply", error)
            self.assertEqual(_files(destination), {})


if __name__ == "__main__":
    unittest.main()
