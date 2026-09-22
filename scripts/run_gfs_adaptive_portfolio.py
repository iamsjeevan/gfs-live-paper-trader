"""
GFS ADAPTIVE PORTFOLIO — QUANTITATIVE RESEARCH & SIMULATION ENGINE
Independent backtesting of adaptive portfolio extensions for the Grandfather-Father-Son (GFS) RSI strategy.

Strategy Rules:
- Grandfather: Monthly RSI(14) > 60 (strictly completed prior month)
- Father: Weekly RSI(14) > 60 (strictly completed prior week)
- Son: Daily RSI(14) crosses above 40 (prev <= 40, curr > 40)
- Entry: Day T+1 Open

Adaptive Components Tested:
1. Momentum Stock Selection (Weekly RSI, Monthly RSI, 20D Mom, 60D Mom, RS vs NIFTY, Rel Vol, Composite)
2. Portfolio Capacity (5, 10, 15, 20, 30 slots)
3. Market Regime Dynamic Allocation (NIFTY 50 200 EMA + trend -> Bull, Neutral, Bear schedules)
4. Sector Rotation & Concentration Control (20%, 25%, 33% caps, Top 2/3/5 sectors)
5. Initial Stop-loss (-5%) with activation (+3%, +5%, +7%, +10%) & EMA21 trailing exit
6. Progressive Models (Model 0 to Model 4)
7. Full 7-combination Ablation Study
8. Expanding Walk-Forward Validation (6 folds)
9. Monte Carlo Simulation (5,000 runs)
10. Realistic Transaction Costs & Slippage (0, 25, 50, 100, 150 bps)
"""

import sqlite3
import time
import os
from pathlib import Path
import numpy as np
import pandas as pd

DB_PATH = Path("data/indian_market.db")
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

EXCLUDED_SYMBOLS = {
    "NIFTY50", "BANKNIFTY", "NIFTYIT", "NIFTYBEES", "GOLDBEES", "BANKBEES",
    "LIQUIDBEES", "INFRABEES", "JUNIORBEES", "MON100", "CPSEETF", "SILVERBEES",
    "AUTOBEES", "PHARMABEES", "SETFNIF50", "HDFCMFGETF", "ICICIB22", "KOTAKBKETF"
}

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, 1e-9)
    return 100.0 - (100.0 / (1.0 + rs))

def compute_ema(series: pd.Series, span: int = 21) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def load_universe_and_enrich_data():
    """Load universe, daily data, NIFTY 50, sectors, and precompute indicators."""
    print("=" * 80)
    print("STEP 1: LOADING DATA & PRECOMPUTING INDICATORS")
    print("=" * 80)
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)

    # 1. Securities Master
    sec_df = pd.read_sql("SELECT security_id, symbol, company_name, industry FROM securities;", conn)
    etf_mask = sec_df["symbol"].isin(EXCLUDED_SYMBOLS) | sec_df["symbol"].str.contains("BEES|ETF|NIFTY", case=False, na=False)
    corp_sec = sec_df[~etf_mask].copy()
    sec_info = corp_sec.set_index("security_id").to_dict(orient="index")
    corp_ids = set(corp_sec["security_id"])

    # 2. Sector Mapping
    try:
        tfa = pd.read_sql("SELECT DISTINCT Ticker as symbol, sector, mcap_cr FROM trades_fundamental_analysis WHERE sector IS NOT NULL AND sector != '';", conn)
        sector_map = dict(zip(tfa["symbol"], tfa["sector"]))
        mcap_map = dict(zip(tfa["symbol"], tfa["mcap_cr"]))
    except Exception:
        sector_map, mcap_map = {}, {}

    # Fill remaining sectors from industry
    for sid, row in corp_sec.iterrows():
        s_sym = row["symbol"]
        if s_sym not in sector_map or not sector_map[s_sym]:
            ind = row["industry"]
            if pd.notna(ind) and ind.strip():
                sector_map[s_sym] = ind.title()
            else:
                sector_map[s_sym] = "Diversified / Other"

    # 3. NIFTY 50 Data
    nifty_df = pd.read_sql("SELECT date, open, high, low, close, volume FROM daily_ohlcv WHERE security_id = 2835 ORDER BY date ASC;", conn)
    nifty_df["date_dt"] = pd.to_datetime(nifty_df["date"])
    nifty_df["nifty_ema200"] = compute_ema(nifty_df["close"], 200)
    nifty_df["nifty_ema50"] = compute_ema(nifty_df["close"], 50)
    nifty_df["nifty_ret_20d"] = nifty_df["close"].pct_change(20)
    nifty_df["nifty_ret_60d"] = nifty_df["close"].pct_change(60)

    # NIFTY regime on date T Close:
    # BULL: Close > EMA200 AND Close > EMA50
    # NEUTRAL: Close > EMA200 AND Close <= EMA50
    # BEAR: Close <= EMA200
    nifty_df["bull_flag"] = (nifty_df["close"] > nifty_df["nifty_ema200"]) & (nifty_df["close"] > nifty_df["nifty_ema50"])
    nifty_df["bear_flag"] = nifty_df["close"] <= nifty_df["nifty_ema200"]
    nifty_df["regime"] = "NEUTRAL"
    nifty_df.loc[nifty_df["bull_flag"], "regime"] = "BULL"
    nifty_df.loc[nifty_df["bear_flag"], "regime"] = "BEAR"

    nifty_regime_map = dict(zip(nifty_df["date"], nifty_df["regime"]))
    nifty_ret20_map = dict(zip(nifty_df["date"], nifty_df["nifty_ret_20d"]))
    nifty_ret60_map = dict(zip(nifty_df["date"], nifty_df["nifty_ret_60d"]))

    # 4. Equities Daily Data
    daily_df = pd.read_sql("SELECT security_id, date, open, high, low, close, volume FROM daily_ohlcv ORDER BY security_id, date ASC;", conn)
    daily_df = daily_df[daily_df["security_id"].isin(corp_ids)].copy()
    conn.close()

    print(f"Loaded {len(daily_df):,} daily bars across {daily_df['security_id'].nunique():,} corporate equities in {time.time()-t0:.2f}s.")
    print(f"NIFTY 50 bars loaded: {len(nifty_df):,}")

    return daily_df, nifty_df, sec_info, sector_map, mcap_map, nifty_regime_map, nifty_ret20_map, nifty_ret60_map

def process_stocks_and_signals(daily_df, sec_info, sector_map, nifty_ret20_map, nifty_ret60_map):
    """Compute indicators, detect strictly causal GFS signals, and enrich with momentum factors."""
    print("\n" + "=" * 80)
    print("STEP 2: PROCESSING STOCKS & GENERATING ENRICHED GFS SIGNALS")
    print("=" * 80)
    t0 = time.time()

    all_signals = []
    processed_stocks = {}
    grouped = daily_df.groupby("security_id")
    total_stocks = len(grouped)

    for sec_id, g in grouped:
        if len(g) < 60:
            continue
        sym = sec_info[sec_id]["symbol"]
        comp = sec_info[sec_id]["company_name"]
        sector = sector_map.get(sym, "Diversified / Other")

        g = g.sort_values("date").copy().reset_index(drop=True)
        g["date_dt"] = pd.to_datetime(g["date"])
        g["year_week"] = g["date_dt"].dt.strftime("%G-W%V")
        g["year_month"] = g["date_dt"].dt.strftime("%Y-%m")
        g["sector"] = sector

        c = g["close"]
        v = g["volume"]

        # Daily indicators
        g["daily_rsi"] = compute_rsi(c, 14)
        g["prev_daily_rsi"] = g["daily_rsi"].shift(1)
        g["daily_ema21"] = compute_ema(c, 21)
        g["ret_20d"] = c.pct_change(20)
        g["ret_60d"] = c.pct_change(60)
        g["vol_ma20"] = v.rolling(20).mean().replace(0.0, np.nan)
        g["rel_vol_20d"] = (v / g["vol_ma20"]).fillna(1.0)

        # Weekly RSI (completed prior week)
        w_df = g.groupby("year_week").agg({"close": "last", "date": ["first", "last"]}).reset_index()
        w_df.columns = ["year_week", "close", "start_date", "end_date"]
        w_df["weekly_rsi"] = compute_rsi(w_df["close"], 14)
        w_df["completed_weekly_rsi"] = w_df["weekly_rsi"].shift(1)
        w_df["completed_week_end_date"] = w_df["end_date"].shift(1)
        w_map_rsi = dict(zip(w_df["year_week"], w_df["completed_weekly_rsi"]))
        w_map_end = dict(zip(w_df["year_week"], w_df["completed_week_end_date"]))
        g["weekly_rsi_completed"] = g["year_week"].map(w_map_rsi)
        g["weekly_completed_end_date"] = g["year_week"].map(w_map_end)

        # Monthly RSI (completed prior month)
        m_df = g.groupby("year_month").agg({"close": "last", "date": ["first", "last"]}).reset_index()
        m_df.columns = ["year_month", "close", "start_date", "end_date"]
        m_df["monthly_rsi"] = compute_rsi(m_df["close"], 14)
        m_df["completed_monthly_rsi"] = m_df["monthly_rsi"].shift(1)
        m_df["completed_month_end_date"] = m_df["end_date"].shift(1)
        m_map_rsi = dict(zip(m_df["year_month"], m_df["completed_monthly_rsi"]))
        m_map_end = dict(zip(m_df["year_month"], m_df["completed_month_end_date"]))
        g["monthly_rsi_completed"] = g["year_month"].map(m_map_rsi)
        g["monthly_completed_end_date"] = g["year_month"].map(m_map_end)

        # Next-Day Open Price & Entry Date
        g["entry_date"] = g["date"].shift(-1)
        g["entry_open"] = g["open"].shift(-1)

        processed_stocks[sym] = g

        # Son Daily Crossing Condition
        son_cross = (g["prev_daily_rsi"] <= 40.0) & (g["daily_rsi"] > 40.0)
        father_ok = g["weekly_rsi_completed"] > 60.0
        grandfather_ok = g["monthly_rsi_completed"] > 60.0

        gfs_valid = son_cross & father_ok & grandfather_ok & g["entry_date"].notna()
        sig_rows = g[gfs_valid]

        for _, row in sig_rows.iterrows():
            d = row["date"]
            n_r20 = nifty_ret20_map.get(d, 0.0)
            n_r60 = nifty_ret60_map.get(d, 0.0)
            stk_r20 = row["ret_20d"] if pd.notna(row["ret_20d"]) else 0.0
            stk_r60 = row["ret_60d"] if pd.notna(row["ret_60d"]) else 0.0

            all_signals.append({
                "security_id": sec_id,
                "symbol": sym,
                "company_name": comp,
                "sector": sector,
                "signal_date": d,
                "entry_date": row["entry_date"],
                "signal_close": row["close"],
                "entry_price": row["entry_open"],
                "prev_daily_rsi": row["prev_daily_rsi"],
                "daily_rsi": row["daily_rsi"],
                "daily_rsi_delta": row["daily_rsi"] - row["prev_daily_rsi"],
                "weekly_rsi": row["weekly_rsi_completed"],
                "monthly_rsi": row["monthly_rsi_completed"],
                "daily_ema21": row["daily_ema21"],
                "ret_20d": stk_r20,
                "ret_60d": stk_r60,
                "rs_20d": stk_r20 - n_r20,
                "rs_60d": stk_r60 - n_r60,
                "rel_vol_20d": row["rel_vol_20d"] if pd.notna(row["rel_vol_20d"]) else 1.0,
            })

    signals_df = pd.DataFrame(all_signals).sort_values(["signal_date", "symbol"]).reset_index(drop=True)

    # Standardize factors across all signals to build Composite Momentum Score
    factors = ["weekly_rsi", "monthly_rsi", "ret_20d", "ret_60d", "rs_60d", "rel_vol_20d"]
    z_scores = []
    for f in factors:
        col = signals_df[f].fillna(0.0)
        mean_val, std_val = col.mean(), col.std()
        if std_val > 1e-6:
            z = (col - mean_val) / std_val
        else:
            z = col * 0.0
        signals_df[f"{f}_z"] = z
        z_scores.append(f"{f}_z")
    signals_df["composite_momentum"] = signals_df[z_scores].mean(axis=1)

    print(f"Processed {total_stocks:,} stocks in {time.time()-t0:.2f}s.")
    print(f"Total GFS Signals: {len(signals_df):,} across {signals_df['symbol'].nunique():,} unique symbols.")

    return signals_df, processed_stocks

def compute_sector_daily_metrics(processed_stocks):
    """Compute daily sector momentum for sector rotation."""
    print("\nComputing sector daily momentum...")
    t0 = time.time()

    # Collect daily close by sector
    records = []
    for sym, df in processed_stocks.items():
        sec = df["sector"].iloc[0] if "sector" in df.columns else "Diversified / Other"
        for _, r in df[["date", "close"]].iterrows():
            records.append({
                "date": r["date"],
                "sector": sec,
                "close": r["close"]
            })

    sec_daily = pd.DataFrame(records)
    sec_agg = sec_daily.groupby(["date", "sector"])["close"].mean().reset_index()
    sec_piv = sec_agg.pivot(index="date", columns="sector", values="close").ffill()
    sec_ret20 = sec_piv.pct_change(20)

    sec_ranks_by_date = {}
    for d in sec_piv.index:
        if d in sec_ret20.index:
            r20 = sec_ret20.loc[d].dropna()
            if not r20.empty:
                ranks = r20.rank(ascending=False).to_dict()
                sec_ranks_by_date[d] = ranks

    print(f"Sector metrics precomputed in {time.time()-t0:.2f}s.")
    return sec_ranks_by_date

def run_simulation(
    signals_df,
    processed_stocks,
    nifty_regime_map,
    sec_ranks_by_date,
    capacity: int = 15,
    ranking_factor: str = "neutral",
    sector_filter: str = "none",
    sector_cap_pct: float = None,
    regime_schedule: str = "fixed",
    initial_stop_pct: float = -0.05,
    activation_pct: float = 0.05,
    exit_type: str = "trailing_ema21",
    cost_bps: float = 25.0,
    start_date: str = "2018-01-01",
    end_date: str = "2026-12-31"
):
    """Core portfolio backtesting engine."""
    STARTING_CAPITAL = 1_000_000.0
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)

    schedules = {
        "fixed": {"BULL": 1.0, "NEUTRAL": 1.0, "BEAR": 1.0},
        "sch1": {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30},
        "sch2": {"BULL": 1.0, "NEUTRAL": 0.80, "BEAR": 0.50},
        "sch3": {"BULL": 1.0, "NEUTRAL": 1.00, "BEAR": 0.50},
        "sch4": {"BULL": 1.0, "NEUTRAL": 0.60, "BEAR": 0.00},
    }
    exp_sch = schedules.get(regime_schedule, schedules["fixed"])

    sig_sub = signals_df[(signals_df["signal_date"] >= start_date) & (signals_df["signal_date"] <= end_date)]
    sig_by_date = {}
    for sig in sig_sub.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    all_dates = sorted(list(set(d for df in processed_stocks.values() for d in df["date"] if start_date <= d <= end_date)))

    def get_rank_val(cand):
        if ranking_factor == "neutral":
            return 0.0
        elif ranking_factor == "weekly_rsi":
            return -cand["weekly_rsi"]
        elif ranking_factor == "monthly_rsi":
            return -cand["monthly_rsi"]
        elif ranking_factor == "ret_20d":
            return -cand["ret_20d"]
        elif ranking_factor == "ret_60d":
            return -cand["ret_60d"]
        elif ranking_factor == "rs_20d":
            return -cand["rs_20d"]
        elif ranking_factor == "rs_60d":
            return -cand["rs_60d"]
        elif ranking_factor == "rel_vol_20d":
            return -cand["rel_vol_20d"]
        elif ranking_factor == "composite":
            return -cand["composite_momentum"]
        elif ranking_factor == "sector_momentum":
            s_ranks = sec_ranks_by_date.get(cand["signal_date"], {})
            return s_ranks.get(cand["sector"], 999)
        return 0.0

    cash = STARTING_CAPITAL
    open_positions = {}
    closed_trades = []
    daily_stats = []

    for d_idx, d in enumerate(all_dates):
        # 1. Check Exits at Day d Open
        to_close = []
        for sym, pos in open_positions.items():
            df_sym = processed_stocks[sym]
            row_d = df_sym[df_sym["date"] == d]
            if row_d.empty:
                continue
            r = row_d.iloc[0]
            op, hp, lp, cp = r["open"], r["high"], r["low"], r["close"]
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
                    "exit_reason": pos["pending_exit_reason"],
                    "max_favorable_pct": pos["max_high_pct"],
                    "max_adverse_pct": pos["max_low_pct"]
                })
                to_close.append(sym)
                continue

            if not pos["trailing_active"] and exit_type == "trailing_ema21":
                if op <= pos["stop_price"]:
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
                        "exit_reason": "STOP_LOSS_GAP_DOWN",
                        "max_favorable_pct": pos["max_high_pct"],
                        "max_adverse_pct": min(pos["max_low_pct"], (op - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0)
                    })
                    to_close.append(sym)
                    continue

        for sym in to_close:
            del open_positions[sym]

        # 2. Mark Portfolio Equity
        invested_equity = sum(pos["shares"] * pos["last_close"] for pos in open_positions.values())
        total_equity = cash + invested_equity

        regime = nifty_regime_map.get(d, "NEUTRAL")
        target_exp = exp_sch.get(regime, 1.0)
        max_allowed_equity = total_equity * target_exp
        max_allowed_positions = int(round(capacity * target_exp))

        # 3. Process New Entries
        prev_d = all_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        if day_signals and len(open_positions) < max_allowed_positions and invested_equity < max_allowed_equity:
            candidates = []
            sec_ranks = sec_ranks_by_date.get(prev_d, {})

            for sig in day_signals:
                s_sym = sig["symbol"]
                if s_sym in open_positions:
                    continue

                sec = sig["sector"]
                if sector_filter != "none":
                    s_rank = sec_ranks.get(sec, 999)
                    if sector_filter == "top2" and s_rank > 2:
                        continue
                    elif sector_filter == "top3" and s_rank > 3:
                        continue
                    elif sector_filter == "top5" and s_rank > 5:
                        continue

                if sector_cap_pct is not None:
                    current_sec_count = sum(1 for p in open_positions.values() if p["sector"] == sec)
                    max_sec_positions = max(1, int(round(capacity * sector_cap_pct)))
                    if current_sec_count >= max_sec_positions:
                        continue

                candidates.append(sig)

            if candidates:
                sorted_cands = sorted(candidates, key=get_rank_val)
                available_slots = max(0, max_allowed_positions - len(open_positions))
                alloc_per_slot = total_equity / capacity

                for cand in sorted_cands[:available_slots]:
                    s_sym = cand["symbol"]
                    raw_entry_p = cand["entry_price"]
                    sim_entry_p = raw_entry_p * cost_mult_entry
                    sec = cand["sector"]

                    if sector_cap_pct is not None:
                        current_sec_count = sum(1 for p in open_positions.values() if p["sector"] == sec)
                        max_sec_positions = max(1, int(round(capacity * sector_cap_pct)))
                        if current_sec_count >= max_sec_positions:
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
                            "stop_price": raw_entry_p * (1.0 + initial_stop_pct),
                            "act_price": raw_entry_p * (1.0 + activation_pct),
                            "trailing_active": False,
                            "holding_days": 0,
                            "max_high_pct": 0.0,
                            "max_low_pct": 0.0,
                            "pending_exit": False,
                            "pending_exit_reason": ""
                        }

        # 4. Intraday Checks & Trailing Exit Trigger
        to_close_intraday = []
        for sym, pos in open_positions.items():
            df_sym = processed_stocks[sym]
            row_d = df_sym[df_sym["date"] == d]
            if row_d.empty:
                continue
            r = row_d.iloc[0]
            op, hp, lp, cp = r["open"], r["high"], r["low"], r["close"]
            pos["last_close"] = cp

            high_pct = (hp - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0
            low_pct = (lp - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0
            pos["max_high_pct"] = max(pos["max_high_pct"], high_pct)
            pos["max_low_pct"] = min(pos["max_low_pct"], low_pct)

            if not pos["trailing_active"] and exit_type == "trailing_ema21":
                if lp <= pos["stop_price"]:
                    exit_price = pos["stop_price"] * cost_mult_exit
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
                        "raw_exit_price": pos["stop_price"],
                        "return_pct": ret_pct,
                        "holding_days": pos["holding_days"],
                        "exit_reason": "STOP_LOSS_INTRADAY",
                        "max_favorable_pct": pos["max_high_pct"],
                        "max_adverse_pct": pos["max_low_pct"]
                    })
                    to_close_intraday.append(sym)
                    continue

                if hp >= pos["act_price"]:
                    pos["trailing_active"] = True

            if exit_type == "trailing_ema21":
                if pos["trailing_active"]:
                    ema21 = r["daily_ema21"]
                    if cp < ema21:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = "DAILY_CLOSE_BELOW_EMA21"
            elif exit_type == "fixed_20d":
                if pos["holding_days"] >= 20:
                    pos["pending_exit"] = True
                    pos["pending_exit_reason"] = "FIXED_20D"
            elif exit_type == "fixed_40d":
                if pos["holding_days"] >= 40:
                    pos["pending_exit"] = True
                    pos["pending_exit_reason"] = "FIXED_40D"
            elif exit_type == "fixed_60d":
                if pos["holding_days"] >= 60:
                    pos["pending_exit"] = True
                    pos["pending_exit_reason"] = "FIXED_60D"

        for sym in to_close_intraday:
            del open_positions[sym]

        # 5. Record Daily State
        inv_val = sum(pos["shares"] * pos["last_close"] for pos in open_positions.values())
        tot_val = cash + inv_val
        eq_exp = (inv_val / tot_val * 100.0) if tot_val > 0 else 0.0
        daily_stats.append({
            "date": d,
            "equity": tot_val,
            "cash": cash,
            "invested": inv_val,
            "exposure_pct": eq_exp,
            "num_positions": len(open_positions),
            "regime": regime
        })

    if open_positions and len(all_dates) > 0:
        final_d = all_dates[-1]
        for sym, pos in open_positions.items():
            final_p = pos["last_close"] * cost_mult_exit
            ret_pct = (final_p - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
            closed_trades.append({
                "symbol": sym,
                "sector": pos["sector"],
                "entry_date": pos["entry_date"],
                "exit_date": final_d,
                "sim_entry_price": pos["sim_entry_price"],
                "raw_entry_price": pos["raw_entry_price"],
                "sim_exit_price": final_p,
                "raw_exit_price": pos["last_close"],
                "return_pct": ret_pct,
                "holding_days": pos["holding_days"],
                "exit_reason": "END_OF_DATA",
                "max_favorable_pct": pos["max_high_pct"],
                "max_adverse_pct": pos["max_low_pct"]
            })

    daily_df_res = pd.DataFrame(daily_stats)
    trades_df_res = pd.DataFrame(closed_trades)

    summary = compute_performance_metrics(daily_df_res, trades_df_res, STARTING_CAPITAL)
    return summary, daily_df_res, trades_df_res

def compute_performance_metrics(daily_df, trades_df, starting_capital=1_000_000.0):
    """Compute standard quantitative performance metrics."""
    if daily_df.empty:
        return {}

    eq = daily_df["equity"]
    initial_val = starting_capital
    ending_val = eq.iloc[-1]
    total_ret_pct = (ending_val - initial_val) / initial_val * 100.0

    n_days = len(daily_df)
    n_years = max(n_days / 252.0, 0.1)
    cagr = ((ending_val / initial_val) ** (1.0 / n_years) - 1.0) * 100.0

    peak = eq.cummax()
    dd = (eq - peak) / peak * 100.0
    max_dd = dd.min()
    avg_dd = dd[dd < 0].mean() if (dd < 0).any() else 0.0

    dd_binary = (dd < 0).astype(int)
    dd_runs = dd_binary.groupby((dd_binary != dd_binary.shift()).cumsum()).cumsum()
    max_dd_duration = dd_runs.max() if not dd_runs.empty else 0

    daily_ret = eq.pct_change().dropna()
    vol_ann = daily_ret.std() * np.sqrt(252) * 100.0 if len(daily_ret) > 1 else 0.0
    sharpe = (cagr - 6.0) / vol_ann if vol_ann > 1e-4 else 0.0
    calmar = abs(cagr / max_dd) if abs(max_dd) > 1e-4 else 0.0
    worst_day_pct = daily_ret.min() * 100.0 if not daily_ret.empty else 0.0

    n_trades = len(trades_df)
    if n_trades > 0:
        win_trades = trades_df[trades_df["return_pct"] > 0]
        loss_trades = trades_df[trades_df["return_pct"] <= 0]
        win_rate = len(win_trades) / n_trades * 100.0
        avg_ret = trades_df["return_pct"].mean()
        med_ret = trades_df["return_pct"].median()

        tot_gains = win_trades["return_pct"].sum()
        tot_losses = abs(loss_trades["return_pct"].sum())
        profit_factor = (tot_gains / tot_losses) if tot_losses > 1e-4 else 99.0

        avg_win = win_trades["return_pct"].mean() if not win_trades.empty else 0.0
        avg_loss = loss_trades["return_pct"].mean() if not loss_trades.empty else 0.0
        win_loss_ratio = abs(avg_win / avg_loss) if abs(avg_loss) > 1e-4 else 99.0
        expectancy = (win_rate / 100.0 * avg_win) + ((1.0 - win_rate / 100.0) * avg_loss)
        avg_hold = trades_df["holding_days"].mean()
        turnover = (n_trades * 2.0) / n_years
    else:
        win_rate = avg_ret = med_ret = profit_factor = avg_win = avg_loss = win_loss_ratio = expectancy = avg_hold = turnover = 0.0

    avg_exp = daily_df["exposure_pct"].mean()
    avg_cash = 100.0 - avg_exp
    max_pos = daily_df["num_positions"].max()
    avg_pos = daily_df["num_positions"].mean()

    return {
        "starting_capital": starting_capital,
        "ending_capital": ending_val,
        "total_return_pct": total_ret_pct,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "avg_drawdown": avg_dd,
        "max_dd_duration": max_dd_duration,
        "volatility_ann": vol_ann,
        "sharpe": sharpe,
        "calmar": calmar,
        "worst_day_pct": worst_day_pct,
        "num_trades": n_trades,
        "win_rate": win_rate,
        "avg_trade_ret": avg_ret,
        "median_trade_ret": med_ret,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "expectancy": expectancy,
        "avg_holding_days": avg_hold,
        "annual_turnover": turnover,
        "avg_exposure_pct": avg_exp,
        "avg_cash_pct": avg_cash,
        "max_positions": max_pos,
        "avg_positions": avg_pos
    }

def run_all_experiments():
    """Execute all systematic research experiments."""
    daily_df, nifty_df, sec_info, sector_map, mcap_map, nifty_regime_map, nifty_ret20_map, nifty_ret60_map = load_universe_and_enrich_data()
    signals_df, processed_stocks = process_stocks_and_signals(daily_df, sec_info, sector_map, nifty_ret20_map, nifty_ret60_map)
    sec_ranks_by_date = compute_sector_daily_metrics(processed_stocks)

    signals_df.to_csv(REPORTS_DIR / "gfs_adaptive_signals_enriched.csv", index=False)
    print(f"Saved enriched signals to {REPORTS_DIR / 'gfs_adaptive_signals_enriched.csv'}")

    # =========================================================================
    # EXPERIMENT 1: BASELINE REPRODUCTION & BENCHMARKS
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 1: BASELINE REPRODUCTION & BENCHMARKS")
    print("=" * 80)

    nifty_p0 = nifty_df["close"].iloc[0]
    nifty_p1 = nifty_df["close"].iloc[-1]
    nifty_nyears = max(len(nifty_df) / 252.0, 0.1)
    nifty_cagr = ((nifty_p1 / nifty_p0) ** (1.0 / nifty_nyears) - 1.0) * 100.0
    nifty_peak = nifty_df["close"].cummax()
    nifty_dd = (nifty_df["close"] - nifty_peak) / nifty_peak * 100.0
    nifty_maxdd = nifty_dd.min()
    print(f"Benchmark 1 (NIFTY 50 B&H): CAGR = {nifty_cagr:.2f}%, MaxDD = {nifty_maxdd:.2f}%")

    b2_sum, b2_eq, b2_tr = run_simulation(
        signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
        capacity=15, ranking_factor="neutral", exit_type="fixed_20d", cost_bps=25.0
    )
    print(f"Benchmark 2 (GFS Baseline Fixed 20D): CAGR = {b2_sum['cagr']:.2f}%, MaxDD = {b2_sum['max_drawdown']:.2f}%, PF = {b2_sum['profit_factor']:.2f}, WinRate = {b2_sum['win_rate']:.1f}%")

    b3_sum, b3_eq, b3_tr = run_simulation(
        signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
        capacity=15, ranking_factor="neutral", exit_type="trailing_ema21",
        initial_stop_pct=-0.05, activation_pct=0.05, cost_bps=25.0
    )
    print(f"Benchmark 3 (GFS -5% -> EMA21 Trailing): CAGR = {b3_sum['cagr']:.2f}%, MaxDD = {b3_sum['max_drawdown']:.2f}%, PF = {b3_sum['profit_factor']:.2f}, WinRate = {b3_sum['win_rate']:.1f}%")

    baseline_rep = pd.DataFrame([
        {"Model": "NIFTY 50 B&H", "CAGR": nifty_cagr, "MaxDD": nifty_maxdd, "PF": np.nan, "WinRate": np.nan, "Trades": 0, "AvgTrade": np.nan, "Exposure": 100.0},
        {"Model": "GFS Baseline (Fixed 20D, 15 slots)", "CAGR": b2_sum["cagr"], "MaxDD": b2_sum["max_drawdown"], "PF": b2_sum["profit_factor"], "WinRate": b2_sum["win_rate"], "Trades": b2_sum["num_trades"], "AvgTrade": b2_sum["avg_trade_ret"], "Exposure": b2_sum["avg_exposure_pct"]},
        {"Model": "GFS -5% -> EMA21 Trailing (15 slots)", "CAGR": b3_sum["cagr"], "MaxDD": b3_sum["max_drawdown"], "PF": b3_sum["profit_factor"], "WinRate": b3_sum["win_rate"], "Trades": b3_sum["num_trades"], "AvgTrade": b3_sum["avg_trade_ret"], "Exposure": b3_sum["avg_exposure_pct"]}
    ])
    baseline_rep.to_csv(REPORTS_DIR / "gfs_adaptive_baseline_reproduction.csv", index=False)

    # =========================================================================
    # EXPERIMENT 2: PORTFOLIO CAPACITY SWEEP
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 2: PORTFOLIO CAPACITY SWEEP")
    print("=" * 80)
    capacity_rows = []
    for cap in [5, 10, 15, 20, 30]:
        s, _, _ = run_simulation(
            signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
            capacity=cap, ranking_factor="neutral", exit_type="trailing_ema21", cost_bps=25.0
        )
        capacity_rows.append({
            "Capacity": cap,
            "Slot_Allocation_Pct": 100.0 / cap,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "NumTrades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "AvgExposure": s["avg_exposure_pct"],
            "MaxPositions": s["max_positions"]
        })
        print(f"Capacity {cap:2d} slots: CAGR = {s['cagr']:6.2f}%, MaxDD = {s['max_drawdown']:6.2f}%, PF = {s['profit_factor']:5.2f}, WinRate = {s['win_rate']:5.1f}%")
    cap_df = pd.DataFrame(capacity_rows)
    cap_df.to_csv(REPORTS_DIR / "gfs_adaptive_portfolio_capacity.csv", index=False)

    # =========================================================================
    # EXPERIMENT 3: MOMENTUM RANKING METHODS
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 3: STOCK SELECTION & MOMENTUM RANKING METHODS")
    print("=" * 80)
    factors = [
        ("Neutral (No factor)", "neutral"),
        ("Weekly RSI", "weekly_rsi"),
        ("Monthly RSI", "monthly_rsi"),
        ("20-Day Momentum", "ret_20d"),
        ("60-Day Momentum", "ret_60d"),
        ("Relative Strength 20D vs NIFTY", "rs_20d"),
        ("Relative Strength 60D vs NIFTY", "rs_60d"),
        ("Relative Volume 20D", "rel_vol_20d"),
        ("Composite Momentum Score", "composite")
    ]
    momentum_rows = []
    for label, factor_key in factors:
        s, _, _ = run_simulation(
            signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
            capacity=15, ranking_factor=factor_key, exit_type="trailing_ema21", cost_bps=25.0
        )
        momentum_rows.append({
            "Ranking_Method": label,
            "Factor_Key": factor_key,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "NumTrades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "AvgExposure": s["avg_exposure_pct"]
        })
        print(f"{label:35s}: CAGR = {s['cagr']:6.2f}%, MaxDD = {s['max_drawdown']:6.2f}%, PF = {s['profit_factor']:5.2f}, WinRate = {s['win_rate']:5.1f}%")
    mom_df = pd.DataFrame(momentum_rows)
    mom_df.to_csv(REPORTS_DIR / "gfs_adaptive_momentum_ranking.csv", index=False)

    # =========================================================================
    # EXPERIMENT 4: MARKET REGIME & DYNAMIC CASH ALLOCATION
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 4: MARKET REGIME & DYNAMIC EXPOSURE SCHEDULES")
    print("=" * 80)
    schedules = [
        ("Fixed (100% all regimes)", "fixed"),
        ("Schedule 1 (Bull 100%, Neutral 70%, Bear 30%)", "sch1"),
        ("Schedule 2 (Bull 100%, Neutral 80%, Bear 50%)", "sch2"),
        ("Schedule 3 (Bull 100%, Neutral 100%, Bear 50%)", "sch3"),
        ("Schedule 4 (Bull 100%, Neutral 60%, Bear 0%)", "sch4"),
    ]
    regime_rows = []
    for label, sch_key in schedules:
        s, _, _ = run_simulation(
            signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
            capacity=15, ranking_factor="ret_20d", regime_schedule=sch_key,
            exit_type="trailing_ema21", cost_bps=25.0
        )
        regime_rows.append({
            "Exposure_Schedule": label,
            "Schedule_Key": sch_key,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "NumTrades": s["num_trades"],
            "AvgExposure": s["avg_exposure_pct"],
            "AvgCash": s["avg_cash_pct"],
            "Calmar": s["calmar"]
        })
        print(f"{label:45s}: CAGR = {s['cagr']:6.2f}%, MaxDD = {s['max_drawdown']:6.2f}%, Exposure = {s['avg_exposure_pct']:5.1f}%, PF = {s['profit_factor']:5.2f}")
    reg_df = pd.DataFrame(regime_rows)
    reg_df.to_csv(REPORTS_DIR / "gfs_adaptive_exposure_schedules.csv", index=False)

    # =========================================================================
    # EXPERIMENT 5: SECTOR ROTATION & CONCENTRATION CONTROL
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 5: SECTOR ROTATION & CONCENTRATION CONTROL")
    print("=" * 80)
    sector_tests = [
        ("No Sector Preference", "none", None),
        ("Sector Momentum Ranking", "none", None),
        ("Top 2 Sectors Only", "top2", None),
        ("Top 3 Sectors Only", "top3", None),
        ("Top 5 Sectors Only", "top5", None),
        ("Sector Cap 20%", "none", 0.20),
        ("Sector Cap 25%", "none", 0.25),
        ("Sector Cap 33%", "none", 0.33),
        ("Top 3 Sectors + 25% Cap", "top3", 0.25)
    ]
    sec_rows = []
    for label, sec_filt, sec_cap in sector_tests:
        r_fac = "sector_momentum" if "Momentum Ranking" in label else "ret_20d"
        s, _, _ = run_simulation(
            signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
            capacity=15, ranking_factor=r_fac, sector_filter=sec_filt, sector_cap_pct=sec_cap,
            exit_type="trailing_ema21", cost_bps=25.0
        )
        sec_rows.append({
            "Test_Label": label,
            "Sector_Filter": sec_filt,
            "Sector_Cap": sec_cap if sec_cap else "None",
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "NumTrades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "AvgExposure": s["avg_exposure_pct"]
        })
        print(f"{label:30s}: CAGR = {s['cagr']:6.2f}%, MaxDD = {s['max_drawdown']:6.2f}%, PF = {s['profit_factor']:5.2f}, Trades = {s['num_trades']}")
    sec_df = pd.DataFrame(sec_rows)
    sec_df.to_csv(REPORTS_DIR / "gfs_adaptive_sector_rotation.csv", index=False)

    # =========================================================================
    # EXPERIMENT 6: EXIT STRATEGY & ACTIVATION THRESHOLD COMPARISON
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 6: EXIT STRATEGY & ACTIVATION THRESHOLDS")
    print("=" * 80)
    exit_tests = [
        ("Fixed 20-Day Exit", "fixed_20d", 0.0),
        ("Fixed 40-Day Exit", "fixed_40d", 0.0),
        ("Fixed 60-Day Exit", "fixed_60d", 0.0),
        ("Trailing EMA21 (Activation +3%)", "trailing_ema21", 0.03),
        ("Trailing EMA21 (Activation +5%)", "trailing_ema21", 0.05),
        ("Trailing EMA21 (Activation +7%)", "trailing_ema21", 0.07),
        ("Trailing EMA21 (Activation +10%)", "trailing_ema21", 0.10)
    ]
    exit_rows = []
    for label, e_type, act in exit_tests:
        s, _, _ = run_simulation(
            signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
            capacity=15, ranking_factor="ret_20d", exit_type=e_type, activation_pct=act, cost_bps=25.0
        )
        exit_rows.append({
            "Exit_Strategy": label,
            "Exit_Type": e_type,
            "Activation_Threshold": f"+{int(act*100)}%" if act > 0 else "N/A",
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "NumTrades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "AvgHoldingDays": s["avg_holding_days"]
        })
        print(f"{label:35s}: CAGR = {s['cagr']:6.2f}%, MaxDD = {s['max_drawdown']:6.2f}%, PF = {s['profit_factor']:5.2f}, Hold = {s['avg_holding_days']:4.1f}d")
    exit_df = pd.DataFrame(exit_rows)
    exit_df.to_csv(REPORTS_DIR / "gfs_adaptive_exit_comparison.csv", index=False)

    # =========================================================================
    # EXPERIMENT 7: PROGRESSIVE MODELS (MODEL 0 to MODEL 4)
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 7: PROGRESSIVE MODEL COMPARISON")
    print("=" * 80)

    m0_sum, m0_eq, m0_tr = run_simulation(
        signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
        capacity=15, ranking_factor="neutral", regime_schedule="fixed", sector_filter="none",
        sector_cap_pct=None, exit_type="trailing_ema21", activation_pct=0.05, cost_bps=25.0
    )

    m1_sum, m1_eq, m1_tr = run_simulation(
        signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
        capacity=15, ranking_factor="ret_20d", regime_schedule="fixed", sector_filter="none",
        sector_cap_pct=None, exit_type="trailing_ema21", activation_pct=0.05, cost_bps=25.0
    )

    m2_sum, m2_eq, m2_tr = run_simulation(
        signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
        capacity=15, ranking_factor="ret_20d", regime_schedule="fixed", sector_filter="none",
        sector_cap_pct=0.25, exit_type="trailing_ema21", activation_pct=0.05, cost_bps=25.0
    )

    m3_sum, m3_eq, m3_tr = run_simulation(
        signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
        capacity=15, ranking_factor="ret_20d", regime_schedule="sch1", sector_filter="none",
        sector_cap_pct=None, exit_type="trailing_ema21", activation_pct=0.05, cost_bps=25.0
    )

    m4_sum, m4_eq, m4_tr = run_simulation(
        signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
        capacity=15, ranking_factor="ret_20d", regime_schedule="sch1", sector_filter="none",
        sector_cap_pct=0.25, exit_type="trailing_ema21", activation_pct=0.05, cost_bps=25.0
    )

    prog_models = pd.DataFrame([
        {"Model": "Model 0: Baseline GFS (-5% -> EMA21)", **m0_sum},
        {"Model": "Model 1: GFS + Momentum Ranking", **m1_sum},
        {"Model": "Model 2: GFS + Momentum + Sector Cap 25%", **m2_sum},
        {"Model": "Model 3: GFS + Momentum + Regime (Sch 1)", **m3_sum},
        {"Model": "Model 4: Full Adaptive (Mom+Sec+Reg)", **m4_sum}
    ])
    prog_models.to_csv(REPORTS_DIR / "gfs_adaptive_models_progressive.csv", index=False)
    for idx, r in prog_models.iterrows():
        print(f"{r['Model']:45s}: CAGR = {r['cagr']:6.2f}%, MaxDD = {r['max_drawdown']:6.2f}%, PF = {r['profit_factor']:5.2f}, WinRate = {r['win_rate']:5.1f}%")

    m0_tr["model"] = "Model 0 Baseline"
    m4_tr["model"] = "Model 4 Full Adaptive"
    pd.concat([m0_tr, m4_tr], ignore_index=True).to_csv(REPORTS_DIR / "gfs_adaptive_trades.csv", index=False)

    # =========================================================================
    # EXPERIMENT 8: ABLATION STUDY (7 COMBINATIONS)
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 8: FULL ABLATION STUDY (7 COMBINATIONS)")
    print("=" * 80)
    ablation_defs = [
        ("1. GFS Baseline", "neutral", "fixed", None),
        ("2. GFS + Momentum", "ret_20d", "fixed", None),
        ("3. GFS + Market Regime", "neutral", "sch1", None),
        ("4. GFS + Sector Rotation", "neutral", "fixed", 0.25),
        ("5. GFS + Momentum + Market Regime", "ret_20d", "sch1", None),
        ("6. GFS + Momentum + Sector Rotation", "ret_20d", "fixed", 0.25),
        ("7. GFS + Momentum + Sector + Regime (Full Adaptive)", "ret_20d", "sch1", 0.25)
    ]
    ablation_rows = []
    for label, rank_f, reg_sch, s_cap in ablation_defs:
        s, _, _ = run_simulation(
            signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
            capacity=15, ranking_factor=rank_f, regime_schedule=reg_sch, sector_cap_pct=s_cap,
            exit_type="trailing_ema21", activation_pct=0.05, cost_bps=25.0
        )
        ablation_rows.append({
            "Combination": label,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "AvgTrade": s["avg_trade_ret"],
            "AnnualTurnover": s["annual_turnover"],
            "AvgExposure": s["avg_exposure_pct"],
            "Sharpe": s["sharpe"],
            "Calmar": s["calmar"],
            "NumTrades": s["num_trades"]
        })
        print(f"{label:50s}: CAGR = {s['cagr']:6.2f}%, MaxDD = {s['max_drawdown']:6.2f}%, PF = {s['profit_factor']:5.2f}")
    abl_df = pd.DataFrame(ablation_rows)
    abl_df.to_csv(REPORTS_DIR / "gfs_adaptive_ablation_matrix.csv", index=False)

    # =========================================================================
    # EXPERIMENT 9: TRANSACTION COST SENSITIVITY
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 9: TRANSACTION COST SENSITIVITY")
    print("=" * 80)
    cost_rows = []
    for cost in [0.0, 25.0, 50.0, 100.0, 150.0]:
        for label, rank_f, reg_sch, s_cap in [
            ("GFS Baseline", "neutral", "fixed", None),
            ("Full Adaptive Model", "ret_20d", "sch1", 0.25)
        ]:
            s, _, _ = run_simulation(
                signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
                capacity=15, ranking_factor=rank_f, regime_schedule=reg_sch, sector_cap_pct=s_cap,
                exit_type="trailing_ema21", activation_pct=0.05, cost_bps=cost
            )
            cost_rows.append({
                "Strategy": label,
                "Cost_Bps": cost,
                "CAGR": s["cagr"],
                "MaxDD": s["max_drawdown"],
                "ProfitFactor": s["profit_factor"],
                "WinRate": s["win_rate"],
                "AvgTrade": s["avg_trade_ret"],
                "EndingCapital": s["ending_capital"]
            })
            print(f"{label:20s} @ {cost:3.0f} bps: CAGR = {s['cagr']:6.2f}%, MaxDD = {s['max_drawdown']:6.2f}%, PF = {s['profit_factor']:5.2f}, EndCap = Rs.{s['ending_capital']:,.0f}")
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(REPORTS_DIR / "gfs_adaptive_cost_sensitivity.csv", index=False)

    # =========================================================================
    # EXPERIMENT 10: MULTIBAGGER RETENTION ANALYSIS
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 10: MULTIBAGGER RETENTION ANALYSIS")
    print("=" * 80)
    multi_rows = []
    for label, e_type, act in [
        ("Fixed 20-Day Exit", "fixed_20d", 0.0),
        ("Fixed 40-Day Exit", "fixed_40d", 0.0),
        ("Fixed 60-Day Exit", "fixed_60d", 0.0),
        ("GFS -5% -> EMA21 Trailing (+5% Act)", "trailing_ema21", 0.05)
    ]:
        _, _, tr = run_simulation(
            signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
            capacity=15, ranking_factor="ret_20d", exit_type=e_type, activation_pct=act, cost_bps=25.0
        )
        total_tr = len(tr)
        w25 = (tr["return_pct"] >= 25.0).sum()
        w50 = (tr["return_pct"] >= 50.0).sum()
        w100 = (tr["return_pct"] >= 100.0).sum()
        w200 = (tr["return_pct"] >= 200.0).sum()
        w300 = (tr["return_pct"] >= 300.0).sum()
        max_win = tr["return_pct"].max() if not tr.empty else 0.0

        multi_rows.append({
            "Strategy": label,
            "TotalTrades": total_tr,
            "Gain_GT_25pct": w25,
            "Pct_GT_25pct": (w25 / total_tr * 100) if total_tr > 0 else 0,
            "Gain_GT_50pct": w50,
            "Pct_GT_50pct": (w50 / total_tr * 100) if total_tr > 0 else 0,
            "Gain_GT_100pct": w100,
            "Pct_GT_100pct": (w100 / total_tr * 100) if total_tr > 0 else 0,
            "Gain_GT_200pct": w200,
            "Pct_GT_200pct": (w200 / total_tr * 100) if total_tr > 0 else 0,
            "Gain_GT_300pct": w300,
            "Pct_GT_300pct": (w300 / total_tr * 100) if total_tr > 0 else 0,
            "MaxWinnerPct": max_win
        })
        print(f"{label:35s}: >25%={w25} ({w25/total_tr*100:.1f}%), >50%={w50} ({w50/total_tr*100:.1f}%), >100%={w100}, Max={max_win:.1f}%")
    multi_df = pd.DataFrame(multi_rows)
    multi_df.to_csv(REPORTS_DIR / "gfs_adaptive_multibagger_analysis.csv", index=False)

    # =========================================================================
    # EXPERIMENT 11: CHRONOLOGICAL WALK-FORWARD VALIDATION
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 11: CHRONOLOGICAL EXPANDING WALK-FORWARD VALIDATION")
    print("=" * 80)
    folds = [
        ("Fold 1", "2018-01-01", "2020-12-31", "2021-01-01", "2021-12-31"),
        ("Fold 2", "2018-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
        ("Fold 3", "2018-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
        ("Fold 4", "2018-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
        ("Fold 5", "2018-01-01", "2024-12-31", "2025-01-01", "2025-12-31"),
        ("Fold 6", "2018-01-01", "2025-12-31", "2026-01-01", "2026-08-24"),
    ]
    wf_rows = []
    for f_name, train_s, train_e, test_s, test_e in folds:
        for mod_name, r_fac, r_sch, s_cap in [
            ("Baseline GFS", "neutral", "fixed", None),
            ("Full Adaptive", "ret_20d", "sch1", 0.25)
        ]:
            s_train, _, _ = run_simulation(
                signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
                capacity=15, ranking_factor=r_fac, regime_schedule=r_sch, sector_cap_pct=s_cap,
                exit_type="trailing_ema21", activation_pct=0.05, cost_bps=25.0,
                start_date=train_s, end_date=train_e
            )
            s_test, _, _ = run_simulation(
                signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
                capacity=15, ranking_factor=r_fac, regime_schedule=r_sch, sector_cap_pct=s_cap,
                exit_type="trailing_ema21", activation_pct=0.05, cost_bps=25.0,
                start_date=test_s, end_date=test_e
            )
            wf_rows.append({
                "Fold": f_name,
                "Model": mod_name,
                "Train_Period": f"{train_s[:4]}-{train_e[:4]}",
                "Test_Period": f"{test_s[:4]}-{test_e[:4]}",
                "Train_CAGR": s_train["cagr"],
                "Train_MaxDD": s_train["max_drawdown"],
                "Train_PF": s_train["profit_factor"],
                "Test_Return": s_test["total_return_pct"],
                "Test_MaxDD": s_test["max_drawdown"],
                "Test_PF": s_test["profit_factor"],
                "Test_WinRate": s_test["win_rate"],
                "Test_Trades": s_test["num_trades"]
            })
            print(f"{f_name} [{mod_name:14s}] -> Train CAGR: {s_train['cagr']:5.2f}% | Test Ret: {s_test['total_return_pct']:5.2f}%, Test MaxDD: {s_test['max_drawdown']:5.2f}%, Test PF: {s_test['profit_factor']:4.2f}")
    wf_df = pd.DataFrame(wf_rows)
    wf_df.to_csv(REPORTS_DIR / "gfs_adaptive_walk_forward.csv", index=False)

    # =========================================================================
    # EXPERIMENT 12: MONTE CARLO SIMULATION (5,000 RUNS)
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 12: MONTE CARLO SIMULATION (5,000 RUNS)")
    print("=" * 80)
    np.random.seed(42)
    mc_results = []
    for mod_name, tr_df in [("Baseline GFS", m0_tr), ("Full Adaptive Model", m4_tr)]:
        trade_returns = tr_df["return_pct"].values / 100.0
        n_tr = len(trade_returns)
        if n_tr < 10:
            continue

        cagrs = []
        max_dds = []
        end_caps = []
        max_loss_streaks = []
        worst_10_trades = []
        worst_20_trades = []

        holding_days_avg = tr_df["holding_days"].mean()
        sim_years = (n_tr * holding_days_avg) / (15.0 * 252.0)
        sim_years = max(sim_years, 1.0)

        for _ in range(5000):
            sampled_rets = np.random.choice(trade_returns, size=n_tr, replace=True)
            equity_mult = 1.0
            peak_mult = 1.0
            mdd = 0.0
            curr_streak = 0
            max_streak = 0

            for r in sampled_rets:
                trade_pnl = equity_mult * (1.0 / 15.0) * r
                equity_mult += trade_pnl
                equity_mult = max(equity_mult, 0.001)
                peak_mult = max(peak_mult, equity_mult)
                dd = (equity_mult - peak_mult) / peak_mult * 100.0
                mdd = min(mdd, dd)

                if r <= 0:
                    curr_streak += 1
                    max_streak = max(max_streak, curr_streak)
                else:
                    curr_streak = 0

            final_cap = 1_000_000.0 * equity_mult
            sim_cagr = ((final_cap / 1_000_000.0) ** (1.0 / sim_years) - 1.0) * 100.0 if final_cap > 0 else -100.0

            end_caps.append(final_cap)
            cagrs.append(sim_cagr)
            max_dds.append(mdd)
            max_loss_streaks.append(max_streak)

            if n_tr >= 20:
                roll_10 = pd.Series(sampled_rets).rolling(10).sum().min() * 100.0
                roll_20 = pd.Series(sampled_rets).rolling(20).sum().min() * 100.0
                worst_10_trades.append(roll_10)
                worst_20_trades.append(roll_20)

        mc_results.append({
            "Model": mod_name,
            "Simulations": 5000,
            "CAGR_Mean": np.mean(cagrs),
            "CAGR_Median": np.median(cagrs),
            "CAGR_5th_Pct": np.percentile(cagrs, 5),
            "CAGR_25th_Pct": np.percentile(cagrs, 25),
            "CAGR_75th_Pct": np.percentile(cagrs, 75),
            "CAGR_95th_Pct": np.percentile(cagrs, 95),
            "MaxDD_Mean": np.mean(max_dds),
            "MaxDD_Median": np.median(max_dds),
            "MaxDD_95th_Pct": np.percentile(max_dds, 5),
            "MaxLossStreak_Max": np.max(max_loss_streaks),
            "MaxLossStreak_Median": np.median(max_loss_streaks),
            "Worst_10_Trade_Sum": np.median(worst_10_trades) if worst_10_trades else 0,
            "Worst_20_Trade_Sum": np.median(worst_20_trades) if worst_20_trades else 0,
            "EndingCapital_Median": np.median(end_caps)
        })
        print(f"Monte Carlo {mod_name:20s}: Median CAGR = {np.median(cagrs):5.2f}%, 95% Worst DD = {np.percentile(max_dds, 5):5.2f}%, Max Loss Streak = {np.max(max_loss_streaks)}")

    mc_df = pd.DataFrame(mc_results)
    mc_df.to_csv(REPORTS_DIR / "gfs_adaptive_monte_carlo.csv", index=False)

    # =========================================================================
    # EXPERIMENT 13: COMPREHENSIVE FINAL COMPARISON TABLE (SECTION 27)
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 13: COMPREHENSIVE FINAL COMPARISON TABLE (SECTION 27)")
    print("=" * 80)
    comp_configs = [
        ("GFS Baseline", "neutral", "fixed", None),
        ("GFS + Momentum", "ret_20d", "fixed", None),
        ("GFS + Regime", "neutral", "sch1", None),
        ("GFS + Sector", "neutral", "fixed", 0.25),
        ("GFS + Momentum + Regime", "ret_20d", "sch1", None),
        ("GFS + Momentum + Sector", "ret_20d", "fixed", 0.25),
        ("GFS + Momentum + Sector + Regime", "ret_20d", "sch1", 0.25)
    ]
    final_table_rows = []
    for strat_label, rank_f, reg_sch, s_cap in comp_configs:
        for cost in [0.0, 25.0, 50.0, 100.0]:
            s, _, _ = run_simulation(
                signals_df, processed_stocks, nifty_regime_map, sec_ranks_by_date,
                capacity=15, ranking_factor=rank_f, regime_schedule=reg_sch, sector_cap_pct=s_cap,
                exit_type="trailing_ema21", activation_pct=0.05, cost_bps=cost
            )
            final_table_rows.append({
                "Strategy": strat_label,
                "Cost_Level": "Gross (0 bps)" if cost == 0 else f"{int(cost)} bps",
                "CAGR": s["cagr"],
                "MaxDD": s["max_drawdown"],
                "ProfitFactor": s["profit_factor"],
                "WinRate": s["win_rate"],
                "AvgTrade": s["avg_trade_ret"],
                "AvgExposure": s["avg_exposure_pct"],
                "Turnover": s["annual_turnover"],
                "NumTrades": s["num_trades"]
            })
    final_comp_df = pd.DataFrame(final_table_rows)
    final_comp_df.to_csv(REPORTS_DIR / "gfs_adaptive_final_comparison_table.csv", index=False)
    print("Exported final comparison table.")

    # =========================================================================
    # EXPERIMENT 14: SECTOR PERFORMANCE BREAKDOWN (SECTION 21)
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 14: SECTOR PERFORMANCE BREAKDOWN (SECTION 21)")
    print("=" * 80)
    sig_sec_cnt = signals_df["sector"].value_counts().to_dict()
    sec_breakdown_rows = []
    for sec, tr_s in m4_tr.groupby("sector"):
        n_tr = len(tr_s)
        w_tr = tr_s[tr_s["return_pct"] > 0]
        l_tr = tr_s[tr_s["return_pct"] <= 0]
        w_rate = len(w_tr) / n_tr * 100.0 if n_tr > 0 else 0.0
        avg_ret = tr_s["return_pct"].mean()
        med_ret = tr_s["return_pct"].median()
        w_sum = w_tr["return_pct"].sum()
        l_sum = abs(l_tr["return_pct"].sum())
        pf = (w_sum / l_sum) if l_sum > 1e-4 else 99.0
        tot_contrib = tr_s["return_pct"].sum()

        sec_breakdown_rows.append({
            "Sector": sec,
            "Total_Signals": sig_sec_cnt.get(sec, 0),
            "Trades_Taken": n_tr,
            "WinRate": w_rate,
            "AvgReturn": avg_ret,
            "MedianReturn": med_ret,
            "ProfitFactor": pf,
            "Cumulative_Return_Contribution": tot_contrib
        })
    sec_bk_df = pd.DataFrame(sec_breakdown_rows).sort_values("Cumulative_Return_Contribution", ascending=False)
    sec_bk_df.to_csv(REPORTS_DIR / "gfs_adaptive_sector_breakdown.csv", index=False)
    print("Exported sector performance breakdown.")

    # =========================================================================
    # EXPERIMENT 15: MARKET REGIME PERFORMANCE BREAKDOWN (SECTION 20)
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 15: MARKET REGIME PERFORMANCE BREAKDOWN (SECTION 20)")
    print("=" * 80)
    m4_tr["entry_regime"] = m4_tr["entry_date"].map(nifty_regime_map).fillna("NEUTRAL")
    regime_breakdown_rows = []
    for reg, tr_r in m4_tr.groupby("entry_regime"):
        n_tr = len(tr_r)
        w_tr = tr_r[tr_r["return_pct"] > 0]
        l_tr = tr_r[tr_r["return_pct"] <= 0]
        w_rate = len(w_tr) / n_tr * 100.0 if n_tr > 0 else 0.0
        avg_ret = tr_r["return_pct"].mean()
        med_ret = tr_r["return_pct"].median()
        w_sum = w_tr["return_pct"].sum()
        l_sum = abs(l_r_sum := abs(l_tr["return_pct"].sum()))
        pf = (w_sum / l_sum) if l_sum > 1e-4 else 99.0

        regime_breakdown_rows.append({
            "Market_Regime": reg,
            "Num_Trades": n_tr,
            "WinRate": w_rate,
            "AvgReturn": avg_ret,
            "MedianReturn": med_ret,
            "ProfitFactor": pf,
            "TotalReturnSum": tr_r["return_pct"].sum()
        })
    reg_bk_df = pd.DataFrame(regime_breakdown_rows)
    reg_bk_df.to_csv(REPORTS_DIR / "gfs_adaptive_regime_breakdown.csv", index=False)
    print("Exported regime performance breakdown.")

    # =========================================================================
    # EXPERIMENT 16: STOP LOSS GAP-DOWN AUDIT (SECTION 12, 14)
    # =========================================================================
    print("\n" + "=" * 80)
    print("EXPERIMENT 16: STOP LOSS GAP-DOWN AUDIT (SECTION 12, 14)")
    print("=" * 80)
    gap_trades = m4_tr[m4_tr["exit_reason"] == "STOP_LOSS_GAP_DOWN"]
    intra_stop_trades = m4_tr[m4_tr["exit_reason"] == "STOP_LOSS_INTRADAY"]
    trailing_trades = m4_tr[m4_tr["exit_reason"] == "DAILY_CLOSE_BELOW_EMA21"]

    gap_audit_rows = [{
        "Model": "Model 4 Full Adaptive",
        "Total_Trades": len(m4_tr),
        "Trailing_EMA21_Exits": len(trailing_trades),
        "Trailing_Pct": len(trailing_trades) / len(m4_tr) * 100 if len(m4_tr) > 0 else 0,
        "Intraday_Stop_Exits": len(intra_stop_trades),
        "Intraday_Stop_Pct": len(intra_stop_trades) / len(m4_tr) * 100 if len(m4_tr) > 0 else 0,
        "GapDown_Stop_Exits": len(gap_trades),
        "GapDown_Stop_Pct": len(gap_trades) / len(m4_tr) * 100 if len(m4_tr) > 0 else 0,
        "Mean_GapDown_Loss_Pct": gap_trades["return_pct"].mean() if not gap_trades.empty else -5.0,
        "Worst_GapDown_Loss_Pct": gap_trades["return_pct"].min() if not gap_trades.empty else -5.0
    }]
    gap_df = pd.DataFrame(gap_audit_rows)
    gap_df.to_csv(REPORTS_DIR / "gfs_adaptive_stop_audit.csv", index=False)
    print("Exported stop loss audit.")

    print("\n" + "=" * 80)
    print("ALL EXPERIMENTS COMPLETED SUCCESSFULLY!")
    print("=" * 80)

if __name__ == "__main__":
    run_all_experiments()

