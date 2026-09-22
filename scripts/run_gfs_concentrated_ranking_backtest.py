#!/usr/bin/env python3
"""
run_gfs_concentrated_ranking_backtest.py
========================================
Comprehensive quantitative research backtest for FROZEN GFS STRATEGY:
- FROZEN ENTRY: Monthly RSI(14) > 60 AND Weekly RSI(14) > 60 AND Daily RSI(14) cross 40
- FROZEN EXIT: Monthly Close < Monthly EMA(9) evaluated at completed month end, exit next day open
- HIGH CONCENTRATION CAPACITIES: 2, 3, 5, 7, 10, 15 positions
- UNRESTRICTED SECTORS (Primary) + SECTOR LIMIT EXPERIMENTS (Secondary)
- SIGNAL RANKING METHODS:
    1. Monthly RSI
    2. Weekly RSI
    3. 3-Month Momentum
    4. 6-Month Momentum
    5. 12-Month Momentum
    6. Relative Volume
    7. Composite Momentum (30% M-RSI, 25% W-RSI, 10% 3M, 20% 6M, 10% 12M, 5% RelVol)
    8. Random Selection Baseline (Monte Carlo distribution)
    9. "Strong but not extended" distance from Monthly EMA9 bucket study
- Comprehensive Multibagger Capture, Concentration Analysis, Drawdowns, Worst Day/Month/Year,
  Walk-Forward Validation (6 annual folds: 2021-2026), and Cost Sensitivity (25, 50, 100 bps).
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

# -----------------------------------------------------------------------------
# STEP 1: INDICATOR CALCULATIONS
# -----------------------------------------------------------------------------
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

def compute_atr(df: pd.DataFrame, period: int = 20) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

# -----------------------------------------------------------------------------
# STEP 2: LOAD DATA AND BUILD CANDIDATES & LOOKUP CACHE
# -----------------------------------------------------------------------------
def load_and_enrich_data():
    t0 = time.time()
    print("=" * 80)
    print("STEP 1: LOADING HISTORICAL OHLCV & SECURITY MASTER")
    print("=" * 80)
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
        mcap_map = dict(zip(tfa["symbol"], tfa["mcap_cr"]))
    except Exception:
        sector_map = {}
        mcap_map = {}

    for sid, row in corp_sec.iterrows():
        s_sym = row["symbol"]
        if s_sym not in sector_map or not sector_map[s_sym]:
            ind = row["industry"]
            if pd.notna(ind) and ind.strip():
                sector_map[s_sym] = ind.title()
            else:
                sector_map[s_sym] = "Diversified / Other"

    # Daily data
    daily_raw = pd.read_sql("""
        SELECT security_id, date, open, high, low, close, volume 
        FROM daily_ohlcv 
        ORDER BY security_id, date ASC;
    """, conn)
    conn.close()

    daily_df = daily_raw[daily_raw["security_id"].isin(corp_ids)].copy()
    daily_df["date"] = daily_df["date"].astype(str)
    print(f"Loaded {len(daily_df):,} daily bars across {len(corp_ids)} stocks in {time.time()-t0:.2f}s.")

    # Build weekly & monthly candles and enrich candidate metrics
    print("\n" + "=" * 80)
    print("STEP 2: ENRICHING TECHNICAL INDICATORS & GENERATING GFS SIGNALS")
    print("=" * 80)
    t1 = time.time()

    processed_stocks = {}
    all_signals = []

    for sec_id, g in daily_df.groupby("security_id"):
        sym = sec_info[sec_id]["symbol"]
        comp = sec_info[sec_id]["company_name"]
        sector = sector_map.get(sym, "Diversified / Other")
        mcap = mcap_map.get(sym, np.nan)

        g = g.sort_values("date").copy()
        if len(g) < 60:
            continue

        # Daily indicators
        g["daily_rsi"] = compute_rsi(g["close"], 14)
        g["prev_daily_rsi"] = g["daily_rsi"].shift(1)
        g["vol_sma20"] = g["volume"].rolling(20).mean()
        g["rel_vol"] = (g["volume"] / g["vol_sma20"].replace(0, np.nan)).fillna(1.0)
        
        # Momentum returns
        g["ret_3m"] = (g["close"] / g["close"].shift(63) - 1.0) * 100.0
        g["ret_6m"] = (g["close"] / g["close"].shift(126) - 1.0) * 100.0
        g["ret_12m"] = (g["close"] / g["close"].shift(252) - 1.0) * 100.0
        
        # Volatility and ATR
        g["atr20"] = compute_atr(g, 20)
        g["atr20_pct"] = (g["atr20"] / g["close"]) * 100.0
        g["daily_ret"] = g["close"].pct_change()
        g["vol_60d"] = g["daily_ret"].rolling(60).std() * np.sqrt(252) * 100.0

        # Weekly aggregation
        g_dt = pd.to_datetime(g["date"])
        g["year_week"] = g_dt.dt.strftime("%Y-W%U")
        w_df = g.groupby("year_week").agg(
            w_open=("open", "first"),
            w_high=("high", "max"),
            w_low=("low", "min"),
            w_close=("close", "last"),
            last_date=("date", "last")
        ).reset_index()
        w_df["weekly_rsi_raw"] = compute_rsi(w_df["w_close"], 14)
        w_df["weekly_rsi_entry"] = w_df["weekly_rsi_raw"].shift(1)
        w_df["w_ema20"] = compute_ema(w_df["w_close"], 20)
        w_entry_map = dict(zip(w_df["year_week"], w_df["weekly_rsi_entry"]))
        g["weekly_rsi_completed"] = g["year_week"].map(w_entry_map)
        w_end_dates = set(w_df["last_date"].values)

        # Monthly aggregation
        g["year_month"] = g_dt.dt.strftime("%Y-%m")
        m_df = g.groupby("year_month").agg(
            m_open=("open", "first"),
            m_high=("high", "max"),
            m_low=("low", "min"),
            m_close=("close", "last"),
            last_date=("date", "last")
        ).reset_index()
        m_df["monthly_rsi_raw"] = compute_rsi(m_df["m_close"], 14)
        m_df["monthly_rsi_entry"] = m_df["monthly_rsi_raw"].shift(1)
        m_df["m_ema9"] = compute_ema(m_df["m_close"], 9)
        m_df["m_ema20"] = compute_ema(m_df["m_close"], 20)
        m_entry_map = dict(zip(m_df["year_month"], m_df["monthly_rsi_entry"]))
        m_ema9_entry_map = dict(zip(m_df["year_month"], m_df["m_ema9"].shift(1)))
        m_ema20_entry_map = dict(zip(m_df["year_month"], m_df["m_ema20"].shift(1)))

        g["monthly_rsi_completed"] = g["year_month"].map(m_entry_map)
        g["monthly_ema9_completed"] = g["year_month"].map(m_ema9_entry_map)
        g["monthly_ema20_completed"] = g["year_month"].map(m_ema20_entry_map)

        # Distances from completed Monthly EMAs
        g["dist_m_ema9"] = ((g["close"] - g["monthly_ema9_completed"]) / g["monthly_ema9_completed"].replace(0, np.nan)) * 100.0
        g["dist_m_ema20"] = ((g["close"] - g["monthly_ema20_completed"]) / g["monthly_ema20_completed"].replace(0, np.nan)) * 100.0

        m_end_dates = set(m_df["last_date"].values)
        m_info = m_df.set_index("last_date")

        g["is_month_end"] = g["date"].isin(m_end_dates)
        g["m_close"] = g["date"].map(m_info["m_close"]).fillna(np.nan)
        g["m_ema9"] = g["date"].map(m_info["m_ema9"]).fillna(np.nan)

        # Next-day open
        g["entry_date"] = g["date"].shift(-1)
        g["entry_open"] = g["open"].shift(-1)

        processed_stocks[sym] = g

        # Daily trigger: prev <= 40 and curr > 40
        son_cross = (g["prev_daily_rsi"] <= 40.0) & (g["daily_rsi"] > 40.0) & (g["entry_date"].notna())
        base_valid = son_cross & (g["weekly_rsi_completed"] > 60.0) & (g["monthly_rsi_completed"] > 60.0)

        sig_rows = g[base_valid]
        for _, row in sig_rows.iterrows():
            all_signals.append({
                "security_id": sec_id,
                "symbol": sym,
                "company_name": comp,
                "sector": sector,
                "mcap_cr": mcap,
                "signal_date": row["date"],
                "entry_date": row["entry_date"],
                "signal_close": row["close"],
                "entry_price": row["entry_open"],
                "prev_daily_rsi": row["prev_daily_rsi"],
                "daily_rsi": row["daily_rsi"],
                "weekly_rsi": row["weekly_rsi_completed"],
                "monthly_rsi": row["monthly_rsi_completed"],
                "ret_3m": row["ret_3m"],
                "ret_6m": row["ret_6m"],
                "ret_12m": row["ret_12m"],
                "dist_m_ema9": row["dist_m_ema9"],
                "dist_m_ema20": row["dist_m_ema20"],
                "rel_vol": row["rel_vol"],
                "atr20_pct": row["atr20_pct"],
                "vol_60d": row["vol_60d"]
            })

    signals_df = pd.DataFrame(all_signals).sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    print(f"Generated {len(signals_df):,} baseline GFS signals across universe in {time.time()-t1:.2f}s.")

    # Pre-build fast in-memory lookup cache
    t_c = time.time()
    stock_date_lookup = {sym: {r["date"]: r for r in df.to_dict(orient="records")} for sym, df in processed_stocks.items()}
    all_trading_days = sorted(list(set(d for sym_dict in stock_date_lookup.values() for d in sym_dict)))
    print(f"Fast lookup cache built in {time.time()-t_c:.2f}s for {len(stock_date_lookup)} stocks across {len(all_trading_days)} days.")

    return signals_df, processed_stocks, stock_date_lookup, all_trading_days

# -----------------------------------------------------------------------------
# STEP 3: CANDIDATE SIGNAL RANKING LOGIC
# -----------------------------------------------------------------------------
def rank_candidates(candidate_list: list, ranking_method: str, rng=None) -> list:
    """
    Ranks a list of candidate signals available on day d.
    Highest rank comes first.
    """
    if len(candidate_list) <= 1 or ranking_method == "none":
        return candidate_list

    if ranking_method == "random":
        shuffled = candidate_list.copy()
        if rng is not None:
            rng.shuffle(shuffled)
        else:
            np.random.shuffle(shuffled)
        return shuffled

    if ranking_method == "monthly_rsi":
        return sorted(candidate_list, key=lambda x: (x.get("monthly_rsi") if pd.notna(x.get("monthly_rsi")) else -999.0), reverse=True)

    if ranking_method == "weekly_rsi":
        return sorted(candidate_list, key=lambda x: (x.get("weekly_rsi") if pd.notna(x.get("weekly_rsi")) else -999.0), reverse=True)

    if ranking_method == "ret_3m":
        return sorted(candidate_list, key=lambda x: (x.get("ret_3m") if pd.notna(x.get("ret_3m")) else -999.0), reverse=True)

    if ranking_method == "ret_6m":
        return sorted(candidate_list, key=lambda x: (x.get("ret_6m") if pd.notna(x.get("ret_6m")) else -999.0), reverse=True)

    if ranking_method == "ret_12m":
        return sorted(candidate_list, key=lambda x: (x.get("ret_12m") if pd.notna(x.get("ret_12m")) else -999.0), reverse=True)

    if ranking_method == "rel_vol":
        return sorted(candidate_list, key=lambda x: (x.get("rel_vol") if pd.notna(x.get("rel_vol")) else -999.0), reverse=True)

    if ranking_method == "composite":
        # Percentile ranking for:
        # 30% Monthly RSI, 25% Weekly RSI, 10% 3M, 20% 6M, 10% 12M, 5% Relative Volume
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

# -----------------------------------------------------------------------------
# STEP 4: CONCENTRATED PORTFOLIO SIMULATION ENGINE
# -----------------------------------------------------------------------------
def simulate_concentrated_portfolio(
    signals_subset: pd.DataFrame,
    stock_date_lookup: dict,
    all_trading_days: list,
    capacity: int = 5,
    ranking_method: str = "composite",
    sector_restriction: str = "none", # 'none', 'max2', 'max3', 'cap25'
    cost_bps: float = 25.0,
    start_date: str = "2018-01-01",
    end_date: str = "2026-12-31",
    random_seed: int = None
):
    """
    Simulates high-concentration equal-weight portfolio with FROZEN Monthly EMA9 exit.
    """
    STARTING_CAPITAL = 1_000_000.0
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)

    # Random number generator if needed
    rng = np.random.default_rng(random_seed) if random_seed is not None else None

    # Pre-group signals by signal_date
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

    max_sector_exposure_recorded = 0.0
    max_single_stock_exposure_recorded = 0.0

    for d_idx, d in enumerate(sim_dates):
        # 1. Process Pending Exits from Month-End
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
                proceeds = pos["shares"] * exit_price
                cash += proceeds
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

        # 2. Daily Portfolio Valuation
        invested_equity = sum(pos["shares"] * pos["last_close"] for pos in open_positions.values())
        total_equity = cash + invested_equity

        # Track Single Stock & Sector Concentrations
        if total_equity > 0 and open_positions:
            for pos in open_positions.values():
                stock_exp = (pos["shares"] * pos["last_close"]) / total_equity * 100.0
                if stock_exp > max_single_stock_exposure_recorded:
                    max_single_stock_exposure_recorded = stock_exp

            sector_sums = {}
            for pos in open_positions.values():
                sector_sums[pos["sector"]] = sector_sums.get(pos["sector"], 0.0) + (pos["shares"] * pos["last_close"])
            for sec_val in sector_sums.values():
                sec_exp = sec_val / total_equity * 100.0
                if sec_exp > max_sector_exposure_recorded:
                    max_sector_exposure_recorded = sec_exp

        # 3. New Entries (Day d Open from Day d-1 signals)
        prev_d = sim_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        available_slots = capacity - len(open_positions)
        if day_signals and available_slots > 0 and cash > 1000.0:
            # Filter out already owned stocks
            cands = [s for s in day_signals if s["symbol"] not in open_positions]

            # Apply Sector Filter if specified
            if sector_restriction != "none" and cands:
                valid_cands = []
                for c in cands:
                    sec = c["sector"]
                    sec_count = sum(1 for p in open_positions.values() if p["sector"] == sec)
                    if sector_restriction == "max2" and sec_count >= 2:
                        continue
                    elif sector_restriction == "max3" and sec_count >= 3:
                        continue
                    elif sector_restriction == "cap25":
                        max_sec = max(1, int(round(capacity * 0.25)))
                        if sec_count >= max_sec:
                            continue
                    valid_cands.append(c)
                cands = valid_cands

            if cands:
                # Rank Candidates!
                ranked_cands = rank_candidates(cands, ranking_method, rng=rng)

                alloc_per_slot = total_equity / capacity
                for cand in ranked_cands[:available_slots]:
                    s_sym = cand["symbol"]
                    raw_entry_p = cand["entry_price"]
                    sim_entry_p = raw_entry_p * cost_mult_entry
                    sec = cand["sector"]

                    # Re-check sector if multiple chosen
                    if sector_restriction != "none":
                        sec_count = sum(1 for p in open_positions.values() if p["sector"] == sec)
                        if sector_restriction == "max2" and sec_count >= 2:
                            continue
                        elif sector_restriction == "max3" and sec_count >= 3:
                            continue
                        elif sector_restriction == "cap25" and sec_count >= max(1, int(round(capacity * 0.25))):
                            continue

                    avail_alloc = min(cash, alloc_per_slot)
                    if avail_alloc > 1000.0:
                        shares = avail_alloc / sim_entry_p
                        cash -= avail_alloc
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
            cp = r["close"]
            pos["last_close"] = cp

            # Check Monthly Close < Monthly EMA9 on completed month-end
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

    # Close remaining positions on last day
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

    # Performance Metrics
    daily_df["ret_1d"] = daily_df["equity"].pct_change().fillna(0.0)
    daily_df["ret_5d"] = daily_df["equity"].pct_change(5).fillna(0.0)
    daily_df["ret_20d"] = daily_df["equity"].pct_change(20).fillna(0.0)
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

    # Drawdown Duration
    dd_mask = daily_df["drawdown"] < -1e-4
    dd_durations = []
    cur_dur = 0
    for is_dd in dd_mask:
        if is_dd:
            cur_dur += 1
        else:
            if cur_dur > 0:
                dd_durations.append(cur_dur)
            cur_dur = 0
    if cur_dur > 0:
        dd_durations.append(cur_dur)
    max_dd_duration = max(dd_durations) if dd_durations else 0

    # Worst Day / 5-Day / 20-Day
    worst_day = daily_df["ret_1d"].min() * 100.0
    worst_5d = daily_df["ret_5d"].min() * 100.0
    worst_20d = daily_df["ret_20d"].min() * 100.0

    # Monthly and Annual Returns
    daily_df["date_dt"] = pd.to_datetime(daily_df["date"])
    m_returns = daily_df.set_index("date_dt")["equity"].resample("ME").last().pct_change().dropna() * 100.0
    worst_month = m_returns.min() if not m_returns.empty else 0.0
    y_returns = daily_df.set_index("date_dt")["equity"].resample("YE").last().pct_change().dropna() * 100.0
    worst_year = y_returns.min() if not y_returns.empty else 0.0

    # Trades stats
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

        # Consecutive losing streak
        trades_df["is_loss"] = trades_df["return_pct"] <= 0
        l_streak = max_l_streak = 0
        for isl in trades_df["is_loss"]:
            if isl:
                l_streak += 1
                max_l_streak = max(max_l_streak, l_streak)
            else:
                l_streak = 0
    else:
        win_rate = avg_ret = med_ret = profit_factor = turnover = 0.0
        w50 = w100 = w200 = w300 = w500 = max_winner = max_l_streak = 0.0

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
        "worst_day": worst_day,
        "worst_5d": worst_5d,
        "worst_20d": worst_20d,
        "worst_month": worst_month,
        "worst_year": worst_year,
        "max_dd_duration": max_dd_duration,
        "max_losing_streak": max_l_streak,
        "max_single_stock_exp": max_single_stock_exposure_recorded,
        "max_sector_exp": max_sector_exposure_recorded,
        "min_positions": daily_df["positions"].min(),
        "avg_positions": daily_df["positions"].mean(),
        "max_positions": daily_df["positions"].max()
    }

    return summary, daily_df, trades_df

# -----------------------------------------------------------------------------
# STEP 5: MAIN RESEARCH EXECUTION ROUTINE
# -----------------------------------------------------------------------------
def run_all_concentrated_research():
    signals_df, processed_stocks, stock_date_lookup, all_trading_days = load_and_enrich_data()

    capacities = [2, 3, 5, 7, 10, 15]
    ranking_methods = [
        ("Monthly RSI", "monthly_rsi"),
        ("Weekly RSI", "weekly_rsi"),
        ("3M Return", "ret_3m"),
        ("6M Return", "ret_6m"),
        ("12M Return", "ret_12m"),
        ("Relative Volume", "rel_vol"),
        ("Composite Momentum", "composite")
    ]

    # -------------------------------------------------------------------------
    # EXPERIMENT 1: RANDOM SELECTION BASELINE (MONTE CARLO)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 1: RANDOM SELECTION BASELINE (50 Monte Carlo Iterations per Capacity)")
    print("=" * 80)
    n_mc = 50
    random_mc_results = {}
    random_summary_rows = []

    for cap in capacities:
        cagr_list, dd_list, pf_list, wr_list, t_list = [], [], [], [], []
        w50_l, w100_l, maxw_l = [], [], []

        for seed in range(n_mc):
            s, _, tr = simulate_concentrated_portfolio(
                signals_df, stock_date_lookup, all_trading_days,
                capacity=cap, ranking_method="random", sector_restriction="none",
                cost_bps=25.0, random_seed=seed + 100
            )
            cagr_list.append(s["cagr"])
            dd_list.append(s["max_drawdown"])
            pf_list.append(s["profit_factor"])
            wr_list.append(s["win_rate"])
            t_list.append(s["num_trades"])
            w50_l.append(s["w50"])
            w100_l.append(s["w100"])
            maxw_l.append(s["max_winner"])

        random_mc_results[cap] = {
            "cagr_mean": np.mean(cagr_list),
            "cagr_median": np.median(cagr_list),
            "cagr_p5": np.percentile(cagr_list, 5),
            "cagr_p95": np.percentile(cagr_list, 95),
            "dd_mean": np.mean(dd_list),
            "dd_median": np.median(dd_list),
            "pf_mean": np.mean(pf_list),
            "wr_mean": np.mean(wr_list),
            "trades_mean": np.mean(t_list),
            "w50_mean": np.mean(w50_l),
            "w100_mean": np.mean(w100_l),
            "maxw_mean": np.mean(maxw_l)
        }

        row = {
            "Ranking Method": "Random Selection (Mean)",
            "Positions": cap,
            "CAGR": np.mean(cagr_list),
            "CAGR_Median": np.median(cagr_list),
            "CAGR_5th": np.percentile(cagr_list, 5),
            "CAGR_95th": np.percentile(cagr_list, 95),
            "Max DD": np.mean(dd_list),
            "Profit Factor": np.mean(pf_list),
            "Win Rate": np.mean(wr_list),
            "Trades": np.mean(t_list),
            ">50% Winners": np.mean(w50_l),
            ">100% Winners": np.mean(w100_l),
            "Maximum Winner": np.mean(maxw_l)
        }
        random_summary_rows.append(row)
        print(f"Random [{cap:2d} slots] -> CAGR Mean: {row['CAGR']:6.2f}% (P5: {row['CAGR_5th']:5.1f}%, P95: {row['CAGR_95th']:5.1f}%) | MaxDD: {row['Max DD']:6.2f}% | PF: {row['Profit Factor']:4.2f} | >100%: {row['>100% Winners']:4.1f}")

    random_df = pd.DataFrame(random_summary_rows)
    random_df.to_csv(REPORTS_DIR / "gfs_ranking_random_distribution.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 2: PRIMARY RANKING METHODS ACROSS CAPACITIES
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 2: PRIMARY RANKING METHODS ACROSS CAPACITIES (Unrestricted Sectors)")
    print("=" * 80)
    master_rows = []
    concentration_rows = []
    multibagger_rows = []
    all_trade_dfs = []

    # First add random baseline rows to master
    for cap in capacities:
        rnd = random_mc_results[cap]
        master_rows.append({
            "Ranking Method": "Random Baseline (Mean)",
            "Positions": cap,
            "CAGR": rnd["cagr_mean"],
            "Max DD": rnd["dd_mean"],
            "Profit Factor": rnd["pf_mean"],
            "Win Rate": rnd["wr_mean"],
            "Avg Trade": 0.0,
            "Median Trade": 0.0,
            "Sharpe": 0.0,
            "Calmar": abs(rnd["cagr_mean"] / rnd["dd_mean"]) if abs(rnd["dd_mean"]) > 1e-4 else 0.0,
            "Annual Turnover": 0.0,
            ">50% Winners": rnd["w50_mean"],
            ">100% Winners": rnd["w100_mean"],
            ">200% Winners": 0.0,
            ">500% Winners": 0.0,
            "Maximum Winner": rnd["maxw_mean"],
            "Worst Day": 0.0,
            "Worst Month": 0.0,
            "Worst Year": 0.0,
            "OOS CAGR": 0.0,
            "OOS Max DD": 0.0
        })

    # Benchmark: find total potential multibaggers in opportunity set under Monthly EMA9
    s_full, _, tr_full = simulate_concentrated_portfolio(
        signals_df, stock_date_lookup, all_trading_days,
        capacity=100, ranking_method="composite", sector_restriction="none", cost_bps=25.0
    )
    total_w50_available = len(tr_full[tr_full["return_pct"] >= 50.0])
    total_w100_available = len(tr_full[tr_full["return_pct"] >= 100.0])
    total_w200_available = len(tr_full[tr_full["return_pct"] >= 200.0])
    print(f"Total opportunity set under Monthly EMA9 (100 capacity): {len(tr_full)} trades | >50%: {total_w50_available} | >100%: {total_w100_available} | >200%: {total_w200_available}")

    for r_label, r_method in ranking_methods:
        for cap in capacities:
            s, ddf, tr = simulate_concentrated_portfolio(
                signals_df, stock_date_lookup, all_trading_days,
                capacity=cap, ranking_method=r_method, sector_restriction="none", cost_bps=25.0
            )
            tr["ranking_method"] = r_label
            tr["capacity"] = cap
            all_trade_dfs.append(tr)

            # Multibagger capture
            w50_cap_pct = (s["w50"] / total_w50_available * 100.0) if total_w50_available > 0 else 0.0
            w100_cap_pct = (s["w100"] / total_w100_available * 100.0) if total_w100_available > 0 else 0.0
            w200_cap_pct = (s["w200"] / total_w200_available * 100.0) if total_w200_available > 0 else 0.0

            multibagger_rows.append({
                "Ranking Method": r_label,
                "Positions": cap,
                "Trades": s["num_trades"],
                ">50% Count": s["w50"],
                ">50% Capture %": w50_cap_pct,
                ">100% Count": s["w100"],
                ">100% Capture %": w100_cap_pct,
                ">200% Count": s["w200"],
                ">200% Capture %": w200_cap_pct,
                ">300% Count": s["w300"],
                ">500% Count": s["w500"],
                "Max Winner %": s["max_winner"]
            })

            concentration_rows.append({
                "Ranking Method": r_label,
                "Positions": cap,
                "Max Single Stock Exp %": s["max_single_stock_exp"],
                "Max Sector Exp %": s["max_sector_exp"],
                "Min Positions": s["min_positions"],
                "Avg Positions": s["avg_positions"],
                "Max Positions": s["max_positions"],
                "Worst 1D Loss %": s["worst_day"],
                "Worst 5D Loss %": s["worst_5d"],
                "Worst 20D Loss %": s["worst_20d"],
                "Max DD Duration (Days)": s["max_dd_duration"],
                "Max Losing Streak": s["max_losing_streak"]
            })

            master_rows.append({
                "Ranking Method": r_label,
                "Positions": cap,
                "CAGR": s["cagr"],
                "Max DD": s["max_drawdown"],
                "Profit Factor": s["profit_factor"],
                "Win Rate": s["win_rate"],
                "Avg Trade": s["avg_trade_ret"],
                "Median Trade": s["median_trade_ret"],
                "Sharpe": s["sharpe"],
                "Calmar": s["calmar"],
                "Annual Turnover": s["annual_turnover"],
                ">50% Winners": s["w50"],
                ">100% Winners": s["w100"],
                ">200% Winners": s["w200"],
                ">500% Winners": s["w500"],
                "Maximum Winner": s["max_winner"],
                "Worst Day": s["worst_day"],
                "Worst Month": s["worst_month"],
                "Worst Year": s["worst_year"],
                "OOS CAGR": 0.0,
                "OOS Max DD": 0.0
            })

            print(f"{r_label:20s} [{cap:2d} pos] -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | WinRate: {s['win_rate']:4.1f}% | >100%: {s['w100']:2d} | Worst 1D: {s['worst_day']:5.1f}% | MaxSecExp: {s['max_sector_exp']:5.1f}%")

    all_trades_df = pd.concat(all_trade_dfs, ignore_index=True)
    all_trades_df.to_csv(REPORTS_DIR / "gfs_ranking_trade_log.csv", index=False)

    multibagger_df = pd.DataFrame(multibagger_rows)
    multibagger_df.to_csv(REPORTS_DIR / "gfs_ranking_multibagger_capture.csv", index=False)

    concentration_df = pd.DataFrame(concentration_rows)
    concentration_df.to_csv(REPORTS_DIR / "gfs_ranking_concentration_metrics.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 3: "STRONG BUT NOT EXTENDED" - DISTANCE FROM MONTHLY EMA9
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 3: 'STRONG BUT NOT EXTENDED' BUCKET STUDY (Distance from Monthly EMA9)")
    print("=" * 80)

    bucket_rows = []
    buckets = [
        ("0–10%", 0.0, 10.0),
        ("10–20%", 10.0, 20.0),
        ("20–30%", 20.0, 30.0),
        ("30–50%", 30.0, 50.0),
        (">50%", 50.0, 9999.0)
    ]

    for b_label, b_min, b_max in buckets:
        sub_sigs = signals_df[(signals_df["dist_m_ema9"] >= b_min) & (signals_df["dist_m_ema9"] < b_max)].copy()
        
        fwd_20_list, fwd_60_list, fwd_120_list, fwd_180_list = [], [], [], []
        mfe_180_list, mae_180_list = [], []

        for _, srow in sub_sigs.iterrows():
            sym = srow["symbol"]
            e_date = srow["entry_date"]
            e_p = srow["entry_price"]
            df_sym = processed_stocks[sym]
            
            post_bars = df_sym[df_sym["date"] >= e_date].copy()
            if len(post_bars) < 20:
                continue

            fwd_20 = (post_bars.iloc[min(19, len(post_bars)-1)]["close"] - e_p) / e_p * 100.0
            fwd_60 = (post_bars.iloc[min(59, len(post_bars)-1)]["close"] - e_p) / e_p * 100.0 if len(post_bars) >= 60 else np.nan
            fwd_120 = (post_bars.iloc[min(119, len(post_bars)-1)]["close"] - e_p) / e_p * 100.0 if len(post_bars) >= 120 else np.nan
            fwd_180 = (post_bars.iloc[min(179, len(post_bars)-1)]["close"] - e_p) / e_p * 100.0 if len(post_bars) >= 180 else np.nan

            b180 = post_bars.iloc[:min(180, len(post_bars))]
            mfe_180 = (b180["high"].max() - e_p) / e_p * 100.0
            mae_180 = (b180["low"].min() - e_p) / e_p * 100.0

            fwd_20_list.append(fwd_20)
            if pd.notna(fwd_60): fwd_60_list.append(fwd_60)
            if pd.notna(fwd_120): fwd_120_list.append(fwd_120)
            if pd.notna(fwd_180): fwd_180_list.append(fwd_180)
            mfe_180_list.append(mfe_180)
            mae_180_list.append(mae_180)

        bucket_rows.append({
            "EMA9_Distance_Bucket": b_label,
            "Sample_Count": len(fwd_20_list),
            "Avg_20D_Return %": np.mean(fwd_20_list) if fwd_20_list else 0.0,
            "Median_20D_Return %": np.median(fwd_20_list) if fwd_20_list else 0.0,
            "Avg_60D_Return %": np.mean(fwd_60_list) if fwd_60_list else 0.0,
            "Median_60D_Return %": np.median(fwd_60_list) if fwd_60_list else 0.0,
            "Avg_120D_Return %": np.mean(fwd_120_list) if fwd_120_list else 0.0,
            "Median_120D_Return %": np.median(fwd_120_list) if fwd_120_list else 0.0,
            "Avg_180D_Return %": np.mean(fwd_180_list) if fwd_180_list else 0.0,
            "Median_180D_Return %": np.median(fwd_180_list) if fwd_180_list else 0.0,
            "Median_MFE_180D %": np.median(mfe_180_list) if mfe_180_list else 0.0,
            "Median_MAE_180D %": np.median(mae_180_list) if mae_180_list else 0.0
        })
        print(f"Bucket {b_label:8s} (N={len(fwd_20_list):4d}) -> 60D Med: {np.median(fwd_60_list):5.1f}% | 120D Med: {np.median(fwd_120_list):5.1f}% | 180D Med: {np.median(fwd_180_list):5.1f}% | MFE: {np.median(mfe_180_list):5.1f}% | MAE: {np.median(mae_180_list):5.1f}%")

    bucket_df = pd.DataFrame(bucket_rows)
    bucket_df.to_csv(REPORTS_DIR / "gfs_ranking_strong_not_extended.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 4: SECTOR RESTRICTION EXPERIMENT
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 4: SECTOR RESTRICTION EXPERIMENT (No Limit vs Max 2 vs Max 3 vs 25% Cap)")
    print("=" * 80)
    sector_rules = [
        ("No Sector Restriction", "none"),
        ("Max 2 Stocks / Sector", "max2"),
        ("Max 3 Stocks / Sector", "max3"),
        ("25% Sector Cap", "cap25")
    ]
    sec_exp_rows = []

    for s_name, s_code in sector_rules:
        for r_label, r_code in [("Composite Momentum", "composite"), ("Monthly RSI", "monthly_rsi")]:
            for cap in [3, 5, 7, 10, 15]:
                s, _, _ = simulate_concentrated_portfolio(
                    signals_df, stock_date_lookup, all_trading_days,
                    capacity=cap, ranking_method=r_code, sector_restriction=s_code, cost_bps=25.0
                )
                sec_exp_rows.append({
                    "Sector_Restriction": s_name,
                    "Ranking_Method": r_label,
                    "Positions": cap,
                    "CAGR": s["cagr"],
                    "MaxDD": s["max_drawdown"],
                    "ProfitFactor": s["profit_factor"],
                    "WinRate": s["win_rate"],
                    "Trades": s["num_trades"],
                    "Max_Sector_Exposure %": s["max_sector_exp"],
                    "Calmar": s["calmar"]
                })
                print(f"[{s_name:23s}] {r_label:18s} [{cap:2d} slots] -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:4.2f} | MaxSecExp: {s['max_sector_exp']:5.1f}%")

    sec_df = pd.DataFrame(sec_exp_rows)
    sec_df.to_csv(REPORTS_DIR / "gfs_ranking_sector_experiment.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 5: TRANSACTION COST SENSITIVITY (25, 50, 100 bps)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 5: TRANSACTION COST SENSITIVITY (25, 50, 100 bps)")
    print("=" * 80)
    cost_rows = []
    test_methods = [("Composite Momentum", "composite"), ("Monthly RSI", "monthly_rsi"), ("6M Return", "ret_6m")]

    for r_label, r_code in test_methods:
        for cap in [3, 5, 7, 10, 15]:
            for c_bps in [25.0, 50.0, 100.0]:
                s, _, _ = simulate_concentrated_portfolio(
                    signals_df, stock_date_lookup, all_trading_days,
                    capacity=cap, ranking_method=r_code, sector_restriction="none", cost_bps=c_bps
                )
                cost_rows.append({
                    "Ranking_Method": r_label,
                    "Positions": cap,
                    "Cost_Bps": c_bps,
                    "CAGR": s["cagr"],
                    "MaxDD": s["max_drawdown"],
                    "ProfitFactor": s["profit_factor"],
                    "WinRate": s["win_rate"],
                    "AnnualTurnover": s["annual_turnover"],
                    "EndingCapital": s["ending_capital"]
                })
                print(f"{r_label:18s} [{cap:2d} pos] @ {c_bps:3.0f} bps -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:4.2f}")

    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(REPORTS_DIR / "gfs_ranking_cost_sensitivity.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 6: CHRONOLOGICAL WALK-FORWARD VALIDATION (6 ANNUAL FOLDS)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 6: CHRONOLOGICAL WALK-FORWARD VALIDATION (6 Annual Folds: 2021-2026)")
    print("=" * 80)
    folds = [
        ("Fold 1", "2018-01-01", "2020-12-31", "2021-01-01", "2021-12-31"),
        ("Fold 2", "2018-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
        ("Fold 3", "2018-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
        ("Fold 4", "2018-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
        ("Fold 5", "2018-01-01", "2024-12-31", "2025-01-01", "2025-12-31"),
        ("Fold 6", "2018-01-01", "2025-12-31", "2026-01-01", "2026-12-31"),
    ]

    wf_rows = []
    oos_tracking = {}

    for f_name, train_s, train_e, test_s, test_e in folds:
        for r_label, r_code in ranking_methods:
            for cap in [3, 5, 7, 10, 15]:
                s_train, _, _ = simulate_concentrated_portfolio(
                    signals_df, stock_date_lookup, all_trading_days,
                    capacity=cap, ranking_method=r_code, sector_restriction="none",
                    cost_bps=25.0, start_date=train_s, end_date=train_e
                )
                s_test, _, _ = simulate_concentrated_portfolio(
                    signals_df, stock_date_lookup, all_trading_days,
                    capacity=cap, ranking_method=r_code, sector_restriction="none",
                    cost_bps=25.0, start_date=test_s, end_date=test_e
                )
                wf_rows.append({
                    "Fold": f_name,
                    "Ranking_Method": r_label,
                    "Positions": cap,
                    "Train_Period": f"{train_s[:4]}-{train_e[:4]}",
                    "Test_Period": f"{test_s[:4]}-{test_e[:4]}",
                    "Train_CAGR": s_train["cagr"],
                    "Train_PF": s_train["profit_factor"],
                    "Test_Return": s_test["total_return_pct"],
                    "Test_MaxDD": s_test["max_drawdown"],
                    "Test_PF": s_test["profit_factor"],
                    "Test_WinRate": s_test["win_rate"],
                    "Test_Trades": s_test["num_trades"]
                })
                oos_tracking.setdefault((r_label, cap), []).append((s_test["total_return_pct"], s_test["max_drawdown"]))
                print(f"{f_name} [{r_label:18s} {cap:2d} pos] -> Train CAGR: {s_train['cagr']:5.1f}% | Test Ret: {s_test['total_return_pct']:5.1f}% | Test MaxDD: {s_test['max_drawdown']:5.1f}% | Test PF: {s_test['profit_factor']:4.2f}")

    wf_df = pd.DataFrame(wf_rows)
    wf_df.to_csv(REPORTS_DIR / "gfs_ranking_walk_forward.csv", index=False)

    master_df = pd.DataFrame(master_rows)
    for idx, row in master_df.iterrows():
        key = (row["Ranking Method"], row["Positions"])
        if key in oos_tracking:
            rets = [x[0] for x in oos_tracking[key]]
            dds = [x[1] for x in oos_tracking[key]]
            geom_mult = 1.0
            for r in rets:
                geom_mult *= (1.0 + r / 100.0)
            oos_cagr = (geom_mult ** (1.0 / len(rets)) - 1.0) * 100.0 if geom_mult > 0 else -100.0
            master_df.at[idx, "OOS CAGR"] = oos_cagr
            master_df.at[idx, "OOS Max DD"] = min(dds)

    master_df.to_csv(REPORTS_DIR / "gfs_ranking_master_table.csv", index=False)
    print("\n" + "=" * 80)
    print("ALL CONCENTRATED GFS RANKING EXPERIMENTS COMPLETED SUCCESSFULLY!")
    print(f"Master Table saved to: {REPORTS_DIR / 'gfs_ranking_master_table.csv'}")
    print("=" * 80)

if __name__ == "__main__":
    run_all_concentrated_research()
