"""Shared team knowledge for coding agents."""

from .catalog import (
    KnowledgeConfig,
    KnowledgeStore,
    SharedKnowledgeError,
    find_repository,
    initialize_repository,
)
from .content import KnowledgeContentError, KnowledgeItem
from .codex import CODEX_SKILL_PATH, install_codex_skill, skill_text
from .sessions import ExposureSession, ExposureSessions
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
    "CODEX_SKILL_PATH",
    "ExposureSession",
    "ExposureSessions",
    "SharedKnowledgeError",
    "SharedKnowledgeService",
    "ValidatedKnowledge",
    "find_repository",
    "initialize_repository",
    "install_codex_skill",
    "skill_text",
]
