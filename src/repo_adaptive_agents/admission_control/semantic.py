"""Ordinary lexical reference selector; not part of deterministic admission."""

from __future__ import annotations

import math
import re
from collections import Counter

from .models import CandidateSelection, ResolutionContext, ResourceRecord


_TOKEN = re.compile(r"[a-z0-9]+")


def lexical_selector(limit: int = 5):
    """Return a simple relevance selector over the resources it is actually given."""

    def select(
        context: ResolutionContext,
        selectable_resources: tuple[ResourceRecord, ...],
        mandatory_controls: tuple[ResourceRecord, ...],
    ) -> tuple[CandidateSelection, ...]:
        del mandatory_controls
        query = Counter(_TOKEN.findall(context.task.lower()))
        query_norm = math.sqrt(sum(count * count for count in query.values()))
        scored: list[tuple[float, ResourceRecord]] = []
        for resource in selectable_resources:
            document = Counter(_TOKEN.findall(f"{resource.title} {resource.summary} {resource.body}".lower()))
            norm = math.sqrt(sum(count * count for count in document.values()))
            dot = sum(count * document.get(token, 0) for token, count in query.items())
            score = dot / (query_norm * norm) if query_norm and norm else 0.0
            if score > 0:
                scored.append((score, resource))
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return tuple(
            CandidateSelection(resource.id, "lexical relevance over admitted resource content", round(score, 6))
            for score, resource in scored[:limit]
        )

    return select
