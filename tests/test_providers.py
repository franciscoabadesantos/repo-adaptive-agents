import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from repo_adaptive_agents.cli import main
from repo_adaptive_agents.providers import ProviderCatalogError, load_provider_catalog


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
            self.assertEqual(
                sorted(path.relative_to(root).as_posix() for path in root.rglob("*")),
                before,
            )

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
