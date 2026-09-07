from __future__ import annotations

import tomllib
from pathlib import Path

from repo_adaptive_agents import __version__
from repo_adaptive_agents.shared_knowledge.canonical import load_canonical_catalog


ROOT = Path(__file__).resolve().parents[1]


def test_distribution_version_and_product_metadata_are_consistent():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["version"] == __version__ == "0.14.0"
    assert project["readme"] == "README.md"
    assert project["scripts"]["team-knowledge"] == (
        "repo_adaptive_agents.shared_knowledge.cli:main"
    )


def test_codex_skill_is_declared_as_wheel_package_data():
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert configuration["tool"]["setuptools"]["package-data"][
        "repo_adaptive_agents.shared_knowledge"
    ] == ["skill_template/team-knowledge/SKILL.md"]


def test_bundled_lets_encrypt_dns01_skill_is_safe_and_canonical():
    catalog = load_canonical_catalog(
        ROOT / "team-knowledge",
        "test-source-commit",
        lambda _path: "test-skill-revision",
    )

    assert [(skill.id, skill.name, skill.state) for skill in catalog.skills] == [
        ("dify-dsl-trace-repair", "dify-dsl-trace-repair", "active"),
        ("dify-evidence-first-workflow-build", "dify-evidence-first-workflow-build", "active"),
        ("dify-external-integration-readiness", "dify-external-integration-readiness", "active"),
        ("dify-iteration-and-batch-safety", "dify-iteration-and-batch-safety", "active"),
        ("dify-knowledge-retrieval-validation", "dify-knowledge-retrieval-validation", "active"),
        ("dify-portable-dsl-migration", "dify-portable-dsl-migration", "active"),
        ("dify-structured-output-gates", "dify-structured-output-gates", "active"),
        ("dify-workflow-state-and-lifecycle", "dify-workflow-state-and-lifecycle", "active"),
        ("lets-encrypt-dns01-octodns-renewal", "lets-encrypt-dns01-octodns-renewal", "active"),
    ]
    skills = {skill.name: skill for skill in catalog.skills}
    renewal = skills["lets-encrypt-dns01-octodns-renewal"]
    assert "Let's Encrypt" in renewal.description
    assert "private key" in renewal.skill_text.lower()
    for skill in catalog.skills:
        assert "CLOUDFLARE_TOKEN" not in skill.skill_text
        assert "/home/user/" not in skill.skill_text
        assert "BEGIN PRIVATE KEY" not in skill.skill_text
    assert "Workspace-dependent" in skills["dify-evidence-first-workflow-build"].skill_text
    assert "first divergence" in skills["dify-dsl-trace-repair"].skill_text
    assert "deterministic gates" in skills["dify-structured-output-gates"].skill_text
    assert "postcondition" in skills["dify-external-integration-readiness"].skill_text
    assert "per-item" in skills["dify-iteration-and-batch-safety"].skill_text
    assert "conflicting-evidence" in skills["dify-knowledge-retrieval-validation"].skill_text
    assert "target-bound" in skills["dify-portable-dsl-migration"].skill_text
    assert "unknown" in skills["dify-workflow-state-and-lifecycle"].skill_text
