"""Small, user-local preferences that must never become repository state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from .catalog import SharedKnowledgeError
from .selector import SELECTOR_NAMES


def preferences_path(*, home: Path | None = None, environ: Mapping[str, str] | None = None) -> Path:
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    config_home = Path(environment.get("XDG_CONFIG_HOME", str(user_home / ".config"))).expanduser()
    return config_home / "team-knowledge" / "config.json"


def load_selector_preference(*, home: Path | None = None, environ: Mapping[str, str] | None = None) -> str | None:
    path = preferences_path(home=home, environ=environ)
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise SharedKnowledgeError(f"user selector preference is unsafe: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SharedKnowledgeError(f"cannot read user selector preference: {error}") from error
    if not isinstance(data, dict) or set(data) != {"schema_version", "selector"} or data.get("schema_version") != 1:
        raise SharedKnowledgeError("user selector preference must be a schema version 1 object")
    selector = data.get("selector")
    if not isinstance(selector, str) or selector.casefold() not in SELECTOR_NAMES:
        raise SharedKnowledgeError(f"selector must be one of: {', '.join(SELECTOR_NAMES)}")
    return selector.casefold()


def save_selector_preference(
    selector: str,
    *,
    home: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    name = selector.strip().casefold()
    if name not in SELECTOR_NAMES:
        raise SharedKnowledgeError(f"selector must be one of: {', '.join(SELECTOR_NAMES)}")
    path = preferences_path(home=home, environ=environ)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise SharedKnowledgeError(f"user selector preference is unsafe: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps({"schema_version": 1, "selector": name}, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as error:
        raise SharedKnowledgeError(f"cannot write user selector preference: {error}") from error
    return path
