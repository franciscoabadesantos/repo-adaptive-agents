"""Shared team knowledge for coding agents."""

from .catalog import (
    KnowledgeConfig,
    KnowledgeStore,
    SharedKnowledgeError,
    find_repository,
    initialize_repository,
    repository_identity,
)
from .canonical import CanonicalCatalog, CanonicalSkill, SourceDescriptor
from .content import KnowledgeContentError, KnowledgeItem
from .codex import CODEX_SKILL_PATH, install_codex_skill, skill_text
from .sessions import ExposureSession, ExposureSessions
from .distribution import DistributionPlan, TeamKnowledgeDistributionService
from .evidence import RepositoryKnowledgeEvidence, collect_skill_bootstrap_evidence
from .selector import (
    CodexSkillSelector,
    SelectorResponseError,
    SelectorUnavailable,
    SkillRoutingEntry,
    SkillSelection,
    SkillSelectionEntry,
    SkillSelector,
)
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
    "CanonicalCatalog",
    "CanonicalSkill",
    "CodexSkillSelector",
    "DistributionPlan",
    "ExposureSession",
    "ExposureSessions",
    "SharedKnowledgeError",
    "SharedKnowledgeService",
    "SkillRoutingEntry",
    "SkillSelection",
    "SkillSelectionEntry",
    "SkillSelector",
    "SelectorResponseError",
    "SelectorUnavailable",
    "SourceDescriptor",
    "TeamKnowledgeDistributionService",
    "RepositoryKnowledgeEvidence",
    "ValidatedKnowledge",
    "find_repository",
    "initialize_repository",
    "repository_identity",
    "collect_skill_bootstrap_evidence",
    "install_codex_skill",
    "skill_text",
]
