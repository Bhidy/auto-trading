#!/usr/bin/env python3
"""
Performance Tracker & Self-Learning Engine
Tracks every trade outcome, computes win rates, and adapts strategy parameters.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from shared.accounting import realized_pnl  # noqa: E402

def load_json(filename, default=None):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(filename, data):
    with open(os.path.join(DATA_DIR, filename), "w") as f:
        json.dump(data, f, indent=2)

# ---------------------------------------------------------------------------
# TRADE LOGGING
# ---------------------------------------------------------------------------

def log_trade(symbol, side, qty, entry_price, bucket, signal_score, reasons,
              stop_loss=None, take_profit=None):
    log = load_json("trade_log.json", [])
    entry = {
        "id": len(log) + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "entry_price": entry_price,
        "bucket": bucket,
        "signal_score": signal_score,
        "reasons": reasons,
        "exit_price": None,
        "exit_timestamp": None,
        "pnl": None,
        "pnl_pct": None,
        "hold_days": None,
        "status": "open",
    }
    if stop_loss is not None:
        entry["stop_loss"] = stop_loss
    if take_profit is not None:
        entry["take_profit"] = take_profit
    log.append(entry)
    save_json("trade_log.json", log)
    return log[-1]["id"]

def close_trade(trade_id, exit_price):
    log = load_json("trade_log.json", [])
    for trade in log:
        if trade["id"] == trade_id and trade["status"] == "open":
            trade["exit_price"] = exit_price
            trade["exit_timestamp"] = datetime.now(timezone.utc).isoformat()
            entry = datetime.fromisoformat(trade["timestamp"])
            trade["hold_days"] = (datetime.now(timezone.utc) - entry).days

            # Net-of-fee realized P&L (C5): logged P&L now reflects round-trip
            # regulatory fees so Sharpe/profit-factor/readiness gates are honest.
            r = realized_pnl(trade["side"], trade["qty"], trade["entry_price"],
                             exit_price)
            entry_notional = abs(trade["entry_price"] * trade["qty"]) or 1.0
            trade["gross_pnl"] = r["gross_pnl"]
            trade["fees"] = r["fees"]
            trade["pnl"] = r["net_pnl"]
            trade["pnl_pct"] = round(r["net_pnl"] / entry_notional * 100, 2)
            trade["status"] = "closed"
            break
    save_json("trade_log.json", log)

def find_open_trade(symbol):
    log = load_json("trade_log.json", [])
    for trade in reversed(log):
        if trade["symbol"] == symbol and trade["status"] == "open":
            return trade
    return None

# ---------------------------------------------------------------------------
# PERFORMANCE METRICS
# ---------------------------------------------------------------------------

def compute_metrics(lookback_days=None):
    log = load_json("trade_log.json", [])
    closed = [t for t in log if t["status"] == "closed"]

    if lookback_days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
        closed = [t for t in closed if t.get("exit_timestamp", "") >= cutoff]

    if not closed:
        return {
            "total_trades": 0,
            "win_rate": None,
            "avg_pnl_pct": None,
            "avg_win": None,
            "avg_loss": None,
            "win_loss_ratio": None,
            "max_win_pct": None,
            "max_loss_pct": None,
            "total_pnl": 0,
            "profit_factor": None,
            "sharpe_estimate": None,
        }

    wins = [t for t in closed if (t.get("pnl") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl") or 0) <= 0]
    win_rate = len(wins) / len(closed) if closed else 0.5

    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    wl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 1.0

    gross_profit = sum(t["pnl"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 1
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 1.0

    all_pnl_pcts = [t.get("pnl_pct", 0) for t in closed]
    mean_pnl = sum(all_pnl_pcts) / len(all_pnl_pcts) if all_pnl_pcts else 0
    if len(all_pnl_pcts) > 1:
        variance = sum((p - mean_pnl) ** 2 for p in all_pnl_pcts) / (len(all_pnl_pcts) - 1)
        std = variance ** 0.5
        sharpe = (mean_pnl / std) if std > 0 else 0
    else:
        sharpe = 0

    pnl_values = [t.get("pnl_pct", 0) for t in closed]

    return {
        "total_trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 3),
        "avg_pnl_pct": round(mean_pnl, 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "win_loss_ratio": round(wl_ratio, 2),
        "max_win_pct": round(max(pnl_values), 2) if pnl_values else 0,
        "max_loss_pct": round(min(pnl_values), 2) if pnl_values else 0,
        "total_pnl": round(sum(t.get("pnl", 0) for t in closed), 2),
        "profit_factor": round(profit_factor, 2),
        "sharpe_estimate": round(sharpe, 2),
    }

def compute_metrics_by_bucket():
    log = load_json("trade_log.json", [])
    closed = [t for t in log if t["status"] == "closed"]
    buckets = set(t.get("bucket", "unknown") for t in closed)
    result = {}
    for bucket in buckets:
        bucket_trades = [t for t in closed if t.get("bucket") == bucket]
        if not bucket_trades:
            continue
        wins = [t for t in bucket_trades if (t.get("pnl") or 0) > 0]
        result[bucket] = {
            "trades": len(bucket_trades),
            "win_rate": round(len(wins) / len(bucket_trades), 3) if bucket_trades else 0,
            "total_pnl": round(sum(t.get("pnl", 0) for t in bucket_trades), 2),
            "avg_pnl_pct": round(sum(t.get("pnl_pct", 0) for t in bucket_trades) / len(bucket_trades), 2),
        }
    return result

def compute_metrics_by_symbol():
    log = load_json("trade_log.json", [])
    closed = [t for t in log if t["status"] == "closed"]
    symbols = set(t["symbol"] for t in closed)
    result = {}
    for sym in symbols:
        sym_trades = [t for t in closed if t["symbol"] == sym]
        if not sym_trades:
            continue
        wins = [t for t in sym_trades if (t.get("pnl") or 0) > 0]
        result[sym] = {
            "trades": len(sym_trades),
            "win_rate": round(len(wins) / len(sym_trades), 3),
            "total_pnl": round(sum(t.get("pnl", 0) for t in sym_trades), 2),
            "avg_pnl_pct": round(sum(t.get("pnl_pct", 0) for t in sym_trades) / len(sym_trades), 2),
        }
    return result

# ---------------------------------------------------------------------------
# ADAPTIVE PARAMETER TUNING (SELF-LEARNING)
# ---------------------------------------------------------------------------

# Strategy knobs subject to out-of-sample (walk-forward) gating. Observability
# fields (win_rate_*, avg_win_loss_ratio) are NOT gated — they always refresh.
_GATED_KNOBS = (
    "position_size_multiplier",
    "rsi_overbought",
    "trailing_stop_atr_mult",
    "confidence_buy_threshold",
)


def adapt_parameters(validate_with_bars=None):
    """Adapt strategy parameters from rolling performance.

    If `validate_with_bars=(symbol_bars, spy_bars)` is supplied, any change to
    the strategy knobs must pass walk-forward out-of-sample validation against
    the prior knobs; otherwise the knobs are reverted (fail-closed). This stops
    the self-learning loop from tuning on live noise. Without bars, the existing
    bounded + min-sample-size logic applies (knobs still move, but only within
    hard bounds and after >=5/10 closed trades).
    """
    import copy

    params = load_json("strategy_params.json", None)
    if params is None:
        from analyst_v2 import load_adaptive_params
        params = load_adaptive_params()

    original = copy.deepcopy(params)

    metrics_7d = compute_metrics(7)
    metrics_30d = compute_metrics(30)
    metrics_all = compute_metrics()

    params["win_rate_7d"] = metrics_7d["win_rate"] if metrics_7d["win_rate"] is not None else 0.5
    params["win_rate_30d"] = metrics_30d["win_rate"] if metrics_30d["win_rate"] is not None else 0.5
    params["avg_win_loss_ratio"] = metrics_all["win_loss_ratio"] if metrics_all["win_loss_ratio"] is not None else 1.0

    wr_30d = params["win_rate_30d"]
    pf_30d = metrics_30d["profit_factor"] or 1.0

    if metrics_30d["total_trades"] >= 5:
        if wr_30d > 0.60 and pf_30d > 1.5:
            params["position_size_multiplier"] = min(params["position_size_multiplier"] * 1.05, 1.5)
        elif wr_30d < 0.40 or pf_30d < 0.8:
            params["position_size_multiplier"] = max(params["position_size_multiplier"] * 0.90, 0.5)
        else:
            params["position_size_multiplier"] = params["position_size_multiplier"] * 0.99 + 1.0 * 0.01

    if metrics_30d["total_trades"] >= 10:
        log = load_json("trade_log.json", [])
        overbought_trades = [t for t in log if t["status"] == "closed" and "overbought" in str(t.get("reasons", "")).lower()]
        if overbought_trades:
            ob_win_rate = len([t for t in overbought_trades if (t.get("pnl") or 0) > 0]) / len(overbought_trades)
            if ob_win_rate > 0.6:
                params["rsi_overbought"] = min(params["rsi_overbought"] + 1, 85)
            elif ob_win_rate < 0.3:
                params["rsi_overbought"] = max(params["rsi_overbought"] - 1, 65)

    if metrics_30d["total_trades"] >= 5:
        max_loss = metrics_30d["max_loss_pct"]
        if max_loss is not None and max_loss < -8:
            params["trailing_stop_atr_mult"] = max(params["trailing_stop_atr_mult"] - 0.1, 1.5)
        if wr_30d < 0.45:
            avg_loss = metrics_30d["avg_loss_pct"]
            if avg_loss is not None and avg_loss > -2:
                params["trailing_stop_atr_mult"] = min(params["trailing_stop_atr_mult"] + 0.1, 4.0)

    if metrics_30d["total_trades"] >= 10:
        if wr_30d > 0.55:
            params["confidence_buy_threshold"] = max(params["confidence_buy_threshold"] - 0.02, 0.30)
        elif wr_30d < 0.40:
            params["confidence_buy_threshold"] = min(params["confidence_buy_threshold"] + 0.02, 0.70)

    gate_detail = None
    knobs_changed = any(original.get(k) != params.get(k) for k in _GATED_KNOBS)
    if validate_with_bars is not None and knobs_changed:
        try:
            from backtest.walk_forward import gate_param_change
            symbol_bars, spy_bars = validate_with_bars
            approved, gate_detail = gate_param_change(original, params, symbol_bars, spy_bars)
            if not approved:
                # Revert ONLY the strategy knobs; keep refreshed metric fields.
                for k in _GATED_KNOBS:
                    if k in original:
                        params[k] = original[k]
        except Exception as e:
            # Fail closed: an un-validatable change is not applied.
            gate_detail = {"error": str(e)}
            for k in _GATED_KNOBS:
                if k in original:
                    params[k] = original[k]

    save_json("strategy_params.json", params)

    return {
        "metrics_7d": metrics_7d,
        "metrics_30d": metrics_30d,
        "metrics_all": metrics_all,
        "updated_params": params,
        "walk_forward_gate": gate_detail,
    }

# ---------------------------------------------------------------------------
# LEARNING REPORT
# ---------------------------------------------------------------------------

def generate_learning_report():
    metrics_all = compute_metrics()
    metrics_7d = compute_metrics(7)
    metrics_30d = compute_metrics(30)
    by_bucket = compute_metrics_by_bucket()
    by_symbol = compute_metrics_by_symbol()

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall": metrics_all,
        "last_7_days": metrics_7d,
        "last_30_days": metrics_30d,
        "by_bucket": by_bucket,
        "by_symbol": by_symbol,
        "insights": [],
    }

    # Generate insights
    if metrics_30d["total_trades"] >= 5:
        wr = metrics_30d["win_rate"]
        if wr is not None and wr > 0.55:
            report["insights"].append("System performing well — consider gradual position size increase")
        if wr is not None and wr < 0.40:
            report["insights"].append("Win rate declining — tighten entry criteria")
        pf = metrics_30d["profit_factor"]
        if pf is not None and pf > 2.0:
            report["insights"].append("Excellent risk/reward — strategy well-calibrated")
        if pf is not None and pf < 1.0:
            report["insights"].append("Losing money — reduce exposure and review strategy")

    for bucket, data in by_bucket.items():
        if data["trades"] >= 3 and data["win_rate"] < 0.30:
            report["insights"].append(f"Bucket '{bucket}' underperforming severely — consider reducing allocation")
        if data["trades"] >= 3 and data["win_rate"] > 0.70:
            report["insights"].append(f"Bucket '{bucket}' outperforming — consider increasing allocation")

    save_json("learning_report.json", report)
    return report

if __name__ == "__main__":
    report = generate_learning_report()
    print(json.dumps(report, indent=2))
