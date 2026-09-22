"""Repository for the historical prices table."""

from typing import Any, Dict, List, Optional
import sqlite3


class PriceRepository:
    """Handles storage and retrieval of historical daily OHLCV stock prices."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def upsert_prices_batch(self, prices: List[Dict[str, Any]]) -> int:
        """Insert or replace daily price records."""
        if not prices:
            return 0

        sql = """
        INSERT INTO prices (
            ticker, date, cik, open, high, low, close, adjusted_close, volume,
            provider, adjustment_type, data_quality, confidence, created_at
        ) VALUES (
            :ticker, :date, :cik, :open, :high, :low, :close, :adjusted_close, :volume,
            :provider, :adjustment_type, :data_quality, :confidence, datetime('now')
        )
        ON CONFLICT(ticker, date) DO UPDATE SET
            cik = COALESCE(excluded.cik, prices.cik),
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            adjusted_close = excluded.adjusted_close,
            volume = excluded.volume,
            provider = COALESCE(excluded.provider, prices.provider),
            adjustment_type = COALESCE(excluded.adjustment_type, prices.adjustment_type),
            data_quality = COALESCE(excluded.data_quality, prices.data_quality),
            confidence = COALESCE(excluded.confidence, prices.confidence);
        """
        defaults = {
            "ticker": "",
            "date": "",
            "cik": None,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "adjusted_close": None,
            "volume": None,
            "provider": "yahoo",
            "adjustment_type": "UNADJUSTED_CLOSE",
            "data_quality": "CLEAN",
            "confidence": 1.0,
        }
        params = [{**defaults, **p} for p in prices]
        self.conn.executemany(sql, params)
        return len(prices)

    def get_price_on_or_before(
        self,
        ticker: Optional[str] = None,
        date: str = "2016-12-31",
        cik: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get the latest available price on or immediately prior to date by ticker or CIK."""
        if ticker:
            sql = """
            SELECT * FROM prices
            WHERE ticker = ? COLLATE NOCASE AND date <= ?
            ORDER BY date DESC
            LIMIT 1;
            """
            cursor = self.conn.execute(sql, (ticker, date))
            row = cursor.fetchone()
            if row:
                return dict(row)

        if cik is not None:
            sql = """
            SELECT * FROM prices
            WHERE cik = ? AND date <= ?
            ORDER BY date DESC
            LIMIT 1;
            """
            cursor = self.conn.execute(sql, (cik, date))
            row = cursor.fetchone()
            if row:
                return dict(row)

        return None

    def get_price_history(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve daily price history for a ticker."""
        query = "SELECT * FROM prices WHERE ticker = ? COLLATE NOCASE"
        params: List[Any] = [ticker]

        if start_date is not None:
            query += " AND date >= ?"
            params.append(start_date)

        if end_date is not None:
            query += " AND date <= ?"
            params.append(end_date)

        query += " ORDER BY date ASC"
        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
