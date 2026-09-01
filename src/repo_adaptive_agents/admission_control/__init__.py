"""Experimental deterministic admission controls around semantic resource selection."""

from .admission import evaluate_admission
from .catalog import CatalogError, ResourceCatalog, load_catalog
from .models import (
    AdmissionDecision,
    AdmissionRun,
    CandidateSelection,
    CompatibilityConstraint,
    EnvironmentContractSemantics,
    Governance,
    Lifecycle,
    MCPSemantics,
    PolicySemantics,
    RepositoryInstructionSemantics,
    ResolutionContext,
    ResourceRecord,
    Scope,
    SkillSemantics,
)
from .pipeline import SemanticSelector, run_guarded_selection
from .writer import AuditWriteError, write_audit_bundle

__all__ = [
    "AdmissionDecision",
    "AdmissionRun",
    "AuditWriteError",
    "CandidateSelection",
    "CatalogError",
    "CompatibilityConstraint",
    "EnvironmentContractSemantics",
    "Governance",
    "Lifecycle",
    "MCPSemantics",
    "PolicySemantics",
    "RepositoryInstructionSemantics",
    "ResolutionContext",
    "ResourceCatalog",
    "ResourceRecord",
    "Scope",
    "SemanticSelector",
    "SkillSemantics",
    "evaluate_admission",
    "load_catalog",
    "run_guarded_selection",
    "write_audit_bundle",
]
