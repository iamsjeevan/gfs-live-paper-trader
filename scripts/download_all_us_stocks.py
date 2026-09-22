#!/usr/bin/env python3
"""
download_all_us_stocks.py
=========================
Overnight bulk downloader for the ENTIRE US EQUITY UNIVERSE (NASDAQ + NYSE + AMEX + S&P + Russell):
1. Aggregates all active tickers from:
   - `us_stock_research/research.db` (Nasdaq, NYSE, CBOE)
   - SEC EDGAR Master Company Tickers (10,000+ public companies)
2. Filters out warrants, preferreds, units, and rights.
3. Automatically skips tickers already up-to-date in `instocks.db`.
4. Downloads historical daily prices (2018 to 2026) in multi-threaded chunks of 50.
5. Inserts into `instocks.db` (`daily_prices` table).
6. Automatically tracks progress in `download_tracker` table for full crash resiliency.
7. Upon completion, automatically triggers `scripts/backtest_gfs_us_stocks.py`!
"""

import sys
import os
import time
import json
import sqlite3
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from pathlib import Path
from datetime import datetime

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
DB_PATH = BASE_DIR / "instocks.db"
RESEARCH_DB = BASE_DIR / "us_stock_research" / "research.db"

CHUNK_SIZE = 50
START_DATE = "2018-01-01"
END_DATE = "2026-08-26"
PAUSE_BETWEEN_CHUNKS = 1.0 # 1 second polite pause to avoid rate limiting

def get_candidate_tickers():
    print("=" * 85, flush=True)
    print("PHASE 1: AGGREGATING COMPLETE US STOCK UNIVERSE...", flush=True)
    print("=" * 85, flush=True)

    tickers = set()

    # 1. From us_stock_research/research.db (verified active Nasdaq & NYSE)
    if RESEARCH_DB.exists():
        try:
            conn_res = sqlite3.connect(RESEARCH_DB)
            res_rows = conn_res.cursor().execute("""
                SELECT ticker FROM companies 
                WHERE is_active = 1 AND exchange IN ('Nasdaq', 'NYSE', 'CBOE');
            """).fetchall()
            for r in res_rows:
                tk = str(r[0]).upper().strip().replace(".", "-")
                if tk:
                    tickers.add(tk)
            conn_res.close()
            print(f"Loaded {len(tickers):,} active tickers from research.db", flush=True)
        except Exception as e:
            print(f"Warning reading research.db: {e}", flush=True)

    # 2. From SEC EDGAR Master Tickers
    try:
        headers = {"User-Agent": "AntigravityResearch admin@quantfirm.com"}
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=headers, timeout=15)
        if r.status_code == 200:
            sec_data = r.json()
            sec_count = 0
            for item in sec_data.values():
                tk = str(item.get("ticker", "")).upper().strip().replace(".", "-")
                if tk:
                    tickers.add(tk)
                    sec_count += 1
            print(f"Fetched {sec_count:,} tickers from SEC EDGAR", flush=True)
    except Exception as e:
        print(f"Warning fetching SEC tickers: {e}", flush=True)

    # 3. Clean and filter tickers (Remove warrants, units, preferreds, debt)
    cleaned = set()
    invalid_suffixes = (
        "-WT", "-WS", "-W", "-U", "-UN", "-P", "-PR", "-RT", "-R", 
        "WT", "WS", "U", "UN", "RT"
    )
    
    for tk in tickers:
        # Must be standard characters
        if not tk or len(tk) > 5 or any(c in tk for c in ["^", "=", "+", "/", "%", " "]):
            continue
        # Exclude warrants/units/preferreds
        if any(tk.endswith(sfx) for sfx in invalid_suffixes if len(tk) > len(sfx)):
            continue
        cleaned.add(tk)

    candidate_list = sorted(list(cleaned))
    print(f"Total Filtered Clean US Common Stocks: {len(candidate_list):,}", flush=True)

    # 4. Check existing coverage in instocks.db
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Initialize download_tracker table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS download_tracker (
            ticker TEXT PRIMARY KEY,
            status TEXT,
            row_count INTEGER,
            last_date TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    # Find already completed tickers
    completed_tickers = set(r[0] for r in cursor.execute("""
        SELECT ticker FROM download_tracker WHERE status = 'SUCCESS' AND last_date >= '2026-01-01';
    """).fetchall())

    # Also check daily_prices for existing tickers with recent data
    existing_in_prices = set(r[0] for r in cursor.execute("""
        SELECT Ticker FROM daily_prices GROUP BY Ticker HAVING MAX(Date) >= '2026-01-01';
    """).fetchall())
    
    already_done = completed_tickers.union(existing_in_prices)
    conn.close()

    to_download = [tk for tk in candidate_list if tk not in already_done]
    print(f"Already up-to-date in database: {len(already_done):,}", flush=True)
    print(f"Queue to download: {len(to_download):,} new stocks", flush=True)

    return to_download

def download_batch(tickers_batch):
    """Downloads a batch of tickers using yfinance and returns parsed rows."""
    try:
        data = yf.download(
            tickers_batch,
            start=START_DATE,
            end=END_DATE,
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=False
        )
    except Exception as e:
        print(f"  [ERROR] yfinance batch download failed: {e}", flush=True)
        return {}, 0

    batch_rows = []
    ticker_stats = {}

    for tk in tickers_batch:
        try:
            if len(tickers_batch) == 1:
                sub = data
            elif tk in data:
                sub = data[tk]
            elif isinstance(data.columns, pd.MultiIndex) and tk in data.columns.levels[0]:
                sub = data[tk]
            else:
                ticker_stats[tk] = {"status": "NO_DATA", "rows": 0, "last_date": None}
                continue

            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                ticker_stats[tk] = {"status": "NO_DATA", "rows": 0, "last_date": None}
                continue

            tk_rows = []
            for dt, r in sub.iterrows():
                d_str = dt.strftime("%Y-%m-%d")
                c = float(r.get("Adj Close", r.get("Close", 0.0)))
                v = float(r.get("Volume", 0.0)) if pd.notna(r.get("Volume")) else 0.0
                if c > 0:
                    tk_rows.append((d_str, tk, c, v))

            if tk_rows:
                batch_rows.extend(tk_rows)
                ticker_stats[tk] = {
                    "status": "SUCCESS",
                    "rows": len(tk_rows),
                    "last_date": tk_rows[-1][0]
                }
            else:
                ticker_stats[tk] = {"status": "NO_DATA", "rows": 0, "last_date": None}

        except Exception as e:
            ticker_stats[tk] = {"status": f"ERROR: {str(e)[:30]}", "rows": 0, "last_date": None}

    return ticker_stats, batch_rows

def run_overnight_downloader():
    to_download = get_candidate_tickers()
    if not to_download:
        print("All tickers are already up to date! Proceeding directly to backtest.", flush=True)
        trigger_backtest()
        return

    chunks = [to_download[i:i + CHUNK_SIZE] for i in range(0, len(to_download), CHUNK_SIZE)]
    total_chunks = len(chunks)
    total_tickers = len(to_download)

    print("\n" + "=" * 85, flush=True)
    print(f"PHASE 2: DOWNLOADING {total_tickers:,} STOCKS IN {total_chunks:,} BATCHES...", flush=True)
    print("=" * 85, flush=True)

    t_start = time.time()
    total_rows_inserted = 0
    successful_tickers = 0

    conn = sqlite3.connect(DB_PATH, timeout=60.0)

    for idx, chunk in enumerate(chunks, 1):
        c_t0 = time.time()
        ticker_stats, rows = download_batch(chunk)

        # Bulk write to daily_prices
        if rows:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR IGNORE INTO daily_prices (Date, Ticker, Adj_Close, Volume)
                VALUES (?, ?, ?, ?);
            """, rows)
            total_rows_inserted += len(rows)

        # Update tracker
        tracker_rows = []
        for tk, stat in ticker_stats.items():
            if stat["status"] == "SUCCESS":
                successful_tickers += 1
            tracker_rows.append((
                tk,
                stat["status"],
                stat["rows"],
                stat["last_date"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))

        cursor = conn.cursor()
        cursor.executemany("""
            INSERT OR REPLACE INTO download_tracker (ticker, status, row_count, last_date, updated_at)
            VALUES (?, ?, ?, ?, ?);
        """, tracker_rows)
        conn.commit()

        c_time = time.time() - c_t0
        elapsed_min = (time.time() - t_start) / 60.0
        pct_done = (idx / total_chunks) * 100.0
        remaining_chunks = total_chunks - idx
        est_remain_min = (elapsed_min / idx) * remaining_chunks if idx > 0 else 0.0

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Chunk {idx:>4}/{total_chunks} ({pct_done:>5.1f}%) | "
            f"+{len(rows):>6,} bars | Total: {total_rows_inserted:>9,} bars | "
            f"Batch Time: {c_time:>4.1f}s | Elapsed: {elapsed_min:>4.1f}m | Est. Remaining: {est_remain_min:>5.1f}m",
            flush=True
        )

        time.sleep(PAUSE_BETWEEN_CHUNKS)

    conn.close()
    total_min = (time.time() - t_start) / 60.0
    print("\n" + "=" * 85, flush=True)
    print(f"DOWNLOAD COMPLETE in {total_min:.1f} minutes!", flush=True)
    print(f"Total Successful Tickers Added: {successful_tickers:,}", flush=True)
    print(f"Total Price Rows Added: {total_rows_inserted:,}", flush=True)
    print("=" * 85, flush=True)

    # Automatically trigger the full backtest!
    trigger_backtest()

def trigger_backtest():
    print("\n" + "=" * 85, flush=True)
    print("PHASE 3: RUNNING EXPANDED US GFS BACKTEST ON NEW UNIVERSE...", flush=True)
    print("=" * 85, flush=True)
    os.system(f"{sys.executable} {BASE_DIR}/scripts/backtest_gfs_us_stocks.py")

if __name__ == "__main__":
    run_overnight_downloader()
