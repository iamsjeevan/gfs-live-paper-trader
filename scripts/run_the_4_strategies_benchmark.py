#!/usr/bin/env python3
"""
run_the_4_strategies_benchmark.py
==================================
Runs the definitive backtest comparing the exact 4 GFS live forward-testing strategies:
1. INDIA BROAD: All corporate stocks > ₹100Cr MCap (GOLDBEES proxy, Month-end EMA9 exit)
2. INDIA LIQUID: Top 500 liquid stocks (GOLDBEES proxy, Month-end EMA9 exit)
3. USA BROAD: All INDmoney/Tickertape tradeable stocks (GLD proxy, 60D Eviction + EMA13 exit)
4. USA LIQUID: S&P 500 Liquid subset (GLD proxy, 60D Eviction + EMA13 exit)

Period: 2018-01-01 to 2026-08-25
Generates:
- Console performance table
- reports/gfs_4_portfolios_dashboard.html (Interactive HTML Dashboard with Trade Logs)
- reports/gfs_4_strategies_trades.csv
"""

import sys
import time
import json
import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
sys.path.insert(0, str(BASE_DIR))

from scripts.run_gfs_concentrated_regime_backtest import (
    load_data_and_regimes,
    rank_candidates
)

print("="*80)
print("🚀 STARTING THE DEFINITIVE 4-STRATEGY GFS BENCHMARK (2018-2026)")
print("="*80)

# ==============================================================================
# 1. RUN INDIAN MARKET BACKTESTS (BROAD vs LIQUID)
# ==============================================================================
print("\n[1/2] Loading Indian Market Data...")
signals_df, stock_date_lookup, all_trading_days, nifty_regime_map = load_data_and_regimes()

# Load GOLDBEES prices
conn_ind = sqlite3.connect(BASE_DIR / "data" / "indian_market.db")
gold_raw = pd.read_sql("SELECT date, open, close FROM daily_ohlcv WHERE security_id = 2628 ORDER BY date ASC;", conn_ind)
conn_ind.close()

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

# Load liquid universe
with open(BASE_DIR / "live_paper_trader" / "universe_india_liquid.json", "r") as f:
    ind_liquid_set = set(json.load(f))

def simulate_indian_strategy(allowed_symbols=None, name="INDIA"):
    initial_capital = 100_000.0 # ₹1 Lakh
    capacity = 10
    cost_stock_bps = 25.0
    cost_stock_entry = 1.0 + (cost_stock_bps / 10000.0)
    cost_stock_exit = 1.0 - (cost_stock_bps / 10000.0)
    cost_gold_bps = 10.0
    cost_gold_entry = 1.0 + (cost_gold_bps / 10000.0)
    cost_gold_exit = 1.0 - (cost_gold_bps / 10000.0)

    exp_sch = {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30}

    # Filter signals if allowed_symbols is specified
    if allowed_symbols is not None:
        filtered_signals = signals_df[signals_df["symbol"].isin(allowed_symbols)]
    else:
        filtered_signals = signals_df

    sig_by_date = {}
    for sig in filtered_signals.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in all_trading_days if "2018-01-01" <= d <= "2026-08-21"]
    first_date = sim_dates[0]
    g_p = gold_lookup.get(first_date, {}).get("open", 26.44) * cost_gold_entry
    gold_units = initial_capital / g_p
    cash = 0.0

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

            if pos.get("pending_exit"):
                exit_price = op * cost_stock_exit
                ret_pct = (exit_price - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
                trade_pnl = pos["shares"] * (exit_price - pos["sim_entry_price"])
                proceeds = pos["shares"] * exit_price

                buy_gold_p = g_op * cost_gold_entry
                gold_units += proceeds / buy_gold_p

                closed_trades.append({
                    "strategy": name,
                    "symbol": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "entry_price": round(pos["sim_entry_price"], 2),
                    "exit_price": round(exit_price, 2),
                    "return_pct": round(ret_pct, 2),
                    "pnl": round(trade_pnl, 2),
                    "holding_days": pos["holding_days"],
                    "exit_reason": "MONTHLY_EMA9_BREAK"
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
        max_allowed_positions = max(1, int(round(capacity * regime_factor)))

        # 3. Entries
        prev_d = sim_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []
        avail_liquid_funds = gold_units * g_op * cost_gold_exit

        if day_signals and len(open_positions) < max_allowed_positions and stock_invested < max_allowed_stock_equity and avail_liquid_funds > 100.0:
            cands = [s for s in day_signals if s["symbol"] not in open_positions]
            if cands:
                ranked = rank_candidates(cands, "weekly_rsi")
                avail_slots = max_allowed_positions - len(open_positions)
                alloc_per_slot = total_equity / capacity

                for cand in ranked[:avail_slots]:
                    s_sym = cand["symbol"]
                    raw_entry_p = cand["entry_price"]
                    sim_entry_p = raw_entry_p * cost_stock_entry
                    req_alloc = min(avail_liquid_funds, alloc_per_slot)
                    if req_alloc > 100.0 and (stock_invested + req_alloc) <= (max_allowed_stock_equity * 1.05):
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
    cagr = ((end_eq / initial_capital) ** (1.0 / years) - 1.0) * 100.0
    tot_ret = (end_eq - initial_capital) / initial_capital * 100.0
    mdd = d_df["drawdown"].min()
    wins = [t for t in closed_trades if t["pnl"] > 0]
    losses = [t for t in closed_trades if t["pnl"] <= 0]
    pf = (sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses))) if losses and sum(t["pnl"] for t in losses) != 0 else np.nan
    wr = len(wins) / len(closed_trades) * 100.0 if closed_trades else 0.0

    return {
        "name": name,
        "market": "INDIA",
        "currency": "₹",
        "initial_capital": initial_capital,
        "end_equity": end_eq,
        "tot_ret": tot_ret,
        "cagr": cagr,
        "max_drawdown": mdd,
        "profit_factor": pf,
        "win_rate": wr,
        "trades": len(closed_trades),
        "trades_list": closed_trades,
        "daily_df": d_df
    }

print("Running 1. INDIA BROAD...")
res_ind_broad = simulate_indian_strategy(allowed_symbols=None, name="INDIA_BROAD")
print("Running 2. INDIA LIQUID...")
res_ind_liquid = simulate_indian_strategy(allowed_symbols=ind_liquid_set, name="INDIA_LIQUID")

# ==============================================================================
# 2. RUN US MARKET BACKTESTS (BROAD vs LIQUID WITH GLD)
# ==============================================================================
print("\n[2/2] Loading US Stock Data from instocks.db...")

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

conn_us = sqlite3.connect(BASE_DIR / "instocks.db")
sp500_df = pd.read_sql("SELECT Date, Adj_Close FROM daily_prices WHERE Ticker = '^GSPC' ORDER BY Date ASC;", conn_us)
sp500_df["ema200"] = compute_ema(sp500_df["Adj_Close"], 200)
sp500_df["ema50"] = compute_ema(sp500_df["Adj_Close"], 50)
sp500_df["bull_flag"] = (sp500_df["Adj_Close"] > sp500_df["ema200"]) & (sp500_df["Adj_Close"] > sp500_df["ema50"])
sp500_df["bear_flag"] = sp500_df["Adj_Close"] <= sp500_df["ema200"]
sp500_df["regime"] = "NEUTRAL"
sp500_df.loc[sp500_df["bull_flag"], "regime"] = "BULL"
sp500_df.loc[sp500_df["bear_flag"], "regime"] = "BEAR"
sp500_regime_map = dict(zip(sp500_df["Date"], sp500_df["regime"]))

# Load GLD
gld_df = yf.download("GLD", start="2015-01-01", end="2026-08-26", progress=False)
if isinstance(gld_df.columns, pd.MultiIndex):
    gld_close = gld_df["Close"]["GLD"]
else:
    gld_close = gld_df["Close"]
gld_map = {d.strftime("%Y-%m-%d"): float(p) for d, p in gld_close.items()}

# Load US tickers
with open(BASE_DIR / "live_paper_trader" / "universe_usa_broad.json", "r") as f:
    us_broad_set = set(json.load(f))
with open(BASE_DIR / "live_paper_trader" / "universe_usa_liquid.json", "r") as f:
    us_liquid_set = set(json.load(f))

# Load all candidate price bars
all_needed_tickers = us_broad_set.union(us_liquid_set)
raw_us_df = pd.read_sql(f"""
    SELECT Date, Ticker, Adj_Close, Volume 
    FROM daily_prices 
    WHERE Date >= '2015-01-01' AND Ticker IN ({','.join(['?']*len(all_needed_tickers))})
    ORDER BY Ticker, Date ASC;
""", conn_us, params=list(all_needed_tickers))
conn_us.close()

# Process US multi-timeframe indicators
print("Computing US indicators (Monthly EMA 13)...")
stock_lookup_us = {}
all_signals_us = []
us_trading_dates = sorted(list(set(sp500_df["Date"])))

for ticker, g in raw_us_df.groupby("Ticker"):
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
    m_df["m_ema"] = compute_ema(m_df["m_close"], 13)
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

    # GFS Signal
    cond_gfs = (
        (g["monthly_rsi"] > 60.0) &
        (g["Adj_Close"] > g["m_ema"].ffill()) &
        (g["weekly_rsi"] > 60.0) &
        (g["prev_daily_rsi"] <= 40.0) &
        (g["daily_rsi"] > 40.0)
    )

    signals_subset = g[cond_gfs & g["entry_date"].notna()].copy()
    for _, row in signals_subset.iterrows():
        all_signals_us.append({
            "ticker": ticker,
            "signal_date": row["Date"],
            "entry_date": row["entry_date"],
            "entry_price": row["entry_price"],
            "weekly_rsi": row["weekly_rsi"],
            "monthly_rsi": row["monthly_rsi"]
        })

    ticker_map = {}
    for _, row in g.iterrows():
        ticker_map[row["Date"]] = {
            "price": row["Adj_Close"],
            "is_month_end": row["is_month_end"],
            "m_close": row["m_close"],
            "m_ema": row["m_ema"]
        }
    stock_lookup_us[ticker] = ticker_map

us_signals_df = pd.DataFrame(all_signals_us)
print(f"Total US GFS Signals generated: {len(us_signals_df):,}")

def simulate_us_strategy(allowed_tickers=None, name="USA"):
    initial_capital = 10_000.0 # $10k
    capacity = 10
    cost_stock_bps = 5.0
    cost_stock_entry = 1.0 + (cost_stock_bps / 10000.0)
    cost_stock_exit = 1.0 - (cost_stock_bps / 10000.0)
    cost_gld_bps = 2.0
    cost_gld_entry = 1.0 + (cost_gld_bps / 10000.0)
    cost_gld_exit = 1.0 - (cost_gld_bps / 10000.0)

    exp_sch = {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30}

    if allowed_tickers is not None:
        filtered_sig = us_signals_df[us_signals_df["ticker"].isin(allowed_tickers)]
    else:
        filtered_sig = us_signals_df

    sig_by_date = {}
    for sig in filtered_sig.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in us_trading_dates if "2018-01-01" <= d <= "2026-08-25"]
    first_date = sim_dates[0]
    g_p = gld_map.get(first_date, 120.0) * cost_gld_entry
    gold_units = initial_capital / g_p
    cash = 0.0

    open_positions = {}
    closed_trades = []
    daily_stats = []

    for d_idx, d in enumerate(sim_dates):
        g_p = gld_map.get(d)
        if g_p is None:
            g_p = daily_stats[-1]["gld_price"] if daily_stats else 120.0

        # 1. Check Exits at Open
        to_close = []
        for ticker, pos in open_positions.items():
            r = stock_lookup_us.get(ticker, {}).get(d)
            if r is None:
                continue
            curr_p = r["price"]
            pos["last_price"] = curr_p
            pos["holding_days"] += 1
            pos["unrealized_ret"] = (curr_p - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0

            should_exit = False
            exit_reason = ""

            if pos.get("pending_exit"):
                should_exit = True
                exit_reason = "MONTHLY_EMA13_BREAK"
            elif pos["holding_days"] >= 60 and pos["unrealized_ret"] < 3.0:
                should_exit = True
                exit_reason = "DEAD_MONEY_EVICTION_(60D_<_+3%)"

            if should_exit:
                exit_price = curr_p * cost_stock_exit
                ret_pct = (exit_price - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
                trade_pnl = pos["shares"] * (exit_price - pos["sim_entry_price"])
                proceeds = pos["shares"] * exit_price

                # Reinvest proceeds into GLD
                buy_gld_p = g_p * cost_gld_entry
                gold_units += proceeds / buy_gld_p

                closed_trades.append({
                    "strategy": name,
                    "symbol": ticker,
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "entry_price": round(pos["sim_entry_price"], 2),
                    "exit_price": round(exit_price, 2),
                    "return_pct": round(ret_pct, 2),
                    "pnl": round(trade_pnl, 2),
                    "holding_days": pos["holding_days"],
                    "exit_reason": exit_reason
                })
                to_close.append(ticker)

        for ticker in to_close:
            del open_positions[ticker]

        # 2. Portfolio Valuation
        stock_val = sum(p["shares"] * p["last_price"] for p in open_positions.values())
        gold_val = gold_units * g_p
        total_equity = cash + gold_val + stock_val

        regime = sp500_regime_map.get(d, "NEUTRAL")
        regime_factor = exp_sch.get(regime, 1.0)
        max_allowed_stock_equity = total_equity * regime_factor
        max_allowed_positions = max(1, int(round(capacity * regime_factor)))

        # 3. Entries
        day_signals = sig_by_date.get(d, [])
        avail_liquid_funds = gold_units * g_p * cost_gld_exit

        if day_signals and len(open_positions) < max_allowed_positions and stock_val < max_allowed_stock_equity and avail_liquid_funds > 10.0:
            cands = [s for s in day_signals if s["ticker"] not in open_positions]
            if cands:
                cands.sort(key=lambda x: x["weekly_rsi"], reverse=True)
                avail_slots = max_allowed_positions - len(open_positions)
                alloc_per_slot = total_equity / capacity

                for cand in cands[:avail_slots]:
                    s_sym = cand["ticker"]
                    raw_entry_p = cand["entry_price"]
                    sim_entry_p = raw_entry_p * cost_stock_entry

                    req_alloc = min(avail_liquid_funds, alloc_per_slot)
                    if req_alloc > 10.0 and (stock_val + req_alloc) <= (max_allowed_stock_equity * 1.05):
                        sell_gld_p = g_p * cost_gld_exit
                        units_to_sell = req_alloc / sell_gld_p
                        if units_to_sell > gold_units:
                            units_to_sell = gold_units
                            req_alloc = units_to_sell * sell_gld_p
                        gold_units -= units_to_sell
                        avail_liquid_funds -= req_alloc

                        shares = req_alloc / sim_entry_p
                        stock_val += req_alloc
                        open_positions[s_sym] = {
                            "symbol": s_sym,
                            "entry_date": cand["entry_date"],
                            "sim_entry_price": sim_entry_p,
                            "shares": shares,
                            "last_price": raw_entry_p,
                            "holding_days": 0,
                            "unrealized_ret": 0.0,
                            "pending_exit": False
                        }

        # 4. Month-End Check
        for ticker, pos in open_positions.items():
            r = stock_lookup_us.get(ticker, {}).get(d)
            if r is not None and r["is_month_end"]:
                m_close = r["m_close"]
                m_ema = r["m_ema"]
                if pd.notna(m_close) and pd.notna(m_ema) and m_close < m_ema:
                    pos["pending_exit"] = True

        daily_stats.append({
            "date": d,
            "equity": round(total_equity, 2),
            "positions": len(open_positions),
            "gld_price": g_p
        })

    d_df = pd.DataFrame(daily_stats)
    d_df["cummax"] = d_df["equity"].cummax()
    d_df["drawdown"] = (d_df["equity"] - d_df["cummax"]) / d_df["cummax"] * 100.0

    end_eq = d_df["equity"].iloc[-1]
    years = (pd.to_datetime(sim_dates[-1]) - pd.to_datetime(sim_dates[0])).days / 365.25
    cagr = ((end_eq / initial_capital) ** (1.0 / years) - 1.0) * 100.0
    tot_ret = (end_eq - initial_capital) / initial_capital * 100.0
    mdd = d_df["drawdown"].min()
    wins = [t for t in closed_trades if t["pnl"] > 0]
    losses = [t for t in closed_trades if t["pnl"] <= 0]
    pf = (sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses))) if losses and sum(t["pnl"] for t in losses) != 0 else np.nan
    wr = len(wins) / len(closed_trades) * 100.0 if closed_trades else 0.0

    return {
        "name": name,
        "market": "USA",
        "currency": "$",
        "initial_capital": initial_capital,
        "end_equity": end_eq,
        "tot_ret": tot_ret,
        "cagr": cagr,
        "max_drawdown": mdd,
        "profit_factor": pf,
        "win_rate": wr,
        "trades": len(closed_trades),
        "trades_list": closed_trades,
        "daily_df": d_df
    }

print("Running 3. USA BROAD (INDmoney / Tickertape tradeable)...")
res_usa_broad = simulate_us_strategy(allowed_tickers=us_broad_set, name="USA_BROAD")
print("Running 4. USA LIQUID (S&P 500 Liquid)...")
res_usa_liquid = simulate_us_strategy(allowed_tickers=us_liquid_set, name="USA_LIQUID")

all_results = [res_ind_broad, res_ind_liquid, res_usa_broad, res_usa_liquid]

# ==============================================================================
# 3. PRINT MASTER COMPARISON TABLE
# ==============================================================================
print("\n" + "="*115)
print(f"{'STRATEGY SETUP':<32} | {'INITIAL':<10} | {'END VALUE':<14} | {'RETURN %':<10} | {'CAGR':<8} | {'MAX DD':<8} | {'PF':<5} | {'WIN %':<6} | {'TRADES'}")
print("="*115)

for r in all_results:
    c = r["currency"]
    print(f"{r['name']:<32} | {c}{r['initial_capital']:>8,.0f} | {c}{r['end_equity']:>12,.2f} | {r['tot_ret']:>8.1f}% | {r['cagr']:>6.2f}% | {r['max_drawdown']:>6.2f}% | {r['profit_factor']:>5.2f} | {r['win_rate']:>5.1f}% | {r['trades']}")
print("="*115)

# Save combined trades CSV
all_trades = []
for r in all_results:
    for t in r["trades_list"]:
        all_trades.append(t)
trades_df = pd.DataFrame(all_trades)
trades_path = BASE_DIR / "reports" / "gfs_4_strategies_trades.csv"
trades_df.to_csv(trades_path, index=False)
print(f"\nSaved {len(trades_df):,} trades to {trades_path}")

# ==============================================================================
# 4. GENERATE INTERACTIVE HTML DASHBOARD
# ==============================================================================
print("Generating Interactive HTML Dashboard...")

# Prepare JSON data for embedded charts
chart_data = {}
for r in all_results:
    # Downsample daily curve to weekly points for smooth rendering
    d_df = r["daily_df"].iloc[::3].copy()
    chart_data[r["name"]] = {
        "dates": d_df["date"].tolist(),
        "equity": d_df["equity"].tolist(),
        "drawdown": d_df["drawdown"].tolist()
    }

html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GFS 4-Strategy Benchmark Dashboard (2018-2026)</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
            --accent-green: #10b981;
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --accent-gold: #f59e0b;
            --accent-red: #ef4444;
            --border: #334155;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            padding: 24px;
            line-height: 1.5;
        }}
        .header {{
            margin-bottom: 24px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
        }}
        .header h1 {{ font-size: 26px; font-weight: 700; color: #fff; }}
        .header p {{ color: var(--text-sub); font-size: 14px; margin-top: 4px; }}
        .grid-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
            position: relative;
            overflow: hidden;
        }}
        .card::before {{
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; height: 4px;
        }}
        .card.ind-broad::before {{ background: #f97316; }}
        .card.ind-liquid::before {{ background: #eab308; }}
        .card.usa-broad::before {{ background: #3b82f6; }}
        .card.usa-liquid::before {{ background: #06b6d4; }}
        .card-title {{ font-size: 13px; text-transform: uppercase; color: var(--text-sub); font-weight: 600; letter-spacing: 0.5px; }}
        .card-val {{ font-size: 28px; font-weight: 800; margin: 8px 0 4px 0; color: #fff; }}
        .card-badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600; }}
        .badge-green {{ background: rgba(16, 185, 129, 0.15); color: var(--accent-green); }}
        .badge-blue {{ background: rgba(59, 130, 246, 0.15); color: var(--accent-blue); }}
        .metric-row {{ display: flex; justify-content: space-between; margin-top: 12px; font-size: 13px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 8px; }}
        .metric-label {{ color: var(--text-sub); }}
        .metric-value {{ font-weight: 600; }}

        .chart-section {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        .chart-title {{ font-size: 18px; font-weight: 700; margin-bottom: 16px; display: flex; justify-content: space-between; }}

        .table-section {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
        }}
        .table-controls {{
            display: flex;
            gap: 12px;
            margin-bottom: 16px;
            flex-wrap: wrap;
        }}
        .btn {{
            background: #334155;
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .btn:hover {{ background: #475569; }}
        .btn.active {{ background: var(--accent-blue); }}
        input[type="text"] {{
            background: #0f172a;
            border: 1px solid var(--border);
            color: #fff;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
            flex-grow: 1;
            max-width: 300px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }}
        th {{
            background: #0f172a;
            padding: 10px 12px;
            color: var(--text-sub);
            font-weight: 600;
            border-bottom: 1px solid var(--border);
        }}
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        tr:hover {{ background: rgba(255,255,255,0.02); }}
        .gain {{ color: var(--accent-green); font-weight: 600; }}
        .loss {{ color: var(--accent-red); font-weight: 600; }}
    </style>
</head>
<body>

<div class="header">
    <div>
        <h1>🏆 GFS 4-Strategy Benchmark Dashboard</h1>
        <p>Verified Institutional Comparison (2018–2026) • 10 Slots • Schedule 1 Regime • 100% Gold Cash Parking</p>
    </div>
    <div style="font-size: 13px; color: var(--text-sub);">Period: 2018-01-01 to 2026-08-25 (~8.6 Years)</div>
</div>

<div class="grid-cards">
    <!-- Card 1: India Broad -->
    <div class="card ind-broad">
        <div class="card-title">🇮🇳 1. India Broad (> ₹100Cr)</div>
        <div class="card-val">₹{res_ind_broad['end_equity']:,.0f}</div>
        <span class="card-badge badge-green">+{res_ind_broad['tot_ret']:.1f}% (+{res_ind_broad['cagr']:.2f}% CAGR)</span>
        <div class="metric-row"><span class="metric-label">Initial Capital</span><span class="metric-value">₹1,00,000</span></div>
        <div class="metric-row"><span class="metric-label">Max Drawdown</span><span class="metric-value" style="color: var(--accent-red);">{res_ind_broad['max_drawdown']:.2f}%</span></div>
        <div class="metric-row"><span class="metric-label">Profit Factor</span><span class="metric-value">{res_ind_broad['profit_factor']:.2f}</span></div>
        <div class="metric-row"><span class="metric-label">Win Rate & Trades</span><span class="metric-value">{res_ind_broad['win_rate']:.1f}% ({res_ind_broad['trades']} trades)</span></div>
        <div class="metric-row"><span class="metric-label">Idle Cash Proxy</span><span class="metric-value" style="color: var(--accent-gold);">GOLDBEES (Gold)</span></div>
    </div>

    <!-- Card 2: India Liquid -->
    <div class="card ind-liquid">
        <div class="card-title">🇮🇳 2. India Liquid (Top 500)</div>
        <div class="card-val">₹{res_ind_liquid['end_equity']:,.0f}</div>
        <span class="card-badge badge-green">+{res_ind_liquid['tot_ret']:.1f}% (+{res_ind_liquid['cagr']:.2f}% CAGR)</span>
        <div class="metric-row"><span class="metric-label">Initial Capital</span><span class="metric-value">₹1,00,000</span></div>
        <div class="metric-row"><span class="metric-label">Max Drawdown</span><span class="metric-value" style="color: var(--accent-red);">{res_ind_liquid['max_drawdown']:.2f}%</span></div>
        <div class="metric-row"><span class="metric-label">Profit Factor</span><span class="metric-value">{res_ind_liquid['profit_factor']:.2f}</span></div>
        <div class="metric-row"><span class="metric-label">Win Rate & Trades</span><span class="metric-value">{res_ind_liquid['win_rate']:.1f}% ({res_ind_liquid['trades']} trades)</span></div>
        <div class="metric-row"><span class="metric-label">Idle Cash Proxy</span><span class="metric-value" style="color: var(--accent-gold);">GOLDBEES (Gold)</span></div>
    </div>

    <!-- Card 3: USA Broad -->
    <div class="card usa-broad">
        <div class="card-title">🇺🇸 3. USA Broad (INDmoney Tradeable)</div>
        <div class="card-val">${res_usa_broad['end_equity']:,.0f}</div>
        <span class="card-badge badge-blue">+{res_usa_broad['tot_ret']:.1f}% (+{res_usa_broad['cagr']:.2f}% CAGR)</span>
        <div class="metric-row"><span class="metric-label">Initial Capital</span><span class="metric-value">$10,000</span></div>
        <div class="metric-row"><span class="metric-label">Max Drawdown</span><span class="metric-value" style="color: var(--accent-red);">{res_usa_broad['max_drawdown']:.2f}%</span></div>
        <div class="metric-row"><span class="metric-label">Profit Factor</span><span class="metric-value">{res_usa_broad['profit_factor']:.2f}</span></div>
        <div class="metric-row"><span class="metric-label">Win Rate & Trades</span><span class="metric-value">{res_usa_broad['win_rate']:.1f}% ({res_usa_broad['trades']} trades)</span></div>
        <div class="metric-row"><span class="metric-label">Idle Cash Proxy</span><span class="metric-value" style="color: var(--accent-gold);">GLD (Gold)</span></div>
    </div>

    <!-- Card 4: USA Liquid -->
    <div class="card usa-liquid">
        <div class="card-title">🇺🇸 4. USA Liquid (S&P 500)</div>
        <div class="card-val">${res_usa_liquid['end_equity']:,.0f}</div>
        <span class="card-badge badge-blue">+{res_usa_liquid['tot_ret']:.1f}% (+{res_usa_liquid['cagr']:.2f}% CAGR)</span>
        <div class="metric-row"><span class="metric-label">Initial Capital</span><span class="metric-value">$10,000</span></div>
        <div class="metric-row"><span class="metric-label">Max Drawdown</span><span class="metric-value" style="color: var(--accent-red);">{res_usa_liquid['max_drawdown']:.2f}%</span></div>
        <div class="metric-row"><span class="metric-label">Profit Factor</span><span class="metric-value">{res_usa_liquid['profit_factor']:.2f}</span></div>
        <div class="metric-row"><span class="metric-label">Win Rate & Trades</span><span class="metric-value">{res_usa_liquid['win_rate']:.1f}% ({res_usa_liquid['trades']} trades)</span></div>
        <div class="metric-row"><span class="metric-label">Idle Cash Proxy</span><span class="metric-value" style="color: var(--accent-gold);">GLD (Gold)</span></div>
    </div>
</div>

<div class="chart-section">
    <div class="chart-title">
        <span>📈 Equity Curves Normalized (Rebased to 100)</span>
    </div>
    <div style="height: 380px;">
        <canvas id="equityChart"></canvas>
    </div>
</div>

<div class="table-section">
    <div class="chart-title">
        <span>📋 Verified Trade Logs</span>
    </div>
    <div class="table-controls">
        <button class="btn active" onclick="filterStrategy('ALL')">All Strategies</button>
        <button class="btn" onclick="filterStrategy('INDIA_BROAD')">India Broad</button>
        <button class="btn" onclick="filterStrategy('INDIA_LIQUID')">India Liquid</button>
        <button class="btn" onclick="filterStrategy('USA_BROAD')">USA Broad</button>
        <button class="btn" onclick="filterStrategy('USA_LIQUID')">USA Liquid</button>
        <input type="text" id="searchInput" placeholder="Search by ticker (e.g. ELECON, NVDA, GRAVITA)..." onkeyup="searchTable()">
    </div>
    <div style="overflow-x: auto; max-height: 550px;">
        <table id="tradesTable">
            <thead>
                <tr>
                    <th>Strategy</th>
                    <th>Symbol</th>
                    <th>Entry Date</th>
                    <th>Exit Date</th>
                    <th>Hold Days</th>
                    <th>Entry</th>
                    <th>Exit</th>
                    <th>Return %</th>
                    <th>PnL</th>
                    <th>Exit Reason</th>
                </tr>
            </thead>
            <tbody>
"""

for t in all_trades:
    ret = t["return_pct"]
    pnl = t["pnl"]
    ret_class = "gain" if ret >= 0 else "loss"
    curr_s = "₹" if "INDIA" in t["strategy"] else "$"
    html_content += f"""
                <tr data-strategy="{t['strategy']}">
                    <td><strong>{t['strategy']}</strong></td>
                    <td><strong>{t['symbol']}</strong></td>
                    <td>{t['entry_date']}</td>
                    <td>{t['exit_date']}</td>
                    <td>{t['holding_days']}d</td>
                    <td>{curr_s}{t['entry_price']:,.2f}</td>
                    <td>{curr_s}{t['exit_price']:,.2f}</td>
                    <td class="{ret_class}">{ret:+.2f}%</td>
                    <td class="{ret_class}">{curr_s}{pnl:+,.2f}</td>
                    <td><small>{t['exit_reason']}</small></td>
                </tr>
    """

html_content += f"""
            </tbody>
        </table>
    </div>
</div>

<script>
const rawData = {json.dumps(chart_data)};

// Rebase all to 100 for visual comparison
const datasets = [
    {{
        label: "🇮🇳 India Broad (> ₹100Cr)",
        borderColor: "#f97316",
        backgroundColor: "rgba(249, 115, 22, 0.05)",
        data: rawData.INDIA_BROAD.equity.map(v => (v / rawData.INDIA_BROAD.equity[0]) * 100),
        borderWidth: 2,
        tension: 0.1,
        pointRadius: 0
    }},
    {{
        label: "🇮🇳 India Liquid (Top 500)",
        borderColor: "#eab308",
        backgroundColor: "transparent",
        data: rawData.INDIA_LIQUID.equity.map(v => (v / rawData.INDIA_LIQUID.equity[0]) * 100),
        borderWidth: 2,
        tension: 0.1,
        pointRadius: 0
    }},
    {{
        label: "🇺🇸 USA Broad (INDmoney)",
        borderColor: "#3b82f6",
        backgroundColor: "transparent",
        data: rawData.USA_BROAD.equity.map(v => (v / rawData.USA_BROAD.equity[0]) * 100),
        borderWidth: 2,
        tension: 0.1,
        pointRadius: 0
    }},
    {{
        label: "🇺🇸 USA Liquid (S&P 500)",
        borderColor: "#06b6d4",
        backgroundColor: "transparent",
        data: rawData.USA_LIQUID.equity.map(v => (v / rawData.USA_LIQUID.equity[0]) * 100),
        borderWidth: 2,
        tension: 0.1,
        pointRadius: 0
    }}
];

const ctx = document.getElementById("equityChart").getContext("2d");
new Chart(ctx, {{
    type: "line",
    data: {{
        labels: rawData.INDIA_BROAD.dates,
        datasets: datasets
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ mode: "index", intersect: false }},
        plugins: {{
            legend: {{ labels: {{ color: "#cbd5e1" }} }},
            tooltip: {{
                callbacks: {{
                    label: function(context) {{
                        return context.dataset.label + ": " + context.parsed.y.toFixed(1) + " (Rebased)";
                    }}
                }}
            }}
        }},
        scales: {{
            x: {{ grid: {{ color: "rgba(255,255,255,0.05)" }}, ticks: {{ color: "#64748b", maxTicksLimit: 12 }} }},
            y: {{ grid: {{ color: "rgba(255,255,255,0.05)" }}, ticks: {{ color: "#64748b" }} }}
        }}
    }}
}});

let currentFilter = "ALL";
function filterStrategy(strat) {{
    currentFilter = strat;
    document.querySelectorAll(".table-controls .btn").forEach(b => b.classList.remove("active"));
    event.target.classList.add("active");
    applyFilters();
}}

function searchTable() {{
    applyFilters();
}}

function applyFilters() {{
    const query = document.getElementById("searchInput").value.toUpperCase();
    const rows = document.querySelectorAll("#tradesTable tbody tr");
    rows.forEach(r => {{
        const strat = r.getAttribute("data-strategy");
        const text = r.innerText.toUpperCase();
        const matchesStrat = (currentFilter === "ALL" || strat === currentFilter);
        const matchesQuery = (!query || text.includes(query));
        r.style.display = (matchesStrat && matchesQuery) ? "" : "none";
    }});
}}
</script>

</body>
</html>
"""

dashboard_path = BASE_DIR / "reports" / "gfs_4_portfolios_dashboard.html"
with open(dashboard_path, "w") as f:
    f.write(html_content)
print(f"Generated Interactive HTML Dashboard at {dashboard_path}")
print("="*80)
