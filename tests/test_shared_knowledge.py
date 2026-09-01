from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import repo_adaptive_agents.admission_control as native
from repo_adaptive_agents.shared_knowledge import (
    KnowledgeStore,
    SharedKnowledgeError,
    SharedKnowledgeService,
    initialize_repository,
)


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
NOW = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)


def _git_repo(tmp_path: Path) -> Path:
    repository = tmp_path / "service"
    repository.mkdir()
    subprocess.run(["git", "-C", str(repository), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", "engineer@example.com"], check=True)
    return repository


def _cli(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(SOURCE_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "repo_adaptive_agents.shared_knowledge", *arguments, "--repo", str(repository)],
        check=False,
        text=True,
        capture_output=True,
        env=environment,
    )


def _add(repository: Path, title: str = "Settlement retry contract", *, restricted: bool = False) -> str:
    arguments = [
        "add",
        "--title",
        title,
        "--summary",
        "Use when changing settlement retry behavior.",
        "--body",
        "Preserve the original idempotency key across every retry.",
    ]
    if restricted:
        arguments.append("--restricted")
    result = _cli(repository, *arguments)
    assert result.returncode == 0, result.stderr
    match = re.search(r"Added (tk-[0-9a-f]{12}):", result.stdout)
    assert match
    return match.group(1)


def test_cli_init_add_list_show_check_and_revoke(tmp_path: Path):
    repository = _git_repo(tmp_path)

    initialized = _cli(repository, "init", "--team", "payments")
    assert initialized.returncode == 0
    assert "Team knowledge is ready" in initialized.stdout
    knowledge = repository / ".team-knowledge"
    assert {
        path.relative_to(knowledge).as_posix()
        for path in knowledge.rglob("*")
        if path.is_file()
    } == {".gitignore", "config.json", "items/.gitkeep"}
    assert (knowledge / ".gitignore").read_text(encoding="utf-8") == (
        "/events.jsonl\n/runtime/\n"
    )
    config = json.loads((knowledge / "config.json").read_text(encoding="utf-8"))
    assert config == {
        "schema_version": 1,
        "organization": "local",
        "team": "payments",
        "repository": "service",
        "default_owner": "engineer@example.com",
    }

    item_id = _add(repository)
    item_path = knowledge / "items" / f"{item_id}.md"
    source = item_path.read_text(encoding="utf-8")
    assert f"id: {item_id}" in source
    assert "owner: engineer@example.com" in source
    assert "state: active" in source
    assert "exposure:" not in source
    assert "revision: 1" in source

    listed = _cli(repository, "list")
    assert listed.returncode == 0
    assert f"{item_id}\tactive\tSettlement retry contract" in listed.stdout
    shown = _cli(repository, "show", item_id)
    assert shown.returncode == 0
    assert shown.stdout == source
    checked = _cli(repository, "check")
    assert checked.returncode == 0
    assert "1 active, 0 revoked, 1 visible in the agent index" in checked.stdout

    revoked = _cli(repository, "revoke", item_id)
    assert revoked.returncode == 0
    assert f"Revoked {item_id}" in revoked.stdout
    checked = _cli(repository, "check")
    assert checked.returncode == 0
    assert "0 active, 1 revoked, 1 visible in the agent index" in checked.stdout
    updated = item_path.read_text(encoding="utf-8")
    assert "state: revoked" in updated
    assert "revision: 2" in updated


def test_init_is_safe_to_repeat_and_never_overwrites_config(tmp_path: Path):
    repository = _git_repo(tmp_path)
    first = _cli(repository, "init", "--team", "payments")
    config_path = repository / ".team-knowledge" / "config.json"
    original = config_path.read_bytes()
    second = _cli(repository, "init")
    conflicting = _cli(repository, "init", "--team", "different-team")
    assert first.returncode == second.returncode == 0
    assert conflicting.returncode == 2
    assert "already initialized with different team" in conflicting.stderr
    assert config_path.read_bytes() == original


def test_show_rejects_path_like_item_id(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    result = _cli(repository, "show", "../../outside")
    assert result.returncode == 2
    assert "invalid knowledge item ID" in result.stderr


def test_init_rejects_empty_explicit_metadata(tmp_path: Path):
    repository = _git_repo(tmp_path)
    result = _cli(repository, "init", "--team", "   ")
    assert result.returncode == 2
    assert "config team must be a non-empty string" in result.stderr
    assert not (repository / ".team-knowledge").exists()


def test_native_boundary_exposes_and_resolves_active_item(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository, organization="acme", team="payments", repository="acme/service")
    store = KnowledgeStore.open(repository)
    item = store.add(
        "Ledger testing checklist",
        "Use when changing ledger persistence.",
        "Run the invariant suite before the integration tests.",
    )
    catalog, _items = store.native_catalog()
    record = catalog.by_id()[item.id]
    assert record.content.kind == native.ResourceKind.SHARED_KNOWLEDGE
    assert record.content.payload.content_path == f".team-knowledge/items/{item.id}.md"
    assert isinstance(record.content.payload, native.SharedKnowledgePayload)
    assert record.admission.scope == native.Scope(
        organization="acme", team="payments", repository="acme/service"
    )
    assert record.admission.exposure_policy == native.ExposurePolicy.ALLOW_WHEN_INADMISSIBLE

    service = SharedKnowledgeService(store)
    exposure = service.expose_index(actor="second@example.com", task_id="task-1", effective_at=NOW)
    assert exposure.index == (
        type(exposure.index[0])(item.id, str(item.revision), item.title, item.summary),
    )
    resolution = service.validate_ids(
        exposure,
        (item.id,),
        actor="second@example.com",
        task_id="task-1",
    )
    assert resolution.validation.final_resource_ids == (item.id,)
    assert resolution.items[0].body == item.body
    assert resolution.citations == (item.title,)


def test_revoke_after_exposure_is_rejected_by_native_validation(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    item = store.add("Retry contract", "Use for retry changes.", "Keep idempotency keys stable.")
    service = SharedKnowledgeService(store)
    exposure = service.expose_index(effective_at=NOW)

    store.revoke(item.id)
    current_exposure = service.expose_index(effective_at=NOW)
    assert tuple(entry.id for entry in current_exposure.index) == (item.id,)
    resolution = service.validate_ids(exposure, (item.id,))

    assert resolution.items == ()
    assert resolution.validation.final_resource_ids == ()
    assert native.ReasonCode.REVOKED in {
        reason.code for reason in resolution.validation.selection_decisions[0].reasons
    }


def test_restricted_knowledge_is_withheld_when_inadmissible(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    ordinary = store.add("Ordinary note", "Useful ordinary context.", "Ordinary body.")
    restricted = store.add(
        "Restricted note",
        "Sensitive context for approved use.",
        "Restricted body.",
        restricted=True,
    )
    assert "exposure: restricted" in (repository / restricted.path).read_text(encoding="utf-8")
    store.revoke(ordinary.id)
    store.revoke(restricted.id)

    catalog, _items = store.native_catalog()
    assert catalog.by_id()[ordinary.id].admission.exposure_policy == native.ExposurePolicy.ALLOW_WHEN_INADMISSIBLE
    assert catalog.by_id()[restricted.id].admission.exposure_policy == native.ExposurePolicy.REQUIRE_ADMISSIBLE
    service = SharedKnowledgeService(store)
    exposure = service.expose_index(effective_at=NOW)

    assert tuple(entry.id for entry in exposure.index) == (ordinary.id,)
    result = service.validate_ids(exposure, (ordinary.id, restricted.id))
    assert result.items == ()
    decisions = {decision.resource_id: decision for decision in result.validation.selection_decisions}
    assert native.ReasonCode.REVOKED in {reason.code for reason in decisions[ordinary.id].reasons}
    assert native.ReasonCode.NOT_EXPOSED in {reason.code for reason in decisions[restricted.id].reasons}
    assert native.ReasonCode.REVOKED in {reason.code for reason in decisions[restricted.id].reasons}


def test_manual_change_after_exposure_is_rejected_by_native_validation(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    item = store.add("Retry contract", "Use for retry changes.", "Original guidance.")
    service = SharedKnowledgeService(store)
    exposure = service.expose_index(effective_at=NOW)
    path = repository / item.path
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("revision: 1", "revision: 2")
        .replace("Original guidance.", "Changed guidance."),
        encoding="utf-8",
    )

    resolution = service.validate_ids(exposure, (item.id,))

    assert resolution.items == ()
    assert native.ReasonCode.RESOURCE_CHANGED in {
        reason.code for reason in resolution.validation.selection_decisions[0].reasons
    }


def test_invalid_markdown_fails_check_and_never_enters_catalog(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    invalid = repository / ".team-knowledge" / "items" / "broken.md"
    invalid.write_text("# Missing frontmatter\n", encoding="utf-8")

    checked = _cli(repository, "check")
    assert checked.returncode == 2
    assert "broken.md: file must start with" in checked.stderr
    with pytest.raises(SharedKnowledgeError, match="invalid team knowledge"):
        KnowledgeStore.open(repository).native_catalog()


def test_event_log_contains_only_minimal_event_data(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    secret_body = "Do not copy this body into telemetry."
    item = store.add("Private operational note", "Use during local operations.", secret_body)
    service = SharedKnowledgeService(store)
    exposure = service.expose_index(actor="reader@example.com", task_id="task-7", effective_at=NOW)
    service.validate_ids(exposure, (item.id,), actor="reader@example.com", task_id="task-7")

    text = (repository / ".team-knowledge" / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in text.splitlines()]
    assert [event["event"] for event in events] == [
        "contribution_created",
        "item_exposed",
        "item_selected",
        "validation_accepted",
        "item_body_returned",
    ]
    assert secret_body not in text
    assert all("prompt" not in event and "body" not in event for event in events)
    assert all(event["revision"] == "1" for event in events)
    assert all(event["actor"].startswith("actor-") for event in events)
    assert "reader@example.com" not in text


@pytest.mark.parametrize(
    "command",
    ["init", "add", "list", "show", "check", "index", "use", "feedback", "revoke"],
)
def test_each_command_has_help(command: str):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(SOURCE_ROOT)
    result = subprocess.run(
        [sys.executable, "-m", "repo_adaptive_agents.shared_knowledge", command, "--help"],
        check=False,
        text=True,
        capture_output=True,
        env=environment,
    )
    assert result.returncode == 0
    assert "usage: team-knowledge" in result.stdout
