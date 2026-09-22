#!/usr/bin/env python3
"""
simulate_cash_parking_gold_liquid.py
====================================
Simulates GFS Cash 10-Slot + Regime Schedule 1 with ₹1 Crore initial capital
testing 3 different treatments for UNALLOCATED / IDLE CASH:
1. Idle Cash at 0.0% (Trading Account balance baseline)
2. Idle Cash in Liquid Fund / T-Bills (6.0% p.a. annualized daily yield)
3. Idle Cash parked in Gold ETF (GOLDBEES historical daily price tracking)
"""

import sys
import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
sys.path.insert(0, str(BASE_DIR))

from scripts.run_gfs_concentrated_regime_backtest import (
    load_data_and_regimes,
    rank_candidates
)

print("Loading GFS data and market regimes...")
signals_df, stock_date_lookup, all_trading_days, nifty_regime_map = load_data_and_regimes()

# Load GOLDBEES prices
conn = sqlite3.connect(BASE_DIR / "data" / "indian_market.db")
gold_raw = pd.read_sql("SELECT date, open, close FROM daily_ohlcv WHERE security_id = 2628 ORDER BY date ASC;", conn)
conn.close()

gold_lookup = {}
for _, row in gold_raw.iterrows():
    gold_lookup[str(row["date"])] = {"open": float(row["open"]), "close": float(row["close"])}

INITIAL_CAPITAL = 10_000_000.0 # ₹1 Crore
CAPACITY = 10

def run_gfs_with_cash_vehicle(cash_vehicle="none", liquid_yield_pa=6.0):
    """
    cash_vehicle:
      - 'none': cash sits at 0%
      - 'liquid': idle cash earns liquid_yield_pa% annualized daily
      - 'gold': idle cash is deployed into GOLDBEES
    """
    cost_stock_bps = 25.0
    cost_stock_entry = 1.0 + (cost_stock_bps / 10000.0)
    cost_stock_exit = 1.0 - (cost_stock_bps / 10000.0)
    
    cost_gold_bps = 10.0
    cost_gold_entry = 1.0 + (cost_gold_bps / 10000.0)
    cost_gold_exit = 1.0 - (cost_gold_bps / 10000.0)

    daily_liquid_yield = (liquid_yield_pa / 100.0) / 252.0
    exp_sch = {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30}

    sig_by_date = {}
    for sig in signals_df.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in all_trading_days if "2018-01-01" <= d <= "2026-08-21"]
    
    cash = INITIAL_CAPITAL
    gold_units = 0.0
    open_positions = {}
    closed_trades = []
    daily_stats = []

    # If starting in gold, buy gold on first day
    first_date = sim_dates[0]
    if cash_vehicle == "gold":
        g_p = gold_lookup.get(first_date, {}).get("open", 26.44) * cost_gold_entry
        gold_units = cash / g_p
        cash = 0.0

    for d_idx, d in enumerate(sim_dates):
        # Current gold price
        g_data = gold_lookup.get(d)
        g_op = g_data["open"] if g_data else 26.44
        g_cp = g_data["close"] if g_data else g_op

        # 1. Earn liquid yield on idle cash if applicable
        if cash_vehicle == "liquid":
            cash += cash * daily_liquid_yield

        # 2. Exits at open
        to_close = []
        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is None:
                continue
            op, cp = r["open"], r["close"]
            pos["last_close"] = cp
            pos["holding_days"] += 1

            if pos.get("pending_exit"):
                exit_price = op * cost_stock_exit
                ret_pct = (exit_price - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
                trade_pnl = pos["shares"] * (exit_price - pos["sim_entry_price"])
                proceeds = pos["shares"] * exit_price

                if cash_vehicle == "gold":
                    # Sweep proceeds into gold at today open
                    buy_gold_p = g_op * cost_gold_entry
                    gold_units += proceeds / buy_gold_p
                else:
                    cash += proceeds

                closed_trades.append({
                    "symbol": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "return_pct": ret_pct,
                    "pnl_inr": trade_pnl,
                    "holding_days": pos["holding_days"]
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # 3. Portfolio Valuation
        stock_invested = sum(p["shares"] * p["last_close"] for p in open_positions.values())
        gold_val = gold_units * g_cp
        total_equity = cash + gold_val + stock_invested

        regime = nifty_regime_map.get(d, "NEUTRAL")
        regime_factor = exp_sch.get(regime, 1.0)
        max_allowed_stock_equity = total_equity * regime_factor
        max_allowed_positions = max(1, int(round(CAPACITY * regime_factor)))

        # 4. Entries
        prev_d = sim_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        avail_liquid_funds = cash if cash_vehicle != "gold" else (gold_units * g_op * cost_gold_exit)

        if day_signals and len(open_positions) < max_allowed_positions and stock_invested < max_allowed_stock_equity and avail_liquid_funds > 10000.0:
            cands = [s for s in day_signals if s["symbol"] not in open_positions]
            if cands:
                ranked = rank_candidates(cands, "weekly_rsi")
                avail_slots = max_allowed_positions - len(open_positions)
                alloc_per_slot = total_equity / CAPACITY

                for cand in ranked[:avail_slots]:
                    s_sym = cand["symbol"]
                    raw_entry_p = cand["entry_price"]
                    sim_entry_p = raw_entry_p * cost_stock_entry
                    
                    req_alloc = min(avail_liquid_funds, alloc_per_slot)
                    if req_alloc > 10000.0 and (stock_invested + req_alloc) <= (max_allowed_stock_equity * 1.05):
                        if cash_vehicle == "gold":
                            # Sell gold to fund stock purchase
                            sell_gold_p = g_op * cost_gold_exit
                            units_to_sell = req_alloc / sell_gold_p
                            if units_to_sell > gold_units:
                                units_to_sell = gold_units
                                req_alloc = units_to_sell * sell_gold_p
                            gold_units -= units_to_sell
                            avail_liquid_funds -= req_alloc
                        else:
                            cash -= req_alloc
                            avail_liquid_funds -= req_alloc

                        shares = req_alloc / sim_entry_p
                        stock_invested += req_alloc
                        open_positions[s_sym] = {
                            "symbol": s_sym,
                            "entry_date": d,
                            "sim_entry_price": sim_entry_p,
                            "shares": shares,
                            "last_close": raw_entry_p,
                            "holding_days": 0,
                            "pending_exit": False
                        }

        # 5. Month-end review
        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is not None and r["is_month_end"]:
                m_close = r["m_close"]
                m_ema9 = r["m_ema9"]
                if pd.notna(m_close) and pd.notna(m_ema9) and m_close < m_ema9:
                    pos["pending_exit"] = True

        daily_stats.append({
            "date": d,
            "equity": round(total_equity, 2),
            "cash": round(cash, 2),
            "gold_val": round(gold_val, 2),
            "stock_invested": round(stock_invested, 2),
            "positions": len(open_positions)
        })

    d_df = pd.DataFrame(daily_stats)
    d_df["cummax"] = d_df["equity"].cummax()
    d_df["drawdown"] = (d_df["equity"] - d_df["cummax"]) / d_df["cummax"] * 100.0

    end_eq = d_df["equity"].iloc[-1]
    years = (pd.to_datetime(sim_dates[-1]) - pd.to_datetime(sim_dates[0])).days / 365.25
    cagr = ((end_eq / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0
    tot_ret = (end_eq - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100.0
    mdd = d_df["drawdown"].min()
    
    wins = [t for t in closed_trades if t["pnl_inr"] > 0]
    losses = [t for t in closed_trades if t["pnl_inr"] <= 0]
    pf = (sum(t["pnl_inr"] for t in wins) / abs(sum(t["pnl_inr"] for t in losses))) if losses and sum(t["pnl_inr"] for t in losses) != 0 else np.nan

    return {
        "cash_vehicle": cash_vehicle,
        "end_equity": end_eq,
        "total_return": tot_ret,
        "cagr": cagr,
        "max_drawdown": mdd,
        "profit_factor": pf,
        "trades": len(closed_trades),
        "daily_df": d_df
    }

print("\nRunning Cash Parking Simulations across 2018-2026 (₹1 Crore Initial)...")
res_zero = run_gfs_with_cash_vehicle("none")
res_liquid = run_gfs_with_cash_vehicle("liquid", liquid_yield_pa=6.5)
res_gold = run_gfs_with_cash_vehicle("gold")

print("\n" + "="*105)
print(f"{'CASH TREATMENT':<35} | {'END CAPITAL':<14} | {'NET PROFIT':<14} | {'CAGR':<8} | {'MAX DD':<8} | {'PF':<5}")
print("="*105)
print(f"{'1. Baseline: Idle Cash at 0.0%':<35} | ₹{res_zero['end_equity']/1e7:>6.2f} Crores | +₹{(res_zero['end_equity']-INITIAL_CAPITAL)/1e7:>5.2f} Cr  | {res_zero['cagr']:>6.2f}% | {res_zero['max_drawdown']:>6.2f}% | {res_zero['profit_factor']:>5.2f}")
print(f"{'2. Idle Cash in Liquid Funds (6.5% p.a.)':<35} | ₹{res_liquid['end_equity']/1e7:>6.2f} Crores | +₹{(res_liquid['end_equity']-INITIAL_CAPITAL)/1e7:>5.2f} Cr  | {res_liquid['cagr']:>6.2f}% | {res_liquid['max_drawdown']:>6.2f}% | {res_liquid['profit_factor']:>5.2f}")
print(f"{'3. Idle Cash in Gold ETF (GOLDBEES)':<35} | ₹{res_gold['end_equity']/1e7:>6.2f} Crores | +₹{(res_gold['end_equity']-INITIAL_CAPITAL)/1e7:>5.2f} Cr  | {res_gold['cagr']:>6.2f}% | {res_gold['max_drawdown']:>6.2f}% | {res_gold['profit_factor']:>5.2f}")
print("="*105)

# Save comparison CSV
comp_df = pd.DataFrame({
    "date": res_zero["daily_df"]["date"],
    "gfs_cash_zero_yield": res_zero["daily_df"]["equity"],
    "gfs_cash_liquid_fund": res_liquid["daily_df"]["equity"],
    "gfs_cash_goldbees": res_gold["daily_df"]["equity"]
})
comp_path = BASE_DIR / "reports" / "gfs_cash_parking_comparison.csv"
comp_df.to_csv(comp_path, index=False)
print(f"\nSaved comparison to {comp_path}")
