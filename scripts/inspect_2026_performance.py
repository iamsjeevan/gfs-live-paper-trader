#!/usr/bin/env python3
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

signals_df, stock_date_lookup, all_trading_days, nifty_regime_map = load_data_and_regimes()

# Scenario A: Starting fresh with 1 Lakh on 2026-01-01
print("\n" + "="*80)
print("SCENARIO A: Starting fresh on 2026-01-01 with ₹1,00,000 (1 Lakh)")
print("="*80)

summary_2026, daily_df_2026, trades_df_2026 = simulate_regime_concentrated_portfolio(
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

scale = 100_000.0 / 1_000_000.0
daily_df_2026["equity_scaled"] = daily_df_2026["equity"] * scale
daily_df_2026["cash_scaled"] = daily_df_2026["cash"] * scale

start_eq = daily_df_2026["equity_scaled"].iloc[0]
end_eq = daily_df_2026["equity_scaled"].iloc[-1]
peak_eq = daily_df_2026["equity_scaled"].max()
min_eq = daily_df_2026["equity_scaled"].min()
total_ret_pct = (end_eq - start_eq) / start_eq * 100.0
max_dd = summary_2026.get("max_drawdown", 0.0)

print(f"Starting Capital (Jan 1, 2026): ₹{start_eq:,.2f}")
print(f"Ending Capital (Aug 24, 2026):   ₹{end_eq:,.2f}")
print(f"Net Profit:                      ₹{end_eq - start_eq:,.2f}")
print(f"Total Return (Jan - Aug 2026):   {total_ret_pct:+.2f}%")
print(f"Peak Portfolio Equity:           ₹{peak_eq:,.2f}")
print(f"Maximum Drawdown in 2026:        {max_dd:.2f}%")
print(f"Total Trades Closed in 2026:     {len(trades_df_2026)}")

print("\n--- CLOSED TRADES IN 2026 (Fresh Start) ---")
if not trades_df_2026.empty:
    for idx, r in trades_df_2026.iterrows():
        print(f"Trade {idx+1}: {r['symbol']} ({r['sector']}) | Entry: {r['entry_date']} @ ₹{r['raw_entry_price']:.2f} | Exit: {r['exit_date']} @ ₹{r['raw_exit_price']:.2f} | P&L: {r['return_pct']:+.2f}% | Held: {r['holding_days']} days")
else:
    print("No trades closed yet (positions held across months).")

# Scenario B: Continuous run from 2018 to 2026, and inspect the 2026 portion
print("\n" + "="*80)
print("SCENARIO B: Continuous Portfolio Running from 2018 (What was 2026 YTD performance?)")
print("="*80)
summary_full, daily_full, trades_full = simulate_regime_concentrated_portfolio(
    signals_subset=signals_df,
    stock_date_lookup=stock_date_lookup,
    all_trading_days=all_trading_days,
    nifty_regime_map=nifty_regime_map,
    capacity=10,
    ranking_method="weekly_rsi",
    regime_schedule="sch1",
    sector_restriction="none",
    cost_bps=25.0,
    start_date="2018-01-01",
    end_date="2026-08-24"
)

daily_full["date"] = pd.to_datetime(daily_full["date"])
daily_2026_full = daily_full[daily_full["date"] >= "2026-01-01"].copy()
start_2026_eq = daily_2026_full["equity"].iloc[0]
end_2026_eq = daily_2026_full["equity"].iloc[-1]
ret_2026_pct = (end_2026_eq - start_2026_eq) / start_2026_eq * 100.0

print(f"2026 YTD Return (Ongoing Portfolio): {ret_2026_pct:+.2f}%")
print(f"Start of 2026 Equity: ₹{start_2026_eq:,.2f}")
print(f"Aug 24, 2026 Equity:   ₹{end_2026_eq:,.2f}")
print(f"If starting with 1 Lakh on Jan 1 with this running portfolio: Ending = ₹{100000 * (1 + ret_2026_pct/100):,.2f}")

trades_2026_full = trades_full[trades_full["entry_date"] >= "2025-01-01"]
print(f"\nRecent Trades in Ongoing Portfolio (Entry >= 2025): {len(trades_2026_full)}")
for idx, r in trades_2026_full.iterrows():
    print(f"  {r['symbol']} | Entry: {r['entry_date']} @ ₹{r['raw_entry_price']:.2f} | Exit: {r['exit_date']} @ ₹{r['raw_exit_price']:.2f} | P&L: {r['return_pct']:+.2f}% | Held: {r['holding_days']} days")
