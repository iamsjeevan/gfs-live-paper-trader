"""Exact candle aggregation engine for 1d, 4h, 1h, 15m, and 5m bars from 1-minute source."""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
import time
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from backtest.data import MARKET_DB_PATH

logger = logging.getLogger("backtest_aggregation")

TIMEFRAME_MS_MAP = {
    "1d": 86_400_000,
    "4h": 14_400_000,
    "1h": 3_600_000,
    "15m": 900_000,
    "5m": 300_000,
}

TABLE_MAP = {
    "1d": "btc_usdt_1d",
    "4h": "btc_usdt_4h",
    "1h": "btc_usdt_1h",
    "15m": "btc_usdt_15m",
    "5m": "btc_usdt_5m",
}


def build_aggregated_tables(db_path: Optional[Path] = None, force_rebuild: bool = False):
    """Aggregate 1-minute data into 1d, 4h, 1h, 15m, and 5m tables in SQLite.

    Strict rules:
    - Open = first 1m open
    - High = max 1m high
    - Low = min 1m low
    - Close = last 1m close
    - Volume = sum 1m volume
    - No interpolation of missing data (missing minutes remain omitted).
    - Unambiguous UTC timestamps.
    """
    target_path = db_path or MARKET_DB_PATH
    conn = sqlite3.connect(str(target_path), timeout=120.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA cache_size = -64000;")

    cursor = conn.cursor()

    # Check if tables already exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    existing_tables = set(r[0] for r in cursor.fetchall())

    all_exist = all(tbl in existing_tables for tbl in TABLE_MAP.values())
    if all_exist and not force_rebuild:
        logger.info("All aggregated candle tables (1d, 4h, 1h, 15m, 5m) already exist.")
        conn.close()
        return

    logger.info("Loading 1-minute base data from btc_usdt_1m...")
    t0 = time.time()
    # Read core columns efficiently
    query = """
        SELECT timestamp, open, high, low, close, volume, quote_volume, trades
        FROM btc_usdt_1m
        ORDER BY timestamp ASC;
    """
    df_1m = pd.read_sql(query, conn)
    logger.info(f"Loaded {len(df_1m):,} 1m rows in {time.time()-t0:.2f}s.")

    # Convert timestamp to DatetimeIndex
    df_1m["datetime"] = pd.to_datetime(df_1m["timestamp"], unit="ms", utc=True)
    df_1m = df_1m.set_index("datetime")

    resample_rules = {
        "1d": "1D",
        "4h": "4h",
        "1h": "1h",
        "15m": "15min",
        "5m": "5min",
    }

    for tf_key, rule in resample_rules.items():
        tbl_name = TABLE_MAP[tf_key]
        if tbl_name in existing_tables and not force_rebuild:
            logger.info(f"Table {tbl_name} already exists; skipping.")
            continue

        logger.info(f"Aggregating {tf_key} ({rule})...")
        t_agg = time.time()

        resampled = df_1m.resample(rule, closed="left", label="left").agg({
            "timestamp": "first",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "quote_volume": "sum",
            "trades": "sum",
        }).dropna(subset=["open", "close"])

        # Construct start timestamp in milliseconds and UTC string
        epoch = pd.Timestamp("1970-01-01", tz="UTC")
        resampled["timestamp"] = (resampled.index - epoch) // pd.Timedelta(milliseconds=1)
        resampled["datetime_utc"] = resampled.index.strftime("%Y-%m-%d %H:%M:%S")

        cols_ordered = [
            "timestamp", "datetime_utc", "open", "high", "low", "close",
            "volume", "quote_volume", "trades"
        ]
        out_df = resampled[cols_ordered].copy()

        # Create table and write to SQLite
        with conn:
            conn.execute(f"DROP TABLE IF EXISTS {tbl_name};")
            conn.execute(f"""
                CREATE TABLE {tbl_name} (
                    timestamp INTEGER PRIMARY KEY,
                    datetime_utc TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    quote_volume REAL NOT NULL,
                    trades INTEGER NOT NULL
                );
            """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{tbl_name}_datetime
                ON {tbl_name}(datetime_utc);
            """)

            # Bulk insert
            rows_to_insert = [tuple(x) for x in out_df.to_numpy()]
            conn.executemany(f"""
                INSERT INTO {tbl_name} (
                    timestamp, datetime_utc, open, high, low, close,
                    volume, quote_volume, trades
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, rows_to_insert)

        logger.info(
            f"Created {tbl_name}: {len(out_df):,} candles in {time.time()-t_agg:.2f}s "
            f"({out_df['datetime_utc'].iloc[0]} to {out_df['datetime_utc'].iloc[-1]})."
        )

    conn.close()
    logger.info(f"All aggregated tables built successfully in {time.time()-t0:.2f}s.")
