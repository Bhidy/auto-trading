"""Research-artifact provenance (pure-stdlib).

Every offline research artifact the cloud path later READS (e.g.
``data/fee_source.json``, ``data/hrp_weights.json``) should carry a
machine-checkable lineage: the sha256 of its inputs, any warnings, and a
disclosure. This closes the "where did this number come from" gap and lets a
reviewer refuse to trust an artifact whose inputs changed underneath it.

Adopted from the Alpaca skill's data_fingerprint / warnings / disclosure
reproducibility contract (see docs/ALPACA_TOOLING.md). Pure-stdlib so it is safe
to import anywhere — it is, however, only USED in the offline research lane.
"""
import hashlib
import json
import os
from datetime import datetime, timezone

DISCLOSURE = (
    "Research artifact for internal model-risk use only — not investment advice. "
    "Derived from the recorded inputs below and reproducible from their fingerprints."
)


def _root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rel(path):
    try:
        return os.path.relpath(path, _root())
    except ValueError:
        return path


def _file_fingerprint(path):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return {"path": _rel(path), "exists": False, "sha256": None, "bytes": 0}
    return {
        "path": _rel(path),
        "exists": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def data_fingerprint(inputs, extra=None):
    """Fingerprint a set of input files: per-file sha256 + a combined hash."""
    files = [_file_fingerprint(p) for p in (inputs or [])]
    combined = hashlib.sha256(
        "".join(f["sha256"] or "" for f in files).encode()
    ).hexdigest()
    fp = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "inputs": files,
        "combined_sha256": combined,
    }
    if extra:
        fp["meta"] = extra
    return fp


def write_provenance(artifact_path, inputs, *, warnings=None, source=None, extra=None):
    """Write ``<artifact_path>.provenance.json`` next to an artifact; return the dict."""
    prov = {
        "artifact": _rel(artifact_path),
        "source": source,
        "fingerprint": data_fingerprint(inputs, extra=extra),
        "warnings": list(warnings or []),
        "disclosure": DISCLOSURE,
    }
    out = artifact_path + ".provenance.json"
    with open(out, "w") as f:
        json.dump(prov, f, indent=2)
        f.write("\n")
    return prov
