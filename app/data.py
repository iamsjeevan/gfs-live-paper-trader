"""Market Data Connector and Synchronizer for Indian Equities.

Handles:
- Loading finalized daily OHLCV from local market database or public APIs (NSE Bhavcopy / Yahoo Finance)
- Filtering out ETFs / Indices, keeping pure corporate equities
- Resampling to completed monthly candles and updating Monthly RSI(14) and EMA(9)
- Resilient recovery against weekends, holidays, missing bars, and duplicate entries
"""

import sqlite3
import logging
import datetime
from pathlib import Path
from typing import List, Dict, Optional
import pandas as pd
import numpy as np

from app.config import DEFAULT_DB_PATH, HISTORICAL_DB_PATH, CONFIG
from app.db import get_db_connection
from app.indicators import (
    compute_ema,
    compute_20d_resistance,
    compute_turnover_cr,
    build_monthly_indicators
)

logger = logging.getLogger("paper_trading.data")

# Known NSE non-corporate symbols to exclude
NON_CORPORATE_EXCLUSIONS = {
    "NIFTY50", "BANKNIFTY", "NIFTYIT", "NIFTYBEES", "GOLDBEES", "BANKBEES",
    "LIQUIDBEES", "INFRABEES", "JUNIORBEES", "MON100", "CPSEETF", "SILVERBEES",
    "AUTOBEES", "PHARMABEES", "SETFNIF50", "HDFCMFGETF", "ICICIB22", "KOTAKBKETF"
}

class MarketDataManager:
    def __init__(self, paper_db_path: Optional[Path] = None, source_db_path: Optional[Path] = None):
        self.paper_db_path = paper_db_path or DEFAULT_DB_PATH
        self.source_db_path = source_db_path or HISTORICAL_DB_PATH

    def sync_from_historical_db(self, limit_stocks: Optional[int] = None) -> int:
        """Seed or update paper trading database from local historical SQLite database.
        
        Copies securities, daily prices, and builds monthly indicators.
        """
        if not self.source_db_path.exists():
            logger.warning(f"Source database not found at {self.source_db_path}. Skipping local seed.")
            return 0

        src_conn = sqlite3.connect(self.source_db_path)
        paper_conn = get_db_connection(self.paper_db_path)

        # 1. Load securities
        sec_df = pd.read_sql("SELECT security_id, symbol, company_name FROM securities;", src_conn)
        sec_df = sec_df[~sec_df["symbol"].isin(NON_CORPORATE_EXCLUSIONS)].copy()
        if limit_stocks:
            sec_df = sec_df.head(limit_stocks)

        logger.info(f"Syncing {len(sec_df)} securities from {self.source_db_path}...")

        # Insert securities
        with paper_conn:
            for _, row in sec_df.iterrows():
                paper_conn.execute("""
                INSERT INTO securities (symbol, company_name, is_active, updated_at)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(symbol) DO UPDATE SET
                    company_name=excluded.company_name,
                    updated_at=CURRENT_TIMESTAMP;
                """, (row["symbol"], row["company_name"]))

        # 2. Sync daily prices and calculate technical indicators
        symbols = sec_df["symbol"].tolist()
        sec_ids = sec_df["security_id"].tolist()
        sec_id_to_sym = dict(zip(sec_ids, symbols))

        logger.info("Extracting daily OHLCV and computing technical indicators...")
        id_placeholders = ",".join(["?"] * len(sec_ids))
        daily_df = pd.read_sql(
            f"SELECT security_id, date, open, high, low, close, volume FROM daily_ohlcv WHERE security_id IN ({id_placeholders}) ORDER BY security_id, date ASC;",
            src_conn,
            params=sec_ids
        )
        src_conn.close()

        daily_df["symbol"] = daily_df["security_id"].map(sec_id_to_sym)
        daily_df = daily_df.dropna(subset=["symbol"]).sort_values(["symbol", "date"]).reset_index(drop=True)

        total_bars_inserted = 0
        all_daily_records = []
        all_monthly_records = []

        for sym, g in daily_df.groupby("symbol"):
            if len(g) < 21:
                continue

            g = g.sort_values("date").copy()
            c = g["close"]
            h = g["high"]
            v = g["volume"]

            # Compute technical indicators
            g["ema21"] = compute_ema(c, 21)
            g["resistance20"] = compute_20d_resistance(h, 20)
            g["turnover_cr"] = compute_turnover_cr(v, c)

            # Monthly indicators
            m_df = build_monthly_indicators(g[["date", "open", "high", "low", "close", "volume"]])
            for _, m_row in m_df.iterrows():
                all_monthly_records.append((
                    sym,
                    m_row["year_month"],
                    float(m_row["open"]),
                    float(m_row["high"]),
                    float(m_row["low"]),
                    float(m_row["close"]),
                    float(m_row["volume"]),
                    float(m_row["rsi14"]) if pd.notna(m_row["rsi14"]) else None,
                    float(m_row["ema9"]) if pd.notna(m_row["ema9"]) else None,
                    int(m_row["is_candidate"]),
                    str(m_row["end_date"])
                ))

            for _, d_row in g.iterrows():
                all_daily_records.append((
                    sym,
                    d_row["date"],
                    float(d_row["open"]),
                    float(d_row["high"]),
                    float(d_row["low"]),
                    float(d_row["close"]),
                    float(d_row["volume"]),
                    float(d_row["turnover_cr"]),
                    float(d_row["ema21"]) if pd.notna(d_row["ema21"]) else None,
                    float(d_row["resistance20"]) if pd.notna(d_row["resistance20"]) else None
                ))

        logger.info(f"Inserting {len(all_daily_records):,} daily bars into paper trading database...")
        with paper_conn:
            paper_conn.executemany("""
            INSERT INTO daily_prices (symbol, date, open, high, low, close, volume, turnover_cr, ema21, resistance20)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, date) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                turnover_cr=excluded.turnover_cr,
                ema21=excluded.ema21,
                resistance20=excluded.resistance20;
            """, all_daily_records)

            paper_conn.executemany("""
            INSERT INTO monthly_prices (symbol, year_month, open, high, low, close, volume, rsi14, ema9, is_candidate, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, year_month) DO UPDATE SET
                open=excluded.open,
                high=excluded.high,
                low=excluded.low,
                close=excluded.close,
                volume=excluded.volume,
                rsi14=excluded.rsi14,
                ema9=excluded.ema9,
                is_candidate=excluded.is_candidate,
                end_date=excluded.end_date;
            """, all_monthly_records)

        paper_conn.close()
        logger.info("Market data synchronization completed successfully.")
        return len(all_daily_records)

    def fetch_live_eod_data_yfinance(self, symbols: List[str]) -> int:
        """Fetch finalized daily candle for active symbols via public Yahoo Finance API (.NS).
        
        Used as fallback/live updater when running live daily at 15:45 IST.
        """
        try:
            import yfinance as yf
        except ImportError:
            logger.error("yfinance package not installed for live EOD fetch.")
            return 0

        logger.info(f"Fetching live EOD bars for {len(symbols)} symbols...")
        # Yahoo Finance ticker mapping
        yf_tickers = [f"{s}.NS" for s in symbols if not s.endswith(".NS")]
        if not yf_tickers:
            return 0

        # Download last 5 days to ensure candle finalization
        data = yf.download(yf_tickers, period="5d", interval="1d", group_by="ticker", auto_adjust=False, progress=False)
        if data.empty:
            logger.warning("No live data returned from Yahoo Finance.")
            return 0

        conn = get_db_connection(self.paper_db_path)
        inserted = 0

        with conn:
            for sym in symbols:
                yf_sym = f"{sym}.NS"
                try:
                    sym_df = data[yf_sym] if len(yf_tickers) > 1 else data
                    sym_df = sym_df.dropna(subset=["Close"]).reset_index()
                    for _, row in sym_df.iterrows():
                        d_str = row["Date"].strftime("%Y-%m-%d")
                        o = float(row["Open"])
                        h = float(row["High"])
                        l = float(row["Low"])
                        c = float(row["Close"])
                        v = float(row["Volume"])
                        t_cr = (v * c) / 10_000_000.0

                        conn.execute("""
                        INSERT INTO daily_prices (symbol, date, open, high, low, close, volume, turnover_cr)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(symbol, date) DO UPDATE SET
                            open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, volume=excluded.volume, turnover_cr=excluded.turnover_cr;
                        """, (sym, d_str, o, h, l, c, v, t_cr))
                        inserted += 1
                except Exception as e:
                    logger.debug(f"Could not parse ticker {sym}: {e}")

        conn.close()
        logger.info(f"Live EOD fetch completed. Inserted/updated {inserted} candles.")
        return inserted
