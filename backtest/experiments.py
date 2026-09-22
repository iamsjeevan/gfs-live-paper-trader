"""Master backtesting orchestration suite covering Parts 1 through 13."""

import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from backtest.costs import CostModel
from backtest.data import get_results_db, init_results_db, load_candles
from backtest.latency import run_latency_sensitivity
from backtest.metrics import calculate_metrics, calculate_period_returns
from backtest.persistence import save_simulation_result
from backtest.portfolio import run_simulation, SimulationResult
from backtest.regimes import evaluate_regimes
from backtest.reporting import (
    plot_baseline_equity_and_drawdown,
    plot_cost_drag_by_timeframe,
    plot_leverage_comparison,
    plot_long_short_vs_long_only,
    plot_monthly_returns_heatmap,
    plot_regime_breakdown,
    plot_robustness_heatmaps,
    plot_scaled_vs_raw_bar,
    plot_timeframe_comparison,
    plot_walk_forward_split,
)
from backtest.robustness import (
    run_grid_sweep,
    run_lookback_sweep,
    run_risk_budget_sweep,
    run_vol_window_sweep,
)
from backtest.signals import compute_momentum_signals, get_lookbacks
from backtest.sizing import compute_target_weights
from backtest.volatility import compute_realized_volatility
from backtest.walk_forward import run_rolling_walk_forward, run_split_validation

logger = logging.getLogger("backtest_experiments")


def run_single_experiment(
    timeframe: str = "1d",
    lookback_mode: str = "time_scaled",
    base_lookbacks: Tuple[int, ...] = (5, 10, 21, 42),
    vol_window_days: int = 20,
    target_vol: float = 0.40,
    max_leverage: float = 1.0,
    sizing_mode: str = "vol_targeted",
    direction_mode: str = "long_short",
    cost_tier: str = "realistic",
    experiment_id: Optional[str] = None,
    category: str = "general",
    df_candles: Optional[pd.DataFrame] = None,
) -> Tuple[SimulationResult, Dict[str, Any]]:
    """Execute a single backtest configuration and calculate all metrics."""
    df = df_candles if df_candles is not None else load_candles(timeframe)
    costs = CostModel.from_tier(cost_tier)

    # Convert lookbacks according to mode
    lookbacks = get_lookbacks(timeframe, mode=lookback_mode, base_days=base_lookbacks)

    # Volatility window
    bars_per_day = {
        "1d": 1, "4h": 6, "1h": 24, "15m": 96, "5m": 288
    }.get(timeframe.lower(), 1)
    vol_window_bars = vol_window_days * bars_per_day if lookback_mode == "time_scaled" else vol_window_days

    # Signal & Sizing Pipeline
    df_sig = compute_momentum_signals(df, lookbacks=lookbacks)
    df_sig = compute_realized_volatility(df_sig, timeframe=timeframe, window_bars=vol_window_bars)
    df_sig = compute_target_weights(
        df_sig,
        target_vol=target_vol,
        max_leverage=max_leverage,
        sizing_mode=sizing_mode,
        direction_mode=direction_mode,
    )

    exp_id = experiment_id or f"{timeframe}_{lookback_mode}_lev{max_leverage}_{cost_tier}_{direction_mode}"

    sim = run_simulation(
        df_sig,
        experiment_id=exp_id,
        timeframe=timeframe,
        initial_capital=10_000.0,
        cost_model=costs,
    )
    metrics = calculate_metrics(sim)
    sim.metrics = metrics

    meta = {
        "name": exp_id,
        "category": category,
        "timeframe": timeframe,
        "lookback_mode": lookback_mode,
        "lookbacks": lookbacks,
        "leverage": max_leverage,
        "volatility_lookback": vol_window_bars,
        "target_volatility": target_vol,
        "sizing_mode": sizing_mode,
        "direction_mode": direction_mode,
        "cost_tier": cost_tier,
    }

    return sim, meta


def run_full_research_suite(candle_cache: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, Any]:
    """Execute all research experiments across Parts 1-13 and generate charts."""
    logger.info("Initializing SQLite Results Database...")
    db_conn = get_results_db()
    init_results_db(db_conn)
    db_conn.close()

    # Preload candles into cache
    cache = candle_cache or {}
    for tf in ["1d", "4h", "1h", "15m", "5m"]:
        if tf not in cache:
            logger.info(f"Loading {tf} candles...")
            cache[tf] = load_candles(tf)

    results: Dict[str, Any] = {}

    # =========================================================================
    # PART 2 & 10: Baseline 1D Strategy and Benchmarks
    # =========================================================================
    logger.info("=== Running Part 2 & 10: Baseline 1D and Benchmarks ===")
    sim_baseline, meta_baseline = run_single_experiment(
        timeframe="1d",
        lookback_mode="time_scaled",
        max_leverage=1.0,
        sizing_mode="vol_targeted",
        direction_mode="long_short",
        cost_tier="realistic",
        experiment_id="baseline_1d_vol_targeted_1x",
        category="baseline",
        df_candles=cache["1d"],
    )
    regime_results = evaluate_regimes(sim_baseline.equity_curve, timeframe="1d")
    save_simulation_result(sim_baseline, meta_baseline, regime_results=regime_results)
    results["baseline_1d"] = sim_baseline
    results["regimes"] = regime_results

    # Benchmarks on 1D:
    # 1. Buy & Hold
    sim_bh, meta_bh = run_single_experiment(
        timeframe="1d", sizing_mode="buy_and_hold", max_leverage=1.0,
        experiment_id="benchmark_btc_buy_and_hold", category="benchmark", df_candles=cache["1d"]
    )
    save_simulation_result(sim_bh, meta_bh)
    results["benchmark_buy_and_hold"] = sim_bh

    # 2. Unscaled Momentum (1x)
    sim_unscaled, meta_unscaled = run_single_experiment(
        timeframe="1d", sizing_mode="unscaled", max_leverage=1.0,
        experiment_id="benchmark_unscaled_momentum_1x", category="benchmark", df_candles=cache["1d"]
    )
    save_simulation_result(sim_unscaled, meta_unscaled)
    results["benchmark_unscaled"] = sim_unscaled

    # 3. Binary Unscaled Momentum
    sim_bin_unscaled, meta_bin = run_single_experiment(
        timeframe="1d", sizing_mode="binary_unscaled", max_leverage=1.0,
        experiment_id="benchmark_binary_unscaled_1x", category="benchmark", df_candles=cache["1d"]
    )
    save_simulation_result(sim_bin_unscaled, meta_bin)
    results["benchmark_binary_unscaled"] = sim_bin_unscaled

    # =========================================================================
    # PART 3: Leverage Variations (1x, 2x, 3x, 5x on 1D)
    # =========================================================================
    logger.info("=== Running Part 3: Leverage Variations on 1D ===")
    leverage_results: Dict[str, SimulationResult] = {"1x": sim_baseline}
    for lev in [2.0, 3.0, 5.0]:
        sim_lev, meta_lev = run_single_experiment(
            timeframe="1d",
            max_leverage=lev,
            sizing_mode="vol_targeted",
            direction_mode="long_short",
            cost_tier="realistic",
            experiment_id=f"leverage_1d_{int(lev)}x",
            category="leverage_comparison",
            df_candles=cache["1d"],
        )
        save_simulation_result(sim_lev, meta_lev)
        leverage_results[f"{int(lev)}x"] = sim_lev
    results["leverage_dict"] = leverage_results

    # =========================================================================
    # PART 4 & 5: Multi-Timeframe Comparison & Timeframe x Leverage Grid
    # =========================================================================
    logger.info("=== Running Part 4 & 5: Timeframes (Scaled vs Raw) x Leverage Grid ===")
    timeframes = ["1d", "4h", "1h", "15m", "5m"]
    tf_scaled_dict: Dict[str, SimulationResult] = {}
    tf_raw_dict: Dict[str, SimulationResult] = {}
    grid_rows = []

    for tf in timeframes:
        for mode in ["time_scaled", "raw"]:
            for lev in [1.0, 2.0, 3.0, 5.0]:
                exp_id = f"tf_grid_{tf}_{mode}_lev{int(lev)}x"
                sim_tf, meta_tf = run_single_experiment(
                    timeframe=tf,
                    lookback_mode=mode,
                    max_leverage=lev,
                    sizing_mode="vol_targeted",
                    direction_mode="long_short",
                    cost_tier="realistic",
                    experiment_id=exp_id,
                    category="timeframe_leverage_grid",
                    df_candles=cache[tf],
                )
                save_simulation_result(sim_tf, meta_tf, save_full_curve=(lev == 1.0))
                m = sim_tf.metrics

                grid_rows.append({
                    "timeframe": tf,
                    "mode": mode,
                    "leverage": lev,
                    "cagr": m["cagr"],
                    "sharpe_ratio": m["sharpe_ratio"],
                    "sortino_ratio": m["sortino_ratio"],
                    "max_drawdown": m["max_drawdown"],
                    "calmar_ratio": m["calmar_ratio"],
                    "win_rate": m["win_rate"],
                    "profit_factor": m["profit_factor"],
                    "turnover": m["turnover"],
                    "total_costs": m["total_costs"],
                    "exposure_pct": m["exposure_pct"],
                })

                if lev == 1.0:
                    if mode == "time_scaled":
                        tf_scaled_dict[tf] = sim_tf
                    else:
                        tf_raw_dict[tf] = sim_tf

    grid_summary_df = pd.DataFrame(grid_rows)
    results["grid_summary"] = grid_summary_df
    results["tf_scaled_dict"] = tf_scaled_dict
    results["tf_raw_dict"] = tf_raw_dict

    # =========================================================================
    # PART 6: Execution Latency Sensitivity
    # =========================================================================
    logger.info("=== Running Part 6: Execution Latency Sensitivity ===")
    latency_df = run_latency_sensitivity(cache["1d"], timeframe="1d", cost_model=CostModel.from_tier("realistic"))
    results["latency_df"] = latency_df

    # =========================================================================
    # PART 7: Parameter Sensitivity / Robustness Sweeps
    # =========================================================================
    logger.info("=== Running Part 7: Robustness Sweeps ===")
    lb_sweep_df = run_lookback_sweep(cache["1d"], timeframe="1d")
    vol_sweep_df = run_vol_window_sweep(cache["1d"], timeframe="1d")
    risk_sweep_df = run_risk_budget_sweep(cache["1d"], timeframe="1d")
    param_grid_df = run_grid_sweep(cache["1d"], timeframe="1d")

    results["lb_sweep_df"] = lb_sweep_df
    results["vol_sweep_df"] = vol_sweep_df
    results["risk_sweep_df"] = risk_sweep_df
    results["param_grid_df"] = param_grid_df

    # =========================================================================
    # PART 8: Long-Short vs Long-Only Comparison
    # =========================================================================
    logger.info("=== Running Part 8: Long-Short vs Long-Only ===")
    sim_long_only, meta_lo = run_single_experiment(
        timeframe="1d",
        lookback_mode="time_scaled",
        max_leverage=1.0,
        sizing_mode="vol_targeted",
        direction_mode="long_only",
        cost_tier="realistic",
        experiment_id="momentum_long_only_1d_1x",
        category="long_only_comparison",
        df_candles=cache["1d"],
    )
    save_simulation_result(sim_long_only, meta_lo)
    results["sim_long_only"] = sim_long_only

    # =========================================================================
    # PART 9: Cost Analysis across Tiers & Timeframes
    # =========================================================================
    logger.info("=== Running Part 9: Cost Analysis Across Tiers ===")
    cost_rows = []
    for tf in ["1d", "4h", "1h", "15m", "5m"]:
        for tier in ["zero", "realistic", "stress"]:
            sim_c, _ = run_single_experiment(
                timeframe=tf,
                lookback_mode="time_scaled",
                max_leverage=1.0,
                cost_tier=tier,
                experiment_id=f"cost_eval_{tf}_{tier}",
                category="cost_analysis",
                df_candles=cache[tf],
            )
            m = sim_c.metrics
            annual_cost_drag = (m["total_costs"] / sim_baseline.initial_capital) / 9.07 * 100
            cost_rows.append({
                "timeframe": tf,
                "tier": tier,
                "cagr": m["cagr"],
                "sharpe_ratio": m["sharpe_ratio"],
                "total_costs": m["total_costs"],
                "turnover": m["turnover"],
                "annual_cost_drag_pct": annual_cost_drag,
            })
    cost_summary_df = pd.DataFrame(cost_rows)
    results["cost_summary_df"] = cost_summary_df

    # =========================================================================
    # PART 12: Walk-Forward & Out-of-Sample Validation
    # =========================================================================
    logger.info("=== Running Part 12: Walk-Forward & Out-of-Sample Validation ===")
    split_results = run_split_validation(cache["1d"], split_date="2022-01-01 00:00:00", timeframe="1d")
    rolling_wf_results = run_rolling_walk_forward(cache["1d"], train_bars=730, test_bars=365, timeframe="1d")
    results["split_results"] = split_results
    results["rolling_wf_results"] = rolling_wf_results

    # =========================================================================
    # PART 14: Generate All 12 Visualizations
    # =========================================================================
    logger.info("=== Generating All 12 Visualizations ===")
    plot_baseline_equity_and_drawdown(sim_baseline.equity_curve)
    plot_leverage_comparison({k: v.equity_curve for k, v in leverage_results.items()})
    plot_timeframe_comparison({k: v.equity_curve for k, v in tf_scaled_dict.items()}, mode_name="Time-Scaled", filename="timeframe_comparison_scaled.png")
    plot_timeframe_comparison({k: v.equity_curve for k, v in tf_raw_dict.items()}, mode_name="Raw", filename="timeframe_comparison_raw.png")
    plot_scaled_vs_raw_bar(grid_summary_df[grid_summary_df["leverage"] == 1.0])
    plot_long_short_vs_long_only(sim_baseline.equity_curve, sim_long_only.equity_curve)
    plot_cost_drag_by_timeframe(cost_summary_df)
    plot_robustness_heatmaps(param_grid_df, lb_sweep_df)
    plot_regime_breakdown(regime_results)
    plot_walk_forward_split(split_results)

    monthly_df, _ = calculate_period_returns(sim_baseline.equity_curve)
    plot_monthly_returns_heatmap(monthly_df)

    logger.info("Research suite completed successfully!")
    return results
