"""Walk-forward and out-of-sample split validation engine."""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from backtest.costs import CostModel
from backtest.metrics import calculate_metrics
from backtest.portfolio import run_simulation, SimulationResult
from backtest.signals import compute_momentum_signals
from backtest.sizing import compute_target_weights
from backtest.volatility import compute_realized_volatility


def run_split_validation(
    df: pd.DataFrame,
    split_date: str = "2022-01-01 00:00:00",
    timeframe: str = "1d",
    lookbacks: List[int] = (5, 10, 21, 42),
    vol_window: int = 20,
    target_vol: float = 0.40,
    max_leverage: float = 1.0,
    cost_model: Optional[CostModel] = None,
    direction_mode: str = "long_short",
) -> Dict[str, Any]:
    """Execute clean In-Sample (2017-2021) vs Out-of-Sample (2022-2026) split evaluation.

    Parameters
    ----------
    df : pd.DataFrame
        Full historical candles dataframe.
    split_date : str
        Boundary dividing in-sample and out-of-sample.
    """
    costs = cost_model or CostModel.from_tier("realistic")

    # 1. Full data signal generation (signals use strictly backward-looking data)
    df_sig = compute_momentum_signals(df, lookbacks=lookbacks)
    df_sig = compute_realized_volatility(df_sig, timeframe=timeframe, window_bars=vol_window)
    df_sig = compute_target_weights(
        df_sig,
        target_vol=target_vol,
        max_leverage=max_leverage,
        sizing_mode="vol_targeted",
        direction_mode=direction_mode,
    )

    # Split into IS and OOS slices
    # To avoid cold-start warmup on OOS, OOS inherits the rolling indicator history
    # but the simulation portfolio starts fresh with $10,000 at the split boundary!
    is_mask = df_sig["datetime_utc"] < split_date
    oos_mask = df_sig["datetime_utc"] >= split_date

    df_is = df_sig[is_mask].copy().reset_index(drop=True)
    df_oos = df_sig[oos_mask].copy().reset_index(drop=True)

    # Simulate IS
    sim_is = run_simulation(
        df_is,
        experiment_id="split_IS_2017_2021",
        timeframe=timeframe,
        initial_capital=10_000.0,
        cost_model=costs,
    )
    metrics_is = calculate_metrics(sim_is)

    # Simulate OOS
    sim_oos = run_simulation(
        df_oos,
        experiment_id="split_OOS_2022_2026",
        timeframe=timeframe,
        initial_capital=10_000.0,
        cost_model=costs,
    )
    metrics_oos = calculate_metrics(sim_oos)

    # Degradation ratios
    sharpe_degradation = (metrics_oos["sharpe_ratio"] / metrics_is["sharpe_ratio"]) if metrics_is["sharpe_ratio"] != 0 else 0.0
    cagr_degradation = (metrics_oos["cagr"] / metrics_is["cagr"]) if metrics_is["cagr"] != 0 else 0.0

    return {
        "is_result": sim_is,
        "oos_result": sim_oos,
        "is_metrics": metrics_is,
        "oos_metrics": metrics_oos,
        "sharpe_degradation": sharpe_degradation,
        "cagr_degradation": cagr_degradation,
        "split_date": split_date,
    }


def run_rolling_walk_forward(
    df: pd.DataFrame,
    train_bars: int = 730,  # ~2 years of daily bars
    test_bars: int = 365,   # ~1 year of daily bars
    timeframe: str = "1d",
    lookbacks: List[int] = (5, 10, 21, 42),
    vol_window: int = 20,
    target_vol: float = 0.40,
    max_leverage: float = 1.0,
    cost_model: Optional[CostModel] = None,
) -> List[Dict[str, Any]]:
    """Execute rolling walk-forward cross validation over historical segments."""
    costs = cost_model or CostModel.from_tier("realistic")

    df_sig = compute_momentum_signals(df, lookbacks=lookbacks)
    df_sig = compute_realized_volatility(df_sig, timeframe=timeframe, window_bars=vol_window)
    df_sig = compute_target_weights(df_sig, target_vol=target_vol, max_leverage=max_leverage)

    n = len(df_sig)
    step = test_bars
    results = []

    start_idx = 0
    fold = 1
    while start_idx + train_bars + test_bars <= n:
        train_slice = df_sig.iloc[start_idx : start_idx + train_bars].copy().reset_index(drop=True)
        test_slice = df_sig.iloc[start_idx + train_bars : start_idx + train_bars + test_bars].copy().reset_index(drop=True)

        sim_train = run_simulation(train_slice, f"wf_train_fold_{fold}", timeframe=timeframe, cost_model=costs)
        sim_test = run_simulation(test_slice, f"wf_test_fold_{fold}", timeframe=timeframe, cost_model=costs)

        m_train = calculate_metrics(sim_train)
        m_test = calculate_metrics(sim_test)

        deg_ratio = (m_test["sharpe_ratio"] / m_train["sharpe_ratio"]) if m_train["sharpe_ratio"] != 0 else 0.0

        results.append({
            "fold": fold,
            "train_start": train_slice["datetime_utc"].iloc[0],
            "train_end": train_slice["datetime_utc"].iloc[-1],
            "test_start": test_slice["datetime_utc"].iloc[0],
            "test_end": test_slice["datetime_utc"].iloc[-1],
            "train_sharpe": m_train["sharpe_ratio"],
            "test_sharpe": m_test["sharpe_ratio"],
            "train_cagr": m_train["cagr"],
            "test_cagr": m_test["cagr"],
            "train_max_dd": m_train["max_drawdown"],
            "test_max_dd": m_test["max_drawdown"],
            "degradation_ratio": deg_ratio,
        })

        start_idx += step
        fold += 1

    return results
