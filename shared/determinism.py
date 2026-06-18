"""Deterministic-hashing guard for the reproducibility-critical entry points
(the offline strategy-research CLI and the EOD self-learning gate).

Python randomizes ``str``/``bytes``/``frozenset`` hashing per process (PEP 456),
which changes ``set`` iteration order run-to-run. The backtest / walk-forward
self-learning path is already hardened to sort every symbol collection, so it is
order-independent on its own. ``ensure_hash_seed_pinned()`` is a belt-and-suspenders
on top of that: it pins ``PYTHONHASHSEED`` so a gate (or research) decision is
bit-for-bit reproducible across separate process invocations even if a future
change reintroduces a hash-ordered collection.

Pure stdlib (``os``/``sys`` only) — safe to import on the requests-only cloud path
(see ``tests/test_trading_path_purity.py``). Call it ONLY from a process entry
point (an ``if __name__ == "__main__"`` block), never at import time and never from
inside a library function: it re-execs the interpreter, so it must run before any
meaningful work and must not fire when the module is imported under pytest.
"""
import os
import sys


def ensure_hash_seed_pinned(seed="0"):
    """Guarantee this process runs with ``PYTHONHASHSEED == seed``.

    ``PYTHONHASHSEED`` is read once at interpreter startup and cannot be changed
    in-process. If it is not already pinned, set it in the environment and re-exec
    the SAME interpreter with the SAME argv. After the re-exec the env var matches,
    so this returns immediately — no re-exec loop is possible.

    Returns ``False`` when the process was already pinned (no-op). On the first,
    unpinned invocation it does NOT return: ``os.execv`` replaces the process image.
    """
    if os.environ.get("PYTHONHASHSEED") == str(seed):
        return False
    # Re-exec needs a reconstructable argv. ``python -c <code>`` sets argv[0] to
    # ``'-c'`` and drops the code string, so re-exec would corrupt the invocation;
    # an interactive/REPL caller has no script either. In those cases skip the
    # re-exec (the ordering fixes already guarantee determinism — the pin is only
    # defense-in-depth). Production entry points are always script invocations,
    # where argv[0] is the script path and this holds.
    if not sys.argv or not os.path.isfile(sys.argv[0]):
        return False
    os.environ["PYTHONHASHSEED"] = str(seed)
    # Replace the current process with an identically-invoked one that now starts
    # with deterministic hashing. CWD and inherited env (incl. PYTHONPATH) are
    # preserved; argv is re-run verbatim.
    os.execv(sys.executable, [sys.executable, *sys.argv])
