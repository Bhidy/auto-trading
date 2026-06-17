"""Vendored-tooling pin verification (invariant C, enforced in CI).

Vendored agent-skills / CLIs must be tamper-evident and version-pinned so a
breaking upstream change cannot silently alter behavior we depend on. This
matters most for PREVIEW upstreams (the Alpaca skill/CLI), which ship breaking
changes.

Source of truth: ``config/vendored_tools.lock.json`` (committed). The global
skill installer's ``skills-lock.json`` is gitignored (.gitignore:26) and is NOT
checked in CI — so this committed registry is what the build verifies.

For every tool entry that declares a ``localPath`` (vendored into this repo),
this guard recomputes its sha256 and asserts it matches ``computedHash`` — so
editing the vendored file without bumping the lock fails the build. Entries with
a ``pinnedCommit`` must carry a 40-hex commit and a 64-hex hash. The Alpaca skill
must additionally be scoped interactive-research-only.
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "config" / "vendored_tools.lock.json"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _load():
    return json.loads(LOCK.read_text())


def test_lock_is_wellformed():
    data = _load()
    assert data.get("version") == 1, "vendored_tools.lock.json version must be 1"
    assert isinstance(data.get("tools"), dict) and data["tools"], "tools map must be non-empty"


def test_vendored_files_match_recorded_hash():
    data = _load()
    checked = 0
    for name, entry in data["tools"].items():
        local = entry.get("localPath")
        if not local:
            continue
        f = ROOT / local
        assert f.exists(), f"{name}: vendored localPath {local} is missing"
        actual = hashlib.sha256(f.read_bytes()).hexdigest()
        assert actual == entry.get("computedHash"), (
            f"{name}: vendored {local} sha256 {actual} != recorded {entry.get('computedHash')}. "
            "Re-vendor at the pinned commit, or bump computedHash if the change is intentional."
        )
        checked += 1
    assert checked >= 1, "expected at least one vendored (localPath) tool to hash-verify"


def test_pinned_entries_have_valid_commit_and_hash():
    data = _load()
    for name, entry in data["tools"].items():
        if "pinnedCommit" in entry:
            assert _HEX40.match(entry["pinnedCommit"]), f"{name}: pinnedCommit must be a 40-hex git commit"
            assert _HEX64.match(entry.get("computedHash", "")), f"{name}: computedHash must be 64-hex sha256"


def test_alpaca_tools_pinned_and_research_scoped():
    data = _load()
    tools = data["tools"]

    skill = tools.get("alpaca-trading-backtest")
    assert skill, "alpaca-trading-backtest must be vendored + pinned"
    assert skill.get("source") == "alpacahq/alpaca-skills"
    assert _HEX40.match(skill.get("pinnedCommit", "")), "Alpaca skill must be commit-pinned (PREVIEW upstream)"
    assert skill.get("scope") == "interactive-research-only", (
        "Alpaca skill must be scoped interactive-research-only — never on the cloud trading path"
    )

    # Every Alpaca tool must be research-scoped (no live/cloud-path tool ever allowed here).
    for name, entry in tools.items():
        if name.startswith("alpaca"):
            assert entry.get("scope") == "interactive-research-only", (
                f"{name}: every Alpaca tool must be interactive-research-only (invariants A/B)"
            )
