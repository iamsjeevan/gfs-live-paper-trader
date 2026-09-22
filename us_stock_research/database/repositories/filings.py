"""Repository for the filings table."""

from typing import Any, Dict, List, Optional
import sqlite3


class FilingRepository:
    """Handles CRUD operations for filing metadata."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_filings_batch(self, filings: List[Dict[str, Any]]) -> int:
        """Insert or replace filing records in batch."""
        if not filings:
            return 0

        sql = """
        INSERT INTO filings (
            accession_number, cik, form, filing_date, report_date,
            fiscal_year, fiscal_period, primary_document, created_at
        ) VALUES (
            :accession_number, :cik, :form, :filing_date, :report_date,
            :fiscal_year, :fiscal_period, :primary_document, datetime('now')
        )
        ON CONFLICT(accession_number) DO UPDATE SET
            form = excluded.form,
            filing_date = excluded.filing_date,
            report_date = excluded.report_date,
            fiscal_year = excluded.fiscal_year,
            fiscal_period = excluded.fiscal_period,
            primary_document = excluded.primary_document;
        """
        defaults = {
            "accession_number": None,
            "cik": None,
            "form": "",
            "filing_date": "",
            "report_date": None,
            "fiscal_year": None,
            "fiscal_period": None,
            "primary_document": None,
        }
        params = [{**defaults, **f} for f in filings]
        self.conn.executemany(sql, params)
        return len(filings)

    def get_by_cik(
        self,
        cik: int,
        form: Optional[str] = None,
        max_filing_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve filings for a company, strictly enforcing point-in-time filing date."""
        query = "SELECT * FROM filings WHERE cik = ?"
        params: List[Any] = [cik]

        if form is not None:
            query += " AND form = ?"
            params.append(form)

        if max_filing_date is not None:
            query += " AND filing_date <= ?"
            params.append(max_filing_date)

        query += " ORDER BY filing_date DESC, report_date DESC"
        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
