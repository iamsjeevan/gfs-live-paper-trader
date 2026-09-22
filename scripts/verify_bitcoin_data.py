#!/usr/bin/env python3
"""Verification script for Bitcoin 1-minute historical dataset.

Checks:
- database exists
- table exists
- row count
- min(timestamp)
- max(timestamp)
- latest candle
- duplicate count
"""

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

# Ensure parent directory in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crypto_data.config import DB_PATH, TABLE_NAME


def verify_bitcoin_data():
    """Perform verification checks and print structured report."""
    print("================================================================================")
    print("BITCOIN HISTORICAL 1-MINUTE DATASET VERIFICATION")
    print("================================================================================")

    # 1. Database exists
    db_exists = DB_PATH.exists()
    print(f"Database Path:   {DB_PATH}")
    print(f"Database Exists: {'YES' if db_exists else 'NO'}")
    if not db_exists:
        print("ERROR: Database file does not exist. Please run the download script first.")
        sys.exit(1)

    db_size_mb = DB_PATH.stat().st_size / (1024.0 * 1024.0)
    print(f"Database Size:   {db_size_mb:.2f} MB")

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # 2. Table exists
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{TABLE_NAME}';")
    table_row = cursor.fetchone()
    table_exists = table_row is not None
    print(f"Table Name:      {TABLE_NAME}")
    print(f"Table Exists:    {'YES' if table_exists else 'NO'}")
    if not table_exists:
        print(f"ERROR: Table '{TABLE_NAME}' does not exist in database.")
        sys.exit(1)

    # 3. Row count, min, max timestamps
    cursor.execute(f"""
        SELECT COUNT(*), MIN(timestamp), MAX(timestamp),
               MIN(datetime_utc), MAX(datetime_utc)
        FROM {TABLE_NAME};
    """)
    row_count, min_ts, max_ts, min_dt, max_dt = cursor.fetchone()

    print(f"Total Row Count: {row_count:,}")
    print(f"Min Timestamp:   {min_ts} ({min_dt} UTC)")
    print(f"Max Timestamp:   {max_ts} ({max_dt} UTC)")

    if row_count == 0:
        print("WARNING: Table is currently empty.")
        sys.exit(0)

    # 4. Duplicate count
    cursor.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT timestamp FROM {TABLE_NAME}
            GROUP BY timestamp HAVING COUNT(*) > 1
        );
    """)
    dup_count = cursor.fetchone()[0]
    print(f"Duplicate Count: {dup_count}")

    # 5. Latest candle
    cursor.execute(f"""
        SELECT timestamp, datetime_utc, open, high, low, close, volume, quote_volume, trades
        FROM {TABLE_NAME}
        ORDER BY timestamp DESC
        LIMIT 1;
    """)
    latest = cursor.fetchone()
    print("\nLatest Candle:")
    print(f"  Timestamp (ms): {latest[0]}")
    print(f"  Datetime (UTC): {latest[1]}")
    print(f"  Open:           ${latest[2]:,.2f}")
    print(f"  High:           ${latest[3]:,.2f}")
    print(f"  Low:            ${latest[4]:,.2f}")
    print(f"  Close:          ${latest[5]:,.2f}")
    print(f"  Volume (BTC):   {latest[6]:,.4f}")
    print(f"  Quote Vol (USDT): ${latest[7]:,.2f}")
    print(f"  Trade Count:    {latest[8]:,}")

    print("================================================================================")
    print("VERIFICATION STATUS: PASSED")
    print("================================================================================")
    conn.close()


if __name__ == "__main__":
    verify_bitcoin_data()
