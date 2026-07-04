"""Profile-aware risk-limits loader — the SINGLE decision of which limits file
the P1 trading path uses.

``RISK_PROFILE=live`` selects the tighter ``config/risk_limits.live.json`` for
the fractional live-capital ramp; anything else (the default) uses the paper
``config/risk_limits.json``. If the live file is missing it FAILS CLOSED to the
paper file, so a misconfiguration can never silently WIDEN limits.

Why this exists (audit 2026-07-04): the profile switch previously lived only in
``risk_officer.load_config``, but the core allocator, the intraday monitor, and
the cap-trim logic each loaded ``risk_limits.json`` DIRECTLY — so a live run
would have sized the core and set the kill switch with PAPER limits (12% ETF /
18% kill-switch) instead of the live ones (6% / 10%). Routing every load through
here makes ``RISK_PROFILE=live`` bind end-to-end. A live-safety precondition.

stdlib-only (cloud-path safe).
"""
import json
import os

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG_DIR = os.path.join(_REPO_ROOT, "config")


def active_profile():
    """'live' or 'paper' (default). Anything but exactly 'live' is paper."""
    return "live" if os.environ.get("RISK_PROFILE", "paper").strip().lower() == "live" else "paper"


def risk_limits_path(config_dir=None):
    """Absolute path to the limits file for the active profile. Fails closed to
    the paper file if the live file is absent."""
    config_dir = str(config_dir) if config_dir is not None else _DEFAULT_CONFIG_DIR
    name = "risk_limits.live.json" if active_profile() == "live" else "risk_limits.json"
    path = os.path.join(config_dir, name)
    if not os.path.exists(path):
        path = os.path.join(config_dir, "risk_limits.json")
    return path


def load_risk_limits(config_dir=None, default=None):
    """Load the active-profile risk limits. ``default`` mirrors the callers'
    ``load_json(..., {})`` contract when the file can't be read."""
    try:
        with open(risk_limits_path(config_dir)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default if default is not None else {}
