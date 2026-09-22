#!/usr/bin/env python3
"""
test_indian_dead_money_eviction.py
==================================
Simulates GFS Cash 10-Slot + Regime Schedule 1 + Gold Proxy (GOLDBEES)
across the Indian Equity Market (2018-2026, ₹1 Crore initial capital)
testing DEAD-MONEY EVICTION rules:
- Baseline: No Eviction (Standard GFS)
- Eviction at 45 days (< 3% return)
- Eviction at 60 days (< 3% return)
- Eviction at 60 days (< 0% return)
- Eviction at 90 days (< 3% return)
- Eviction at 60 days (< 5% return)
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

print("Loading Indian GFS data and market regimes...")
signals_df, stock_date_lookup, all_trading_days, nifty_regime_map = load_data_and_regimes()

# Load GOLDBEES prices
conn = sqlite3.connect(BASE_DIR / "data" / "indian_market.db")
gold_raw = pd.read_sql("SELECT date, open, close FROM daily_ohlcv WHERE security_id = 2628 ORDER BY date ASC;", conn)
conn.close()

gold_lookup = {}
last_valid_op = 26.44
last_valid_cp = 26.44
for _, row in gold_raw.iterrows():
    op, cp = float(row["open"]), float(row["close"])
    if op < 10.0 or op > 200.0:
        op = last_valid_op
    if cp < 10.0 or cp > 200.0:
        cp = last_valid_cp
    last_valid_op = op
    last_valid_cp = cp
    gold_lookup[str(row["date"])] = {"open": op, "close": cp}

INITIAL_CAPITAL = 10_000_000.0 # ₹1 Crore
CAPACITY = 10

def run_indian_gfs(dead_money_days=0, dead_money_thresh=3.0):
    cost_stock_bps = 25.0
    cost_stock_entry = 1.0 + (cost_stock_bps / 10000.0)
    cost_stock_exit = 1.0 - (cost_stock_bps / 10000.0)
    
    cost_gold_bps = 10.0
    cost_gold_entry = 1.0 + (cost_gold_bps / 10000.0)
    cost_gold_exit = 1.0 - (cost_gold_bps / 10000.0)

    exp_sch = {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30}

    sig_by_date = {}
    for sig in signals_df.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in all_trading_days if "2018-01-01" <= d <= "2026-08-21"]
    
    cash = 0.0
    first_date = sim_dates[0]
    g_p = gold_lookup.get(first_date, {}).get("open", 26.44) * cost_gold_entry
    gold_units = INITIAL_CAPITAL / g_p

    open_positions = {}
    closed_trades = []
    daily_stats = []

    for d_idx, d in enumerate(sim_dates):
        g_data = gold_lookup.get(d)
        g_op = g_data["open"] if g_data else 26.44
        g_cp = g_data["close"] if g_data else g_op

        # 1. Exits at Open
        to_close = []
        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is None:
                continue
            op, cp = r["open"], r["close"]
            pos["last_close"] = cp
            pos["holding_days"] += 1
            pos["unrealized_ret"] = (op - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0

            should_exit = False
            exit_reason = ""

            if pos.get("pending_exit"):
                should_exit = True
                exit_reason = "MONTHLY_EMA_BREAK"
            elif dead_money_days > 0 and pos["holding_days"] >= dead_money_days and pos["unrealized_ret"] < dead_money_thresh:
                should_exit = True
                exit_reason = "DEAD_MONEY_EVICTION"

            if should_exit:
                exit_price = op * cost_stock_exit
                ret_pct = (exit_price - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
                trade_pnl = pos["shares"] * (exit_price - pos["sim_entry_price"])
                proceeds = pos["shares"] * exit_price

                # Reinvest proceeds into GOLDBEES
                buy_gold_p = g_op * cost_gold_entry
                gold_units += proceeds / buy_gold_p

                closed_trades.append({
                    "symbol": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "return_pct": ret_pct,
                    "pnl_inr": trade_pnl,
                    "holding_days": pos["holding_days"],
                    "exit_reason": exit_reason
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # 2. Portfolio Valuation
        stock_invested = sum(p["shares"] * p["last_close"] for p in open_positions.values())
        gold_val = gold_units * g_cp
        total_equity = cash + gold_val + stock_invested

        regime = nifty_regime_map.get(d, "NEUTRAL")
        regime_factor = exp_sch.get(regime, 1.0)
        max_allowed_stock_equity = total_equity * regime_factor
        max_allowed_positions = max(1, int(round(CAPACITY * regime_factor)))

        # 3. Entries
        prev_d = sim_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        avail_liquid_funds = gold_units * g_op * cost_gold_exit

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
                        sell_gold_p = g_op * cost_gold_exit
                        units_to_sell = req_alloc / sell_gold_p
                        if units_to_sell > gold_units:
                            units_to_sell = gold_units
                            req_alloc = units_to_sell * sell_gold_p
                        gold_units -= units_to_sell
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
                            "unrealized_ret": 0.0,
                            "pending_exit": False
                        }

        # 4. Month-End Check
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
        "end_equity": end_eq,
        "tot_ret": tot_ret,
        "cagr": cagr,
        "max_drawdown": mdd,
        "profit_factor": pf,
        "trades": len(closed_trades),
        "trades_list": closed_trades,
        "daily_df": d_df
    }

if __name__ == "__main__":
    setups = [
        ("1. Baseline (No Eviction - Original GFS)", 0, 3.0),
        ("2. Eviction at 45 Days (< +3% Return)", 45, 3.0),
        ("3. Eviction at 60 Days (< +3% Return)", 60, 3.0),
        ("4. Eviction at 60 Days (< 0% Return)", 60, 0.0),
        ("5. Eviction at 60 Days (< +5% Return)", 60, 5.0),
        ("6. Eviction at 90 Days (< +3% Return)", 90, 3.0),
    ]

    results = []
    print("\n" + "="*110)
    print(f"{'INDIAN MARKET SETUP (₹1 CRORE INITIAL, 2018-2026)':<48} | {'END VALUE (₹)':<15} | {'CAGR':<8} | {'MAX DD':<8} | {'PF':<5} | {'TRADES'}")
    print("="*110)

    for name, days, thresh in setups:
        r = run_indian_gfs(dead_money_days=days, dead_money_thresh=thresh)
        results.append((name, r))
        print(f"{name:<48} | ₹{r['end_equity']/1e7:>7.2f} Crores | {r['cagr']:>6.2f}% | {r['max_drawdown']:>6.2f}% | {r['profit_factor']:>5.2f} | {r['trades']}")
    print("="*110)

    # Save comparison CSV
    comp_df = pd.DataFrame({"date": results[0][1]["daily_df"]["date"]})
    for name, r in results:
        col = name.split(". ")[1].split(" (")[0].replace(" ", "_").lower()
        comp_df[col] = r["daily_df"]["equity"]
    comp_path = BASE_DIR / "reports" / "gfs_indian_dead_money_comparison.csv"
    comp_df.to_csv(comp_path, index=False)
    print(f"\nSaved daily curves to {comp_path}")

    # Best Setup trade log
    best_idx = max(range(len(results)), key=lambda i: results[i][1]["end_equity"])
    best_name, best_r = results[best_idx]
    best_trades_df = pd.DataFrame(best_r["trades_list"]).sort_values("pnl_inr", ascending=False)
    trades_path = BASE_DIR / "reports" / "gfs_indian_dead_money_trades.csv"
    best_trades_df.to_csv(trades_path, index=False)
    print(f"Saved {best_name} trade log to {trades_path}")
    print(f"\nTOP 10 WINNERS UNDER {best_name}:")
    print(best_trades_df[["symbol", "entry_date", "exit_date", "return_pct", "pnl_inr", "holding_days", "exit_reason"]].head(10).to_string(index=False))
