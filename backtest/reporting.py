"""Chart generation and visualization reporting engine."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

BASE_DIR = Path(__file__).resolve().parent.parent
FIGURES_DIR = BASE_DIR / "reports" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

# Styling defaults
plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Helvetica", "Arial"]
plt.rcParams["axes.edgecolor"] = "#cccccc"
plt.rcParams["axes.linewidth"] = 0.8


def plot_baseline_equity_and_drawdown(eq_df: pd.DataFrame, save_path: Optional[Path] = None):
    """Figure 1: Baseline cumulative equity curve vs BTC Buy & Hold + Drawdown."""
    path = save_path or (FIGURES_DIR / "baseline_equity_and_drawdown.png")
    df = eq_df.copy()
    df["dt"] = pd.to_datetime(df["datetime_utc"])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [2.5, 1]})

    # Equity Curve
    ax1.plot(df["dt"], df["equity"], label="Momentum Strategy (Vol-Targeted 40%, 1x)", color="#1f77b4", lw=1.8)
    ax1.plot(df["dt"], df["benchmark_equity"], label="BTC Buy & Hold", color="#ff7f0e", lw=1.5, alpha=0.85, ls="--")
    ax1.set_yscale("log")
    ax1.set_ylabel("Portfolio Value ($ Log Scale)", fontsize=11)
    ax1.set_title("Bitcoin 4-Lookback Momentum Strategy: Cumulative Equity (2017 - 2026)", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper left", frameon=True)
    ax1.grid(True, alpha=0.3)

    # Annotate end values
    final_eq = df["equity"].iloc[-1]
    final_bench = df["benchmark_equity"].iloc[-1]
    ax1.annotate(f"${final_eq:,.0f} ({(final_eq/10000 - 1)*100:+.0f}%)", xy=(df["dt"].iloc[-1], final_eq),
                 xytext=(-120, 10), textcoords="offset points", fontweight="bold", color="#1f77b4")
    ax1.annotate(f"${final_bench:,.0f} ({(final_bench/10000 - 1)*100:+.0f}%)", xy=(df["dt"].iloc[-1], final_bench),
                 xytext=(-120, -15), textcoords="offset points", fontweight="bold", color="#ff7f0e")

    # Drawdown Chart
    bench_peak = df["benchmark_equity"].cummax()
    bench_dd = (df["benchmark_equity"] - bench_peak) / bench_peak

    ax2.fill_between(df["dt"], df["drawdown"] * 100, 0, color="#1f77b4", alpha=0.4, label="Strategy Drawdown")
    ax2.plot(df["dt"], bench_dd * 100, color="#ff7f0e", lw=1.0, alpha=0.7, label="BTC Buy & Hold Drawdown")
    ax2.set_ylabel("Drawdown (%)", fontsize=11)
    ax2.set_xlabel("Date", fontsize=11)
    ax2.set_ylim(-100, 5)
    ax2.legend(loc="lower left", frameon=True)
    ax2.grid(True, alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_leverage_comparison(leverage_dict: Dict[str, pd.DataFrame], save_path: Optional[Path] = None):
    """Figure 2: Cumulative equity curves for 1x, 2x, 3x, 5x leverage caps on 1D."""
    path = save_path or (FIGURES_DIR / "leverage_comparison.png")
    fig, ax = plt.subplots(figsize=(12, 6))

    colors = {"1x": "#1f77b4", "2x": "#2ca02c", "3x": "#d62728", "5x": "#9467bd"}

    for lev_label, df in leverage_dict.items():
        dt = pd.to_datetime(df["datetime_utc"])
        final_val = df["equity"].iloc[-1]
        ax.plot(dt, df["equity"], label=f"Leverage Cap {lev_label} (${final_val:,.0f})",
                color=colors.get(lev_label, "#333333"), lw=1.6)

    # Benchmark
    first_df = next(iter(leverage_dict.values()))
    ax.plot(pd.to_datetime(first_df["datetime_utc"]), first_df["benchmark_equity"],
            label="BTC Buy & Hold", color="#ff7f0e", lw=1.2, ls="--", alpha=0.8)

    ax.set_yscale("log")
    ax.set_ylabel("Portfolio Value ($ Log Scale)", fontsize=11)
    ax.set_xlabel("Date", fontsize=11)
    ax.set_title("Leverage Impact on Bitcoin Momentum Strategy (1x vs 2x vs 3x vs 5x)", fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", frameon=True)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_timeframe_comparison(
    tf_dict: Dict[str, pd.DataFrame],
    mode_name: str = "Time-Scaled",
    filename: str = "timeframe_comparison_scaled.png",
):
    """Figure 3 / Figure 4: Multi-timeframe equity curve comparison."""
    path = FIGURES_DIR / filename
    fig, ax = plt.subplots(figsize=(12, 6))

    colors = {"1d": "#1f77b4", "4h": "#2ca02c", "1h": "#ff7f0e", "15m": "#d62728", "5m": "#9467bd"}

    for tf, df in tf_dict.items():
        dt = pd.to_datetime(df["datetime_utc"])
        final_val = df["equity"].iloc[-1]
        # Downsample plotting points if massive for smooth rendering
        if len(df) > 5000:
            step = len(df) // 2000
            dt = dt.iloc[::step]
            eq = df["equity"].iloc[::step]
        else:
            eq = df["equity"]

        ax.plot(dt, eq, label=f"{tf.upper()} (${final_val:,.0f})", color=colors.get(tf, "#333333"), lw=1.5)

    ax.set_yscale("log")
    ax.set_ylabel("Portfolio Value ($ Log Scale)", fontsize=11)
    ax.set_xlabel("Date", fontsize=11)
    ax.set_title(f"Multi-Timeframe Performance Comparison ({mode_name} Lookbacks)", fontsize=14, fontweight="bold")
    ax.legend(loc="upper left", frameon=True)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_scaled_vs_raw_bar(
    summary_df: pd.DataFrame,
    save_path: Optional[Path] = None,
):
    """Figure 5: Side-by-side comparison of Sharpe and CAGR for Scaled vs Raw lookbacks."""
    path = save_path or (FIGURES_DIR / "scaled_vs_raw_timeframes.png")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    timeframes = [tf for tf in ["1d", "4h", "1h", "15m", "5m"] if tf in summary_df["timeframe"].values]
    x = np.arange(len(timeframes))
    width = 0.35

    scaled_sharpe = [summary_df[(summary_df["timeframe"] == tf) & (summary_df["mode"] == "time_scaled")]["sharpe_ratio"].values[0] for tf in timeframes]
    raw_sharpe = [summary_df[(summary_df["timeframe"] == tf) & (summary_df["mode"] == "raw")]["sharpe_ratio"].values[0] for tf in timeframes]

    scaled_cagr = [summary_df[(summary_df["timeframe"] == tf) & (summary_df["mode"] == "time_scaled")]["cagr"].values[0] * 100 for tf in timeframes]
    raw_cagr = [summary_df[(summary_df["timeframe"] == tf) & (summary_df["mode"] == "raw")]["cagr"].values[0] * 100 for tf in timeframes]

    # Sharpe subplot
    ax1.bar(x - width/2, scaled_sharpe, width, label="Time-Scaled Lookbacks", color="#1f77b4")
    ax1.bar(x + width/2, raw_sharpe, width, label="Raw Candle Lookbacks", color="#ff7f0e")
    ax1.set_ylabel("Sharpe Ratio (Net of Fees)", fontsize=11)
    ax1.set_title("Sharpe Ratio: Time-Scaled vs Raw", fontsize=12, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels([tf.upper() for tf in timeframes], fontsize=11)
    ax1.axhline(0, color="gray", lw=0.8)
    ax1.legend(loc="upper right", frameon=True)
    ax1.grid(True, alpha=0.3)

    # CAGR subplot
    ax2.bar(x - width/2, scaled_cagr, width, label="Time-Scaled Lookbacks", color="#1f77b4")
    ax2.bar(x + width/2, raw_cagr, width, label="Raw Candle Lookbacks", color="#ff7f0e")
    ax2.set_ylabel("CAGR (%)", fontsize=11)
    ax2.set_title("Annualized Return (CAGR): Time-Scaled vs Raw", fontsize=12, fontweight="bold")
    ax2.set_xticks(x)
    ax2.set_xticklabels([tf.upper() for tf in timeframes], fontsize=11)
    ax2.axhline(0, color="gray", lw=0.8)
    ax2.legend(loc="upper right", frameon=True)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_long_short_vs_long_only(
    ls_df: pd.DataFrame,
    lo_df: pd.DataFrame,
    save_path: Optional[Path] = None,
):
    """Figure 6: Long-Short vs Long-Only cumulative equity and drawdowns."""
    path = save_path or (FIGURES_DIR / "long_short_vs_long_only.png")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [2.5, 1]})

    dt_ls = pd.to_datetime(ls_df["datetime_utc"])
    dt_lo = pd.to_datetime(lo_df["datetime_utc"])

    ax1.plot(dt_ls, ls_df["equity"], label=f"Long-Short Momentum (${ls_df['equity'].iloc[-1]:,.0f})", color="#1f77b4", lw=1.8)
    ax1.plot(dt_lo, lo_df["equity"], label=f"Long-Only Momentum (${lo_df['equity'].iloc[-1]:,.0f})", color="#2ca02c", lw=1.8)
    ax1.plot(dt_ls, ls_df["benchmark_equity"], label=f"BTC Buy & Hold (${ls_df['benchmark_equity'].iloc[-1]:,.0f})", color="#ff7f0e", lw=1.2, ls="--", alpha=0.8)
    ax1.set_yscale("log")
    ax1.set_ylabel("Portfolio Value ($ Log Scale)", fontsize=11)
    ax1.set_title("Long-Short vs Long-Only Bitcoin Momentum (2017 - 2026)", fontsize=14, fontweight="bold")
    ax1.legend(loc="upper left", frameon=True)
    ax1.grid(True, alpha=0.3)

    # Drawdown
    ax2.plot(dt_ls, ls_df["drawdown"] * 100, label="Long-Short Drawdown", color="#1f77b4", lw=1.2)
    ax2.plot(dt_lo, lo_df["drawdown"] * 100, label="Long-Only Drawdown", color="#2ca02c", lw=1.2)
    ax2.set_ylabel("Drawdown (%)", fontsize=11)
    ax2.set_xlabel("Date", fontsize=11)
    ax2.set_ylim(-90, 5)
    ax2.legend(loc="lower left", frameon=True)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_cost_drag_by_timeframe(
    cost_summary_df: pd.DataFrame,
    save_path: Optional[Path] = None,
):
    """Figure 7: Cost drag across timeframes for Zero, Realistic, and Stress tiers."""
    path = save_path or (FIGURES_DIR / "cost_drag_by_timeframe.png")
    fig, ax = plt.subplots(figsize=(10, 6))

    pivot = cost_summary_df.pivot(index="timeframe", columns="tier", values="annual_cost_drag_pct")
    # Sort timeframes logically
    tf_order = [tf for tf in ["1d", "4h", "1h", "15m", "5m"] if tf in pivot.index]
    pivot = pivot.reindex(tf_order)

    pivot.plot(kind="bar", ax=ax, colormap="Blues", edgecolor="#333333", width=0.7)
    ax.set_ylabel("Annualized Cost Drag (% of Equity / Year)", fontsize=11)
    ax.set_xlabel("Candle Timeframe", fontsize=11)
    ax.set_title("Friction Penalty: Annual Cost Drag Across Timeframes & Cost Tiers", fontsize=13, fontweight="bold")
    ax.set_xticklabels([tf.upper() for tf in tf_order], rotation=0, fontsize=11)
    ax.legend(title="Cost Tier", frameon=True)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_robustness_heatmaps(
    grid_df: pd.DataFrame,
    lb_df: pd.DataFrame,
    save_path_lb: Optional[Path] = None,
    save_path_vol: Optional[Path] = None,
):
    """Figure 8 & Figure 9: Lookback parameter stability and Volatility window heatmaps."""
    # Fig 8: Lookback variation bar chart
    path_lb = save_path_lb or (FIGURES_DIR / "robustness_lookback_heatmap.png")
    fig1, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    lb_labels = [s.replace("_[", "\n[") for s in lb_df["lookback_set"]]
    x = np.arange(len(lb_labels))

    ax1.bar(x, lb_df["sharpe_ratio"], color="#1f77b4", edgecolor="#333333", width=0.55)
    ax1.set_ylabel("Sharpe Ratio", fontsize=11)
    ax1.set_title("Sharpe Ratio Across Lookback Variations", fontsize=12, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(lb_labels, fontsize=10)
    ax1.grid(True, alpha=0.3)

    ax2.bar(x, lb_df["cagr"] * 100, color="#2ca02c", edgecolor="#333333", width=0.55)
    ax2.set_ylabel("CAGR (%)", fontsize=11)
    ax2.set_title("CAGR Across Lookback Variations", fontsize=12, fontweight="bold")
    ax2.set_xticks(x)
    ax2.set_xticklabels(lb_labels, fontsize=10)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    fig1.savefig(path_lb, dpi=180)
    plt.close(fig1)

    # Fig 9: 2D Grid Heatmap (Lookback Set x Vol Window)
    path_vol = save_path_vol or (FIGURES_DIR / "robustness_vol_window_heatmap.png")
    fig2, ax = plt.subplots(figsize=(9, 6))

    pivot_sharpe = grid_df.pivot(index="lookback_set", columns="vol_window", values="sharpe_ratio")
    sns.heatmap(pivot_sharpe, annot=True, fmt=".3f", cmap="YlGnBu", ax=ax, cbar_kws={"label": "Sharpe Ratio"})
    ax.set_title("Parameter Stability Heatmap: Lookback Sets vs Volatility Lookback (Sharpe)", fontsize=13, fontweight="bold")
    ax.set_ylabel("Lookback Set", fontsize=11)
    ax.set_xlabel("Volatility Window (Days)", fontsize=11)

    plt.tight_layout()
    fig2.savefig(path_vol, dpi=180)
    plt.close(fig2)


def plot_regime_breakdown(regime_results: List[Dict[str, Any]], save_path: Optional[Path] = None):
    """Figure 10: Performance across historical market regimes (Bull, Bear, Sideways)."""
    path = save_path or (FIGURES_DIR / "regime_performance_breakdown.png")
    df = pd.DataFrame(regime_results)

    fig, ax = plt.subplots(figsize=(13, 6))
    x = np.arange(len(df))
    width = 0.38

    strat_rets = df["strategy_return"] * 100
    bench_rets = df["benchmark_return"] * 100

    ax.bar(x - width/2, strat_rets, width, label="Strategy Return (%)", color="#1f77b4", edgecolor="#333333")
    ax.bar(x + width/2, bench_rets, width, label="BTC Buy & Hold (%)", color="#ff7f0e", edgecolor="#333333")

    ax.set_ylabel("Regime Total Return (%)", fontsize=11)
    ax.set_title("Market Regime Performance: Strategy vs Bitcoin Buy & Hold (2017 - 2026)", fontsize=13, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(df["regime_name"], rotation=30, ha="right", fontsize=9)
    ax.axhline(0, color="gray", lw=0.8)
    ax.legend(loc="upper left", frameon=True)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_walk_forward_split(split_dict: Dict[str, Any], save_path: Optional[Path] = None):
    """Figure 11: In-Sample (2017-2021) vs Out-of-Sample (2022-2026) equity curves."""
    path = save_path or (FIGURES_DIR / "walk_forward_is_vs_oos.png")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    is_eq = split_dict["is_result"].equity_curve
    oos_eq = split_dict["oos_result"].equity_curve

    dt_is = pd.to_datetime(is_eq["datetime_utc"])
    dt_oos = pd.to_datetime(oos_eq["datetime_utc"])

    # In-Sample subplot
    ax1.plot(dt_is, is_eq["equity"], label=f"Strategy (${is_eq['equity'].iloc[-1]:,.0f})", color="#1f77b4", lw=1.8)
    ax1.plot(dt_is, is_eq["benchmark_equity"], label=f"BTC Buy & Hold (${is_eq['benchmark_equity'].iloc[-1]:,.0f})", color="#ff7f0e", lw=1.2, ls="--")
    ax1.set_yscale("log")
    ax1.set_ylabel("Portfolio Value ($ Log Scale)", fontsize=11)
    ax1.set_title(f"In-Sample (2017 - 2021) | Sharpe: {split_dict['is_metrics']['sharpe_ratio']:.2f}", fontsize=12, fontweight="bold")
    ax1.legend(loc="upper left", frameon=True)
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # Out-of-Sample subplot
    ax2.plot(dt_oos, oos_eq["equity"], label=f"Strategy (${oos_eq['equity'].iloc[-1]:,.0f})", color="#2ca02c", lw=1.8)
    ax2.plot(dt_oos, oos_eq["benchmark_equity"], label=f"BTC Buy & Hold (${oos_eq['benchmark_equity'].iloc[-1]:,.0f})", color="#ff7f0e", lw=1.2, ls="--")
    ax2.set_yscale("log")
    ax2.set_ylabel("Portfolio Value ($ Log Scale)", fontsize=11)
    ax2.set_title(f"Out-of-Sample (2022 - 2026) | Sharpe: {split_dict['oos_metrics']['sharpe_ratio']:.2f} (Degradation: {split_dict['sharpe_degradation']:.2f}x)", fontsize=12, fontweight="bold")
    ax2.legend(loc="upper left", frameon=True)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def plot_monthly_returns_heatmap(monthly_df: pd.DataFrame, save_path: Optional[Path] = None):
    """Figure 12: Heatmap matrix of monthly returns across years."""
    path = save_path or (FIGURES_DIR / "monthly_returns_heatmap.png")
    fig, ax = plt.subplots(figsize=(12, 6))

    pivot = monthly_df.pivot(index="year", columns="month", values="return_pct") * 100
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    pivot.columns = [month_names[m - 1] for m in pivot.columns]

    sns.heatmap(pivot, annot=True, fmt=".1f", cmap="RdYlGn", center=0.0, ax=ax, cbar_kws={"label": "Monthly Return (%)"})
    ax.set_title("Bitcoin Momentum Strategy: Monthly Returns (%) Matrix (2017 - 2026)", fontsize=13, fontweight="bold")
    ax.set_ylabel("Year", fontsize=11)
    ax.set_xlabel("Month", fontsize=11)

    plt.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
