"""Preview and safely install a validated adapter bundle into a local repository."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .generator import _repo_relative
from .validator import validate_adapter_bundle


class AdapterInstallError(ValueError):
    """Raised when an adapter bundle cannot be installed without overwriting state."""


@dataclass(frozen=True)
class InstallEntry:
    source_path: str
    destination_path: str
    status: str
    reason: str = ""


@dataclass(frozen=True)
class InstallPlan:
    entries: tuple[InstallEntry, ...]

    @property
    def additions(self) -> tuple[InstallEntry, ...]:
        return tuple(item for item in self.entries if item.status == "addition")

    @property
    def conflicts(self) -> tuple[InstallEntry, ...]:
        return tuple(item for item in self.entries if item.status == "conflict")

    @property
    def unchanged(self) -> tuple[InstallEntry, ...]:
        return tuple(item for item in self.entries if item.status == "unchanged")


@dataclass(frozen=True)
class InstallResult:
    created: tuple[str, ...]
    unchanged: tuple[str, ...]


def _parent_conflict(destination: Path, relative: str) -> str | None:
    cursor = destination
    for part in Path(relative).parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink():
            return f"parent path is a symlink: {cursor.relative_to(destination).as_posix()}"
        if cursor.exists() and not cursor.is_dir():
            return f"parent path is not a directory: {cursor.relative_to(destination).as_posix()}"
    return None


def _installable_sources(bundle: Path, manifest: dict) -> dict[str, Path]:
    mapped: dict[str, Path] = {}
    for role_id, section in sorted(manifest.get("roles", {}).items()):
        prefix = f"roles/{role_id}/"
        for entry in section.get("files", []):
            proposal_relative = entry.get("path", "")
            if not proposal_relative.startswith(prefix):
                raise AdapterInstallError(
                    f"Adapter file escapes its role prefix: {proposal_relative!r}"
                )
            inner = proposal_relative.removeprefix(prefix)
            destination_relative = _repo_relative(inner)
            if destination_relative is None:
                continue
            source = bundle / proposal_relative
            cursor = source
            while cursor != bundle:
                if cursor.is_symlink():
                    raise AdapterInstallError(
                        f"Adapter source path contains a symlink: {proposal_relative!r}"
                    )
                cursor = cursor.parent
            if not source.resolve().is_relative_to(bundle):
                raise AdapterInstallError(
                    f"Adapter source escapes the bundle: {proposal_relative!r}"
                )
            previous = mapped.get(destination_relative)
            if previous is not None and previous != source:
                raise AdapterInstallError(
                    f"Multiple adapter files map to {destination_relative!r}"
                )
            mapped[destination_relative] = source
    return mapped


def plan_adapter_install(
    bundle_dir: str | Path,
    destination_repo: str | Path,
) -> InstallPlan:
    """Build a read-only plan. Existing, differing paths are conflicts, never updates."""
    bundle = Path(bundle_dir).expanduser().resolve()
    destination = Path(destination_repo).expanduser().resolve()
    if not destination.is_dir():
        raise AdapterInstallError(
            f"Destination repository is not a directory: {destination_repo}"
        )
    issues = validate_adapter_bundle(bundle)
    if issues:
        raise AdapterInstallError("Invalid adapter bundle: " + "; ".join(issues))
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("selection_confirmation") != "caller_attested":
        raise AdapterInstallError(
            "Adapter installation requires a bundle generated after explicit user "
            "selection of roles and harness targets"
        )

    entries: list[InstallEntry] = []
    for relative, source in sorted(_installable_sources(bundle, manifest).items()):
        target = destination / relative
        reason = _parent_conflict(destination, relative)
        if reason:
            entries.append(InstallEntry(source.relative_to(bundle).as_posix(), relative, "conflict", reason))
        elif target.is_symlink():
            entries.append(InstallEntry(source.relative_to(bundle).as_posix(), relative, "conflict", "destination is a symlink"))
        elif target.is_file():
            status = "unchanged" if target.read_bytes() == source.read_bytes() else "conflict"
            detail = "" if status == "unchanged" else "existing content differs"
            entries.append(InstallEntry(source.relative_to(bundle).as_posix(), relative, status, detail))
        elif target.exists():
            entries.append(InstallEntry(source.relative_to(bundle).as_posix(), relative, "conflict", "destination is not a regular file"))
        else:
            entries.append(InstallEntry(source.relative_to(bundle).as_posix(), relative, "addition"))
    return InstallPlan(tuple(entries))


def _create_parent_directories(
    destination: Path,
    parent: Path,
    created_directories: list[Path],
) -> None:
    missing: list[Path] = []
    cursor = parent
    while cursor != destination and not cursor.exists() and not cursor.is_symlink():
        missing.append(cursor)
        cursor = cursor.parent
    if cursor.is_symlink() or (cursor.exists() and not cursor.is_dir()):
        raise AdapterInstallError("Destination parent changed after planning")
    for directory in reversed(missing):
        directory.mkdir()
        created_directories.append(directory)


def apply_adapter_install(
    bundle_dir: str | Path,
    destination_repo: str | Path,
) -> InstallResult:
    """Install additions only. Any conflict blocks the whole operation before writing."""
    bundle = Path(bundle_dir).expanduser().resolve()
    destination = Path(destination_repo).expanduser().resolve()
    plan = plan_adapter_install(bundle, destination)
    if plan.conflicts:
        paths = ", ".join(item.destination_path for item in plan.conflicts)
        raise AdapterInstallError(f"Installation blocked by conflicts: {paths}")

    created_files: list[Path] = []
    created_directories: list[Path] = []
    try:
        for entry in plan.additions:
            source = bundle / entry.source_path
            target = destination / entry.destination_path
            _create_parent_directories(destination, target.parent, created_directories)
            if _parent_conflict(destination, entry.destination_path):
                raise AdapterInstallError("Destination parent changed after planning")
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            created_files.append(target)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(source.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
    except Exception as error:
        for path in reversed(created_files):
            try:
                path.unlink()
            except OSError:
                pass
        for path in reversed(created_directories):
            try:
                path.rmdir()
            except OSError:
                pass
        if isinstance(error, AdapterInstallError):
            raise
        raise AdapterInstallError(f"Installation failed and created files were rolled back: {error}") from error

    return InstallResult(
        created=tuple(path.relative_to(destination).as_posix() for path in created_files),
        unchanged=tuple(item.destination_path for item in plan.unchanged),
    )
