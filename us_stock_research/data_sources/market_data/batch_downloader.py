"""Batch Historical Price Downloader using yfinance.

Downloads historical closing prices around screen date in bulk chunks
and persists them to the SQLite `prices` table.
"""

from pathlib import Path
from typing import List, Optional
import time
import pandas as pd
import yfinance as yf

from config.settings import DATABASE_PATH, setup_logger
from database.connection import get_connection
from database.repositories.prices import PriceRepository

logger = setup_logger("batch_prices", "price_download.log")


def batch_fetch_and_store_prices(
    tickers: List[str],
    start_date: str = "2016-12-20",
    end_date: str = "2017-01-05",
    chunk_size: int = 50,
    db_path: Optional[Path] = None,
) -> int:
    """Download prices for tickers in batches and store in SQLite.

    Returns:
        Total number of price records inserted.
    """
    database_file = db_path or DATABASE_PATH
    conn = get_connection(database_file)
    repo = PriceRepository(conn)

    clean_tickers = list(dict.fromkeys([t.strip().upper() for t in tickers if t and t.strip()]))
    total_chunks = (len(clean_tickers) + chunk_size - 1) // chunk_size
    total_saved = 0

    logger.info(f"Starting batch price download for {len(clean_tickers)} tickers in {total_chunks} chunks...")

    for chunk_idx in range(total_chunks):
        chunk = clean_tickers[chunk_idx * chunk_size : (chunk_idx + 1) * chunk_size]
        t0 = time.time()
        try:
            # Download bulk chunk from yfinance
            data = yf.download(
                chunk,
                start=start_date,
                end=end_date,
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
            )

            records = []
            if len(chunk) == 1:
                t = chunk[0]
                if not data.empty:
                    for d_idx, row in data.iterrows():
                        d_str = d_idx.strftime("%Y-%m-%d")
                        records.append({
                            "ticker": t,
                            "date": d_str,
                            "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
                            "high": float(row["High"]) if pd.notna(row["High"]) else None,
                            "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
                            "close": float(row["Close"]) if pd.notna(row["Close"]) else None,
                            "adjusted_close": float(row.get("Adj Close", row["Close"])) if pd.notna(row.get("Adj Close")) else None,
                            "volume": float(row["Volume"]) if pd.notna(row["Volume"]) else None,
                        })
            else:
                for t in chunk:
                    if t in data.columns.levels[0]:
                        t_df = data[t].dropna(how="all")
                        if not t_df.empty:
                            for d_idx, row in t_df.iterrows():
                                d_str = d_idx.strftime("%Y-%m-%d")
                                records.append({
                                    "ticker": t,
                                    "date": d_str,
                                    "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
                                    "high": float(row["High"]) if pd.notna(row["High"]) else None,
                                    "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
                                    "close": float(row["Close"]) if pd.notna(row["Close"]) else None,
                                    "adjusted_close": float(row.get("Adj Close", row["Close"])) if pd.notna(row.get("Adj Close")) else None,
                                    "volume": float(row["Volume"]) if pd.notna(row["Volume"]) else None,
                                })

            if records:
                saved = repo.upsert_prices_batch(records)
                conn.commit()
                total_saved += saved
            
            elapsed = time.time() - t0
            logger.info(f"Chunk {chunk_idx + 1}/{total_chunks} ({len(chunk)} tickers) processed in {elapsed:.2f}s, saved {len(records)} price rows.")

        except Exception as exc:
            logger.warning(f"Error downloading chunk {chunk_idx + 1}: {exc}")

    conn.close()
    logger.info(f"Batch price download completed: {total_saved} total price records saved.")
    return total_saved
