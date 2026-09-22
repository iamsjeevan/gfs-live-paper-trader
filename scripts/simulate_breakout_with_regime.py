#!/usr/bin/env python3
"""
simulate_breakout_with_regime.py
================================
Simulates the Breakout + Retest strategy with MARKET REGIME SCHEDULE 1:
(100% Bull / 70% Neutral / 30% Bear using NIFTY 50 200 EMA & 50 EMA)
across both 10-position and 15-position capacities in 2026.
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
import sys

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
sys.path.insert(0, str(BASE_DIR))

from scripts.run_gfs_concentrated_regime_backtest import load_data_and_regimes
from scripts.run_dynamic_allocation_research import prepare_opportunity_dataset

# 1. Load data
print("Loading opportunity trades and NIFTY regimes...")
opp_trades = prepare_opportunity_dataset()

conn = sqlite3.connect("data/indian_market.db")
daily_all = pd.read_sql("SELECT security_id, date, close FROM daily_ohlcv WHERE date >= '2026-01-01' ORDER BY date ASC;", conn)
nifty_df = pd.read_sql("SELECT date, open, high, low, close FROM daily_ohlcv WHERE security_id = 2835 ORDER BY date ASC;", conn)
conn.close()

# Compute NIFTY EMAs
nifty_df["ema200"] = nifty_df["close"].ewm(span=200, adjust=False).mean()
nifty_df["ema50"] = nifty_df["close"].ewm(span=50, adjust=False).mean()
nifty_df["bull_flag"] = (nifty_df["close"] > nifty_df["ema200"]) & (nifty_df["close"] > nifty_df["ema50"])
nifty_df["bear_flag"] = (nifty_df["close"] <= nifty_df["ema200"]) & (nifty_df["close"] <= nifty_df["ema50"])
nifty_df["regime"] = "NEUTRAL"
nifty_df.loc[nifty_df["bull_flag"], "regime"] = "BULL"
nifty_df.loc[nifty_df["bear_flag"], "regime"] = "BEAR"
nifty_regime_map = dict(zip(nifty_df["date"], nifty_df["regime"]))

calendar_days_2026 = sorted(daily_all["date"].unique())
price_dict = daily_all.set_index(["security_id", "date"])["close"].to_dict()

def simulate_breakout_regime(
    trades,
    all_trading_days,
    price_dict,
    nifty_regime_map,
    capacity=15,
    allocation_model="MODEL_A", # MODEL_A or MODEL_C_VOL
    ranking_col="rel_volume",
    cost_bps=25.0,
    regime_schedule="sch1", # 'fixed' or 'sch1'
    start_date="2026-01-01",
    end_date="2026-08-24"
):
    STARTING_CAPITAL = 100_000.0  # ₹1 Lakh
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)

    schedules = {
        "fixed": {"BULL": 1.0, "NEUTRAL": 1.0, "BEAR": 1.0},
        "sch1": {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30},
    }
    exp_sch = schedules.get(regime_schedule, schedules["fixed"])

    valid_set = trades[
        (trades["Entry Date"] >= start_date) &
        (trades["Entry Date"] <= end_date)
    ].copy()

    trades_by_entry = {}
    for t in valid_set.to_dict(orient="records"):
        trades_by_entry.setdefault(t["Entry Date"], []).append(t)

    portfolio_cash = STARTING_CAPITAL
    open_positions = {}
    realized_trades = []
    daily_records = []

    for d in all_trading_days:
        if d < start_date or d > end_date:
            continue

        # 1. Close positions exiting on this day
        to_close = []
        for sec_id, pos in open_positions.items():
            if pos["exit_date"] == d:
                raw_exit_p = pos["exit_price"]
                net_exit_p = raw_exit_p * cost_mult_exit
                exit_proceeds = pos["shares"] * net_exit_p
                portfolio_cash += exit_proceeds

                trade_ret = (net_exit_p - pos["effective_entry_p"]) / pos["effective_entry_p"] * 100.0
                realized_trades.append({
                    "ticker": pos["ticker"],
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "return_pct": trade_ret,
                    "holding_days": pos["holding_days"],
                    "invested": pos["allocated_capital"]
                })
                to_close.append(sec_id)
        for sec_id in to_close:
            del open_positions[sec_id]

        # 2. Portfolio Valuation
        current_invested_val = sum(pos["shares"] * price_dict.get((sec_id, d), pos["effective_entry_p"]) for sec_id, pos in open_positions.items())
        current_equity = portfolio_cash + current_invested_val

        # Regime limits
        regime = nifty_regime_map.get(d, "NEUTRAL")
        target_exp = exp_sch.get(regime, 1.0)
        max_allowed_equity = current_equity * target_exp
        max_allowed_positions = max(1, int(round(capacity * target_exp)))

        # 3. Enter new positions
        if d in trades_by_entry:
            day_signals = trades_by_entry[d]
            day_signals = [s for s in day_signals if s["security_id"] not in open_positions]

            day_signals = sorted(
                day_signals,
                key=lambda x: (x[ranking_col] if pd.notna(x[ranking_col]) else -1e9),
                reverse=True
            )

            available_slots = max(0, max_allowed_positions - len(open_positions))
            candidates_to_enter = day_signals[:available_slots]

            if candidates_to_enter and current_invested_val < max_allowed_equity and portfolio_cash > 100.0:
                k = len(candidates_to_enter)
                deployable_cash = max(0.0, min(portfolio_cash, max_allowed_equity - current_invested_val))

                if allocation_model == "MODEL_C_VOL":
                    vols = np.array([max(0.01, c["rel_volume"]) for c in candidates_to_enter])
                    proportions = vols / vols.sum()
                else:
                    proportions = np.ones(k) / k

                alloc_per_candidate = (deployable_cash / available_slots) if available_slots > 0 else 0.0
                slot_cap = current_equity / capacity

                for idx, t in enumerate(candidates_to_enter):
                    if allocation_model == "MODEL_C_VOL":
                        target_alloc = min(deployable_cash * proportions[idx], slot_cap * 1.5)
                    else:
                        target_alloc = min(slot_cap, deployable_cash / len(candidates_to_enter))

                    actual_alloc = min(portfolio_cash, target_alloc)
                    if actual_alloc > 100.0 and (current_invested_val + actual_alloc) <= (max_allowed_equity * 1.05):
                        raw_entry_p = t["Entry Price"]
                        effective_entry_p = raw_entry_p * cost_mult_entry
                        shares = actual_alloc / effective_entry_p
                        portfolio_cash -= actual_alloc
                        current_invested_val += actual_alloc

                        open_positions[t["security_id"]] = {
                            "ticker": t["Ticker"],
                            "shares": shares,
                            "effective_entry_p": effective_entry_p,
                            "entry_price": raw_entry_p,
                            "entry_date": t["Entry Date"],
                            "exit_date": t["Exit Date"],
                            "exit_price": t["Exit Price"],
                            "holding_days": t["Holding Days"],
                            "allocated_capital": actual_alloc
                        }

        # Daily record
        eod_invested = sum(pos["shares"] * price_dict.get((sec_id, d), pos["effective_entry_p"]) for sec_id, pos in open_positions.items())
        eod_equity = portfolio_cash + eod_invested
        daily_records.append({
            "date": d,
            "equity": eod_equity,
            "cash": portfolio_cash,
            "invested": eod_invested,
            "regime": regime,
            "positions": len(open_positions)
        })

    p_df = pd.DataFrame(daily_records)
    p_df["peak"] = p_df["equity"].cummax()
    p_df["drawdown"] = (p_df["equity"] - p_df["peak"]) / p_df["peak"] * 100.0

    ending_equity = p_df["equity"].iloc[-1]
    tot_return = (ending_equity - STARTING_CAPITAL) / STARTING_CAPITAL * 100.0
    max_dd = p_df["drawdown"].min()
    trades_count = len(realized_trades)

    return {
        "ending_equity": ending_equity,
        "tot_return": tot_return,
        "max_drawdown": max_dd,
        "trades_count": trades_count,
        "daily_df": p_df,
        "realized_trades": realized_trades
    }

# Run simulations for Breakout with and without Regime Schedule 1
print("\n" + "="*80)
print("RUNNING BREAKOUT / RETEST SIMULATIONS (WITH & WITHOUT REGIME)")
print("="*80)

# 1. Breakout 15 slots Fixed (No regime)
b_fixed_15 = simulate_breakout_regime(opp_trades, calendar_days_2026, price_dict, nifty_regime_map, capacity=15, regime_schedule="fixed")
# 2. Breakout 15 slots + Regime Schedule 1
b_regime_15 = simulate_breakout_regime(opp_trades, calendar_days_2026, price_dict, nifty_regime_map, capacity=15, regime_schedule="sch1")
# 3. Breakout 10 slots Fixed (No regime)
b_fixed_10 = simulate_breakout_regime(opp_trades, calendar_days_2026, price_dict, nifty_regime_map, capacity=10, regime_schedule="fixed")
# 4. Breakout 10 slots + Regime Schedule 1
b_regime_10 = simulate_breakout_regime(opp_trades, calendar_days_2026, price_dict, nifty_regime_map, capacity=10, regime_schedule="sch1")
# 5. Breakout 15 slots Model C (RelVol) + Regime Schedule 1
b_relvol_regime_15 = simulate_breakout_regime(opp_trades, calendar_days_2026, price_dict, nifty_regime_map, capacity=15, allocation_model="MODEL_C_VOL", regime_schedule="sch1")

print(f"{'Configuration':45} | {'Ending NAV':>12} | {'Return %':>9} | {'MaxDD %':>8} | {'Trades':>6}")
print("-" * 90)
print(f"{'Breakout 15-Slot Fixed (No Regime)':45} | ₹{b_fixed_15['ending_equity']:>10,.2f} | {b_fixed_15['tot_return']:>+8.2f}% | {b_fixed_15['max_drawdown']:>7.2f}% | {b_fixed_15['trades_count']:>6}")
print(f"{'Breakout 15-Slot + Regime Schedule 1':45} | ₹{b_regime_15['ending_equity']:>10,.2f} | {b_regime_15['tot_return']:>+8.2f}% | {b_regime_15['max_drawdown']:>7.2f}% | {b_regime_15['trades_count']:>6}")
print(f"{'Breakout 10-Slot Fixed (No Regime)':45} | ₹{b_fixed_10['ending_equity']:>10,.2f} | {b_fixed_10['tot_return']:>+8.2f}% | {b_fixed_10['max_drawdown']:>7.2f}% | {b_fixed_10['trades_count']:>6}")
print(f"{'Breakout 10-Slot + Regime Schedule 1':45} | ₹{b_regime_10['ending_equity']:>10,.2f} | {b_regime_10['tot_return']:>+8.2f}% | {b_regime_10['max_drawdown']:>7.2f}% | {b_regime_10['trades_count']:>6}")
print(f"{'Breakout RelVol 15-Slot + Regime Schedule 1':45} | ₹{b_relvol_regime_15['ending_equity']:>10,.2f} | {b_relvol_regime_15['tot_return']:>+8.2f}% | {b_relvol_regime_15['max_drawdown']:>7.2f}% | {b_relvol_regime_15['trades_count']:>6}")

# Save comparison dataframe
comp_csv_path = BASE_DIR / "reports" / "breakout_regime_comparison_2026.csv"
b_comp_df = pd.DataFrame({
    "date": b_regime_15["daily_df"]["date"],
    "breakout_15_fixed": b_fixed_15["daily_df"]["equity"],
    "breakout_15_regime": b_regime_15["daily_df"]["equity"],
    "breakout_10_fixed": b_fixed_10["daily_df"]["equity"],
    "breakout_10_regime": b_regime_10["daily_df"]["equity"],
    "breakout_relvol_regime": b_relvol_regime_15["daily_df"]["equity"]
})
b_comp_df.to_csv(comp_csv_path, index=False)
print("Saved breakout regime comparison CSV.")
