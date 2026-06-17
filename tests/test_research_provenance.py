"""Tests for shared.research_provenance (Phase 3).

Fingerprints must be deterministic and change when an input changes; the sidecar
must capture warnings + disclosure.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.research_provenance import DISCLOSURE, data_fingerprint, write_provenance  # noqa: E402


def test_fingerprint_is_deterministic(tmp_path):
    a = tmp_path / "a.json"
    a.write_text('{"x": 1}')
    fp1 = data_fingerprint([str(a)])
    fp2 = data_fingerprint([str(a)])
    assert fp1["combined_sha256"] == fp2["combined_sha256"]
    assert fp1["inputs"][0]["exists"] is True
    assert fp1["inputs"][0]["sha256"]


def test_fingerprint_changes_when_input_changes(tmp_path):
    a = tmp_path / "a.json"
    a.write_text('{"x": 1}')
    before = data_fingerprint([str(a)])["combined_sha256"]
    a.write_text('{"x": 2}')
    after = data_fingerprint([str(a)])["combined_sha256"]
    assert before != after


def test_missing_input_is_recorded_not_crashing(tmp_path):
    fp = data_fingerprint([str(tmp_path / "nope.json")])
    assert fp["inputs"][0]["exists"] is False
    assert fp["inputs"][0]["sha256"] is None


def test_write_provenance_sidecar(tmp_path):
    src = tmp_path / "in.json"
    src.write_text('{"k": 1}')
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}")
    prov = write_provenance(str(artifact), [str(src)],
                            warnings=["below floor"], source="unit-test")
    sidecar = tmp_path / "artifact.json.provenance.json"
    assert sidecar.exists()
    on_disk = json.loads(sidecar.read_text())
    assert on_disk["warnings"] == ["below floor"]
    assert on_disk["source"] == "unit-test"
    assert on_disk["disclosure"] == DISCLOSURE
    assert on_disk["fingerprint"]["combined_sha256"] == prov["fingerprint"]["combined_sha256"]
