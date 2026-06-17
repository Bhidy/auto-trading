"""Strategy-spec validator — the "formalize before you trust it" front door.

Adopted from the Alpaca skill's step-1 discipline: before any strategy or
catalyst pattern is trusted (or a self-learning knob is tuned), it must exist as
a PRECISE, falsifiable spec — exact indicators+params, entry/exit bounds, an
explicit signal-bar≠fill-bar separation, a named fill model, sizing, friction,
and a benchmark. This module validates that contract.

Pure-stdlib (safe to import anywhere). It is DELIBERATELY NOT wired into
gate_param_change — per the red-team, coupling a hard spec gate into the
self-learning loop risks freezing it. This is a research / committee / CI
conformance tool, not a runtime gate on the money path.
"""
import json

REQUIRED = [
    "spec_id", "portfolio", "universe", "timeframe", "indicators",
    "entry_rule", "exit_rule", "signal_bar", "fill", "sizing",
    "fees_bps", "slippage_bps", "benchmark",
]

FILL_MODELS = {"next_open", "time_based", "same_bar", "limit", "stop"}


def validate_spec(spec):
    """Return ``(ok: bool, errors: list[str])`` for a single strategy spec."""
    if not isinstance(spec, dict):
        return False, ["spec must be a JSON object"]

    errors = []
    for k in REQUIRED:
        if k not in spec or spec[k] in (None, "", [], {}):
            errors.append(f"missing required field: {k}")

    # Friction must be explicit + non-negative (no hidden costs).
    for f in ("fees_bps", "slippage_bps"):
        v = spec.get(f)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
            errors.append(f"{f} must be a non-negative number")

    # Indicators must each name their exact params (no vague "an RSI").
    inds = spec.get("indicators")
    if inds is not None and not isinstance(inds, list):
        errors.append("indicators must be a list")
    elif isinstance(inds, list):
        for i, ind in enumerate(inds):
            if not isinstance(ind, dict) or "name" not in ind or "params" not in ind:
                errors.append(f"indicator[{i}] must have name + params")

    # Fill model + the cardinal anti-look-ahead rule.
    fill = spec.get("fill")
    if isinstance(fill, dict):
        model = fill.get("model")
        if model not in FILL_MODELS:
            errors.append(f"fill.model must be one of {sorted(FILL_MODELS)} (got {model!r})")
        same_bar = (model == "same_bar") or (spec.get("signal_bar") == fill.get("bar"))
        if same_bar and not fill.get("look_ahead_ack"):
            errors.append(
                "signal and fill on the same bar requires fill.look_ahead_ack=true "
                "(must explicitly document the look-ahead)")
    elif "fill" not in [e.split(":")[-1].strip() for e in errors]:
        errors.append("fill must be an object with a 'model'")

    return (not errors), errors


def load_and_validate(path):
    """Validate a spec file on disk. Returns ``(ok, errors)``."""
    try:
        with open(path) as f:
            spec = json.load(f)
    except (OSError, ValueError) as e:
        return False, [f"cannot read spec: {e}"]
    return validate_spec(spec)
