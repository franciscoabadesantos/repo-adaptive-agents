"""Provenance guard for the initial native admission-control extraction."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import repo_adaptive_agents.admission_control as native


VALIDATED_COMMIT = "b610f1b1232eeb2840e5cca2ddaf450ba64fa491"
VALIDATED_TREE = "a0e784208ab3df5e8889cc96c2319448ffab4687"
EXPECTED_SHA256 = {
    "__init__.py": "bafb5fbc8e6f6300e5a7a43adcef5f47247f5923eac69344746e385fdc0bb712",
    "admission.py": "a6f608d4a515284a89666160fede0e50d61231e0c769bbe3ee8599538fb554f5",
    "catalog.py": "a5373d5aa0e55c16397e351447fc1c6cd8e51c28372bf67c0f4e6a14dc04a945",
    "models.py": "ce0359ebe5841def106afd20c17d78cab29e8a5b7e1b815acc388007f6f8da1d",
    "writer.py": "2ce1c7cc9a6e20712f9d23bc05991fc57c15a8a1f95dcfecaa1f39f9743c8f29",
}


def test_initial_extraction_matches_validated_native_sources():
    package = Path(inspect.getsourcefile(native.admit)).resolve().parent
    observed = {
        name: hashlib.sha256((package / name).read_bytes()).hexdigest()
        for name in EXPECTED_SHA256
    }
    assert observed == EXPECTED_SHA256, (
        "Native sources no longer match the initial validated extraction. "
        "Update this provenance contract only with an explicit product change."
    )


def test_native_decision_callable_origins():
    assert {
        "admit": f"{native.admit.__module__}.{native.admit.__name__}",
        "validate": f"{native.validate.__module__}.{native.validate.__name__}",
        "record_exposure": (
            f"{native.AdmissionSnapshot.record_exposure.__module__}."
            f"{native.AdmissionSnapshot.record_exposure.__qualname__}"
        ),
    } == {
        "admit": "repo_adaptive_agents.admission_control.admission.admit",
        "validate": "repo_adaptive_agents.admission_control.admission.validate",
        "record_exposure": "repo_adaptive_agents.admission_control.models.AdmissionSnapshot.record_exposure",
    }
