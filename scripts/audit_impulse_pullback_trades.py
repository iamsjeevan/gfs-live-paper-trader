#!/usr/bin/env python3
"""
audit_impulse_pullback_trades.py
================================
Performs a deep quantitative audit and portfolio simulation on the Impulse Pullback
strategy trade log provided in /Users/jeevans/Downloads/trades.csv.
"""

import pandas as pd
import numpy as np
from pathlib import Path

TRADES_CSV = Path("/Users/jeevans/Downloads/trades.csv")
df = pd.read_csv(TRADES_CSV)

print("="*80)
print("1. TRADE LOG DATASET OVERVIEW")
print("="*80)
print(f"Total Trade Records: {len(df):,}")
print(f"Unique Symbols: {df['symbol'].nunique():,}")
print(f"Columns: {df.columns.tolist()}")

# Parse dates: format seems to be DD-MM-YYYY
df["entry_dt"] = pd.to_datetime(df["entry_date"], format="%d-%m-%Y", errors="coerce")
df["exit_dt"] = pd.to_datetime(df["exit_date"], format="%d-%m-%Y", errors="coerce")

print(f"Date Range: {df['entry_dt'].min().strftime('%Y-%m-%d')} to {df['entry_dt'].max().strftime('%Y-%m-%d')}")
years = (df["exit_dt"].max() - df["entry_dt"].min()).days / 365.25
print(f"Total Span: {years:.2f} years")

print("\n" + "="*80)
print("2. STANDALONE UNWEIGHTED TRADE METRICS")
print("="*80)
wins = df[df["pnl_pct"] > 0]
losses = df[df["pnl_pct"] <= 0]
win_rate = len(wins) / len(df) * 100.0
avg_win = wins["pnl_pct"].mean()
avg_loss = losses["pnl_pct"].mean()
reward_to_risk = abs(avg_win / avg_loss) if avg_loss != 0 else np.nan
profit_factor = wins["pnl_pct"].sum() / abs(losses["pnl_pct"].sum())

print(f"Win Rate:              {win_rate:.2f}% ({len(wins):,} Wins / {len(losses):,} Losses)")
print(f"Average Win:           +{avg_win:.2f}%")
print(f"Average Loss:          {avg_loss:.2f}%")
print(f"Reward-to-Risk Ratio:  {reward_to_risk:.2f} : 1")
print(f"Unweighted Expectancy: {df['pnl_pct'].mean():+.2f}% per trade")
print(f"Profit Factor:         {profit_factor:.2f}")
print(f"Average Days Held:     {df['days_held'].mean():.1f} days (Median: {df['days_held'].median():.0f} days)")

print("\n--- Breakdown by Exit Reason ---")
reason_grp = df.groupby("reason").agg(
    count=("pnl_pct", "count"),
    win_rate=("pnl_pct", lambda x: (x > 0).mean() * 100.0),
    avg_pnl=("pnl_pct", "mean"),
    avg_days=("days_held", "mean")
).reset_index()
print(reason_grp.to_string(index=False))

print("\n" + "="*80)
print("3. CONGESTION & CONCURRENCY ANALYSIS")
print("="*80)
# How many trades are open simultaneously?
# Build daily active trades count
min_d = df["entry_dt"].min()
max_d = df["exit_dt"].max()
all_days = pd.date_range(min_d, max_d, freq="B")

daily_open_counts = []
for d in all_days:
    # count how many trades had entry_dt <= d <= exit_dt
    c = ((df["entry_dt"] <= d) & (df["exit_dt"] >= d)).sum()
    daily_open_counts.append(c)

daily_open_s = pd.Series(daily_open_counts, index=all_days)
print(f"Average Concurrent Active Trades: {daily_open_s.mean():.1f}")
print(f"Median Concurrent Active Trades:  {daily_open_s.median():.0f}")
print(f"Peak Concurrent Active Trades:    {daily_open_s.max():.0f}")
print(f"90th Percentile Concurrent:       {daily_open_s.quantile(0.90):.0f}")
print(f"Days with >50 simultaneous trades:{ (daily_open_s > 50).sum()} days")

# Check entries per day
entries_per_day = df.groupby("entry_dt")["symbol"].count()
print(f"\nAverage New Entries per Signal Day: {entries_per_day.mean():.1f}")
print(f"Max New Entries in a Single Day:     {entries_per_day.max()}")

print("\n" + "="*80)
print("4. REALISTIC PORTFOLIO SIMULATION (10, 15, 20, 30 POSITIONS)")
print("Starting Capital: ₹1,00,000 (1 Lakh)")
print("="*80)

def simulate_portfolio(trades_df, capacity=10, initial_capital=100_000.0, cost_bps=25.0):
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)

    # Sort trades chronologically
    t_sorted = trades_df.sort_values(["entry_dt", "symbol"]).copy()
    trades_by_date = {}
    for r in t_sorted.to_dict(orient="records"):
        trades_by_date.setdefault(r["entry_dt"], []).append(r)

    sim_days = pd.date_range(t_sorted["entry_dt"].min(), t_sorted["exit_dt"].max(), freq="B")

    cash = initial_capital
    open_pos = [] # list of dicts
    realized = []
    nav_history = []

    for d in sim_days:
        # 1. Close positions exiting on or before today
        still_open = []
        for pos in open_pos:
            if pos["exit_dt"] <= d:
                raw_exit_p = pos["exit"]
                sim_exit_p = raw_exit_p * cost_mult_exit
                proceeds = pos["shares"] * sim_exit_p
                cash += proceeds
                pnl = (sim_exit_p - pos["sim_entry_p"]) / pos["sim_entry_p"] * 100.0
                realized.append({
                    "symbol": pos["symbol"],
                    "pnl_pct": pnl,
                    "holding_days": (d - pos["entry_dt"]).days
                })
            else:
                still_open.append(pos)
        open_pos = still_open

        # 2. Portfolio valuation
        current_eq = cash + sum(pos["shares"] * pos["entry"] for pos in open_pos)

        # 3. Enter new trades
        if d in trades_by_date:
            candidates = trades_by_date[d]
            avail_slots = capacity - len(open_pos)
            if avail_slots > 0 and cash > 100.0:
                to_take = candidates[:avail_slots]
                alloc_per_slot = current_eq / capacity
                for cand in to_take:
                    alloc = min(cash, alloc_per_slot)
                    if alloc > 100.0:
                        raw_entry_p = cand["entry"]
                        sim_entry_p = raw_entry_p * cost_mult_entry
                        shares = alloc / sim_entry_p
                        cash -= alloc
                        open_pos.append({
                            "symbol": cand["symbol"],
                            "entry_dt": cand["entry_dt"],
                            "exit_dt": cand["exit_dt"],
                            "entry": raw_entry_p,
                            "sim_entry_p": sim_entry_p,
                            "exit": cand["exit"],
                            "shares": shares
                        })

        # EOD valuation
        eod_eq = cash + sum(pos["shares"] * pos["entry"] for pos in open_pos)
        nav_history.append({"date": d, "equity": eod_eq, "cash": cash, "positions": len(open_pos)})

    p_df = pd.DataFrame(nav_history)
    p_df["peak"] = p_df["equity"].cummax()
    p_df["drawdown"] = (p_df["equity"] - p_df["peak"]) / p_df["peak"] * 100.0

    end_eq = p_df["equity"].iloc[-1]
    years_sim = (sim_days[-1] - sim_days[0]).days / 365.25
    cagr = ((end_eq / initial_capital) ** (1.0 / years_sim) - 1.0) * 100.0
    tot_ret = (end_eq - initial_capital) / initial_capital * 100.0
    mdd = p_df["drawdown"].min()
    wr = (sum(1 for t in realized if t["pnl_pct"] > 0) / len(realized) * 100.0) if realized else 0.0

    return {
        "capacity": capacity,
        "ending_capital": end_eq,
        "total_return": tot_ret,
        "cagr": cagr,
        "max_drawdown": mdd,
        "trades_taken": len(realized),
        "win_rate": wr,
        "daily_df": p_df
    }

for cap in [5, 10, 15, 20, 30, 50]:
    res = simulate_portfolio(df, capacity=cap)
    print(f"Capacity {cap:2d} Slots | End Capital: ₹{res['ending_capital']:>11,.2f} | Total Ret: {res['total_return']:>+7.1f}% | CAGR: {res['cagr']:>6.2f}% | MaxDD: {res['max_drawdown']:>6.2f}% | Trades: {res['trades_taken']:>5} | Win Rate: {res['win_rate']:>5.1f}%")

print("\n" + "="*80)
print("5. 2026 YEAR-TO-DATE AUDIT (2026-01-01 to 2026-08-24)")
print("="*80)
df_2026 = df[df["entry_dt"] >= "2026-01-01"].copy()
print(f"Trades in 2026: {len(df_2026)}")
if not df_2026.empty:
    w26 = df_2026[df_2026["pnl_pct"] > 0]
    l26 = df_2026[df_2026["pnl_pct"] <= 0]
    wr26 = len(w26) / len(df_2026) * 100.0
    pf26 = w26["pnl_pct"].sum() / abs(l26["pnl_pct"].sum()) if not l26.empty else np.nan
    print(f"2026 Win Rate:      {wr26:.1f}% ({len(w26)} Wins / {len(l26)} Losses)")
    print(f"2026 Profit Factor: {pf26:.2f}")
    print(f"2026 Avg Trade:     {df_2026['pnl_pct'].mean():+.2f}%")
    
    # Simulate 2026 with 10 slots
    res_2026_10 = simulate_portfolio(df_2026, capacity=10)
    print(f"2026 Portfolio (10 Slots): End NAV = ₹{res_2026_10['ending_capital']:,.2f} ({res_2026_10['total_return']:+.2f}%) | MaxDD = {res_2026_10['max_drawdown']:.2f}% | Trades = {res_2026_10['trades_taken']}")
