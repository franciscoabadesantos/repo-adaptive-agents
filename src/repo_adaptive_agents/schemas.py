"""Schema documents for the public profile and plan shapes.

The MVP does not require a JSON-schema dependency. These documents are exported so
consumers can validate serialized output with their validator of choice.
"""

REPO_PROFILE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "RepoProfile",
    "type": "object",
    "required": ["path", "name", "project_types", "languages", "frameworks", "manifests", "components", "architecture", "tests", "deployment", "risks", "warnings"],
    "properties": {
        "path": {"type": "string"}, "name": {"type": "string"},
        "project_types": {"type": "array", "items": {"type": "string"}},
        "languages": {"type": "array", "items": {"type": "string"}},
        "frameworks": {"type": "array", "items": {"type": "string"}},
        "manifests": {"type": "array", "items": {"type": "string"}},
        "components": {"type": "array", "items": {"$ref": "#/$defs/component"}},
        "architecture": {"$ref": "#/$defs/evidence_group"},
        "tests": {"$ref": "#/$defs/evidence_group"},
        "deployment": {"$ref": "#/$defs/evidence_group"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "$defs": {
        "evidence_group": {"type": "object"},
        "component": {
            "type": "object",
            "required": ["name", "path", "manifests", "project_types", "languages", "frameworks", "runtimes", "entrypoints"],
            "properties": {
                "name": {"type": "string"}, "path": {"type": "string"},
                "manifests": {"type": "array", "items": {"type": "string"}},
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

TEAM_PLAN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "TeamPlan",
    "type": "object",
    "required": ["capabilities", "agents", "integrations", "questions", "assumptions"],
    "properties": {
        "capabilities": {"type": "array"}, "agents": {"type": "array"},
        "integrations": {"type": "array"}, "questions": {"type": "array"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}
