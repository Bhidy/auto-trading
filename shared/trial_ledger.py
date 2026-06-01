"""
Persistent trial ledger for the self-learning gate (T1, pure-Python).

The Deflated Sharpe Ratio is only honest if N — the number of strategy
configurations tried — reflects the FULL search history, not just one run's
windows. With multiple testing, the best Sharpe of N zero-skill trials is
expected to look impressive purely by luck; deflating against a too-small N
under-corrects. This ledger persists every gated param-change evaluation so the
gate can deflate against the CUMULATIVE trial count: more trials → higher
expected-max-Sharpe hurdle → stricter approval. It can only tighten the gate,
never loosen it.

Append-only (capped), JSON, dependency-free, read-only w.r.t. trading. Lives in
shared/ so the EOD self-learning loop (scripts/) can import it like governance.
"""
import json
import os
from datetime import datetime, timezone

LEDGER_NAME = "trial_ledger.json"
MAX_ENTRIES = 1000          # cap so the ledger can't grow unbounded across years


def _path(data_dir):
    return os.path.join(str(data_dir), LEDGER_NAME)


def load_trials(data_dir):
    """Return the ledger as a list (empty on missing/corrupt — fails safe)."""
    try:
        with open(_path(data_dir)) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def record_trial(data_dir, entry):
    """Append one evaluation record (adds a UTC timestamp if absent). Caps the
    ledger to the most recent MAX_ENTRIES. Returns the stored entry."""
    entry = dict(entry or {})
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    trials = load_trials(data_dir)
    trials.append(entry)
    if len(trials) > MAX_ENTRIES:
        trials = trials[-MAX_ENTRIES:]
    with open(_path(data_dir), "w") as f:
        json.dump(trials, f, indent=2)
    return entry


def historical_oos_sharpes(data_dir):
    """Out-of-sample Sharpes of all prior trials — fed to the DSR as additional
    trials so N reflects the whole search history (counteracts selection bias)."""
    return [t["oos_sharpe"] for t in load_trials(data_dir)
            if isinstance(t, dict) and isinstance(t.get("oos_sharpe"), (int, float))]


def trial_count(data_dir):
    """Cumulative number of recorded trials."""
    return len(load_trials(data_dir))
