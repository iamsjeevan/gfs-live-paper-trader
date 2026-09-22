"""Technical Strategy Engine and Signal Generator.

Frozen Strategy Rules:
1. Monthly Qualification: Completed Prior Month RSI(14) > 70 AND Close > EMA(9).
2. Daily Breakout: Daily Close > 20-Day Resistance (Highest High of previous 20 completed days) AND Close > Daily EMA(21).
3. Retest: Price returns within +-0.5% of original broken resistance [0.995*R, 1.005*R].
4. Invalidation: Daily Close drops below 0.97*R.
5. Setup Expiration: Must confirm within 20 trading days after breakout.
6. Confirmation Candle:
   - Low <= 1.005*R AND High >= 0.995*R (trades into retest zone)
   - Close > Resistance
   - Close > Open (Bullish green bar)
   - Close > Daily EMA(21)
7. Entry: Next trading day OPEN (09:15 IST).
"""

import sqlite3
import logging
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np

from app.config import DEFAULT_DB_PATH, CONFIG
from app.db import get_db_connection

logger = logging.getLogger("paper_trading.strategy")

class TechnicalStrategyEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH

    def evaluate_signals_for_date(self, evaluation_date: str) -> List[Dict]:
        """Evaluate technical setups on completed Day T close and generate confirmed signals for Day T+1 entry."""
        conn = get_db_connection(self.db_path)
        cur = conn.cursor()

        # 1. Determine prior month for monthly qualification
        eval_dt = pd.to_datetime(evaluation_date)
        prev_month = (eval_dt - pd.offsets.MonthBegin(1)).strftime("%Y-%m")

        # 2. Get monthly candidates for prior month
        monthly_cands = set(
            row["symbol"] for row in cur.execute(
                "SELECT symbol FROM monthly_prices WHERE year_month = ? AND is_candidate = 1;",
                (prev_month,)
            ).fetchall()
        )

        if not monthly_cands:
            logger.info(f"No monthly candidates found for prior month {prev_month} on {evaluation_date}.")
            conn.close()
            return []

        # 3. Load active setups from database
        active_setups_rows = cur.execute(
            "SELECT setup_id, symbol, breakout_date, resistance, breakout_close, retested, days_active FROM setups WHERE status = 'ACTIVE';"
        ).fetchall()
        active_setups = {row["symbol"]: dict(row) for row in active_setups_rows}

        # 4. Load today's bar for all symbols with history
        placeholders = ",".join(["?"] * len(monthly_cands))
        today_bars = pd.read_sql(
            f"""
            SELECT symbol, date, open, high, low, close, volume, turnover_cr, ema21, resistance20
            FROM daily_prices
            WHERE date = ? AND symbol IN ({placeholders});
            """,
            conn,
            params=[evaluation_date] + list(monthly_cands)
        )

        confirmed_signals = []

        for _, row in today_bars.iterrows():
            sym = row["symbol"]
            o_p = row["open"]
            h_p = row["high"]
            l_p = row["low"]
            c_p = row["close"]
            v = row["volume"]
            t_cr = row["turnover_cr"]
            ema_val = row["ema21"]
            res_val = row["resistance20"]

            if pd.isna(ema_val) or pd.isna(res_val):
                continue

            # Check existing active setup
            if sym in active_setups:
                setup = active_setups[sym]
                R = setup["resistance"]
                setup["days_active"] += 1

                # Expiration check (>20 trading days)
                if setup["days_active"] > CONFIG.MAX_DAYS_TO_CONFIRM:
                    cur.execute("UPDATE setups SET status = 'EXPIRED' WHERE setup_id = ?;", (setup["setup_id"],))
                    continue

                # Invalidation check (Close < 0.97 * R)
                if c_p < R * (1.0 - CONFIG.INVALIDATION_PCT):
                    cur.execute("UPDATE setups SET status = 'INVALIDATED' WHERE setup_id = ?;", (setup["setup_id"],))
                    continue

                # Retest touch zone check: [0.995*R, 1.005*R]
                retest_min = R * (1.0 - CONFIG.RETEST_TOLERANCE)
                retest_max = R * (1.0 + CONFIG.RETEST_TOLERANCE)
                touches_retest = (l_p <= retest_max and h_p >= retest_min)

                if touches_retest and not setup["retested"]:
                    setup["retested"] = 1
                    cur.execute("UPDATE setups SET retested = 1, retest_date = ? WHERE setup_id = ?;", (evaluation_date, setup["setup_id"]))

                # Confirmation Candle Check:
                # 1. Trade into retest zone, 2. Close > R, 3. Bullish (Close > Open), 4. Close > Daily EMA21
                is_green = (c_p > o_p)
                closes_above_r = (c_p > R)
                closes_above_ema = (c_p > ema_val)

                if touches_retest and closes_above_r and is_green and closes_above_ema:
                    # Calculate Relative Volume on Breakout Date
                    breakout_date = setup["breakout_date"]
                    vol_hist = pd.read_sql(
                        """
                        SELECT date, volume FROM daily_prices
                        WHERE symbol = ? AND date <= ?
                        ORDER BY date DESC LIMIT 25;
                        """,
                        conn,
                        params=[sym, breakout_date]
                    )
                    
                    rel_vol = 1.0
                    if len(vol_hist) >= 21:
                        # Breakout volume / 20-day SMA prior to breakout
                        b_vol = vol_hist[vol_hist["date"] == breakout_date]["volume"].values
                        if len(b_vol) > 0:
                            prior_20_vol = vol_hist[vol_hist["date"] < breakout_date]["volume"].head(20).mean()
                            if prior_20_vol > 0:
                                rel_vol = float(b_vol[0] / prior_20_vol)

                    # Mark setup confirmed
                    cur.execute(
                        "UPDATE setups SET status = 'CONFIRMED', confirmed = 1, confirmation_date = ? WHERE setup_id = ?;",
                        (evaluation_date, setup["setup_id"])
                    )

                    # Fetch monthly indicators
                    m_row = cur.execute(
                        "SELECT rsi14, ema9, close FROM monthly_prices WHERE symbol = ? AND year_month = ?;",
                        (sym, prev_month)
                    ).fetchone()
                    m_rsi = m_row["rsi14"] if m_row else None
                    m_ema9 = m_row["ema9"] if m_row else None
                    m_close = m_row["close"] if m_row else None

                    signal_data = {
                        "symbol": sym,
                        "signal_date": evaluation_date,
                        "signal_type": "LONG_BREAKOUT_RETEST",
                        "monthly_rsi": m_rsi,
                        "monthly_ema9": m_ema9,
                        "monthly_close": m_close,
                        "daily_ema21": ema_val,
                        "resistance": R,
                        "breakout_price": setup["breakout_close"],
                        "confirmation_price": c_p,
                        "relative_volume": rel_vol,
                        "turnover_cr": t_cr,
                        "reason": "Retest confirmed with bullish candle above resistance & EMA21"
                    }
                    confirmed_signals.append(signal_data)

            else:
                # No active setup: Search for new Daily Breakout
                # Conditions: Close > Resistance AND Close > Daily EMA21
                if c_p > res_val and c_p > ema_val:
                    cur.execute("""
                    INSERT INTO setups (symbol, breakout_date, resistance, breakout_close, status, days_active)
                    VALUES (?, ?, ?, ?, 'ACTIVE', 0);
                    """, (sym, evaluation_date, res_val, c_p))

        conn.commit()
        conn.close()
        logger.info(f"Signal evaluation on {evaluation_date} yielded {len(confirmed_signals)} confirmed setups.")
        return confirmed_signals
