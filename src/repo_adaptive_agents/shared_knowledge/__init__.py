"""Shared team knowledge for coding agents."""

from .catalog import (
    KnowledgeConfig,
    KnowledgeStore,
    SharedKnowledgeError,
    find_repository,
    initialize_repository,
)
from .content import KnowledgeContentError, KnowledgeItem
from .service import (
    KnowledgeCheck,
    KnowledgeExposure,
    KnowledgeIndexEntry,
    KnowledgeResolution,
    SharedKnowledgeService,
    ValidatedKnowledge,
)

__all__ = [
    "KnowledgeCheck",
    "KnowledgeConfig",
    "KnowledgeContentError",
    "KnowledgeExposure",
    "KnowledgeIndexEntry",
    "KnowledgeItem",
    "KnowledgeResolution",
    "KnowledgeStore",
    "SharedKnowledgeError",
    "SharedKnowledgeService",
    "ValidatedKnowledge",
    "find_repository",
    "initialize_repository",
]
