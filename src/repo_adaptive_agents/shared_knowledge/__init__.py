"""Git-backed portable team Skills for coding agents."""

from .repository import SharedKnowledgeError, find_repository, repository_identity
from .canonical import CanonicalCatalog, CanonicalSkill, SourceDescriptor
from .onboarding import (
    ONBOARDING_SKILL_NAME,
    install_onboarding_skills,
    onboarding_destinations,
    onboarding_readiness,
    onboarding_skill_text,
)
from .preferences import load_selector_preference, preferences_path, save_selector_preference
from .distribution import DistributionPlan, TeamKnowledgeDistributionService
from .evidence import RepositoryKnowledgeEvidence, collect_skill_bootstrap_evidence
from .selector import (
    ClaudeSkillSelector,
    CodexSkillSelector,
    CopilotSkillSelector,
    SelectorResponseError,
    SelectorUnavailable,
    SkillRoutingEntry,
    SkillSelection,
    SkillSelectionEntry,
    SkillSelector,
    build_selection_prompt,
    build_selection_request,
    resolve_selector_name,
    selector_for,
)

__all__ = [
    "ONBOARDING_SKILL_NAME",
    "CanonicalCatalog",
    "CanonicalSkill",
    "ClaudeSkillSelector",
    "CodexSkillSelector",
    "CopilotSkillSelector",
    "DistributionPlan",
    "SharedKnowledgeError",
    "SkillRoutingEntry",
    "SkillSelection",
    "SkillSelectionEntry",
    "SkillSelector",
    "SelectorResponseError",
    "SelectorUnavailable",
    "SourceDescriptor",
    "TeamKnowledgeDistributionService",
    "RepositoryKnowledgeEvidence",
    "build_selection_prompt",
    "build_selection_request",
    "find_repository",
    "repository_identity",
    "resolve_selector_name",
    "selector_for",
    "collect_skill_bootstrap_evidence",
    "install_onboarding_skills",
    "onboarding_destinations",
    "onboarding_readiness",
    "onboarding_skill_text",
    "load_selector_preference",
    "preferences_path",
    "save_selector_preference",
]
