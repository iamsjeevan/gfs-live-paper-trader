#!/usr/bin/env python3
"""
simulate_fno_cash_and_hybrid.py
===============================
Simulates GFS with ₹1 Crore capital across 2018-2026:
1. GFS Cash on F&O Universe Only (184 stocks, pure cash delivery, no futures, no roll drag)
2. GFS Cash on Broad Market (all stocks, pure cash delivery)
3. GFS Hybrid (F&O stocks bought in Futures with 1.5x leverage / margin, Non-F&O bought in Cash)
"""

import sys
import os
import time
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
from scripts.simulate_gfs_futures import FNO_SYMBOLS

print("Loading GFS data and market regimes...")
signals_df, stock_date_lookup, all_trading_days, nifty_regime_map = load_data_and_regimes()

INITIAL_CAPITAL = 10_000_000.0 # ₹1 Crore

# Filter signals
fno_signals = signals_df[signals_df["symbol"].isin(FNO_SYMBOLS)].copy().reset_index(drop=True)
print(f"Total Signals: Broad Market = {len(signals_df):,}, F&O Universe = {len(fno_signals):,}")

# -------------------------------------------------------------
# 1. CASH SEGMENT: F&O STOCKS ONLY (10 Slots & 15 Slots)
# -------------------------------------------------------------
def run_cash_sim(signals_sub, capacity=10, initial_cap=10_000_000.0):
    cost_bps = 25.0
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)
    exp_sch = {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30}

    sig_by_date = {}
    for sig in signals_sub.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in all_trading_days if "2018-01-01" <= d <= "2026-08-24"]
    cash = initial_cap
    open_positions = {}
    closed_trades = []
    daily_stats = []

    for d_idx, d in enumerate(sim_dates):
        # Exits at open
        to_close = []
        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is None:
                continue
            op, cp = r["open"], r["close"]
            pos["last_close"] = cp
            pos["holding_days"] += 1

            if pos.get("pending_exit"):
                exit_price = op * cost_mult_exit
                ret_pct = (exit_price - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
                trade_pnl = pos["shares"] * (exit_price - pos["sim_entry_price"])
                cash += pos["shares"] * exit_price
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

        # Valuation
        invested = sum(p["shares"] * p["last_close"] for p in open_positions.values())
        total_equity = cash + invested

        regime = nifty_regime_map.get(d, "NEUTRAL")
        regime_factor = exp_sch.get(regime, 1.0)
        max_allowed_equity = total_equity * regime_factor
        max_allowed_positions = max(1, int(round(capacity * regime_factor)))

        # Entries
        prev_d = sim_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        if day_signals and len(open_positions) < max_allowed_positions and invested < max_allowed_equity and cash > 10000.0:
            cands = [s for s in day_signals if s["symbol"] not in open_positions]
            if cands:
                ranked = rank_candidates(cands, "weekly_rsi")
                avail_slots = max_allowed_positions - len(open_positions)
                alloc_per_slot = total_equity / capacity

                for cand in ranked[:avail_slots]:
                    s_sym = cand["symbol"]
                    raw_entry_p = cand["entry_price"]
                    sim_entry_p = raw_entry_p * cost_mult_entry
                    avail_alloc = min(cash, alloc_per_slot)

                    if avail_alloc > 10000.0 and (invested + avail_alloc) <= (max_allowed_equity * 1.05):
                        shares = avail_alloc / sim_entry_p
                        cash -= avail_alloc
                        invested += avail_alloc
                        open_positions[s_sym] = {
                            "symbol": s_sym,
                            "entry_date": d,
                            "sim_entry_price": sim_entry_p,
                            "shares": shares,
                            "last_close": raw_entry_p,
                            "holding_days": 0,
                            "pending_exit": False
                        }

        # Month-end check
        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is not None and r["is_month_end"]:
                m_close = r["m_close"]
                m_ema9 = r["m_ema9"]
                if pd.notna(m_close) and pd.notna(m_ema9) and m_close < m_ema9:
                    pos["pending_exit"] = True

        daily_stats.append({
            "date": d,
            "equity": total_equity,
            "cash": cash,
            "invested": invested,
            "positions": len(open_positions)
        })

    d_df = pd.DataFrame(daily_stats)
    d_df["cummax"] = d_df["equity"].cummax()
    d_df["drawdown"] = (d_df["equity"] - d_df["cummax"]) / d_df["cummax"] * 100.0

    end_eq = d_df["equity"].iloc[-1]
    years = (pd.to_datetime(sim_dates[-1]) - pd.to_datetime(sim_dates[0])).days / 365.25
    cagr = ((end_eq / initial_cap) ** (1.0 / years) - 1.0) * 100.0
    tot_ret = (end_eq - initial_cap) / initial_cap * 100.0
    mdd = d_df["drawdown"].min()
    wr = (sum(1 for t in closed_trades if t["return_pct"] > 0) / len(closed_trades) * 100.0) if closed_trades else 0.0

    wins = [t for t in closed_trades if t["pnl_inr"] > 0]
    losses = [t for t in closed_trades if t["pnl_inr"] <= 0]
    pf = (sum(t["pnl_inr"] for t in wins) / abs(sum(t["pnl_inr"] for t in losses))) if losses and sum(t["pnl_inr"] for t in losses) != 0 else np.nan

    return {
        "end_equity": end_eq,
        "tot_ret": tot_ret,
        "cagr": cagr,
        "max_drawdown": mdd,
        "profit_factor": pf,
        "win_rate": wr,
        "trades": closed_trades,
        "daily_df": d_df
    }

# -------------------------------------------------------------
# 2. HYBRID SIMULATION: IF F&O THEN BUY IN FUTURES (1.5x), ELSE CASH (1.0x)
# -------------------------------------------------------------
def run_hybrid_sim(signals_sub, capacity=10, initial_cap=10_000_000.0, fno_leverage=1.5):
    """
    If stock in FNO_SYMBOLS: Buy in Futures (1.5x notional, margin locked = notional / 1.5, collateral yield + roll drag)
    If stock NOT in FNO_SYMBOLS: Buy in Cash delivery (1.0x equity)
    """
    cost_cash_bps = 25.0
    cost_fno_bps = 15.0
    daily_roll_drag = (0.40 / 100.0) / 21.0
    daily_collateral_yield = (6.0 / 100.0) / 252.0
    exp_sch = {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30}

    sig_by_date = {}
    for sig in signals_sub.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in all_trading_days if "2018-01-01" <= d <= "2026-08-24"]
    free_cash = initial_cap
    open_positions = {}
    closed_trades = []
    daily_stats = []

    for d_idx, d in enumerate(sim_dates):
        # 1. Earn collateral yield on unallocated cash
        free_cash += free_cash * daily_collateral_yield

        # 2. Exits at open
        to_close = []
        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is None:
                continue
            op, cp = r["open"], r["close"]
            pos["last_price"] = op
            pos["holding_days"] += 1

            if pos.get("pending_exit"):
                is_fno = pos["is_fno"]
                c_mult = (1.0 - cost_fno_bps / 10000.0) if is_fno else (1.0 - cost_cash_bps / 10000.0)
                exit_price = op * c_mult
                trade_pnl = (exit_price - pos["sim_entry_price"]) * pos["shares"]
                ret_pct = (exit_price - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0

                if is_fno:
                    free_cash += pos["margin_locked"] + trade_pnl
                else:
                    free_cash += pos["shares"] * exit_price

                closed_trades.append({
                    "symbol": sym,
                    "is_fno": is_fno,
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "return_pct": ret_pct,
                    "pnl_inr": trade_pnl,
                    "holding_days": pos["holding_days"]
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # 3. Mark to Market & Roll Drag on remaining positions
        current_fno_mtm = 0.0
        total_margin_locked = 0.0
        total_cash_invested = 0.0

        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is not None:
                cp = r["close"]
                pos["last_price"] = cp
                if pos["is_fno"]:
                    pos["sim_entry_price"] += pos["sim_entry_price"] * daily_roll_drag

            if pos["is_fno"]:
                pos_mtm = (pos["last_price"] - pos["sim_entry_price"]) * pos["shares"]
                current_fno_mtm += pos_mtm
                total_margin_locked += pos["margin_locked"]
            else:
                total_cash_invested += pos["shares"] * pos["last_price"]

        account_equity = free_cash + total_margin_locked + current_fno_mtm + total_cash_invested

        # 4. Regime Target
        regime = nifty_regime_map.get(d, "NEUTRAL")
        regime_factor = exp_sch.get(regime, 1.0)
        max_allowed_positions = max(1, int(round(capacity * regime_factor)))

        # 5. New Entries
        prev_d = sim_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        if day_signals and len(open_positions) < max_allowed_positions and free_cash > 10000.0:
            cands = [s for s in day_signals if s["symbol"] not in open_positions]
            if cands:
                ranked = rank_candidates(cands, "weekly_rsi")
                avail_slots = max_allowed_positions - len(open_positions)
                alloc_slot_notional = account_equity / capacity

                for cand in ranked[:avail_slots]:
                    s_sym = cand["symbol"]
                    is_fno = s_sym in FNO_SYMBOLS
                    raw_entry_p = cand["entry_price"]

                    if is_fno:
                        sim_entry_p = raw_entry_p * (1.0 + cost_fno_bps / 10000.0)
                        fno_notional = alloc_slot_notional * fno_leverage
                        req_margin = alloc_slot_notional # 1x margin locked, gives 1.5x notional exposure
                        if free_cash >= req_margin:
                            shares = fno_notional / sim_entry_p
                            free_cash -= req_margin
                            open_positions[s_sym] = {
                                "symbol": s_sym,
                                "is_fno": True,
                                "entry_date": d,
                                "sim_entry_price": sim_entry_p,
                                "shares": shares,
                                "margin_locked": req_margin,
                                "last_price": raw_entry_p,
                                "holding_days": 0,
                                "pending_exit": False
                            }
                    else:
                        sim_entry_p = raw_entry_p * (1.0 + cost_cash_bps / 10000.0)
                        cash_alloc = alloc_slot_notional
                        if free_cash >= cash_alloc:
                            shares = cash_alloc / sim_entry_p
                            free_cash -= cash_alloc
                            open_positions[s_sym] = {
                                "symbol": s_sym,
                                "is_fno": False,
                                "entry_date": d,
                                "sim_entry_price": sim_entry_p,
                                "shares": shares,
                                "margin_locked": 0.0,
                                "last_price": raw_entry_p,
                                "holding_days": 0,
                                "pending_exit": False
                            }

        # 6. Month-end review
        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is not None and r["is_month_end"]:
                m_close = r["m_close"]
                m_ema9 = r["m_ema9"]
                if pd.notna(m_close) and pd.notna(m_ema9) and m_close < m_ema9:
                    pos["pending_exit"] = True

        daily_stats.append({
            "date": d,
            "equity": account_equity,
            "free_cash": free_cash,
            "positions": len(open_positions)
        })

    d_df = pd.DataFrame(daily_stats)
    d_df["cummax"] = d_df["equity"].cummax()
    d_df["drawdown"] = (d_df["equity"] - d_df["cummax"]) / d_df["cummax"] * 100.0

    end_eq = d_df["equity"].iloc[-1]
    years = (pd.to_datetime(sim_dates[-1]) - pd.to_datetime(sim_dates[0])).days / 365.25
    cagr = ((end_eq / initial_cap) ** (1.0 / years) - 1.0) * 100.0
    tot_ret = (end_eq - initial_cap) / initial_cap * 100.0
    mdd = d_df["drawdown"].min()
    wr = (sum(1 for t in closed_trades if t["return_pct"] > 0) / len(closed_trades) * 100.0) if closed_trades else 0.0

    wins = [t for t in closed_trades if t["pnl_inr"] > 0]
    losses = [t for t in closed_trades if t["pnl_inr"] <= 0]
    pf = (sum(t["pnl_inr"] for t in wins) / abs(sum(t["pnl_inr"] for t in losses))) if losses and sum(t["pnl_inr"] for t in losses) != 0 else np.nan

    return {
        "end_equity": end_eq,
        "tot_ret": tot_ret,
        "cagr": cagr,
        "max_drawdown": mdd,
        "profit_factor": pf,
        "win_rate": wr,
        "trades": closed_trades,
        "daily_df": d_df
    }

# Run Simulations
print("\nRunning Cash F&O and Broad simulations...")
res_fno_10 = run_cash_sim(fno_signals, capacity=10)
res_fno_15 = run_cash_sim(fno_signals, capacity=15)
res_broad_10 = run_cash_sim(signals_df, capacity=10)
res_hybrid = run_hybrid_sim(signals_df, capacity=10, fno_leverage=1.5)

print("\n" + "="*100)
print(f"{'STRATEGY SETUP (₹1 CRORE CAPITAL, 2018-2026)':<48} | {'END CAPITAL':<12} | {'CAGR':<8} | {'MAX DD':<8} | {'PF':<6} | {'TRADES'}")
print("="*100)
print(f"{'1. Pure Cash - F&O Stocks Only (10 Slots)':<48} | ₹{res_fno_10['end_equity']/1e7:>5.2f} Cr  | {res_fno_10['cagr']:>6.2f}% | {res_fno_10['max_drawdown']:>6.2f}% | {res_fno_10['profit_factor']:>5.2f} | {len(res_fno_10['trades'])}")
print(f"{'2. Pure Cash - F&O Stocks Only (15 Slots)':<48} | ₹{res_fno_15['end_equity']/1e7:>5.2f} Cr  | {res_fno_15['cagr']:>6.2f}% | {res_fno_15['max_drawdown']:>6.2f}% | {res_fno_15['profit_factor']:>5.2f} | {len(res_fno_15['trades'])}")
print(f"{'3. Hybrid: If F&O buy Futures (1.5x), else Cash':<48} | ₹{res_hybrid['end_equity']/1e7:>5.2f} Cr  | {res_hybrid['cagr']:>6.2f}% | {res_hybrid['max_drawdown']:>6.2f}% | {res_hybrid['profit_factor']:>5.2f} | {len(res_hybrid['trades'])}")
print(f"{'4. Pure Cash - Broad Market All Stocks (10 Slots)':<48} | ₹{res_broad_10['end_equity']/1e7:>5.2f} Cr  | {res_broad_10['cagr']:>6.2f}% | {res_broad_10['max_drawdown']:>6.2f}% | {res_broad_10['profit_factor']:>5.2f} | {len(res_broad_10['trades'])}")
print("="*100)

# Save summary
comp_daily = pd.DataFrame({
    "date": res_fno_10["daily_df"]["date"],
    "cash_fno_10_slot": res_fno_10["daily_df"]["equity"],
    "cash_fno_15_slot": res_fno_15["daily_df"]["equity"],
    "hybrid_10_slot": res_hybrid["daily_df"]["equity"],
    "cash_broad_10_slot": res_broad_10["daily_df"]["equity"]
})
comp_csv_path = BASE_DIR / "reports" / "gfs_fno_cash_and_hybrid_1cr.csv"
comp_daily.to_csv(comp_csv_path, index=False)
print(f"\nSaved daily equity curves to {comp_csv_path}")
