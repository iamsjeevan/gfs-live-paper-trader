#!/usr/bin/env python3
"""
run_gfs_concentrated_regime_backtest.py
======================================
Backtest evaluating MARKET REGIME MODULATION (NIFTY 50 200 EMA Schedule 1: 100% Bull / 70% Neutral / 30% Bear)
combined with HIGH CONCENTRATION CAPACITIES (2, 3, 5, 7, 10, 15 positions)
under the FROZEN GFS strategy (Monthly Close < Monthly EMA9 exit).

Tests:
1. Fixed 100% Exposure vs Regime Schedule 1 across all capacities (2, 3, 5, 7, 10, 15)
2. Ranking Methods: 3M Return, Composite Momentum, Weekly RSI, Monthly RSI, Relative Volume, Random Baseline
3. Sector Rules: Unrestricted vs Max 2 / Sector vs 25% Sector Cap
4. Slippage: 25, 50, 100 bps
5. Multibagger capture and tail risk
6. Chronological Walk-Forward validation (6 annual folds: 2021 to 2026)
"""

import os
import sys
import time
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

# Paths
BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
DB_PATH = BASE_DIR / "data" / "indian_market.db"
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

EXCLUDED_SYMBOLS = {"NIFTY 50", "NIFTY50", "NIFTY BANK", "BANKNIFTY", "NIFTY MIDCAP 50", "NIFTY AUTO"}

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

def load_data_and_regimes():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)

    sec_df = pd.read_sql("SELECT security_id, symbol, company_name, industry FROM securities;", conn)
    etf_mask = sec_df["symbol"].isin(EXCLUDED_SYMBOLS) | sec_df["symbol"].str.contains("BEES|ETF|NIFTY", case=False, na=False)
    corp_sec = sec_df[~etf_mask].copy()
    sec_info = corp_sec.set_index("security_id").to_dict(orient="index")
    corp_ids = set(corp_sec["security_id"])

    # Sector mapping
    try:
        tfa = pd.read_sql("SELECT DISTINCT Ticker as symbol, sector, mcap_cr FROM trades_fundamental_analysis WHERE sector IS NOT NULL AND sector != '';", conn)
        sector_map = dict(zip(tfa["symbol"], tfa["sector"]))
    except Exception:
        sector_map = {}

    for sid, row in corp_sec.iterrows():
        s_sym = row["symbol"]
        if s_sym not in sector_map or not sector_map[s_sym]:
            ind = row["industry"]
            sector_map[s_sym] = ind.title() if (pd.notna(ind) and ind.strip()) else "Diversified / Other"

    # NIFTY 50 Benchmark & Regimes
    nifty_df = pd.read_sql("SELECT date, open, high, low, close, volume FROM daily_ohlcv WHERE security_id = 2835 ORDER BY date ASC;", conn)
    nifty_df["ema200"] = compute_ema(nifty_df["close"], 200)
    nifty_df["ema50"] = compute_ema(nifty_df["close"], 50)
    nifty_df["bull_flag"] = (nifty_df["close"] > nifty_df["ema200"]) & (nifty_df["close"] > nifty_df["ema50"])
    nifty_df["bear_flag"] = nifty_df["close"] <= nifty_df["ema200"]
    nifty_df["regime"] = "NEUTRAL"
    nifty_df.loc[nifty_df["bull_flag"], "regime"] = "BULL"
    nifty_df.loc[nifty_df["bear_flag"], "regime"] = "BEAR"
    nifty_regime_map = dict(zip(nifty_df["date"], nifty_df["regime"]))

    daily_raw = pd.read_sql("""
        SELECT security_id, date, open, high, low, close, volume 
        FROM daily_ohlcv 
        ORDER BY security_id, date ASC;
    """, conn)
    conn.close()

    daily_df = daily_raw[daily_raw["security_id"].isin(corp_ids)].copy()
    daily_df["date"] = daily_df["date"].astype(str)

    processed_stocks = {}
    all_signals = []

    for sec_id, g in daily_df.groupby("security_id"):
        sym = sec_info[sec_id]["symbol"]
        comp = sec_info[sec_id]["company_name"]
        sector = sector_map.get(sym, "Diversified / Other")

        g = g.sort_values("date").copy()
        if len(g) < 60:
            continue

        g["daily_rsi"] = compute_rsi(g["close"], 14)
        g["prev_daily_rsi"] = g["daily_rsi"].shift(1)
        g["vol_sma20"] = g["volume"].rolling(20).mean()
        g["rel_vol"] = (g["volume"] / g["vol_sma20"].replace(0, np.nan)).fillna(1.0)
        g["ret_3m"] = (g["close"] / g["close"].shift(63) - 1.0) * 100.0
        g["ret_6m"] = (g["close"] / g["close"].shift(126) - 1.0) * 100.0
        g["ret_12m"] = (g["close"] / g["close"].shift(252) - 1.0) * 100.0

        g_dt = pd.to_datetime(g["date"])
        g["year_week"] = g_dt.dt.strftime("%Y-W%U")
        w_df = g.groupby("year_week").agg(w_close=("close", "last")).reset_index()
        w_df["weekly_rsi_raw"] = compute_rsi(w_df["w_close"], 14)
        w_df["weekly_rsi_entry"] = w_df["weekly_rsi_raw"].shift(1)
        w_entry_map = dict(zip(w_df["year_week"], w_df["weekly_rsi_entry"]))
        g["weekly_rsi_completed"] = g["year_week"].map(w_entry_map)

        g["year_month"] = g_dt.dt.strftime("%Y-%m")
        m_df = g.groupby("year_month").agg(
            m_close=("close", "last"),
            last_date=("date", "last")
        ).reset_index()
        m_df["monthly_rsi_raw"] = compute_rsi(m_df["m_close"], 14)
        m_df["monthly_rsi_entry"] = m_df["monthly_rsi_raw"].shift(1)
        m_df["m_ema9"] = compute_ema(m_df["m_close"], 9)
        m_entry_map = dict(zip(m_df["year_month"], m_df["monthly_rsi_entry"]))
        g["monthly_rsi_completed"] = g["year_month"].map(m_entry_map)

        m_end_dates = set(m_df["last_date"].values)
        m_info = m_df.set_index("last_date")
        g["is_month_end"] = g["date"].isin(m_end_dates)
        g["m_close"] = g["date"].map(m_info["m_close"]).fillna(np.nan)
        g["m_ema9"] = g["date"].map(m_info["m_ema9"]).fillna(np.nan)

        g["entry_date"] = g["date"].shift(-1)
        g["entry_open"] = g["open"].shift(-1)

        processed_stocks[sym] = g

        son_cross = (g["prev_daily_rsi"] <= 40.0) & (g["daily_rsi"] > 40.0) & (g["entry_date"].notna())
        base_valid = son_cross & (g["weekly_rsi_completed"] > 60.0) & (g["monthly_rsi_completed"] > 60.0)

        sig_rows = g[base_valid]
        for _, row in sig_rows.iterrows():
            all_signals.append({
                "security_id": sec_id,
                "symbol": sym,
                "company_name": comp,
                "sector": sector,
                "signal_date": row["date"],
                "entry_date": row["entry_date"],
                "signal_close": row["close"],
                "entry_price": row["entry_open"],
                "daily_rsi": row["daily_rsi"],
                "weekly_rsi": row["weekly_rsi_completed"],
                "monthly_rsi": row["monthly_rsi_completed"],
                "ret_3m": row["ret_3m"],
                "ret_6m": row["ret_6m"],
                "ret_12m": row["ret_12m"],
                "rel_vol": row["rel_vol"]
            })

    signals_df = pd.DataFrame(all_signals).sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    stock_date_lookup = {sym: {r["date"]: r for r in df.to_dict(orient="records")} for sym, df in processed_stocks.items()}
    all_trading_days = sorted(list(set(d for sym_dict in stock_date_lookup.values() for d in sym_dict)))
    print(f"Data & regime mapping loaded in {time.time()-t0:.2f}s. Signals: {len(signals_df):,}.")
    return signals_df, stock_date_lookup, all_trading_days, nifty_regime_map

def rank_candidates(candidate_list: list, ranking_method: str, rng=None) -> list:
    if len(candidate_list) <= 1 or ranking_method == "none":
        return candidate_list
    if ranking_method == "random":
        shuffled = candidate_list.copy()
        if rng is not None: rng.shuffle(shuffled)
        else: np.random.shuffle(shuffled)
        return shuffled
    if ranking_method == "ret_3m":
        return sorted(candidate_list, key=lambda x: (x.get("ret_3m") if pd.notna(x.get("ret_3m")) else -999.0), reverse=True)
    if ranking_method == "ret_6m":
        return sorted(candidate_list, key=lambda x: (x.get("ret_6m") if pd.notna(x.get("ret_6m")) else -999.0), reverse=True)
    if ranking_method == "weekly_rsi":
        return sorted(candidate_list, key=lambda x: (x.get("weekly_rsi") if pd.notna(x.get("weekly_rsi")) else -999.0), reverse=True)
    if ranking_method == "monthly_rsi":
        return sorted(candidate_list, key=lambda x: (x.get("monthly_rsi") if pd.notna(x.get("monthly_rsi")) else -999.0), reverse=True)
    if ranking_method == "composite":
        keys = ["monthly_rsi", "weekly_rsi", "ret_3m", "ret_6m", "ret_12m", "rel_vol"]
        weights = [0.30, 0.25, 0.10, 0.20, 0.10, 0.05]
        n = len(candidate_list)
        pct_ranks = {i: 0.0 for i in range(n)}
        for k, w in zip(keys, weights):
            vals = [c.get(k) if pd.notna(c.get(k)) else -9999.0 for c in candidate_list]
            ranks = pd.Series(vals).rank(pct=True, method="average").values
            for i in range(n):
                pct_ranks[i] += w * ranks[i]
        sorted_indices = sorted(range(n), key=lambda i: pct_ranks[i], reverse=True)
        return [candidate_list[i] for i in sorted_indices]
    return candidate_list

def simulate_regime_concentrated_portfolio(
    signals_subset: pd.DataFrame,
    stock_date_lookup: dict,
    all_trading_days: list,
    nifty_regime_map: dict,
    capacity: int = 5,
    ranking_method: str = "ret_3m",
    regime_schedule: str = "sch1", # 'fixed' or 'sch1' (100/70/30)
    sector_restriction: str = "none", # 'none', 'max2', 'cap25'
    cost_bps: float = 25.0,
    start_date: str = "2018-01-01",
    end_date: str = "2026-12-31",
    random_seed: int = None
):
    STARTING_CAPITAL = 1_000_000.0
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)

    schedules = {
        "fixed": {"BULL": 1.0, "NEUTRAL": 1.0, "BEAR": 1.0},
        "sch1": {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30},
    }
    exp_sch = schedules.get(regime_schedule, schedules["fixed"])
    rng = np.random.default_rng(random_seed) if random_seed is not None else None

    sig_sub = signals_subset[(signals_subset["signal_date"] >= start_date) & (signals_subset["signal_date"] <= end_date)]
    sig_by_date = {}
    for sig in sig_sub.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    sim_dates = [d for d in all_trading_days if start_date <= d <= end_date]
    if not sim_dates:
        return {}, pd.DataFrame(), pd.DataFrame()

    cash = STARTING_CAPITAL
    open_positions = {}
    closed_trades = []
    daily_stats = []
    max_sector_exp_recorded = 0.0

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
                cash += pos["shares"] * exit_price
                closed_trades.append({
                    "symbol": sym,
                    "sector": pos["sector"],
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "sim_entry_price": pos["sim_entry_price"],
                    "raw_entry_price": pos["raw_entry_price"],
                    "sim_exit_price": exit_price,
                    "raw_exit_price": op,
                    "return_pct": ret_pct,
                    "holding_days": pos["holding_days"],
                    "exit_reason": "MONTHLY_CLOSE_LT_M_EMA9"
                })
                to_close.append(sym)

        for sym in to_close:
            del open_positions[sym]

        # 2. Portfolio Valuation & Regime Limits
        invested_equity = sum(pos["shares"] * pos["last_close"] for pos in open_positions.values())
        total_equity = cash + invested_equity

        if total_equity > 0 and open_positions:
            sec_sums = {}
            for pos in open_positions.values():
                sec_sums[pos["sector"]] = sec_sums.get(pos["sector"], 0.0) + (pos["shares"] * pos["last_close"])
            for sec_val in sec_sums.values():
                s_exp = sec_val / total_equity * 100.0
                if s_exp > max_sector_exp_recorded:
                    max_sector_exp_recorded = s_exp

        # Regime target exposure
        regime = nifty_regime_map.get(d, "NEUTRAL")
        target_exp = exp_sch.get(regime, 1.0)
        max_allowed_equity = total_equity * target_exp
        max_allowed_positions = max(1, int(round(capacity * target_exp)))

        # 3. New Entries
        prev_d = sim_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        if day_signals and len(open_positions) < max_allowed_positions and invested_equity < max_allowed_equity and cash > 1000.0:
            cands = [s for s in day_signals if s["symbol"] not in open_positions]

            if sector_restriction != "none" and cands:
                valid_cands = []
                for c in cands:
                    sec = c["sector"]
                    sec_count = sum(1 for p in open_positions.values() if p["sector"] == sec)
                    if sector_restriction == "max2" and sec_count >= 2:
                        continue
                    elif sector_restriction == "cap25" and sec_count >= max(1, int(round(capacity * 0.25))):
                        continue
                    valid_cands.append(c)
                cands = valid_cands

            if cands:
                ranked_cands = rank_candidates(cands, ranking_method, rng=rng)
                available_slots = max_allowed_positions - len(open_positions)
                alloc_per_slot = total_equity / capacity

                for cand in ranked_cands[:available_slots]:
                    s_sym = cand["symbol"]
                    raw_entry_p = cand["entry_price"]
                    sim_entry_p = raw_entry_p * cost_mult_entry
                    sec = cand["sector"]

                    if sector_restriction != "none":
                        sec_count = sum(1 for p in open_positions.values() if p["sector"] == sec)
                        if sector_restriction == "max2" and sec_count >= 2:
                            continue
                        elif sector_restriction == "cap25" and sec_count >= max(1, int(round(capacity * 0.25))):
                            continue

                    avail_alloc = min(cash, alloc_per_slot)
                    if avail_alloc > 1000.0 and (invested_equity + avail_alloc) <= (max_allowed_equity * 1.05):
                        shares = avail_alloc / sim_entry_p
                        cash -= avail_alloc
                        invested_equity += avail_alloc
                        open_positions[s_sym] = {
                            "symbol": s_sym,
                            "sector": sec,
                            "entry_date": d,
                            "sim_entry_price": sim_entry_p,
                            "raw_entry_price": raw_entry_p,
                            "shares": shares,
                            "last_close": raw_entry_p,
                            "holding_days": 0,
                            "pending_exit": False
                        }

        # 4. Check Month-End Exit Condition
        for sym, pos in open_positions.items():
            r = stock_date_lookup.get(sym, {}).get(d)
            if r is None:
                continue
            pos["last_close"] = r["close"]
            if r["is_month_end"]:
                m_close = r["m_close"]
                m_ema9 = r["m_ema9"]
                if pd.notna(m_close) and pd.notna(m_ema9) and m_close < m_ema9:
                    pos["pending_exit"] = True

        # 5. Record Daily Valuation
        eod_invested = sum(pos["shares"] * pos["last_close"] for pos in open_positions.values())
        eod_equity = cash + eod_invested
        daily_stats.append({
            "date": d,
            "equity": eod_equity,
            "cash": cash,
            "invested": eod_invested,
            "positions": len(open_positions),
            "exposure_pct": (eod_invested / eod_equity * 100.0) if eod_equity > 0 else 0.0
        })

    last_d = sim_dates[-1]
    for sym, pos in open_positions.items():
        r = stock_date_lookup.get(sym, {}).get(last_d)
        cp = r["close"] if r is not None else pos["last_close"]
        exit_p = cp * cost_mult_exit
        ret_pct = (exit_p - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
        closed_trades.append({
            "symbol": sym,
            "sector": pos["sector"],
            "entry_date": pos["entry_date"],
            "exit_date": last_d,
            "sim_entry_price": pos["sim_entry_price"],
            "raw_entry_price": pos["raw_entry_price"],
            "sim_exit_price": exit_p,
            "raw_exit_price": cp,
            "return_pct": ret_pct,
            "holding_days": pos["holding_days"],
            "exit_reason": "END_OF_BACKTEST"
        })

    daily_df = pd.DataFrame(daily_stats)
    trades_df = pd.DataFrame(closed_trades)

    if daily_df.empty:
        return {}, daily_df, trades_df

    daily_df["ret_1d"] = daily_df["equity"].pct_change().fillna(0.0)
    daily_df["cummax"] = daily_df["equity"].cummax()
    daily_df["drawdown"] = (daily_df["equity"] - daily_df["cummax"]) / daily_df["cummax"] * 100.0

    ending_val = daily_df["equity"].iloc[-1]
    total_ret_pct = (ending_val - STARTING_CAPITAL) / STARTING_CAPITAL * 100.0
    n_days = len(daily_df)
    n_years = n_days / 252.0 if n_days > 0 else 1.0
    cagr = ((ending_val / STARTING_CAPITAL) ** (1.0 / n_years) - 1.0) * 100.0 if (ending_val > 0 and n_years > 0) else -100.0
    max_dd = daily_df["drawdown"].min()
    vol_ann = daily_df["ret_1d"].std() * np.sqrt(252) * 100.0
    sharpe = (cagr / vol_ann) if vol_ann > 1e-4 else 0.0
    calmar = (cagr / abs(max_dd)) if abs(max_dd) > 1e-4 else 0.0

    n_trades = len(trades_df)
    if n_trades > 0:
        wins = trades_df[trades_df["return_pct"] > 0]
        losses = trades_df[trades_df["return_pct"] <= 0]
        win_rate = len(wins) / n_trades * 100.0
        avg_ret = trades_df["return_pct"].mean()
        med_ret = trades_df["return_pct"].median()
        tot_gains = wins["return_pct"].sum()
        tot_losses = abs(losses["return_pct"].sum())
        profit_factor = (tot_gains / tot_losses) if tot_losses > 1e-4 else 99.0
        turnover = (n_trades / n_years) * (100.0 / capacity)
        w50 = len(trades_df[trades_df["return_pct"] >= 50.0])
        w100 = len(trades_df[trades_df["return_pct"] >= 100.0])
        w200 = len(trades_df[trades_df["return_pct"] >= 200.0])
        w300 = len(trades_df[trades_df["return_pct"] >= 300.0])
        w500 = len(trades_df[trades_df["return_pct"] >= 500.0])
        max_winner = trades_df["return_pct"].max()
    else:
        win_rate = avg_ret = med_ret = profit_factor = turnover = 0.0
        w50 = w100 = w200 = w300 = w500 = max_winner = 0.0

    summary = {
        "starting_capital": STARTING_CAPITAL,
        "ending_capital": ending_val,
        "total_return_pct": total_ret_pct,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "volatility_ann": vol_ann,
        "sharpe": sharpe,
        "calmar": calmar,
        "profit_factor": profit_factor,
        "num_trades": n_trades,
        "win_rate": win_rate,
        "avg_trade_ret": avg_ret,
        "median_trade_ret": med_ret,
        "annual_turnover": turnover,
        "w50": w50,
        "w100": w100,
        "w200": w200,
        "w300": w300,
        "w500": w500,
        "max_winner": max_winner,
        "max_sector_exp": max_sector_exp_recorded,
        "avg_exposure_pct": daily_df["exposure_pct"].mean()
    }
    return summary, daily_df, trades_df

def run_concentrated_regime_study():
    signals_df, stock_date_lookup, all_trading_days, nifty_regime_map = load_data_and_regimes()

    capacities = [3, 5, 7, 10, 15]
    ranking_methods = [
        ("3M Return", "ret_3m"),
        ("Composite Momentum", "composite"),
        ("Weekly RSI", "weekly_rsi"),
        ("Monthly RSI", "monthly_rsi"),
        ("6M Return", "ret_6m")
    ]
    regime_options = [
        ("Fixed 100% Exposure", "fixed"),
        ("Regime Schedule 1 (100/70/30)", "sch1")
    ]
    sector_rules = [
        ("Unrestricted", "none"),
        ("Max 2 / Sector", "max2")
    ]

    results = []

    print("\n" + "=" * 80)
    print("RUNNING CONCENTRATED REGIME EXPERIMENTS")
    print("=" * 80)

    for r_label, r_code in ranking_methods:
        for cap in capacities:
            for s_label, s_code in sector_rules:
                for reg_label, reg_code in regime_options:
                    s, _, tr = simulate_regime_concentrated_portfolio(
                        signals_df, stock_date_lookup, all_trading_days, nifty_regime_map,
                        capacity=cap, ranking_method=r_code, regime_schedule=reg_code,
                        sector_restriction=s_code, cost_bps=25.0
                    )
                    results.append({
                        "Ranking Method": r_label,
                        "Positions": cap,
                        "Sector Rule": s_label,
                        "Regime Schedule": reg_label,
                        "CAGR": s["cagr"],
                        "Max DD": s["max_drawdown"],
                        "Profit Factor": s["profit_factor"],
                        "Calmar": s["calmar"],
                        "Win Rate": s["win_rate"],
                        "Trades": s["num_trades"],
                        "Avg Trade %": s["avg_trade_ret"],
                        "Avg Exposure %": s["avg_exposure_pct"],
                        ">100% Wins": s["w100"],
                        "Max Winner %": s["max_winner"]
                    })
                    print(f"[{cap:2d} pos | {r_label:18s} | {s_label:14s} | {reg_label[:14]:14s}] -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Calmar: {s['calmar']:5.3f} | >100%: {s['w100']:2d}")

    reg_df = pd.DataFrame(results)
    reg_df.to_csv(REPORTS_DIR / "gfs_concentrated_regime_comparison.csv", index=False)
    print("\nSaved regime comparison to: reports/gfs_concentrated_regime_comparison.csv")

if __name__ == "__main__":
    run_concentrated_regime_study()
