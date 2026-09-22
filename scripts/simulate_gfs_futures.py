#!/usr/bin/env python3
"""
simulate_gfs_futures.py
=======================
Simulates the GFS Strategy exclusively on the NSE F&O UNIVERSE (184 liquid stocks)
across multiple leverage tiers:
1. 1.0x Leverage (Cash equivalent / 100% margin buffer with 6.5% collateral yield)
2. 1.5x Effective Leverage
3. 2.0x Effective Leverage
4. 2.5x Effective Leverage
5. 3.0x Effective Leverage

Includes:
- Rollover cost (contango / cost-of-carry: 0.40% per month)
- Daily Mark-to-Market (MTM) calculation
- Margin call / liquidation monitoring
- Starting Capital: ₹1,00,00,000 (1 Crore)
- Period: 2018-01-01 to 2026-08-24 (8.64 Years)
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
    rank_candidates
)

# Standard NSE F&O Symbols
FNO_SYMBOLS = {
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENT", "ADANIPORTS", 
    "ALKEM", "AMBUJACEM", "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", 
    "ATUL", "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", 
    "BALKRISIND", "BALRAMCHIN", "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BEL", "BERGEPAINT", 
    "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BOSCHLTD", "BPCL", "BRITANNIA", "BSOFT", 
    "CANBK", "CANFINHOME", "CHAMBLFERT", "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE", 
    "COLPAL", "CONCOR", "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DABUR", "DALBHARAT", 
    "DEEPAKNTR", "DELTACORP", "DIVISLAB", "DIXON", "DLF", "DRREDDY", "EICHERMOT", "ESCORTS", 
    "EXIDEIND", "FEDERALBNK", "GAIL", "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP", 
    "GRANULES", "GRASIM", "GUJGASLTD", "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", 
    "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDCOPPER", "HINDPETRO", "HINDUNILVR", "IBULHSGFIN", 
    "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFC", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", 
    "INDIACEM", "INDIAMART", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "IOC", "IPCALAB", 
    "IRCTC", "ITC", "JINDALSTEL", "JKCEMENT", "JSWSTEEL", "JUBLFOOD", "KOTAKBANK", "L&TFH", 
    "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LT", "LTIM", "LTTS", "LUPIN", "M&M", "M&MFIN", 
    "MANAPPURAM", "MARICO", "MARUTI", "MCDOWELL-N", "MCX", "METROPOLIS", "MFSL", "MGL", 
    "MOTHERSON", "MPHASIS", "MRF", "MUTHOOTFIN", "NATIONALUM", "NAUKRI", "NAVINFLUOR", 
    "NESTLEIND", "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "ONGC", "PAGEIND", "PEL", "PERSISTENT", 
    "PETRONET", "PFC", "PIDILITIND", "PIIND", "PNB", "POLYCAB", "POONAWALLA", "POWERGRID", 
    "PVRINOX", "RAMCOCEM", "RBLBANK", "RECLTD", "RELIANCE", "SAIL", "SBICARD", "SBILIFE", 
    "SBIN", "SHREECEM", "SIEMENS", "SRF", "SUNPHARMA", "SUNTV", "SYNGENE", "TATACHEM", 
    "TATACOMM", "TATACONSUM", "TATAMOTORS", "TATAPOWER", "TATASTEEL", "TCS", "TECHM", 
    "TITAN", "TORNTPHARM", "TORNTPOWER", "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO", "UPL", 
    "VEDL", "VOLTAS", "WIPRO", "ZEEL", "ZYDUSLIFE"
}

print("Loading GFS data and market indicators...")
signals_df, stock_date_lookup, all_trading_days, nifty_regime_map = load_data_and_regimes()

# Filter signals strictly to F&O universe
fno_signals = signals_df[signals_df["symbol"].isin(FNO_SYMBOLS)].copy().reset_index(drop=True)
print(f"Total GFS Signals across Broad Market: {len(signals_df):,}")
print(f"Total GFS Signals in pure F&O Universe: {len(fno_signals):,}")

def simulate_gfs_futures(
    signals_subset: pd.DataFrame,
    stock_date_lookup: dict,
    all_trading_days: list,
    nifty_regime_map: dict,
    capacity: int = 10,
    leverage: float = 1.0,
    ranking_method: str = "weekly_rsi",
    regime_schedule: str = "sch1", # 100/70/30
    rollover_cost_monthly_pct: float = 0.40, # 0.40% contango/roll drag per month
    collateral_yield_annual_pct: float = 6.0, # 6.0% yield on idle/pledged margin
    initial_capital: float = 10_000_000.0 # ₹1 Crore
):
    cost_bps = 15.0 # F&O transaction cost + STT on futures is much lower than delivery!
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)
    daily_roll_drag = (rollover_cost_monthly_pct / 100.0) / 21.0
    daily_collateral_yield = (collateral_yield_annual_pct / 100.0) / 252.0

    schedules = {
        "fixed": {"BULL": 1.0, "NEUTRAL": 1.0, "BEAR": 1.0},
        "sch1": {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30},
    }
    exp_sch = schedules.get(regime_schedule, schedules["fixed"])

    sig_by_date = {}
    for sig in signals_subset.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in all_trading_days if "2018-01-01" <= d <= "2026-08-24"]
    
    account_equity = initial_capital
    free_cash = initial_capital
    open_positions = {}
    realized_trades = []
    daily_history = []
    liquidated = False

    for d_idx, d in enumerate(sim_dates):
        if liquidated:
            daily_history.append({"date": d, "equity": 0.0, "drawdown": -100.0, "positions": 0})
            continue

        # 1. Earn collateral yield on unallocated cash / pledged margin
        free_cash += free_cash * daily_collateral_yield

        # 2. Exits at Open (Month-End triggered)
        to_close = []
        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is None:
                continue
            op = r["open"]
            pos["last_price"] = op
            pos["holding_days"] += 1

            if pos.get("pending_exit"):
                exit_price = op * cost_mult_exit
                # MTM PnL on futures contract
                trade_pnl = (exit_price - pos["sim_entry_price"]) * pos["notional_shares"]
                # Return initial margin + MTM PnL to free cash
                free_cash += pos["margin_locked"] + trade_pnl
                
                trade_ret_pct = (exit_price - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
                realized_trades.append({
                    "symbol": sym,
                    "return_pct": trade_ret_pct,
                    "pnl_inr": trade_pnl,
                    "holding_days": pos["holding_days"]
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # 3. Mark to Market (MTM) on remaining open positions + deduct daily roll drag
        current_mtm_pnl = 0.0
        total_margin_locked = 0.0
        total_notional_exposure = 0.0

        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is not None:
                cp = r["close"]
                pos["last_price"] = cp
                # Roll drag (contango)
                pos["sim_entry_price"] += pos["sim_entry_price"] * daily_roll_drag

            # MTM PnL
            pos_mtm = (pos["last_price"] - pos["sim_entry_price"]) * pos["notional_shares"]
            current_mtm_pnl += pos_mtm
            total_margin_locked += pos["margin_locked"]
            total_notional_exposure += pos["notional_shares"] * pos["last_price"]

        account_equity = free_cash + total_margin_locked + current_mtm_pnl

        # Margin Call / Liquidation Check (If account equity drops below 20% of initial or below maintenance margin)
        maintenance_margin_required = total_notional_exposure * 0.15 # 15% SPAN maintenance
        if account_equity <= maintenance_margin_required * 0.50 or account_equity <= initial_capital * 0.10:
            liquidated = True
            print(f"  [ALERT] LIQUIDATION / MARGIN CALL on {d}! Account equity ₹{account_equity:,.0f} fell below maintenance margin.")
            continue

        # 4. Regime exposure target
        regime = nifty_regime_map.get(d, "NEUTRAL")
        regime_factor = exp_sch.get(regime, 1.0)
        max_allowed_positions = max(1, int(round(capacity * regime_factor)))
        target_total_notional = account_equity * leverage * regime_factor

        # 5. New Entries
        prev_d = sim_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        if day_signals and len(open_positions) < max_allowed_positions and total_notional_exposure < target_total_notional and free_cash > 10000.0:
            cands = [s for s in day_signals if s["symbol"] not in open_positions]
            if cands:
                ranked_cands = rank_candidates(cands, ranking_method)
                avail_slots = max_allowed_positions - len(open_positions)
                notional_per_slot = (account_equity * leverage) / capacity
                margin_per_slot = notional_per_slot / leverage  # margin locked = equity / capacity

                for cand in ranked_cands[:avail_slots]:
                    s_sym = cand["symbol"]
                    raw_entry_p = cand["entry_price"]
                    sim_entry_p = raw_entry_p * cost_mult_entry

                    # Margin required is 1/leverage of notional
                    req_margin = margin_per_slot
                    if free_cash >= req_margin and (total_notional_exposure + notional_per_slot) <= (target_total_notional * 1.05):
                        shares = notional_per_slot / sim_entry_p
                        free_cash -= req_margin
                        total_notional_exposure += notional_per_slot

                        open_positions[s_sym] = {
                            "symbol": s_sym,
                            "entry_date": d,
                            "raw_entry_price": raw_entry_p,
                            "sim_entry_price": sim_entry_p,
                            "notional_shares": shares,
                            "margin_locked": req_margin,
                            "last_price": raw_entry_p,
                            "holding_days": 0,
                            "pending_exit": False
                        }

        # 6. Month-End Review Check (Monthly Close vs Monthly EMA9)
        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is not None and r["is_month_end"]:
                m_close = r["m_close"]
                m_ema9 = r["m_ema9"]
                if pd.notna(m_close) and pd.notna(m_ema9) and m_close < m_ema9:
                    pos["pending_exit"] = True

        # EOD Record
        daily_history.append({
            "date": d,
            "equity": account_equity,
            "notional_exposure": total_notional_exposure,
            "free_cash": free_cash,
            "positions": len(open_positions)
        })

    p_df = pd.DataFrame(daily_history)
    p_df["peak"] = p_df["equity"].cummax()
    p_df["drawdown"] = (p_df["equity"] - p_df["peak"]) / p_df["peak"] * 100.0

    end_eq = p_df["equity"].iloc[-1]
    years = (pd.to_datetime(sim_dates[-1]) - pd.to_datetime(sim_dates[0])).days / 365.25
    cagr = ((end_eq / initial_capital) ** (1.0 / years) - 1.0) * 100.0 if end_eq > 0 else -100.0
    tot_ret = (end_eq - initial_capital) / initial_capital * 100.0
    mdd = p_df["drawdown"].min()
    wr = (sum(1 for t in realized_trades if t["return_pct"] > 0) / len(realized_trades) * 100.0) if realized_trades else 0.0
    
    wins = [t for t in realized_trades if t["pnl_inr"] > 0]
    losses = [t for t in realized_trades if t["pnl_inr"] <= 0]
    pf = (sum(t["pnl_inr"] for t in wins) / abs(sum(t["pnl_inr"] for t in losses))) if losses and sum(t["pnl_inr"] for t in losses) != 0 else np.nan

    return {
        "leverage": leverage,
        "ending_capital": end_eq,
        "total_return": tot_ret,
        "cagr": cagr,
        "max_drawdown": mdd,
        "profit_factor": pf,
        "win_rate": wr,
        "trades_taken": len(realized_trades),
        "daily_df": p_df
    }

print("\n" + "="*100)
print("FUTURES SIMULATION: GFS 10-SLOT + REGIME SCHEDULE 1 ACROSS LEVERAGE TIERS")
print("Universe: 184 NSE F&O Liquid Stocks | Starting Capital: ₹1,00,00,000 (1 Crore)")
print("Rollover Contango Drag: -0.40%/mo | Collateral Margin Yield: +6.0%/yr")
print("="*100)

leverage_tiers = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
results = []

for lev in leverage_tiers:
    r = simulate_gfs_futures(
        signals_subset=fno_signals,
        stock_date_lookup=stock_date_lookup,
        all_trading_days=all_trading_days,
        nifty_regime_map=nifty_regime_map,
        capacity=10,
        leverage=lev,
        ranking_method="weekly_rsi",
        regime_schedule="sch1"
    )
    results.append(r)
    pf_str = f"{r['profit_factor']:>6.2f}" if pd.notna(r['profit_factor']) else "   N/A"
    print(f"Leverage {lev:>4.2f}x | End Capital: ₹{r['ending_capital']/1e7:>7.2f} Cr ({r['total_return']:>+7.1f}%) | CAGR: {r['cagr']:>6.2f}% | MaxDD: {r['max_drawdown']:>6.2f}% | PF: {pf_str} | Trades: {r['trades_taken']}")

# Save comparison to CSV
fno_comp_df = pd.DataFrame({"date": results[0]["daily_df"]["date"]})
for r in results:
    fno_comp_df[f"futures_{r['leverage']}x"] = r["daily_df"]["equity"].values

fno_csv_path = BASE_DIR / "reports" / "gfs_futures_leverage_comparison.csv"
fno_comp_df.to_csv(fno_csv_path, index=False)
print(f"\nSaved F&O Futures leverage simulation results to {fno_csv_path}")
