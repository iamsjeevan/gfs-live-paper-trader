"""Comprehensive performance, risk, and trade metric calculations."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from backtest.portfolio import SimulationResult, TradeRecord
from backtest.volatility import ANNUAL_PERIODS


def calculate_metrics(sim_result: SimulationResult) -> Dict[str, Any]:
    """Calculate all standard performance, risk, and trade metrics.

    Metrics include:
    - Total return, CAGR, Annualized Volatility, Sharpe Ratio, Sortino Ratio
    - Maximum Drawdown, Calmar Ratio
    - Win rate, Profit Factor, Total trades, Win/Loss streaks, Best/Worst trades
    - Turnover, Exposure %, Average position size
    - Fee, Slippage, Borrow cost totals
    - Benchmark comparison (Total return, CAGR, Sharpe, Max Drawdown, Alpha)
    """
    eq_df = sim_result.equity_curve
    timeframe = sim_result.timeframe.lower()
    ann_periods = ANNUAL_PERIODS.get(timeframe, 365)

    initial_capital = sim_result.initial_capital
    ending_equity = float(eq_df["equity"].iloc[-1])
    benchmark_ending = float(eq_df["benchmark_equity"].iloc[-1])

    # Duration in calendar years
    start_dt = pd.to_datetime(eq_df["datetime_utc"].iloc[0], utc=True)
    end_dt = pd.to_datetime(eq_df["datetime_utc"].iloc[-1], utc=True)
    days_elapsed = (end_dt - start_dt).total_seconds() / 86400.0
    years_elapsed = max(days_elapsed / 365.25, 0.01)

    # Strategy Returns
    total_return = (ending_equity - initial_capital) / initial_capital
    cagr = (ending_equity / initial_capital) ** (1.0 / years_elapsed) - 1.0 if ending_equity > 0 else -1.0

    # Benchmark Returns
    bench_start = float(eq_df["benchmark_equity"].iloc[0])
    bench_total_return = (benchmark_ending - bench_start) / bench_start
    bench_cagr = (benchmark_ending / bench_start) ** (1.0 / years_elapsed) - 1.0 if benchmark_ending > 0 else -1.0

    # Period returns
    eq_series = eq_df["equity"]
    bench_series = eq_df["benchmark_equity"]
    
    # Avoid zero division
    pct_returns = eq_series.pct_change().dropna().replace([np.inf, -np.inf], 0.0)
    bench_pct_returns = bench_series.pct_change().dropna().replace([np.inf, -np.inf], 0.0)

    # Annualized Volatility
    vol = pct_returns.std(ddof=1) * np.sqrt(ann_periods) if len(pct_returns) > 1 else 0.0
    bench_vol = bench_pct_returns.std(ddof=1) * np.sqrt(ann_periods) if len(bench_pct_returns) > 1 else 0.0

    # Sharpe Ratio (Rf = 0%)
    mean_ret = pct_returns.mean() * ann_periods
    sharpe = (mean_ret / vol) if vol > 1e-8 else 0.0

    bench_mean_ret = bench_pct_returns.mean() * ann_periods
    bench_sharpe = (bench_mean_ret / bench_vol) if bench_vol > 1e-8 else 0.0

    # Downside Deviation and Sortino Ratio (MAR = 0%)
    downside_returns = pct_returns[pct_returns < 0.0]
    downside_std = np.sqrt(np.mean(downside_returns ** 2)) * np.sqrt(ann_periods) if len(downside_returns) > 0 else 0.0
    sortino = (mean_ret / downside_std) if downside_std > 1e-8 else (100.0 if mean_ret > 0 else 0.0)

    # Maximum Drawdown
    max_dd = float(eq_df["drawdown"].min())  # negative number, e.g. -0.25 for -25%
    
    bench_peak = bench_series.cummax()
    bench_dd = (bench_series - bench_peak) / bench_peak
    bench_max_dd = float(bench_dd.min())

    # Calmar Ratio (CAGR / |MaxDD|)
    calmar = (cagr / abs(max_dd)) if abs(max_dd) > 1e-6 else 0.0

    # Cost totals
    total_fees = float(eq_df["fee"].sum())
    total_slippage = float(eq_df["slippage"].sum())
    total_borrow = float(eq_df["borrow_cost"].sum())
    total_costs = total_fees + total_slippage + total_borrow

    # Exposure and Average Position Size
    abs_weights = eq_df["position_weight"].abs()
    in_market_bars = (abs_weights > 1e-4).sum()
    exposure_pct = float(in_market_bars / len(eq_df))
    avg_position_size = float(abs_weights[abs_weights > 1e-4].mean()) if in_market_bars > 0 else 0.0

    # Turnover
    # Traded dollars / average equity / years
    total_traded_dollars = sum(t.traded_dollars for t in sim_result.trades)
    avg_equity = float(eq_df["equity"].mean())
    turnover = (total_traded_dollars / avg_equity / years_elapsed) if avg_equity > 0 else 0.0

    # Trade-level statistics
    trades = sim_result.trades
    total_trades = len(trades)
    pnls = [t.realized_pnl for t in trades if abs(t.realized_pnl) > 1e-6]
    return_pcts = [t.return_pct for t in trades if abs(t.return_pct) > 1e-6]

    winning_trades = [p for p in pnls if p > 0]
    losing_trades = [p for p in pnls if p < 0]

    win_count = len(winning_trades)
    loss_count = len(losing_trades)
    evaluated_trades = win_count + loss_count
    win_rate = (win_count / evaluated_trades) if evaluated_trades > 0 else 0.0

    gross_profit = sum(winning_trades)
    gross_loss = abs(sum(losing_trades))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 1e-6 else (999.0 if gross_profit > 0 else 0.0)

    win_returns = [r for r in return_pcts if r > 0]
    loss_returns = [r for r in return_pcts if r < 0]
    avg_win_pct = float(np.mean(win_returns)) if win_returns else 0.0
    avg_loss_pct = float(np.mean(loss_returns)) if loss_returns else 0.0
    best_trade_pct = float(max(return_pcts)) if return_pcts else 0.0
    worst_trade_pct = float(min(return_pcts)) if return_pcts else 0.0

    # Streaks
    longest_win_streak = 0
    longest_loss_streak = 0
    curr_win_streak = 0
    curr_loss_streak = 0

    for p in pnls:
        if p > 0:
            curr_win_streak += 1
            curr_loss_streak = 0
            longest_win_streak = max(longest_win_streak, curr_win_streak)
        elif p < 0:
            curr_loss_streak += 1
            curr_win_streak = 0
            longest_loss_streak = max(longest_loss_streak, curr_loss_streak)

    # Alpha CAGR
    alpha_cagr = cagr - bench_cagr

    metrics = {
        "total_return": total_return,
        "cagr": cagr,
        "annualized_volatility": vol,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": max_dd,
        "calmar_ratio": calmar,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_trades": total_trades,
        "turnover": turnover,
        "total_fees": total_fees,
        "total_slippage": total_slippage,
        "total_costs": total_costs,
        "exposure_pct": exposure_pct,
        "avg_position_size": avg_position_size,
        "avg_win_pct": avg_win_pct,
        "avg_loss_pct": avg_loss_pct,
        "best_trade_pct": best_trade_pct,
        "worst_trade_pct": worst_trade_pct,
        "longest_win_streak": longest_win_streak,
        "longest_loss_streak": longest_loss_streak,
        "benchmark_total_return": bench_total_return,
        "benchmark_cagr": bench_cagr,
        "benchmark_sharpe": bench_sharpe,
        "benchmark_max_drawdown": bench_max_dd,
        "alpha_cagr": alpha_cagr,
    }

    return metrics


def calculate_period_returns(eq_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate monthly and yearly returns tables from equity curve."""
    df = eq_df.copy()
    if "timestamp" in df.columns:
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    else:
        df["datetime"] = pd.to_datetime(df["datetime_utc"], utc=True)
    df = df.set_index("datetime")

    # Monthly resampling: take last equity of each month
    monthly_eq = df["equity"].resample("ME").last().dropna()
    monthly_ret = monthly_eq.pct_change()
    
    # First month return from initial equity
    if len(monthly_eq) > 0:
        first_m_idx = monthly_eq.index[0]
        init_eq = df["equity"].iloc[0]
        monthly_ret.iloc[0] = (monthly_eq.iloc[0] - init_eq) / init_eq if init_eq > 0 else 0.0

    monthly_ret = monthly_ret.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    monthly_rows = []
    for dt, ret in monthly_ret.items():
        val = float(ret) if np.isfinite(ret) else 0.0
        monthly_rows.append({
            "year": dt.year,
            "month": dt.month,
            "return_pct": val,
        })
    monthly_df = pd.DataFrame(monthly_rows)

    # Yearly resampling
    yearly_eq = df["equity"].resample("YE").last().dropna()
    yearly_ret = yearly_eq.pct_change()
    if len(yearly_eq) > 0:
        init_eq = df["equity"].iloc[0]
        yearly_ret.iloc[0] = (yearly_eq.iloc[0] - init_eq) / init_eq if init_eq > 0 else 0.0

    yearly_ret = yearly_ret.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    yearly_rows = []
    for dt, ret in yearly_ret.items():
        val = float(ret) if np.isfinite(ret) else 0.0
        yearly_rows.append({
            "year": dt.year,
            "return_pct": val,
        })
    yearly_df = pd.DataFrame(yearly_rows)

    return monthly_df, yearly_df
