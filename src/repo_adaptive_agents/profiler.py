"""Deterministic repository profiling based on manifests, workflows, and entrypoints."""

from __future__ import annotations

import json
import os
import re
import tomllib
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import (
    ArchitectureProfile,
    Availability,
    ComponentProfile,
    DeploymentProfile,
    Evidence,
    IntegrationProfile,
    RepoProfile,
    TestProfile,
)

IGNORED_DIRS = {
    ".git", ".codex", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".tox", ".ruff_cache", ".cache", ".hypothesis", "coverage",
    "dist", "build", ".next", ".terraform", "target", "vendor", "htmlcov", ".gradle",
}
IGNORED_FILES = {".coverage", ".DS_Store"}
MANIFEST_NAMES = {"package.json", "pyproject.toml", "requirements.txt", "requirements-dev.txt", "setup.py", "setup.cfg", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "Gemfile", "composer.json"}
PACKAGE_FRAMEWORKS = {"next": "Next.js", "react": "React", "vue": "Vue", "@angular/core": "Angular", "svelte": "Svelte", "hono": "Hono", "express": "Express", "fastify": "Fastify"}
PYTHON_FRAMEWORKS = {"fastapi": "FastAPI", "flask": "Flask", "django": "Django", "pandas": "pandas", "scikit-learn": "scikit-learn", "sklearn": "scikit-learn", "torch": "PyTorch", "tensorflow": "TensorFlow", "numpy": "NumPy"}
STRONG_ML_DEPENDENCIES = {
    "scikit-learn": "scikit-learn", "sklearn": "scikit-learn", "torch": "PyTorch", "tensorflow": "TensorFlow", "keras": "Keras",
    "xgboost": "XGBoost", "lightgbm": "LightGBM", "catboost": "CatBoost", "jax": "JAX", "transformers": "Transformers",
    "mlflow": "MLflow", "optuna": "Optuna", "pytorch-lightning": "PyTorch Lightning", "onnxruntime": "ONNX Runtime",
    "onnxruntime-node": "ONNX Runtime", "@tensorflow/tfjs": "TensorFlow.js",
}
ML_PATH_DIRECTORIES = {"notebooks", "training", "experiments", "machine-learning", "data-science"}
ML_ARTIFACT_SUFFIXES = {".pkl", ".pickle", ".joblib", ".onnx", ".pt", ".pth", ".safetensors", ".h5", ".keras"}
CODE_SUFFIXES = {".bats", ".c", ".cc", ".cl", ".cpp", ".cs", ".go", ".java", ".js", ".jsx", ".kt", ".mjs", ".php", ".py", ".rb", ".rs", ".sh", ".ts", ".tsx"}
DOCUMENTATION_DIRS = {"docs", "doc", "documentation", "templates"}
FIXTURE_DIRS = {"fixtures", "fixture", "testdata", "test-data", "samples"}
DEFAULT_EVIDENCE_PATH_LIMIT = 25
_EVIDENCE_PATH_LIMIT: ContextVar[int] = ContextVar("evidence_path_limit", default=DEFAULT_EVIDENCE_PATH_LIMIT)


@dataclass(frozen=True)
class _ReadResult:
    text: str
    truncated: bool = False
    error: str | None = None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_candidate(path: Path, root: Path) -> Path | None:
    """Resolve a candidate without allowing it to escape the profiled root."""
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    return resolved if _is_within(resolved, root) else None


def _secret_risk_type(path: str) -> str | None:
    name = Path(path).name.lower()
    if name == ".env" or (name.startswith(".env.") and name not in {".env.example", ".env.template"}):
        return "environment_file"
    if re.fullmatch(r"credentials[^/]*\.json", name):
        return "credentials_file"
    if re.fullmatch(r"secrets[^/]*\.(json|yaml|yml|toml)", name):
        return "secrets_file"
    if name in {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"} or "private" in name:
        return "private_key_or_certificate"
    if name.endswith((".key", ".pem", ".p12", ".pfx")):
        return "private_key_or_certificate"
    return None


def _ignored_directory(name: str) -> bool:
    lower = name.lower()
    return (
        name in IGNORED_DIRS
        or name.endswith(".egg-info")
        or lower in {"env", "venv"}
        or lower.startswith((".venv-", "venv-", "env-"))
    )


def _is_installed_dependency_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return "site-packages" in parts or "dist-packages" in parts


def _looks_like_virtualenv(path: Path) -> bool:
    if (path / "pyvenv.cfg").is_file():
        return True
    return any(
        candidate.is_dir()
        for candidate in (
            path / "lib" / "site-packages",
            path / "Lib" / "site-packages",
        )
    )


def _files(root: Path) -> tuple[list[Path], list[Evidence]]:
    found: list[Path] = []
    warnings: list[Evidence] = []

    def onerror(error: OSError) -> None:
        if error.filename:
            try:
                path = str(Path(error.filename).resolve(strict=False).relative_to(root))
            except (OSError, RuntimeError, ValueError):
                path = "."
        else:
            path = "."
        warnings.append(_evidence("scan_error", [path], f"Repository path could not be scanned ({type(error).__name__})"))

    for current, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        safe_dirs: list[str] = []
        for name in sorted(dirs):
            path = Path(current) / name
            if _ignored_directory(name) or _is_installed_dependency_path(path.relative_to(root)) or _looks_like_virtualenv(path):
                continue
            if path.is_symlink():
                resolved = _resolve_candidate(path, root)
                if resolved is None:
                    warnings.append(_evidence("unsafe_symlink", [_rel(path, root)], "Symlink outside the repository was ignored"))
                continue
            safe_dirs.append(name)
        dirs[:] = safe_dirs
        for name in sorted(names):
            path = Path(current) / name
            relative = _rel(path, root)
            if name in IGNORED_FILES:
                continue
            if path.is_symlink():
                resolved = _resolve_candidate(path, root)
                if resolved is None:
                    warnings.append(_evidence("unsafe_symlink", [relative], "Symlink outside the repository was ignored"))
                continue
            if _resolve_candidate(path, root) is not None and path.is_file():
                found.append(path)
    return sorted(found), warnings


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _read_limited(path: Path, limit: int = 200_000) -> _ReadResult:
    try:
        with path.open("r", encoding="utf-8") as stream:
            text = stream.read(limit + 1)
        return _ReadResult(text[:limit], len(text) > limit)
    except (OSError, UnicodeDecodeError) as error:
        return _ReadResult("", error=type(error).__name__)


def _read(path: Path, limit: int = 200_000) -> str:
    return _read_limited(path, limit).text


def _evidence(signal: str, paths: list[str], detail: str) -> Evidence:
    unique_paths = sorted(dict.fromkeys(paths))
    total = len(unique_paths)
    limit = max(1, _EVIDENCE_PATH_LIMIT.get())
    shown = unique_paths[:limit]
    return Evidence(
        signal=signal,
        paths=tuple(shown),
        detail=detail,
        total_count=total,
        omitted_count=max(0, total - len(shown)),
    )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _unique_evidence(values: list[Evidence]) -> list[Evidence]:
    return list(dict.fromkeys(values))


def _under(path: str, prefix: str) -> bool:
    return not prefix or path == prefix or path.startswith(f"{prefix}/")


def _local(path: str, prefix: str) -> str:
    if not prefix:
        return path
    return path[len(prefix) + 1 :] if path.startswith(f"{prefix}/") else path


def _is_documentation_path(path: str) -> bool:
    parts = tuple(part.lower() for part in Path(path).parts)
    name = Path(path).name.lower()
    return (
        path.lower().endswith((".md", ".rst"))
        or any(part in DOCUMENTATION_DIRS or part == "agents" for part in parts)
        or name in {"readme", "readme.txt", "readme.rst", "changelog", "claude.md", "agents.md"}
    )


def _is_fixture_path(path: str) -> bool:
    parts = tuple(part.lower() for part in Path(path).parts)
    return any(part in FIXTURE_DIRS for part in parts)


def _is_test_path(path: str) -> bool:
    parts = tuple(part.lower() for part in Path(path).parts)
    return any(part in {"tests", "test", "__tests__"} for part in parts) or bool(
        re.search(r"\.(test|spec)\.[^.]+$", path, re.IGNORECASE)
    )


def _load_json(path: Path) -> tuple[dict[str, Any], str | None]:
    result = _read_limited(path)
    if result.error:
        return {}, f"JSON manifest could not be read ({result.error})"
    try:
        value = json.loads(result.text)
    except json.JSONDecodeError as error:
        return {}, f"invalid JSON manifest (line {error.lineno}, column {error.colno})"
    if not isinstance(value, dict):
        return {}, "invalid JSON manifest (top-level value is not an object)"
    return value, None


def _load_toml(path: Path) -> tuple[dict[str, Any], str | None]:
    result = _read_limited(path)
    if result.error:
        return {}, f"TOML manifest could not be read ({result.error})"
    try:
        return tomllib.loads(result.text), None
    except tomllib.TOMLDecodeError as error:
        line = getattr(error, "lineno", None)
        column = getattr(error, "colno", None)
        location = f"line {line}, column {column}" if line and column else "location unavailable"
        return {}, f"invalid TOML manifest ({location})"


def _is_runtime_path(path: str) -> bool:
    return (
        not _is_documentation_path(path)
        and not _is_fixture_path(path)
        and not _is_test_path(path)
        and not path.lower().startswith(".github/workflows/")
        and not path.lower().startswith("config/zones/")
        and Path(path).name.lower() not in {"wrangler.toml", "wrangler.json", "wrangler.jsonc"}
    )


def _runtime_integration_matches(root: Path, contents: dict[str, str], tokens: tuple[str, ...], env_prefix: str) -> tuple[list[str], list[Evidence]]:
    paths: list[str] = []
    evidence: list[Evidence] = []
    for relative, content in contents.items():
        if not _is_runtime_path(relative):
            continue
        name = Path(relative).name
        if Path(relative).suffix.lower() not in CODE_SUFFIXES and name not in MANIFEST_NAMES and name not in {".env.example", ".env.template"}:
            continue
        lower_content = content.lower()
        if name in MANIFEST_NAMES and any(re.search(rf"\b{re.escape(token.lower())}\b", lower_content) for token in tokens):
            paths.append(relative)
        env_usage = re.search(
            rf"(?:process\.env\.|os\.environ(?:\.get)?\s*[\[(]|getenv\s*\(|secrets\.|vars\.|env/)[^)\]\n]*\b{re.escape(env_prefix)}[A-Z0-9_]*\b",
            content,
            re.IGNORECASE,
        )
        if env_usage:
            paths.append(relative)
        if Path(relative).name in {".env.example", ".env.template"}:
            declared = re.findall(rf"^\s*(?:export\s+)?({re.escape(env_prefix)}[A-Z0-9_]*)\s*=", content, re.IGNORECASE | re.MULTILINE)
            if declared:
                paths.append(relative)
                evidence.append(_evidence("integration_env_declaration", [relative], f"Declared {env_prefix} environment variable names detected; values were not profiled"))
    if paths:
        evidence.insert(0, _evidence("integration_runtime_reference", _unique(paths), "Runtime code, configuration, manifest, or declared environment variable references detected"))
    return _unique(paths), evidence


def _dependency_info(manifest: str, path: Path, by_rel: dict[str, Path], all_evidence: list[Evidence]) -> tuple[list[str], list[str], list[Evidence], dict[str, Any], str | None]:
    """Return languages, frameworks, scoped evidence, parsed data, and parse status."""
    name = Path(manifest).name
    languages: list[str] = []
    frameworks: list[str] = []
    scoped: list[Evidence] = []
    data: dict[str, Any] = {}
    parse_error: str | None = None
    if name == "package.json":
        data, parse_error = _load_json(path)
        languages.append("javascript")
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        for dependency, framework in PACKAGE_FRAMEWORKS.items():
            if dependency in deps:
                frameworks.append(framework)
                scoped.append(_evidence("package_dependency", [manifest], f"Detected dependency {dependency} declared by {manifest}"))
        for dependency, framework in STRONG_ML_DEPENDENCIES.items():
            if dependency in deps:
                frameworks.append(framework)
                scoped.append(_evidence("ml_dependency", [manifest], f"Detected ML dependency {dependency} declared by {manifest}"))
    elif name == "pyproject.toml":
        data, parse_error = _load_toml(path)
        languages.append("python")
        project = data.get("project", {})
        dependency_text = " ".join(project.get("dependencies", []))
        dependency_text += " " + " ".join(item for values in project.get("optional-dependencies", {}).values() for item in values)
        for dependency, framework in PYTHON_FRAMEWORKS.items():
            if dependency.lower() in dependency_text.lower():
                frameworks.append(framework)
                signal = "ml_dependency" if dependency in STRONG_ML_DEPENDENCIES else "python_dependency"
                scoped.append(_evidence(signal, [manifest], f"Detected dependency {dependency} declared by {manifest}"))
        for dependency, framework in STRONG_ML_DEPENDENCIES.items():
            if dependency.lower() in dependency_text.lower() and framework not in frameworks:
                frameworks.append(framework)
                scoped.append(_evidence("ml_dependency", [manifest], f"Detected ML dependency {dependency} declared by {manifest}"))
    elif name in {"requirements.txt", "requirements-dev.txt"}:
        languages.append("python")
        text = _read(path).lower()
        for dependency, framework in PYTHON_FRAMEWORKS.items():
            if re.search(rf"^\s*{re.escape(dependency)}(?:[<=>!~]|\s|$)", text, re.MULTILINE):
                frameworks.append(framework)
                signal = "ml_dependency" if dependency in STRONG_ML_DEPENDENCIES else "python_dependency"
                scoped.append(_evidence(signal, [manifest], f"Detected dependency {dependency} declared by {manifest}"))
    elif name in {"setup.py", "setup.cfg"}:
        languages.append("python")
        scoped.append(_evidence("packaging_manifest", [manifest], f"Python packaging file detected: {manifest}"))
    elif name == "Cargo.toml":
        languages.append("rust")
    elif name == "go.mod":
        languages.append("go")
    elif name in {"pom.xml", "build.gradle"}:
        languages.append("java")
        text = _read(path)
        # Deterministic order: Keycloak before JAX-RS.
        if "org.keycloak" in text:
            frameworks.append("Keycloak")
            scoped.append(_evidence("keycloak_dependency", [manifest], f"Detected Keycloak dependency declared by {manifest}"))
        if re.search(r"(?:javax|jakarta)\.ws\.rs", text):
            frameworks.append("JAX-RS")
            scoped.append(_evidence("jaxrs_dependency", [manifest], f"Detected JAX-RS dependency declared by {manifest}"))
    return languages, _unique(frameworks), scoped, data, parse_error


def _component_files(rel_paths: list[str], prefix: str, nested_prefixes: list[str]) -> list[str]:
    descendants = [nested for nested in nested_prefixes if nested != prefix and _under(nested, prefix)]
    return [path for path in rel_paths if _under(path, prefix) and not any(_under(path, nested) for nested in descendants)]


def _strong_ml_evidence(paths: list[str], evidence: list[Evidence]) -> list[Evidence]:
    groups = {
        "notebook": [path for path in paths if Path(path).suffix.lower() == ".ipynb"],
        "ml_workflow_directory": [path for path in paths if ML_PATH_DIRECTORIES.intersection({part.lower() for part in Path(path).parts})],
        "model_artifact": [path for path in paths if Path(path).suffix.lower() in ML_ARTIFACT_SUFFIXES],
    }
    path_evidence = [_evidence(signal, _unique(values), "Strong ML repository signal detected") for signal, values in groups.items() if values]
    return [item for item in evidence if item.signal == "ml_dependency"] + path_evidence


def _packaging_signal(prefix: str, local_paths: list[str], manifest: str | None, manifest_data: dict[str, Any]) -> bool:
    name = Path(manifest).name if manifest else ""
    if name in {"setup.py", "setup.cfg"}:
        return True
    if name == "pyproject.toml" and ("project" in manifest_data or "build-system" in manifest_data):
        return True
    if name == "package.json" and (manifest_data.get("exports") or (manifest_data.get("main") and not manifest_data.get("private", False))):
        return True
    return any(Path(path).name == "__init__.py" and not any(part in {"tests", "test", "scripts"} for part in Path(_local(path, prefix)).parts) for path in local_paths)


def profile_repository(repo_path: str | Path, evidence_path_limit: int = DEFAULT_EVIDENCE_PATH_LIMIT) -> RepoProfile:
    if evidence_path_limit < 1:
        raise ValueError("evidence_path_limit must be at least 1")
    root = Path(repo_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path is not a directory: {root}")
    if not os.access(root, os.R_OK | os.X_OK):
        raise PermissionError(f"Repository path is not readable: {root}")
    evidence_limit_token = _EVIDENCE_PATH_LIMIT.set(evidence_path_limit)

    paths, scan_evidence = _files(root)
    rel_paths = [_rel(path, root) for path in paths]
    by_rel = dict(zip(rel_paths, paths))
    all_evidence: list[Evidence] = list(scan_evidence)
    warnings: list[str] = []
    contents: dict[str, str] = {}
    for relative, path in by_rel.items():
        is_example_env = Path(relative).name.lower() in {".env.example", ".env.template"}
        readable_candidate = (
            is_example_env
            or Path(relative).suffix in {".toml", ".json", ".txt", ".md", ".yml", ".yaml", ".xml", ".properties", ".config"}
            or Path(relative).suffix.lower() in CODE_SUFFIXES
            or Path(relative).name in {"Dockerfile", "Makefile"}
            or (not Path(relative).suffix and os.access(path, os.X_OK))
        )
        if not readable_candidate or _secret_risk_type(relative):
            continue
        result = _read_limited(path)
        contents[relative] = result.text
        if result.truncated:
            all_evidence.append(_evidence("truncated_file", [relative], "File content was limited before profiling completed"))
            warnings.append(f"File content was truncated during scan: {relative}")
        if result.error:
            all_evidence.append(_evidence("unreadable_file", [relative], f"File could not be read ({result.error})"))
            warnings.append(f"File could not be read during scan: {relative}")
    manifests = sorted(path for path in rel_paths if Path(path).name in MANIFEST_NAMES and not _is_fixture_path(path))
    nested_prefixes = sorted({str(Path(path).parent) for path in manifests if str(Path(path).parent) != "."})
    component_specs: list[tuple[str, str, list[str]]] = [("root", "", [path for path in manifests if str(Path(path).parent) == "."])]
    for prefix in nested_prefixes:
        component_specs.append((prefix, prefix, [path for path in manifests if str(Path(path).parent) == prefix]))
    container_component_prefixes = sorted({
        str(Path(path).parent)
        for path in rel_paths
        if Path(path).name.lower() in {"dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
        and str(Path(path).parent) != "."
        and not _is_fixture_path(path)
        and not _is_test_path(path)
        and str(Path(path).parent) not in nested_prefixes
    })
    for prefix in container_component_prefixes:
        component_specs.append((prefix, prefix, []))
    component_prefixes = sorted(_unique(nested_prefixes + container_component_prefixes))

    all_languages: list[str] = []
    all_frameworks: list[str] = []
    manifest_data: dict[str, dict[str, Any]] = {}
    invalid_manifests: dict[str, str] = {}
    for manifest in manifests:
        languages, frameworks, scoped, data, parse_error = _dependency_info(manifest, by_rel[manifest], by_rel, all_evidence)
        all_languages.extend(languages)
        all_frameworks.extend(frameworks)
        all_evidence.append(_evidence("manifest", [manifest], f"Recognized manifest detected: {manifest}"))
        all_evidence.extend(scoped)
        manifest_data[manifest] = data
        if parse_error:
            invalid_manifests[manifest] = parse_error
            all_evidence.append(_evidence("invalid_manifest", [manifest], parse_error))
            warnings.append(f"Manifest parsing failed: {manifest} ({parse_error})")
    if any(path.endswith((".ts", ".tsx")) for path in rel_paths):
        all_languages.append("typescript")
    if any(path.endswith((".tf", ".tfvars")) for path in rel_paths):
        all_languages.append("hcl")

    workflow_paths = [path for path in rel_paths if path.lower().startswith(".github/workflows/") and Path(path).suffix.lower() in {".yml", ".yaml"}]
    workflow_contents = {path: contents.get(path, _read(by_rel[path])) for path in workflow_paths}
    workflow_scheduled = any("schedule:" in text for text in workflow_contents.values())
    workflow_manual = any("workflow_dispatch:" in text for text in workflow_contents.values())
    self_hosted_paths = [path for path, text in workflow_contents.items() if "self-hosted" in text.lower()]
    jenkins_paths = [
        path for path in rel_paths
        if "jenkinsfile" in Path(path).name.lower()
        and not _is_fixture_path(path)
        and not _is_documentation_path(path)
    ]
    workflow_refs = [path for path in rel_paths if (path.startswith("bin/") or path.startswith("scripts/")) and any(path in text for text in workflow_contents.values())]
    readme_text = contents.get("README.md", "")
    readme_refs = [path for path in rel_paths if (path.startswith("bin/") or path.startswith("scripts/")) and (path in readme_text or Path(path).name in readme_text)]
    operational_entrypoints = _unique([path for path in rel_paths if path.startswith("bin/") and Path(path).suffix == ".sh"] + workflow_refs + readme_refs)
    reference_sources = list(operational_entrypoints)
    referenced_operational_paths = [
        candidate
        for candidate in rel_paths
        if candidate.startswith(("bin/", "scripts/"))
        and any(candidate in contents.get(source, "") or Path(candidate).name in contents.get(source, "") for source in reference_sources)
    ]
    operational_entrypoints = _unique(operational_entrypoints + referenced_operational_paths)

    components: list[ComponentProfile] = []
    for name, prefix, component_manifests in component_specs:
        local_paths = _component_files(rel_paths, prefix, component_prefixes)
        architecture_paths = [
            path for path in local_paths
            if not _is_fixture_path(path) and not _is_test_path(path) and not _is_documentation_path(path)
        ]
        local_frameworks: list[str] = []
        local_languages: list[str] = []
        local_evidence: list[Evidence] = []
        for manifest in component_manifests:
            languages, frameworks, scoped, _, _ = _dependency_info(manifest, by_rel[manifest], by_rel, [])
            local_languages.extend(languages)
            local_frameworks.extend(frameworks)
            local_evidence.extend(scoped)
        if component_manifests:
            local_evidence.insert(0, _evidence("manifest", component_manifests, f"Component manifests detected: {', '.join(component_manifests)}"))
        local_contents = {path: contents[path] for path in local_paths if path in contents}
        runtime_local_contents = {path: text for path, text in local_contents.items() if _is_runtime_path(path)}
        runtime_text = "\n".join(runtime_local_contents.values())
        worker_configs = [path for path in architecture_paths if Path(path).name in {"wrangler.toml", "wrangler.json", "wrangler.jsonc"}]
        worker = bool(worker_configs)
        infrastructure_paths = [path for path in architecture_paths if path.endswith((".tf", ".tfvars")) or path.lower().startswith(("k8s/", "kubernetes/", "helm/"))]
        container_paths = [path for path in architecture_paths if Path(path).name.lower() in {"dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}]
        package_manifests = [manifest for manifest in component_manifests if Path(manifest).name == "package.json"]
        package = manifest_data.get(package_manifests[0], {}) if package_manifests else {}
        primary_manifest = component_manifests[0] if component_manifests else None
        pyproject_manifests = [manifest for manifest in component_manifests if Path(manifest).name == "pyproject.toml"]
        pyproject = manifest_data.get(pyproject_manifests[0], {}) if pyproject_manifests else {}
        pom_manifests = [manifest for manifest in component_manifests if Path(manifest).name == "pom.xml"]
        pom_text = "\n".join(_read(by_rel[manifest]) for manifest in pom_manifests)
        console_scripts = pyproject.get("project", {}).get("scripts", {}) if isinstance(pyproject.get("project"), dict) else {}
        api_framework = any(item in local_frameworks for item in {"FastAPI", "Flask", "Django", "Express", "Fastify", "Hono"})
        api_paths = [path for path in architecture_paths if "api" in {part.lower() for part in Path(path).parts}]
        edge_api = worker and any(re.search(r"\b(fetch|Request|Response)\b", text) for text in local_contents.values())
        api_evidence_paths = _unique(api_paths + ([primary_manifest] if api_framework and primary_manifest else []) + ([path for path in local_paths if Path(path).name in {"index.ts", "index.js", "worker.ts"}] if edge_api else []))
        project_types: list[str] = []
        if any(item in local_frameworks for item in {"Next.js", "React", "Vue", "Angular", "Svelte"}):
            project_types.append("frontend")
            local_evidence.append(_evidence("frontend_framework", [primary_manifest] if primary_manifest else [], "Browser-facing framework detected in this component manifest"))
        if worker:
            project_types.append("cloudflare_worker")
            local_evidence.append(_evidence("worker_manifest", worker_configs, "Cloudflare Workers configuration detected in this component"))
        if api_framework or api_paths or edge_api:
            project_types.append("api")
            local_evidence.append(_evidence("api_signal", api_evidence_paths, "API framework, edge handler, or API route detected in this component"))
        console_script_paths = pyproject_manifests if isinstance(console_scripts, dict) and console_scripts else []
        interactive_paths = [path for path, text in runtime_local_contents.items() if re.search(r"\bcv2\.imshow\s*\(|\bwaitKey\s*\(|\btkinter\b|\bPyQt\b", text)]
        if console_script_paths or interactive_paths:
            project_types.append("application")
            local_evidence.append(_evidence("application_entrypoint", _unique(console_script_paths + interactive_paths), "Executable application entrypoint or interactive loop detected"))
        if console_script_paths:
            project_types.append("cli_tool")
            local_evidence.append(_evidence("cli_entrypoint", console_script_paths, "Console script declared by the component manifest"))
        if interactive_paths:
            project_types.extend(["desktop_application", "interactive_application"])
            local_evidence.append(_evidence("interactive_ui", interactive_paths, "Desktop or interactive display loop detected"))

        cv_inference_patterns = (
            r"cv2\.dnn\.readNet", r"readNetFromDarknet", r"blobFromImage",
            r"\.forward\s*\(", r"NMSBoxes",
        )
        cv_inference_paths = [
            path for path, text in runtime_local_contents.items()
            if sum(bool(re.search(pattern, text)) for pattern in cv_inference_patterns) >= 2
        ]
        cv_dependency = "opencv" in str(pyproject).lower() or any(
            re.search(r"^\s*(?:import|from)\s+cv2\b|^\s*(?:import|from)\s+pyopencl\b", text, re.MULTILINE)
            for text in runtime_local_contents.values()
        )
        cv_config_paths = [path for path in architecture_paths if Path(path).suffix.lower() in {".cfg", ".prototxt"}]
        classical_cv_paths = [
            path for path, text in runtime_local_contents.items()
            if re.search(r"\b(cv2|pyopencl|Sobel|Hough|image processing|histogram|EXIF)\b", text, re.IGNORECASE)
        ]
        if cv_inference_paths and cv_dependency:
            project_types.extend(["computer_vision", "ml_inference"])
            local_evidence.append(_evidence("ml_inference_signal", _unique(cv_inference_paths + cv_config_paths), "OpenCV DNN model loading, inference, and post-processing detected"))
        if (classical_cv_paths or cv_inference_paths) and cv_dependency:
            project_types.append("image_processing")
            local_evidence.append(_evidence("image_processing_signal", _unique(classical_cv_paths + cv_inference_paths), "Image-processing or classical computer-vision operations detected"))
        if (cv_inference_paths or classical_cv_paths) and cv_dependency:
            project_types.append("computer_vision")

        mcp_dependency = "fastmcp" in str(pyproject).lower() or any(
            re.search(r"^\s*(?:from|import)\s+fastmcp\b", text, re.MULTILINE)
            for text in runtime_local_contents.values()
        )
        mcp_paths = [
            path for path, text in runtime_local_contents.items()
            if re.search(r"@mcp\.tool|FastMCP\s*\(|mcp\.run\s*\(", text)
        ]
        if mcp_dependency and mcp_paths:
            project_types.extend(["mcp_server", "integration_service", "developer_tool"])
            local_evidence.append(_evidence("mcp_server_signal", _unique(pyproject_manifests + mcp_paths), "FastMCP dependency, tool registration, or MCP server run call detected"))
        opaque_tool_paths = [
            path for path, text in runtime_local_contents.items()
            if "@mcp.tool" in text and re.search(r"dict\s*\[\s*str\s*,\s*Any\s*\]", text)
        ]
        if opaque_tool_paths:
            local_evidence.append(_evidence("opaque_tool_contract", opaque_tool_paths, "MCP tools use open dict[str, Any] structures that weaken contract precision"))
        photographic_paths = [
            path for path, text in runtime_local_contents.items()
            if re.search(r"RawTherapee|PP3|EXIF|LocalLab|lens correction|LUT|histogram", text, re.IGNORECASE)
        ]
        photographic_identity = (
            any(token in str(pyproject).lower() for token in ("rawtherapee", "exifread", "pillow", "piexif"))
        )
        if photographic_paths and photographic_identity:
            project_types.extend(["photographic_tool", "image_processing"])
            local_evidence.append(_evidence("photographic_domain_signal", photographic_paths, "Photographic processing, metadata, profile, or evaluation operations detected"))

        shell_paths = [
            path for path, text in runtime_local_contents.items()
            if text.startswith("#!") and re.search(r"\b(?:ba|z|k)?sh\b", text.splitlines()[0])
        ]
        java_wrapper_paths = [
            path for path in shell_paths
            if re.search(r"\bjava\b[^\n]*\s-jar\s|pid(?:file|[-_.])|\bkill\s+\$?\(?cat\b", runtime_local_contents[path], re.IGNORECASE)
        ]
        acme_paths = [
            path for path, text in runtime_local_contents.items()
            if re.search(r"\bACME(?:v2)?\b|acme-v\d|rfc8555", text, re.IGNORECASE)
            and re.search(r"openssl|certificate|CSR|revoke", text, re.IGNORECASE)
        ]
        dns_hook_paths = [path for path in local_paths if re.search(r"(^|/)dns_(add|del)_", path) and not _is_fixture_path(path)]
        certificate_paths = [
            path for path, text in runtime_local_contents.items()
            if re.search(r"certificate|CSR|private key|revoke|renew|reload_service", text, re.IGNORECASE)
            and re.search(r"openssl|ACME", text, re.IGNORECASE)
        ]
        if shell_paths:
            project_types.extend(["cli_tool", "shell_tool"])
            local_evidence.append(_evidence("shell_tool_signal", shell_paths, "Executable shell entrypoints detected"))
        if java_wrapper_paths:
            local_evidence.append(_evidence("java_service_wrapper", java_wrapper_paths, "Shell scripts only start, stop, or track packaged JVM services"))
        if acme_paths and shell_paths:
            project_types.extend(["certificate_automation", "security_tooling", "integration_tool"])
            local_evidence.append(_evidence("acme_protocol_signal", acme_paths, "ACME protocol operations and cryptographic certificate handling detected"))
        if certificate_paths and shell_paths:
            local_evidence.append(_evidence("certificate_lifecycle_signal", certificate_paths, "Certificate issuance, renewal, installation, revocation, or reload operations detected"))
        if dns_hook_paths:
            project_types.append("integration_tool")
            local_evidence.append(_evidence("dns_provider_hooks", dns_hook_paths, "DNS challenge provider add/delete hooks detected"))

        java_main_paths = [
            path for path, text in runtime_local_contents.items()
            if Path(path).suffix.lower() == ".java"
            and re.search(r"\bpublic\s+static\s+void\s+main\s*\(", text)
        ]
        spring_boot_paths = [
            path for path, text in runtime_local_contents.items()
            if Path(path).suffix.lower() == ".java" and "@SpringBootApplication" in text
        ]
        spring_controller_paths = [
            path for path, text in runtime_local_contents.items()
            if Path(path).suffix.lower() == ".java" and re.search(r"@(RestController|Controller)\b", text)
        ]
        rabbit_listener_paths = [
            path for path, text in runtime_local_contents.items()
            if Path(path).suffix.lower() == ".java"
            and re.search(r"@RabbitListener\b|MessageListenerContainer|setQueueNames\s*\(", text)
        ]
        rabbit_publisher_paths = [
            path for path, text in runtime_local_contents.items()
            if Path(path).suffix.lower() == ".java"
            and re.search(r"\bRabbitTemplate\b|convertAndSend\s*\(|sendAndReceive\s*\(", text)
        ]
        rabbit_config_paths = [
            path for path, text in runtime_local_contents.items()
            if (
                Path(path).suffix.lower() in {".java", ".properties", ".yaml", ".yml", ".xml"}
                or Path(path).name == "pom.xml"
            )
            and re.search(
                r"spring\.rabbitmq\.|ConnectionFactory|CachingConnectionFactory|"
                r"\b(?:Queue|Exchange|Binding)\s*\(|dead.?letter|routing.?key|rabbitmq_management|"
                r"com\.rabbitmq\.http\.client|ClientParameters|RabbitManagementTemplate|managementUri",
                text,
                re.IGNORECASE,
            )
        ]
        spring_plugin = bool(re.search(r"spring-boot-(?:maven-plugin|starter-parent)", pom_text))
        spring_web = bool(re.search(r"spring-boot-starter-web|spring-web", pom_text)) or bool(spring_controller_paths)
        spring_amqp = bool(re.search(r"spring-(?:boot-starter-)?amqp|spring-rabbit|amqp-client", pom_text)) or bool(
            rabbit_listener_paths or rabbit_publisher_paths or rabbit_config_paths
        )
        spring_actuator = bool(re.search(r"spring-boot-starter-actuator", pom_text))
        spring_runtime = bool(spring_boot_paths or (java_main_paths and spring_plugin))
        if spring_runtime:
            project_types.extend(["java_application", "application"])
            local_frameworks.append("Spring Boot")
            local_evidence.append(
                _evidence(
                    "java_spring_signal",
                    _unique(pom_manifests + spring_boot_paths + java_main_paths),
                    "Spring Boot application annotation, executable main class, or Maven plugin detected",
                )
            )
        if spring_web:
            local_frameworks.append("Spring Web")
        if spring_web and (spring_runtime or spring_controller_paths):
            project_types.append("api")
            local_evidence.append(
                _evidence(
                    "spring_web_signal",
                    _unique(pom_manifests + spring_controller_paths),
                    "Spring Web dependency or HTTP controller detected",
                )
            )
        if spring_actuator:
            local_frameworks.append("Spring Boot Actuator")
            local_evidence.append(_evidence("spring_actuator_signal", pom_manifests, "Spring Boot Actuator dependency detected"))
        if spring_amqp:
            local_frameworks.append("Spring AMQP")
            local_evidence.append(
                _evidence(
                    "rabbitmq_signal",
                    _unique(pom_manifests + rabbit_listener_paths + rabbit_publisher_paths + rabbit_config_paths),
                    "Spring AMQP/RabbitMQ dependency, publisher, listener, queue, exchange, or broker configuration detected",
                )
            )
        external_http_paths = [
            path for path, text in runtime_local_contents.items()
            if Path(path).suffix.lower() == ".java"
            and re.search(r"\b(RestTemplate|WebClient|HttpClient|HttpURLConnection)\b", text)
            and re.search(r"\b(getForObject|postForObject|exchange|execute|send|forward|retry)\b", text, re.IGNORECASE)
        ]
        if external_http_paths:
            project_types.append("integration_service")
            local_evidence.append(
                _evidence(
                    "external_http_gateway",
                    external_http_paths,
                    "Configured HTTP client forwards payloads to an external gateway or downstream service",
                )
            )
        strong_ml = _strong_ml_evidence(architecture_paths, local_evidence)
        if strong_ml:
            project_types.append("data_ml")
            local_evidence.append(_evidence("ml_signal", _unique([path for item in strong_ml for path in item.paths]), "Strong ML dependency or repository artifact/layout signal detected in this component"))
        if infrastructure_paths:
            project_types.append("infrastructure")
        runtime: list[str] = []
        if any(Path(manifest).name in {"pyproject.toml", "requirements.txt", "requirements-dev.txt", "setup.py", "setup.cfg"} for manifest in component_manifests):
            runtime.append("Python")
        if package_manifests:
            runtime.append("Cloudflare Workers" if worker else "Node.js")
        if pom_manifests:
            runtime.append("JVM")
        if prefix.startswith("server/proxy") or ("Express" in local_frameworks and not worker):
            project_types.extend(item for item in ("node_service", "proxy_service") if item not in project_types)
        packaging = any(_packaging_signal(prefix, local_paths, manifest, manifest_data.get(manifest, {})) for manifest in component_manifests)
        executable_identity = {"application", "cli_tool", "mcp_server", "cloudflare_worker", "api", "pipeline", "shell_tool"}.intersection(project_types)
        if packaging and not executable_identity and not project_types:
            project_types.append("library")
        entrypoints: list[str] = []
        for package_manifest in package_manifests:
            package_data = manifest_data.get(package_manifest, {})
            if isinstance(package_data.get("main"), str):
                entrypoints.append(str(Path(prefix) / package_data["main"]).replace("./", "") if prefix else package_data["main"])
        for config in worker_configs:
            config_data, _ = _load_toml(by_rel[config]) if config.endswith(".toml") else _load_json(by_rel[config])
            if isinstance(config_data.get("main"), str):
                entrypoints.append(str(Path(prefix) / config_data["main"]).replace("./", "") if prefix else config_data["main"])
        entrypoints.extend(path for path in operational_entrypoints if _under(path, prefix))
        entrypoints.extend(path for path in architecture_paths if Path(path).name in {"server.js", "server.ts", "main.py", "app.py", "index.js", "index.ts", "worker.ts"})
        entrypoints.extend(java_main_paths)
        component_targets: list[str] = []
        if worker:
            component_targets.append("Cloudflare Workers")
        if "proxy_service" in project_types:
            component_targets.append("Node proxy service")
        if not project_types:
            project_types.append("unknown")
        if infrastructure_paths:
            local_evidence.append(_evidence("infrastructure_signal", infrastructure_paths, "Infrastructure or container deployment signal detected"))
        if container_paths:
            local_evidence.append(_evidence("container_support", container_paths, "Container packaging or runtime support detected"))
        java_source_paths = [path for path in architecture_paths if "/src/main/java/" in f"/{path}"]
        assembly_signal = bool(re.search(r"maven-(?:assembly|shade)-plugin|appassembler-maven-plugin", pom_text)) and not spring_runtime
        broker_container_signal = bool(container_paths) and any(
            re.search(r"\bimage\s*:\s*rabbitmq|FROM\s+rabbitmq", local_contents.get(path, ""), re.IGNORECASE)
            for path in container_paths
        )
        simulator_signal = spring_runtime and bool(
            re.search(r"\b(simulator|stub|mock server|fake gateway)\b", pom_text + "\n" + runtime_text, re.IGNORECASE)
        )
        has_nested_components = any(nested != prefix and _under(nested, prefix) for nested in component_prefixes)
        if broker_container_signal and not spring_runtime:
            component_role = "broker_support"
        elif assembly_signal and not has_nested_components:
            component_role = "packaging"
        elif simulator_signal:
            component_role = "simulator"
        elif spring_runtime:
            component_role = "service"
        elif pom_manifests and java_source_paths:
            component_role = "internal_library"
        else:
            component_role = "root" if not prefix else "module"
        if component_role == "internal_library":
            project_types = [
                item for item in project_types
                if item not in {"application", "java_application", "api", "integration_service"}
            ]
            project_types.append("library")
        components.append(ComponentProfile(
            name=name,
            path=prefix or ".",
            manifests=component_manifests,
            role=component_role,
            project_types=_unique(project_types),
            languages=_unique(local_languages),
            frameworks=_unique(local_frameworks),
            runtimes=_unique(runtime),
            entrypoints=_unique(entrypoints),
            deployment_targets=_unique(component_targets),
            evidence=local_evidence + strong_ml,
        ))

    component_types = [item for component in components for item in component.project_types]
    all_frameworks.extend(item for component in components for item in component.frameworks)
    spring_service_components = [
        component for component in components
        if component.role in {"service", "simulator"} and "java_application" in component.project_types
    ]
    production_spring_services = [component for component in spring_service_components if component.role == "service"]
    rabbit_evidence = [
        item for component in components for item in component.evidence if item.signal == "rabbitmq_signal"
    ]
    rabbit_publisher_evidence = [
        item for component in components for item in component.evidence
        if item.signal == "rabbitmq_signal"
        and any(
            re.search(r"\bRabbitTemplate\b|convertAndSend\s*\(|sendAndReceive\s*\(", contents.get(path, ""))
            for path in item.paths
        )
    ]
    rabbit_listener_evidence = [
        item for component in components for item in component.evidence
        if item.signal == "rabbitmq_signal"
        and any(re.search(r"@RabbitListener\b|MessageListenerContainer", contents.get(path, "")) for path in item.paths)
    ]
    external_gateway_evidence = [
        item for component in components for item in component.evidence if item.signal == "external_http_gateway"
    ]
    has_pipeline = (
        any(Path(path).name == "run_pipeline.sh" or "pipeline" in Path(path).name.lower() for path in operational_entrypoints)
        or any("pipeline" in text.lower() for text in workflow_contents.values())
        or bool(jenkins_paths)
    )
    has_automation = bool(operational_entrypoints or any(path.startswith("scripts/") for path in rel_paths))
    has_ci_cd = bool((workflow_paths and (workflow_scheduled or workflow_manual or workflow_contents)) or jenkins_paths)
    runtime_non_docs = {path: text for path, text in contents.items() if _is_runtime_path(path)}
    cloudflare_api_paths = [
        path for path, text in runtime_non_docs.items()
        if re.search(r"api\.cloudflare\.com|CLOUDFLARE_(ACCOUNT_TOKEN|API_TOKEN|ACCOUNT_ID)", text, re.IGNORECASE)
        and (
            (Path(path).suffix.lower() in {".sh", ".bash"} or not Path(path).suffix)
            and re.search(r"\bcurl\b", text, re.IGNORECASE)
            or re.search(r"^\s*(?:from|import)\s+(?:requests|urllib)\b", text, re.MULTILINE)
            or re.search(r"\bfetch\s*\(\s*[\"'`][^\"'`]*api\.cloudflare\.com", text, re.IGNORECASE)
        )
    ]
    oracle_paths = [
        path for path, text in runtime_non_docs.items()
        if (
            re.search(r"^\s*(?:from|import)\s+oracledb\b", text, re.IGNORECASE | re.MULTILINE)
            or (
                (Path(path).suffix.lower() in {".sh", ".bash"} or (not Path(path).suffix and text.startswith("#!")))
                and re.search(r"\bsqlplus\b", text, re.IGNORECASE)
            )
        )
    ]
    dns_config_paths = [
        path for path, text in contents.items()
        if not _is_documentation_path(path)
        and not _is_fixture_path(path)
        and Path(path).suffix.lower() in {".yaml", ".yml", ".toml"}
        and (
            re.search(r"CloudflareProvider|Rfc2136Provider|YamlProvider|ZoneFileSource", text)
            or (
                Path(path).suffix.lower() in {".yaml", ".yml"}
                and re.search(r"^\s*providers\s*:", text, re.MULTILINE)
                and re.search(r"^\s*zones\s*:", text, re.MULTILINE)
            )
        )
    ]
    if dns_config_paths and workflow_paths and not has_pipeline:
        has_pipeline = True
    cloudflare_dns_paths = [path for path in dns_config_paths if re.search(r"CloudflareProvider|octodns-cloudflare|octodns_cloudflare", contents.get(path, ""))]
    rfc2136_dns_paths = [path for path in dns_config_paths if re.search(r"Rfc2136Provider|octodns-bind|octodns_bind", contents.get(path, ""))]
    sensitive_operation_paths = [
        path for path, text in runtime_non_docs.items()
        if re.search(r"\b(?:scp|sftp|ssh|WebDAV|reload_service|RELOAD_CMD|revoke_certificate)\b", text, re.IGNORECASE)
        and (
            Path(path).suffix.lower() in {".sh", ".bash", ".ps1"}
            or (not Path(path).suffix and text.startswith("#!"))
            or re.search(r"^\s*(?:from|import)\s+subprocess\b", text, re.MULTILINE)
        )
    ]
    java_wrapper_evidence = [
        item for component in components for item in component.evidence if item.signal == "java_service_wrapper"
    ]
    has_operations = bool(cloudflare_api_paths or oracle_paths or self_hosted_paths or sensitive_operation_paths or dns_config_paths or java_wrapper_evidence)
    project_types = [item for item in _unique(component_types) if item != "unknown"]
    if has_pipeline:
        project_types.append("pipeline")
    if has_automation:
        project_types.append("automation")
    if has_ci_cd:
        project_types.append("ci_cd")
    if has_operations:
        project_types.append("operations")
    if dns_config_paths:
        project_types.extend(["dns_iac", "dns_configuration"])
    if spring_service_components:
        project_types.append("java_application")
    if rabbit_evidence and production_spring_services:
        project_types.extend(["messaging_application", "integration_service"])
    if rabbit_publisher_evidence and rabbit_listener_evidence:
        project_types.append("message_pipeline")
    if len(production_spring_services) >= 2:
        project_types.append("distributed_application")
    if external_gateway_evidence:
        project_types.append("integration_service")
    runnable_components = [component for component in components if any(item in component.project_types for item in {"cloudflare_worker", "node_service", "proxy_service", "api"})]
    if len(runnable_components) > 1 and {"cloudflare_worker", "proxy_service"}.issubset(set(component_types)):
        project_types.append("hybrid_service")
    if not project_types or project_types == ["unknown"]:
        project_types = ["library"] if any("library" in component.project_types for component in components) else ["unknown"]

    model_reference_paths: list[str] = []
    referenced_model_names: set[str] = set()
    if {"ml_inference", "data_ml"}.intersection(project_types):
        for path, text in runtime_non_docs.items():
            matches = re.findall(r"""["']([^"']+\.(?:weights|onnx|pt|pth|safetensors|h5|keras))["']""", text, re.IGNORECASE)
            if matches:
                model_reference_paths.append(path)
                referenced_model_names.update(Path(match).name for match in matches)
    versioned_model_names = {Path(path).name for path in rel_paths if Path(path).suffix.lower() in ML_ARTIFACT_SUFFIXES or Path(path).suffix.lower() == ".weights"}
    missing_model_names = sorted(referenced_model_names - versioned_model_names)
    if missing_model_names:
        all_evidence.append(_evidence("external_model_artifact_missing", model_reference_paths, f"Referenced model artifacts are not present in the repository: {', '.join(missing_model_names)}"))
        warnings.append(f"External model artifacts referenced but not versioned: {', '.join(missing_model_names)}")

    test_dir_paths = [path for path in rel_paths if any(part.lower() in {"tests", "test", "__tests__"} for part in Path(path).parts)]
    test_file_paths = [path for path in rel_paths if re.search(r"\.(test|spec)\.[^.]+$", path, re.IGNORECASE)]
    operational_test_like = [path for path in rel_paths if Path(path).name.lower().startswith("test_") and (path.startswith("scripts/") or path.startswith("bin/"))]
    standalone_test_paths = [path for path in rel_paths if Path(path).name.lower().startswith("test_") and path not in operational_test_like and re.search(r"assert\s|pytest|unittest|def\s+test_", contents.get(path, ""), re.IGNORECASE)]
    real_test_paths = _unique([path for path in test_dir_paths + test_file_paths + standalone_test_paths if path not in operational_test_like])
    test_frameworks: list[str] = []
    test_commands: list[str] = []
    test_evidence: list[Evidence] = []
    if real_test_paths:
        test_frameworks.append("repository test files")
        test_evidence.append(_evidence("test_files", real_test_paths, "Test directories or test-file conventions detected"))
    bats_paths = [path for path in real_test_paths if Path(path).suffix.lower() == ".bats"]
    shellcheck_paths = [
        path for path, text in contents.items()
        if not _is_fixture_path(path)
        and not _is_test_path(path)
        and (
            path.lower().startswith(".github/workflows/")
            or Path(path).suffix.lower() in {".sh", ".bash"}
            or Path(path).name.lower() in {".shellcheckrc", "makefile"}
        )
        and re.search(r"\bshellcheck\b", text, re.IGNORECASE)
    ]
    if bats_paths:
        test_frameworks.append("Bats")
        test_commands.append("bats")
        test_evidence.append(_evidence("bats_tests", bats_paths, "Bats shell test suite detected"))
    if shellcheck_paths:
        test_frameworks.append("ShellCheck")
        test_evidence.append(_evidence("shellcheck_config", shellcheck_paths, "ShellCheck usage or configuration detected"))
    test_config_paths = [path for path in rel_paths if Path(path).name in {"pytest.ini", "tox.ini", "unittest.cfg"} or Path(path).name.startswith(("vitest.config", "jest.config", "playwright.config"))]
    package_test_manifests = [manifest for manifest, data in manifest_data.items() if Path(manifest).name == "package.json" and isinstance(data.get("scripts"), dict) and "test" in data["scripts"]]
    py_test_configs = [manifest for manifest, data in manifest_data.items() if Path(manifest).name == "pyproject.toml" and ("[tool.pytest" in _read(by_rel[manifest]) or "pytest" in _read(by_rel[manifest]).lower() and real_test_paths)]
    maven_manifests = [manifest for manifest in manifests if Path(manifest).name == "pom.xml"]
    maven_wrappers = sorted(path for path in rel_paths if Path(path).name == "mvnw" and not _is_fixture_path(path))
    if package_test_manifests:
        test_frameworks.append("package test script")
        test_commands.extend("npm test" for _ in package_test_manifests)
        test_evidence.append(_evidence("test_config", package_test_manifests, "Package manifest exposes a test script"))
    if test_config_paths or py_test_configs:
        test_frameworks.append("pytest" if any(Path(path).name in {"pytest.ini", "tox.ini"} or "pytest" in _read(by_rel[path]).lower() for path in test_config_paths + py_test_configs) else "test configuration")
        test_commands.append("pytest")
        test_evidence.append(_evidence("test_config", _unique(test_config_paths + py_test_configs), "Recognized test-runner configuration detected"))
    if maven_manifests:
        if maven_wrappers:
            wrapper = min(maven_wrappers, key=lambda path: (len(Path(path).parts), path))
            wrapper_parent = str(Path(wrapper).parent)
            test_commands.append("./mvnw test" if wrapper_parent == "." else f"cd {wrapper_parent} && ./mvnw test")
        else:
            test_commands.append("mvn test")
        test_frameworks.append("Maven")
        test_evidence.append(_evidence("maven_test_command", maven_manifests + maven_wrappers[:1], "Maven project supports a repository-local test command"))
    tests = TestProfile(bool(real_test_paths or test_commands), _unique(test_frameworks), _unique(test_commands), test_evidence)

    skipped_test_build_paths = [
        path for path, text in contents.items()
        if not _is_documentation_path(path)
        and not _is_fixture_path(path)
        and not _is_test_path(path)
        and (
            path.lower().startswith(".github/workflows/")
            or "jenkinsfile" in Path(path).name.lower()
            or Path(path).suffix.lower() in {".sh", ".bash", ".xml", ".gradle", ".yaml", ".yml"}
        )
        and re.search(r"-DskipTests(?:=true)?\b|-Dmaven\.test\.skip=true\b", text)
    ]
    if skipped_test_build_paths:
        all_evidence.append(_evidence("tests_disabled_in_build", skipped_test_build_paths, "A build or delivery pipeline explicitly disables tests"))
        warnings.append("Tests are disabled in at least one build or delivery path")

    deploy_tools: list[str] = []
    deploy_targets = _unique([target for component in components for target in component.deployment_targets])
    deploy_evidence: list[Evidence] = []
    if any("cloudflare_worker" in component.project_types for component in components):
        deploy_tools.append("wrangler")
        deploy_evidence.append(_evidence("cloudflare_deployment", [path for path in rel_paths if Path(path).name.startswith("wrangler")], "Wrangler configuration identifies Cloudflare Workers deployment"))
    if workflow_paths:
        deploy_tools.append("github-actions")
        deploy_evidence.append(_evidence("ci_cd_workflow", workflow_paths, "GitHub Actions workflows detected"))
    package_manifests = [manifest for manifest in manifests if Path(manifest).name == "package.json" and manifest_data.get(manifest, {}).get("scripts")]
    if package_manifests:
        deploy_tools.append("npm-scripts")
        deploy_evidence.append(_evidence("npm_scripts", package_manifests, "npm scripts detected in package manifests"))
    container_paths = [
        path for path in rel_paths
        if Path(path).name.lower() in {"dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}
        and not _is_fixture_path(path) and not _is_test_path(path)
    ]
    if container_paths:
        deploy_tools.append("containers")
        deploy_evidence.append(_evidence("container_support", container_paths, "Container packaging or runtime support detected"))
    ansible_paths = [path for path in rel_paths if Path(path).suffix.lower() in {".yaml", ".yml"} and "ansible" in {part.lower() for part in Path(path).parts}]
    if ansible_paths:
        deploy_tools.append("ansible")
        deploy_evidence.append(_evidence("ansible_deployment", ansible_paths, "Ansible deployment or broker provisioning configuration detected"))
    if jenkins_paths:
        deploy_tools.append("jenkins")
        deploy_evidence.append(_evidence("jenkins_pipeline", jenkins_paths, "Jenkins delivery pipeline detected"))
    if maven_manifests:
        deploy_tools.append("maven")
        deploy_evidence.append(_evidence("maven_packaging", maven_manifests, "Maven build and JAR/module packaging detected"))
    if cloudflare_dns_paths:
        deploy_targets.append("Cloudflare DNS")
        deploy_evidence.append(_evidence("cloudflare_dns_target", cloudflare_dns_paths, "octoDNS Cloudflare DNS target detected"))
    if rfc2136_dns_paths:
        deploy_targets.append("RFC2136/BIND DNS")
        deploy_evidence.append(_evidence("rfc2136_dns_target", rfc2136_dns_paths, "RFC2136 or BIND DNS target detected"))
    dns_hook_paths = [path for path in rel_paths if re.search(r"(^|/)dns_(add|del)_", path) and not _is_fixture_path(path)]
    if dns_hook_paths:
        deploy_targets.append("DNS challenge providers")
        deploy_evidence.append(_evidence("dns_challenge_targets", dns_hook_paths, "DNS provider hooks can mutate challenge records"))
    if sensitive_operation_paths:
        deploy_targets.extend(["local filesystem", "remote hosts", "generic web servers"])
        deploy_evidence.append(_evidence("remote_certificate_operations", sensitive_operation_paths, "Local/remote certificate copy, install, or reload operations detected"))
    cpanel_iis_paths = [
        path for path in rel_paths
        if re.search(r"cpanel|iis", Path(path).name, re.IGNORECASE) and not _is_fixture_path(path)
    ]
    if any("cpanel" in path.lower() for path in cpanel_iis_paths):
        deploy_targets.append("cPanel")
    if any("iis" in path.lower() for path in cpanel_iis_paths):
        deploy_targets.append("IIS")
    deploy_targets = _unique(deploy_targets)
    deployment = DeploymentProfile(_unique(deploy_tools), deploy_targets, deploy_evidence)

    entrypoints = _unique(operational_entrypoints + [path for component in components for path in component.entrypoints])
    architecture_evidence: list[Evidence] = [item for component in components for item in component.evidence]
    if workflow_paths:
        architecture_evidence.append(_evidence("ci_cd_workflow", workflow_paths, "Workflow automation detected"))
    if self_hosted_paths:
        architecture_evidence.append(_evidence("self_hosted_runner", self_hosted_paths, "Self-hosted CI runner detected"))
    if operational_entrypoints:
        architecture_evidence.append(_evidence("operational_entrypoint", operational_entrypoints, "Operational scripts or workflow-referenced commands detected"))
    if cloudflare_api_paths:
        architecture_evidence.append(_evidence("cloudflare_api", cloudflare_api_paths, "Runtime code calls or configures the Cloudflare API"))
    if oracle_paths:
        architecture_evidence.append(_evidence("oracle_operation", oracle_paths, "Runtime code or configuration references Oracle operations"))
    if dns_config_paths:
        architecture_evidence.append(_evidence("dns_configuration", dns_config_paths, "Declarative DNS providers, zones, or targets detected"))
    if sensitive_operation_paths:
        architecture_evidence.append(_evidence("sensitive_operations", sensitive_operation_paths, "Remote copy, command execution, certificate revocation, or reload operations detected"))
    if rabbit_evidence:
        architecture_evidence.extend(_unique_evidence(rabbit_evidence))
    if external_gateway_evidence:
        architecture_evidence.extend(_unique_evidence(external_gateway_evidence))
    styles: list[str] = []
    if "hybrid_service" in project_types:
        styles.append("hybrid-service")
    if has_pipeline:
        styles.append("operational-pipeline")
    if any("cloudflare_worker" in component.project_types for component in components):
        styles.append("edge-worker")
    if any("proxy_service" in component.project_types for component in components):
        styles.append("node-proxy")
    if "messaging_application" in project_types:
        styles.append("distributed-messaging-application")
    if "message_pipeline" in project_types:
        styles.append("message-pipeline")
    if not styles:
        styles.append("package-or-unknown")
    root_component = next(component for component in components if component.name == "root")
    root_component.project_types = [item for item in root_component.project_types if item != "unknown"]
    for operational_type in ("pipeline", "automation", "ci_cd", "operations"):
        if operational_type in project_types and operational_type not in root_component.project_types:
            root_component.project_types.append(operational_type)
    architecture = ArchitectureProfile(styles, entrypoints, architecture_evidence)

    integrations: list[IntegrationProfile] = []
    for name, tokens, env_prefix in (("jira", ("jira", "atlassian"), "JIRA_"), ("confluence", ("confluence",), "CONFLUENCE_"), ("dify", ("dify",), "DIFY_"), ("cloudflare_api", ("api.cloudflare.com",), "CLOUDFLARE_"), ("oracle_database", ("oracledb", "sqlplus", "oracle"), "ORACLE_")):
        matches, integration_evidence = _runtime_integration_matches(root, contents, tokens, env_prefix)
        if name == "dify":
            dify_workflow_paths = [
                path for path in workflow_paths
                if re.search(r"\bDIFY_[A-Z0-9_]+\b|dify_[a-z0-9_]+\.py", workflow_contents.get(path, ""), re.IGNORECASE)
            ]
            if dify_workflow_paths:
                matches = _unique(matches + dify_workflow_paths)
                integration_evidence = _unique_evidence(
                    integration_evidence
                    + [_evidence("integration_workflow_reference", dify_workflow_paths, "Workflow invokes Dify-specific scripts or declared variables")]
                )
        if name == "cloudflare_api":
            matches = _unique(cloudflare_api_paths)
            integration_evidence = [_evidence("cloudflare_api", matches, "Runtime Cloudflare API endpoint or token variable detected")] if matches else []
        if name == "oracle_database":
            matches = _unique(oracle_paths)
            integration_evidence = [_evidence("oracle_operation", matches, "Oracle client, SQL*Plus, or Oracle environment variable detected")] if matches else []
        if matches:
            integrations.append(IntegrationProfile(name, True, Availability.REQUIRES_AUTHORIZATION, integration_evidence))
        else:
            integrations.append(IntegrationProfile(name, False, Availability.UNAVAILABLE))
    if rabbit_evidence:
        integrations.append(
            IntegrationProfile(
                "rabbitmq",
                True,
                Availability.AVAILABLE,
                _unique_evidence(rabbit_evidence),
            )
        )
    else:
        integrations.append(IntegrationProfile("rabbitmq", False, Availability.UNAVAILABLE))
    if external_gateway_evidence:
        integrations.append(
            IntegrationProfile(
                "external_http_gateway",
                True,
                Availability.AVAILABLE,
                _unique_evidence(external_gateway_evidence),
            )
        )
    else:
        integrations.append(IntegrationProfile("external_http_gateway", False, Availability.UNAVAILABLE))

    risks: list[str] = []
    if not tests.present:
        risks.append("No real test suite or recognized test command detected")
    if deployment.tools:
        risks.append("Deployment or automation tooling detected; generated agents must remain non-deploying")
    secret_names = [path for path in rel_paths if _secret_risk_type(path)]
    if secret_names:
        risks.append("Potential credential-bearing files detected; contents were excluded from profiling")
        all_evidence.append(_evidence("secret_filename", secret_names, "Sensitive-looking filenames detected; file contents were not read"))
        for path in secret_names:
            warnings.append(f"Sensitive-looking file excluded from scan: {path}")
    for item in scan_evidence:
        if item.signal == "unsafe_symlink":
            warnings.append(f"Unsafe symlink excluded from scan: {item.paths[0]}")
    if invalid_manifests:
        risks.append("One or more dependency manifests are invalid; dependency and framework inference is incomplete")
    if not all_languages:
        risks.append("Language could not be inferred from recognized manifests")

    project_types = _unique(project_types)
    if "messaging_application" in project_types:
        primary_project_types = [item for item in ("messaging_application", "integration_service") if item in project_types]
    elif "mcp_server" in project_types:
        primary_project_types = [item for item in ("mcp_server", "image_processing", "photographic_tool") if item in project_types]
    elif "certificate_automation" in project_types:
        primary_project_types = [item for item in ("cli_tool", "certificate_automation", "security_tooling") if item in project_types]
    elif "computer_vision" in project_types:
        primary_project_types = [item for item in ("application", "computer_vision", "ml_inference") if item in project_types]
    elif "dns_iac" in project_types:
        primary_project_types = [item for item in ("pipeline", "dns_iac") if item in project_types]
    elif "hybrid_service" in project_types:
        primary_project_types = ["hybrid_service"]
    else:
        primary_project_types = [
            item for item in project_types
            if item not in {"automation", "ci_cd", "operations", "containerized", "packaged_python", "shell_tool"}
        ][:3]
    secondary_project_types = [item for item in project_types if item not in primary_project_types]
    if "messaging_application" in primary_project_types:
        secondary_project_types = [item for item in secondary_project_types if item != "cli_tool"]
    if container_paths and "containerized" not in secondary_project_types:
        secondary_project_types.append("containerized")
    if any(Path(manifest).name == "pyproject.toml" for manifest in manifests) and "library" not in primary_project_types:
        secondary_project_types.append("packaged_python")
    project_types = _unique(primary_project_types + secondary_project_types)
    profile = RepoProfile(
        path=str(root), name=root.name, project_types=project_types, primary_project_types=primary_project_types, secondary_project_types=_unique(secondary_project_types), languages=_unique(all_languages), frameworks=_unique(all_frameworks),
        manifests=manifests, components=components, architecture=architecture, tests=tests, deployment=deployment,
        integrations=integrations, risks=risks, evidence=all_evidence, warnings=_unique(warnings),
    )
    _EVIDENCE_PATH_LIMIT.reset(evidence_limit_token)
    return profile
