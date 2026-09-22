"""Persistence module for storing backtest simulation runs into SQLite."""

from datetime import datetime, timezone
import json
import logging
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from backtest.data import get_results_db
from backtest.metrics import calculate_metrics, calculate_period_returns
from backtest.portfolio import SimulationResult

logger = logging.getLogger("backtest_persistence")


def _clean_float(val: any, default: float = 0.0) -> float:
    try:
        f = float(val)
        return f if np.isfinite(f) else default
    except (ValueError, TypeError):
        return default


def save_simulation_result(
    sim_result: SimulationResult,
    experiment_metadata: Dict[str, any],
    regime_results: Optional[List[Dict[str, any]]] = None,
    save_full_curve: bool = True,
):
    """Save experiment metadata, metrics, equity curve, and periodic returns into SQLite."""
    conn = get_results_db()
    exp_id = sim_result.experiment_id

    # 1. Calculate metrics if not already attached
    metrics = sim_result.metrics or calculate_metrics(sim_result)
    sim_result.metrics = metrics

    # 2. Monthly and yearly returns
    monthly_df, yearly_df = calculate_period_returns(sim_result.equity_curve)

    with conn:
        # Save experiments table
        conn.execute("""
            INSERT OR REPLACE INTO experiments (
                experiment_id, name, category, timeframe, lookbacks,
                leverage, volatility_lookback, target_volatility, sizing_mode,
                direction_mode, fee_rate, slippage_rate, borrow_rate_apr,
                start_datetime, end_datetime, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            exp_id,
            experiment_metadata.get("name", exp_id),
            experiment_metadata.get("category", "general"),
            sim_result.timeframe,
            json.dumps(experiment_metadata.get("lookbacks", [5, 10, 21, 42])),
            _clean_float(experiment_metadata.get("leverage", 1.0), 1.0),
            int(experiment_metadata.get("volatility_lookback", 20)),
            _clean_float(experiment_metadata.get("target_volatility", 0.40), 0.40),
            experiment_metadata.get("sizing_mode", "vol_targeted"),
            experiment_metadata.get("direction_mode", "long_short"),
            _clean_float(sim_result.cost_model.fee_rate),
            _clean_float(sim_result.cost_model.slippage_rate),
            _clean_float(sim_result.cost_model.borrow_rate_apr),
            str(sim_result.equity_curve["datetime_utc"].iloc[0]),
            str(sim_result.equity_curve["datetime_utc"].iloc[-1]),
            datetime.now(timezone.utc).isoformat(),
        ))

        # Save metrics table
        conn.execute("""
            INSERT OR REPLACE INTO metrics (
                experiment_id, total_return, cagr, annualized_volatility,
                sharpe_ratio, sortino_ratio, max_drawdown, calmar_ratio,
                win_rate, profit_factor, total_trades, turnover,
                total_fees, total_slippage, total_costs, exposure_pct,
                avg_position_size, avg_win_pct, avg_loss_pct,
                best_trade_pct, worst_trade_pct, longest_win_streak,
                longest_loss_streak, benchmark_total_return, benchmark_cagr,
                benchmark_sharpe, benchmark_max_drawdown, alpha_cagr
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            exp_id,
            _clean_float(metrics["total_return"]),
            _clean_float(metrics["cagr"]),
            _clean_float(metrics["annualized_volatility"]),
            _clean_float(metrics["sharpe_ratio"]),
            _clean_float(metrics["sortino_ratio"]),
            _clean_float(metrics["max_drawdown"]),
            _clean_float(metrics["calmar_ratio"]),
            _clean_float(metrics["win_rate"]),
            _clean_float(metrics["profit_factor"]),
            int(metrics["total_trades"]),
            _clean_float(metrics["turnover"]),
            _clean_float(metrics["total_fees"]),
            _clean_float(metrics["total_slippage"]),
            _clean_float(metrics["total_costs"]),
            _clean_float(metrics["exposure_pct"]),
            _clean_float(metrics["avg_position_size"]),
            _clean_float(metrics["avg_win_pct"]),
            _clean_float(metrics["avg_loss_pct"]),
            _clean_float(metrics["best_trade_pct"]),
            _clean_float(metrics["worst_trade_pct"]),
            int(metrics["longest_win_streak"]),
            int(metrics["longest_loss_streak"]),
            _clean_float(metrics["benchmark_total_return"]),
            _clean_float(metrics["benchmark_cagr"]),
            _clean_float(metrics["benchmark_sharpe"]),
            _clean_float(metrics["benchmark_max_drawdown"]),
            _clean_float(metrics["alpha_cagr"]),
        ))

        # Save monthly returns
        monthly_rows = [
            (exp_id, int(r["year"]), int(r["month"]), _clean_float(r["return_pct"]))
            for _, r in monthly_df.iterrows()
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO monthly_returns (experiment_id, year, month, return_pct)
            VALUES (?, ?, ?, ?);
        """, monthly_rows)

        # Save yearly returns
        yearly_rows = [
            (exp_id, int(r["year"]), _clean_float(r["return_pct"]))
            for _, r in yearly_df.iterrows()
        ]
        conn.executemany("""
            INSERT OR REPLACE INTO yearly_returns (experiment_id, year, return_pct)
            VALUES (?, ?, ?);
        """, yearly_rows)

        # Save regime metrics if provided
        if regime_results:
            regime_rows = [
                (
                    exp_id,
                    r["regime_name"],
                    r["period_start"],
                    r["period_end"],
                    _clean_float(r["strategy_return"]),
                    _clean_float(r["benchmark_return"]),
                    _clean_float(r["strategy_sharpe"]),
                    _clean_float(r["strategy_max_dd"]),
                )
                for r in regime_results
            ]
            conn.executemany("""
                INSERT OR REPLACE INTO regime_metrics (
                    experiment_id, regime_name, period_start, period_end,
                    strategy_return, benchmark_return, strategy_sharpe, strategy_max_dd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, regime_rows)

        # Save equity curves (downsample if very large, e.g. for 5m to 1h bars to keep db fast)
        if save_full_curve:
            eq_df = sim_result.equity_curve
            if len(eq_df) > 50_000:
                # Downsample equity curve to hourly intervals for storage efficiency
                sample_step = len(eq_df) // 10_000
                eq_df = eq_df.iloc[::sample_step].copy()

            eq_rows = [
                (
                    exp_id,
                    int(r["timestamp"]),
                    str(r["datetime_utc"]),
                    float(r["equity"]),
                    float(r["benchmark_equity"]),
                    float(r["cash"]),
                    float(r["position_weight"]),
                    float(r["drawdown"]),
                )
                for _, r in eq_df.iterrows()
            ]
            conn.executemany("""
                INSERT OR REPLACE INTO equity_curves (
                    experiment_id, timestamp, datetime_utc, equity,
                    benchmark_equity, cash, position_weight, drawdown
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, eq_rows)

    conn.close()
