import json
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import tomllib

from repo_adaptive_agents.generator import proposal_diff, write_proposal
from repo_adaptive_agents.generator import ProposalError
from repo_adaptive_agents.cli import main
from repo_adaptive_agents.models import to_jsonable
from repo_adaptive_agents.profiler import profile_repository
from repo_adaptive_agents.recommender import recommend_team


ROOT = Path(__file__).parent / "fixtures"


class MvpTests(unittest.TestCase):
    @staticmethod
    def _write(root: Path, relative: str, content: str, executable: bool = False) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if executable:
            path.chmod(0o755)
        return path

    def test_profiles_cover_materially_different_repositories(self):
        frontend = profile_repository(ROOT / "frontend-next")
        worker = profile_repository(ROOT / "cloudflare-worker")
        api = profile_repository(ROOT / "backend-api")
        ml = profile_repository(ROOT / "python-ml")

        self.assertIn("frontend", frontend.project_types)
        self.assertIn("browser_qa", {agent.name for agent in recommend_team(frontend).agents})
        self.assertNotIn("browser_qa", {agent.name for agent in recommend_team(worker).agents})
        self.assertIn("cloudflare_worker", worker.project_types)
        self.assertIn("worker_reviewer", {agent.name for agent in recommend_team(worker).agents})
        self.assertIn("api", api.project_types)
        self.assertIn("api_reviewer", {agent.name for agent in recommend_team(api).agents})
        self.assertIn("data_ml", ml.project_types)
        self.assertIn("ml_reviewer", {agent.name for agent in recommend_team(ml).agents})

    def test_next_fullstack_ai_is_not_classified_as_ml(self):
        profile = profile_repository(ROOT / "next-fullstack-ai")
        plan = recommend_team(profile)

        self.assertEqual(profile.project_types, ["frontend", "api"])
        self.assertNotIn("data_ml", profile.project_types)
        self.assertNotIn("ml_reviewer", {agent.name for agent in plan.agents})
        self.assertFalse(next(item for item in profile.integrations if item.name == "dify").detected)
        self.assertNotIn("dify_workflow", {item.capability_id for item in plan.capabilities})

    def test_capability_evidence_matches_the_rule_that_selected_it(self):
        profile = profile_repository(ROOT / "next-fullstack-ai")
        plan = recommend_team(profile)
        by_id = {item.capability_id: item for item in plan.capabilities}

        self.assertEqual({item.signal for item in by_id["browser_qa"].evidence}, {"frontend_framework"})
        self.assertEqual({item.signal for item in by_id["api_contract_review"].evidence}, {"api_signal"})
        self.assertEqual({item.signal for item in by_id["test_strategy"].evidence}, {"test_files", "test_config"})
        self.assertTrue(all(path.startswith("app/api/") for item in by_id["api_contract_review"].evidence for path in item.paths))

    def test_documentation_only_dify_reference_is_not_an_integration(self):
        profile = profile_repository(ROOT / "next-fullstack-ai")
        dify = next(item for item in profile.integrations if item.name == "dify")

        self.assertFalse(dify.detected)
        self.assertEqual(dify.authorization, "unavailable")
        self.assertEqual(dify.evidence, [])

    def test_recommendations_are_capability_first_and_auditable(self):
        profile = profile_repository(ROOT / "cloudflare-worker")
        plan = recommend_team(profile)
        capability_ids = {item.capability_id for item in plan.capabilities}
        self.assertIn("worker_runtime_review", capability_ids)
        self.assertIn("security_review", capability_ids)
        self.assertTrue(any(item.evidence for item in plan.capabilities if item.capability_id == "worker_runtime_review"))
        self.assertTrue(plan.assumptions)

    def test_ml_capability_uses_strong_ml_evidence(self):
        profile = profile_repository(ROOT / "python-ml")
        plan = recommend_team(profile)
        ml = next(item for item in plan.capabilities if item.capability_id == "ml_reproducibility")

        self.assertEqual({item.signal for item in ml.evidence}, {"ml_signal"})
        self.assertTrue(any("pyproject.toml" in path for item in ml.evidence for path in item.paths))

    def test_external_reference_requires_authorization(self):
        profile = profile_repository(ROOT / "backend-api")
        integration = next(item for item in profile.integrations if item.name == "jira")
        self.assertTrue(integration.detected)
        plan = recommend_team(profile)
        jira = next(item for item in plan.integrations if item.name == "jira")
        self.assertEqual(jira.status, "requires_authorization")
        self.assertTrue(any(question.id == "authorize_jira" for question in plan.questions))

    def test_proposal_is_valid_toml_and_does_not_require_existing_codex(self):
        profile = profile_repository(ROOT / "frontend-next")
        plan = recommend_team(profile)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proposal"
            files = write_proposal(profile, plan, output)
            self.assertGreaterEqual(len(files), 4)
            tomllib.loads((output / "config.toml").read_text())
            for path in (output / "agents").glob("*.toml"):
                tomllib.loads(path.read_text())
            payload = json.loads((output / "profile.json").read_text())
            json.loads((output / "team-plan.json").read_text())
            self.assertEqual(payload["name"], "frontend-next")
            self.assertIn("[agents.repo_mapper]", proposal_diff(output, Path(temporary) / "missing-codex"))

    def test_serialization_is_json_compatible(self):
        profile = profile_repository(ROOT / "python-ml")
        json.dumps(to_jsonable(profile))

    def test_operational_python_pipeline_is_not_a_library_or_test_suite(self):
        profile = profile_repository(ROOT / "pipeline-operational")
        plan = recommend_team(profile)
        capability_ids = {item.capability_id for item in plan.capabilities}

        self.assertTrue({"pipeline", "automation", "ci_cd", "operations"}.issubset(profile.project_types))
        self.assertNotIn("library", profile.project_types)
        self.assertFalse(profile.tests.present)
        self.assertIn("bin/run_pipeline.sh", profile.architecture.entrypoints)
        self.assertIn("scripts/sync_oracle_from_csv.py", profile.architecture.entrypoints)
        self.assertIn("pipeline_review", capability_ids)
        self.assertIn("ci_cd_review", capability_ids)
        self.assertIn("operations_review", capability_ids)
        self.assertIn("security_review", capability_ids)
        self.assertIn("dependency_audit", capability_ids)
        self.assertNotIn("worker_runtime_review", capability_ids)
        self.assertNotIn("browser_qa", capability_ids)
        self.assertNotIn("ml_reproducibility", capability_ids)
        self.assertTrue(next(item for item in profile.integrations if item.name == "cloudflare_api").detected)
        self.assertEqual(next(item for item in plan.capabilities if item.capability_id == "test_strategy").status, "missing")

    def test_python_library_requires_packaging_and_importable_package(self):
        profile = profile_repository(ROOT / "python-library")
        plan = recommend_team(profile)

        self.assertEqual(profile.project_types, ["library"])
        self.assertEqual(profile.components[0].project_types, ["library"])
        self.assertIn("dependency_audit", {item.capability_id for item in plan.capabilities})
        self.assertNotIn("pipeline_review", {item.capability_id for item in plan.capabilities})
        self.assertTrue(profile.tests.present)

    def test_hybrid_worker_and_nested_proxy_are_separate_components(self):
        profile = profile_repository(ROOT / "hybrid-worker-proxy")
        plan = recommend_team(profile)
        components = {component.name: component for component in profile.components}

        self.assertIn("hybrid_service", profile.project_types)
        self.assertEqual(set(components), {"root", "server/proxy"})
        self.assertEqual(components["root"].manifest, "package.json")
        self.assertEqual(components["root"].runtimes, ["Cloudflare Workers"])
        self.assertEqual(components["server/proxy"].manifest, "server/proxy/package.json")
        self.assertEqual(components["server/proxy"].frameworks, ["Express"])
        self.assertEqual(components["server/proxy"].runtimes, ["Node.js"])
        self.assertTrue(all(path.startswith("server/proxy/") for path in components["server/proxy"].evidence[0].paths))
        self.assertEqual(set(profile.deployment.targets), {"Cloudflare Workers", "Node proxy service"})
        self.assertIn("deployment_scope", {question.id for question in plan.questions})
        self.assertIn("proxy_service_review", {item.capability_id for item in plan.capabilities})
        self.assertIn("deployment_review", {item.capability_id for item in plan.capabilities})
        self.assertNotIn("ml_reproducibility", {item.capability_id for item in plan.capabilities})

    def test_wrangle_and_actions_with_one_target_has_no_deployment_scope_question(self):
        profile = profile_repository(ROOT / "worker-with-actions")
        plan = recommend_team(profile)

        self.assertEqual(profile.deployment.targets, ["Cloudflare Workers"])
        self.assertIn("wrangler", profile.deployment.tools)
        self.assertIn("github-actions", profile.deployment.tools)
        self.assertNotIn("deployment_scope", {question.id for question in plan.questions})

    def test_operational_test_named_script_is_not_a_test_suite(self):
        profile = profile_repository(ROOT / "operational-test-script")

        self.assertFalse(profile.tests.present)
        self.assertEqual(profile.tests.evidence, [])

    def test_proposal_output_cannot_be_inside_analyzed_repository(self):
        profile = profile_repository(ROOT / "frontend-next")
        plan = recommend_team(profile)
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            profile.path = str(repo)
            with self.assertRaisesRegex(ProposalError, "repository root"):
                write_proposal(profile, plan, repo)
            with self.assertRaisesRegex(ProposalError, "inside the analyzed repository"):
                write_proposal(profile, plan, repo / "proposal")
            with self.assertRaisesRegex(ProposalError, r"\.codex"):
                write_proposal(profile, plan, repo / ".codex")

    def test_existing_proposal_is_never_overwritten(self):
        profile = profile_repository(ROOT / "frontend-next")
        plan = recommend_team(profile)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proposal"
            output.mkdir()
            marker = output / "marker.txt"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ProposalError, "already exists"):
                write_proposal(profile, plan, output)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_failed_atomic_write_cleans_temporary_directory(self):
        profile = profile_repository(ROOT / "frontend-next")
        plan = recommend_team(profile)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proposal"
            with patch("repo_adaptive_agents.generator._validate_rendered", side_effect=ProposalError("simulated validation failure")):
                with self.assertRaisesRegex(ProposalError, "simulated validation failure"):
                    write_proposal(profile, plan, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(temporary).glob(".proposal.tmp-*")), [])

    def test_external_file_symlink_is_ignored_with_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            outside = Path(temporary) / "outside.txt"
            root.mkdir()
            outside.write_text("SYMLINK_SECRET_MARKER", encoding="utf-8")
            os.symlink(outside, root / "linked.txt")
            profile = profile_repository(root)
            payload = json.dumps(to_jsonable(profile))
            self.assertNotIn("SYMLINK_SECRET_MARKER", payload)
            self.assertTrue(any(item.signal == "unsafe_symlink" for item in profile.evidence))
            self.assertTrue(any("linked.txt" in warning for warning in profile.warnings))

    def test_sensitive_files_are_not_read_but_env_example_names_are_safe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "credentials.json").write_text('{"token":"SECRET_MARKER"}', encoding="utf-8")
            (root / ".env").write_text("DIFY_API_KEY=SECRET_MARKER", encoding="utf-8")
            (root / ".env.example").write_text("DIFY_API_KEY=EXAMPLE_VALUE_MARKER", encoding="utf-8")
            profile = profile_repository(root)
            payload = json.dumps(to_jsonable(profile))
            self.assertNotIn("SECRET_MARKER", payload)
            self.assertNotIn("EXAMPLE_VALUE_MARKER", payload)
            secret = next(item for item in profile.evidence if item.signal == "secret_filename")
            self.assertIn("credentials.json", secret.paths)
            self.assertTrue(next(item for item in profile.integrations if item.name == "dify").detected)

    def test_invalid_json_and_toml_manifests_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"dependencies": ', encoding="utf-8")
            (root / "pyproject.toml").write_text("[project\nname = 'broken'", encoding="utf-8")
            profile = profile_repository(root)
            invalid = [item for item in profile.evidence if item.signal == "invalid_manifest"]
            self.assertEqual({path for item in invalid for path in item.paths}, {"package.json", "pyproject.toml"})
            self.assertTrue(any("Manifest parsing failed" in warning for warning in profile.warnings))
            self.assertNotIn("React", profile.frameworks)
            self.assertNotIn("FastAPI", profile.frameworks)

    def test_operational_pipeline_file_alone_is_not_ml(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bin").mkdir()
            (root / "bin" / "run_pipeline.sh").write_text("#!/bin/sh\npython pipeline.py\n", encoding="utf-8")
            (root / "pipeline.py").write_text("print('operational pipeline')\n", encoding="utf-8")
            profile = profile_repository(root)
            self.assertIn("pipeline", profile.project_types)
            self.assertNotIn("data_ml", profile.project_types)

    def test_multiple_manifests_are_preserved_in_one_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text('{"dependencies":{"express":"1"}}', encoding="utf-8")
            (root / "pyproject.toml").write_text("[project]\nname = 'mixed'\n", encoding="utf-8")
            profile = profile_repository(root)
            component = next(item for item in profile.components if item.name == "root")
            self.assertEqual(component.manifests, ["package.json", "pyproject.toml"])
            self.assertEqual(component.manifest, "package.json")

    def test_dotted_nested_component_path_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "service.v2"
            nested.mkdir()
            (nested / "package.json").write_text('{"dependencies":{"express":"1"}}', encoding="utf-8")
            profile = profile_repository(root)
            component = next(item for item in profile.components if item.name == "service.v2")
            self.assertEqual(component.path, "service.v2")
            self.assertEqual(component.manifests, ["service.v2/package.json"])
            self.assertEqual(component.frameworks, ["Express"])

    def test_cli_expected_path_errors_are_short_and_on_stderr(self):
        for path in (Path("/definitely/missing"), Path(__file__)):
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(["profile", str(path)])
            self.assertEqual(exit_code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertTrue(stderr.getvalue().startswith("error: "))
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_proposal_diff_includes_json_and_toml_additions(self):
        profile = profile_repository(ROOT / "frontend-next")
        plan = recommend_team(profile)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "proposal"
            write_proposal(profile, plan, output)
            existing = Path(temporary) / "existing-codex"
            existing.mkdir()
            (existing / "config.toml").write_text("model = 'old'\n", encoding="utf-8")
            diff = proposal_diff(output, existing)
            self.assertIn("profile.json", diff)
            self.assertIn("team-plan.json", diff)
            self.assertIn("config.toml", diff)
            self.assertIn("change/conflict: config.toml", diff)

    def test_custom_virtualenv_and_installed_package_content_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root, "app.py", "def run():\n    return 1\n")
            self._write(root, "tests/test_app.py", "def test_app():\n    assert True\n")
            self._write(root, ".venv-certbot/pyvenv.cfg", "home = /usr/bin\n")
            self._write(
                root,
                ".venv-certbot/lib/python3.12/site-packages/fake/tests/test_worker.py",
                "import torch\nfrom fastmcp import FastMCP\nassert True\n",
            )
            self._write(root, ".venv-certbot/lib/python3.12/site-packages/fake/secrets.pem", "PRIVATE")
            profile = profile_repository(root)
            payload = json.dumps(to_jsonable(profile))
            self.assertNotIn(".venv-certbot", payload)
            self.assertTrue(profile.tests.present)
            self.assertEqual(profile.project_types, ["unknown"])

    def test_evidence_paths_are_deterministically_limited_with_counts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(6):
                self._write(root, f"tests/test_{index}.py", "def test_value():\n    assert True\n")
            profile = profile_repository(root, evidence_path_limit=2)
            evidence = next(item for item in profile.tests.evidence if item.signal == "test_files")
            self.assertEqual(evidence.paths, ("tests/test_0.py", "tests/test_1.py"))
            self.assertEqual(evidence.total_count, 6)
            self.assertEqual(evidence.omitted_count, 4)

    def test_opencv_dnn_application_is_inference_not_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(
                root,
                "pyproject.toml",
                "[build-system]\nrequires=['setuptools']\n"
                "[project]\nname='vision-app'\ndescription='YOLO vision application'\n"
                "dependencies=['opencv-python','pyopencl']\n"
                "[project.scripts]\nvision-app='vision_app.cli:main'\n",
            )
            self._write(
                root,
                "src/vision_app/app.py",
                "import cv2\n"
                "net=cv2.dnn.readNet('model.cfg','model.weights')\n"
                "blob=cv2.dnn.blobFromImage(frame)\nnet.setInput(blob)\n"
                "outputs=net.forward()\nboxes=cv2.dnn.NMSBoxes([],[],0.5,0.4)\n"
                "cv2.imshow('vision', frame)\n",
            )
            self._write(root, "src/vision_app/model.cfg", "[net]\n")
            profile = profile_repository(root)
            plan = recommend_team(profile)
            self.assertEqual(profile.primary_project_types, ["application", "computer_vision", "ml_inference"])
            self.assertNotIn("library", profile.project_types)
            self.assertTrue(any(item.signal == "external_model_artifact_missing" for item in profile.evidence))
            capability_ids = {item.capability_id for item in plan.capabilities}
            self.assertTrue({"computer_vision_review", "image_processing_review", "ml_inference_review", "model_evaluation"}.issubset(capability_ids))
            self.assertNotIn("api_contract_review", capability_ids)

    def test_packaged_console_application_is_not_a_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(
                root,
                "pyproject.toml",
                "[build-system]\nrequires=['setuptools']\n"
                "[project]\nname='runner'\n"
                "[project.scripts]\nrunner='runner.cli:main'\n",
            )
            self._write(root, "src/runner/__init__.py", "")
            profile = profile_repository(root)
            self.assertIn("application", profile.primary_project_types)
            self.assertNotIn("library", profile.primary_project_types)
            self.assertIn("packaged_python", profile.secondary_project_types)

    def test_shell_acme_client_detects_lifecycle_bats_and_shellcheck(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(
                root,
                "certctl",
                "#!/usr/bin/env bash\n"
                "CA=https://acme-staging-v02.api.letsencrypt.org/directory\n"
                "openssl req -new -key account.key -out request.csr\n"
                "curl \"$CA\"\nrevoke_certificate(){ :; }\nreload_service(){ ssh host reload; }\n",
                executable=True,
            )
            self._write(root, "dns_scripts/dns_add_cloudflare", "#!/bin/bash\ncurl api.cloudflare.com\n", executable=True)
            self._write(root, "dns_scripts/dns_del_cloudflare", "#!/bin/bash\n:\n", executable=True)
            self._write(root, "test/certificate.bats", "@test 'renew' { run ./certctl; }\n")
            self._write(root, ".github/workflows/test.yml", "jobs:\n  lint:\n    steps:\n      - run: shellcheck certctl\n")
            profile = profile_repository(root)
            plan = recommend_team(profile)
            self.assertEqual(profile.primary_project_types, ["cli_tool", "certificate_automation", "security_tooling"])
            self.assertTrue({"Bats", "ShellCheck"}.issubset(set(profile.tests.frameworks)))
            self.assertNotIn("cloudflare_worker", profile.project_types)
            capability_ids = {item.capability_id for item in plan.capabilities}
            self.assertTrue({"shell_review", "acme_protocol_review", "certificate_lifecycle_review", "integration_review"}.issubset(capability_ids))

    def test_fastmcp_stdio_server_has_secondary_container_and_tool_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(
                root,
                "pyproject.toml",
                "[project]\nname='photo-mcp'\ndescription='RawTherapee photographic MCP tool'\n"
                "dependencies=['fastmcp','Pillow','exifread']\n"
                "[project.scripts]\nphoto-mcp='photo_mcp.server:main'\n",
            )
            self._write(
                root,
                "src/photo_mcp/server.py",
                "from typing import Any\nfrom fastmcp import FastMCP\n"
                "mcp=FastMCP('photo')\n"
                "@mcp.tool()\ndef edit_photo(parameters: dict[str, Any]) -> dict[str, Any]:\n"
                "    return {'pp3': parameters, 'histogram': 'RawTherapee EXIF LUT'}\n"
                "def main():\n    mcp.run(transport='stdio')\n",
            )
            self._write(root, "Dockerfile", "FROM python:3.12\n")
            self._write(root, "tests/test_server.py", "def test_server():\n    assert True\n")
            profile = profile_repository(root)
            plan = recommend_team(profile)
            self.assertEqual(profile.primary_project_types, ["mcp_server", "image_processing", "photographic_tool"])
            self.assertNotIn("infrastructure", profile.project_types)
            self.assertIn("containerized", profile.secondary_project_types)
            capability_ids = {item.capability_id for item in plan.capabilities}
            self.assertTrue({"mcp_protocol_review", "tool_contract_review", "photographic_domain_review", "image_processing_review", "container_review"}.issubset(capability_ids))

    def test_dns_iac_ignores_integration_words_in_zone_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(
                root,
                "config/dns.yaml",
                "providers:\n  cf:\n    class: octodns_cloudflare.CloudflareProvider\n"
                "  bind:\n    class: octodns_bind.Rfc2136Provider\n"
                "zones:\n  '*':\n    targets: [cf, bind]\n",
            )
            self._write(root, "config/zones/example.yaml", "jira: confluence-data-only\n")
            self._write(root, "scripts/dify_sync.py", "import os\nurl=os.environ.get('DIFY_BASE_URL')\n")
            self._write(root, ".github/workflows/apply.yml", "on: workflow_dispatch\njobs:\n  apply:\n    steps:\n      - run: python scripts/dify_sync.py\n")
            profile = profile_repository(root)
            integrations = {item.name: item.detected for item in profile.integrations}
            self.assertEqual(profile.primary_project_types, ["pipeline", "dns_iac"])
            self.assertEqual(set(profile.deployment.targets), {"Cloudflare DNS", "RFC2136/BIND DNS"})
            self.assertFalse(integrations["jira"])
            self.assertFalse(integrations["confluence"])
            self.assertTrue(integrations["dify"])

    def test_fixture_manifests_and_runtime_do_not_contaminate_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(
                root,
                "pyproject.toml",
                "[project]\nname='profiler-cli'\n[project.scripts]\nprofiler='profiler.cli:main'\n",
            )
            self._write(root, "src/profiler/cli.py", "def main():\n    return 0\n")
            self._write(root, "tests/fixtures/worker/package.json", '{"dependencies":{"next":"1","express":"1"}}')
            self._write(root, "tests/fixtures/worker/wrangler.toml", "main='src/index.ts'\n")
            self._write(root, "tests/fixtures/ml/train.py", "import torch\n")
            profile = profile_repository(root)
            self.assertEqual(profile.primary_project_types, ["application", "cli_tool"])
            self.assertFalse({"frontend", "api", "cloudflare_worker", "data_ml"}.intersection(profile.project_types))
            self.assertEqual([component.name for component in profile.components], ["root"])


if __name__ == "__main__":
    unittest.main()
