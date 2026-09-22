#!/usr/bin/env python3
"""
run_full_history_comparison_1lakh.py
====================================
Runs full historical simulation from the oldest data (January 2018) to August 2026
starting with ₹1,00,000 (1 Lakh) initial capital across all strategies:
1. GFS 10-Slot + Regime Schedule 1 (Weekly RSI)
2. GFS 15-Slot + Regime Schedule 1 (3M Return)
3. GFS 15-Slot Fixed 100% (3M Return)
4. Breakout Model C (RelVol) + Regime Schedule 1
5. Breakout Model A (Equal Weight 15) + Regime Schedule 1
6. Breakout Model C (RelVol) Fixed 100%
7. Breakout Model A (Equal Weight 15) Fixed 100%
8. NIFTY 50 Benchmark (Buy & Hold)
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
from scripts.run_dynamic_allocation_research import prepare_opportunity_dataset

# 1. Load GFS data & simulate
print("Loading GFS data and regimes...")
signals_df, stock_date_lookup, all_trading_days, nifty_regime_map = load_data_and_regimes()

START_DATE = "2018-01-01"
END_DATE = "2026-08-24"
STARTING_CAPITAL = 100_000.0  # ₹1 Lakh
SCALE_GFS = STARTING_CAPITAL / 1_000_000.0

# Strategy 1: GFS 10-Slot Regime Schedule 1 (Weekly RSI)
print("\nSimulating GFS 10-Slot + Regime Schedule 1 (Weekly RSI)...")
res_gfs10_reg, daily_gfs10_reg, trades_gfs10_reg = simulate_regime_concentrated_portfolio(
    signals_subset=signals_df,
    stock_date_lookup=stock_date_lookup,
    all_trading_days=all_trading_days,
    nifty_regime_map=nifty_regime_map,
    capacity=10,
    ranking_method="weekly_rsi",
    regime_schedule="sch1",
    sector_restriction="none",
    cost_bps=25.0,
    start_date=START_DATE,
    end_date=END_DATE
)
daily_gfs10_reg["equity_1lakh"] = daily_gfs10_reg["equity"] * SCALE_GFS

# Strategy 2: GFS 15-Slot Regime Schedule 1 (3M Return)
print("Simulating GFS 15-Slot + Regime Schedule 1 (3M Return)...")
res_gfs15_reg, daily_gfs15_reg, trades_gfs15_reg = simulate_regime_concentrated_portfolio(
    signals_subset=signals_df,
    stock_date_lookup=stock_date_lookup,
    all_trading_days=all_trading_days,
    nifty_regime_map=nifty_regime_map,
    capacity=15,
    ranking_method="ret_3m",
    regime_schedule="sch1",
    sector_restriction="none",
    cost_bps=25.0,
    start_date=START_DATE,
    end_date=END_DATE
)
daily_gfs15_reg["equity_1lakh"] = daily_gfs15_reg["equity"] * SCALE_GFS

# Strategy 3: GFS 15-Slot Fixed 100% (3M Return)
print("Simulating GFS 15-Slot Fixed 100% (3M Return)...")
res_gfs15_fix, daily_gfs15_fix, trades_gfs15_fix = simulate_regime_concentrated_portfolio(
    signals_subset=signals_df,
    stock_date_lookup=stock_date_lookup,
    all_trading_days=all_trading_days,
    nifty_regime_map=nifty_regime_map,
    capacity=15,
    ranking_method="ret_3m",
    regime_schedule="fixed",
    sector_restriction="none",
    cost_bps=25.0,
    start_date=START_DATE,
    end_date=END_DATE
)
daily_gfs15_fix["equity_1lakh"] = daily_gfs15_fix["equity"] * SCALE_GFS

# 2. Breakout / Retest Simulations
print("\nPreparing Breakout dataset and price dict for 2018-2026...")
opp_trades = prepare_opportunity_dataset()

conn = sqlite3.connect("data/indian_market.db")
daily_all = pd.read_sql("SELECT security_id, date, close FROM daily_ohlcv WHERE date >= '2018-01-01' ORDER BY date ASC;", conn)
nifty_df = pd.read_sql("SELECT date, open, high, low, close FROM daily_ohlcv WHERE security_id = 2835 ORDER BY date ASC;", conn)
conn.close()

calendar_days = sorted(daily_all["date"].unique())
price_dict = daily_all.set_index(["security_id", "date"])["close"].to_dict()

def simulate_breakout_full(trades, all_days, p_dict, regime_map, capacity=15, model="MODEL_A", regime_sch="sch1"):
    schedules = {
        "fixed": {"BULL": 1.0, "NEUTRAL": 1.0, "BEAR": 1.0},
        "sch1": {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30},
    }
    exp_sch = schedules.get(regime_sch, schedules["fixed"])
    cost_bps = 25.0
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)

    trades_by_entry = {}
    for t in trades.to_dict(orient="records"):
        trades_by_entry.setdefault(t["Entry Date"], []).append(t)

    portfolio_cash = STARTING_CAPITAL
    open_positions = {}
    realized_trades = []
    daily_records = []

    for d in all_days:
        # Exits
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
                    "holding_days": pos["holding_days"]
                })
                to_close.append(sec_id)
        for sec_id in to_close:
            del open_positions[sec_id]

        # Valuation
        current_invested_val = sum(pos["shares"] * p_dict.get((sec_id, d), pos["effective_entry_p"]) for sec_id, pos in open_positions.items())
        current_equity = portfolio_cash + current_invested_val

        # Regime limits
        regime = regime_map.get(d, "NEUTRAL")
        target_exp = exp_sch.get(regime, 1.0)
        max_allowed_equity = current_equity * target_exp
        max_allowed_positions = max(1, int(round(capacity * target_exp)))

        # Entries
        if d in trades_by_entry:
            day_signals = trades_by_entry[d]
            day_signals = [s for s in day_signals if s["security_id"] not in open_positions]
            day_signals = sorted(day_signals, key=lambda x: (x["rel_volume"] if pd.notna(x["rel_volume"]) else -1e9), reverse=True)

            available_slots = max(0, max_allowed_positions - len(open_positions))
            candidates_to_enter = day_signals[:available_slots]

            if candidates_to_enter and current_invested_val < max_allowed_equity and portfolio_cash > 100.0:
                k = len(candidates_to_enter)
                deployable_cash = max(0.0, min(portfolio_cash, max_allowed_equity - current_invested_val))

                if model == "MODEL_C_VOL":
                    vols = np.array([max(0.01, c["rel_volume"]) for c in candidates_to_enter])
                    proportions = vols / vols.sum()
                else:
                    proportions = np.ones(k) / k

                slot_cap = current_equity / capacity
                for idx, t in enumerate(candidates_to_enter):
                    if model == "MODEL_C_VOL":
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
                            "holding_days": t["Holding Days"]
                        }

        eod_invested = sum(pos["shares"] * p_dict.get((sec_id, d), pos["effective_entry_p"]) for sec_id, pos in open_positions.items())
        daily_records.append({
            "date": d,
            "equity": portfolio_cash + eod_invested,
            "cash": portfolio_cash
        })

    p_df = pd.DataFrame(daily_records)
    p_df["peak"] = p_df["equity"].cummax()
    p_df["drawdown"] = (p_df["equity"] - p_df["peak"]) / p_df["peak"] * 100.0

    end_eq = p_df["equity"].iloc[-1]
    years = (pd.to_datetime(all_days[-1]) - pd.to_datetime(all_days[0])).days / 365.25
    cagr = ((end_eq / STARTING_CAPITAL) ** (1.0 / years) - 1.0) * 100.0
    tot_ret = (end_eq - STARTING_CAPITAL) / STARTING_CAPITAL * 100.0
    mdd = p_df["drawdown"].min()
    
    wins = [t for t in realized_trades if t["return_pct"] > 0]
    losses = [t for t in realized_trades if t["return_pct"] <= 0]
    win_rate = (len(wins) / len(realized_trades) * 100.0) if realized_trades else 0.0
    pf = (sum(t["return_pct"] for t in wins) / abs(sum(t["return_pct"] for t in losses))) if losses and sum(t["return_pct"] for t in losses) != 0 else 0.0

    return {
        "end_equity": end_eq,
        "tot_return": tot_ret,
        "cagr": cagr,
        "max_drawdown": mdd,
        "win_rate": win_rate,
        "profit_factor": pf,
        "trades_count": len(realized_trades),
        "daily_df": p_df
    }

print("\nSimulating Breakout 15-Slot Model C (RelVol) + Regime Schedule 1...")
bo_relvol_reg = simulate_breakout_full(opp_trades, calendar_days, price_dict, nifty_regime_map, capacity=15, model="MODEL_C_VOL", regime_sch="sch1")

print("Simulating Breakout 15-Slot Model A (Equal Wt) + Regime Schedule 1...")
bo_equal_reg = simulate_breakout_full(opp_trades, calendar_days, price_dict, nifty_regime_map, capacity=15, model="MODEL_A", regime_sch="sch1")

print("Simulating Breakout 15-Slot Model C (RelVol) Fixed 100%...")
bo_relvol_fix = simulate_breakout_full(opp_trades, calendar_days, price_dict, nifty_regime_map, capacity=15, model="MODEL_C_VOL", regime_sch="fixed")

print("Simulating Breakout 15-Slot Model A (Equal Wt) Fixed 100%...")
bo_equal_fix = simulate_breakout_full(opp_trades, calendar_days, price_dict, nifty_regime_map, capacity=15, model="MODEL_A", regime_sch="fixed")

# 3. NIFTY 50 Benchmark Buy & Hold
nifty_start_open = nifty_df["open"].iloc[0]
nifty_df["equity_1lakh"] = (nifty_df["close"] / nifty_start_open) * STARTING_CAPITAL
nifty_df["peak"] = nifty_df["equity_1lakh"].cummax()
nifty_df["drawdown"] = (nifty_df["equity_1lakh"] - nifty_df["peak"]) / nifty_df["peak"] * 100.0

nifty_end_eq = nifty_df["equity_1lakh"].iloc[-1]
years_full = (pd.to_datetime(nifty_df["date"].iloc[-1]) - pd.to_datetime(nifty_df["date"].iloc[0])).days / 365.25
nifty_cagr = ((nifty_end_eq / STARTING_CAPITAL) ** (1.0 / years_full) - 1.0) * 100.0
nifty_tot_ret = (nifty_end_eq - STARTING_CAPITAL) / STARTING_CAPITAL * 100.0
nifty_mdd = nifty_df["drawdown"].min()

# Collect and print full comparison
print("\n" + "="*110)
print("FULL HISTORICAL COMPILATION (JANUARY 2018 TO AUGUST 2026 — 8.64 YEARS)")
print("STARTING CAPITAL: ₹1,00,000 (1 LAKH)")
print("="*110)

all_results = [
    ("GFS 10-Slot + Regime Schedule 1 (Weekly RSI)", daily_gfs10_reg["equity_1lakh"].iloc[-1], res_gfs10_reg["cagr"], res_gfs10_reg["max_drawdown"], res_gfs10_reg["profit_factor"], res_gfs10_reg["win_rate"], len(trades_gfs10_reg)),
    ("GFS 15-Slot + Regime Schedule 1 (3M Return)", daily_gfs15_reg["equity_1lakh"].iloc[-1], res_gfs15_reg["cagr"], res_gfs15_reg["max_drawdown"], res_gfs15_reg["profit_factor"], res_gfs15_reg["win_rate"], len(trades_gfs15_reg)),
    ("GFS 15-Slot Fixed 100% (3M Return)", daily_gfs15_fix["equity_1lakh"].iloc[-1], res_gfs15_fix["cagr"], res_gfs15_fix["max_drawdown"], res_gfs15_fix["profit_factor"], res_gfs15_fix["win_rate"], len(trades_gfs15_fix)),
    ("Breakout RelVol 15 + Regime Sch 1", bo_relvol_reg["end_equity"], bo_relvol_reg["cagr"], bo_relvol_reg["max_drawdown"], bo_relvol_reg["profit_factor"], bo_relvol_reg["win_rate"], bo_relvol_reg["trades_count"]),
    ("Breakout Equal Wt 15 + Regime Sch 1", bo_equal_reg["end_equity"], bo_equal_reg["cagr"], bo_equal_reg["max_drawdown"], bo_equal_reg["profit_factor"], bo_equal_reg["win_rate"], bo_equal_reg["trades_count"]),
    ("Breakout RelVol 15 Fixed 100%", bo_relvol_fix["end_equity"], bo_relvol_fix["cagr"], bo_relvol_fix["max_drawdown"], bo_relvol_fix["profit_factor"], bo_relvol_fix["win_rate"], bo_relvol_fix["trades_count"]),
    ("Breakout Equal Wt 15 Fixed 100%", bo_equal_fix["end_equity"], bo_equal_fix["cagr"], bo_equal_fix["max_drawdown"], bo_equal_fix["profit_factor"], bo_equal_fix["win_rate"], bo_equal_fix["trades_count"]),
    ("NIFTY 50 Benchmark (Buy & Hold)", nifty_end_eq, nifty_cagr, nifty_mdd, np.nan, np.nan, 1)
]

print(f"{'Strategy / Benchmark':46} | {'Ending Capital (₹)':>18} | {'Total Return':>12} | {'CAGR %':>8} | {'MaxDD %':>8} | {'Profit Factor':>13} | {'Trades':>6}")
print("-" * 125)
for name, end_c, cagr_val, mdd_val, pf_val, wr_val, tr_cnt in all_results:
    tot_pct = (end_c - STARTING_CAPITAL) / STARTING_CAPITAL * 100.0
    pf_str = f"{pf_val:13.2f}" if pd.notna(pf_val) else "          N/A"
    print(f"{name:46} | ₹{end_c:>16,.2f} | {tot_pct:>+11.1f}% | {cagr_val:>7.2f}% | {mdd_val:>7.2f}% | {pf_str} | {tr_cnt:>6}")

# Save full comparison series to CSV
full_comp_df = pd.DataFrame({"date": daily_gfs10_reg["date"]})
full_comp_df["gfs_10_regime"] = daily_gfs10_reg["equity_1lakh"].values
full_comp_df["gfs_15_regime"] = daily_gfs15_reg["equity_1lakh"].values
full_comp_df["gfs_15_fixed"] = daily_gfs15_fix["equity_1lakh"].values

# Merge breakout series
bo_rr_df = bo_relvol_reg["daily_df"][["date", "equity"]].rename(columns={"equity": "breakout_relvol_regime"})
full_comp_df = full_comp_df.merge(bo_rr_df, on="date", how="left").ffill()

bo_er_df = bo_equal_reg["daily_df"][["date", "equity"]].rename(columns={"equity": "breakout_equal_regime"})
full_comp_df = full_comp_df.merge(bo_er_df, on="date", how="left").ffill()

bo_rf_df = bo_relvol_fix["daily_df"][["date", "equity"]].rename(columns={"equity": "breakout_relvol_fixed"})
full_comp_df = full_comp_df.merge(bo_rf_df, on="date", how="left").ffill()

bo_ef_df = bo_equal_fix["daily_df"][["date", "equity"]].rename(columns={"equity": "breakout_equal_fixed"})
full_comp_df = full_comp_df.merge(bo_ef_df, on="date", how="left").ffill()

nifty_df_merge = nifty_df[["date", "equity_1lakh"]].rename(columns={"equity_1lakh": "nifty_50"})
full_comp_df = full_comp_df.merge(nifty_df_merge, on="date", how="left").ffill()

full_csv_path = BASE_DIR / "reports" / "full_history_1lakh_comparison.csv"
full_comp_df.to_csv(full_csv_path, index=False)
print(f"\nSaved full history comparison CSV to {full_csv_path}.")
