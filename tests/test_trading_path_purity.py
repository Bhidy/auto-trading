"""Cloud-path import-purity tripwire (invariant A + B, enforced in CI).

The autonomous cloud trading/EOD path runs with ``requirements.txt == 'requests'``
only. Heavy scientific / ML / LLM / vendored-CLI imports are allowed ONLY in the
offline T2 research lane (``scripts/research/``, installed via
``requirements-research.txt``) and the dashboard. This guard fails the build if
any trading-path module imports a banned top-level package, or if
``requirements.txt`` gains a runtime dependency beyond ``requests``.

Why this is a hard gate, not a convention: a heavy/LLM/CLI import leaking onto
the cloud path would crash the requests-only runtime mid-session (missed trades,
unmanaged stops) — an outage-class, money-losing failure across all 3 portfolios.
It also structurally enforces "no Claude/LLM in the autonomous loop" by banning
the LLM SDKs. See CLAUDE.md "dependency-tiering law" and
``memory/feedback_cloud_only_no_claude_pc``.

NOTE: ``scripts/backtest/`` is intentionally IN scope (not excluded). The
backtest stack is imported by the EOD self-learning path, so it must stay
pure-Python — this guard keeps it that way.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories whose .py files can execute on the autonomous cloud trading/EOD path.
TRADING_PATH_DIRS = [
    ROOT / "scripts",
    ROOT / "shared",
    ROOT / "event-driven-bot" / "scripts",
    ROOT / "political-copy-bot" / "scripts",
]

# The ONLY place heavy deps may be imported: the manual, offline T2 research lane.
EXCLUDED_DIRS = [
    ROOT / "scripts" / "research",
]

# Banned top-level modules:
#   - scientific / ML stack  -> T2 offline research lane only
#   - LLM SDKs               -> invariant B: no Claude/LLM in the autonomous loop
#   - vendored Alpaca CLI/skill wrappers -> interactive-research lane only
BANNED = {
    "numpy", "pandas", "scipy", "sklearn", "statsmodels",
    "torch", "tensorflow", "xgboost", "lightgbm", "cvxpy", "matplotlib",
    "anthropic", "openai", "cohere", "litellm", "langchain",
    "alpaca_cli", "alpaca_skills",
}


def _py_files():
    for d in TRADING_PATH_DIRS:
        if not d.exists():
            continue
        for f in d.rglob("*.py"):
            if "__pycache__" in f.parts:
                continue
            if any(f.is_relative_to(e) for e in EXCLUDED_DIRS):
                continue
            yield f


def _imported_top_levels(tree):
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Only absolute imports name a third-party package; level>0 is relative.
            if node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
    return mods


def test_trading_path_has_no_heavy_or_llm_imports():
    offenders = []
    for f in _py_files():
        bad = _imported_top_levels(ast.parse(f.read_text(), filename=str(f))) & BANNED
        if bad:
            offenders.append(f"{f.relative_to(ROOT)}: {sorted(bad)}")
    assert not offenders, (
        "Banned heavy/LLM/CLI import on the requests-only cloud trading path:\n  "
        + "\n  ".join(offenders)
        + "\nMove this work into scripts/research/ (offline T2 lane) and emit a static "
        "artifact the pure-Python path reads. See CLAUDE.md dependency-tiering law."
    )


def test_requirements_txt_is_requests_only():
    lines = [
        ln.strip()
        for ln in (ROOT / "requirements.txt").read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    assert len(lines) == 1 and lines[0].lower().startswith("requests"), (
        f"requirements.txt must declare ONLY 'requests' on the cloud path; found: {lines}. "
        "Heavy deps belong in requirements-research.txt (offline T2 lane)."
    )
