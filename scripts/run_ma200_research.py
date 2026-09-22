"""Run comprehensive 1-hour 200 MA strategy research across 1x to 10x leverage."""

from pathlib import Path
import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backtest.data import load_candles
from backtest.ma200_strategy import (
    run_ma200_leverage_sweep,
    plot_ma200_leverage_curves,
    plot_best_worst_years,
    FIGURES_DIR,
)


def main():
    print("Loading 1h candles from SQLite...")
    df_1h = load_candles("1h")
    print(f"Loaded {len(df_1h):,} 1h bars (2017-08-17 to 2026-09-12).")

    # 1. Long-Short Sweep (Realistic Costs)
    print("\nExecuting Long-Short 200 SMA Sweep (1x to 10x)...")
    res_ls = run_ma200_leverage_sweep(df_1h, mode="long_short", cost_tier="realistic")
    plot_ma200_leverage_curves(res_ls, save_name="ma200_leverage_equity_curves.png")
    plot_best_worst_years(res_ls, save_name="ma200_best_worst_years.png")

    # 2. Long-Only Sweep (Realistic Costs)
    print("Executing Long-Only 200 SMA Sweep (1x to 10x)...")
    res_lo = run_ma200_leverage_sweep(df_1h, mode="long_only", cost_tier="realistic")
    plot_ma200_leverage_curves(res_lo, save_name="ma200_long_only_equity_curves.png")

    # 3. Print Comprehensive Tables
    print("\n" + "="*90)
    print("=== 1-HOUR 200 SMA STRATEGY: LONG-SHORT RESULTS (LEVERAGE 1x TO 10x) ===")
    print("="*90)
    ls_rows = []
    for r in res_ls:
        status = f"LIQ ({r.liquidation_datetime[:10]} @ ${r.liquidation_price:,.0f})" if r.is_liquidated else "Survived"
        ls_rows.append({
            "Leverage": f"{int(r.leverage)}x",
            "CAGR (%)": f"{r.cagr*100:6.2f}%" if not r.is_liquidated else "-100.0%",
            "Sharpe": f"{r.sharpe_ratio:5.2f}",
            "Sortino": f"{r.sortino_ratio:5.2f}",
            "MaxDD (%)": f"{r.max_drawdown*100:6.1f}%",
            "Final ($)": f"${r.final_equity:10.2f}",
            "Best Year": f"{r.best_year[0]}: {r.best_year[1]*100:+6.1f}%",
            "Worst Year": f"{r.worst_year[0]}: {r.worst_year[1]*100:+6.1f}%",
            "Turnover": f"{r.turnover:5.1f}x",
            "Total Costs ($)": f"${r.total_costs:8.2f}",
            "Status": status,
        })
    print(pd.DataFrame(ls_rows).to_string(index=False))

    print("\n" + "="*90)
    print("=== 1-HOUR 200 SMA STRATEGY: LONG-ONLY RESULTS (LEVERAGE 1x TO 10x) ===")
    print("="*90)
    lo_rows = []
    for r in res_lo:
        status = f"LIQ ({r.liquidation_datetime[:10]} @ ${r.liquidation_price:,.0f})" if r.is_liquidated else "Survived"
        lo_rows.append({
            "Leverage": f"{int(r.leverage)}x",
            "CAGR (%)": f"{r.cagr*100:6.2f}%" if not r.is_liquidated else "-100.0%",
            "Sharpe": f"{r.sharpe_ratio:5.2f}",
            "Sortino": f"{r.sortino_ratio:5.2f}",
            "MaxDD (%)": f"{r.max_drawdown*100:6.1f}%",
            "Final ($)": f"${r.final_equity:10.2f}",
            "Best Year": f"{r.best_year[0]}: {r.best_year[1]*100:+6.1f}%",
            "Worst Year": f"{r.worst_year[0]}: {r.worst_year[1]*100:+6.1f}%",
            "Turnover": f"{r.turnover:5.1f}x",
            "Total Costs ($)": f"${r.total_costs:8.2f}",
            "Status": status,
        })
    print(pd.DataFrame(lo_rows).to_string(index=False))

    # 4. Year-by-Year Breakdown Matrix for Long-Short
    print("\n" + "="*90)
    print("=== YEAR-BY-YEAR RETURNS MATRIX: LONG-SHORT (2017 - 2026) ===")
    print("="*90)
    yr_dict_ls = {}
    for r in res_ls:
        col_name = f"{int(r.leverage)}x"
        yr_dict_ls[col_name] = r.yearly_returns.set_index("year")["return_pct"] * 100
    df_yr_ls = pd.DataFrame(yr_dict_ls)
    print(df_yr_ls.to_string())

    # 5. Year-by-Year Breakdown Matrix for Long-Only
    print("\n" + "="*90)
    print("=== YEAR-BY-YEAR RETURNS MATRIX: LONG-ONLY (2017 - 2026) ===")
    print("="*90)
    yr_dict_lo = {}
    for r in res_lo:
        col_name = f"{int(r.leverage)}x"
        yr_dict_lo[col_name] = r.yearly_returns.set_index("year")["return_pct"] * 100
    df_yr_lo = pd.DataFrame(yr_dict_lo)
    print(df_yr_lo.to_string())

    # Generate Yearly Heatmap
    fig, ax = plt.subplots(figsize=(12, 6))
    sns.heatmap(df_yr_lo, annot=True, fmt=".1f", cmap="RdYlGn", center=0.0, ax=ax, cbar_kws={"label": "Yearly Return (%)"})
    ax.set_title("1-Hour 200 SMA Long-Only Strategy: Annual Return (%) by Leverage (1x to 10x)", fontsize=13, fontweight="bold")
    ax.set_ylabel("Year", fontsize=11)
    ax.set_xlabel("Leverage Tier", fontsize=11)
    plt.tight_layout()
    fig.savefig(FIGURES_DIR / "ma200_yearly_heatmap.png", dpi=180)
    plt.close(fig)

    print("\nSaved all figures to reports/figures/ successfully.")


if __name__ == "__main__":
    main()
