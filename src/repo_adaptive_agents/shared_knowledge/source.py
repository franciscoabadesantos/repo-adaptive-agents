"""Maintain a durable local Git replica of each canonical knowledge source."""

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
    registered_source_checkout,
    source_cache_directory,
    source_identity,
    source_replica_directory,
    user_data_root,
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
        data_root: Path | None = None,
        runtime_root: Path | None = None,
    ) -> None:
        self.consumer_root = consumer_root
        self.data_root = user_data_root() if data_root is None else data_root
        self.runtime = (
            consumer_root / ".team-knowledge" / "runtime"
            if runtime_root is None
            else runtime_root
        )
        self.repository: Path | None = None
        self.metadata_path: Path | None = None
        self.replica_mode = "persistent"
        self.used_offline_fallback = False
        self.resolved_ref_commit: str | None = None
        self._ephemeral: tempfile.TemporaryDirectory[str] | None = None

    def _paths(self, source_url: str, *, offline: bool) -> tuple[Path, Path, Path, Path]:
        directory = source_replica_directory(source_url, self.consumer_root, root=self.data_root)
        registered = registered_source_checkout(
            source_url,
            self.consumer_root,
            root=self.data_root,
        )
        if self.runtime.is_symlink() or (self.runtime.exists() and not self.runtime.is_dir()):
            raise SharedKnowledgeError("team knowledge runtime must be a real directory")
        root = self.data_root
        sources = root / "sources"
        for path, label in ((root, "root"), (sources, "sources")):
            if path.is_symlink() or (path.exists() and not path.is_dir()):
                raise SharedKnowledgeError(f"team knowledge data {label} must be a real directory")
        if not directory.exists() and registered is None:
            self._migrate_shared_cache(source_url, directory)
        if offline and not directory.exists() and registered is None:
            raise SourceUnavailable("canonical team knowledge has no local replica; online bootstrap is required")
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            sources.mkdir(exist_ok=True, mode=0o700)
            if not offline:
                descriptor, probe = tempfile.mkstemp(prefix=".write-probe-", dir=sources)
                os.close(descriptor)
                Path(probe).unlink()
        except OSError as error:
            if offline:
                raise SourceUnavailable("local canonical replica is unavailable in offline mode") from error
            self._use_temporary_replica()
            directory = source_replica_directory(source_url, self.consumer_root, root=self.data_root)
            sources = directory.parent
            sources.mkdir(parents=True, mode=0o700)
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise SharedKnowledgeError("team knowledge source replica must be a real directory")
        repository = registered if registered is not None else directory / "repository"
        metadata = directory / "metadata.json"
        lock = sources / f".{directory.name}.lock"
        if repository.is_symlink() or metadata.is_symlink():
            raise SharedKnowledgeError("team knowledge source replica files must not be symlinks")
        self.repository = repository
        self.metadata_path = metadata
        return directory, repository, metadata, lock

    def _use_temporary_replica(self) -> None:
        self._ephemeral = tempfile.TemporaryDirectory(prefix="team-knowledge-replica-")
        self.data_root = Path(self._ephemeral.name)
        self.replica_mode = "temporary"

    def _expected_metadata(self, source_url: str) -> dict[str, object]:
        identity = source_replica_directory(
            source_url,
            self.consumer_root,
            root=Path("."),
        ).name
        return {"schema_version": 3, "source_identity_sha256": identity, "refs": {}}

    @staticmethod
    def _write_metadata(path: Path, value: dict[str, object]) -> None:
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def _migrate_shared_cache(self, source_url: str, directory: Path) -> None:
        """Seed the persistent replica from the previous shared bare cache, if valid."""
        legacy = source_cache_directory(source_url, self.consumer_root)
        bare = legacy / "repository.git"
        metadata = legacy / "metadata.json"
        if not bare.is_dir() or metadata.is_symlink() or not metadata.is_file():
            return
        try:
            value = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return
        expected_id = self._expected_metadata(source_url)["source_identity_sha256"]
        if value != {"schema_version": 2, "source_identity_sha256": expected_id}:
            return
        directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        staging = directory.with_name(f".{directory.name}.{os.getpid()}.migration")
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(mode=0o700)
        result = _run_git(
            ["clone", "--", str(bare), str(staging / "repository")],
            cwd=self.consumer_root,
        )
        if result.returncode != 0:
            shutil.rmtree(staging, ignore_errors=True)
            return
        origin = clone_source(source_url, self.consumer_root)
        configured = _run_git(["remote", "set-url", "origin", origin], cwd=staging / "repository")
        if configured.returncode != 0:
            shutil.rmtree(staging, ignore_errors=True)
            return
        self._write_metadata(staging / "metadata.json", self._expected_metadata(source_url))
        try:
            os.replace(staging, directory)
        except FileExistsError:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _metadata(path: Path, expected: dict[str, object]) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SharedKnowledgeError(
                "local canonical replica provenance is missing or invalid"
            ) from error
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != expected["schema_version"]
            or value.get("source_identity_sha256") != expected["source_identity_sha256"]
            or not isinstance(value.get("refs"), dict)
            or any(not isinstance(key, str) or not isinstance(commit, str) for key, commit in value["refs"].items())
        ):
            raise SharedKnowledgeError("local canonical replica belongs to a different source or is invalid")
        return value

    @staticmethod
    def _verify_commit(repository: Path, commit: str) -> bool:
        result = _run_git(["cat-file", "-e", f"{commit}^{{commit}}"], cwd=repository)
        return result.returncode == 0

    def _try_fast_forward_checkout(self, repository: Path, ref: str, commit: str) -> None:
        """Keep an ordinary clean branch visibly current without disturbing active work."""
        branch = _run_git(["branch", "--show-current"], cwd=repository)
        status = _run_git(["status", "--porcelain"], cwd=repository)
        if branch.returncode != 0 or status.returncode != 0:
            return
        if branch.stdout.strip() != ref or status.stdout.strip():
            return
        _run_git(["merge", "--ff-only", commit], cwd=repository)

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
        directory, repository, metadata_path, lock_path = self._paths(source_url, offline=offline)
        expected = self._expected_metadata(source_url)
        with cache_lock(lock_path):
            if not directory.exists():
                if offline:
                    if not repository.is_dir():
                        raise SourceUnavailable(
                            "canonical team knowledge has no local replica; online bootstrap is required"
                        )
                    directory.mkdir(mode=0o700)
                    self._write_metadata(metadata_path, expected)
                elif repository.is_dir():
                    directory.mkdir(mode=0o700)
                    self._write_metadata(metadata_path, expected)
                else:
                    staging = directory.with_name(f".{directory.name}.{os.getpid()}.tmp")
                    shutil.rmtree(staging, ignore_errors=True)
                    staging.mkdir(mode=0o700)
                    staged_repository = staging / "repository"
                    result = _run_git(
                        [
                            "clone",
                            "--",
                            clone_source(source_url, self.consumer_root),
                            str(staged_repository),
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
                        raise SourceUnavailable(f"could not create local canonical replica: {detail}")
                    self._write_metadata(staging / "metadata.json", expected)
                    os.replace(staging, directory)
            if not repository.is_dir() or not (repository / ".git").is_dir():
                raise SharedKnowledgeError("local canonical replica is not a Git working repository")
            metadata = self._metadata(metadata_path, expected)
            origin = _run_git(
                ["config", "--get", "remote.origin.url"],
                cwd=repository,
            )
            if (
                origin.returncode != 0
                or source_identity(origin.stdout.strip(), self.consumer_root)
                != source_identity(source_url, self.consumer_root)
            ):
                raise SharedKnowledgeError("local canonical replica origin does not match its source")
            if offline:
                selected = commit or metadata["refs"].get(ref)
                if selected is None:
                    resolved = _run_git(["rev-parse", "--verify", f"origin/{ref}^{{commit}}"], cwd=repository)
                    selected = resolved.stdout.strip() if resolved.returncode == 0 else None
                if selected is None or not self._verify_commit(repository, selected):
                    raise SourceUnavailable(f"canonical source ref is not available locally: {ref}")
                self.resolved_ref_commit = selected
                return self._catalog_revision(repository, selected, catalog_path)
            result = _run_git(
                ["fetch", "--no-tags", "origin", ref],
                cwd=repository,
            )
            if result.returncode != 0:
                fallback = metadata["refs"].get(ref)
                if fallback is not None and self._verify_commit(repository, fallback):
                    self.used_offline_fallback = True
                    self.resolved_ref_commit = fallback
                    return self._catalog_revision(repository, fallback, catalog_path)
                detail = (
                    result.stderr.strip().splitlines()[-1]
                    if result.stderr.strip()
                    else "git fetch failed"
                )
                raise SourceUnavailable(f"could not refresh canonical team knowledge: {detail}")
            resolved = _run_git(
                ["rev-parse", "--verify", "FETCH_HEAD^{commit}"],
                cwd=repository,
            )
            if resolved.returncode != 0 or not resolved.stdout.strip():
                raise SourceUnavailable(f"canonical ref could not be resolved: {ref}")
            fetched_commit = resolved.stdout.strip()
            self.resolved_ref_commit = fetched_commit
            metadata["refs"][ref] = fetched_commit
            self._write_metadata(metadata_path, metadata)
            self._try_fast_forward_checkout(repository, ref, fetched_commit)
        return self._catalog_revision(repository, fetched_commit, catalog_path)

    def _catalog_revision(self, repository: Path, commit: str, catalog_path: str) -> str:
        if catalog_path == ".":
            return commit
        knowledge_revision = _run_git(
            [
                "log",
                "-1",
                "--format=%H",
                commit,
                "--",
                catalog_path,
            ],
            cwd=repository,
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
                "log",
                "-1",
                "--format=%H",
                commit,
                "--",
                git_path,
            ],
            cwd=self._required_repository(),
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
            arguments = ["archive", "--format=tar", commit]
            if catalog_path != ".":
                arguments.extend(["--", catalog_path])
            result = _run_git(
                arguments,
                cwd=self._required_repository(),
                binary=True,
            )
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                raise SharedKnowledgeError(f"cannot read pinned canonical source {commit}: {detail}")
            self._extract(result.stdout, root)
            yield root if catalog_path == "." else root.joinpath(*PurePosixPath(catalog_path).parts)

    def _required_repository(self) -> Path:
        if self.repository is None:
            raise SharedKnowledgeError("canonical source must be acquired before it can be read")
        return self.repository

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
