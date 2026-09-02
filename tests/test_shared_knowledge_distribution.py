from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import repo_adaptive_agents.shared_knowledge.distribution as distribution
from repo_adaptive_agents.shared_knowledge import (
    CodexSkillSelector,
    SelectorUnavailable,
    SharedKnowledgeError,
    SkillSelection,
    SkillSelectionEntry,
    TeamKnowledgeDistributionService,
)
from repo_adaptive_agents.shared_knowledge.consumer import load_consumer_lock
from repo_adaptive_agents.shared_knowledge.evidence import RepositoryKnowledgeEvidence
from repo_adaptive_agents.shared_knowledge.selector import SkillRoutingEntry, parse_selection


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def _repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", "Test Engineer")
    _git(path, "config", "user.email", "engineer@example.invalid")
    return path


def _write_skill(
    source: Path,
    *,
    name: str = "dns",
    resource_id: str = "dns",
    state: str = "active",
    body: str = "Use the company DNS review workflow.",
    description: str = "Use for company DNS zones, records, delegation, and DNS operations.",
) -> None:
    directory = source / "skills" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: >\n  {description}\n---\n\n# Company DNS\n\n{body}\n",
        encoding="utf-8",
    )
    (directory / "team-knowledge.json").write_text(
        json.dumps({"schema_version": 1, "id": resource_id, "state": state}, indent=2) + "\n",
        encoding="utf-8",
    )
    references = directory / "references"
    references.mkdir(exist_ok=True)
    (references / "operations.md").write_text("# DNS operations\n\nReview zone diffs.\n", encoding="utf-8")


def _canonical(parent: Path) -> Path:
    source = _repo(parent / "canonical")
    (source / "team-knowledge.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_id": "engineering-team-knowledge",
                "organization": "company",
                "team": "engineering",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_skill(source)
    _git(source, "add", ".")
    _git(source, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Add canonical DNS Skill")
    return source


def _dns_repo(parent: Path, name: str, variant: int) -> Path:
    root = _repo(parent / name)
    if variant == 1:
        config = root / "config"
        config.mkdir()
        (config / "dns.yaml").write_text(
            "providers:\n  cf:\n    class: octodns_cloudflare.CloudflareProvider\nzones:\n  '*':\n    targets: [cf]\n",
            encoding="utf-8",
        )
    else:
        scripts = root / "dns_scripts"
        scripts.mkdir()
        hook = scripts / "dns_add_cloudflare"
        hook.write_text("#!/bin/sh\ncurl https://api.cloudflare.com/client/v4/zones\n", encoding="utf-8")
        hook.chmod(0o755)
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Add repository facts")
    return root


def _unrelated_repo(parent: Path, name: str = "repo-c") -> Path:
    root = _repo(parent / name)
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'calculator'\nversion = '1.0.0'\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Add Python package")
    return root


@dataclass
class EvidenceRoutingStub:
    calls: list[tuple[dict[str, object], tuple[object, ...]]] = field(default_factory=list)

    def select(self, evidence, skills):
        self.calls.append((evidence.data, skills))
        serialized = json.dumps(evidence.data).casefold()
        selected = tuple(
            SkillSelectionEntry(skill.id, "Factual repository evidence relates to DNS.")
            for skill in skills
            if "dns" in serialized and skill.id == "dns"
        )
        return SkillSelection(selected)


class UnavailableSelector:
    def select(self, evidence, skills):
        raise SelectorUnavailable("stub selector unavailable")


class UnknownSelector:
    def select(self, evidence, skills):
        return SkillSelection((SkillSelectionEntry("invented", "unknown"),))


class RevokedSelector:
    def select(self, evidence, skills):
        return SkillSelection((SkillSelectionEntry("dns", "Model requested revoked ID."),))


class SelectAllStub:
    def select(self, evidence, skills):
        return SkillSelection(tuple(SkillSelectionEntry(skill.id, "Plausibly useful.") for skill in skills))


def _bootstrap(service: TeamKnowledgeDistributionService, root: Path) -> None:
    plan = service.bootstrap_plan(root, source_url="../canonical")
    service.apply(plan)


def test_cross_repository_bootstrap_update_and_revocation_vertical(tmp_path: Path):
    source = _canonical(tmp_path)
    repo_a = _dns_repo(tmp_path, "repo-a", 1)
    repo_b = _dns_repo(tmp_path, "repo-b", 2)
    repo_c = _unrelated_repo(tmp_path)
    selector = EvidenceRoutingStub()
    service = TeamKnowledgeDistributionService(selector)

    _bootstrap(service, repo_a)
    _bootstrap(service, repo_b)
    _bootstrap(service, repo_c)

    skill_a = repo_a / ".agents/skills/dns/SKILL.md"
    skill_b = repo_b / ".agents/skills/dns/SKILL.md"
    assert skill_a.is_file() and skill_b.is_file()
    assert not (repo_c / ".agents/skills/dns").exists()
    lock_a = load_consumer_lock(repo_a)
    lock_b = load_consumer_lock(repo_b)
    lock_c = load_consumer_lock(repo_c)
    assert len(lock_a.resources) == len(lock_b.resources) == 1
    assert lock_c.resources == ()
    assert (
        lock_a.resources[0].id,
        lock_a.resources[0].revision,
        lock_a.resources[0].digest_sha256,
    ) == (
        lock_b.resources[0].id,
        lock_b.resources[0].revision,
        lock_b.resources[0].digest_sha256,
    )
    assert _git(repo_a, "check-ignore", "-q", ".agents/skills/dns") == ""
    exclude = (repo_a / ".git/info/exclude").read_text(encoding="utf-8")
    assert "/.agents/skills/dns/" in exclude
    assert "/.agents/skills/" not in {line for line in exclude.splitlines()}
    assert not (repo_a / ".agents/skills/dns/team-knowledge.json").exists()
    status = _git(repo_a, "status", "--short", "--untracked-files=all")
    assert ".agents/skills/dns" not in status
    assert ".team-knowledge/config.json" in status
    assert ".team-knowledge/lock.json" in status
    lock_text = (repo_a / ".team-knowledge/lock.json").read_text(encoding="utf-8")
    assert '"url": "../canonical"' in lock_text
    assert str(tmp_path) not in lock_text
    assert "reason" not in lock_text
    assert len(selector.calls) == 3
    assert all(set(skill.to_data()) == {"id", "name", "description"} for _evidence, skills in selector.calls for skill in skills)

    improved = "Use the improved DNS review workflow and verify delegation before apply."
    _write_skill(source, body=improved)
    _git(source, "add", "skills/dns")
    _git(source, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Improve DNS Skill once")
    selector_calls = len(selector.calls)
    for repo in (repo_a, repo_b, repo_c):
        plan = service.sync_plan(repo)
        service.apply(plan)
    assert improved in skill_a.read_text(encoding="utf-8")
    assert skill_a.read_bytes() == skill_b.read_bytes()
    assert not (repo_c / ".agents/skills/dns").exists()
    updated_a = load_consumer_lock(repo_a)
    updated_b = load_consumer_lock(repo_b)
    assert updated_a.resources[0].revision == updated_b.resources[0].revision
    assert updated_a.resources[0].digest_sha256 == updated_b.resources[0].digest_sha256
    assert updated_a.resources[0].digest_sha256 != lock_a.resources[0].digest_sha256
    assert len(selector.calls) == selector_calls

    _write_skill(source, state="revoked", body=improved)
    _git(source, "add", "skills/dns/team-knowledge.json")
    _git(source, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Revoke DNS Skill")
    selector_calls = len(selector.calls)
    for repo in (repo_a, repo_b):
        plan = service.sync_plan(repo)
        assert any(action.action == "remove" for action in plan.actions)
        service.apply(plan)
        assert load_consumer_lock(repo).resources == ()
        assert not (repo / ".agents/skills/dns").exists()
    assert len(selector.calls) == selector_calls

    _write_skill(source, state="active", body=improved)
    _git(source, "add", "skills/dns/team-knowledge.json")
    _git(source, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Reactivate DNS Skill")
    reactivation = service.sync_plan(repo_a)
    assert any(action.action == "add" for action in reactivation.actions)
    service.apply(reactivation)
    assert (repo_a / ".agents/skills/dns/SKILL.md").is_file()
    assert len(selector.calls) == selector_calls + 1


def test_new_skill_can_be_semantically_added_and_nonselection_never_prunes(tmp_path: Path):
    source = _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    service = TeamKnowledgeDistributionService(EvidenceRoutingStub())
    _bootstrap(service, repository)

    _write_skill(
        source,
        name="postgres",
        resource_id="postgres",
        body="Use reviewed migrations.",
        description="Use for company PostgreSQL schema and migration work.",
    )
    _git(source, "add", "skills/postgres")
    _git(source, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Add Postgres Skill")
    add_plan = TeamKnowledgeDistributionService(SelectAllStub()).sync_plan(repository)
    assert any(action.id == "postgres" and action.action == "add" for action in add_plan.actions)
    TeamKnowledgeDistributionService(SelectAllStub()).apply(add_plan)
    assert (repository / ".agents/skills/postgres/SKILL.md").is_file()

    facts = repository / "config/dns.yaml"
    facts.unlink()
    (repository / "pyproject.toml").write_text(
        "[project]\nname='plain-service'\nversion='1.0.0'\n", encoding="utf-8"
    )
    keep_plan = service.sync_plan(repository)
    assert set(keep_plan.possibly_no_longer_relevant) == {"dns", "postgres"}
    service.apply(keep_plan)
    assert (repository / ".agents/skills/dns/SKILL.md").is_file()
    assert (repository / ".agents/skills/postgres/SKILL.md").is_file()


def test_bootstrap_uses_native_admit_receipt_and_validate(monkeypatch, tmp_path: Path):
    _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    calls = {"admit": 0, "receipt": 0, "validate": 0}
    captured = {}
    original_admit = distribution.native.admit
    original_validate = distribution.native.validate
    original_receipt = distribution.native.AdmissionSnapshot.record_exposure

    def admit(*args, **kwargs):
        calls["admit"] += 1
        captured["context"] = args[0]
        captured["catalog"] = args[1]
        return original_admit(*args, **kwargs)

    def validate(*args, **kwargs):
        calls["validate"] += 1
        return original_validate(*args, **kwargs)

    def receipt(*args, **kwargs):
        calls["receipt"] += 1
        return original_receipt(*args, **kwargs)

    monkeypatch.setattr(distribution.native, "admit", admit)
    monkeypatch.setattr(distribution.native, "validate", validate)
    monkeypatch.setattr(distribution.native.AdmissionSnapshot, "record_exposure", receipt)
    plan = TeamKnowledgeDistributionService(EvidenceRoutingStub()).bootstrap_plan(
        repository, source_url="../canonical"
    )

    assert calls == {"admit": 1, "receipt": 1, "validate": 1}
    assert len(plan.desired_skills) == 1
    record = captured["catalog"].resources[0]
    assert record.content.kind == distribution.native.ResourceKind.AGENT_SKILL
    assert record.admission.scope == distribution.native.Scope(
        organization="company", team="engineering"
    )
    assert record.admission.exposure_policy == distribution.native.ExposurePolicy.REQUIRE_ADMISSIBLE
    assert captured["context"].repository == "consumer"


def test_revoked_model_selected_skill_is_native_rejected(tmp_path: Path):
    source = _canonical(tmp_path)
    _write_skill(source, state="revoked")
    _git(source, "add", "skills/dns/team-knowledge.json")
    _git(source, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Revoke DNS")
    repository = _dns_repo(tmp_path, "consumer", 1)

    plan = TeamKnowledgeDistributionService(RevokedSelector()).bootstrap_plan(
        repository, source_url="../canonical"
    )

    assert plan.desired_skills == ()
    assert plan.rejected_ids == ("dns",)


def test_unknown_selector_id_is_rejected_by_native_without_materialization(tmp_path: Path):
    _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    service = TeamKnowledgeDistributionService(UnknownSelector())

    plan = service.bootstrap_plan(repository, source_url="../canonical")
    service.apply(plan)

    assert plan.rejected_ids == ("invented",)
    assert load_consumer_lock(repository).resources == ()
    assert not (repository / ".agents/skills/dns").exists()


def test_bootstrap_model_unavailable_creates_no_selection_state(tmp_path: Path):
    _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)

    with pytest.raises(SelectorUnavailable):
        TeamKnowledgeDistributionService(UnavailableSelector()).bootstrap_plan(
            repository, source_url="../canonical"
        )

    assert not (repository / ".team-knowledge/config.json").exists()
    assert not (repository / ".team-knowledge/lock.json").exists()
    assert not (repository / ".agents/skills/dns").exists()


def test_unmanaged_collision_and_modified_managed_copy_are_never_overwritten(tmp_path: Path):
    source = _canonical(tmp_path)
    collision = _dns_repo(tmp_path, "collision", 1)
    unmanaged = collision / ".agents/skills/dns"
    unmanaged.mkdir(parents=True)
    (unmanaged / "SKILL.md").write_text("unmanaged\n", encoding="utf-8")
    service = TeamKnowledgeDistributionService(EvidenceRoutingStub())

    with pytest.raises(SharedKnowledgeError, match="unmanaged"):
        service.bootstrap_plan(collision, source_url="../canonical")
    assert (unmanaged / "SKILL.md").read_text(encoding="utf-8") == "unmanaged\n"

    managed = _dns_repo(tmp_path, "managed", 1)
    _bootstrap(service, managed)
    local = managed / ".agents/skills/dns/SKILL.md"
    local.write_text(local.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
    _write_skill(source, body="Central update must not destroy local work.")
    _git(source, "add", "skills/dns")
    _git(source, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Update DNS centrally")

    with pytest.raises(SharedKnowledgeError, match="locally modified"):
        service.sync_plan(managed)
    assert "local edit" in local.read_text(encoding="utf-8")


def test_missing_skill_without_revocation_is_source_integrity_error(tmp_path: Path):
    source = _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    service = TeamKnowledgeDistributionService(EvidenceRoutingStub())
    _bootstrap(service, repository)
    before = (repository / ".team-knowledge/lock.json").read_bytes()
    _git(source, "rm", "-q", "-r", "skills/dns")
    _git(source, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Delete without revocation")

    with pytest.raises(SharedKnowledgeError, match="without explicit revocation"):
        service.sync_plan(repository)
    assert (repository / ".team-knowledge/lock.json").read_bytes() == before
    assert (repository / ".agents/skills/dns/SKILL.md").is_file()


def test_network_failure_and_offline_verification_leave_locked_skill_usable(tmp_path: Path):
    source = _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    service = TeamKnowledgeDistributionService(EvidenceRoutingStub())
    _bootstrap(service, repository)
    skill = repository / ".agents/skills/dns/SKILL.md"
    lock = (repository / ".team-knowledge/lock.json").read_bytes()
    source.rename(tmp_path / "canonical-unavailable")

    with pytest.raises(SharedKnowledgeError, match="no local state was changed"):
        service.sync_plan(repository)
    assert skill.is_file()
    assert (repository / ".team-knowledge/lock.json").read_bytes() == lock
    offline = service.sync_plan(repository, offline=True)
    assert offline.offline
    service.apply(offline)
    assert skill.is_file()


def test_sync_updates_existing_and_defers_new_skill_when_selector_unavailable(tmp_path: Path):
    source = _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    _bootstrap(TeamKnowledgeDistributionService(EvidenceRoutingStub()), repository)
    old_lock = load_consumer_lock(repository)
    _write_skill(source, body="Updated while the selector is unavailable.")
    _write_skill(
        source,
        name="postgres",
        resource_id="postgres",
        body="Use the canonical database migration process.",
        description="Use for company PostgreSQL schema and migration work.",
    )
    _git(source, "add", "skills")
    _git(source, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Update DNS and add Postgres")

    service = TeamKnowledgeDistributionService(UnavailableSelector())
    plan = service.sync_plan(repository)
    assert plan.semantic_pending
    assert {action.action for action in plan.actions} >= {"update"}
    service.apply(plan)
    lock = load_consumer_lock(repository)
    assert lock.resolved_commit != old_lock.resolved_commit
    assert lock.evaluated_source_commit == old_lock.evaluated_source_commit
    assert [item.id for item in lock.resources] == ["dns"]
    assert "Updated while" in (repository / ".agents/skills/dns/SKILL.md").read_text()
    assert not (repository / ".agents/skills/postgres").exists()


def test_deleted_managed_copy_is_reconstructed_from_lock_and_canonical_source(tmp_path: Path):
    _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    service = TeamKnowledgeDistributionService(EvidenceRoutingStub())
    _bootstrap(service, repository)
    generated = repository / ".agents/skills/dns"
    shutil.rmtree(generated)

    plan = service.sync_plan(repository)
    assert next(action for action in plan.actions if action.id == "dns").action == "restore"
    service.apply(plan)
    assert (generated / "SKILL.md").is_file()


def test_fresh_checkout_hydrates_generated_skill_from_committed_config_and_lock(tmp_path: Path):
    _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    remote = tmp_path / "company/dns-repository.git"
    remote.parent.mkdir()
    _git(tmp_path, "init", "--bare", "-q", str(remote))
    _git(repository, "remote", "add", "origin", str(remote))
    service = TeamKnowledgeDistributionService(EvidenceRoutingStub())
    _bootstrap(service, repository)
    original = load_consumer_lock(repository)
    _git(repository, "add", ".team-knowledge/.gitignore", ".team-knowledge/config.json", ".team-knowledge/lock.json")
    _git(repository, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Bootstrap team knowledge")
    _git(repository, "push", "-q", "-u", "origin", "main")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")

    fresh = tmp_path / "fresh-checkout"
    _git(tmp_path, "clone", "-q", str(remote), str(fresh))
    assert (fresh / ".team-knowledge/config.json").is_file()
    assert (fresh / ".team-knowledge/lock.json").is_file()
    assert not (fresh / ".team-knowledge/cache").exists()
    assert not (fresh / ".team-knowledge/runtime").exists()
    assert not (fresh / ".team-knowledge/events.jsonl").exists()
    assert not (fresh / ".agents/skills/dns").exists()

    binaries = tmp_path / "bin"
    binaries.mkdir()
    selector_marker = tmp_path / "selector-was-called"
    codex = binaries / "codex"
    codex.write_text(
        f"#!/bin/sh\ntouch '{selector_marker}'\nexit 99\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    environment["PATH"] = f"{binaries}:{environment['PATH']}"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_adaptive_agents.shared_knowledge",
            "sync",
            "--yes",
            "--repo",
            str(fresh),
        ],
        check=False,
        text=True,
        capture_output=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert "RESTORE dns -> .agents/skills/dns" in result.stdout
    assert not selector_marker.exists()
    assert (fresh / ".team-knowledge/cache/source.git").is_dir()
    assert (fresh / ".agents/skills/dns/SKILL.md").is_file()
    hydrated = load_consumer_lock(fresh)
    assert hydrated.resources[0].revision == original.resources[0].revision
    assert hydrated.resources[0].digest_sha256 == original.resources[0].digest_sha256
    assert distribution.directory_digest(fresh / ".agents/skills/dns") == original.resources[0].digest_sha256


def test_codex_selector_uses_read_only_structured_noninteractive_contract(tmp_path: Path):
    executable = tmp_path / "fake-codex"
    arguments = tmp_path / "arguments.txt"
    executable.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > '{arguments}'\n"
        "output=''\n"
        "previous=''\n"
        "for value in \"$@\"; do\n"
        "  if [ \"$previous\" = '--output-last-message' ]; then output=\"$value\"; fi\n"
        "  previous=\"$value\"\n"
        "done\n"
        "printf '%s\\n' '{\"schema_version\":1,\"selected\":[{\"id\":\"dns\",\"reason\":null}]}' > \"$output\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    evidence = RepositoryKnowledgeEvidence({"schema_version": 1, "repository": "service"}, "0" * 64)

    result = CodexSkillSelector(str(executable)).select(
        evidence,
        (SkillRoutingEntry("dns", "dns", "Use for DNS."),),
    )

    assert result == SkillSelection((SkillSelectionEntry("dns", None),))
    assert parse_selection({"schema_version": 1, "selected": []}) == SkillSelection(())
    invoked = arguments.read_text(encoding="utf-8").splitlines()
    assert invoked[:6] == ["exec", "--ephemeral", "--sandbox", "read-only", "--ignore-user-config", "--ignore-rules"]
    assert "--output-schema" in invoked


def test_bootstrap_cli_runs_complete_plan_with_codex_selector_contract(tmp_path: Path):
    _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    codex = binaries / "codex"
    codex.write_text(
        "#!/bin/sh\n"
        "output=''\n"
        "previous=''\n"
        "for value in \"$@\"; do\n"
        "  if [ \"$previous\" = '--output-last-message' ]; then output=\"$value\"; fi\n"
        "  previous=\"$value\"\n"
        "done\n"
        "printf '%s\\n' '{\"schema_version\":1,\"selected\":[{\"id\":\"dns\",\"reason\":\"Relevant to repository facts.\"}]}' > \"$output\"\n",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    environment["PATH"] = f"{binaries}:{environment['PATH']}"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_adaptive_agents.shared_knowledge",
            "bootstrap",
            "--source",
            "../canonical",
            "--yes",
            "--repo",
            str(repository),
        ],
        check=False,
        text=True,
        capture_output=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert "ADD     dns -> .agents/skills/dns" in result.stdout
    assert "Recorded canonical selection" in result.stdout
    assert (repository / ".agents/skills/dns/SKILL.md").is_file()


@pytest.mark.parametrize("unsafe", ["symlink", "executable", "scripts", "binary"])
def test_unsafe_canonical_skill_packages_are_rejected(tmp_path: Path, unsafe: str):
    source = _canonical(tmp_path)
    skill = source / "skills/dns"
    if unsafe == "symlink":
        os.symlink("SKILL.md", skill / "alias.md")
    elif unsafe == "executable":
        executable = skill / "references/tool.txt"
        executable.write_text("not executable in this slice\n", encoding="utf-8")
        executable.chmod(0o755)
    elif unsafe == "scripts":
        scripts = skill / "scripts"
        scripts.mkdir()
        (scripts / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    else:
        (skill / "references/binary.txt").write_bytes(b"\xff\x00")
    _git(source, "add", ".")
    _git(source, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "Add unsafe content")
    repository = _dns_repo(tmp_path, "consumer", 1)

    with pytest.raises(SharedKnowledgeError, match="symlink|executable|scripts|UTF-8"):
        TeamKnowledgeDistributionService(EvidenceRoutingStub()).bootstrap_plan(
            repository, source_url="../canonical"
        )


def test_existing_repo_local_v01_state_is_not_overwritten(tmp_path: Path):
    _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    state = repository / ".team-knowledge"
    (state / "items").mkdir(parents=True)
    (state / "config.json").write_text('{"schema_version": 1}\n', encoding="utf-8")

    with pytest.raises(SharedKnowledgeError, match="refusing to overwrite"):
        TeamKnowledgeDistributionService(EvidenceRoutingStub()).bootstrap_plan(
            repository, source_url="../canonical"
        )


def test_local_cache_symlink_is_rejected(tmp_path: Path):
    _canonical(tmp_path)
    repository = _dns_repo(tmp_path, "consumer", 1)
    outside = tmp_path / "outside"
    outside.mkdir()
    state = repository / ".team-knowledge"
    state.mkdir()
    (state / "cache").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SharedKnowledgeError, match="must not be symlinks"):
        TeamKnowledgeDistributionService(EvidenceRoutingStub()).bootstrap_plan(
            repository, source_url="../canonical"
        )
