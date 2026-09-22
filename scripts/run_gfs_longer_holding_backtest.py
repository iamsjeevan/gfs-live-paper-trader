"""
GFS 60/65/70 THRESHOLD + LONGER-HOLDING + ADAPTIVE EXIT BACKTEST
Comprehensive Quantitative Research Engine for Indian Equities (2018-2026).

Mandated Research Questions:
1. Higher-Timeframe RSI Thresholds: 60/60 vs 65/65 vs 70/70 and Asymmetric (70/60, 60/70, 70/65, 65/70)
2. Longer Holding Periods: Fixed 20D, 40D, 60D, 90D, 120D, 180D
3. Catastrophic Protection Sweep: -5%, -7%, -8%, -10%, -12%, -15%
4. MAE / MFE Distribution Analysis & Empirical Noise Boundaries
5. "Let Winners Run" Delayed EMA21 Trailing Matrix (-7% to -12% stop x +5% to +20% activation)
6. Profit-Locking Step Trailing Stops (-10% initial -> -2% -> +5% -> +10% -> +20%)
7. Peak Drawdown (Chandelier) Exits (-10%, -15%, -20%, -25% from peak)
8. Hybrid Exit Systems A through I
9. Large Winner Analysis (+10% to +300%)
10. Expectancy & Win/Loss Tradeoff Analysis
11. Portfolio Capacity (5, 10, 15, 20, 30 slots)
12. Market Regime (Schedule 1 vs 100% Fixed) & Sector Concentration (None, 25%, 33%)
13. Transaction Cost Sensitivity (0, 25, 50, 100 bps)
14. Expanding Walk-Forward OOS Validation (6 folds)
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

def load_data_and_precompute():
    print("=" * 80)
    print("STEP 1: LOADING DATA & PRECOMPUTING INDICATORS ACROSS UNIVERSE")
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

def generate_signals_all_thresholds(daily_df, sec_info, sector_map):
    print("\n" + "=" * 80)
    print("STEP 2: SCANNING STOCKS & GENERATING THRESHOLD-TAGGED SIGNALS")
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

        c = g["close"]
        g["daily_rsi"] = compute_rsi(c, 14)
        g["prev_daily_rsi"] = g["daily_rsi"].shift(1)
        g["daily_ema21"] = compute_ema(c, 21)

        # Weekly RSI completed
        w_df = g.groupby("year_week")["close"].last().reset_index()
        w_df["weekly_rsi"] = compute_rsi(w_df["close"], 14).shift(1)
        w_map = dict(zip(w_df["year_week"], w_df["weekly_rsi"]))
        g["weekly_rsi_completed"] = g["year_week"].map(w_map)

        # Monthly RSI completed
        m_df = g.groupby("year_month")["close"].last().reset_index()
        m_df["monthly_rsi"] = compute_rsi(m_df["close"], 14).shift(1)
        m_map = dict(zip(m_df["year_month"], m_df["monthly_rsi"]))
        g["monthly_rsi_completed"] = g["year_month"].map(m_map)

        # Next-day open
        g["entry_date"] = g["date"].shift(-1)
        g["entry_open"] = g["open"].shift(-1)

        processed_stocks[sym] = g

        # Daily trigger: prev <= 40 and curr > 40
        son_cross = (g["prev_daily_rsi"] <= 40.0) & (g["daily_rsi"] > 40.0) & (g["entry_date"].notna())
        base_valid = son_cross & (g["weekly_rsi_completed"] > 60.0) & (g["monthly_rsi_completed"] > 60.0)

        sig_rows = g[base_valid]
        for _, row in sig_rows.iterrows():
            w_r = row["weekly_rsi_completed"]
            m_r = row["monthly_rsi_completed"]

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
                "weekly_rsi": w_r,
                "monthly_rsi": m_r,
                "daily_ema21": row["daily_ema21"],
                # Threshold flags
                "is_60_60": True,
                "is_65_65": (m_r > 65.0) and (w_r > 65.0),
                "is_70_70": (m_r > 70.0) and (w_r > 70.0),
                "is_70_60": (m_r > 70.0) and (w_r > 60.0),
                "is_60_70": (m_r > 60.0) and (w_r > 70.0),
                "is_70_65": (m_r > 70.0) and (w_r > 65.0),
                "is_65_70": (m_r > 65.0) and (w_r > 70.0),
            })

    signals_df = pd.DataFrame(all_signals).sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    print(f"Generated signals across universe in {time.time()-t0:.2f}s.")
    print("Signal Counts:")
    for tag in ["60_60", "65_65", "70_70", "70_60", "60_70", "70_65", "65_70"]:
        print(f"  {tag:8s}: {signals_df['is_' + tag].sum():,} signals")

    return signals_df, processed_stocks

def simulate_long_hold_engine(
    signals_subset,
    processed_stocks,
    nifty_regime_map,
    capacity: int = 15,
    sector_cap_pct: float = None,
    regime_schedule: str = "fixed", # 'fixed' or 'sch1' (100/70/30)
    # Exit configuration:
    exit_model: str = "fixed_hold", # 'fixed_hold', 'catastrophic_stop', 'delayed_ema21', 'profit_locking', 'peak_drawdown', 'hybrid'
    hold_days: int = 60,
    cat_stop_pct: float = -0.10, # e.g. -0.05 to -0.15
    activation_pct: float = 0.10, # +0.05 to +0.20 for delayed EMA21
    profit_locking: bool = False,
    peak_dd_pct: float = None, # e.g. 0.15 for -15% from high
    cost_bps: float = 25.0,
    start_date: str = "2018-01-01",
    end_date: str = "2026-12-31"
):
    """Universal long-holding & adaptive exit simulation engine."""
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

    all_dates = sorted(list(set(d for df in processed_stocks.values() for d in df["date"] if start_date <= d <= end_date)))

    cash = STARTING_CAPITAL
    open_positions = {}
    closed_trades = []
    daily_stats = []

    for d_idx, d in enumerate(all_dates):
        # 1. Process Open Exits & Pending Exits
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

            # Track MFE / MAE
            high_gain = (hp - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0
            low_loss = (lp - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0
            pos["max_favorable_pct"] = max(pos["max_favorable_pct"], high_gain)
            pos["max_adverse_pct"] = min(pos["max_adverse_pct"], low_loss)
            pos["highest_price"] = max(pos["highest_price"], hp)

            # A. Execute Pending Exit from Yesterday's Close Trigger
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

            # B. Check Stop-Loss Gap Down at Today's Open (if stop active)
            # Current dynamic stop price
            current_stop_price = pos["stop_price"]
            if current_stop_price is not None and not pos["trailing_active"]:
                if op <= current_stop_price:
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
            # Candidates filtering
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

                # Neutral selection (no momentum ranking)
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
                        act_p = (raw_entry_p * (1.0 + activation_pct)) if activation_pct is not None else None

                        open_positions[s_sym] = {
                            "symbol": s_sym,
                            "sector": sec,
                            "entry_date": d,
                            "sim_entry_price": sim_entry_p,
                            "raw_entry_price": raw_entry_p,
                            "shares": shares,
                            "last_close": raw_entry_p,
                            "stop_price": initial_stop,
                            "act_price": act_p,
                            "trailing_active": False,
                            "holding_days": 0,
                            "max_favorable_pct": 0.0,
                            "max_adverse_pct": 0.0,
                            "highest_price": raw_entry_p,
                            "pending_exit": False,
                            "pending_exit_reason": ""
                        }

        # 4. Intraday Checks & End of Day Exit Conditions
        to_close_intraday = []
        for sym, pos in open_positions.items():
            df_sym = processed_stocks[sym]
            row_d = df_sym[df_sym["date"] == d]
            if row_d.empty:
                continue
            r = row_d.iloc[0]
            op, hp, lp, cp = r["open"], r["high"], r["low"], r["close"]
            pos["last_close"] = cp
            high_gain = (hp - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0
            low_loss = (lp - pos["raw_entry_price"]) / pos["raw_entry_price"] * 100.0
            pos["max_favorable_pct"] = max(pos["max_favorable_pct"], high_gain)
            pos["max_adverse_pct"] = min(pos["max_adverse_pct"], low_loss)
            pos["highest_price"] = max(pos["highest_price"], hp)

            # Profit Locking Step Adjustments
            if profit_locking and pos["raw_entry_price"] > 0:
                cur_gain = pos["max_favorable_pct"]
                if cur_gain >= 50.0:
                    pos["stop_price"] = max(pos["stop_price"] or 0, pos["raw_entry_price"] * 1.20)
                elif cur_gain >= 30.0:
                    pos["stop_price"] = max(pos["stop_price"] or 0, pos["raw_entry_price"] * 1.10)
                elif cur_gain >= 20.0:
                    pos["stop_price"] = max(pos["stop_price"] or 0, pos["raw_entry_price"] * 1.05)
                elif cur_gain >= 10.0:
                    pos["stop_price"] = max(pos["stop_price"] or 0, pos["raw_entry_price"] * 0.98) # -2% from entry

            # Intraday Catastrophic Stop Loss Check
            cur_stop = pos["stop_price"]
            if cur_stop is not None and not pos["trailing_active"]:
                if lp <= cur_stop:
                    exit_price = cur_stop * cost_mult_exit
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
                        "raw_exit_price": cur_stop,
                        "return_pct": ret_pct,
                        "holding_days": pos["holding_days"],
                        "exit_reason": "STOP_LOSS_INTRADAY",
                        "max_favorable_pct": pos["max_favorable_pct"],
                        "max_adverse_pct": pos["max_adverse_pct"],
                        "gap_down": False
                    })
                    to_close_intraday.append(sym)
                    continue

            # Check Activation for Delayed EMA21
            if pos["act_price"] is not None and not pos["trailing_active"]:
                if hp >= pos["act_price"]:
                    pos["trailing_active"] = True

            # End of Day Exit Triggers (to execute tomorrow open)
            # A. Fixed Holding Period Exits
            if exit_model == "fixed_hold":
                if pos["holding_days"] >= hold_days:
                    pos["pending_exit"] = True
                    pos["pending_exit_reason"] = f"FIXED_{hold_days}D"

            # B. Catastrophic Stop + Fixed Max Hold (Hybrid D)
            elif exit_model == "stop_and_hold":
                if pos["holding_days"] >= hold_days:
                    pos["pending_exit"] = True
                    pos["pending_exit_reason"] = f"MAX_HOLD_{hold_days}D"

            # C. Delayed EMA21 Trailing Exits (Systems E, F, G, H, I)
            elif exit_model in ("delayed_ema21", "hybrid"):
                if pos["trailing_active"]:
                    ema21 = r["daily_ema21"]
                    if cp < ema21:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = "DAILY_CLOSE_BELOW_EMA21"
                # Optional max holding cap
                if hold_days and pos["holding_days"] >= hold_days:
                    pos["pending_exit"] = True
                    pos["pending_exit_reason"] = f"MAX_HOLD_{hold_days}D"

            # D. Peak Drawdown (Chandelier) Stop
            elif exit_model == "peak_drawdown":
                if peak_dd_pct is not None and pos["highest_price"] > pos["raw_entry_price"]:
                    trailing_floor = pos["highest_price"] * (1.0 - peak_dd_pct)
                    if cp < trailing_floor:
                        pos["pending_exit"] = True
                        pos["pending_exit_reason"] = f"PEAK_DD_{int(peak_dd_pct*100)}PCT"

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

    # Close any open positions at final bar
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
                "max_favorable_pct": pos["max_favorable_pct"],
                "max_adverse_pct": pos["max_adverse_pct"],
                "gap_down": False
            })

    daily_df_res = pd.DataFrame(daily_stats)
    trades_df_res = pd.DataFrame(closed_trades)
    summary = compute_metrics(daily_df_res, trades_df_res, STARTING_CAPITAL)
    return summary, daily_df_res, trades_df_res

def compute_metrics(daily_df, trades_df, starting_capital=1_000_000.0):
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

    daily_ret = eq.pct_change().dropna()
    vol_ann = daily_ret.std() * np.sqrt(252) * 100.0 if len(daily_ret) > 1 else 0.0
    sharpe = (cagr - 6.0) / vol_ann if vol_ann > 1e-4 else 0.0
    calmar = abs(cagr / max_dd) if abs(max_dd) > 1e-4 else 0.0

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

        loss_rate = 1.0 - (win_rate / 100.0)
        expectancy = ((win_rate / 100.0) * avg_win) - (loss_rate * abs(avg_loss))
        avg_hold = trades_df["holding_days"].mean()
        turnover = (n_trades * 2.0) / n_years

        # Large winner counts
        w10 = (trades_df["return_pct"] >= 10.0).sum()
        w20 = (trades_df["return_pct"] >= 20.0).sum()
        w30 = (trades_df["return_pct"] >= 30.0).sum()
        w50 = (trades_df["return_pct"] >= 50.0).sum()
        w75 = (trades_df["return_pct"] >= 75.0).sum()
        w100 = (trades_df["return_pct"] >= 100.0).sum()
        w150 = (trades_df["return_pct"] >= 150.0).sum()
        w200 = (trades_df["return_pct"] >= 200.0).sum()
        w300 = (trades_df["return_pct"] >= 300.0).sum()
        max_winner = trades_df["return_pct"].max()
        worst_loss = trades_df["return_pct"].min()
    else:
        win_rate = avg_ret = med_ret = profit_factor = avg_win = avg_loss = win_loss_ratio = expectancy = avg_hold = turnover = 0.0
        w10 = w20 = w30 = w50 = w75 = w100 = w150 = w200 = w300 = max_winner = worst_loss = 0.0

    avg_exp = daily_df["exposure_pct"].mean()
    avg_cash = 100.0 - avg_exp

    return {
        "starting_capital": starting_capital,
        "ending_capital": ending_val,
        "total_return_pct": total_ret_pct,
        "cagr": cagr,
        "max_drawdown": max_dd,
        "avg_drawdown": avg_dd,
        "volatility_ann": vol_ann,
        "sharpe": sharpe,
        "calmar": calmar,
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
        "w10": w10,
        "w20": w20,
        "w30": w30,
        "w50": w50,
        "w75": w75,
        "w100": w100,
        "w150": w150,
        "w200": w200,
        "w300": w300,
        "max_winner": max_winner,
        "worst_loss": worst_loss
    }

def run_research():
    daily_df, nifty_df, sec_info, sector_map, nifty_regime_map = load_data_and_precompute()
    signals_df, processed_stocks = generate_signals_all_thresholds(daily_df, sec_info, sector_map)

    # -------------------------------------------------------------------------
    # STAGE 1: RSI 60 vs 65 vs 70 (and Asymmetric Combinations)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 1: HIGHER-TIMEFRAME RSI THRESHOLD COMPARISON (Fixed 60D Hold)")
    print("=" * 80)
    combos = [
        ("SET A: 60/60 (Symmetric)", "is_60_60"),
        ("SET B: 65/65 (Symmetric)", "is_65_65"),
        ("SET C: 70/70 (Symmetric)", "is_70_70"),
        ("Asym 70/60 (Monthly 70 / Weekly 60)", "is_70_60"),
        ("Asym 60/70 (Monthly 60 / Weekly 70)", "is_60_70"),
        ("Asym 70/65 (Monthly 70 / Weekly 65)", "is_70_65"),
        ("Asym 65/70 (Monthly 65 / Weekly 70)", "is_65_70")
    ]
    rsi_rows = []
    for label, mask_col in combos:
        sig_sub = signals_df[signals_df[mask_col]].copy()
        s, _, tr = simulate_long_hold_engine(
            sig_sub, processed_stocks, nifty_regime_map,
            capacity=15, exit_model="fixed_hold", hold_days=60, cost_bps=25.0
        )
        rsi_rows.append({
            "Threshold_Set": label,
            "Total_Signals": len(sig_sub),
            "Trades_Taken": s["num_trades"],
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "AvgWin": s["avg_win"],
            "AvgLoss": s["avg_loss"],
            "Expectancy": s["expectancy"],
            "Winners_GT_50pct": s["w50"],
            "Winners_GT_100pct": s["w100"],
            "AvgExposure": s["avg_exposure_pct"]
        })
        print(f"{label:40s} -> Signals: {len(sig_sub):5,d} | CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | >50% Wins: {s['w50']:3d}")
    rsi_df = pd.DataFrame(rsi_rows)
    rsi_df.to_csv(REPORTS_DIR / "gfs_rsi_threshold_comparison.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 2: LONGER HOLDING PERIODS (20D, 40D, 60D, 90D, 120D, 180D)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 2: LONGER HOLDING PERIOD SWEEP (GFS 60/60 Baseline)")
    print("=" * 80)
    hold_periods = [20, 40, 60, 90, 120, 180]
    hold_rows = []
    sig_60 = signals_df[signals_df["is_60_60"]].copy()
    for h in hold_periods:
        s, _, tr = simulate_long_hold_engine(
            sig_60, processed_stocks, nifty_regime_map,
            capacity=15, exit_model="fixed_hold", hold_days=h, cost_bps=25.0
        )
        hold_rows.append({
            "Holding_Period_Days": h,
            "CAGR": s["cagr"],
            "Total_Return_Pct": s["total_return_pct"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "NumTrades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "Expectancy": s["expectancy"],
            "AvgWin": s["avg_win"],
            "AvgLoss": s["avg_loss"],
            "WinLossRatio": s["win_loss_ratio"],
            "Turnover": s["annual_turnover"],
            "AvgExposure": s["avg_exposure_pct"],
            "W50": s["w50"],
            "W100": s["w100"],
            "MaxWinner": s["max_winner"]
        })
        print(f"Fixed {h:3d} Trading Days -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | WinRate: {s['win_rate']:5.1f}% | AvgTrade: {s['avg_trade_ret']:5.2f}% | >50% Wins: {s['w50']:3d}")
    hold_df = pd.DataFrame(hold_rows)
    hold_df.to_csv(REPORTS_DIR / "gfs_holding_period_sweep.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 3 & 4: MAE / MFE DISTRIBUTION ANALYSIS
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 3 & 4: MAE & MFE DISTRIBUTION ANALYSIS (Across 90D Window)")
    print("=" * 80)
    # Run a 90-day hold to observe full adverse and favorable excursion paths
    _, _, tr_90 = simulate_long_hold_engine(
        sig_60, processed_stocks, nifty_regime_map,
        capacity=15, exit_model="fixed_hold", hold_days=90, cost_bps=25.0
    )
    maes = tr_90["max_adverse_pct"].values # all negative values
    mfes = tr_90["max_favorable_pct"].values

    mae_pctiles = np.percentile(maes, [5, 10, 25, 50, 75, 90, 95])
    mfe_pctiles = np.percentile(mfes, [5, 10, 25, 50, 75, 90, 95])

    mae_mfe_summary = pd.DataFrame([
        {"Excursion": "MAE (Max Adverse Excursion %)", "P5": mae_pctiles[0], "P10": mae_pctiles[1], "P25": mae_pctiles[2], "P50_Median": mae_pctiles[3], "P75": mae_pctiles[4], "P90": mae_pctiles[5], "P95": mae_pctiles[6]},
        {"Excursion": "MFE (Max Favorable Excursion %)", "P5": mfe_pctiles[0], "P10": mfe_pctiles[1], "P25": mfe_pctiles[2], "P50_Median": mfe_pctiles[3], "P75": mfe_pctiles[4], "P90": mfe_pctiles[5], "P95": mfe_pctiles[6]}
    ])
    mae_mfe_summary.to_csv(REPORTS_DIR / "gfs_mae_mfe_distribution.csv", index=False)
    print("MAE Percentiles (Drawdown from entry):")
    print(f"  P10: {mae_pctiles[1]:.2f}% | P25: {mae_pctiles[2]:.2f}% | Median (P50): {mae_pctiles[3]:.2f}% | P75: {mae_pctiles[4]:.2f}% | P90: {mae_pctiles[5]:.2f}%")

    # -------------------------------------------------------------------------
    # STAGE 5: CATASTROPHIC STOP-LOSS SWEEP (-5%, -7%, -8%, -10%, -12%, -15%)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 5: CATASTROPHIC STOP-LOSS SWEEP (With 90D Max Hold)")
    print("=" * 80)
    stops = [-0.05, -0.07, -0.08, -0.10, -0.12, -0.15]
    stop_rows = []
    tradeoff_rows = []
    for st in stops:
        st_pct_label = f"{int(st*100)}%"
        s, _, tr = simulate_long_hold_engine(
            sig_60, processed_stocks, nifty_regime_map,
            capacity=15, exit_model="stop_and_hold", hold_days=90, cat_stop_pct=st, cost_bps=25.0
        )
        stopped_out = tr[tr["exit_reason"].str.contains("STOP_LOSS")]
        n_stopped = len(stopped_out)
        pct_stopped = (n_stopped / len(tr) * 100.0) if len(tr) > 0 else 0.0

        # Check how many trades would have been positive at 90D if not stopped
        # Compare against tr_90
        cut_winners = 0
        for _, str_row in stopped_out.iterrows():
            sym_s = str_row["symbol"]
            e_d = str_row["entry_date"]
            match_90 = tr_90[(tr_90["symbol"] == sym_s) & (tr_90["entry_date"] == e_d)]
            if not match_90.empty:
                if match_90["return_pct"].iloc[0] > 0:
                    cut_winners += 1

        stop_rows.append({
            "Stop_Level": st_pct_label,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "Trades_Stopped_Out": n_stopped,
            "Pct_Stopped_Out": pct_stopped,
            "Cut_Winners_Count": cut_winners,
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "Expectancy": s["expectancy"],
            "W50": s["w50"],
            "W100": s["w100"],
            "AvgWin": s["avg_win"],
            "AvgLoss": s["avg_loss"]
        })

        tradeoff_rows.append({
            "Stop_Level": st_pct_label,
            "AvgLoss": s["avg_loss"],
            "WorstLoss": s["worst_loss"],
            "AvgWinner": s["avg_win"],
            "LargestWinner": s["max_winner"],
            "ProfitFactor": s["profit_factor"],
            "CAGR": s["cagr"],
            "MaxDrawdown": s["max_drawdown"],
            "Trades_Stopped": n_stopped,
            "Winners_Cut_Prematurely": cut_winners
        })
        print(f"Stop {st_pct_label:5s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Stopped: {n_stopped:3d} ({pct_stopped:4.1f}%) | Winners Cut: {cut_winners:3d}")

    stop_df = pd.DataFrame(stop_rows)
    stop_df.to_csv(REPORTS_DIR / "gfs_stop_loss_sweep.csv", index=False)
    tradeoff_df = pd.DataFrame(tradeoff_rows)
    tradeoff_df.to_csv(REPORTS_DIR / "gfs_risk_reward_tradeoff.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 6: "LET WINNERS RUN" DELAYED EMA21 TRAILING MATRIX
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 6: 'LET WINNERS RUN' DELAYED EMA21 TRAILING MATRIX")
    print("=" * 80)
    delayed_rows = []
    for st in [-0.07, -0.08, -0.10, -0.12]:
        for act in [0.05, 0.10, 0.15, 0.20]:
            label = f"Stop {int(st*100)}% / Act +{int(act*100)}%"
            s, _, tr = simulate_long_hold_engine(
                sig_60, processed_stocks, nifty_regime_map,
                capacity=15, exit_model="delayed_ema21", cat_stop_pct=st, activation_pct=act,
                hold_days=None, cost_bps=25.0
            )
            delayed_rows.append({
                "Configuration": label,
                "Catastrophic_Stop": f"{int(st*100)}%",
                "Activation_Threshold": f"+{int(act*100)}%",
                "CAGR": s["cagr"],
                "MaxDD": s["max_drawdown"],
                "ProfitFactor": s["profit_factor"],
                "WinRate": s["win_rate"],
                "Trades": s["num_trades"],
                "AvgTrade": s["avg_trade_ret"],
                "MedianTrade": s["median_trade_ret"],
                "Expectancy": s["expectancy"],
                "AvgHoldDays": s["avg_holding_days"],
                "W50": s["w50"],
                "W100": s["w100"],
                "MaxWinner": s["max_winner"]
            })
            print(f"{label:30s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Hold: {s['avg_holding_days']:4.1f}d | W50: {s['w50']:2d}")
    delayed_df = pd.DataFrame(delayed_rows)
    delayed_df.to_csv(REPORTS_DIR / "gfs_delayed_ema21_matrix.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 7: PROFIT-LOCKING (STEP TRAILING STOPS)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 7: PROFIT-LOCKING STEP TRAILING STOPS")
    print("=" * 80)
    profit_lock_tests = [
        ("No Profit Lock (Fixed Stop -10% + EMA21 after +10%)", -0.10, 0.10, False),
        ("Step Profit Lock (-10% -> -2% -> +5% -> +10% -> +20%) + EMA21", -0.10, 0.10, True),
        ("No Profit Lock (Fixed Stop -12% + EMA21 after +10%)", -0.12, 0.10, False),
        ("Step Profit Lock (-12% -> -2% -> +5% -> +10% -> +20%) + EMA21", -0.12, 0.10, True),
    ]
    pl_rows = []
    for label, st, act, pl_flag in profit_lock_tests:
        s, _, tr = simulate_long_hold_engine(
            sig_60, processed_stocks, nifty_regime_map,
            capacity=15, exit_model="delayed_ema21", cat_stop_pct=st, activation_pct=act,
            profit_locking=pl_flag, hold_days=None, cost_bps=25.0
        )
        pl_rows.append({
            "Strategy": label,
            "Profit_Locking_Active": pl_flag,
            "Initial_Stop": f"{int(st*100)}%",
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
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:55s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f}")
    pl_df = pd.DataFrame(pl_rows)
    pl_df.to_csv(REPORTS_DIR / "gfs_profit_locking_comparison.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 8: PEAK DRAWDOWN (CHANDELIER) EXITS (-10%, -15%, -20%, -25% from peak)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 8: PEAK DRAWDOWN (CHANDELIER) EXITS")
    print("=" * 80)
    peak_rows = []
    for p_dd in [0.10, 0.15, 0.20, 0.25]:
        p_label = f"Trail -{int(p_dd*100)}% from Peak High"
        s, _, tr = simulate_long_hold_engine(
            sig_60, processed_stocks, nifty_regime_map,
            capacity=15, exit_model="peak_drawdown", cat_stop_pct=-0.10, peak_dd_pct=p_dd,
            cost_bps=25.0
        )
        peak_rows.append({
            "Peak_Drawdown_Stop": p_label,
            "Trailing_Drop_Pct": f"{int(p_dd*100)}%",
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
            "MaxWinner": s["max_winner"]
        })
        print(f"{p_label:35s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Hold: {s['avg_holding_days']:4.1f}d")
    peak_df = pd.DataFrame(peak_rows)
    peak_df.to_csv(REPORTS_DIR / "gfs_peak_drawdown_exits.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 9: HYBRID EXIT SYSTEMS (SYSTEMS A THROUGH I)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 9: HYBRID EXIT SYSTEMS COMPARISON (SYSTEMS A THROUGH I)")
    print("=" * 80)
    hybrid_defs = [
        ("SYSTEM A: Fixed 60D", "fixed_hold", 60, None, None, False),
        ("SYSTEM B: Fixed 90D", "fixed_hold", 90, None, None, False),
        ("SYSTEM C: Fixed 120D", "fixed_hold", 120, None, None, False),
        ("SYSTEM D: -10% Stop + 90D Max Hold", "stop_and_hold", 90, -0.10, None, False),
        ("SYSTEM E: -10% Stop + EMA21 after +10%", "delayed_ema21", None, -0.10, 0.10, False),
        ("SYSTEM F: -10% Stop + EMA21 after +20%", "delayed_ema21", None, -0.10, 0.20, False),
        ("SYSTEM G: -12% Stop + EMA21 after +10%", "delayed_ema21", None, -0.12, 0.10, False),
        ("SYSTEM H: -10% Stop + Profit Lock + EMA21 after +10%", "delayed_ema21", None, -0.10, 0.10, True),
        ("SYSTEM I: -10% Stop + EMA21 only after +20%", "delayed_ema21", None, -0.10, 0.20, False),
    ]
    hybrid_rows = []
    large_winner_rows = []
    for label, e_mod, h_days, c_stop, act, pl in hybrid_defs:
        s, _, tr = simulate_long_hold_engine(
            sig_60, processed_stocks, nifty_regime_map,
            capacity=15, exit_model=e_mod, hold_days=h_days, cat_stop_pct=c_stop,
            activation_pct=act, profit_locking=pl, cost_bps=25.0
        )
        hybrid_rows.append({
            "System": label,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "AvgWin": s["avg_win"],
            "AvgLoss": s["avg_loss"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "Turnover": s["annual_turnover"],
            "AvgExposure": s["avg_exposure_pct"],
            "W50": s["w50"],
            "W100": s["w100"],
            "MaxWinner": s["max_winner"]
        })

        n_tr = s["num_trades"]
        large_winner_rows.append({
            "System": label,
            "TotalTrades": n_tr,
            "W10": s["w10"], "Pct10": (s["w10"]/n_tr*100) if n_tr>0 else 0,
            "W20": s["w20"], "Pct20": (s["w20"]/n_tr*100) if n_tr>0 else 0,
            "W30": s["w30"], "Pct30": (s["w30"]/n_tr*100) if n_tr>0 else 0,
            "W50": s["w50"], "Pct50": (s["w50"]/n_tr*100) if n_tr>0 else 0,
            "W75": s["w75"], "Pct75": (s["w75"]/n_tr*100) if n_tr>0 else 0,
            "W100": s["w100"], "Pct100": (s["w100"]/n_tr*100) if n_tr>0 else 0,
            "W150": s["w150"], "Pct150": (s["w150"]/n_tr*100) if n_tr>0 else 0,
            "W200": s["w200"], "Pct200": (s["w200"]/n_tr*100) if n_tr>0 else 0,
            "W300": s["w300"], "Pct300": (s["w300"]/n_tr*100) if n_tr>0 else 0,
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:55s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Exp: {s['expectancy']:5.2f}% | >50%: {s['w50']:2d}")

    hybrid_df = pd.DataFrame(hybrid_rows)
    hybrid_df.to_csv(REPORTS_DIR / "gfs_hybrid_systems_comparison.csv", index=False)
    large_w_df = pd.DataFrame(large_winner_rows)
    large_w_df.to_csv(REPORTS_DIR / "gfs_large_winners_distribution.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 10: PORTFOLIO CAPACITY SWEEP (Under System E: -10% stop + EMA21 after +10%)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 10: PORTFOLIO CAPACITY SWEEP (System E)")
    print("=" * 80)
    cap_rows = []
    for cap in [5, 10, 15, 20, 30]:
        s, _, _ = simulate_long_hold_engine(
            sig_60, processed_stocks, nifty_regime_map,
            capacity=cap, exit_model="delayed_ema21", cat_stop_pct=-0.10, activation_pct=0.10,
            cost_bps=25.0
        )
        cap_rows.append({
            "Capacity": cap,
            "Slot_Allocation_Pct": 100.0 / cap,
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "AvgExposure": s["avg_exposure_pct"],
            "Calmar": s["calmar"]
        })
        print(f"Capacity {cap:2d} slots -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Exposure: {s['avg_exposure_pct']:5.1f}%")
    cap_df = pd.DataFrame(cap_rows)
    cap_df.to_csv(REPORTS_DIR / "gfs_capacity_long_hold.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 11: MARKET REGIME & SECTOR CONCENTRATION
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 11: MARKET REGIME & SECTOR CONCENTRATION (System E)")
    print("=" * 80)
    reg_sec_tests = [
        ("System E: Fixed Exposure (100%), No Sector Cap", "fixed", None),
        ("System E: Fixed Exposure (100%), Sector Cap 25%", "fixed", 0.25),
        ("System E: Fixed Exposure (100%), Sector Cap 33%", "fixed", 0.33),
        ("System E: Regime Schedule 1, No Sector Cap", "sch1", None),
        ("System E: Regime Schedule 1, Sector Cap 25%", "sch1", 0.25),
        ("System E: Regime Schedule 1, Sector Cap 33%", "sch1", 0.33),
    ]
    reg_sec_rows = []
    for label, r_sch, s_cap in reg_sec_tests:
        s, _, _ = simulate_long_hold_engine(
            sig_60, processed_stocks, nifty_regime_map,
            capacity=15, exit_model="delayed_ema21", cat_stop_pct=-0.10, activation_pct=0.10,
            regime_schedule=r_sch, sector_cap_pct=s_cap, cost_bps=25.0
        )
        reg_sec_rows.append({
            "Configuration": label,
            "Regime_Schedule": r_sch,
            "Sector_Cap": s_cap if s_cap else "None",
            "CAGR": s["cagr"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "Trades": s["num_trades"],
            "AvgTrade": s["avg_trade_ret"],
            "AvgExposure": s["avg_exposure_pct"],
            "Calmar": s["calmar"]
        })
        print(f"{label:55s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Calmar: {s['calmar']:.3f}")
    reg_sec_df = pd.DataFrame(reg_sec_rows)
    reg_sec_df.to_csv(REPORTS_DIR / "gfs_regime_sector_comparison.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 12: TRANSACTION COST SENSITIVITY (0, 25, 50, 100 bps)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 12: TRANSACTION COST SENSITIVITY")
    print("=" * 80)
    cost_rows = []
    tested_strats = [
        ("Baseline GFS (-5% stop -> fast EMA21)", "delayed_ema21", None, -0.05, 0.05, False, "fixed", None),
        ("Fixed 60D Hold (No stop)", "fixed_hold", 60, None, None, False, "fixed", None),
        ("System E: -10% stop + EMA21 after +10%", "delayed_ema21", None, -0.10, 0.10, False, "fixed", None),
        ("System E + Regime Sch 1 + Sector Cap 25%", "delayed_ema21", None, -0.10, 0.10, False, "sch1", 0.25),
    ]
    for cost in [0.0, 25.0, 50.0, 100.0]:
        for label, e_mod, h_days, c_stop, act, pl, r_sch, s_cap in tested_strats:
            s, _, _ = simulate_long_hold_engine(
                sig_60, processed_stocks, nifty_regime_map,
                capacity=15, exit_model=e_mod, hold_days=h_days, cat_stop_pct=c_stop,
                activation_pct=act, profit_locking=pl, regime_schedule=r_sch, sector_cap_pct=s_cap,
                cost_bps=cost
            )
            cost_rows.append({
                "Strategy": label,
                "Cost_Level": f"{int(cost)} bps" if cost > 0 else "Gross (0 bps)",
                "Cost_Bps": cost,
                "CAGR": s["cagr"],
                "MaxDD": s["max_drawdown"],
                "ProfitFactor": s["profit_factor"],
                "WinRate": s["win_rate"],
                "AvgTrade": s["avg_trade_ret"],
                "Expectancy": s["expectancy"],
                "EndingCapital": s["ending_capital"]
            })
            print(f"{label:45s} @ {cost:3.0f} bps -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f}")
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(REPORTS_DIR / "gfs_cost_sensitivity_long_hold.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 13: EXPANDING WALK-FORWARD VALIDATION (6 FOLDS)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 13: EXPANDING CHRONOLOGICAL WALK-FORWARD VALIDATION (6 FOLDS)")
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
    wf_models = [
        ("Baseline GFS (-5% -> fast EMA21)", "delayed_ema21", None, -0.05, 0.05, False, "fixed", None),
        ("Fixed 60D Hold", "fixed_hold", 60, None, None, False, "fixed", None),
        ("System E: -10% Stop + EMA21 after +10%", "delayed_ema21", None, -0.10, 0.10, False, "fixed", None),
        ("System E + Regime Sch 1 + Sector Cap 25%", "delayed_ema21", None, -0.10, 0.10, False, "sch1", 0.25),
    ]
    for f_name, train_s, train_e, test_s, test_e in folds:
        for mod_name, e_mod, h_days, c_stop, act, pl, r_sch, s_cap in wf_models:
            s_train, _, _ = simulate_long_hold_engine(
                sig_60, processed_stocks, nifty_regime_map,
                capacity=15, exit_model=e_mod, hold_days=h_days, cat_stop_pct=c_stop,
                activation_pct=act, profit_locking=pl, regime_schedule=r_sch, sector_cap_pct=s_cap,
                cost_bps=25.0, start_date=train_s, end_date=train_e
            )
            s_test, _, _ = simulate_long_hold_engine(
                sig_60, processed_stocks, nifty_regime_map,
                capacity=15, exit_model=e_mod, hold_days=h_days, cat_stop_pct=c_stop,
                activation_pct=act, profit_locking=pl, regime_schedule=r_sch, sector_cap_pct=s_cap,
                cost_bps=25.0, start_date=test_s, end_date=test_e
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
            print(f"{f_name} [{mod_name[:30]:30s}] -> Train: {s_train['cagr']:5.2f}% | Test Ret: {s_test['total_return_pct']:5.2f}%, Test MaxDD: {s_test['max_drawdown']:5.2f}%, Test PF: {s_test['profit_factor']:4.2f}")
    wf_df = pd.DataFrame(wf_rows)
    wf_df.to_csv(REPORTS_DIR / "gfs_walk_forward_long_hold.csv", index=False)

    # -------------------------------------------------------------------------
    # STAGE 14: MASTER FINAL STRATEGY COMPARISON (SECTION 19)
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STAGE 14: MASTER FINAL STRATEGY COMPARISON (SECTION 19)")
    print("=" * 80)
    final_configs = [
        # Baseline threshold & holding variants:
        ("GFS 60/60 + 20D", "is_60_60", "fixed_hold", 20, None, None, False, "fixed", None),
        ("GFS 60/60 + 40D", "is_60_60", "fixed_hold", 40, None, None, False, "fixed", None),
        ("GFS 60/60 + 60D", "is_60_60", "fixed_hold", 60, None, None, False, "fixed", None),
        ("GFS 65/65 + 60D", "is_65_65", "fixed_hold", 60, None, None, False, "fixed", None),
        ("GFS 70/70 + 60D", "is_70_70", "fixed_hold", 60, None, None, False, "fixed", None),
        ("GFS 70/70 + 90D", "is_70_70", "fixed_hold", 90, None, None, False, "fixed", None),
        # Risk-managed versions:
        ("GFS + wide stop (-10%) + EMA21 (fast)", "is_60_60", "delayed_ema21", None, -0.10, 0.05, False, "fixed", None),
        ("GFS + wide stop (-10%) + delayed EMA21 (+10%)", "is_60_60", "delayed_ema21", None, -0.10, 0.10, False, "fixed", None),
        ("GFS + wide stop (-10%) + delayed EMA21 (+20%)", "is_60_60", "delayed_ema21", None, -0.10, 0.20, False, "fixed", None),
        ("GFS + wide stop (-10%) + profit protection", "is_60_60", "delayed_ema21", None, -0.10, 0.10, True, "fixed", None),
        ("GFS + wide stop + EMA21 + regime allocation", "is_60_60", "delayed_ema21", None, -0.10, 0.10, False, "sch1", None),
        ("GFS + wide stop + EMA21 + regime + sector cap", "is_60_60", "delayed_ema21", None, -0.10, 0.10, False, "sch1", 0.25),
    ]
    final_rows = []
    for label, mask_col, e_mod, h_days, c_stop, act, pl, r_sch, s_cap in final_configs:
        sig_sub = signals_df[signals_df[mask_col]].copy()
        s, _, tr = simulate_long_hold_engine(
            sig_sub, processed_stocks, nifty_regime_map,
            capacity=15, exit_model=e_mod, hold_days=h_days, cat_stop_pct=c_stop,
            activation_pct=act, profit_locking=pl, regime_schedule=r_sch, sector_cap_pct=s_cap,
            cost_bps=25.0
        )
        final_rows.append({
            "Strategy": label,
            "CAGR": s["cagr"],
            "TotalReturn": s["total_return_pct"],
            "MaxDD": s["max_drawdown"],
            "ProfitFactor": s["profit_factor"],
            "WinRate": s["win_rate"],
            "AvgTrade": s["avg_trade_ret"],
            "MedianTrade": s["median_trade_ret"],
            "AvgWinner": s["avg_win"],
            "AvgLoser": s["avg_loss"],
            "Expectancy": s["expectancy"],
            "AvgHoldDays": s["avg_holding_days"],
            "Trades": s["num_trades"],
            "Turnover": s["annual_turnover"],
            "AvgExposure": s["avg_exposure_pct"],
            "AvgCash": s["avg_cash_pct"],
            "W50": s["w50"],
            "W100": s["w100"],
            "W200": s["w200"],
            "MaxWinner": s["max_winner"]
        })
        print(f"{label:45s} -> CAGR: {s['cagr']:6.2f}% | MaxDD: {s['max_drawdown']:6.2f}% | PF: {s['profit_factor']:5.2f} | Exp: {s['expectancy']:5.2f}% | >50%: {s['w50']:2d} | >100%: {s['w100']:2d}")
    final_df = pd.DataFrame(final_rows)
    final_df.to_csv(REPORTS_DIR / "gfs_final_comparison_long_hold.csv", index=False)

    print("\n" + "=" * 80)
    print("ALL RESEARCH MODULES COMPLETED SUCCESSFULLY!")
    print("=" * 80)

if __name__ == "__main__":
    run_research()
