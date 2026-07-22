import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from repo_adaptive_agents.cli import main
from repo_adaptive_agents.providers import (
    ProviderCatalogError,
    ProviderResolutionError,
    load_provider_catalog,
    parse_provider_resolution,
)


FIXTURES = Path(__file__).parent / "fixtures"


def _catalog(provider_items: list[dict]) -> dict:
    return {"schema_version": 1, "providers": provider_items}


def _ml_provider(**overrides) -> dict:
    provider = {
        "id": "example_ml_review",
        "title": "Example ML review knowledge",
        "capabilities": ["ml_reproducibility"],
        "kind": "skill",
        "source": "https://example.invalid/providers/ml-review",
        "revision": "0123456789abcdef0123456789abcdef01234567",
        "compatible_targets": ["codex"],
        "license": "MIT",
        "review_status": "candidate",
    }
    provider.update(overrides)
    return provider


def _research_candidate(**overrides) -> dict:
    candidate = {
        "provider_id": "example_ml_review",
        "title": "Example ML review knowledge",
        "primary_source": "https://example.invalid/providers/ml-review",
        "revision": "0123456789abcdef0123456789abcdef01234567",
        "kind": "skill",
        "compatible_targets": ["codex"],
        "license": "MIT",
        "trust_signals": ["Versioned primary source"],
        "exact_coverage": ["ML experiment review"],
        "coverage_gaps": [],
        "permissions": ["Read repository files"],
        "external_requirements": [],
        "platform_coupling": "Codex adapter required",
        "recommendation": "suitable",
    }
    candidate.update(overrides)
    return candidate


def _resolution_item(capability_id: str, **overrides) -> dict:
    item = {
        "capability_id": capability_id,
        "research_status": "unavailable",
        "candidates": [],
        "evidence": ["Runtime reported that public network access is unavailable."],
        "limitation": "Public network access was unavailable.",
        "proposed_outcome": "leave_unresolved",
        "provider_id": None,
        "rationale": "Keep the capability gap explicit.",
    }
    item.update(overrides)
    return item


def _resolution(*items: dict) -> dict:
    return {
        "schema_version": 1,
        "kind": "provider_resolution",
        "capabilities": list(items),
    }


class ProviderCatalogTests(unittest.TestCase):
    def test_catalog_is_strict_and_deterministically_sorted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "providers.json"
            path.write_text(
                json.dumps(
                    _catalog([
                        _ml_provider(id="z_provider"),
                        _ml_provider(id="a_provider"),
                    ])
                ),
                encoding="utf-8",
            )

            providers = load_provider_catalog(path)

            self.assertEqual([item.id for item in providers], ["a_provider", "z_provider"])

    def test_unknown_capability_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "providers.json"
            path.write_text(
                json.dumps(_catalog([_ml_provider(capabilities=["invented_review"])])),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ProviderCatalogError, "unknown capabilities"):
                load_provider_catalog(path)

    def test_boolean_schema_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "providers.json"
            path.write_text(
                json.dumps({"schema_version": True, "providers": []}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ProviderCatalogError, "schema_version must be 1"):
                load_provider_catalog(path)


class ProviderResolutionTests(unittest.TestCase):
    def test_every_gap_requires_research_and_a_proposed_outcome(self):
        with self.assertRaisesRegex(
            ProviderResolutionError,
            "missing provider research for capability gaps: dependency_audit",
        ):
            parse_provider_resolution(
                _resolution(_resolution_item("ml_reproducibility")),
                ["ml_reproducibility", "dependency_audit"],
            )

    def test_valid_resolution_is_canonicalized_to_capability_order(self):
        normalized, proposals = parse_provider_resolution(
            _resolution(
                _resolution_item(
                    "dependency_audit",
                    proposed_outcome="create_local_knowledge",
                ),
                _resolution_item(
                    "ml_reproducibility",
                    proposed_outcome="decompose_capability",
                ),
            ),
            ["ml_reproducibility", "dependency_audit"],
        )

        self.assertEqual(
            [item["capability_id"] for item in normalized["capabilities"]],
            ["ml_reproducibility", "dependency_audit"],
        )
        self.assertEqual(
            [(item.capability_id, item.outcome) for item in proposals],
            [
                ("ml_reproducibility", "decompose_capability"),
                ("dependency_audit", "create_local_knowledge"),
            ],
        )

    def test_provider_selection_requires_matching_catalog_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary) / "providers.json"
            catalog.write_text(
                json.dumps(_catalog([_ml_provider()])),
                encoding="utf-8",
            )
            providers = load_provider_catalog(catalog)

            _normalized, proposals = parse_provider_resolution(
                _resolution(_resolution_item(
                    "ml_reproducibility",
                    research_status="completed",
                    candidates=[_research_candidate()],
                    evidence=["https://example.invalid/providers/ml-review"],
                    limitation=None,
                    proposed_outcome="select_provider",
                    provider_id="example_ml_review",
                    rationale="Candidate covers the requested capability.",
                )),
                ["ml_reproducibility"],
                providers,
            )
            self.assertEqual(proposals[0].provider_id, "example_ml_review")

            with self.assertRaisesRegex(
                ProviderResolutionError,
                "does not claim capability",
            ):
                parse_provider_resolution(
                    _resolution(_resolution_item(
                        "model_evaluation",
                        research_status="completed",
                        candidates=[_research_candidate()],
                        evidence=["https://example.invalid/providers/ml-review"],
                        limitation=None,
                        proposed_outcome="select_provider",
                        provider_id="example_ml_review",
                    )),
                    ["model_evaluation"],
                    providers,
                )

    def test_completed_research_requires_evidence(self):
        with self.assertRaisesRegex(ProviderResolutionError, "evidence must be a non-empty array"):
            parse_provider_resolution(
                _resolution(_resolution_item(
                    "ml_reproducibility",
                    research_status="completed",
                    evidence=[],
                    limitation=None,
                )),
                ["ml_reproducibility"],
            )

    def test_unavailable_research_requires_blocker_evidence(self):
        with self.assertRaisesRegex(ProviderResolutionError, "evidence must be a non-empty array"):
            parse_provider_resolution(
                _resolution(_resolution_item(
                    "ml_reproducibility",
                    evidence=[],
                )),
                ["ml_reproducibility"],
            )

    def test_suitable_candidate_can_still_be_left_unresolved(self):
        _normalized, proposals = parse_provider_resolution(
            _resolution(_resolution_item(
                "ml_reproducibility",
                research_status="completed",
                candidates=[_research_candidate()],
                evidence=["https://example.invalid/providers/ml-review"],
                limitation=None,
                rationale="The candidate is suitable, but adoption remains optional.",
            )),
            ["ml_reproducibility"],
        )

        self.assertEqual(proposals[0].outcome, "leave_unresolved")

    def test_selected_provider_metadata_must_match_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary) / "providers.json"
            catalog.write_text(
                json.dumps(_catalog([_ml_provider()])),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ProviderResolutionError,
                "metadata does not match",
            ):
                parse_provider_resolution(
                    _resolution(_resolution_item(
                        "ml_reproducibility",
                        research_status="completed",
                        candidates=[_research_candidate(revision="different-revision")],
                        evidence=["https://example.invalid/providers/ml-review"],
                        limitation=None,
                        proposed_outcome="select_provider",
                        provider_id="example_ml_review",
                    )),
                    ["ml_reproducibility"],
                    load_provider_catalog(catalog),
                )


class ProviderOptionsCliTests(unittest.TestCase):
    @staticmethod
    def _run(argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_empty_builtin_catalog_preserves_ml_gap(self):
        code, stdout, stderr = self._run([
            "provider-options",
            str(FIXTURES / "python-ml"),
        ])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["catalog"], {
            "network_access": False,
            "provider_count": 0,
            "source": "builtin-empty",
        })
        self.assertEqual(payload["provider_candidates"], [])
        research = payload["provider_discovery"]
        self.assertEqual(research["status"], "research_recommended")
        self.assertEqual(research["network_access"], "not_performed_by_cli")
        self.assertIn("Main agent", research["actor"])
        self.assertIn(
            "ml_reproducibility",
            {item["capability_id"] for item in research["capabilities"]},
        )
        self.assertIn(
            "exact_coverage",
            research["result_contract"]["required_candidate_fields"],
        )
        self.assertEqual(research["result_contract"]["kind"], "provider_resolution")
        self.assertIn(
            "proposed_outcome",
            research["result_contract"]["required_capability_fields"],
        )
        self.assertEqual(research["result_contract"]["max_candidates_per_capability"], 3)
        self.assertTrue(research["result_contract"]["no_match_allowed"])
        self.assertTrue(
            any("never map a narrower provider" in rule for rule in research["research_rules"])
        )
        unresolved = {
            item["capability_id"] for item in payload["unresolved_capabilities"]
        }
        self.assertIn("ml_reproducibility", unresolved)

    def test_local_catalog_matches_metadata_without_accessing_provider_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / "providers.json"
            catalog.write_text(
                json.dumps(_catalog([_ml_provider()])),
                encoding="utf-8",
            )
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))

            code, stdout, stderr = self._run([
                "provider-options",
                str(FIXTURES / "python-ml"),
                "--catalog",
                str(catalog),
            ])

            self.assertEqual(code, 0, stderr)
            payload = json.loads(stdout)
            self.assertEqual(payload["catalog"]["provider_count"], 1)
            self.assertFalse(payload["catalog"]["network_access"])
            self.assertEqual(len(payload["provider_candidates"]), 1)
            candidate = payload["provider_candidates"][0]
            self.assertEqual(candidate["provider"]["id"], "example_ml_review")
            self.assertEqual(candidate["matched_capabilities"], ["ml_reproducibility"])
            self.assertEqual(candidate["provider"]["review_status"], "candidate")
            self.assertIn(
                "ml_reproducibility",
                {
                    item["capability_id"]
                    for item in payload["provider_discovery"]["capabilities"]
                },
            )
            self.assertEqual(
                sorted(path.relative_to(root).as_posix() for path in root.rglob("*")),
                before,
            )

    def test_approved_provider_does_not_require_repeat_research(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary) / "providers.json"
            catalog.write_text(
                json.dumps(
                    _catalog([_ml_provider(review_status="approved")])
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self._run([
                "provider-options",
                str(FIXTURES / "python-ml"),
                "--catalog",
                str(catalog),
            ])

            self.assertEqual(code, 0, stderr)
            payload = json.loads(stdout)
            research_ids = {
                item["capability_id"]
                for item in payload["provider_discovery"]["capabilities"]
            }
            self.assertNotIn("ml_reproducibility", research_ids)

    def test_narrow_provider_does_not_claim_broad_ml_gap(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary) / "providers.json"
            catalog.write_text(
                json.dumps(
                    _catalog([
                        _ml_provider(
                            id="model_evaluation_only",
                            capabilities=["model_evaluation"],
                        )
                    ])
                ),
                encoding="utf-8",
            )

            code, stdout, stderr = self._run([
                "provider-options",
                str(FIXTURES / "python-ml"),
                "--catalog",
                str(catalog),
            ])

            self.assertEqual(code, 0, stderr)
            payload = json.loads(stdout)
            self.assertEqual(payload["provider_candidates"], [])
            unresolved = {
                item["capability_id"] for item in payload["unresolved_capabilities"]
            }
            self.assertIn("ml_reproducibility", unresolved)
            research_ids = {
                item["capability_id"]
                for item in payload["provider_discovery"]["capabilities"]
            }
            self.assertIn("ml_reproducibility", research_ids)

    def test_invalid_catalog_returns_short_cli_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary) / "providers.json"
            catalog.write_text("{}", encoding="utf-8")

            code, stdout, stderr = self._run([
                "provider-options",
                str(FIXTURES / "python-ml"),
                "--catalog",
                str(catalog),
            ])

            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertTrue(stderr.startswith("error: provider catalog"))
            self.assertNotIn("Traceback", stderr)


if __name__ == "__main__":
    unittest.main()
