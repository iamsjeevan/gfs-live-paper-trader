"""
Comprehensive Backtest & Quantitative Research Engine
GFS Multi-Timeframe Strategy: Low-Maintenance, Long-Holding Trend Exits (2018-2026)
"""

import sqlite3
import time
import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

DB_PATH = Path("data/indian_market.db")
REPORTS_DIR = Path("reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# TECHNICAL INDICATORS
# -----------------------------------------------------------------------------
def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)

def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

EXCLUDED_SYMBOLS = {
    "NIFTY50", "BANKNIFTY", "NIFTYIT", "NIFTYBEES", "GOLDBEES", "BANKBEES",
    "LIQUIDBEES", "INFRABEES", "JUNIORBEES", "MON100", "CPSEETF", "SILVERBEES",
    "AUTOBEES", "PHARMABEES", "SETFNIF50", "HDFCMFGETF", "ICICIB22", "KOTAKBKETF"
}

# -----------------------------------------------------------------------------
# STEP 1: LOAD DATA & PRECOMPUTE DAILY, WEEKLY, MONTHLY CANDLES & INDICATORS
# -----------------------------------------------------------------------------
def load_data_and_precompute():
    print("=" * 80)
    print("STEP 1: LOADING DATA & PRECOMPUTING MULTI-TIMEFRAME INDICATORS")
    print("=" * 80)
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)

    sec_df = pd.read_sql("SELECT security_id, symbol, company_name, industry FROM securities;", conn)
    etf_mask = sec_df["symbol"].isin(EXCLUDED_SYMBOLS) | sec_df["symbol"].str.contains("BEES|ETF|NIFTY", case=False, na=False)
    corp_sec = sec_df[~etf_mask].copy()
    sec_info = corp_sec.set_index("security_id").to_dict(orient="index")
    corp_ids = set(corp_sec["security_id"])

    # Sector mapping
    try:
        tfa = pd.read_sql("SELECT DISTINCT Ticker as symbol, sector FROM trades_fundamental_analysis WHERE sector IS NOT NULL AND sector != '';", conn)
        sector_map = dict(zip(tfa["symbol"], tfa["sector"]))
    except Exception:
        sector_map = {}

    for sid, row in corp_sec.iterrows():
        s_sym = row["symbol"]
        if s_sym not in sector_map or not sector_map[s_sym]:
            ind = row["industry"]
            if pd.notna(ind) and ind.strip():
                sector_map[s_sym] = ind.title()
            else:
                sector_map[s_sym] = "Diversified / Other"

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

    daily_df = pd.read_sql("SELECT security_id, date, open, high, low, close, volume FROM daily_ohlcv WHERE security_id IN (" + ",".join(map(str, corp_ids)) + ") ORDER BY security_id, date ASC;", conn)
    conn.close()

    print(f"Loaded {len(daily_df):,} daily bars across {daily_df['security_id'].nunique():,} stocks in {time.time()-t0:.2f}s.")
    return daily_df, nifty_df, sec_info, sector_map, nifty_regime_map

# -----------------------------------------------------------------------------
# STEP 2: BUILD HTF CANDLES & DETECT GFS ENTRY SIGNALS
# -----------------------------------------------------------------------------
def build_htf_and_generate_signals(daily_df, sec_info, sector_map):
    print("\n" + "=" * 80)
    print("STEP 2: BUILDING WEEKLY/MONTHLY CANDLES & SCANNING GFS ENTRY SIGNALS")
    print("=" * 80)
    t0 = time.time()

    all_signals = []
    processed_stocks = {}

    for sec_id, g in daily_df.groupby("security_id"):
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

        # Daily RSI & prev RSI
        c = g["close"]
        g["daily_rsi"] = compute_rsi(c, 14)
        g["prev_daily_rsi"] = g["daily_rsi"].shift(1)
        g["daily_ema21"] = compute_ema(c, 21)

        # ---------------------------------------------------------------------
        # WEEKLY AGGREGATION & INDICATORS
        # ---------------------------------------------------------------------
        w_df = g.groupby("year_week").agg(
            w_open=("open", "first"),
            w_high=("high", "max"),
            w_low=("low", "min"),
            w_close=("close", "last"),
            last_date=("date", "last")
        ).reset_index()

        # Weekly RSI completed (shift 1 for entry qualification to ensure strictly completed candle)
        w_df["weekly_rsi_raw"] = compute_rsi(w_df["w_close"], 14)
        w_df["weekly_rsi_entry"] = w_df["weekly_rsi_raw"].shift(1)
        
        # Weekly EMAs for exit (evaluated on completed weekly candle)
        w_df["w_ema5"] = compute_ema(w_df["w_close"], 5)
        w_df["w_ema9"] = compute_ema(w_df["w_close"], 9)
        w_df["w_ema12"] = compute_ema(w_df["w_close"], 12)
        w_df["w_ema20"] = compute_ema(w_df["w_close"], 20)
        w_df["w_ema26"] = compute_ema(w_df["w_close"], 26)
        w_df["prev_w_low"] = w_df["w_low"].shift(1)

        # Maps for entry lookup
        w_entry_map = dict(zip(w_df["year_week"], w_df["weekly_rsi_entry"]))
        g["weekly_rsi_completed"] = g["year_week"].map(w_entry_map)

        # Maps for weekly exit trigger on week-end day
        w_end_dates = set(w_df["last_date"].values)
        w_info = w_df.set_index("last_date")

        # ---------------------------------------------------------------------
        # MONTHLY AGGREGATION & INDICATORS
        # ---------------------------------------------------------------------
        m_df = g.groupby("year_month").agg(
            m_open=("open", "first"),
            m_high=("high", "max"),
            m_low=("low", "min"),
            m_close=("close", "last"),
            last_date=("date", "last")
        ).reset_index()

        m_df["monthly_rsi_raw"] = compute_rsi(m_df["m_close"], 14)
        m_df["monthly_rsi_entry"] = m_df["monthly_rsi_raw"].shift(1)

        # Monthly EMAs for exit
        m_df["m_ema5"] = compute_ema(m_df["m_close"], 5)
        m_df["m_ema9"] = compute_ema(m_df["m_close"], 9)
        m_df["m_ema12"] = compute_ema(m_df["m_close"], 12)
        m_df["m_ema20"] = compute_ema(m_df["m_close"], 20)
        m_df["prev_m_low"] = m_df["m_low"].shift(1)

        m_entry_map = dict(zip(m_df["year_month"], m_df["monthly_rsi_entry"]))
        g["monthly_rsi_completed"] = g["year_month"].map(m_entry_map)

        m_end_dates = set(m_df["last_date"].values)
        m_info = m_df.set_index("last_date")

        # Attach HTF exit indicator values to day d
        g["is_week_end"] = g["date"].isin(w_end_dates)
        g["w_close"] = g["date"].map(w_info["w_close"]).fillna(np.nan)
        g["w_ema5"] = g["date"].map(w_info["w_ema5"]).fillna(np.nan)
        g["w_ema9"] = g["date"].map(w_info["w_ema9"]).fillna(np.nan)
        g["w_ema12"] = g["date"].map(w_info["w_ema12"]).fillna(np.nan)
        g["w_ema20"] = g["date"].map(w_info["w_ema20"]).fillna(np.nan)
        g["w_ema26"] = g["date"].map(w_info["w_ema26"]).fillna(np.nan)
        g["w_rsi"] = g["date"].map(w_info["weekly_rsi_raw"]).fillna(np.nan)
        g["prev_w_low"] = g["date"].map(w_info["prev_w_low"]).fillna(np.nan)

        # Month-end indicators
        g["is_month_end"] = g["date"].isin(m_end_dates)
        g["m_close"] = g["date"].map(m_info["m_close"]).fillna(np.nan)
        g["m_ema5"] = g["date"].map(m_info["m_ema5"]).fillna(np.nan)
        g["m_ema9"] = g["date"].map(m_info["m_ema9"]).fillna(np.nan)
        g["m_ema12"] = g["date"].map(m_info["m_ema12"]).fillna(np.nan)
        g["m_ema20"] = g["date"].map(m_info["m_ema20"]).fillna(np.nan)
        g["m_rsi"] = g["date"].map(m_info["monthly_rsi_raw"]).fillna(np.nan)
        g["prev_m_low"] = g["date"].map(w_info["prev_m_low"] if "prev_m_low" in w_info else m_info["prev_m_low"]).fillna(np.nan)

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
                "signal_date": row["date"],
                "entry_date": row["entry_date"],
                "signal_close": row["close"],
                "entry_price": row["entry_open"],
                "prev_daily_rsi": row["prev_daily_rsi"],
                "daily_rsi": row["daily_rsi"],
                "weekly_rsi": row["weekly_rsi_completed"],
                "monthly_rsi": row["monthly_rsi_completed"]
            })

    signals_df = pd.DataFrame(all_signals).sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    print(f"Generated {len(signals_df):,} baseline GFS signals across universe in {time.time()-t0:.2f}s.")
    return signals_df, processed_stocks

GLOBAL_STOCK_DATE_LOOKUP = {}
GLOBAL_ALL_TRADING_DAYS = []

# -----------------------------------------------------------------------------
# STEP 3: GENERALIZED LOW-MAINTENANCE SIMULATION ENGINE
# -----------------------------------------------------------------------------
def simulate_low_maintenance_engine(
    signals_subset,
    processed_stocks,
    nifty_regime_map,
    capacity: int = 15,
    sector_cap_pct: float = 0.25,
    regime_schedule: str = "fixed", # 'fixed' or 'sch1' (100/70/30)
    # Exit configuration:
    exit_type: str = "fixed_hold", # 'fixed_hold', 'weekly_ema', 'monthly_ema', 'weekly_rsi', 'monthly_rsi', 'price_based', 'hybrid'
    exit_param: str = "60D", # e.g. 60D, w_ema9, m_ema9, w_rsi50, m_rsi50, etc.
    cat_stop_pct: float = None, # None or -0.10 to -0.30
    profit_logic: str = None, # None, 'sys_a_25' (remove stop after +25%), 'sys_b_50' (remove after +50%), 'sys_c_100' (remove after +100%)
    cost_bps: float = 25.0,
    start_date: str = "2018-01-01",
    end_date: str = "2026-12-31"
):
    """
    Simulates portfolio execution with weekly/monthly trend exits and disaster stops.
    Exits execute at the NEXT TRADING DAY OPEN.
    """
    STARTING_CAPITAL = 1_000_000.0
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)

    schedules = {
        "fixed": {"BULL": 1.0, "NEUTRAL": 1.0, "BEAR": 1.0},
        "sch1": {"BULL": 1.0, "NEUTRAL": 0.70, "BEAR": 0.30},
    }
    exp_sch = schedules.get(regime_schedule, schedules["fixed"])

    sig_sub = signals_subset[(signals_subset["signal_date"] >= start_date) & (signals_subset["signal_date"] <= end_date)]
    sig_by_date = {}
    for sig in sig_sub.to_dict(orient="records"):
        sig_by_date.setdefault(sig["signal_date"], []).append(sig)

    global GLOBAL_STOCK_DATE_LOOKUP, GLOBAL_ALL_TRADING_DAYS
    if not GLOBAL_STOCK_DATE_LOOKUP:
        GLOBAL_STOCK_DATE_LOOKUP = {sym: {r["date"]: r for r in df.to_dict(orient="records")} for sym, df in processed_stocks.items()}
        GLOBAL_ALL_TRADING_DAYS = sorted(list(set(d for sym_dict in GLOBAL_STOCK_DATE_LOOKUP.values() for d in sym_dict)))

    all_dates = [d for d in GLOBAL_ALL_TRADING_DAYS if start_date <= d <= end_date]

    cash = STARTING_CAPITAL
    open_positions = {}
    closed_trades = []
    daily_stats = []

    for d_idx, d in enumerate(all_dates):
        # 1. Process Open Exits (Pending from Yesterday's Close Trigger)
        to_close = []
        for sym, pos in open_positions.items():
            r = GLOBAL_STOCK_DATE_LOOKUP.get(sym, {}).get(d)
            if r is None:
                continue
            op, hp, lp, cp = r["open"], r["high"], r["low"], r["close"]
            pos["last_close"] = cp
            pos["holding_days"] += 1

            # Track MFE / MAE
            high_gain = (hp - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0
            low_loss = (lp - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0
            pos["max_favorable_pct"] = max(pos["max_favorable_pct"], high_gain)
            pos["max_adverse_pct"] = min(pos["max_adverse_pct"], low_loss)

            # A. Execute Pending HTF or Fixed Exit from Yesterday's Close
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
                    "max_favorable_pct": pos["max_favorable_pct"],
                    "max_adverse_pct": pos["max_adverse_pct"],
                    "gap_down": False
                })
                to_close.append(sym)
                continue

            # B. Check Catastrophic Stop Loss Gap Down at Today's Open (if stop active)
            cur_stop_p = pos["stop_price"]
            if cur_stop_p is not None:
                if op <= cur_stop_p:
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
                        "exit_reason": "CATASTROPHIC_STOP_GAP_DOWN",
                        "max_favorable_pct": pos["max_favorable_pct"],
                        "max_adverse_pct": min(pos["max_adverse_pct"], (op - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0),
                        "gap_down": True
                    })
                    to_close.append(sym)
                    continue

        for sym in to_close:
            del open_positions[sym]

        # 2. Portfolio Equity & Sizing
        invested_equity = sum(pos["shares"] * pos["last_close"] for pos in open_positions.values())
        total_equity = cash + invested_equity
        regime = nifty_regime_map.get(d, "NEUTRAL")
        target_exp = exp_sch.get(regime, 1.0)
        max_allowed_equity = total_equity * target_exp
        max_allowed_positions = int(round(capacity * target_exp))

        # 3. Process New Entries (Day d Open from Day d-1 signals)
        prev_d = all_dates[d_idx - 1] if d_idx > 0 else None
        day_signals = sig_by_date.get(prev_d, []) if prev_d else []

        if day_signals and len(open_positions) < max_allowed_positions and invested_equity < max_allowed_equity:
            candidates = []
            for sig in day_signals:
                s_sym = sig["symbol"]
                if s_sym in open_positions:
                    continue
                sec = sig["sector"]
                if sector_cap_pct is not None:
                    curr_sec = sum(1 for p in open_positions.values() if p["sector"] == sec)
                    max_sec = max(1, int(round(capacity * sector_cap_pct)))
                    if curr_sec >= max_sec:
                        continue
                candidates.append(sig)

            if candidates:
                available_slots = max(0, max_allowed_positions - len(open_positions))
                alloc_per_slot = total_equity / capacity

                for cand in candidates[:available_slots]:
                    s_sym = cand["symbol"]
                    raw_entry_p = cand["entry_price"]
                    sim_entry_p = raw_entry_p * cost_mult_entry
                    sec = cand["sector"]

                    if sector_cap_pct is not None:
                        curr_sec = sum(1 for p in open_positions.values() if p["sector"] == sec)
                        max_sec = max(1, int(round(capacity * sector_cap_pct)))
                        if curr_sec >= max_sec:
                            continue

                    avail_alloc = min(cash, alloc_per_slot)
                    if avail_alloc > 1000.0 and (invested_equity + avail_alloc) <= (max_allowed_equity * 1.05):
                        shares = avail_alloc / sim_entry_p
                        cash -= avail_alloc
                        invested_equity += avail_alloc

                        initial_stop = (raw_entry_p * (1.0 + cat_stop_pct)) if cat_stop_pct is not None else None

                        open_positions[s_sym] = {
                            "symbol": s_sym,
                            "sector": sec,
                            "entry_date": d,
                            "sim_entry_price": sim_entry_p,
                            "raw_entry_price": raw_entry_p,
                            "shares": shares,
                            "last_close": raw_entry_p,
                            "stop_price": initial_stop,
                            "holding_days": 0,
                            "max_favorable_pct": 0.0,
                            "max_adverse_pct": 0.0,
                            "pending_exit": False,
                            "pending_exit_reason": ""
                        }

        # 4. Intraday Checks & End of Day Exit Conditions
        to_close_intraday = []
        for sym, pos in open_positions.items():
            r = GLOBAL_STOCK_DATE_LOOKUP.get(sym, {}).get(d)
            if r is None:
                continue
            op, hp, lp, cp = r["open"], r["high"], r["low"], r["close"]
            pos["last_close"] = cp
            high_gain = (hp - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0
            low_loss = (lp - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0
            pos["max_favorable_pct"] = max(pos["max_favorable_pct"], high_gain)
            pos["max_adverse_pct"] = min(pos["max_adverse_pct"], low_loss)

            # Check Profitable Position Logic (Remove Catastrophic Stop if reached threshold)
            if profit_logic and pos["stop_price"] is not None:
                cur_mfe = pos["max_favorable_pct"]
                if profit_logic == "sys_a_25" and cur_mfe >= 25.0:
                    pos["stop_price"] = None # remove catastrophic stop
                elif profit_logic == "sys_b_50" and cur_mfe >= 50.0:
                    pos["stop_price"] = None
                elif profit_logic == "sys_c_100" and cur_mfe >= 100.0:
                    pos["stop_price"] = None

            # Intraday Catastrophic Stop Loss Check
            cur_stop_p = pos["stop_price"]
            if cur_stop_p is not None:
                if lp <= cur_stop_p:
                    exit_price = cur_stop_p * cost_mult_exit
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
                        "raw_exit_price": cur_stop_p,
                        "return_pct": ret_pct,
                        "holding_days": pos["holding_days"],
                        "exit_reason": "CATASTROPHIC_STOP_INTRADAY",
                        "max_favorable_pct": pos["max_favorable_pct"],
                        "max_adverse_pct": pos["max_adverse_pct"],
                        "gap_down": False
                    })
                    to_close_intraday.append(sym)
                    continue

            # -----------------------------------------------------------------
            # END OF DAY EXIT TRIGGERS (TO EXECUTE NEXT TRADING DAY OPEN)
            # -----------------------------------------------------------------
            # A. Fixed Holding Benchmarks
            if exit_type == "fixed_hold":
                h_target = int(exit_param.replace("D", ""))
                if pos["holding_days"] >= h_target:
                    pos["pending_exit"] = True
                    pos["pending_exit_reason"] = f"FIXED_{h_target}D"

            # B. Weekly EMA Exits (Evaluated only on completed weekly candle)
            elif exit_type == "weekly_ema":
                if r["is_week_end"]:
                    w_col = exit_param # e.g. 'w_ema5', 'w_ema9', 'w_ema12', 'w_ema20', 'w_ema26'
                    ema_val = r[w_col]
                    w_close = r["w_close"]
                    if pd.notna(ema_val) and pd.notna(w_close) and w_close < ema_val:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = f"WEEKLY_CLOSE_LT_{exit_param.upper()}"

            # C. Monthly EMA Exits (Evaluated only on completed monthly candle)
            elif exit_type == "monthly_ema":
                if r["is_month_end"]:
                    m_col = exit_param # e.g. 'm_ema5', 'm_ema9', 'm_ema12', 'm_ema20'
                    ema_val = r[m_col]
                    m_close = r["m_close"]
                    if pd.notna(ema_val) and pd.notna(m_close) and m_close < ema_val:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = f"MONTHLY_CLOSE_LT_{exit_param.upper()}"

            # D. Weekly RSI Exits
            elif exit_type == "weekly_rsi":
                if r["is_week_end"]:
                    thresh = float(exit_param) # 55, 50, 45, 40
                    w_rsi = r["w_rsi"]
                    if pd.notna(w_rsi) and w_rsi < thresh:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = f"WEEKLY_RSI_LT_{int(thresh)}"

            # E. Monthly RSI Exits
            elif exit_type == "monthly_rsi":
                if r["is_month_end"]:
                    thresh = float(exit_param) # 55, 50, 45, 40
                    m_rsi = r["m_rsi"]
                    if pd.notna(m_rsi) and m_rsi < thresh:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = f"MONTHLY_RSI_LT_{int(thresh)}"

            # F. Price-Based Higher-Timeframe Exits
            elif exit_type == "price_based":
                if exit_param == "weekly_prev_low" and r["is_week_end"]:
                    if pd.notna(r["prev_w_low"]) and pd.notna(r["w_close"]) and r["w_close"] < r["prev_w_low"]:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = "WEEKLY_CLOSE_LT_PREV_WEEK_LOW"
                elif exit_param == "monthly_prev_low" and r["is_month_end"]:
                    if pd.notna(r["prev_m_low"]) and pd.notna(r["m_close"]) and r["m_close"] < r["prev_m_low"]:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = "MONTHLY_CLOSE_LT_PREV_MONTH_LOW"
                elif exit_param == "weekly_close_ema9" and r["is_week_end"]:
                    if pd.notna(r["w_ema9"]) and pd.notna(r["w_close"]) and r["w_close"] < r["w_ema9"]:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = "WEEKLY_CLOSE_LT_W_EMA9"
                elif exit_param == "monthly_close_ema9" and r["is_month_end"]:
                    if pd.notna(r["m_ema9"]) and pd.notna(r["m_close"]) and r["m_close"] < r["m_ema9"]:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = "MONTHLY_CLOSE_LT_M_EMA9"

            # G. Hybrid Exits (Exit when EITHER condition becomes true)
            elif exit_type == "hybrid":
                triggered = False
                reason = ""
                # Parse hybrid exit rules:
                if exit_param == "w_ema9_or_w_rsi50":
                    if r["is_week_end"]:
                        if pd.notna(r["w_ema9"]) and r["w_close"] < r["w_ema9"]:
                            triggered, reason = True, "W_CLOSE_LT_W_EMA9"
                        elif pd.notna(r["w_rsi"]) and r["w_rsi"] < 50.0:
                            triggered, reason = True, "W_RSI_LT_50"
                elif exit_param == "w_ema20_or_w_rsi50":
                    if r["is_week_end"]:
                        if pd.notna(r["w_ema20"]) and r["w_close"] < r["w_ema20"]:
                            triggered, reason = True, "W_CLOSE_LT_W_EMA20"
                        elif pd.notna(r["w_rsi"]) and r["w_rsi"] < 50.0:
                            triggered, reason = True, "W_RSI_LT_50"
                elif exit_param == "m_ema9_or_m_rsi50":
                    if r["is_month_end"]:
                        if pd.notna(r["m_ema9"]) and r["m_close"] < r["m_ema9"]:
                            triggered, reason = True, "M_CLOSE_LT_M_EMA9"
                        elif pd.notna(r["m_rsi"]) and r["m_rsi"] < 50.0:
                            triggered, reason = True, "M_RSI_LT_50"
                elif exit_param == "m_ema12_or_m_rsi50":
                    if r["is_month_end"]:
                        if pd.notna(r["m_ema12"]) and r["m_close"] < r["m_ema12"]:
                            triggered, reason = True, "M_CLOSE_LT_M_EMA12"
                        elif pd.notna(r["m_rsi"]) and r["m_rsi"] < 50.0:
                            triggered, reason = True, "M_RSI_LT_50"
                elif exit_param == "m_ema20_or_m_rsi50":
                    if r["is_month_end"]:
                        if pd.notna(r["m_ema20"]) and r["m_close"] < r["m_ema20"]:
                            triggered, reason = True, "M_CLOSE_LT_M_EMA20"
                        elif pd.notna(r["m_rsi"]) and r["m_rsi"] < 50.0:
                            triggered, reason = True, "M_RSI_LT_50"
                elif exit_param == "w_ema20_or_m_ema9":
                    if r["is_week_end"] and pd.notna(r["w_ema20"]) and r["w_close"] < r["w_ema20"]:
                        triggered, reason = True, "W_CLOSE_LT_W_EMA20"
                    elif r["is_month_end"] and pd.notna(r["m_ema9"]) and r["m_close"] < r["m_ema9"]:
                        triggered, reason = True, "M_CLOSE_LT_M_EMA9"
                elif exit_param == "w_ema26_or_m_ema12":
                    if r["is_week_end"] and pd.notna(r["w_ema26"]) and r["w_close"] < r["w_ema26"]:
                        triggered, reason = True, "W_CLOSE_LT_W_EMA26"
                    elif r["is_month_end"] and pd.notna(r["m_ema12"]) and r["m_close"] < r["m_ema12"]:
                        triggered, reason = True, "M_CLOSE_LT_M_EMA12"

                if triggered:
                    pos["pending_exit"] = True
                    pos["pending_exit_reason"] = reason

        for sym in to_close_intraday:
            del open_positions[sym]

        # 5. Record Daily Stats
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

    # Close any positions still open on last day
    last_d = all_dates[-1]
    for sym, pos in open_positions.items():
        r = GLOBAL_STOCK_DATE_LOOKUP.get(sym, {}).get(last_d)
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
            "exit_reason": "END_OF_BACKTEST",
            "max_favorable_pct": pos["max_favorable_pct"],
            "max_adverse_pct": pos["max_adverse_pct"],
            "gap_down": False
        })

    daily_df = pd.DataFrame(daily_stats)
    trades_df = pd.DataFrame(closed_trades)

    # -------------------------------------------------------------------------
    # PERFORMANCE METRICS CALCULATION
    # -------------------------------------------------------------------------
    ending_val = daily_df["equity"].iloc[-1] if not daily_df.empty else STARTING_CAPITAL
    total_ret_pct = ((ending_val - STARTING_CAPITAL) / STARTING_CAPITAL) * 100.0
    n_days = len(daily_df)
    n_years = n_days / 252.0 if n_days > 0 else 1.0
    cagr = (((ending_val / STARTING_CAPITAL) ** (1.0 / n_years)) - 1.0) * 100.0 if ending_val > 0 else -100.0

    peak = daily_df["equity"].cummax()
    dd_series = (daily_df["equity"] - peak) / peak * 100.0
    max_dd = dd_series.min()

    daily_ret = daily_df["equity"].pct_change().dropna()
    vol_ann = daily_ret.std() * np.sqrt(252) * 100.0 if len(daily_ret) > 1 else 0.0
    sharpe = ((daily_ret.mean() * 252.0) / (daily_ret.std() * np.sqrt(252.0))) if daily_ret.std() > 1e-6 else 0.0
    calmar = abs(cagr / max_dd) if abs(max_dd) > 1e-4 else 0.0

    n_trades = len(trades_df)
    if n_trades > 0:
        win_trades = trades_df[trades_df["return_pct"] > 0]
        loss_trades = trades_df[trades_df["return_pct"] <= 0]
        win_rate = (len(win_trades) / n_trades) * 100.0
        avg_ret = trades_df["return_pct"].mean()
        med_ret = trades_df["return_pct"].median()

        tot_gains = win_trades["return_pct"].sum()
        tot_losses = abs(loss_trades["return_pct"].sum())
        profit_factor = (tot_gains / tot_losses) if tot_losses > 1e-4 else 99.0

        avg_win = win_trades["return_pct"].mean() if not win_trades.empty else 0.0
        avg_loss = loss_trades["return_pct"].mean() if not loss_trades.empty else 0.0
        win_loss_ratio = abs(avg_win / avg_loss) if abs(avg_loss) > 1e-4 else 99.0

        loss_rate = 1.0 - (win_rate / 100.0)
        expectancy = ((win_rate / 100.0) * avg_win) - (loss_rate * abs(avg_loss))
        avg_hold = trades_df["holding_days"].mean()
        med_hold = trades_df["holding_days"].median()
        max_hold = trades_df["holding_days"].max()
        turnover = (n_trades * 2.0) / n_years

        # Multibagger / Winner thresholds
        w25 = (trades_df["return_pct"] >= 25.0).sum()
        w50 = (trades_df["return_pct"] >= 50.0).sum()
        w100 = (trades_df["return_pct"] >= 100.0).sum()
        w200 = (trades_df["return_pct"] >= 200.0).sum()
        w300 = (trades_df["return_pct"] >= 300.0).sum()
        w500 = (trades_df["return_pct"] >= 500.0).sum()
        max_winner = trades_df["return_pct"].max()

        # Patience duration thresholds
        # 1 month ~ 21 days, 6 months ~ 126 days, 1 year ~ 252 days, 2y ~ 504d, 3y ~ 756d, 5y ~ 1260d
        h_6m = (trades_df["holding_days"] >= 126).sum()
        h_1y = (trades_df["holding_days"] >= 252).sum()
        h_2y = (trades_df["holding_days"] >= 504).sum()
        h_3y = (trades_df["holding_days"] >= 756).sum()
        h_5y = (trades_df["holding_days"] >= 1260).sum()

        # Top trade contribution
        sorted_rets = trades_df["return_pct"].sort_values(ascending=False).values
        tot_positive_ret = trades_df[trades_df["return_pct"] > 0]["return_pct"].sum()
        top1_pct_count = max(1, int(round(len(sorted_rets) * 0.01)))
        top1_contrib = (sorted_rets[:top1_pct_count].sum() / tot_positive_ret * 100.0) if tot_positive_ret > 0 else 0.0
        top5_contrib = (sorted_rets[:5].sum() / tot_positive_ret * 100.0) if tot_positive_ret > 0 else 0.0
        top10_contrib = (sorted_rets[:10].sum() / tot_positive_ret * 100.0) if tot_positive_ret > 0 else 0.0
    else:
        win_rate = avg_ret = med_ret = profit_factor = avg_win = avg_loss = win_loss_ratio = expectancy = 0.0
        avg_hold = med_hold = max_hold = turnover = 0.0
        w25 = w50 = w100 = w200 = w300 = w500 = max_winner = 0.0
        h_6m = h_1y = h_2y = h_3y = h_5y = 0
        top1_contrib = top5_contrib = top10_contrib = 0.0

    avg_exp = daily_df["exposure_pct"].mean()

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
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "expectancy": expectancy,
        "avg_holding_days": avg_hold,
        "median_holding_days": med_hold,
        "max_holding_days": max_hold,
        "annual_turnover": turnover,
        "avg_exposure_pct": avg_exp,
        "w25": w25,
        "w50": w50,
        "w100": w100,
        "w200": w200,
        "w300": w300,
        "w500": w500,
        "max_winner": max_winner,
        "h_6m": h_6m,
        "h_1y": h_1y,
        "h_2y": h_2y,
        "h_3y": h_3y,
        "h_5y": h_5y,
        "top1_contrib": top1_contrib,
        "top5_contrib": top5_contrib,
        "top10_contrib": top10_contrib
    }

    return summary, daily_df, trades_df

# -----------------------------------------------------------------------------
# STEP 4: MAIN RESEARCH EXECUTION ROUTINE
# -----------------------------------------------------------------------------
def run_all_experiments():
    daily_df, nifty_df, sec_info, sector_map, nifty_regime_map = load_data_and_precompute()
    signals_df, processed_stocks = build_htf_and_generate_signals(daily_df, sec_info, sector_map)

    print("Pre-building fast lookup tables for instant simulation execution...")
    t_lookup = time.time()
    global GLOBAL_STOCK_DATE_LOOKUP, GLOBAL_ALL_TRADING_DAYS
    GLOBAL_STOCK_DATE_LOOKUP = {sym: {r["date"]: r for r in df.to_dict(orient="records")} for sym, df in processed_stocks.items()}
    GLOBAL_ALL_TRADING_DAYS = sorted(list(set(d for sym_dict in GLOBAL_STOCK_DATE_LOOKUP.values() for d in sym_dict)))
    print(f"Lookup cache built in {time.time()-t_lookup:.2f}s for {len(GLOBAL_STOCK_DATE_LOOKUP)} stocks across {len(GLOBAL_ALL_TRADING_DAYS)} dates.")

    # -------------------------------------------------------------------------
    # EXPERIMENT 1: FIXED HOLDING BENCHMARKS (SECTION 4.A)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 1: FIXED HOLDING BENCHMARKS (60, 120, 180, 252, 504 Days)")
    print("=" * 80)
    bench_configs = ["60D", "120D", "180D", "252D", "504D"]
    bench_rows = []
    bench_trades = {}
    for h in bench_configs:
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type="fixed_hold", exit_param=h, cost_bps=25.0
        )
        bench_trades[h] = tr
        bench_rows.append({
            "Benchmark": f"Fixed {h}",
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "Turnover": s["annual_turnover"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "W500": s["w500"],
            "MaxWinner": s["max_winner"]
        })
        print(f"Fixed {h:5s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Trades: {s['num_trades']:4d} | AvgTrade: {s['avg_trade_ret']:5.2f}% | >100%: {s['w100']:2d}")
    bench_df = pd.DataFrame(bench_rows)
    bench_df.to_csv(REPORTS_DIR / "gfs_fixed_benchmarks.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 2: WEEKLY EMA EXITS (SECTION 4.B)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 2: WEEKLY EMA EXITS (EMA5, EMA9, EMA12, EMA20, EMA26)")
    print("=" * 80)
    w_ema_configs = [
        ("Weekly EMA5", "w_ema5"),
        ("Weekly EMA9", "w_ema9"),
        ("Weekly EMA12", "w_ema12"),
        ("Weekly EMA20", "w_ema20"),
        ("Weekly EMA26", "w_ema26"),
    ]
    w_ema_rows = []
    for label, param in w_ema_configs:
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type="weekly_ema", exit_param=param, cost_bps=25.0
        )
        w_ema_rows.append({
            "Strategy": label,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "MedianHoldDays": s["median_holding_days"],
            "MaxHoldDays": s["max_holding_days"],
            "Turnover": s["annual_turnover"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "W500": s["w500"],
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:15s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Hold: {s['avg_holding_days']:5.1f}d | >50%: {s['w50']:2d} | >100%: {s['w100']:2d}")
    w_ema_df = pd.DataFrame(w_ema_rows)
    w_ema_df.to_csv(REPORTS_DIR / "gfs_weekly_ema_exits.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 3: MONTHLY EMA EXITS (SECTION 4.C)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 3: MONTHLY EMA EXITS (EMA5, EMA9, EMA12, EMA20)")
    print("=" * 80)
    m_ema_configs = [
        ("Monthly EMA5", "m_ema5"),
        ("Monthly EMA9", "m_ema9"),
        ("Monthly EMA12", "m_ema12"),
        ("Monthly EMA20", "m_ema20"),
    ]
    m_ema_rows = []
    for label, param in m_ema_configs:
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type="monthly_ema", exit_param=param, cost_bps=25.0
        )
        m_ema_rows.append({
            "Strategy": label,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "MedianHoldDays": s["median_holding_days"],
            "MaxHoldDays": s["max_holding_days"],
            "Turnover": s["annual_turnover"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "W500": s["w500"],
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:15s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Hold: {s['avg_holding_days']:5.1f}d | >50%: {s['w50']:2d} | >100%: {s['w100']:2d}")
    m_ema_df = pd.DataFrame(m_ema_rows)
    m_ema_df.to_csv(REPORTS_DIR / "gfs_monthly_ema_exits.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 4: WEEKLY RSI EXITS (SECTION 4.D)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 4: WEEKLY RSI EXITS (<55, <50, <45, <40)")
    print("=" * 80)
    w_rsi_configs = [
        ("Weekly RSI < 55", "55"),
        ("Weekly RSI < 50", "50"),
        ("Weekly RSI < 45", "45"),
        ("Weekly RSI < 40", "40"),
    ]
    w_rsi_rows = []
    for label, param in w_rsi_configs:
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type="weekly_rsi", exit_param=param, cost_bps=25.0
        )
        w_rsi_rows.append({
            "Strategy": label,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "Turnover": s["annual_turnover"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:18s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Hold: {s['avg_holding_days']:5.1f}d | >50%: {s['w50']:2d}")
    w_rsi_df = pd.DataFrame(w_rsi_rows)
    w_rsi_df.to_csv(REPORTS_DIR / "gfs_weekly_rsi_exits.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 5: MONTHLY RSI EXITS (SECTION 4.E)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 5: MONTHLY RSI EXITS (<55, <50, <45, <40)")
    print("=" * 80)
    m_rsi_configs = [
        ("Monthly RSI < 55", "55"),
        ("Monthly RSI < 50", "50"),
        ("Monthly RSI < 45", "45"),
        ("Monthly RSI < 40", "40"),
    ]
    m_rsi_rows = []
    for label, param in m_rsi_configs:
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type="monthly_rsi", exit_param=param, cost_bps=25.0
        )
        m_rsi_rows.append({
            "Strategy": label,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "Turnover": s["annual_turnover"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:18s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Hold: {s['avg_holding_days']:5.1f}d | >50%: {s['w50']:2d}")
    m_rsi_df = pd.DataFrame(m_rsi_rows)
    m_rsi_df.to_csv(REPORTS_DIR / "gfs_monthly_rsi_exits.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 6: PRICE-BASED HIGHER-TIMEFRAME EXITS (SECTION 5)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 6: PRICE-BASED HIGHER-TIMEFRAME EXITS")
    print("=" * 80)
    price_configs = [
        ("Weekly Close < Prev Week Low", "weekly_prev_low"),
        ("Monthly Close < Prev Month Low", "monthly_prev_low"),
        ("Weekly Close < Weekly EMA9", "weekly_close_ema9"),
        ("Monthly Close < Monthly EMA9", "monthly_close_ema9"),
    ]
    price_rows = []
    for label, param in price_configs:
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type="price_based", exit_param=param, cost_bps=25.0
        )
        price_rows.append({
            "Strategy": label,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "Turnover": s["annual_turnover"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:32s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Hold: {s['avg_holding_days']:5.1f}d")
    price_df = pd.DataFrame(price_rows)
    price_df.to_csv(REPORTS_DIR / "gfs_price_based_exits.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 7: HYBRID EXITS (SECTION 6)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 7: HYBRID EXITS (EITHER CONDITION TRUE)")
    print("=" * 80)
    hybrid_configs = [
        ("Weekly EMA9 OR Weekly RSI < 50", "w_ema9_or_w_rsi50"),
        ("Weekly EMA20 OR Weekly RSI < 50", "w_ema20_or_w_rsi50"),
        ("Monthly EMA9 OR Monthly RSI < 50", "m_ema9_or_m_rsi50"),
        ("Monthly EMA12 OR Monthly RSI < 50", "m_ema12_or_m_rsi50"),
        ("Monthly EMA20 OR Monthly RSI < 50", "m_ema20_or_m_rsi50"),
        ("Weekly EMA20 OR Monthly EMA9", "w_ema20_or_m_ema9"),
        ("Weekly EMA26 OR Monthly EMA12", "w_ema26_or_m_ema12"),
    ]
    hybrid_rows = []
    for label, param in hybrid_configs:
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type="hybrid", exit_param=param, cost_bps=25.0
        )
        hybrid_rows.append({
            "Strategy": label,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "Turnover": s["annual_turnover"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:35s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Hold: {s['avg_holding_days']:5.1f}d | >50%: {s['w50']:2d}")
    hybrid_df = pd.DataFrame(hybrid_rows)
    hybrid_df.to_csv(REPORTS_DIR / "gfs_hybrid_exits.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 8: EXTREMELY PATIENT SYSTEMS (HOLDING METRICS >6M TO >5Y) (SECTION 7)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 8: EXTREMELY PATIENT SYSTEMS (HOLDING DURATION BREAKDOWN)")
    print("=" * 80)
    patient_configs = [
        ("Monthly EMA9", "monthly_ema", "m_ema9"),
        ("Monthly EMA12", "monthly_ema", "m_ema12"),
        ("Monthly EMA20", "monthly_ema", "m_ema20"),
        ("Monthly RSI < 50", "monthly_rsi", "50"),
        ("Monthly RSI < 45", "monthly_rsi", "45"),
    ]
    patient_rows = []
    for label, e_type, param in patient_configs:
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type=e_type, exit_param=param, cost_bps=25.0
        )
        patient_rows.append({
            "System": label,
            "TotalTrades": s["num_trades"],
            "AvgHoldDays": s["avg_holding_days"],
            "MedianHoldDays": s["median_holding_days"],
            "MaxHoldDays": s["max_holding_days"],
            "Held_GT_6M": s["h_6m"],
            "Held_GT_1Y": s["h_1y"],
            "Held_GT_2Y": s["h_2y"],
            "Held_GT_3Y": s["h_3y"],
            "Held_GT_5Y": s["h_5y"],
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:18s} -> MaxHold: {s['max_holding_days']:4d}d | MedHold: {s['median_holding_days']:4.0f}d | >6M: {s['h_6m']:3d} | >1Y: {s['h_1y']:2d} | >2Y: {s['h_2y']:2d} | >3Y: {s['h_3y']:2d} | >5Y: {s['h_5y']:2d}")
    patient_df = pd.DataFrame(patient_rows)
    patient_df.to_csv(REPORTS_DIR / "gfs_patient_duration_breakdown.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 9: CATASTROPHIC RISK PROTECTION SWEEP (SECTION 8)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 9: CATASTROPHIC RISK PROTECTION SWEEP ON MONTHLY EMA9")
    print("=" * 80)
    s_unstopped, _, tr_unstopped = simulate_low_maintenance_engine(
        signals_df, processed_stocks, nifty_regime_map,
        capacity=15, exit_type="monthly_ema", exit_param="m_ema9", cat_stop_pct=None, cost_bps=25.0
    )

    stop_levels = [None, -0.10, -0.15, -0.20, -0.25, -0.30]
    cat_rows = []
    for st in stop_levels:
        st_label = "No Catastrophic Stop" if st is None else f"{int(st*100)}%"
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type="monthly_ema", exit_param="m_ema9", cat_stop_pct=st, cost_bps=25.0
        )
        stopped_out = tr[tr["exit_reason"].str.contains("CATASTROPHIC_STOP")]
        n_stopped = len(stopped_out)

        cut_winners = 0
        for _, str_row in stopped_out.iterrows():
            sym_s = str_row["symbol"]
            e_d = str_row["entry_date"]
            match_base = tr_unstopped[(tr_unstopped["symbol"] == sym_s) & (tr_unstopped["entry_date"] == e_d)]
            if not match_base.empty and match_base.iloc[0]["return_pct"] > 0:
                cut_winners += 1

        cat_rows.append({
            "Catastrophic_Stop": st_label,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "StoppedOutCount": n_stopped,
            "KilledWinnersCount": cut_winners,
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "MaxWinner": s["max_winner"]
        })
        print(f"{st_label:22s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Stopped: {n_stopped:3d} | Killed Winners: {cut_winners:2d}")
    cat_df = pd.DataFrame(cat_rows)
    cat_df.to_csv(REPORTS_DIR / "gfs_catastrophic_stop_sweep.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 10: OPTIONAL "PROFITABLE POSITION" LOGIC (SECTION 9)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 10: PROFITABLE POSITION LOGIC (REMOVE STOP AFTER WIN)")
    print("=" * 80)
    profit_configs = [
        ("Monthly EMA9: Static -20% Stop", None),
        ("Monthly EMA9: Remove Stop after +25% (Sys A)", "sys_a_25"),
        ("Monthly EMA9: Remove Stop after +50% (Sys B)", "sys_b_50"),
        ("Monthly EMA9: Remove Stop after +100% (Sys C)", "sys_c_100"),
    ]
    prof_rows = []
    for label, plog in profit_configs:
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type="monthly_ema", exit_param="m_ema9",
            cat_stop_pct=-0.20, profit_logic=plog, cost_bps=25.0
        )
        prof_rows.append({
            "Strategy": label,
            "Profit_Logic": str(plog),
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:45s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Hold: {s['avg_holding_days']:5.1f}d | W100: {s['w100']:2d}")
    prof_df = pd.DataFrame(prof_rows)
    prof_df.to_csv(REPORTS_DIR / "gfs_profitable_position_logic.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 11: MULTIBAGGER ANALYSIS & CASE STUDIES (SECTION 15)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 11: MULTIBAGGER DISTRIBUTION & TOP CONTRIBUTION")
    print("=" * 80)
    mb_configs = [
        ("Monthly EMA9", "monthly_ema", "m_ema9", None),
        ("Monthly EMA12", "monthly_ema", "m_ema12", None),
        ("Weekly EMA20", "weekly_ema", "w_ema20", None),
        ("Monthly EMA9 (-20% stop)", "monthly_ema", "m_ema9", -0.20),
        ("Monthly EMA12 (-20% stop)", "monthly_ema", "m_ema12", -0.20),
        ("Fixed 120D Benchmark", "fixed_hold", "120D", None),
        ("Fixed 252D Benchmark", "fixed_hold", "252D", None),
    ]
    mb_rows = []
    sample_trades_for_case_study = None
    for label, e_type, param, c_stop in mb_configs:
        s, _, tr = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type=e_type, exit_param=param, cat_stop_pct=c_stop, cost_bps=25.0
        )
        if label == "Monthly EMA9":
            sample_trades_for_case_study = tr.copy()
        mb_rows.append({
            "System": label,
            "Trades": s["num_trades"],
            "W25": s["w25"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "W300": s["w300"],
            "W500": s["w500"],
            "MaxWinner": s["max_winner"],
            "AvgWin": s["avg_win"],
            "Top1Pct_Contrib": s["top1_contrib"],
            "Top5_Contrib": s["top5_contrib"],
            "Top10_Contrib": s["top10_contrib"],
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"]
        })
        print(f"{label:26s} -> W50: {s['w50']:2d} | W100: {s['w100']:2d} | W200: {s['w200']:2d} | W500: {s['w500']:2d} | Max: {s['max_winner']:6.1f}% | Top5: {s['top5_contrib']:4.1f}%")
    mb_df = pd.DataFrame(mb_rows)
    mb_df.to_csv(REPORTS_DIR / "gfs_multibagger_distribution.csv", index=False)

    # Identify concrete case studies where stock dipped 10-20% but became >100%/200% winner
    case_studies = []
    if sample_trades_for_case_study is not None:
        deep_dip_winners = sample_trades_for_case_study[
            (sample_trades_for_case_study["max_adverse_pct"] <= -10.0) &
            (sample_trades_for_case_study["return_pct"] >= 100.0)
        ].sort_values("return_pct", ascending=False)
        for _, r in deep_dip_winners.head(10).iterrows():
            case_studies.append({
                "Symbol": r["symbol"],
                "Sector": r["sector"],
                "EntryDate": r["entry_date"],
                "ExitDate": r["exit_date"],
                "HoldingDays": r["holding_days"],
                "MaxDipPct": r["max_adverse_pct"],
                "FinalReturnPct": r["return_pct"],
                "ExitReason": r["exit_reason"]
            })
    case_df = pd.DataFrame(case_studies)
    case_df.to_csv(REPORTS_DIR / "gfs_multibagger_deep_dip_cases.csv", index=False)
    print("\nIdentified Multibagger Deep-Dip Case Studies:")
    for _, cs in case_df.head(5).iterrows():
        print(f"  {cs['Symbol']:12s} ({cs['Sector'][:15]:15s}): Dipped {cs['MaxDipPct']:5.1f}% after entry, then rallied to +{cs['FinalReturnPct']:5.1f}% (Held {cs['HoldingDays']} days)")

    # -------------------------------------------------------------------------
    # EXPERIMENT 12: MAE / MFE QUANTILE DISTRIBUTIONS (SECTION 16)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 12: MAE / MFE COHORT DISTRIBUTIONS (Monthly EMA9 System)")
    print("=" * 80)
    tr_m9 = sample_trades_for_case_study
    cohorts = [
        ("All Trades", tr_m9),
        ("Winners (>0%)", tr_m9[tr_m9["return_pct"] > 0]),
        ("Losers (<=0%)", tr_m9[tr_m9["return_pct"] <= 0]),
        ("Winners >= +50%", tr_m9[tr_m9["return_pct"] >= 50.0]),
        ("Winners >= +100%", tr_m9[tr_m9["return_pct"] >= 100.0]),
        ("Winners >= +200%", tr_m9[tr_m9["return_pct"] >= 200.0]),
    ]
    mae_mfe_rows = []
    for c_name, c_df in cohorts:
        if len(c_df) > 0:
            maes = c_df["max_adverse_pct"].values
            mfes = c_df["max_favorable_pct"].values
            mae_mfe_rows.append({
                "Cohort": c_name,
                "SampleCount": len(c_df),
                "MAE_25th": np.percentile(maes, 25),
                "MAE_Median": np.percentile(maes, 50),
                "MAE_75th": np.percentile(maes, 75),
                "MAE_90th": np.percentile(maes, 90),
                "MFE_25th": np.percentile(mfes, 25),
                "MFE_Median": np.percentile(mfes, 50),
                "MFE_75th": np.percentile(mfes, 75),
                "MFE_90th": np.percentile(mfes, 90),
            })
            print(f"{c_name:18s} (N={len(c_df):3d}) -> MAE Median: {np.percentile(maes, 50):5.1f}% | MAE 25th: {np.percentile(maes, 25):5.1f}% | MFE Median: {np.percentile(mfes, 50):5.1f}%")
    mae_mfe_df = pd.DataFrame(mae_mfe_rows)
    mae_mfe_df.to_csv(REPORTS_DIR / "gfs_mae_mfe_cohorts.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 13: PORTFOLIO CAPACITY (10, 15, 20 POSITIONS) (SECTION 11)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 13: PORTFOLIO CAPACITY SWEEP (Monthly EMA9 & Weekly EMA20)")
    print("=" * 80)
    cap_rows = []
    for cap in [10, 15, 20]:
        for strat_name, e_type, param in [("Monthly EMA9", "monthly_ema", "m_ema9"), ("Weekly EMA20", "weekly_ema", "w_ema20")]:
            s, _, tr = simulate_low_maintenance_engine(
                signals_df, processed_stocks, nifty_regime_map,
                capacity=cap, exit_type=e_type, exit_param=param, cost_bps=25.0
            )
            cap_rows.append({
                "Strategy": strat_name,
                "Capacity": cap,
                "PerSlotAlloc": f"{100.0/cap:.1f}%",
                "CAGR": s["cagr"],
                "MaxDD": s["max_drawdown"],
                "ProfitFactor": s["profit_factor"],
                "WinRate": s["win_rate"],
                "Trades": s["num_trades"],
                "AvgTrade": s["avg_trade_ret"],
                "AvgExposure": s["avg_exposure_pct"],
                "Calmar": s["calmar"]
            })
            print(f"{strat_name:15s} [{cap:2d} slots] -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Exposure: {s['avg_exposure_pct']:5.1f}%")
    cap_df = pd.DataFrame(cap_rows)
    cap_df.to_csv(REPORTS_DIR / "gfs_capacity_sweep.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 14: MARKET REGIME ALLOCATION (SECTION 12)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 14: MARKET REGIME ALLOCATION (Schedule 1 vs Fixed 100%)")
    print("=" * 80)
    regime_rows = []
    for strat_name, e_type, param in [("Monthly EMA9", "monthly_ema", "m_ema9"), ("Monthly EMA12", "monthly_ema", "m_ema12"), ("Weekly EMA20", "weekly_ema", "w_ema20")]:
        for r_sch in ["fixed", "sch1"]:
            r_label = "Fixed 100% Exposure" if r_sch == "fixed" else "Regime Schedule 1 (100/70/30)"
            s, _, tr = simulate_low_maintenance_engine(
                signals_df, processed_stocks, nifty_regime_map,
                capacity=15, exit_type=e_type, exit_param=param, regime_schedule=r_sch, cost_bps=25.0
            )
            regime_rows.append({
                "Strategy": strat_name,
                "RegimeSchedule": r_label,
                "CAGR": s["cagr"],
                "MaxDD": s["max_drawdown"],
                "ProfitFactor": s["profit_factor"],
                "WinRate": s["win_rate"],
                "Trades": s["num_trades"],
                "AvgTrade": s["avg_trade_ret"],
                "AvgExposure": s["avg_exposure_pct"],
                "Calmar": s["calmar"]
            })
            print(f"{strat_name:15s} [{r_label[:20]:20s}] -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Calmar: {s['calmar']:5.3f}")
    regime_df = pd.DataFrame(regime_rows)
    regime_df.to_csv(REPORTS_DIR / "gfs_regime_sweep.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 15: TRANSACTION COST SENSITIVITY (25, 50, 100 bps) (SECTION 14)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 15: TRANSACTION COST SENSITIVITY (25, 50, 100 bps)")
    print("=" * 80)
    cost_strats = [
        ("Monthly EMA9", "monthly_ema", "m_ema9"),
        ("Monthly EMA12", "monthly_ema", "m_ema12"),
        ("Weekly EMA20", "weekly_ema", "w_ema20"),
        ("Fixed 120D Benchmark", "fixed_hold", "120D"),
        ("Baseline Daily Fast EMA21", "weekly_ema", "w_ema5")
    ]
    cost_rows = []
    for s_label, e_type, param in cost_strats:
        for c_bps in [25.0, 50.0, 100.0]:
            s, _, tr = simulate_low_maintenance_engine(
                signals_df, processed_stocks, nifty_regime_map,
                capacity=15, exit_type=e_type, exit_param=param, cost_bps=c_bps
            )
            cost_rows.append({
                "Strategy": s_label,
                "Cost_Bps": c_bps,
                "CAGR": s["cagr"],
                "MaxDD": s["max_drawdown"],
                "ProfitFactor": s["profit_factor"],
                "WinRate": s["win_rate"],
                "AvgTrade": s["avg_trade_ret"],
                "Expectancy": s["expectancy"],
                "EndingCapital": s["ending_capital"]
            })
            print(f"{s_label:26s} @ {c_bps:3.0f} bps -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f}")
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(REPORTS_DIR / "gfs_cost_sensitivity_low_maint.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 16: WALK-FORWARD VALIDATION (10 CANDIDATE SYSTEMS, 6 FOLDS) (SECTION 18)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 16: CHRONOLOGICAL WALK-FORWARD VALIDATION (10 SYSTEMS, 6 FOLDS)")
    print("=" * 80)
    wf_systems = [
        ("Weekly EMA9", "weekly_ema", "w_ema9"),
        ("Weekly EMA20", "weekly_ema", "w_ema20"),
        ("Monthly EMA9", "monthly_ema", "m_ema9"),
        ("Monthly EMA12", "monthly_ema", "m_ema12"),
        ("Monthly EMA20", "monthly_ema", "m_ema20"),
        ("Monthly RSI < 50", "monthly_rsi", "50"),
        ("Monthly RSI < 45", "monthly_rsi", "45"),
        ("Monthly EMA9 OR RSI < 50", "hybrid", "m_ema9_or_m_rsi50"),
        ("Monthly EMA12 OR RSI < 50", "hybrid", "m_ema12_or_m_rsi50"),
        ("Fixed 120D Benchmark", "fixed_hold", "120D"),
    ]
    folds = [
        ("Fold 1", "2018-01-01", "2020-12-31", "2021-01-01", "2021-12-31"),
        ("Fold 2", "2018-01-01", "2021-12-31", "2022-01-01", "2022-12-31"),
        ("Fold 3", "2018-01-01", "2022-12-31", "2023-01-01", "2023-12-31"),
        ("Fold 4", "2018-01-01", "2023-12-31", "2024-01-01", "2024-12-31"),
        ("Fold 5", "2018-01-01", "2024-12-31", "2025-01-01", "2025-12-31"),
        ("Fold 6", "2018-01-01", "2025-12-31", "2026-01-01", "2026-12-31"),
    ]
    wf_rows = []
    for f_name, train_s, train_e, test_s, test_e in folds:
        for s_label, e_type, param in wf_systems:
            s_train, _, _ = simulate_low_maintenance_engine(
                signals_df, processed_stocks, nifty_regime_map,
                capacity=15, exit_type=e_type, exit_param=param, cost_bps=25.0,
                start_date=train_s, end_date=train_e
            )
            s_test, _, _ = simulate_low_maintenance_engine(
                signals_df, processed_stocks, nifty_regime_map,
                capacity=15, exit_type=e_type, exit_param=param, cost_bps=25.0,
                start_date=test_s, end_date=test_e
            )
            wf_rows.append({
                "Fold": f_name,
                "Model": s_label,
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
            print(f"{f_name} [{s_label[:22]:22s}] -> Train: {s_train['cagr']:5.2f}% | Test Ret: {s_test['total_return_pct']:5.2f}%, Test MaxDD: {s_test['max_drawdown']:5.2f}%, Test PF: {s_test['profit_factor']:4.2f}")
    wf_df = pd.DataFrame(wf_rows)
    wf_df.to_csv(REPORTS_DIR / "gfs_walk_forward_low_maint.csv", index=False)

    # -------------------------------------------------------------------------
    # EXPERIMENT 17: MASTER FINAL STRATEGY COMPARISON TABLE (SECTION 17)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("EXPERIMENT 17: MASTER FINAL STRATEGY COMPARISON TABLE")
    print("=" * 80)
    master_list = [
        # Benchmarks:
        ("Fixed 60D Benchmark", "fixed_hold", "60D", None, "VERY LOW"),
        ("Fixed 120D Benchmark", "fixed_hold", "120D", None, "VERY LOW"),
        ("Fixed 180D Benchmark", "fixed_hold", "180D", None, "VERY LOW"),
        ("Fixed 252D (1-Year) Benchmark", "fixed_hold", "252D", None, "VERY LOW"),
        ("Fixed 504D (2-Year) Benchmark", "fixed_hold", "504D", None, "VERY LOW"),
        # Weekly EMAs:
        ("Weekly EMA5 Exit", "weekly_ema", "w_ema5", None, "WEEKLY"),
        ("Weekly EMA9 Exit", "weekly_ema", "w_ema9", None, "WEEKLY"),
        ("Weekly EMA12 Exit", "weekly_ema", "w_ema12", None, "WEEKLY"),
        ("Weekly EMA20 Exit", "weekly_ema", "w_ema20", None, "WEEKLY"),
        ("Weekly EMA26 Exit", "weekly_ema", "w_ema26", None, "WEEKLY"),
        # Monthly EMAs:
        ("Monthly EMA5 Exit", "monthly_ema", "m_ema5", None, "MONTHLY"),
        ("Monthly EMA9 Exit", "monthly_ema", "m_ema9", None, "MONTHLY"),
        ("Monthly EMA12 Exit", "monthly_ema", "m_ema12", None, "MONTHLY"),
        ("Monthly EMA20 Exit", "monthly_ema", "m_ema20", None, "MONTHLY"),
        # Weekly RSIs:
        ("Weekly RSI < 50 Exit", "weekly_rsi", "50", None, "WEEKLY"),
        ("Weekly RSI < 45 Exit", "weekly_rsi", "45", None, "WEEKLY"),
        # Monthly RSIs:
        ("Monthly RSI < 50 Exit", "monthly_rsi", "50", None, "MONTHLY"),
        ("Monthly RSI < 45 Exit", "monthly_rsi", "45", None, "MONTHLY"),
        # Price-Based:
        ("Weekly Close < Prev Week Low", "price_based", "weekly_prev_low", None, "WEEKLY"),
        ("Monthly Close < Prev Month Low", "price_based", "monthly_prev_low", None, "MONTHLY"),
        # Hybrids:
        ("Weekly EMA9 OR Weekly RSI < 50", "hybrid", "w_ema9_or_w_rsi50", None, "WEEKLY"),
        ("Weekly EMA20 OR Weekly RSI < 50", "hybrid", "w_ema20_or_w_rsi50", None, "WEEKLY"),
        ("Monthly EMA9 OR Monthly RSI < 50", "hybrid", "m_ema9_or_m_rsi50", None, "MONTHLY"),
        ("Monthly EMA12 OR Monthly RSI < 50", "hybrid", "m_ema12_or_m_rsi50", None, "MONTHLY"),
        ("Weekly EMA20 OR Monthly EMA9", "hybrid", "w_ema20_or_m_ema9", None, "WEEKLY"),
        # Catastrophic Stop protected versions:
        ("Monthly EMA9 (-20% Cat Stop)", "monthly_ema", "m_ema9", -0.20, "MONTHLY"),
        ("Monthly EMA12 (-20% Cat Stop)", "monthly_ema", "m_ema12", -0.20, "MONTHLY"),
        ("Weekly EMA20 (-15% Cat Stop)", "weekly_ema", "w_ema20", -0.15, "WEEKLY"),
        ("Monthly EMA9 + Regime Sch 1", "monthly_ema", "m_ema9", -0.20, "MONTHLY"),
    ]

    master_rows = []
    master_trades_export = []
    for label, e_type, param, c_stop, burden in master_list:
        r_sch = "sch1" if "Regime" in label else "fixed"
        s25, _, tr25 = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type=e_type, exit_param=param, cat_stop_pct=c_stop, regime_schedule=r_sch, cost_bps=25.0
        )
        s50, _, _ = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type=e_type, exit_param=param, cat_stop_pct=c_stop, regime_schedule=r_sch, cost_bps=50.0
        )
        s100, _, _ = simulate_low_maintenance_engine(
            signals_df, processed_stocks, nifty_regime_map,
            capacity=15, exit_type=e_type, exit_param=param, cat_stop_pct=c_stop, regime_schedule=r_sch, cost_bps=100.0
        )

        if label in ["Monthly EMA9 Exit", "Weekly EMA20 Exit", "Monthly EMA9 (-20% Cat Stop)", "Fixed 120D Benchmark"]:
            tr_save = tr25.copy()
            tr_save["strategy"] = label
            master_trades_export.append(tr_save)

        master_rows.append({
            "Strategy": label,
            "Entry": "Monthly RSI>60, Weekly RSI>60, Daily RSI cross 40",
            "Exit": param if c_stop is None else f"{param} + {int(c_stop*100)}% stop",
            "CAGR": s25["cagr"],
            "MaxDD": s25["max_drawdown"],
            "ProfitFactor": s25["profit_factor"],
            "WinRate": s25["win_rate"],
            "AvgTrade": s25["avg_trade_ret"],
            "MedianTrade": s25["median_trade_ret"],
            "AvgHoldDays": s25["avg_holding_days"],
            "MedianHoldDays": s25["median_holding_days"],
            "MaxHoldDays": s25["max_holding_days"],
            "Turnover": s25["annual_turnover"],
            "W50": s25["w50"],
            "W100": s25["w100"],
            "W200": s25["w200"],
            "W500": s25["w500"],
            "MaxWinner": s25["max_winner"],
            "CAGR_25bps": s25["cagr"],
            "CAGR_50bps": s50["cagr"],
            "CAGR_100bps": s100["cagr"],
            "MonitoringBurden": burden
        })
        print(f"{label:36s} -> CAGR: {s25['cagr']:6.2f}% | MaxDD: {s25['max_drawdown']:6.2f}% | PF: {s25['profit_factor']:5.2f} | Hold: {s25['avg_holding_days']:5.1f}d | W100: {s25['w100']:2d} | 50bps: {s50['cagr']:5.2f}% | Burden: {burden}")

    master_df = pd.DataFrame(master_rows)
    master_df.to_csv(REPORTS_DIR / "gfs_master_exit_comparison.csv", index=False)

    if master_trades_export:
        all_trades_df = pd.concat(master_trades_export, ignore_index=True)
        all_trades_df.to_csv(REPORTS_DIR / "gfs_low_maint_sample_trades.csv", index=False)

    # Save summary tables to SQLite for full reproducibility
    conn = sqlite3.connect(DB_PATH)
    master_df.to_sql("gfs_low_maintenance_master", conn, if_exists="replace", index=False)
    wf_df.to_sql("gfs_low_maintenance_walkforward", conn, if_exists="replace", index=False)
    conn.close()

    print("\n" + "=" * 80)
    print("ALL LOW-MAINTENANCE GFS EXPERIMENTS COMPLETED SUCCESSFULLY!")
    print("=" * 80)

if __name__ == "__main__":
    run_all_experiments()
