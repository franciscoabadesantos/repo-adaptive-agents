"""Deterministic repository profiling based on manifests, workflows, and entrypoints."""

from __future__ import annotations

import json
import os
import re
import tomllib
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
CODE_SUFFIXES = {".c", ".cc", ".cpp", ".cs", ".go", ".java", ".js", ".jsx", ".kt", ".mjs", ".php", ".py", ".rb", ".rs", ".sh", ".ts", ".tsx"}
DOCUMENTATION_DIRS = {"docs", "doc", "documentation", "templates"}


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
    return name in IGNORED_DIRS or name.endswith(".egg-info")


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
            if _ignored_directory(name):
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
    return Evidence(signal=signal, paths=tuple(paths), detail=detail)


def _unique(values: list[str]) -> list[str]:
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
    return not _is_documentation_path(path) and not path.lower().startswith(".github/workflows/") and Path(path).name.lower() not in {"wrangler.toml", "wrangler.json", "wrangler.jsonc"}


def _runtime_integration_matches(root: Path, contents: dict[str, str], tokens: tuple[str, ...], env_prefix: str) -> tuple[list[str], list[Evidence]]:
    paths: list[str] = []
    evidence: list[Evidence] = []
    for relative, content in contents.items():
        if not _is_runtime_path(relative):
            continue
        lower_content = content.lower()
        if any(re.search(rf"\b{re.escape(token.lower())}\b", lower_content) for token in tokens):
            paths.append(relative)
        if re.search(rf"\b{re.escape(env_prefix)}[A-Z0-9_]*\b", content, re.IGNORECASE):
            paths.append(relative)
        if Path(relative).name == ".env.example":
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


def profile_repository(repo_path: str | Path) -> RepoProfile:
    root = Path(repo_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path is not a directory: {root}")
    if not os.access(root, os.R_OK | os.X_OK):
        raise PermissionError(f"Repository path is not readable: {root}")

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
            or Path(relative).suffix in {".toml", ".json", ".txt", ".md", ".yml", ".yaml"}
            or Path(relative).suffix.lower() in CODE_SUFFIXES
            or Path(relative).name in {"Dockerfile", "Makefile"}
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
    manifests = sorted(path for path in rel_paths if Path(path).name in MANIFEST_NAMES)
    nested_prefixes = sorted({str(Path(path).parent) for path in manifests if str(Path(path).parent) != "."})
    component_specs: list[tuple[str, str, list[str]]] = [("root", "", [path for path in manifests if str(Path(path).parent) == "."])]
    for prefix in nested_prefixes:
        component_specs.append((prefix, prefix, [path for path in manifests if str(Path(path).parent) == prefix]))

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
        local_paths = _component_files(rel_paths, prefix, nested_prefixes)
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
        worker_configs = [path for path in local_paths if Path(path).name in {"wrangler.toml", "wrangler.json", "wrangler.jsonc"}]
        worker = bool(worker_configs)
        infrastructure_paths = [path for path in local_paths if path.endswith((".tf", ".tfvars")) or path.lower().startswith(("k8s/", "kubernetes/", "helm/")) or Path(path).name == "Dockerfile"]
        package_manifests = [manifest for manifest in component_manifests if Path(manifest).name == "package.json"]
        package = manifest_data.get(package_manifests[0], {}) if package_manifests else {}
        primary_manifest = component_manifests[0] if component_manifests else None
        package_scripts = package.get("scripts", {}) if isinstance(package.get("scripts", {}), dict) else {}
        api_framework = any(item in local_frameworks for item in {"FastAPI", "Flask", "Django", "Express", "Fastify", "Hono"})
        api_paths = [path for path in local_paths if not _is_documentation_path(path) and "api" in {part.lower() for part in Path(path).parts}]
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
        strong_ml = _strong_ml_evidence(local_paths, local_evidence)
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
        if prefix.startswith("server/proxy") or ("Express" in local_frameworks and not worker):
            project_types.extend(item for item in ("node_service", "proxy_service") if item not in project_types)
        packaging = any(_packaging_signal(prefix, local_paths, manifest, manifest_data.get(manifest, {})) for manifest in component_manifests)
        if packaging and not project_types:
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
        entrypoints.extend(path for path in local_paths if Path(path).name in {"server.js", "server.ts", "main.py", "app.py", "index.js", "index.ts", "worker.ts"})
        component_targets: list[str] = []
        if worker:
            component_targets.append("Cloudflare Workers")
        if "proxy_service" in project_types:
            component_targets.append("Node proxy service")
        if not project_types:
            project_types.append("unknown")
        if infrastructure_paths:
            local_evidence.append(_evidence("infrastructure_signal", infrastructure_paths, "Infrastructure or container deployment signal detected"))
        components.append(ComponentProfile(
            name=name,
            path=prefix or ".",
            manifests=component_manifests,
            project_types=_unique(project_types),
            languages=_unique(local_languages),
            frameworks=_unique(local_frameworks),
            runtimes=_unique(runtime),
            entrypoints=_unique(entrypoints),
            deployment_targets=_unique(component_targets),
            evidence=local_evidence + strong_ml,
        ))

    component_types = [item for component in components for item in component.project_types]
    has_pipeline = any(Path(path).name == "run_pipeline.sh" or "pipeline" in Path(path).name.lower() for path in operational_entrypoints) or any("pipeline" in text.lower() for text in workflow_contents.values())
    has_automation = bool(operational_entrypoints or any(path.startswith("scripts/") for path in rel_paths))
    has_ci_cd = bool(workflow_paths and (workflow_scheduled or workflow_manual or workflow_contents))
    runtime_non_docs = {path: text for path, text in contents.items() if _is_runtime_path(path)}
    cloudflare_api_paths = [path for path, text in runtime_non_docs.items() if re.search(r"api\.cloudflare\.com|CLOUDFLARE_(ACCOUNT_TOKEN|API_TOKEN|ACCOUNT_ID)", text, re.IGNORECASE)]
    oracle_paths = [path for path, text in runtime_non_docs.items() if re.search(r"oracledb|sqlplus|ORACLE_|oracle", text, re.IGNORECASE)]
    has_operations = bool(cloudflare_api_paths or oracle_paths or self_hosted_paths)
    project_types = [item for item in _unique(component_types) if item != "unknown"]
    if has_pipeline:
        project_types.append("pipeline")
    if has_automation:
        project_types.append("automation")
    if has_ci_cd:
        project_types.append("ci_cd")
    if has_operations:
        project_types.append("operations")
    runnable_components = [component for component in components if any(item in component.project_types for item in {"cloudflare_worker", "node_service", "proxy_service", "api"})]
    if len(runnable_components) > 1 and {"cloudflare_worker", "proxy_service"}.issubset(set(component_types)):
        project_types.append("hybrid_service")
    if not project_types or project_types == ["unknown"]:
        project_types = ["library"] if any("library" in component.project_types for component in components) else ["unknown"]

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
    test_config_paths = [path for path in rel_paths if Path(path).name in {"pytest.ini", "tox.ini", "unittest.cfg"} or Path(path).name.startswith(("vitest.config", "jest.config", "playwright.config"))]
    package_test_manifests = [manifest for manifest, data in manifest_data.items() if Path(manifest).name == "package.json" and isinstance(data.get("scripts"), dict) and "test" in data["scripts"]]
    py_test_configs = [manifest for manifest, data in manifest_data.items() if Path(manifest).name == "pyproject.toml" and ("[tool.pytest" in _read(by_rel[manifest]) or "pytest" in _read(by_rel[manifest]).lower() and real_test_paths)]
    if package_test_manifests:
        test_frameworks.append("package test script")
        test_commands.extend("npm test" for _ in package_test_manifests)
        test_evidence.append(_evidence("test_config", package_test_manifests, "Package manifest exposes a test script"))
    if test_config_paths or py_test_configs:
        test_frameworks.append("pytest" if any(Path(path).name in {"pytest.ini", "tox.ini"} or "pytest" in _read(by_rel[path]).lower() for path in test_config_paths + py_test_configs) else "test configuration")
        test_commands.append("pytest")
        test_evidence.append(_evidence("test_config", _unique(test_config_paths + py_test_configs), "Recognized test-runner configuration detected"))
    tests = TestProfile(bool(real_test_paths or test_commands), _unique(test_frameworks), _unique(test_commands), test_evidence)

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
    styles: list[str] = []
    if "hybrid_service" in project_types:
        styles.append("hybrid-service")
    if has_pipeline:
        styles.append("operational-pipeline")
    if any("cloudflare_worker" in component.project_types for component in components):
        styles.append("edge-worker")
    if any("proxy_service" in component.project_types for component in components):
        styles.append("node-proxy")
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

    return RepoProfile(
        path=str(root), name=root.name, project_types=_unique(project_types), languages=_unique(all_languages), frameworks=_unique(all_frameworks),
        manifests=manifests, components=components, architecture=architecture, tests=tests, deployment=deployment,
        integrations=integrations, risks=risks, evidence=all_evidence, warnings=_unique(warnings),
    )
