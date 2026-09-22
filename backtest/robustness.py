"""Parameter sensitivity sweeps and robustness analysis."""

from itertools import product
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from backtest.costs import CostModel
from backtest.metrics import calculate_metrics
from backtest.portfolio import run_simulation
from backtest.signals import compute_momentum_signals
from backtest.sizing import compute_target_weights
from backtest.volatility import compute_realized_volatility

# Candidate parameter sets
LOOKBACK_SETS = {
    "faster_[3,7,14,30]": (3, 7, 14, 30),
    "baseline_[5,10,21,42]": (5, 10, 21, 42),
    "medium_[7,14,28,56]": (7, 14, 28, 56),
    "slower_[10,20,40,80]": (10, 20, 40, 80),
}

VOL_WINDOWS_DAYS = [10, 20, 30, 60]
RISK_BUDGETS = [0.20, 0.30, 0.40, 0.50, 0.60]


def run_lookback_sweep(
    df: pd.DataFrame,
    timeframe: str = "1d",
    vol_window: int = 20,
    target_vol: float = 0.40,
    max_leverage: float = 1.0,
    cost_model: Optional[CostModel] = None,
) -> pd.DataFrame:
    """Evaluate performance across candidate lookback sets."""
    costs = cost_model or CostModel.from_tier("realistic")
    rows = []

    for name, lb_set in LOOKBACK_SETS.items():
        df_sig = compute_momentum_signals(df, lookbacks=lb_set)
        df_sig = compute_realized_volatility(df_sig, timeframe=timeframe, window_bars=vol_window)
        df_sig = compute_target_weights(df_sig, target_vol=target_vol, max_leverage=max_leverage)

        sim = run_simulation(df_sig, f"sweep_lb_{name}", timeframe=timeframe, cost_model=costs)
        m = calculate_metrics(sim)

        rows.append({
            "lookback_set": name,
            "lookbacks": str(list(lb_set)),
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


def run_vol_window_sweep(
    df: pd.DataFrame,
    timeframe: str = "1d",
    lookbacks: Tuple[int, ...] = (5, 10, 21, 42),
    target_vol: float = 0.40,
    max_leverage: float = 1.0,
    cost_model: Optional[CostModel] = None,
) -> pd.DataFrame:
    """Evaluate performance across different rolling volatility lookback windows."""
    costs = cost_model or CostModel.from_tier("realistic")
    rows = []

    df_sig_base = compute_momentum_signals(df, lookbacks=lookbacks)

    for vw in VOL_WINDOWS_DAYS:
        df_sig = compute_realized_volatility(df_sig_base, timeframe=timeframe, window_bars=vw)
        df_sig = compute_target_weights(df_sig, target_vol=target_vol, max_leverage=max_leverage)

        sim = run_simulation(df_sig, f"sweep_vol_{vw}d", timeframe=timeframe, cost_model=costs)
        m = calculate_metrics(sim)

        rows.append({
            "vol_window_days": vw,
            "cagr": m["cagr"],
            "sharpe_ratio": m["sharpe_ratio"],
            "sortino_ratio": m["sortino_ratio"],
            "max_drawdown": m["max_drawdown"],
            "calmar_ratio": m["calmar_ratio"],
            "volatility": m["annualized_volatility"],
            "total_costs": m["total_costs"],
        })

    return pd.DataFrame(rows)


def run_risk_budget_sweep(
    df: pd.DataFrame,
    timeframe: str = "1d",
    lookbacks: Tuple[int, ...] = (5, 10, 21, 42),
    vol_window: int = 20,
    max_leverage: float = 1.0,
    cost_model: Optional[CostModel] = None,
) -> pd.DataFrame:
    """Evaluate performance across risk budgets (target volatilities)."""
    costs = cost_model or CostModel.from_tier("realistic")
    rows = []

    df_sig_base = compute_momentum_signals(df, lookbacks=lookbacks)
    df_sig_base = compute_realized_volatility(df_sig_base, timeframe=timeframe, window_bars=vol_window)

    for rb in RISK_BUDGETS:
        df_sig = compute_target_weights(df_sig_base, target_vol=rb, max_leverage=max_leverage)

        sim = run_simulation(df_sig, f"sweep_targetvol_{int(rb*100)}pct", timeframe=timeframe, cost_model=costs)
        m = calculate_metrics(sim)

        rows.append({
            "target_vol": rb,
            "cagr": m["cagr"],
            "realized_vol": m["annualized_volatility"],
            "sharpe_ratio": m["sharpe_ratio"],
            "max_drawdown": m["max_drawdown"],
            "calmar_ratio": m["calmar_ratio"],
            "avg_position_size": m["avg_position_size"],
            "total_costs": m["total_costs"],
        })

    return pd.DataFrame(rows)


def run_grid_sweep(
    df: pd.DataFrame,
    timeframe: str = "1d",
    cost_model: Optional[CostModel] = None,
) -> pd.DataFrame:
    """Execute full 2D grid: Lookback Sets x Vol Windows."""
    costs = cost_model or CostModel.from_tier("realistic")
    rows = []

    for lb_name, lb_set in LOOKBACK_SETS.items():
        df_sig = compute_momentum_signals(df, lookbacks=lb_set)
        for vw in VOL_WINDOWS_DAYS:
            df_vol = compute_realized_volatility(df_sig, timeframe=timeframe, window_bars=vw)
            df_wt = compute_target_weights(df_vol, target_vol=0.40, max_leverage=1.0)

            sim = run_simulation(df_wt, f"grid_{lb_name}_{vw}d", timeframe=timeframe, cost_model=costs)
            m = calculate_metrics(sim)

            rows.append({
                "lookback_set": lb_name,
                "vol_window": vw,
                "cagr": m["cagr"],
                "sharpe_ratio": m["sharpe_ratio"],
                "max_drawdown": m["max_drawdown"],
                "calmar_ratio": m["calmar_ratio"],
            })

    return pd.DataFrame(rows)
