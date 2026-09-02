from __future__ import annotations

import tomllib
from pathlib import Path

from repo_adaptive_agents import __version__


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
