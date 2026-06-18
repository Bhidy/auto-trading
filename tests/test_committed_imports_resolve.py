"""Committed-import integrity tripwire (enforced in CI).

Guards against the exact failure class that took down the P1 End-of-Day job on
2026-06-18: a commit added ``from shared.determinism import ...`` to
``scripts/autonomous_runner.py`` (and ``scripts/research/optimize_strategy.py``)
but the new module ``shared/determinism.py`` was never ``git add``-ed. The caller
shipped to ``main``; the module did not. The cloud checked out a tree where the
import could not resolve, so every EOD run crashed at startup with
``ModuleNotFoundError: No module named 'shared.determinism'``.

Why existing tests did NOT catch it:
  * The import lives behind an ``if __name__ == "__main__"`` + argv guard, so
    importing the module under pytest never executes it.
  * The test that *would* have exercised it was ALSO left untracked.
  * No CI step actually invoked the EOD entry point.

This tripwire closes that gap permanently and cheaply, with zero false positives:
every ``shared.*`` import in any *git-tracked* Python file MUST resolve to a
*git-tracked* module file. It is static (AST), so it catches runtime-guarded
imports too — exactly the ones a smoke test would miss. ``shared/`` is the
canonical cross-portfolio module directory shared by P1/P2/P3 and the research
lane, so "tracked code imports an untracked ``shared.*`` module" is always a bug:
the cloud runs a clean checkout of ``origin/main`` and an untracked file is simply
not there.

See CLAUDE.md "Unified Alpaca client / SINGLE SOURCE OF TRUTH" and
``tests/test_trading_path_purity.py`` for the sibling cloud-path invariants.
"""
import ast
import os
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tracked_files():
    """Files git knows about — i.e. what a fresh cloud checkout actually receives."""
    out = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, text=True
    )
    return set(p for p in out.split("\0") if p)


def _shared_imports(tree):
    """Yield top-level ``shared`` submodule names referenced by a parsed module.

    Handles all three import forms:
      * ``from shared.X import ...``    -> "X"
      * ``from shared import X``        -> "X"
      * ``import shared.X``             -> "X"
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "shared":
                for alias in node.names:           # from shared import X
                    yield alias.name
            elif node.module.startswith("shared."):
                yield node.module.split(".")[1]    # from shared.X[.Y] import ...
        elif isinstance(node, ast.Import):
            for alias in node.names:               # import shared.X
                if alias.name.startswith("shared."):
                    yield alias.name.split(".")[1]


def test_every_committed_shared_import_resolves_to_a_committed_module():
    tracked = _tracked_files()
    py_files = sorted(f for f in tracked if f.endswith(".py"))

    parse_errors = []
    missing = {}  # "shared.X" -> sorted list of caller files

    for rel in py_files:
        path = os.path.join(REPO_ROOT, rel)
        try:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rel)
        except (SyntaxError, UnicodeDecodeError) as exc:  # broken tracked source is itself a defect
            parse_errors.append(f"{rel}: {exc}")
            continue

        for sub in _shared_imports(tree):
            module_file = f"shared/{sub}.py"
            package_init = f"shared/{sub}/__init__.py"
            if module_file not in tracked and package_init not in tracked:
                on_disk = os.path.exists(os.path.join(REPO_ROOT, module_file))
                missing.setdefault(
                    f"shared.{sub} (untracked; on_disk={on_disk})", []
                ).append(rel)

    assert not parse_errors, "Tracked Python files failed to parse:\n  " + "\n  ".join(parse_errors)

    if missing:
        lines = [
            f"  {mod}\n      imported by: {sorted(set(callers))}"
            for mod, callers in sorted(missing.items())
        ]
        raise AssertionError(
            "Tracked code imports shared.* modules that are NOT committed to git.\n"
            "A fresh cloud checkout will crash at import (this is the 2026-06-18 P1 EOD "
            "outage class). `git add` the missing module(s):\n" + "\n".join(lines)
        )


def test_eod_determinism_canary_imports():
    """Direct canary for the specific module that broke EOD.

    The EOD ``__main__`` guard does ``from shared.determinism import
    ensure_hash_seed_pinned``. That import is unreachable from a normal pytest
    ``import autonomous_runner`` (runtime-guarded), so assert it explicitly here:
    if ``shared/determinism.py`` ever goes missing again, CI goes red instead of
    the cloud EOD job.
    """
    from shared.determinism import ensure_hash_seed_pinned

    assert callable(ensure_hash_seed_pinned)
