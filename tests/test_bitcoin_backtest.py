"""Unit and regression tests for Bitcoin momentum backtesting system."""

import numpy as np
import pandas as pd
import pytest

from backtest.costs import CostModel
from backtest.metrics import calculate_metrics, calculate_period_returns
from backtest.portfolio import run_simulation, SimulationResult
from backtest.signals import compute_momentum_signals, get_lookbacks
from backtest.sizing import compute_target_weights
from backtest.volatility import compute_realized_volatility, get_annualization_factor


def test_get_lookbacks():
    """Verify time-scaled and raw lookback bar calculations."""
    # 1D
    assert get_lookbacks("1d", "raw") == [5, 10, 21, 42]
    assert get_lookbacks("1d", "time_scaled") == [5, 10, 21, 42]

    # 4H (6 bars/day)
    assert get_lookbacks("4h", "raw") == [5, 10, 21, 42]
    assert get_lookbacks("4h", "time_scaled") == [30, 60, 126, 252]

    # 1H (24 bars/day)
    assert get_lookbacks("1h", "raw") == [5, 10, 21, 42]
    assert get_lookbacks("1h", "time_scaled") == [120, 240, 504, 1008]

    # 15M (96 bars/day)
    assert get_lookbacks("15m", "time_scaled") == [480, 960, 2016, 4032]

    # 5M (288 bars/day)
    assert get_lookbacks("5m", "time_scaled") == [1440, 2880, 6048, 12096]


def test_compute_momentum_signals():
    """Verify momentum signals produce {-1, +1} and valid composite scores."""
    # 50 days of monotonically increasing prices
    df = pd.DataFrame({
        "close": np.linspace(100.0, 200.0, 50),
    })
    sig_df = compute_momentum_signals(df, lookbacks=(5, 10, 20))

    # All signals should be +1.0 after warmup
    assert sig_df["signal_5"].iloc[5] == 1.0
    assert sig_df["signal_10"].iloc[10] == 1.0
    assert sig_df["signal_20"].iloc[20] == 1.0
    assert sig_df["momentum_score"].iloc[20] == 3.0

    # Test monotonically decreasing prices
    df_down = pd.DataFrame({
        "close": np.linspace(200.0, 100.0, 50),
    })
    sig_down = compute_momentum_signals(df_down, lookbacks=(5, 10, 20))
    assert sig_down["momentum_score"].iloc[20] == -3.0


def test_compute_realized_volatility():
    """Verify realized annualized volatility with floor."""
    # Constant price -> 0 volatility -> clamped by floor
    df = pd.DataFrame({"close": [100.0] * 30})
    vol_df = compute_realized_volatility(df, timeframe="1d", window_bars=20, min_vol=0.05)
    # After warmup at bar 20, vol is 0.0 before clipping, so should be 0.05
    assert vol_df["realized_vol"].iloc[20] == pytest.approx(0.05, abs=1e-5)

    # Check annualization factor
    assert get_annualization_factor("1d") == pytest.approx(np.sqrt(365), rel=1e-5)
    assert get_annualization_factor("1h") == pytest.approx(np.sqrt(365 * 24), rel=1e-5)


def test_compute_target_weights():
    """Verify volatility targeting and leverage capping."""
    df = pd.DataFrame({
        "momentum_score": [4.0, -4.0, 2.0, 0.0],
        "realized_vol": [0.40, 0.40, 0.40, 0.40],
    })

    # Vol targeted 40% with 1x cap
    res = compute_target_weights(df, target_vol=0.40, max_leverage=1.0, sizing_mode="vol_targeted")
    # score=4 -> weight = (4/4) * (0.40/0.40) = 1.0
    assert res["target_weight"].iloc[0] == pytest.approx(1.0)
    assert res["target_weight"].iloc[1] == pytest.approx(-1.0)
    assert res["target_weight"].iloc[2] == pytest.approx(0.5)
    assert res["target_weight"].iloc[3] == pytest.approx(0.0)

    # Vol targeted with 2x leverage and low vol (0.20)
    df_low_vol = pd.DataFrame({
        "momentum_score": [4.0, -4.0],
        "realized_vol": [0.20, 0.20],
    })
    res_lev = compute_target_weights(df_low_vol, target_vol=0.40, max_leverage=2.0)
    # (4/4) * (0.40/0.20) = 2.0
    assert res_lev["target_weight"].iloc[0] == pytest.approx(2.0)
    assert res_lev["target_weight"].iloc[1] == pytest.approx(-2.0)

    # Long-only mode
    res_lo = compute_target_weights(df, target_vol=0.40, max_leverage=1.0, direction_mode="long_only")
    assert res_lo["target_weight"].iloc[0] == pytest.approx(1.0)
    assert res_lo["target_weight"].iloc[1] == pytest.approx(0.0)  # -4 becomes 0 (cash)


def test_zero_lookahead_next_bar_open_execution():
    """Strict test verifying that orders execute strictly at next candle open."""
    # Create 3 candles:
    # Candle 0: Open=100, High=105, Low=95, Close=100. Target weight computed = 1.0
    # Candle 1: Open=110 (gap up!), High=120, Low=105, Close=115. Target weight computed = 0.0
    # Candle 2: Open=115, High=118, Low=110, Close=112.
    df = pd.DataFrame({
        "timestamp": [1000, 2000, 3000],
        "datetime_utc": ["2020-01-01 00:00:00", "2020-01-02 00:00:00", "2020-01-03 00:00:00"],
        "open": [100.0, 110.0, 115.0],
        "high": [105.0, 120.0, 118.0],
        "low": [95.0, 105.0, 110.0],
        "close": [100.0, 115.0, 112.0],
        "target_weight": [1.0, 0.0, 0.0],
    })

    # Zero cost model to check pure price math
    costs = CostModel(fee_rate=0.0, slippage_rate=0.0, borrow_rate_apr=0.0)
    sim = run_simulation(df, initial_capital=10_000.0, cost_model=costs)

    eq = sim.equity_curve
    # At bar 0: cash = 10,000, shares = 0, equity = 10,000
    assert eq["equity"].iloc[0] == pytest.approx(10_000.0)
    assert eq["shares"].iloc[0] == 0.0

    # At bar 1: signal from bar 0 (target_weight=1.0) executes at bar 1 OPEN (110.0).
    # Pre-equity at open = 10,000. Target dollars = 10,000. Shares bought = 10,000 / 110.0 = 90.90909 shares.
    # Holding from open (110.0) to close (115.0) gain = 90.90909 * (115.0 - 110.0) = 454.5454.
    # Ending equity at bar 1 close = 10,000 + 454.5454 = 10,454.5454.
    assert eq["shares"].iloc[1] == pytest.approx(10_000.0 / 110.0, rel=1e-4)
    assert eq["equity"].iloc[1] == pytest.approx(10_454.5454, rel=1e-3)

    # At bar 2: signal from bar 1 (target_weight=0.0) executes at bar 2 OPEN (115.0).
    # Pre-equity at bar 2 open = cash + shares * 115.0 = 10,454.5454.
    # Target shares = 0.0. Position closed at 115.0.
    # Ending equity at bar 2 close remains 10,454.5454 in 100% cash.
    assert eq["shares"].iloc[2] == pytest.approx(0.0)
    assert eq["equity"].iloc[2] == pytest.approx(10_454.5454, rel=1e-3)


def test_cost_deduction():
    """Verify that fees and slippage are correctly deducted from cash on trade."""
    df = pd.DataFrame({
        "timestamp": [1000, 2000],
        "datetime_utc": ["2020-01-01 00:00:00", "2020-01-02 00:00:00"],
        "open": [100.0, 100.0],
        "high": [100.0, 100.0],
        "low": [100.0, 100.0],
        "close": [100.0, 100.0],
        "target_weight": [1.0, 1.0],
    })

    # Realistic: 5 bps fee, 2.5 bps slippage = 7.5 bps total
    costs = CostModel(fee_rate=0.0005, slippage_rate=0.00025, borrow_rate_apr=0.0)
    sim = run_simulation(df, initial_capital=10_000.0, cost_model=costs)

    eq = sim.equity_curve
    # Trade of $10,000 at bar 1 open: fee = $5.0, slippage = $2.5, total cost = $7.50
    assert eq["fee"].iloc[1] == pytest.approx(5.0, abs=1e-3)
    assert eq["slippage"].iloc[1] == pytest.approx(2.5, abs=1e-3)
    assert eq["equity"].iloc[1] == pytest.approx(10_000.0 - 7.50, abs=1e-3)


def test_metrics_calculation():
    """Verify performance metrics calculation."""
    df = pd.DataFrame({
        "timestamp": [1000, 2000, 3000],
        "datetime_utc": ["2020-01-01 00:00:00", "2021-01-01 00:00:00", "2022-01-01 00:00:00"],
        "open": [100.0, 150.0, 200.0],
        "high": [105.0, 155.0, 205.0],
        "low": [95.0, 145.0, 195.0],
        "close": [100.0, 150.0, 200.0],
        "target_weight": [1.0, 1.0, 1.0],
    })
    costs = CostModel(fee_rate=0.0, slippage_rate=0.0, borrow_rate_apr=0.0)
    sim = run_simulation(df, initial_capital=10_000.0, cost_model=costs)
    m = calculate_metrics(sim)

    assert "sharpe_ratio" in m
    assert "max_drawdown" in m
    assert "cagr" in m
    assert "calmar_ratio" in m
    assert m["max_drawdown"] <= 0.0
