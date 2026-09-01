"""Provenance guard for the initial native admission-control extraction."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import repo_adaptive_agents.admission_control as native


VALIDATED_COMMIT = "b610f1b1232eeb2840e5cca2ddaf450ba64fa491"
VALIDATED_TREE = "a0e784208ab3df5e8889cc96c2319448ffab4687"
INITIAL_VALIDATED_SHA256 = {
    "__init__.py": "bafb5fbc8e6f6300e5a7a43adcef5f47247f5923eac69344746e385fdc0bb712",
    "admission.py": "a6f608d4a515284a89666160fede0e50d61231e0c769bbe3ee8599538fb554f5",
    "catalog.py": "a5373d5aa0e55c16397e351447fc1c6cd8e51c28372bf67c0f4e6a14dc04a945",
    "models.py": "ce0359ebe5841def106afd20c17d78cab29e8a5b7e1b815acc388007f6f8da1d",
    "writer.py": "2ce1c7cc9a6e20712f9d23bc05991fc57c15a8a1f95dcfecaa1f39f9743c8f29",
}
PRODUCT_BOUNDARY_SHA256 = {
    "__init__.py": "f4eae60f4911915aca71056773ee75afde45d15d7c35e1c4d0b4a19ed4808482",
    "admission.py": "a6f608d4a515284a89666160fede0e50d61231e0c769bbe3ee8599538fb554f5",
    "catalog.py": "021c20524eb23527f4a7e049052ab57b938f3deb1e5c9107604ab12f050f1ad5",
    "models.py": "b050c3a468766aaac378a90ab86a0548ead28c0c30f1d53eb8dd3b040b63ee30",
    "writer.py": "2ce1c7cc9a6e20712f9d23bc05991fc57c15a8a1f95dcfecaa1f39f9743c8f29",
}


def test_product_boundary_matches_reviewed_native_sources():
    package = Path(inspect.getsourcefile(native.admit)).resolve().parent
    observed = {
        name: hashlib.sha256((package / name).read_bytes()).hexdigest()
        for name in PRODUCT_BOUNDARY_SHA256
    }
    assert observed == PRODUCT_BOUNDARY_SHA256, (
        "Native sources no longer match the reviewed product boundary. "
        "Update this provenance contract only with an explicit product change."
    )


def test_admission_and_audit_algorithms_remain_at_validated_hashes():
    assert PRODUCT_BOUNDARY_SHA256["admission.py"] == INITIAL_VALIDATED_SHA256["admission.py"]
    assert PRODUCT_BOUNDARY_SHA256["writer.py"] == INITIAL_VALIDATED_SHA256["writer.py"]


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
