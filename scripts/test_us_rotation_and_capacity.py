#!/usr/bin/env python3
"""
test_us_rotation_and_capacity.py
================================
Tests the user's two core hypotheses for the US Market:
1. CAPACITY EXPANSION: 10 Slots vs 15 Slots vs 20 Slots vs 25 Slots
2. LAGGARD EVICTION / MOMENTUM ROTATION:
   - "Dead-Money Eviction": If an older position is held >= 60 days and return < +3%, evict it to free up capacity.
   - "Relative Strength Hot-Swap": If portfolio is full and a new candidate triggers, swap out the worst-performing laggard (< 0% return after >= 30 days).
   - Exit Rule: Monthly EMA 13 vs Monthly EMA 9.
"""

import sys
import time
import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
DB_PATH = BASE_DIR / "instocks.db"
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = "2018-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 1_000_000.0 # $1M

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)

def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def load_data(ema_span=13):
    t0 = time.time()
    print("Loading liquid US stocks ($1M+ daily turnover) from instocks.db...")
    conn = sqlite3.connect(DB_PATH)

    # 1. S&P 500 Market Regime
    sp500_df = pd.read_sql("SELECT Date, Adj_Close FROM daily_prices WHERE Ticker = '^GSPC' ORDER BY Date ASC;", conn)
    sp500_df["ema200"] = compute_ema(sp500_df["Adj_Close"], 200)
    sp500_df["ema50"] = compute_ema(sp500_df["Adj_Close"], 50)
    sp500_df["bull_flag"] = (sp500_df["Adj_Close"] > sp500_df["ema200"]) & (sp500_df["Adj_Close"] > sp500_df["ema50"])
    sp500_df["bear_flag"] = sp500_df["Adj_Close"] <= sp500_df["ema200"]
    sp500_df["regime"] = "NEUTRAL"
    sp500_df.loc[sp500_df["bull_flag"], "regime"] = "BULL"
    sp500_df.loc[sp500_df["bear_flag"], "regime"] = "BEAR"
    regime_map = dict(zip(sp500_df["Date"], sp500_df["regime"]))
    sp500_close_map = dict(zip(sp500_df["Date"], sp500_df["Adj_Close"]))

    # 2. Select top liquid tickers (average dollar volume >= $1M)
    liquid_tickers_df = pd.read_sql("""
        SELECT Ticker, COUNT(*) as bars, AVG(Adj_Close * Volume) as avg_dvol
        FROM daily_prices
        WHERE Date >= '2018-01-01' AND Ticker != '^GSPC'
        GROUP BY Ticker
        HAVING bars >= 500 AND avg_dvol >= 1000000;
    """, conn)
    liquid_tickers = set(liquid_tickers_df["Ticker"])
    print(f"Selected {len(liquid_tickers):,} highly liquid US tickers in {time.time()-t0:.2f}s.")

    # 3. Load daily prices for liquid tickers
    t1 = time.time()
    raw_df = pd.read_sql(f"""
        SELECT Date, Ticker, Adj_Close, Volume 
        FROM daily_prices 
        WHERE Date >= '2015-01-01' AND Ticker IN ({','.join(['?']*len(liquid_tickers))})
        ORDER BY Ticker, Date ASC;
    """, conn, params=list(liquid_tickers))
    conn.close()
    print(f"Loaded {len(raw_df):,} daily bars in {time.time()-t1:.2f}s.")

    # 4. GLD prices
    gld_df = yf.download("GLD", start="2015-01-01", end="2026-08-26", progress=False)
    if isinstance(gld_df.columns, pd.MultiIndex):
        gld_close = gld_df["Close"]["GLD"]
    else:
        gld_close = gld_df["Close"]
    gld_map = {d.strftime("%Y-%m-%d"): float(p) for d, p in gld_close.items()}

    # 5. Process Indicators & Signals
    t2 = time.time()
    print(f"Computing multi-timeframe indicators (Monthly EMA {ema_span})...")
    stock_lookup = {}
    all_signals = []
    all_dates = sorted(list(set(sp500_df["Date"])))

    for ticker, g in raw_df.groupby("Ticker"):
        g = g.sort_values("Date").copy()
        if len(g) < 60:
            continue

        g["daily_rsi"] = compute_rsi(g["Adj_Close"], 14)
        g["prev_daily_rsi"] = g["daily_rsi"].shift(1)

        g_dt = pd.to_datetime(g["Date"])
        g["year_week"] = g_dt.dt.strftime("%Y-W%U")
        w_df = g.groupby("year_week").agg(w_close=("Adj_Close", "last")).reset_index()
        w_df["weekly_rsi"] = compute_rsi(w_df["w_close"], 14).shift(1)
        w_map = dict(zip(w_df["year_week"], w_df["weekly_rsi"]))
        g["weekly_rsi"] = g["year_week"].map(w_map)

        g["year_month"] = g_dt.dt.strftime("%Y-%m")
        m_df = g.groupby("year_month").agg(
            m_close=("Adj_Close", "last"),
            last_date=("Date", "last")
        ).reset_index()
        m_df["monthly_rsi"] = compute_rsi(m_df["m_close"], 14).shift(1)
        m_df["m_ema"] = compute_ema(m_df["m_close"], ema_span)
        m_map_rsi = dict(zip(m_df["year_month"], m_df["monthly_rsi"]))
        m_map_ema = dict(zip(m_df["last_date"], m_df["m_ema"]))
        m_map_close = dict(zip(m_df["last_date"], m_df["m_close"]))
        g["monthly_rsi"] = g["year_month"].map(m_map_rsi)

        m_end_dates = set(m_df["last_date"].values)
        g["is_month_end"] = g["Date"].isin(m_end_dates)
        g["m_close"] = g["Date"].map(m_map_close).fillna(np.nan)
        g["m_ema"] = g["Date"].map(m_map_ema).fillna(np.nan)

        g["entry_date"] = g["Date"].shift(-1)
        g["entry_price"] = g["Adj_Close"].shift(-1)

        stock_dict = {}
        for row in g.to_dict(orient="records"):
            stock_dict[row["Date"]] = row
        stock_lookup[ticker] = stock_dict

        # Signal check (price >= $5.00, volume valid)
        son_cross = (g["prev_daily_rsi"] <= 40.0) & (g["daily_rsi"] > 40.0) & (g["entry_date"].notna())
        price_ok = (g["entry_price"] >= 5.0)
        valid_sig = son_cross & (g["weekly_rsi"] > 60.0) & (g["monthly_rsi"] > 60.0) & price_ok

        for _, row in g[valid_sig].iterrows():
            all_signals.append({
                "ticker": ticker,
                "signal_date": row["Date"],
                "entry_date": row["entry_date"],
                "entry_price": row["entry_price"],
                "weekly_rsi": row["weekly_rsi"],
                "monthly_rsi": row["monthly_rsi"]
            })

    signals_df = pd.DataFrame(all_signals)
    print(f"Processed indicators in {time.time()-t2:.2f}s. Total Signals: {len(signals_df):,}")
    return signals_df, stock_lookup, all_dates, regime_map, gld_map

def simulate_portfolio(
    signals_df,
    stock_lookup,
    all_dates,
    regime_map,
    gld_map,
    capacity=10,
    dead_money_days=0, # 0 = disabled, e.g. 60 days
    dead_money_ret_thresh=3.0, # Evict if return < 3% after dead_money_days
    enable_hotswap=False # If full, swap out worst position (< 0% after 30 days)
):
    cost_bps = 10.0
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)
    exp_sch = {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30}

    sig_by_date = {}
    for sig in signals_df.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in all_dates if START_DATE <= d <= END_DATE]
    
    cash = 0.0
    first_d = sim_dates[0]
    curr_gold_p = gld_map.get(first_d, 120.0)
    gold_units = INITIAL_CAPITAL / (curr_gold_p * cost_mult_entry)
    
    open_positions = {}
    closed_trades = []
    daily_stats = []

    for d_idx, d in enumerate(sim_dates):
        curr_gold_p = gld_map.get(d, 120.0)

        # 1. Execute Exits
        to_close = []
        for ticker, pos in open_positions.items():
            r = stock_lookup.get(ticker, {}).get(d)
            if r is None:
                continue
            p = r["Adj_Close"]
            pos["last_price"] = p
            pos["holding_days"] += 1
            pos["unrealized_ret"] = (p - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0

            # Exit reasons:
            # A. Monthly EMA break
            # B. Dead money eviction
            should_exit = False
            exit_reason = ""

            if pos.get("pending_exit"):
                should_exit = True
                exit_reason = "MONTHLY_EMA_BREAK"
            elif dead_money_days > 0 and pos["holding_days"] >= dead_money_days and pos["unrealized_ret"] < dead_money_ret_thresh:
                should_exit = True
                exit_reason = "DEAD_MONEY_EVICTION"

            if should_exit:
                exit_p = p * cost_mult_exit
                ret_pct = (exit_p - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
                trade_pnl = pos["shares"] * (exit_p - pos["sim_entry_price"])
                proceeds = pos["shares"] * exit_p

                # Sweep proceeds to gold
                buy_g_p = curr_gold_p * cost_mult_entry
                gold_units += proceeds / buy_g_p

                closed_trades.append({
                    "ticker": ticker,
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "return_pct": ret_pct,
                    "pnl_usd": trade_pnl,
                    "holding_days": pos["holding_days"],
                    "exit_reason": exit_reason
                })
                to_close.append(ticker)

        for ticker in to_close:
            del open_positions[ticker]

        # 2. Portfolio Valuation
        stock_equity = sum(p["shares"] * p["last_price"] for p in open_positions.values())
        gold_val = gold_units * curr_gold_p
        total_equity = cash + gold_val + stock_equity

        regime = regime_map.get(d, "NEUTRAL")
        regime_factor = exp_sch.get(regime, 1.0)
        max_allowed_stock_equity = total_equity * regime_factor
        max_allowed_positions = max(1, int(round(capacity * regime_factor)))

        # 3. Entries & Hot-Swapping
        prev_d = sim_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        if day_signals:
            cands = [s for s in day_signals if s["ticker"] not in open_positions]
            if cands:
                ranked = sorted(cands, key=lambda x: x.get("weekly_rsi", 0.0), reverse=True)
                alloc_per_slot = total_equity / capacity

                # Check hot-swap if portfolio full
                if enable_hotswap and len(open_positions) >= max_allowed_positions:
                    # Find worst position
                    laggards = [
                        (tk, pos) for tk, pos in open_positions.items()
                        if pos["holding_days"] >= 30 and pos["unrealized_ret"] < 0.0
                    ]
                    if laggards:
                        # Sort by lowest return
                        laggards.sort(key=lambda x: x[1]["unrealized_ret"])
                        worst_tk, worst_pos = laggards[0]
                        top_cand = ranked[0]
                        if top_cand["weekly_rsi"] >= 65.0: # High conviction swap
                            # Liquidate worst position
                            r = stock_lookup.get(worst_tk, {}).get(d)
                            p = r["Adj_Close"] if r else worst_pos["last_price"]
                            exit_p = p * cost_mult_exit
                            trade_pnl = worst_pos["shares"] * (exit_p - worst_pos["sim_entry_price"])
                            proceeds = worst_pos["shares"] * exit_p
                            gold_units += proceeds / (curr_gold_p * cost_mult_entry)

                            closed_trades.append({
                                "ticker": worst_tk,
                                "entry_date": worst_pos["entry_date"],
                                "exit_date": d,
                                "return_pct": (exit_p - worst_pos["sim_entry_price"]) / worst_pos["sim_entry_price"] * 100.0,
                                "pnl_usd": trade_pnl,
                                "holding_days": worst_pos["holding_days"],
                                "exit_reason": "HOT_SWAP_REPLACED"
                            })
                            del open_positions[worst_tk]

                # Regular entry
                avail_slots = max_allowed_positions - len(open_positions)
                avail_liquid = gold_units * curr_gold_p * cost_mult_exit

                if avail_slots > 0 and avail_liquid > 1000.0 and stock_equity < max_allowed_stock_equity:
                    for cand in ranked[:avail_slots]:
                        s_sym = cand["ticker"]
                        raw_entry_p = cand["entry_price"]
                        sim_entry_p = raw_entry_p * cost_mult_entry

                        req_alloc = min(avail_liquid, alloc_per_slot)
                        if req_alloc > 1000.0 and (stock_equity + req_alloc) <= (max_allowed_stock_equity * 1.05):
                            sell_g_p = curr_gold_p * cost_mult_exit
                            units_to_sell = req_alloc / sell_g_p
                            if units_to_sell > gold_units:
                                units_to_sell = gold_units
                                req_alloc = units_to_sell * sell_g_p
                            gold_units -= units_to_sell
                            avail_liquid -= req_alloc

                            shares = req_alloc / sim_entry_p
                            stock_equity += req_alloc
                            open_positions[s_sym] = {
                                "ticker": s_sym,
                                "entry_date": d,
                                "sim_entry_price": sim_entry_p,
                                "shares": shares,
                                "last_price": raw_entry_p,
                                "holding_days": 0,
                                "unrealized_ret": 0.0,
                                "pending_exit": False
                            }

        # 4. Month-End Check
        for ticker, pos in open_positions.items():
            r = stock_lookup.get(ticker, {}).get(d)
            if r is not None and r["is_month_end"]:
                m_close = r["m_close"]
                m_ema = r["m_ema"]
                if pd.notna(m_close) and pd.notna(m_ema) and m_close < m_ema:
                    pos["pending_exit"] = True

        daily_stats.append({"date": d, "equity": total_equity, "positions": len(open_positions)})

    d_df = pd.DataFrame(daily_stats)
    d_df["cummax"] = d_df["equity"].cummax()
    d_df["drawdown"] = (d_df["equity"] - d_df["cummax"]) / d_df["cummax"] * 100.0

    end_eq = d_df["equity"].iloc[-1]
    years = (pd.to_datetime(sim_dates[-1]) - pd.to_datetime(sim_dates[0])).days / 365.25
    cagr = ((end_eq / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0
    tot_ret = (end_eq - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100.0
    mdd = d_df["drawdown"].min()
    
    wins = [t for t in closed_trades if t["pnl_usd"] > 0]
    losses = [t for t in closed_trades if t["pnl_usd"] <= 0]
    pf = (sum(t["pnl_usd"] for t in wins) / abs(sum(t["pnl_usd"] for t in losses))) if losses and sum(t["pnl_usd"] for t in losses) != 0 else np.nan

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
    # Load with EMA 13
    signals_df, stock_lookup, all_dates, regime_map, gld_map = load_data(ema_span=13)

    setups = [
        ("1. 10 Slots Baseline (No Eviction)", 10, 0, False),
        ("2. 15 Slots Baseline (No Eviction)", 15, 0, False),
        ("3. 20 Slots Baseline (No Eviction)", 20, 0, False),
        ("4. 25 Slots Baseline (No Eviction)", 25, 0, False),
        ("5. 10 Slots + Dead-Money Eviction (60d, <3%)", 10, 60, False),
        ("6. 20 Slots + Dead-Money Eviction (60d, <3%)", 20, 60, False),
        ("7. 20 Slots + Hot-Swap Laggards (<0% @ 30d)", 20, 0, True),
        ("8. 20 Slots + Eviction + Hot-Swap (Both)", 20, 60, True),
    ]

    results = []
    print("\n" + "="*110)
    print(f"{'STRATEGY SETUP (US LIQUID UNIVERSE, $1M INITIAL)':<48} | {'END VALUE ($)':<14} | {'CAGR':<8} | {'MAX DD':<8} | {'PF':<5} | {'TRADES'}")
    print("="*110)

    for name, cap, dm_days, hotswap in setups:
        r = simulate_portfolio(
            signals_df, stock_lookup, all_dates, regime_map, gld_map,
            capacity=cap, dead_money_days=dm_days, enable_hotswap=hotswap
        )
        results.append((name, r))
        print(f"{name:<48} | ${r['end_equity']:>13,.0f} | {r['cagr']:>6.2f}% | {r['max_drawdown']:>6.2f}% | {r['profit_factor']:>5.2f} | {r['trades']}")
    print("="*110)

    # Save comparison to CSV
    comp_df = pd.DataFrame({"date": results[0][1]["daily_df"]["date"]})
    for name, r in results:
        col = name.split(". ")[1].split(" (")[0].replace(" ", "_").lower()
        comp_df[col] = r["daily_df"]["equity"]
    comp_path = REPORTS_DIR / "us_capacity_and_rotation_comparison.csv"
    comp_df.to_csv(comp_path, index=False)
    print(f"\nSaved results to {comp_path}")
