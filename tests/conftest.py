"""Shared pytest fixtures. Makes the P1 `scripts/` package importable and
provides canonical risk-limit and portfolio fixtures mirroring production."""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
for _p in (REPO_ROOT, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def limits():
    """Canonical risk limits — mirrors config/risk_limits.json."""
    return {
        "max_daily_loss_pct": 4.0,
        "max_weekly_loss_pct": 8.0,
        "kill_switch_drawdown_pct": 18.0,
        "max_single_position_pct": {"etf": 12.0, "stock": 8.0, "penny": 1.0, "crypto": 5.0},
        "max_crypto_exposure_pct": 10.0,
        "max_trades_per_day": 12,
        "max_gross_exposure_pct": 160.0,
        "max_short_exposure_pct": 25.0,
        "penny_stock_rules": {
            "min_price": 1.0, "max_price": 5.0,
            "min_volume": 2_000_000, "min_dollar_volume": 5_000_000,
        },
    }


@pytest.fixture
def portfolio():
    """Healthy portfolio with headroom for new positions."""
    return {
        "equity": 100_000.0,
        "starting_equity": 100_000.0,
        "day_start_equity": 100_000.0,
        "week_start_equity": 100_000.0,
        "positions": {},
        "trades_today": 0,
        "total_exposure": 0.0,
        "short_exposure": 0.0,
        "crypto_exposure": 0.0,
        "halted": False,
        "halt_reason": None,
        "halt_until": None,
    }
