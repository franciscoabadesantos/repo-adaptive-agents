"""Acquire immutable canonical Git snapshots into a shared user cache."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator

from repo_adaptive_agents.shared_knowledge.cache_lock import cache_lock
from repo_adaptive_agents.shared_knowledge.consumer import _atomic_text, validate_catalog_path
from repo_adaptive_agents.shared_knowledge.repository import SharedKnowledgeError
from repo_adaptive_agents.shared_knowledge.storage import (
    clone_source,
    source_cache_directory,
    source_identity,
    user_cache_root,
)


class SourceUnavailable(SharedKnowledgeError):
    """The configured canonical Git source could not be refreshed."""


def removable_legacy_cache(
    consumer_root: Path,
    source_url: str,
    catalog_path: str,
) -> Path | None:
    """Return an exact legacy cache owned by this consumer, never unknown content."""
    path = consumer_root / ".team-knowledge" / "cache"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_dir():
        raise SharedKnowledgeError("legacy team knowledge cache must be a real directory")
    if {item.name for item in path.iterdir()} != {"source.git", "source.json"}:
        return None
    repository = path / "source.git"
    metadata_path = path / "source.json"
    if repository.is_symlink() or not repository.is_dir() or metadata_path.is_symlink():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    expected = {"schema_version": 1, "source_url": source_url, "catalog_path": catalog_path}
    if isinstance(metadata, dict) and "catalog_path" not in metadata:
        metadata = {**metadata, "catalog_path": "."}
    if metadata != expected:
        return None
    bare = _run_git(
        ["--git-dir", str(repository), "rev-parse", "--is-bare-repository"],
        cwd=consumer_root,
    )
    return path if bare.returncode == 0 and bare.stdout.strip() == "true" else None


def remove_legacy_cache(consumer_root: Path, source_url: str, catalog_path: str) -> bool:
    """Remove only a legacy cache that still passes the complete ownership check."""
    path = removable_legacy_cache(consumer_root, source_url, catalog_path)
    if path is None:
        return False
    ignore = consumer_root / ".team-knowledge" / ".gitignore"
    if ignore.is_symlink() or (ignore.exists() and not ignore.is_file()):
        raise SharedKnowledgeError(".team-knowledge/.gitignore must be a regular file")
    shutil.rmtree(path)
    if ignore.exists():
        lines = [line for line in ignore.read_text(encoding="utf-8").splitlines() if line != "/cache/"]
        content = "\n".join(lines).rstrip()
        _atomic_text(ignore, content + ("\n" if content else ""))
    return True


def _run_git(
    arguments: list[str],
    *,
    cwd: Path,
    binary: bool = False,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
    )


class GitKnowledgeSource:
    def __init__(
        self,
        consumer_root: Path,
        *,
        cache_root: Path | None = None,
        runtime_root: Path | None = None,
    ) -> None:
        self.consumer_root = consumer_root
        self.cache_root = user_cache_root() if cache_root is None else cache_root
        self.runtime = (
            consumer_root / ".team-knowledge" / "runtime"
            if runtime_root is None
            else runtime_root
        )
        self.cache: Path | None = None
        self.cache_metadata: Path | None = None
        self.cache_mode = "persistent"
        self._ephemeral: tempfile.TemporaryDirectory[str] | None = None

    def _paths(self, source_url: str, *, offline: bool) -> tuple[Path, Path, Path, Path]:
        directory = source_cache_directory(source_url, self.consumer_root, root=self.cache_root)
        if self.runtime.is_symlink() or (self.runtime.exists() and not self.runtime.is_dir()):
            raise SharedKnowledgeError("team knowledge runtime must be a real directory")
        root = self.cache_root
        sources = root / "sources"
        for path, label in ((root, "root"), (sources, "sources")):
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise SharedKnowledgeError(f"team knowledge cache {label} must be a real directory")
        if offline and not directory.exists():
            raise SourceUnavailable("canonical team knowledge is not cached; online bootstrap is required")
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            sources.mkdir(exist_ok=True, mode=0o700)
            if not offline:
                descriptor, probe = tempfile.mkstemp(prefix=".write-probe-", dir=sources)
                os.close(descriptor)
                Path(probe).unlink()
        except OSError as error:
            if offline:
                raise SourceUnavailable("shared team knowledge cache is unavailable in offline mode") from error
            self._use_temporary_cache()
            directory = source_cache_directory(source_url, self.consumer_root, root=self.cache_root)
            sources = directory.parent
            sources.mkdir(parents=True, mode=0o700)
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise SharedKnowledgeError("team knowledge cache source must be a real directory")
        cache = directory / "repository.git"
        metadata = directory / "metadata.json"
        lock = sources / f".{directory.name}.lock"
        if cache.is_symlink() or metadata.is_symlink():
            raise SharedKnowledgeError("team knowledge source cache files must not be symlinks")
        self.cache = cache
        self.cache_metadata = metadata
        return directory, cache, metadata, lock

    def _use_temporary_cache(self) -> None:
        self._ephemeral = tempfile.TemporaryDirectory(prefix="team-knowledge-cache-")
        self.cache_root = Path(self._ephemeral.name)
        self.cache_mode = "temporary"

    def _expected_metadata(self, source_url: str) -> dict[str, object]:
        identity = source_cache_directory(
            source_url,
            self.consumer_root,
            root=Path("."),
        ).name
        return {"schema_version": 2, "source_identity_sha256": identity}

    @staticmethod
    def _write_metadata(path: Path, value: dict[str, object]) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def acquire(
        self,
        source_url: str,
        ref: str,
        *,
        catalog_path: str = ".",
        offline: bool = False,
        commit: str | None = None,
    ) -> str:
        catalog_path = validate_catalog_path(catalog_path)
        directory, cache, metadata_path, lock_path = self._paths(source_url, offline=offline)
        expected = self._expected_metadata(source_url)
        with cache_lock(lock_path):
            if not directory.exists():
                if offline:
                    raise SourceUnavailable(
                        "canonical team knowledge is not cached; online bootstrap is required"
                    )
                staging = directory.with_name(f".{directory.name}.{os.getpid()}.tmp")
                shutil.rmtree(staging, ignore_errors=True)
                staging.mkdir(mode=0o700)
                staged_cache = staging / "repository.git"
                result = _run_git(
                    [
                        "clone",
                        "--bare",
                        "--",
                        clone_source(source_url, self.consumer_root),
                        str(staged_cache),
                    ],
                    cwd=self.consumer_root,
                )
                if result.returncode != 0:
                    shutil.rmtree(staging, ignore_errors=True)
                    detail = (
                        result.stderr.strip().splitlines()[-1]
                        if result.stderr.strip()
                        else "git clone failed"
                    )
                    raise SourceUnavailable(f"could not acquire canonical team knowledge: {detail}")
                self._write_metadata(staging / "metadata.json", expected)
                os.replace(staging, directory)
            if not cache.is_dir():
                raise SharedKnowledgeError("team knowledge source cache is not a directory")
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SharedKnowledgeError(
                    "team knowledge source cache provenance is missing or invalid"
                ) from error
            if metadata != expected:
                raise SharedKnowledgeError(
                    "team knowledge source cache belongs to a different canonical source"
                )
            origin = _run_git(
                ["--git-dir", str(cache), "config", "--get", "remote.origin.url"],
                cwd=self.consumer_root,
            )
            if (
                origin.returncode != 0
                or source_identity(origin.stdout.strip(), self.consumer_root)
                != source_identity(source_url, self.consumer_root)
            ):
                raise SharedKnowledgeError("team knowledge source cache origin does not match its source")
            if offline:
                if commit is None:
                    raise SharedKnowledgeError("offline source access requires a locked source commit")
                verify = _run_git(
                    ["--git-dir", str(cache), "cat-file", "-e", f"{commit}^{{commit}}"],
                    cwd=self.consumer_root,
                )
                if verify.returncode != 0:
                    raise SourceUnavailable(f"locked canonical source commit is not cached: {commit}")
                return commit
            result = _run_git(
                ["--git-dir", str(cache), "fetch", "--no-tags", "origin", ref],
                cwd=self.consumer_root,
            )
            if result.returncode != 0:
                detail = (
                    result.stderr.strip().splitlines()[-1]
                    if result.stderr.strip()
                    else "git fetch failed"
                )
                raise SourceUnavailable(f"could not refresh canonical team knowledge: {detail}")
            resolved = _run_git(
                ["--git-dir", str(cache), "rev-parse", "--verify", "FETCH_HEAD^{commit}"],
                cwd=self.consumer_root,
            )
        if resolved.returncode != 0 or not resolved.stdout.strip():
            raise SourceUnavailable(f"canonical ref could not be resolved: {ref}")
        fetched_commit = resolved.stdout.strip()
        if catalog_path == ".":
            return fetched_commit
        knowledge_revision = _run_git(
            [
                "--git-dir",
                str(self.cache),
                "log",
                "-1",
                "--format=%H",
                fetched_commit,
                "--",
                catalog_path,
            ],
            cwd=self.consumer_root,
        )
        if knowledge_revision.returncode != 0 or not knowledge_revision.stdout.strip():
            raise SourceUnavailable(
                f"canonical catalog path has no revision at requested ref: {catalog_path}"
            )
        return knowledge_revision.stdout.strip()

    def revision_for(self, commit: str, source_path: str, *, catalog_path: str = ".") -> str:
        catalog_path = validate_catalog_path(catalog_path)
        git_path = source_path if catalog_path == "." else f"{catalog_path}/{source_path}"
        result = _run_git(
            [
                "--git-dir",
                str(self._required_cache()),
                "log",
                "-1",
                "--format=%H",
                commit,
                "--",
                git_path,
            ],
            cwd=self.consumer_root,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise SharedKnowledgeError(f"cannot derive Git revision for canonical Skill: {source_path}")
        return result.stdout.strip()

    @contextmanager
    def snapshot(self, commit: str, *, catalog_path: str = ".") -> Iterator[Path]:
        catalog_path = validate_catalog_path(catalog_path)
        self.runtime.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="source-", dir=self.runtime) as temporary:
            root = Path(temporary)
            arguments = ["--git-dir", str(self._required_cache()), "archive", "--format=tar", commit]
            if catalog_path != ".":
                arguments.extend(["--", catalog_path])
            result = _run_git(
                arguments,
                cwd=self.consumer_root,
                binary=True,
            )
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                raise SharedKnowledgeError(f"cannot read pinned canonical source {commit}: {detail}")
            self._extract(result.stdout, root)
            yield root if catalog_path == "." else root.joinpath(*PurePosixPath(catalog_path).parts)

    def _required_cache(self) -> Path:
        if self.cache is None:
            raise SharedKnowledgeError("canonical source must be acquired before it can be read")
        return self.cache

    @staticmethod
    def _extract(archive: bytes, destination: Path) -> None:
        total = 0
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            for member in bundle.getmembers():
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise SharedKnowledgeError("canonical Git archive contains an unsafe path")
                target = destination.joinpath(*relative.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if member.issym() or member.islnk():
                    raise SharedKnowledgeError(f"canonical Git archive contains symlink: {member.name}")
                if not member.isfile():
                    raise SharedKnowledgeError(f"canonical Git archive contains unsafe entry: {member.name}")
                source = bundle.extractfile(member)
                if source is None:
                    raise SharedKnowledgeError(f"cannot read canonical Git archive entry: {member.name}")
                data = source.read()
                total += len(data)
                if total > 20_000_000:
                    raise SharedKnowledgeError("canonical Git archive is too large for this product slice")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(member.mode & 0o777)
