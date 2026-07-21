"""Schema documents for the public profile and plan shapes.

The MVP does not require a JSON-schema dependency. These documents are exported so
consumers can validate serialized output with their validator of choice.
"""

REPO_PROFILE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RepoProfile",
    "type": "object",
    "required": ["path", "name", "project_types", "primary_project_types", "secondary_project_types", "languages", "frameworks", "manifests", "components", "architecture", "workflow", "tests", "browser_qa", "deployment", "risks", "warnings"],
    "properties": {
        "path": {"type": "string"}, "name": {"type": "string"},
        "project_types": {"type": "array", "items": {"type": "string"}},
        "primary_project_types": {"type": "array", "items": {"type": "string"}},
        "secondary_project_types": {"type": "array", "items": {"type": "string"}},
        "languages": {"type": "array", "items": {"type": "string"}},
        "frameworks": {"type": "array", "items": {"type": "string"}},
        "manifests": {"type": "array", "items": {"type": "string"}},
        "components": {"type": "array", "items": {"$ref": "#/$defs/component"}},
        "architecture": {"$ref": "#/$defs/evidence_group"},
        "workflow": {"$ref": "#/$defs/evidence_group"},
        "tests": {"$ref": "#/$defs/evidence_group"},
        "browser_qa": {"$ref": "#/$defs/evidence_group"},
        "deployment": {"$ref": "#/$defs/evidence_group"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "$defs": {
        "evidence_group": {"type": "object"},
        "component": {
            "type": "object",
            "required": ["name", "path", "manifests", "role", "project_types", "languages", "frameworks", "runtimes", "entrypoints"],
            "properties": {
                "name": {"type": "string"}, "path": {"type": "string"},
                "manifests": {"type": "array", "items": {"type": "string"}},
                "role": {"type": "string"},
                "project_types": {"type": "array", "items": {"type": "string"}},
                "languages": {"type": "array", "items": {"type": "string"}},
                "frameworks": {"type": "array", "items": {"type": "string"}},
                "runtimes": {"type": "array", "items": {"type": "string"}},
                "entrypoints": {"type": "array", "items": {"type": "string"}},
                "deployment_targets": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": "array"},
            },
        },
    },
}

INFRASTRUCTURE_PLAN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "InfrastructurePlan",
    "type": "object",
    "required": ["repository_contracts", "capabilities", "available_roles", "integrations", "questions", "assumptions"],
    "properties": {
        "repository_contracts": {"type": "object"},
        "capabilities": {"type": "array"}, "available_roles": {"type": "array"},
        "integrations": {"type": "array"}, "questions": {"type": "array"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}

# Backward-compatible export name for consumers of the original MVP schema module.
TEAM_PLAN_SCHEMA = INFRASTRUCTURE_PLAN_SCHEMA
