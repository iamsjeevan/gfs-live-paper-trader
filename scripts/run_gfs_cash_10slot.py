#!/usr/bin/env python3
"""
run_gfs_cash_10slot.py
======================
Standalone executable script for the winning strategy:
GFS CASH 10-SLOT + REGIME SCHEDULE 1

Outputs:
- reports/gfs_cash_10slot_regime_trades.csv (Complete list of all trades with entry, exit, PnL)
- reports/gfs_cash_10slot_regime_equity.csv (Daily equity curve, cash, invested amount, drawdown)
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
sys.path.insert(0, str(BASE_DIR))

from scripts.run_gfs_concentrated_regime_backtest import (
    load_data_and_regimes,
    rank_candidates
)

def run_strategy(initial_capital=10_000_000.0, capacity=10):
    print("Loading data & market regimes...")
    signals_df, stock_date_lookup, all_trading_days, nifty_regime_map = load_data_and_regimes()

    cost_bps = 25.0
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)
    exp_sch = {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30}

    sig_by_date = {}
    for sig in signals_df.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in all_trading_days if "2018-01-01" <= d <= "2026-08-24"]
    cash = initial_capital
    open_positions = {}
    closed_trades = []
    daily_stats = []

    for d_idx, d in enumerate(sim_dates):
        # 1. Month-end exit execution at day open
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
                    "company_name": pos.get("company_name", sym),
                    "sector": pos.get("sector", "Other"),
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "entry_price": round(pos["sim_entry_price"], 2),
                    "exit_price": round(exit_price, 2),
                    "shares": int(round(pos["shares"])),
                    "return_pct": round(ret_pct, 2),
                    "pnl_inr": round(trade_pnl, 2),
                    "holding_days": pos["holding_days"],
                    "exit_reason": "MONTHLY_CLOSE_BELOW_EMA9"
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # 2. Portfolio Valuation & Regime Limits
        invested = sum(p["shares"] * p["last_close"] for p in open_positions.values())
        total_equity = cash + invested

        regime = nifty_regime_map.get(d, "NEUTRAL")
        regime_factor = exp_sch.get(regime, 1.0)
        max_allowed_equity = total_equity * regime_factor
        max_allowed_positions = max(1, int(round(capacity * regime_factor)))

        # 3. Entries
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
                            "company_name": cand.get("company_name", s_sym),
                            "sector": cand.get("sector", "Other"),
                            "entry_date": d,
                            "sim_entry_price": sim_entry_p,
                            "shares": shares,
                            "last_close": raw_entry_p,
                            "holding_days": 0,
                            "pending_exit": False
                        }

        # 4. Month-end review check
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
            "invested": round(invested, 2),
            "regime": regime,
            "open_positions": len(open_positions)
        })

    # Add open positions at end of backtest to trade log
    last_d = sim_dates[-1]
    for sym, pos in open_positions.items():
        exit_p = pos["last_close"] * cost_mult_exit
        ret_pct = (exit_p - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
        trade_pnl = pos["shares"] * (exit_p - pos["sim_entry_price"])
        closed_trades.append({
            "symbol": sym,
            "company_name": pos.get("company_name", sym),
            "sector": pos.get("sector", "Other"),
            "entry_date": pos["entry_date"],
            "exit_date": f"{last_d} (OPEN)",
            "entry_price": round(pos["sim_entry_price"], 2),
            "exit_price": round(exit_p, 2),
            "shares": int(round(pos["shares"])),
            "return_pct": round(ret_pct, 2),
            "pnl_inr": round(trade_pnl, 2),
            "holding_days": pos["holding_days"],
            "exit_reason": "CURRENTLY_ACTIVE"
        })

    d_df = pd.DataFrame(daily_stats)
    d_df["peak"] = d_df["equity"].cummax()
    d_df["drawdown_pct"] = round((d_df["equity"] - d_df["peak"]) / d_df["peak"] * 100.0, 2)
    t_df = pd.DataFrame(closed_trades)

    # Save to dedicated CSV files
    reports_dir = BASE_DIR / "reports"
    trades_path = reports_dir / "gfs_cash_10slot_regime_trades.csv"
    equity_path = reports_dir / "gfs_cash_10slot_regime_equity.csv"
    
    t_df.to_csv(trades_path, index=False)
    d_df.to_csv(equity_path, index=False)

    end_eq = d_df["equity"].iloc[-1]
    years = (pd.to_datetime(sim_dates[-1]) - pd.to_datetime(sim_dates[0])).days / 365.25
    cagr = ((end_eq / initial_capital) ** (1.0 / years) - 1.0) * 100.0
    mdd = d_df["drawdown_pct"].min()
    
    wins = t_df[t_df["return_pct"] > 0]
    losses = t_df[t_df["return_pct"] <= 0]
    pf = (wins["pnl_inr"].sum() / abs(losses["pnl_inr"].sum())) if len(losses) > 0 else 99.0

    print("\n" + "="*80)
    print("GFS CASH 10-SLOT + REGIME SCHEDULE 1 (2018-2026)")
    print("="*80)
    print(f"Starting Capital : ₹{initial_capital:,.2f}")
    print(f"Ending Capital   : ₹{end_eq:,.2f} ({((end_eq/initial_capital)-1)*100:+.2f}%)")
    print(f"CAGR             : {cagr:.2f}%")
    print(f"Max Drawdown     : {mdd:.2f}%")
    print(f"Profit Factor    : {pf:.2f}")
    print(f"Total Trades     : {len(t_df)}")
    print(f"Win Rate         : {len(wins)/len(t_df)*100:.2f}%")
    print(f"\nFiles Generated:")
    print(f"1. Trades CSV : {trades_path}")
    print(f"2. Equity CSV : {equity_path}")
    print("="*80)

if __name__ == "__main__":
    run_strategy()
