"""Acquire immutable canonical Git snapshots into an ignored local cache."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterator

from repo_adaptive_agents.shared_knowledge.catalog import SharedKnowledgeError


class SourceUnavailable(SharedKnowledgeError):
    """The configured canonical Git source could not be refreshed."""


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
    def __init__(self, consumer_root: Path) -> None:
        self.consumer_root = consumer_root
        self.state = consumer_root / ".team-knowledge"
        self.cache = self.state / "cache" / "source.git"
        self.cache_metadata = self.state / "cache" / "source.json"
        self.runtime = self.state / "runtime"

    def acquire(self, source_url: str, ref: str, *, offline: bool = False, commit: str | None = None) -> str:
        if self.cache.parent.is_symlink() or self.runtime.is_symlink():
            raise SharedKnowledgeError("team knowledge cache and runtime paths must not be symlinks")
        if self.cache.is_symlink():
            raise SharedKnowledgeError("team knowledge source cache must not be a symlink")
        if not self.cache.exists():
            if offline:
                raise SourceUnavailable("canonical team knowledge is not cached; online bootstrap is required")
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            result = _run_git(["clone", "--bare", "--", source_url, str(self.cache)], cwd=self.consumer_root)
            if result.returncode != 0:
                if self.cache.exists():
                    shutil.rmtree(self.cache, ignore_errors=True)
                detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "git clone failed"
                raise SourceUnavailable(f"could not acquire canonical team knowledge: {detail}")
            self.cache_metadata.write_text(
                json.dumps({"schema_version": 1, "source_url": source_url}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        if not self.cache.is_dir():
            raise SharedKnowledgeError("team knowledge source cache is not a directory")
        try:
            metadata = json.loads(self.cache_metadata.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SharedKnowledgeError("team knowledge source cache provenance is missing or invalid") from error
        if metadata != {"schema_version": 1, "source_url": source_url}:
            raise SharedKnowledgeError("team knowledge source cache belongs to a different canonical source")
        if offline:
            if commit is None:
                raise SharedKnowledgeError("offline source access requires a locked source commit")
            verify = _run_git(["--git-dir", str(self.cache), "cat-file", "-e", f"{commit}^{{commit}}"], cwd=self.consumer_root)
            if verify.returncode != 0:
                raise SourceUnavailable(f"locked canonical source commit is not cached: {commit}")
            return commit
        result = _run_git(
            ["--git-dir", str(self.cache), "fetch", "--no-tags", "origin", ref],
            cwd=self.consumer_root,
        )
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "git fetch failed"
            raise SourceUnavailable(f"could not refresh canonical team knowledge: {detail}")
        resolved = _run_git(
            ["--git-dir", str(self.cache), "rev-parse", "--verify", "FETCH_HEAD^{commit}"],
            cwd=self.consumer_root,
        )
        if resolved.returncode != 0 or not resolved.stdout.strip():
            raise SourceUnavailable(f"canonical ref could not be resolved: {ref}")
        return resolved.stdout.strip()

    def revision_for(self, commit: str, source_path: str) -> str:
        result = _run_git(
            ["--git-dir", str(self.cache), "log", "-1", "--format=%H", commit, "--", source_path],
            cwd=self.consumer_root,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise SharedKnowledgeError(f"cannot derive Git revision for canonical Skill: {source_path}")
        return result.stdout.strip()

    @contextmanager
    def snapshot(self, commit: str) -> Iterator[Path]:
        self.runtime.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="source-", dir=self.runtime) as temporary:
            root = Path(temporary)
            result = _run_git(
                ["--git-dir", str(self.cache), "archive", "--format=tar", commit],
                cwd=self.consumer_root,
                binary=True,
            )
            if result.returncode != 0:
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                raise SharedKnowledgeError(f"cannot read pinned canonical source {commit}: {detail}")
            self._extract(result.stdout, root)
            yield root

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
