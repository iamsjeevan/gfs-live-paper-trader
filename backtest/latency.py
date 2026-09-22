"""Execution latency sensitivity analysis: baseline (t+1 open) vs delayed execution."""

from typing import Dict, List, Optional
import pandas as pd

from backtest.costs import CostModel
from backtest.metrics import calculate_metrics
from backtest.portfolio import run_simulation
from backtest.signals import compute_momentum_signals
from backtest.sizing import compute_target_weights
from backtest.volatility import compute_realized_volatility


def run_latency_sensitivity(
    df: pd.DataFrame,
    timeframe: str = "1d",
    lookbacks: List[int] = (5, 10, 21, 42),
    vol_window: int = 20,
    target_vol: float = 0.40,
    max_leverage: float = 1.0,
    cost_model: Optional[CostModel] = None,
    extra_lags: List[int] = (0, 1, 2),
) -> pd.DataFrame:
    """Evaluate performance when execution is delayed by 0, 1, or 2 bars.

    Parameters
    ----------
    df : pd.DataFrame
        Candle data.
    extra_lags : List[int]
        0: execute at t+1 open (baseline)
        1: execute at t+2 open (1-bar delay)
        2: execute at t+3 open (2-bar delay)
    """
    costs = cost_model or CostModel.from_tier("realistic")

    df_sig = compute_momentum_signals(df, lookbacks=lookbacks)
    df_sig = compute_realized_volatility(df_sig, timeframe=timeframe, window_bars=vol_window)
    df_sig = compute_target_weights(df_sig, target_vol=target_vol, max_leverage=max_leverage)

    rows = []

    for lag in extra_lags:
        df_lag = df_sig.copy()
        if lag > 0:
            df_lag["target_weight"] = df_lag["target_weight"].shift(lag).fillna(0.0)

        sim = run_simulation(df_lag, f"latency_lag_{lag}bars", timeframe=timeframe, cost_model=costs)
        m = calculate_metrics(sim)

        rows.append({
            "extra_lag_bars": lag,
            "description": f"{lag}-bar delay (execute at t+{lag+1} open)",
            "cagr": m["cagr"],
            "sharpe_ratio": m["sharpe_ratio"],
            "sortino_ratio": m["sortino_ratio"],
            "max_drawdown": m["max_drawdown"],
            "calmar_ratio": m["calmar_ratio"],
            "win_rate": m["win_rate"],
            "profit_factor": m["profit_factor"],
            "turnover": m["turnover"],
            "total_costs": m["total_costs"],
        })

    return pd.DataFrame(rows)
