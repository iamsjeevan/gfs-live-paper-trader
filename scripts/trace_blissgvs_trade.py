"""Accurate State Machine reconstruction for BLISSGVS."""

import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect("data/indian_market.db")

# Fetch monthly candles
monthly_df = pd.read_sql("""
    SELECT m.*, s.symbol, s.company_name
    FROM monthly_ohlcv m
    JOIN securities s ON s.security_id = m.security_id
    WHERE s.symbol = 'BLISSGVS'
    ORDER BY m.year_month ASC;
""", conn)

# Monthly RSI(14)
closes = monthly_df["close"]
delta = closes.diff()
gain = delta.clip(lower=0.0)
loss = -delta.clip(upper=0.0)
avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
rs = avg_gain / avg_loss.replace(0.0, 1e-9)
monthly_df["rsi14"] = 100.0 - (100.0 / (1.0 + rs))
monthly_df["ema9"] = closes.ewm(span=9, adjust=False).mean()
monthly_df["is_candidate"] = (monthly_df["rsi14"] > 70.0) & (monthly_df["close"] > monthly_df["ema9"])

qualified_months = set(monthly_df[monthly_df["is_candidate"]]["year_month"])
print("Qualified Months for BLISSGVS:", sorted(list(qualified_months)))

# Fetch daily candles
daily_df = pd.read_sql("""
    SELECT d.date, d.open, d.high, d.low, d.close, d.volume
    FROM daily_ohlcv d
    JOIN securities s ON s.security_id = d.security_id
    WHERE s.symbol = 'BLISSGVS'
    ORDER BY d.date ASC;
""", conn)
conn.close()

daily_df["date"] = pd.to_datetime(daily_df["date"])
daily_df["year_month"] = daily_df["date"].dt.strftime("%Y-%m")
daily_df["prev_month"] = (daily_df["date"] - pd.offsets.MonthBegin(1)).dt.strftime("%Y-%m")

# Daily indicators
daily_df["ema21"] = daily_df["close"].ewm(span=21, adjust=False).mean()
daily_df["res20"] = daily_df["high"].shift(1).rolling(20).max()
daily_df["vol20"] = daily_df["volume"].shift(1).rolling(20).mean()

# Run State Machine for BLISSGVS
state = "NO_SIGNAL"
active_trade = None
completed_trades = []

# Variables for setup tracking
active_setup = None

for i in range(25, len(daily_df)):
    row = daily_df.iloc[i]
    prev_row = daily_df.iloc[i - 1]
    curr_date = row["date"].strftime("%Y-%m-%d")
    open_p = row["open"]
    high_p = row["high"]
    low_p = row["low"]
    close_p = row["close"]
    vol = row["volume"]
    ema21 = row["ema21"]
    res = row["res20"]

    # 1. Manage Active Trade if in position
    if active_trade is not None:
        # Check MFE & MAE
        mfe = (high_p - active_trade["entry_price"]) / active_trade["entry_price"]
        mae = (low_p - active_trade["entry_price"]) / active_trade["entry_price"]
        active_trade["mfe"] = max(active_trade["mfe"], mfe)
        active_trade["mae"] = min(active_trade["mae"], mae)
        active_trade["holding_days"] += 1

        # Check if exit was pending from previous day (e.g. EMA21 breakdown)
        if active_trade.get("exit_pending"):
            active_trade["exit_date"] = curr_date
            active_trade["exit_price"] = open_p
            active_trade["return_pct"] = (open_p - active_trade["entry_price"]) / active_trade["entry_price"] * 100
            completed_trades.append(active_trade)
            print(f"[{curr_date}] EXIT at Open: {open_p:.2f} | Reason: {active_trade['exit_reason']} | Return: {active_trade['return_pct']:+.2f}% | Hold Days: {active_trade['holding_days']}")
            active_trade = None
            state = "NO_SIGNAL"
            continue

        # Check Stop Loss (if +5% not reached yet)
        if not active_trade["plus_5_reached"]:
            # Check intraday low vs stop price
            if low_p <= active_trade["initial_stop"]:
                # Stop triggered
                exit_p = min(open_p, active_trade["initial_stop"])
                active_trade["exit_date"] = curr_date
                active_trade["exit_price"] = exit_p
                active_trade["exit_reason"] = "INITIAL_STOP_LOSS"
                active_trade["return_pct"] = (exit_p - active_trade["entry_price"]) / active_trade["entry_price"] * 100
                completed_trades.append(active_trade)
                print(f"[{curr_date}] STOP LOSS TRIGGERED at {exit_p:.2f} | Return: {active_trade['return_pct']:+.2f}%")
                active_trade = None
                state = "NO_SIGNAL"
                continue

            # Check +5% threshold activation
            if high_p >= active_trade["plus_5_threshold"]:
                active_trade["plus_5_reached"] = True
                active_trade["plus_5_date"] = curr_date
                state = "EMA21_TRAILING_PHASE"
                print(f"[{curr_date}] +5% THRESHOLD REACHED! High: {high_p:.2f} >= {active_trade['plus_5_threshold']:.2f}. EMA21 Trailing ACTIVE.")

        # In EMA21 Trailing Phase: check daily close < EMA21
        if active_trade["plus_5_reached"]:
            if close_p < ema21:
                active_trade["exit_pending"] = True
                active_trade["exit_reason"] = "EMA21_TRAILING_EXIT"
                print(f"[{curr_date}] EMA21 EXIT SIGNAL: Close {close_p:.2f} < EMA21 {ema21:.2f}. Will exit at next day Open.")

        continue

    # 2. Check Pending Entry (confirmation occurred previous day)
    if active_setup and active_setup.get("confirmed"):
        # BUY AT TODAY OPEN
        entry_price = open_p
        initial_stop = entry_price * 0.97
        plus_5_thresh = entry_price * 1.05

        active_trade = {
            "ticker": "BLISSGVS",
            "company": "Bliss GVS Pharma Ltd.",
            "monthly_signal_date": active_setup["monthly_signal_date"],
            "monthly_rsi": active_setup["monthly_rsi"],
            "monthly_ema9": active_setup["monthly_ema9"],
            "daily_ema21_at_setup": active_setup["daily_ema21"],
            "breakout_date": active_setup["breakout_date"],
            "resistance": active_setup["resistance"],
            "retest_date": active_setup["retest_date"],
            "confirmation_date": active_setup["confirmation_date"],
            "entry_date": curr_date,
            "entry_price": entry_price,
            "initial_stop": initial_stop,
            "plus_5_threshold": plus_5_thresh,
            "plus_5_reached": False,
            "plus_5_date": None,
            "exit_date": None,
            "exit_price": None,
            "exit_reason": None,
            "return_pct": 0.0,
            "holding_days": 0,
            "mfe": 0.0,
            "mae": 0.0,
        }
        print(f"\n[{curr_date}] *** ENTRY EXECUTED *** Buy at Open: {entry_price:.2f} | Initial Stop: {initial_stop:.2f} (-3%) | +5% Threshold: {plus_5_thresh:.2f}")
        active_setup = None
        state = "INITIAL_STOP_PHASE"
        continue

    # 3. Monthly Qualification Check
    # Does the prior completed month qualify as monthly candidate?
    prior_month = row["prev_month"]
    month_qualified = (prior_month in qualified_months)

    if not month_qualified and active_setup is None:
        state = "NO_SIGNAL"
        continue

    # 4. Search for Breakout if not in setup
    if active_setup is None:
        state = "WAITING_FOR_BREAKOUT"
        # Must have Daily Close > EMA21 before breakout
        if close_p > res and close_p > ema21:
            # Monthly info
            m_info = monthly_df[monthly_df["year_month"] == prior_month].iloc[0]
            active_setup = {
                "monthly_signal_date": m_info["end_date"],
                "monthly_rsi": m_info["rsi14"],
                "monthly_ema9": m_info["ema9"],
                "daily_ema21": ema21,
                "breakout_date": curr_date,
                "resistance": res,
                "retest_date": None,
                "confirmation_date": None,
                "breakout_idx": i,
                "retested": False,
                "confirmed": False
            }
            state = "BREAKOUT_DETECTED"
            print(f"\n[{curr_date}] BREAKOUT DETECTED: Close {close_p:.2f} > Resistance {res:.2f} | EMA21: {ema21:.2f} | Retest Zone: [{res*0.995:.2f}, {res*1.005:.2f}]")
        continue

    # 5. Track Active Setup (Retest and Confirmation)
    if active_setup is not None:
        bars_since_bo = i - active_setup["breakout_idx"]
        # Invalidation check: 20 trading days
        if bars_since_bo > 20:
            print(f"[{curr_date}] SETUP EXPIRED (stale after {bars_since_bo} days). Invalidation.")
            active_setup = None
            state = "NO_SIGNAL"
            continue

        R = active_setup["resistance"]
        retest_min = R * 0.995
        retest_max = R * 1.005

        # Invalidation: falls substantially below retest zone (e.g. close < R * 0.97)
        if close_p < R * 0.97:
            print(f"[{curr_date}] SETUP INVALIDATED: Close {close_p:.2f} fell substantially below retest zone ({R*0.97:.2f}).")
            active_setup = None
            state = "NO_SIGNAL"
            continue

        # Check if price trades into retest zone today
        touches_retest = (low_p <= retest_max and high_p >= retest_min)
        if touches_retest and not active_setup["retested"]:
            active_setup["retested"] = True
            active_setup["retest_date"] = curr_date
            state = "RETEST_DETECTED"
            print(f"[{curr_date}] RETEST DETECTED: Low {low_p:.2f} <= {retest_max:.2f} & High {high_p:.2f} >= {retest_min:.2f}")

        # Check Confirmation Candle
        # "1. Trade into the retest zone, 2. Close ABOVE original resistance, 3. Close > Open, 4. Close > EMA21"
        is_green = (close_p > open_p)
        closes_above_res = (close_p > R)
        closes_above_ema = (close_p > ema21)

        if touches_retest and closes_above_res and is_green and closes_above_ema:
            active_setup["confirmed"] = True
            active_setup["confirmation_date"] = curr_date
            if active_setup["retest_date"] is None:
                active_setup["retest_date"] = curr_date
            state = "WAITING_FOR_CONFIRMATION"
            print(f"[{curr_date}] *** CONFIRMATION CANDLE ***: Retested [{low_p:.2f}-{high_p:.2f}], Close {close_p:.2f} > Res {R:.2f}, Green (C>O), C > EMA21 ({ema21:.2f}). Entry tomorrow!")

print("\n" + "="*80)
print(f"BLISSGVS TOTAL TRADES: {len(completed_trades)}")
print("="*80)
for t in completed_trades:
    for k, v in t.items():
        if isinstance(v, float):
            print(f"  {k:25s}: {v:.2f}")
        else:
            print(f"  {k:25s}: {v}")
    print("-" * 50)
