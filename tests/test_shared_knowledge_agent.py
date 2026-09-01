from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from repo_adaptive_agents.shared_knowledge import KnowledgeStore, initialize_repository, skill_text


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"


def _git_repo(tmp_path: Path, email: str = "author@example.com") -> Path:
    repository = tmp_path / "service"
    repository.mkdir()
    subprocess.run(["git", "-C", str(repository), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repository), "config", "user.email", email], check=True)
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


def _index(repository: Path, task_id: str = "task-1") -> dict:
    result = _cli(repository, "index", "--json", "--task-id", task_id)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _use(repository: Path, exposure_id: str, *item_ids: str, task_id: str = "task-1") -> dict:
    result = _cli(
        repository,
        "use",
        *item_ids,
        "--exposure",
        exposure_id,
        "--json",
        "--task-id",
        task_id,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_index_respects_exposure_and_never_leaks_bodies_or_private_metadata(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    ordinary = store.add("Retry contract", "Use for retry changes.", "ORDINARY-SECRET-BODY")
    restricted = store.add(
        "Production checklist",
        "Use for approved production work.",
        "RESTRICTED-SECRET-BODY",
        restricted=True,
    )
    withheld = store.add(
        "Revoked restricted note",
        "No longer approved.",
        "WITHHELD-SECRET-BODY",
        restricted=True,
    )
    store.revoke(withheld.id)

    payload = _index(repository)

    assert payload["schema_version"] == 1
    assert payload["exposure_id"].startswith("exp-")
    by_id = {item["id"]: item for item in payload["knowledge"]}
    assert set(by_id) == {ordinary.id, restricted.id}
    assert by_id[ordinary.id] == {
        "id": ordinary.id,
        "revision": "1",
        "title": ordinary.title,
        "summary": ordinary.summary,
    }
    serialized = json.dumps(payload)
    assert "ORDINARY-SECRET-BODY" not in serialized
    assert "RESTRICTED-SECRET-BODY" not in serialized
    assert "WITHHELD-SECRET-BODY" not in serialized
    assert withheld.id not in serialized
    assert all(set(item) == {"id", "revision", "title", "summary"} for item in payload["knowledge"])

    session_path = repository / ".team-knowledge" / "runtime" / "exposures" / f"{payload['exposure_id']}.json"
    stored = session_path.read_text(encoding="utf-8")
    assert "SECRET-BODY" not in stored
    assert session_path.stat().st_mode & 0o777 == 0o600
    ignored = subprocess.run(
        ["git", "-C", str(repository), "check-ignore", "-q", str(session_path)],
        check=False,
    )
    assert ignored.returncode == 0


def test_index_requires_ignored_runtime_and_init_repairs_existing_repository(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    store.add("Retry contract", "Use for retry changes.", "Keep the idempotency key.")
    ignore_path = repository / ".team-knowledge" / ".gitignore"
    ignore_path.write_text("/events.jsonl\n", encoding="utf-8")

    refused = _cli(repository, "index", "--json")

    assert refused.returncode == 2
    assert "run 'team-knowledge init'" in refused.stderr
    repaired = _cli(repository, "init")
    assert repaired.returncode == 0, repaired.stderr
    assert ignore_path.read_text(encoding="utf-8") == "/events.jsonl\n/runtime/\n"
    payload = _index(repository)
    assert len(payload["knowledge"]) == 1


def test_use_returns_multiple_valid_bodies_and_exact_citations(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    retry = store.add("Retry contract", "Use for retry changes.", "Keep the idempotency key.")
    tests = store.add("Ledger checklist", "Use for ledger tests.", "Run the invariant suite.")
    exposure = _index(repository)

    payload = _use(repository, exposure["exposure_id"], retry.id, tests.id)

    assert payload["rejected"] == []
    assert payload["binding_additions"] == []
    assert [(item["id"], item["body"]) for item in payload["knowledge"]] == [
        (retry.id, retry.body),
        (tests.id, tests.body),
    ]
    assert payload["citations"] == [
        {"id": retry.id, "revision": "1", "title": retry.title},
        {"id": tests.id, "revision": "1", "title": tests.title},
    ]
    assert all(item["status"] == "accepted" for item in payload["selected"])


def test_revoked_after_index_is_rejected_without_returning_body(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    item = store.add("Retry contract", "Use for retry changes.", "MUST-NOT-RETURN")
    exposure = _index(repository)
    store.revoke(item.id)

    result = _cli(repository, "use", item.id, "--exposure", exposure["exposure_id"], "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["knowledge"] == []
    assert payload["citations"] == []
    assert payload["rejected"] == [{"id": item.id, "revision": "1", "status": "rejected"}]
    assert "MUST-NOT-RETURN" not in result.stdout


def test_changed_after_index_is_rejected_without_returning_body(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    item = store.add("Retry contract", "Use for retry changes.", "ORIGINAL-BODY")
    exposure = _index(repository)
    path = repository / item.path
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("revision: 1", "revision: 2")
        .replace("ORIGINAL-BODY", "CHANGED-BODY"),
        encoding="utf-8",
    )

    result = _cli(repository, "use", item.id, "--exposure", exposure["exposure_id"], "--json")

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["knowledge"] == []
    assert payload["citations"] == []
    assert payload["rejected"][0]["id"] == item.id
    assert "ORIGINAL-BODY" not in result.stdout
    assert "CHANGED-BODY" not in result.stdout


def test_unknown_and_never_exposed_ids_are_rejected_without_body_leak(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    hidden = store.add("Restricted note", "Withheld when revoked.", "HIDDEN-BODY", restricted=True)
    store.revoke(hidden.id)
    exposure = _index(repository)

    result = _cli(
        repository,
        "use",
        "unknown-item",
        hidden.id,
        "--exposure",
        exposure["exposure_id"],
        "--json",
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["knowledge"] == []
    assert payload["citations"] == []
    assert [item["id"] for item in payload["rejected"]] == ["unknown-item", hidden.id]
    assert all(item["revision"] is None for item in payload["rejected"])
    assert "HIDDEN-BODY" not in result.stdout


def test_events_include_revision_and_repository_scoped_pseudonymous_actor(tmp_path: Path):
    repository = _git_repo(tmp_path, "author@example.com")
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    authored = store.add("Retry contract", "Use for retry changes.", "Keep keys stable.")
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "reader@example.com"],
        check=True,
    )
    exposure = _index(repository, task_id="task-reader")
    _use(repository, exposure["exposure_id"], authored.id, task_id="task-reader")

    text = (repository / ".team-knowledge" / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in text.splitlines()]
    assert "author@example.com" not in text
    assert "reader@example.com" not in text
    assert all(event["revision"] == "1" for event in events)
    assert all(event["task_id"] == "task-reader" for event in events[1:])
    author_actor = events[0]["actor"]
    reader_actors = {event["actor"] for event in events[1:]}
    assert author_actor.startswith("actor-")
    assert len(reader_actors) == 1
    assert author_actor not in reader_actors
    assert [event["event"] for event in events] == [
        "contribution_created",
        "item_exposed",
        "item_selected",
        "validation_accepted",
        "item_body_returned",
    ]


def test_new_contribution_uses_current_clone_git_identity(tmp_path: Path):
    repository = _git_repo(tmp_path, "initializer@example.com")
    initialize_repository(repository)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "contributor@example.com"],
        check=True,
    )

    item = KnowledgeStore.open(repository).add(
        "Contributor note",
        "Use for contributor workflow.",
        "Contributor-owned body.",
    )

    assert item.owner == "contributor@example.com"
    assert "owner: contributor@example.com" in (repository / item.path).read_text(encoding="utf-8")


def test_feedback_records_event_without_mutating_knowledge(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialize_repository(repository)
    store = KnowledgeStore.open(repository)
    item = store.add("Retry contract", "Use for retry changes.", "Keep keys stable.")
    path = repository / item.path
    before = path.read_bytes()

    result = _cli(repository, "feedback", item.id, "outdated", "--json", "--task-id", "task-2")

    assert result.returncode == 0
    assert json.loads(result.stdout)["feedback"] == "outdated"
    assert path.read_bytes() == before
    event = json.loads((repository / ".team-knowledge" / "events.jsonl").read_text().splitlines()[-1])
    assert event["event"] == "feedback_recorded"
    assert event["feedback"] == "outdated"
    assert event["revision"] == "1"


def test_codex_skill_is_installed_and_fake_agent_uses_only_cli_contract(tmp_path: Path):
    repository = _git_repo(tmp_path)
    initialized = _cli(repository, "init", "--codex")
    assert initialized.returncode == 0, initialized.stderr
    installed = repository / ".agents" / "skills" / "team-knowledge" / "SKILL.md"
    assert installed.read_text(encoding="utf-8") == skill_text()
    assert "team-knowledge index --json" in skill_text()
    assert "team-knowledge use --exposure" in skill_text()
    assert "Do not open files under" in skill_text()

    store = KnowledgeStore.open(repository)
    relevant = store.add("Settlement retry contract", "Use for settlement retry changes.", "Preserve the key.")
    store.add("CSS checklist", "Use for frontend styling.", "Run visual checks.")
    command_log: list[tuple[str, ...]] = []

    # Stub Codex follows the Skill contract; semantic choice is external to the product.
    command_log.append(("index", "--json"))
    index_payload = _index(repository)
    chosen_id = relevant.id
    command_log.append(("use", "--exposure", index_payload["exposure_id"], "--json", chosen_id))
    use_payload = _use(repository, index_payload["exposure_id"], chosen_id)

    assert command_log[0] == ("index", "--json")
    assert command_log[1][0:2] == ("use", "--exposure")
    assert use_payload["knowledge"] == [
        {"id": relevant.id, "revision": "1", "title": relevant.title, "body": relevant.body}
    ]
    assert use_payload["citations"][0]["title"] == "Settlement retry contract"
    disclosure = "Used team knowledge: " + "; ".join(item["title"] for item in use_payload["citations"])
    assert disclosure == "Used team knowledge: Settlement retry contract"
