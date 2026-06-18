"""Committed-reference integrity tripwires (enforced in CI).

Guards against the failure class that took down the P1 End-of-Day job on
2026-06-18: committed code (or a committed workflow) referenced a first-party
file that was never ``git add``-ed. The reference shipped to ``main``; the file
did not. The cloud checked out a tree where it could not resolve, so the job
crashed at startup (``ModuleNotFoundError: No module named 'shared.determinism'``).

Why existing CI did NOT catch it: the import lived behind an
``if __name__ == "__main__"`` + argv guard (never executed by a plain pytest
``import``), the test that *would* have exercised it was also left untracked, and
no CI step invoked the entry point. These tripwires close that gap permanently,
statically (so runtime-guarded references are caught too), with zero false
positives — a reference only fails if its target *exists on disk but is not
git-tracked*, i.e. it is genuinely missing from a clean ``origin/main`` checkout.

Covers all three portfolios and the workflow layer:
  1. test_every_first_party_import_resolves_to_a_committed_module
  2. test_workflow_referenced_scripts_are_committed
  3. test_cloud_path_sources_compile
  4. test_eod_determinism_canary_imports   (specific 2026-06-18 regression)

Sibling cloud-path invariants: ``tests/test_trading_path_purity.py`` (dependency
purity) and ``tests/test_skills_lock_pinned.py`` (vendored-tool pinning).
"""
import ast
import glob
import os
import py_compile
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories that each cloud entry point places on sys.path. An absolute import
# is first-party iff a matching file exists under one of these roots.
IMPORT_ROOTS = ("", "scripts", "political-copy-bot/scripts", "event-driven-bot/scripts")

# Cloud-path source trees (the 3 engines + shared core). The dashboard (Node) and
# anything else is out of scope for the Python import guard.
SOURCE_PREFIXES = (
    "scripts/",
    "shared/",
    "political-copy-bot/scripts/",
    "event-driven-bot/scripts/",
)


def _tracked_files():
    """Exactly what a fresh cloud checkout of origin/main receives."""
    out = subprocess.check_output(["git", "ls-files", "-z"], cwd=REPO_ROOT, text=True)
    return set(p for p in out.split("\0") if p)


def _candidates(dotted):
    """Repo-relative file paths an absolute dotted import could resolve to."""
    parts = dotted.split(".")
    out = []
    for root in IMPORT_ROOTS:
        base = "/".join([p for p in [root, *parts] if p])
        out.append(base + ".py")
        out.append(base + "/__init__.py")
    return out


def _classify(dotted, tracked):
    """'ok' (tracked), 'untracked' (on disk, not tracked => the bug), or 'absent'."""
    cands = _candidates(dotted)
    if any(c in tracked for c in cands):
        return "ok"
    if any(os.path.exists(os.path.join(REPO_ROOT, c)) for c in cands):
        return "untracked"
    return "absent"  # third-party / stdlib / an imported attribute, not a module


def _dotted_targets(tree):
    """Every dotted name an import statement could require as a first-party module.

    For ``from a.b import c`` we check ``a.b`` (the package) AND ``a.b.c`` (in case
    ``c`` is a submodule). An imported *attribute* simply classifies as 'absent'
    (no file on disk), so this never false-positives on function/class names.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:  # skip relative imports (intra-package)
                continue
            yield node.module
            for alias in node.names:
                yield f"{node.module}.{alias.name}"


def test_every_first_party_import_resolves_to_a_committed_module():
    """No tracked engine source may import a first-party module that isn't tracked."""
    tracked = _tracked_files()
    py_files = sorted(
        f for f in tracked if f.endswith(".py") and f.startswith(SOURCE_PREFIXES)
    )

    parse_errors, missing = [], {}
    for rel in py_files:
        try:
            with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
        except (SyntaxError, UnicodeDecodeError) as exc:
            parse_errors.append(f"{rel}: {exc}")
            continue
        for dotted in _dotted_targets(tree):
            if _classify(dotted, tracked) == "untracked":
                missing.setdefault(dotted, set()).add(rel)

    assert not parse_errors, "Tracked sources failed to parse:\n  " + "\n  ".join(parse_errors)
    if missing:
        lines = [f"  {mod}\n      imported by: {sorted(callers)}" for mod, callers in sorted(missing.items())]
        raise AssertionError(
            "Tracked code imports first-party modules that are present on disk but NOT "
            "committed to git. A clean origin/main checkout will crash at import (the "
            "2026-06-18 P1 EOD outage class). `git add` the module(s):\n" + "\n".join(lines)
        )


# --------------------------------------------------------------------------- #
# Sibling class: a committed workflow invokes a script that isn't committed.   #
# Each Actions STEP resets cwd to the repo root (a `cd` only persists within one #
# run block), and bots run via `cd $GITHUB_WORKSPACE/<bot> && python3 scripts/…`.#
# So resolve cwd-agnostically: a reference is satisfied if it maps to a tracked  #
# file under the repo root OR under either bot dir. It fails only when NO         #
# committed file matches anywhere — exactly "missing from the checkout".         #
# --------------------------------------------------------------------------- #
_RUN = re.compile(r'\b(?:python3?|bash|sh)\s+("?)([\w./-]+\.(?:py|sh))\1')
_RUN_BASES = ("", "event-driven-bot", "political-copy-bot")


def _workflow_script_refs():
    """Yield (workflow, script-path-as-written) for every script a workflow runs.
    Heredocs / `python3 -c` (no path token) and absolute paths are ignored."""
    for wf in sorted(glob.glob(os.path.join(REPO_ROOT, ".github/workflows/*.yml"))):
        for line in open(wf, encoding="utf-8"):
            for m in _RUN.finditer(line):
                path = m.group(2)
                if not path.startswith(("-", "/")):
                    yield os.path.basename(wf), path


def test_workflow_referenced_scripts_are_committed():
    """Every script a workflow shells out to must resolve to a git-tracked file."""
    tracked = _tracked_files()
    missing = {}
    for wf, path in _workflow_script_refs():
        candidates = [os.path.normpath(os.path.join(b, path)) if b else path for b in _RUN_BASES]
        if any(c in tracked for c in candidates):
            continue
        on_disk = any(os.path.exists(os.path.join(REPO_ROOT, c)) for c in candidates)
        missing.setdefault(path, {"on_disk": on_disk, "wf": set()})["wf"].add(wf)
    if missing:
        lines = [f"  {p}  (exists_on_disk={info['on_disk']})  referenced by: {sorted(info['wf'])}" for p, info in sorted(missing.items())]
        raise AssertionError(
            "GitHub Actions workflows invoke scripts not committed to git anywhere. "
            "A scheduled run on a clean checkout will fail:\n" + "\n".join(lines)
        )


def test_cloud_path_sources_compile():
    """Every tracked cloud-path source byte-compiles (no committed syntax errors)."""
    tracked = _tracked_files()
    py_files = sorted(f for f in tracked if f.endswith(".py") and f.startswith(SOURCE_PREFIXES))
    errors = []
    for rel in py_files:
        try:
            py_compile.compile(os.path.join(REPO_ROOT, rel), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"{rel}: {exc.msg}")
    assert not errors, "Committed cloud-path sources fail to compile:\n  " + "\n  ".join(errors)


def test_eod_determinism_canary_imports():
    """Direct canary for the module that broke EOD (runtime-guarded => invisible to
    a normal pytest import). If shared/determinism.py ever goes missing again, CI
    goes red here instead of the cloud EOD job."""
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    from shared.determinism import ensure_hash_seed_pinned

    assert callable(ensure_hash_seed_pinned)
