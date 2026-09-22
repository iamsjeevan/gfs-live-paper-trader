"""Yahoo Finance market data provider.

Fetches historical daily OHLCV prices and corporate actions using yfinance,
with SQLite caching in the `prices` table and multi-threaded batch downloading.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging
import sqlite3
import pandas as pd
import yfinance as yf

from config.settings import DATABASE_PATH, PRICE_WORKERS, setup_logger
from database.connection import get_connection
from database.repositories.prices import PriceRepository
from .base import PriceProvider

logger = setup_logger("yahoo_prices", "price_download.log")


class YahooPriceProvider(PriceProvider):
    """Downloads, caches, and queries historical stock prices using Yahoo Finance."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DATABASE_PATH

    def get_history(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        refresh: bool = False,
    ) -> pd.DataFrame:
        """Fetch daily price history for ticker between start_date and end_date.

        Checks SQLite first unless refresh=True.
        """
        ticker_clean = ticker.strip().upper()

        if not refresh:
            conn = get_connection(self.db_path)
            repo = PriceRepository(conn)
            cached_rows = repo.get_price_history(ticker_clean, start_date=start_date, end_date=end_date)
            conn.close()

            if cached_rows:
                df = pd.DataFrame(cached_rows)
                return df

        # Fetch from Yahoo Finance
        try:
            yt = yf.Ticker(ticker_clean)
            # Fetch with auto_adjust=False so we record both raw close and split/dividend-adjusted close
            hist = yt.history(start=start_date, end=end_date, auto_adjust=False)

            if hist.empty:
                logger.debug(f"No price history found on Yahoo for {ticker_clean}")
                return pd.DataFrame()

            # Format records
            records: List[Dict[str, Any]] = []
            for date_idx, row in hist.iterrows():
                d_str = date_idx.strftime("%Y-%m-%d")
                records.append({
                    "ticker": ticker_clean,
                    "date": d_str,
                    "open": float(row["Open"]) if pd.notna(row["Open"]) else None,
                    "high": float(row["High"]) if pd.notna(row["High"]) else None,
                    "low": float(row["Low"]) if pd.notna(row["Low"]) else None,
                    "close": float(row["Close"]) if pd.notna(row["Close"]) else None,
                    "adjusted_close": float(row.get("Adj Close", row["Close"])) if pd.notna(row.get("Adj Close")) else None,
                    "volume": float(row["Volume"]) if pd.notna(row["Volume"]) else None,
                })

            # Save to SQLite
            conn = get_connection(self.db_path)
            repo = PriceRepository(conn)
            repo.upsert_prices_batch(records)
            conn.commit()
            conn.close()

            return pd.DataFrame(records)

        except Exception as exc:
            logger.warning(f"Error downloading Yahoo prices for {ticker_clean}: {exc}")
            return pd.DataFrame()

    def get_price(
        self,
        ticker: str,
        date: str,
        adjusted: bool = False,
        lookback_days: int = 10,
    ) -> Optional[float]:
        """Fetch the closing price on or immediately prior to date.

        If markets were closed (e.g. Saturday 2016-12-31), looks back up to lookback_days
        (e.g. finds Friday 2016-12-30).
        """
        ticker_clean = ticker.strip().upper()

        conn = get_connection(self.db_path)
        repo = PriceRepository(conn)
        row = repo.get_price_on_or_before(ticker_clean, date)
        conn.close()

        if row:
            # Check that the row is within reasonable lookback window
            row_date = row["date"]
            days_diff = (pd.to_datetime(date) - pd.to_datetime(row_date)).days
            if 0 <= days_diff <= lookback_days:
                return float(row["adjusted_close"] if adjusted else row["close"])

        # Not in SQLite: fetch historical window around date
        start_dt = (pd.to_datetime(date) - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        end_dt = (pd.to_datetime(date) + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        df = self.get_history(ticker_clean, start_date=start_dt, end_date=end_dt)

        if not df.empty:
            df_filtered = df[df["date"] <= date].sort_values("date")
            if not df_filtered.empty:
                last_row = df_filtered.iloc[-1]
                return float(last_row["adjusted_close"] if adjusted else last_row["close"])

        return None

    def get_corporate_actions(self, ticker: str) -> pd.DataFrame:
        """Fetch historical splits and dividends."""
        ticker_clean = ticker.strip().upper()
        try:
            yt = yf.Ticker(ticker_clean)
            actions = yt.actions
            if actions is not None and not actions.empty:
                actions = actions.reset_index()
                actions["date"] = actions["Date"].dt.strftime("%Y-%m-%d")
                return actions
        except Exception as exc:
            logger.warning(f"Failed to fetch actions for {ticker_clean}: {exc}")
        return pd.DataFrame()

    def download_batch_prices(
        self,
        tickers: List[str],
        start_date: str,
        end_date: str,
        workers: int = PRICE_WORKERS,
        refresh: bool = False,
    ) -> Dict[str, bool]:
        """Download prices for multiple tickers in parallel.

        Returns:
            Dict[ticker, success_bool]
        """
        results = {}
        unique_tickers = list(dict.fromkeys([t.strip().upper() for t in tickers if t]))

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self.get_history, t, start_date, end_date, refresh): t
                for t in unique_tickers
            }

            for future in as_completed(futures):
                t = futures[future]
                try:
                    df = future.result()
                    results[t] = not df.empty
                except Exception:
                    results[t] = False

        return results
