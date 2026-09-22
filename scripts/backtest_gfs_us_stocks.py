#!/usr/bin/env python3
"""
backtest_gfs_us_stocks.py
=========================
Backtests the exact GFS (Grandfather-Father-Son) Trend Following Strategy
on US EQUITIES using `instocks.db` (1,506 US stocks) + S&P 500 (^GSPC) + GLD.

Compares:
1. GFS US Equities (0% Cash)
2. GFS US Equities + US Treasury / Liquid Yield (4.5% p.a.)
3. GFS US Equities + Gold Proxy (GLD)
4. S&P 500 (^GSPC) Benchmark Buy-and-Hold

Period: 2018-01-01 to 2026-08-25 (8.64 Years, identical to Indian Market backtest)
Capital: $1,000,000 ($1M) or $100,000
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
CAPACITY = 10

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

def load_us_data():
    t0 = time.time()
    print("Loading US Stock data from instocks.db...")
    conn = sqlite3.connect(DB_PATH)

    # 1. Load S&P 500 (^GSPC) for Market Regime
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

    # 2. Load Stock Prices (Exclude indices)
    raw_df = pd.read_sql("""
        SELECT Date, Ticker, Adj_Close, Volume 
        FROM daily_prices 
        WHERE Ticker != '^GSPC' AND Date >= '2015-01-01'
        ORDER BY Ticker, Date ASC;
    """, conn)
    conn.close()

    print(f"Loaded {len(raw_df):,} rows across {raw_df['Ticker'].nunique():,} tickers in {time.time()-t0:.2f}s.")

    # 3. Load GLD (Gold)
    print("Fetching GLD (Gold ETF) data...")
    gld_df = yf.download("GLD", start="2015-01-01", end="2026-08-26", progress=False)
    if isinstance(gld_df.columns, pd.MultiIndex):
        gld_close = gld_df["Close"]["GLD"]
    else:
        gld_close = gld_df["Close"]
    gld_map = {d.strftime("%Y-%m-%d"): float(p) for d, p in gld_close.items()}

    # 4. Process Multi-timeframe Indicators for each stock
    t1 = time.time()
    print("Computing Grandfather, Father, and Son multi-timeframe indicators...")

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
        m_df["m_ema9"] = compute_ema(m_df["m_close"], 9)
        m_map = dict(zip(m_df["year_month"], m_df["monthly_rsi"]))
        g["monthly_rsi"] = g["year_month"].map(m_map)

        m_end_dates = set(m_df["last_date"].values)
        m_info = m_df.set_index("last_date")
        g["is_month_end"] = g["Date"].isin(m_end_dates)
        g["m_close"] = g["Date"].map(m_info["m_close"]).fillna(np.nan)
        g["m_ema9"] = g["Date"].map(m_info["m_ema9"]).fillna(np.nan)

        g["dollar_vol_20d"] = (g["Adj_Close"] * g["Volume"]).rolling(20).mean()
        g["entry_date"] = g["Date"].shift(-1)
        g["entry_price"] = g["Adj_Close"].shift(-1)

        # Store lookup
        stock_dict = {}
        for row in g.to_dict(orient="records"):
            stock_dict[row["Date"]] = row
        stock_lookup[ticker] = stock_dict

        # Identify signals with Institutional Investability Filters:
        # 1. Entry price >= $5.00 (Excludes sub-dollar/penny stocks)
        # 2. 20-day Average Daily Dollar Volume >= $500,000 (Ensures liquidity for $100k slot execution)
        # 3. Excludes 5-letter OTC foreign pink sheets ending in F or Y
        son_cross = (g["prev_daily_rsi"] <= 40.0) & (g["daily_rsi"] > 40.0) & (g["entry_date"].notna())
        price_ok = (g["entry_price"] >= 5.0)
        vol_ok = (g["dollar_vol_20d"] >= 500_000.0)
        not_otc_shell = not (len(ticker) == 5 and ticker[-1] in ("F", "Y"))
        
        valid_sig = son_cross & (g["weekly_rsi"] > 60.0) & (g["monthly_rsi"] > 60.0) & price_ok & vol_ok & not_otc_shell

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
    print(f"Computed indicators in {time.time()-t1:.2f}s. Total Liquid GFS Signals in US Stocks: {len(signals_df):,}")

    return signals_df, stock_lookup, all_dates, regime_map, sp500_close_map, gld_map

def run_us_gfs_simulation(
    signals_df,
    stock_lookup,
    all_dates,
    regime_map,
    gld_map,
    cash_mode="zero", # 'zero', 'tbill' (4.5%), 'gold' (GLD)
    capacity=10,
    cost_bps=10.0
):
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)
    daily_tbill_yield = (4.5 / 100.0) / 252.0
    exp_sch = {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30}

    sig_by_date = {}
    for sig in signals_df.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in all_dates if START_DATE <= d <= END_DATE]
    
    cash = INITIAL_CAPITAL
    gold_units = 0.0
    open_positions = {}
    closed_trades = []
    daily_stats = []

    # If starting in gold, buy gold on first day
    if cash_mode == "gold":
        first_d = sim_dates[0]
        g_p = gld_map.get(first_d, 120.0) * cost_mult_entry
        gold_units = cash / g_p
        cash = 0.0

    for d_idx, d in enumerate(sim_dates):
        curr_gold_p = gld_map.get(d, 120.0)

        # 1. Earn T-Bill interest if applicable
        if cash_mode == "tbill":
            cash += cash * daily_tbill_yield

        # 2. Exits at Day Open
        to_close = []
        for ticker, pos in open_positions.items():
            r = stock_lookup.get(ticker, {}).get(d)
            if r is None:
                continue
            p = r["Adj_Close"]
            pos["last_price"] = p
            pos["holding_days"] += 1

            if pos.get("pending_exit"):
                exit_price = p * cost_mult_exit
                ret_pct = (exit_price - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
                trade_pnl = pos["shares"] * (exit_price - pos["sim_entry_price"])
                proceeds = pos["shares"] * exit_price

                if cash_mode == "gold":
                    buy_g_p = curr_gold_p * cost_mult_entry
                    gold_units += proceeds / buy_g_p
                else:
                    cash += proceeds

                closed_trades.append({
                    "ticker": ticker,
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "return_pct": ret_pct,
                    "pnl_usd": trade_pnl,
                    "holding_days": pos["holding_days"]
                })
                to_close.append(ticker)

        for ticker in to_close:
            del open_positions[ticker]

        # 3. Portfolio Valuation
        stock_equity = sum(p["shares"] * p["last_price"] for p in open_positions.values())
        gold_val = gold_units * curr_gold_p
        total_equity = cash + gold_val + stock_equity

        regime = regime_map.get(d, "NEUTRAL")
        regime_factor = exp_sch.get(regime, 1.0)
        max_allowed_stock_equity = total_equity * regime_factor
        max_allowed_positions = max(1, int(round(capacity * regime_factor)))

        # 4. New Entries
        prev_d = sim_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        avail_liquid = cash if cash_mode != "gold" else (gold_units * curr_gold_p * cost_mult_exit)

        if day_signals and len(open_positions) < max_allowed_positions and stock_equity < max_allowed_stock_equity and avail_liquid > 1000.0:
            cands = [s for s in day_signals if s["ticker"] not in open_positions]
            if cands:
                # Rank by Weekly RSI descending
                ranked = sorted(cands, key=lambda x: x.get("weekly_rsi", 0.0), reverse=True)
                avail_slots = max_allowed_positions - len(open_positions)
                alloc_per_slot = total_equity / capacity

                for cand in ranked[:avail_slots]:
                    s_sym = cand["ticker"]
                    raw_entry_p = cand["entry_price"]
                    sim_entry_p = raw_entry_p * cost_mult_entry

                    req_alloc = min(avail_liquid, alloc_per_slot)
                    if req_alloc > 1000.0 and (stock_equity + req_alloc) <= (max_allowed_stock_equity * 1.05):
                        if cash_mode == "gold":
                            sell_g_p = curr_gold_p * cost_mult_exit
                            units_to_sell = req_alloc / sell_g_p
                            if units_to_sell > gold_units:
                                units_to_sell = gold_units
                                req_alloc = units_to_sell * sell_g_p
                            gold_units -= units_to_sell
                            avail_liquid -= req_alloc
                        else:
                            cash -= req_alloc
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
                            "pending_exit": False
                        }

        # 5. Month-End Trailing Exit Review
        for ticker, pos in open_positions.items():
            r = stock_lookup.get(ticker, {}).get(d)
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
            "stock_equity": round(stock_equity, 2),
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
    
    wins = [t for t in closed_trades if t["pnl_usd"] > 0]
    losses = [t for t in closed_trades if t["pnl_usd"] <= 0]
    pf = (sum(t["pnl_usd"] for t in wins) / abs(sum(t["pnl_usd"] for t in losses))) if losses and sum(t["pnl_usd"] for t in losses) != 0 else np.nan

    return {
        "cash_mode": cash_mode,
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
    signals_df, stock_lookup, all_dates, regime_map, sp500_close_map, gld_map = load_us_data()

    print("\nRunning US GFS Simulations (2018 - 2026)...")
    res_zero = run_us_gfs_simulation(signals_df, stock_lookup, all_dates, regime_map, gld_map, cash_mode="zero")
    res_tbill = run_us_gfs_simulation(signals_df, stock_lookup, all_dates, regime_map, gld_map, cash_mode="tbill")
    res_gold = run_us_gfs_simulation(signals_df, stock_lookup, all_dates, regime_map, gld_map, cash_mode="gold")

    # S&P 500 Buy and hold
    sim_dates = [d for d in all_dates if START_DATE <= d <= END_DATE]
    sp_start = sp500_close_map[sim_dates[0]]
    sp_end = sp500_close_map[sim_dates[-1]]
    years = (pd.to_datetime(sim_dates[-1]) - pd.to_datetime(sim_dates[0])).days / 365.25
    sp_cagr = ((sp_end / sp_start) ** (1.0 / years) - 1.0) * 100.0
    sp_tot = ((sp_end - sp_start) / sp_start) * 100.0
    
    sp_series = pd.Series([sp500_close_map[d] for d in sim_dates])
    sp_mdd = ((sp_series - sp_series.cummax()) / sp_series.cummax() * 100.0).min()

    print("\n" + "="*105)
    print(f"{'US MARKET STRATEGY ($1,000,000 INITIAL CAPITAL)':<45} | {'END VALUE ($)':<14} | {'CAGR':<8} | {'MAX DD':<8} | {'PF':<5} | {'TRADES'}")
    print("="*105)
    print(f"{'1. GFS US Equities (0% Cash Baseline)':<45} | ${res_zero['end_equity']:>13,.0f} | {res_zero['cagr']:>6.2f}% | {res_zero['max_drawdown']:>6.2f}% | {res_zero['profit_factor']:>5.2f} | {res_zero['trades']}")
    print(f"{'2. GFS US Equities + US T-Bills (4.5% Yield)':<45} | ${res_tbill['end_equity']:>13,.0f} | {res_tbill['cagr']:>6.2f}% | {res_tbill['max_drawdown']:>6.2f}% | {res_tbill['profit_factor']:>5.2f} | {res_tbill['trades']}")
    print(f"{'3. GFS US Equities + Gold Proxy (GLD)':<45} | ${res_gold['end_equity']:>13,.0f} | {res_gold['cagr']:>6.2f}% | {res_gold['max_drawdown']:>6.2f}% | {res_gold['profit_factor']:>5.2f} | {res_gold['trades']}")
    print(f"{'4. S&P 500 Index (^GSPC) Buy & Hold':<45} | ${INITIAL_CAPITAL * (1.0 + sp_tot/100.0):>13,.0f} | {sp_cagr:>6.2f}% | {sp_mdd:>6.2f}% | {'N/A':>5} | 0")
    print("="*105)

    # Save daily equity curves
    comp_us_df = pd.DataFrame({
        "date": res_zero["daily_df"]["date"],
        "gfs_us_zero_cash": res_zero["daily_df"]["equity"],
        "gfs_us_tbills": res_tbill["daily_df"]["equity"],
        "gfs_us_gold": res_gold["daily_df"]["equity"],
        "sp500_index": [INITIAL_CAPITAL * (sp500_close_map[d] / sp_start) for d in sim_dates]
    })
    us_csv_path = REPORTS_DIR / "gfs_us_stocks_comparison.csv"
    comp_us_df.to_csv(us_csv_path, index=False)
    print(f"\nSaved US backtest daily curves to {us_csv_path}")

    # Top US Trades
    t_df = pd.DataFrame(res_gold["trades_list"]).sort_values("return_pct", ascending=False)
    trades_csv = REPORTS_DIR / "gfs_us_stocks_trades.csv"
    t_df.to_csv(trades_csv, index=False)
    print(f"Saved US trade log to {trades_csv}")
    print("\nTOP 10 WINNING US TRADES:")
    print(t_df[["ticker", "entry_date", "exit_date", "return_pct", "pnl_usd", "holding_days"]].head(10).to_string(index=False))
