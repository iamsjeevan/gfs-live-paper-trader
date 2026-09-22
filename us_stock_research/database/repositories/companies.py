"""Repository for the companies table."""

from typing import Any, Dict, List, Optional
import sqlite3


class CompanyRepository:
    """Handles CRUD operations for companies."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_company(self, company: Dict[str, Any]) -> None:
        """Insert or update a single company record."""
        sql = """
        INSERT INTO companies (
            cik, ticker, company_name, exchange, sic, sic_description,
            first_seen, last_seen, is_active, metadata_json, updated_at
        ) VALUES (
            :cik, :ticker, :company_name, :exchange, :sic, :sic_description,
            :first_seen, :last_seen, :is_active, :metadata_json, datetime('now')
        )
        ON CONFLICT(cik) DO UPDATE SET
            ticker = COALESCE(excluded.ticker, companies.ticker),
            company_name = COALESCE(excluded.company_name, companies.company_name),
            exchange = COALESCE(excluded.exchange, companies.exchange),
            sic = COALESCE(excluded.sic, companies.sic),
            sic_description = COALESCE(excluded.sic_description, companies.sic_description),
            first_seen = COALESCE(companies.first_seen, excluded.first_seen),
            last_seen = COALESCE(excluded.last_seen, companies.last_seen),
            is_active = COALESCE(excluded.is_active, companies.is_active),
            metadata_json = COALESCE(excluded.metadata_json, companies.metadata_json),
            updated_at = datetime('now');
        """
        defaults = {
            "cik": None,
            "ticker": None,
            "company_name": "",
            "exchange": None,
            "sic": None,
            "sic_description": None,
            "first_seen": None,
            "last_seen": None,
            "is_active": 1,
            "metadata_json": None,
        }
        params = {**defaults, **company}
        self.conn.execute(sql, params)

    def upsert_companies_batch(self, companies: List[Dict[str, Any]]) -> int:
        """Insert or update multiple companies in a single transaction."""
        if not companies:
            return 0

        sql = """
        INSERT INTO companies (
            cik, ticker, company_name, exchange, sic, sic_description,
            first_seen, last_seen, is_active, metadata_json, updated_at
        ) VALUES (
            :cik, :ticker, :company_name, :exchange, :sic, :sic_description,
            :first_seen, :last_seen, :is_active, :metadata_json, datetime('now')
        )
        ON CONFLICT(cik) DO UPDATE SET
            ticker = COALESCE(excluded.ticker, companies.ticker),
            company_name = COALESCE(excluded.company_name, companies.company_name),
            exchange = COALESCE(excluded.exchange, companies.exchange),
            sic = COALESCE(excluded.sic, companies.sic),
            sic_description = COALESCE(excluded.sic_description, companies.sic_description),
            first_seen = COALESCE(companies.first_seen, excluded.first_seen),
            last_seen = COALESCE(excluded.last_seen, companies.last_seen),
            is_active = COALESCE(excluded.is_active, companies.is_active),
            metadata_json = COALESCE(excluded.metadata_json, companies.metadata_json),
            updated_at = datetime('now');
        """
        defaults = {
            "cik": None,
            "ticker": None,
            "company_name": "",
            "exchange": None,
            "sic": None,
            "sic_description": None,
            "first_seen": None,
            "last_seen": None,
            "is_active": 1,
            "metadata_json": None,
        }
        params_list = [{**defaults, **c} for c in companies]
        self.conn.executemany(sql, params_list)
        return len(companies)

    def get_by_cik(self, cik: int) -> Optional[Dict[str, Any]]:
        """Retrieve a company by CIK."""
        cursor = self.conn.execute("SELECT * FROM companies WHERE cik = ?", (cik,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_by_ticker(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Retrieve a company by ticker."""
        cursor = self.conn.execute("SELECT * FROM companies WHERE ticker = ? COLLATE NOCASE", (ticker,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_all(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        """List all companies with pagination."""
        sql = "SELECT * FROM companies ORDER BY cik ASC"
        if limit is not None:
            sql += f" LIMIT {limit} OFFSET {offset}"
        cursor = self.conn.execute(sql)
        return [dict(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """Count total companies."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM companies")
        return cursor.fetchone()[0]
