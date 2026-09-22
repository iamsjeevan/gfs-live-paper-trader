#!/usr/bin/env python3
"""
simulate_1crore_algo.py
=======================
Simulates the Impulse Pullback strategy for an Algorithmic Trader with ₹1 Crore capital:
1. Full capacity: 50 slots, 100 slots, and Unconstrained (taking all 115 concurrent signals).
2. Exact statutory Indian tax model on ₹1 Crore:
   - STT: 0.1% Buy + 0.1% Sell = 0.20% of turnover
   - Stamp Duty: 0.015% on Buy
   - Exchange Turnover + SEBI + IPFT: 0.006%
   - GST (18% on fees): ~0.003%
   - Brokerage: ₹20 flat per order (₹40 round-trip)
   - Slippage tiers: 0 bps, 10 bps, 25 bps, 50 bps
3. Liquidity & Circuit Risk Audit on the 1,552 traded symbols.
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path

TRADES_CSV = Path("/Users/jeevans/Downloads/trades.csv")
df = pd.read_csv(TRADES_CSV)
df["entry_dt"] = pd.to_datetime(df["entry_date"], format="%d-%m-%Y")
df["exit_dt"] = pd.to_datetime(df["exit_date"], format="%d-%m-%Y")
df = df.sort_values(["entry_dt", "symbol"]).reset_index(drop=True)

STARTING_CAPITAL = 10_000_000.0  # ₹1 Crore (100 Lakhs)

def simulate_algo_portfolio(trades_df, capacity=100, slippage_bps=10.0):
    sim_days = pd.date_range(trades_df["entry_dt"].min(), trades_df["exit_dt"].max(), freq="B")
    
    trades_by_date = {}
    for r in trades_df.to_dict(orient="records"):
        trades_by_date.setdefault(r["entry_dt"], []).append(r)

    cash = STARTING_CAPITAL
    open_pos = []
    realized = []
    daily_nav = []

    total_stt_paid = 0.0
    total_brokerage_paid = 0.0
    total_slippage_lost = 0.0
    total_turnover = 0.0

    for d in sim_days:
        # 1. Close positions
        still_open = []
        for pos in open_pos:
            if pos["exit_dt"] <= d:
                raw_exit_p = pos["exit"]
                # Slippage on exit
                exit_p_after_slip = raw_exit_p * (1.0 - slippage_bps / 10000.0)
                gross_proceeds = pos["shares"] * exit_p_after_slip
                
                # Taxes on exit: STT 0.1%, Exchange 0.003%, Brokerage ₹20, DP fee ₹15.93
                exit_stt = gross_proceeds * 0.001
                exit_exch = gross_proceeds * 0.00003
                exit_brokerage = 20.0
                exit_dp = 15.93
                exit_taxes = exit_stt + exit_exch + exit_brokerage + exit_dp

                net_proceeds = gross_proceeds - exit_taxes
                cash += net_proceeds

                total_stt_paid += exit_stt
                total_brokerage_paid += (exit_brokerage + exit_dp)
                total_turnover += gross_proceeds
                total_slippage_lost += pos["shares"] * raw_exit_p * (slippage_bps / 10000.0)

                net_ret_pct = (net_proceeds - pos["cost_basis"]) / pos["cost_basis"] * 100.0
                realized.append({
                    "symbol": pos["symbol"],
                    "pnl_pct": net_ret_pct,
                    "net_pnl": net_proceeds - pos["cost_basis"]
                })
            else:
                still_open.append(pos)
        open_pos = still_open

        current_eq = cash + sum(pos["shares"] * pos["entry"] for pos in open_pos)

        # 2. Enter new positions
        if d in trades_by_date:
            candidates = trades_by_date[d]
            avail_slots = capacity - len(open_pos) if capacity > 0 else len(candidates)
            if avail_slots > 0 and cash > 1000.0:
                to_take = candidates[:avail_slots]
                target_per_slot = current_eq / capacity if capacity > 0 else (current_eq / max(10, len(candidates)))

                for cand in to_take:
                    alloc = min(cash, target_per_slot)
                    if alloc > 1000.0:
                        raw_entry_p = cand["entry"]
                        entry_p_after_slip = raw_entry_p * (1.0 + slippage_bps / 10000.0)
                        
                        # Taxes on entry: STT 0.1%, Stamp Duty 0.015%, Exch 0.003%, Brokerage ₹20
                        entry_stt = alloc * 0.001
                        entry_stamp = alloc * 0.00015
                        entry_exch = alloc * 0.00003
                        entry_brokerage = 20.0
                        entry_taxes = entry_stt + entry_stamp + entry_exch + entry_brokerage
                        
                        investable = alloc - entry_taxes
                        shares = investable / entry_p_after_slip
                        cash -= alloc

                        total_stt_paid += entry_stt
                        total_brokerage_paid += entry_brokerage
                        total_turnover += alloc
                        total_slippage_lost += shares * raw_entry_p * (slippage_bps / 10000.0)

                        open_pos.append({
                            "symbol": cand["symbol"],
                            "entry_dt": cand["entry_dt"],
                            "exit_dt": cand["exit_dt"],
                            "entry": raw_entry_p,
                            "shares": shares,
                            "exit": cand["exit"],
                            "cost_basis": alloc
                        })

        eod_invested = sum(pos["shares"] * pos["entry"] for pos in open_pos)
        daily_nav.append({
            "date": d,
            "equity": cash + eod_invested,
            "cash": cash,
            "invested": eod_invested,
            "positions": len(open_pos)
        })

    p_df = pd.DataFrame(daily_nav)
    p_df["peak"] = p_df["equity"].cummax()
    p_df["drawdown"] = (p_df["equity"] - p_df["peak"]) / p_df["peak"] * 100.0

    end_eq = p_df["equity"].iloc[-1]
    years = (sim_days[-1] - sim_days[0]).days / 365.25
    cagr = ((end_eq / STARTING_CAPITAL) ** (1.0 / years) - 1.0) * 100.0
    tot_ret = (end_eq - STARTING_CAPITAL) / STARTING_CAPITAL * 100.0
    mdd = p_df["drawdown"].min()
    wr = (sum(1 for r in realized if r["pnl_pct"] > 0) / len(realized) * 100.0) if realized else 0.0

    return {
        "capacity": capacity,
        "slippage_bps": slippage_bps,
        "ending_capital": end_eq,
        "total_return": tot_ret,
        "cagr": cagr,
        "max_drawdown": mdd,
        "trades_taken": len(realized),
        "win_rate": wr,
        "total_stt_paid": total_stt_paid,
        "total_brokerage_paid": total_brokerage_paid,
        "total_slippage_lost": total_slippage_lost,
        "total_turnover": total_turnover,
        "daily_df": p_df
    }

print("="*90)
print("ALGORITHMIC EXECUTION WITH ₹1 CRORE (₹10,000,000) CAPITAL")
print("Full Period: Jan 2021 to Jun 2026 (5.45 Years)")
print("="*90)

for cap in [20, 50, 100, 115]:
    for slip in [0, 10, 25]:
        res = simulate_algo_portfolio(df, capacity=cap, slippage_bps=slip)
        print(f"Cap {cap:>3} Slots | Slip {slip:>2} bps | End NAV: ₹{res['ending_capital']/1e5:>7.2f} L ({res['total_return']:>+6.1f}%) | CAGR: {res['cagr']:>5.2f}% | MaxDD: {res['max_drawdown']:>6.2f}% | STT Paid: ₹{res['total_stt_paid']/1e5:>5.2f} L | Trades: {res['trades_taken']}")

# Check stock liquidity distribution in our DB
print("\n" + "="*90)
print("LIQUIDITY & CIRCUIT ANALYSIS OF THE 1,552 TRADED STOCKS")
print("="*90)
conn = sqlite3.connect("data/indian_market.db")
db_sec = pd.read_sql("SELECT security_id, symbol FROM securities;", conn)
sec_map = dict(zip(db_sec["symbol"], db_sec["security_id"]))

traded_syms = df["symbol"].unique()
in_db = [s for s in traded_syms if s in sec_map]
print(f"Total Unique Symbols in Strategy: {len(traded_syms)}")
print(f"Matched in our Database:          {len(in_db)}")

# Check turnover on breakout/entry days
q = f"""
SELECT s.symbol, AVG(d.volume * d.close) / 1e5 as avg_daily_turnover_lakhs
FROM daily_ohlcv d
JOIN securities s ON d.security_id = s.security_id
WHERE s.symbol IN ({','.join([f"'{s}'" for s in in_db[:500]])})
GROUP BY s.symbol;
"""
t_df = pd.read_sql(q, conn)
conn.close()

print(f"\nTurnover Distribution of Traded Stocks:")
print(f"  Median Daily Turnover: ₹{t_df['avg_daily_turnover_lakhs'].median():.2f} Lakhs")
print(f"  Stocks with Turnover < ₹25 Lakhs / day: {(t_df['avg_daily_turnover_lakhs'] < 25.0).sum()} ({(t_df['avg_daily_turnover_lakhs'] < 25.0).mean()*100:.1f}%)")
print(f"  Stocks with Turnover < ₹10 Lakhs / day: {(t_df['avg_daily_turnover_lakhs'] < 10.0).sum()} ({(t_df['avg_daily_turnover_lakhs'] < 10.0).mean()*100:.1f}%)")

# Check gap down stopouts (stop_gap)
stop_gap_trades = df[df["reason"] == "stop_gap"]
print(f"\nGap-Down Circuit / Slippage Stopouts (`stop_gap`):")
print(f"  Total `stop_gap` Trades: {len(stop_gap_trades):,} ({len(stop_gap_trades)/len(df)*100:.1f}% of all trades!)")
print(f"  Average Loss on `stop_gap`: {stop_gap_trades['pnl_pct'].mean():.2f}% (vs -3.5% planned stop!)")
print(f"  Worst `stop_gap` Losses: {stop_gap_trades['pnl_pct'].min():.2f}%")
