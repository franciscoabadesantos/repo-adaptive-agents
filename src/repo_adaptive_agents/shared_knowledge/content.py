"""Human-readable Markdown contract for shared team knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REQUIRED_FIELDS = ("id", "title", "summary", "owner", "state", "revision")
OPTIONAL_FIELDS = ("exposure",)
VALID_STATES = frozenset({"active", "revoked"})
VALID_EXPOSURES = frozenset({"normal", "restricted"})


class KnowledgeContentError(ValueError):
    """A knowledge Markdown file does not satisfy the public content contract."""


@dataclass(frozen=True)
class KnowledgeItem:
    id: str
    title: str
    summary: str
    owner: str
    state: str
    exposure: str
    revision: int
    body: str
    path: Path


def _one_line(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned or "\n" in cleaned or "\r" in cleaned:
        raise KnowledgeContentError(f"{field} must be a non-empty single line")
    return cleaned


def parse_item(path: Path, *, relative_to: Path | None = None) -> KnowledgeItem:
    """Parse the deliberately small frontmatter subset used by v0.1."""

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise KnowledgeContentError("file must be UTF-8") from error
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise KnowledgeContentError("file must start with a --- frontmatter delimiter")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise KnowledgeContentError("frontmatter must end with a --- delimiter") from error

    values: dict[str, str] = {}
    for number, line in enumerate(lines[1:closing], start=2):
        if not line.strip():
            continue
        if ":" not in line:
            raise KnowledgeContentError(f"frontmatter line {number} must use key: value")
        key, value = line.split(":", 1)
        key = key.strip()
        if key not in {*REQUIRED_FIELDS, *OPTIONAL_FIELDS}:
            raise KnowledgeContentError(f"unsupported frontmatter field: {key or '<empty>'}")
        if key in values:
            raise KnowledgeContentError(f"duplicate frontmatter field: {key}")
        values[key] = value.strip()

    missing = [field for field in REQUIRED_FIELDS if not values.get(field)]
    if missing:
        raise KnowledgeContentError(f"missing frontmatter field(s): {', '.join(missing)}")
    state = values["state"].strip()
    if state not in VALID_STATES:
        raise KnowledgeContentError("state must be active or revoked")
    exposure = values.get("exposure", "normal").strip()
    if exposure not in VALID_EXPOSURES:
        raise KnowledgeContentError("exposure must be normal or restricted")
    try:
        revision = int(values["revision"])
    except ValueError as error:
        raise KnowledgeContentError("revision must be a positive integer") from error
    if revision < 1 or str(revision) != values["revision"]:
        raise KnowledgeContentError("revision must be a positive integer")

    body = "\n".join(lines[closing + 1 :]).strip()
    if not body:
        raise KnowledgeContentError("body must be non-empty")
    stored_path = path.relative_to(relative_to) if relative_to is not None else path
    return KnowledgeItem(
        id=_one_line(values["id"], "id"),
        title=_one_line(values["title"], "title"),
        summary=_one_line(values["summary"], "summary"),
        owner=_one_line(values["owner"], "owner"),
        state=state,
        exposure=exposure,
        revision=revision,
        body=body,
        path=stored_path,
    )


def render_item(item: KnowledgeItem) -> str:
    """Render a stable, hand-editable Markdown representation."""

    values = {
        "id": _one_line(item.id, "id"),
        "title": _one_line(item.title, "title"),
        "summary": _one_line(item.summary, "summary"),
        "owner": _one_line(item.owner, "owner"),
        "state": item.state,
        "exposure": item.exposure,
        "revision": str(item.revision),
    }
    if values["state"] not in VALID_STATES:
        raise KnowledgeContentError("state must be active or revoked")
    if values["exposure"] not in VALID_EXPOSURES:
        raise KnowledgeContentError("exposure must be normal or restricted")
    if item.revision < 1:
        raise KnowledgeContentError("revision must be a positive integer")
    body = item.body.strip()
    if not body:
        raise KnowledgeContentError("body must be non-empty")
    rendered_fields = ["id", "title", "summary", "owner", "state"]
    if values["exposure"] == "restricted":
        rendered_fields.append("exposure")
    rendered_fields.append("revision")
    frontmatter = "\n".join(f"{field}: {values[field]}" for field in rendered_fields)
    return f"---\n{frontmatter}\n---\n\n{body}\n"
