"""Repository for the historical_listings table.

Manages the bridge between SEC CIK identities and market-data trading identities.
"""

from typing import Any, Dict, List, Optional
import sqlite3


class HistoricalListingRepository:
    """Handles CRUD operations for historical_listings table."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def upsert_listing(self, listing: Dict[str, Any]) -> None:
        """Insert or replace a single listing record."""
        sql = """
        INSERT INTO historical_listings (
            cik, ticker, company_name, exchange, security_type,
            listing_start_date, listing_end_date, source, confidence, created_at
        ) VALUES (
            :cik, :ticker, :company_name, :exchange, :security_type,
            :listing_start_date, :listing_end_date, :source, :confidence, datetime('now')
        );
        """
        defaults = {
            "cik": None,
            "ticker": None,
            "company_name": "",
            "exchange": None,
            "security_type": "COMMON_EQUITY",
            "listing_start_date": None,
            "listing_end_date": None,
            "source": "manual",
            "confidence": 1.0,
        }
        params = {**defaults, **listing}
        self.conn.execute(sql, params)

    def upsert_listings_batch(self, listings: List[Dict[str, Any]]) -> int:
        """Insert multiple listings in a transaction."""
        if not listings:
            return 0

        sql = """
        INSERT INTO historical_listings (
            cik, ticker, company_name, exchange, security_type,
            listing_start_date, listing_end_date, source, confidence, created_at
        ) VALUES (
            :cik, :ticker, :company_name, :exchange, :security_type,
            :listing_start_date, :listing_end_date, :source, :confidence, datetime('now')
        );
        """
        defaults = {
            "cik": None,
            "ticker": None,
            "company_name": "",
            "exchange": None,
            "security_type": "COMMON_EQUITY",
            "listing_start_date": None,
            "listing_end_date": None,
            "source": "manual",
            "confidence": 1.0,
        }
        params_list = [{**defaults, **l} for l in listings]
        self.conn.executemany(sql, params_list)
        return len(listings)

    def get_by_cik(self, cik: int) -> List[Dict[str, Any]]:
        """Get all listings associated with a CIK."""
        sql = "SELECT * FROM historical_listings WHERE cik = ? ORDER BY confidence DESC, id DESC;"
        cursor = self.conn.execute(sql, (cik,))
        return [dict(r) for r in cursor.fetchall()]

    def get_primary_listing(self, cik: int) -> Optional[Dict[str, Any]]:
        """Get the highest confidence listing for a CIK."""
        sql = """
        SELECT * FROM historical_listings
        WHERE cik = ?
        ORDER BY confidence DESC, id DESC
        LIMIT 1;
        """
        cursor = self.conn.execute(sql, (cik,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_by_ticker(self, ticker: str) -> List[Dict[str, Any]]:
        """Get listings matching a ticker symbol."""
        sql = "SELECT * FROM historical_listings WHERE ticker = ? COLLATE NOCASE ORDER BY confidence DESC;"
        cursor = self.conn.execute(sql, (ticker,))
        return [dict(r) for r in cursor.fetchall()]

    def list_all(
        self,
        security_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List listings with optional security_type filter."""
        sql = "SELECT * FROM historical_listings"
        params: List[Any] = []
        if security_type:
            sql += " WHERE security_type = ?"
            params.append(security_type)
        sql += " ORDER BY cik ASC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        cursor = self.conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]

    def count(self, security_type: Optional[str] = None) -> int:
        """Count total listings."""
        sql = "SELECT COUNT(*) FROM historical_listings"
        params: List[Any] = []
        if security_type:
            sql += " WHERE security_type = ?"
            params.append(security_type)
        cursor = self.conn.execute(sql, params)
        return cursor.fetchone()[0]
