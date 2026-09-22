#!/usr/bin/env python3
"""
compare_2026_all_strategies.py
==============================
Compares all key strategies and benchmarks across the exact same period:
January 1, 2026 to August 24, 2026, starting with ₹1,00,000 (1 Lakh).
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
import sys

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
sys.path.insert(0, str(BASE_DIR))

from scripts.run_gfs_concentrated_regime_backtest import (
    load_data_and_regimes,
    simulate_regime_concentrated_portfolio
)
from scripts.run_dynamic_allocation_research import (
    prepare_opportunity_dataset,
    run_simulation_engine
)

# 1. Load GFS data & simulate
signals_df, stock_date_lookup, all_trading_days, nifty_regime_map = load_data_and_regimes()

# Strategy 1: GFS 10-Position Weekly RSI + Regime Schedule 1
print("Simulating GFS 10-Position Regime Super-Compounder...")
res_gfs10, daily_gfs10, trades_gfs10 = simulate_regime_concentrated_portfolio(
    signals_subset=signals_df,
    stock_date_lookup=stock_date_lookup,
    all_trading_days=all_trading_days,
    nifty_regime_map=nifty_regime_map,
    capacity=10,
    ranking_method="weekly_rsi",
    regime_schedule="sch1",
    sector_restriction="none",
    cost_bps=25.0,
    start_date="2026-01-01",
    end_date="2026-08-24"
)
scale_gfs = 100_000.0 / 1_000_000.0
daily_gfs10["equity_scaled"] = daily_gfs10["equity"] * scale_gfs

# Strategy 2: GFS 15-Position 3M Return + Regime Schedule 1
print("Simulating GFS 15-Position Regime Compounder...")
res_gfs15, daily_gfs15, trades_gfs15 = simulate_regime_concentrated_portfolio(
    signals_subset=signals_df,
    stock_date_lookup=stock_date_lookup,
    all_trading_days=all_trading_days,
    nifty_regime_map=nifty_regime_map,
    capacity=15,
    ranking_method="ret_3m",
    regime_schedule="sch1",
    sector_restriction="none",
    cost_bps=25.0,
    start_date="2026-01-01",
    end_date="2026-08-24"
)
daily_gfs15["equity_scaled"] = daily_gfs15["equity"] * scale_gfs

# 2. Breakout / Retest Strategy Simulation
print("Preparing Breakout / Retest Dataset...")
opp_trades = prepare_opportunity_dataset()

# Load price dict for breakout simulation
conn = sqlite3.connect("data/indian_market.db")
daily_all = pd.read_sql("SELECT security_id, date, close FROM daily_ohlcv WHERE date >= '2026-01-01' ORDER BY date ASC;", conn)
conn.close()

calendar_days_2026 = sorted(daily_all["date"].unique())
price_dict = daily_all.set_index(["security_id", "date"])["close"].to_dict()

# Simulate Breakout Model A (Equal Weight, 15 slots)
print("Simulating Breakout Model A (Equal Weight 15 slots)...")
res_bo_a = run_simulation_engine(
    opp_trades,
    calendar_days_2026,
    price_dict,
    capacity=15,
    allocation_model="MODEL_A",
    ranking_col="rel_volume",
    ranking_ascending=False,
    max_concentration_pct=0.10,
    cash_reserve_pct=0.10,
    cost_bps=25.0,
    start_date="2026-01-01",
    end_date="2026-08-24"
)

# Simulate Breakout Model C (Relative Volume Weighted, 15 slots)
print("Simulating Breakout Model C (Rel Vol Weighted 15 slots)...")
res_bo_c = run_simulation_engine(
    opp_trades,
    calendar_days_2026,
    price_dict,
    capacity=15,
    allocation_model="MODEL_C_VOL",
    ranking_col="rel_volume",
    ranking_ascending=False,
    max_concentration_pct=0.10,
    cash_reserve_pct=0.10,
    cost_bps=25.0,
    start_date="2026-01-01",
    end_date="2026-08-24"
)

# 3. NIFTY 50 Benchmark
conn = sqlite3.connect("data/indian_market.db")
nifty_daily = pd.read_sql("SELECT date, open, close FROM daily_ohlcv WHERE security_id=2835 AND date >= '2026-01-01' ORDER BY date ASC;", conn)
conn.close()

nifty_open_start = nifty_daily["open"].iloc[0]
nifty_daily["equity_scaled"] = (nifty_daily["close"] / nifty_open_start) * 100_000.0
nifty_dd = ((nifty_daily["close"] - nifty_daily["close"].cummax()) / nifty_daily["close"].cummax() * 100.0).min()

scale_bo = 100_000.0 / 1_000_000.0
bo_a_end = res_bo_a["Ending Equity (₹)"] * scale_bo
bo_c_end = res_bo_c["Ending Equity (₹)"] * scale_bo

print("\n" + "="*95)
print("2026 HEAD-TO-HEAD COMPARISON (JANUARY 1, 2026 TO AUGUST 24, 2026)")
print("Starting Capital: ₹1,00,000 (1 Lakh)")
print("="*95)

strategies = [
    ("GFS 10-Slot + Regime Sch 1 (Weekly RSI)", daily_gfs10["equity_scaled"].iloc[-1], res_gfs10.get("max_drawdown", 0.0), len(trades_gfs10), daily_gfs10["equity_scaled"].tolist()),
    ("GFS 15-Slot + Regime Sch 1 (3M Return)", daily_gfs15["equity_scaled"].iloc[-1], res_gfs15.get("max_drawdown", 0.0), len(trades_gfs15), daily_gfs15["equity_scaled"].tolist()),
    ("Breakout/Retest (Model C - RelVol 15-Slot)", bo_c_end, res_bo_c["Max Drawdown (%)"], res_bo_c["Trades Taken"], (res_bo_c["Equity Curve"]["equity"] * scale_bo).tolist()),
    ("Breakout/Retest (Model A - Equal Wt 15-Slot)", bo_a_end, res_bo_a["Max Drawdown (%)"], res_bo_a["Trades Taken"], (res_bo_a["Equity Curve"]["equity"] * scale_bo).tolist()),
    ("NIFTY 50 Benchmark (Buy & Hold)", nifty_daily["equity_scaled"].iloc[-1], nifty_dd, 1, nifty_daily["equity_scaled"].tolist()),
]

for name, end_eq, mdd, num_tr, _ in strategies:
    ret_pct = (end_eq - 100_000.0) / 100_000.0 * 100.0
    net_inr = end_eq - 100_000.0
    print(f"{name:46} | End NAV: ₹{end_eq:>10,.2f} | P&L: {ret_pct:>+7.2f}% ({net_inr:>+9,.2f}) | MaxDD: {mdd:>6.2f}% | Trades: {num_tr}")

print("\nSaving comparison results...")
# Save daily comparison series to CSV for HTML inclusion
dates_comp = daily_gfs10["date"].tolist()
comp_df = pd.DataFrame({"date": dates_comp})
comp_df["gfs_10_regime"] = daily_gfs10["equity_scaled"].values
comp_df["gfs_15_regime"] = daily_gfs15["equity_scaled"].values

# Align breakout series
bo_c_eq_df = res_bo_c["Equity Curve"][["date", "equity"]].copy()
bo_c_eq_df["bo_c_relvol"] = bo_c_eq_df["equity"] * scale_bo
comp_df = comp_df.merge(bo_c_eq_df[["date", "bo_c_relvol"]], on="date", how="left").ffill()

bo_a_eq_df = res_bo_a["Equity Curve"][["date", "equity"]].copy()
bo_a_eq_df["bo_a_equal"] = bo_a_eq_df["equity"] * scale_bo
comp_df = comp_df.merge(bo_a_eq_df[["date", "bo_a_equal"]], on="date", how="left").ffill()

nifty_eq_df = nifty_daily[["date", "equity_scaled"]].rename(columns={"equity_scaled": "nifty_50"})
comp_df = comp_df.merge(nifty_eq_df, on="date", how="left").ffill()

comp_df.to_csv(BASE_DIR / "reports" / "strategy_comparison_2026.csv", index=False)
print("Saved comparison CSV.")
