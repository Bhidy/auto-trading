"""Phase-0 fix C6: a held position absent from today's signals must keep its
PERSISTED entry stop, not be left unprotected (the -10.8% no-stop failure mode)."""
from portfolio_manager import check_stop_triggers, compute_stop_levels

POS = [{"symbol": "TSLA", "avg_entry_price": 100.0, "current_price": 88.0, "side": "long"}]
NO_SIGNALS = {"signals": []}
OPEN = [{"symbol": "TSLA", "status": "open", "stop_loss": 95.0, "take_profit": 120.0}]


def test_fallback_protects_position_absent_from_signals():
    stops = compute_stop_levels(POS, NO_SIGNALS, open_trades=OPEN)
    assert stops["TSLA"]["stop_loss"] == 95.0
    triggers = check_stop_triggers(POS, NO_SIGNALS, open_trades=OPEN)
    assert any(t["action"] == "STOP_LOSS_SELL" and t["symbol"] == "TSLA" for t in triggers)


def test_without_open_trades_old_unprotected_behavior_preserved():
    # Backward-compatible: no open_trades passed -> no stop derivable from empty signals.
    stops = compute_stop_levels(POS, NO_SIGNALS)
    assert stops["TSLA"]["stop_loss"] is None
    assert check_stop_triggers(POS, NO_SIGNALS) == []


def test_signal_stop_takes_precedence_over_fallback():
    sig = {"signals": [{"symbol": "TSLA",
                        "risk_management": {"stop_loss": 97.0, "take_profit": 121.0}}]}
    stops = compute_stop_levels(POS, sig, open_trades=OPEN)
    assert stops["TSLA"]["stop_loss"] == 97.0  # today's signal wins, not the 95 fallback


def test_fallback_does_not_block_breakeven_tightening():
    # Up >3%: breakeven (entry*1.005=100.5) must still raise the stop above the 90 fallback.
    pos = [{"symbol": "AAA", "avg_entry_price": 100.0, "current_price": 106.0, "side": "long"}]
    open_t = [{"symbol": "AAA", "status": "open", "stop_loss": 90.0, "take_profit": 130.0}]
    stops = compute_stop_levels(pos, {"signals": []}, open_trades=open_t)
    assert stops["AAA"]["stop_loss"] == 100.5  # tightened above the fallback, never loosened


def test_closed_trades_are_not_used_as_fallback():
    closed = [{"symbol": "TSLA", "status": "closed", "stop_loss": 95.0}]
    stops = compute_stop_levels(POS, NO_SIGNALS, open_trades=closed)
    assert stops["TSLA"]["stop_loss"] is None  # only OPEN lots seed the fallback
