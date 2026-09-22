"""Repository for historical fundamentals table."""

from typing import Any, Dict, List, Optional
import sqlite3


class FundamentalRepository:
    """Handles storage and point-in-time queries for fundamental financial data."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_fundamentals_batch(self, records: List[Dict[str, Any]]) -> int:
        """Insert or update fundamental records in batch."""
        if not records:
            return 0

        columns = [
            "cik", "ticker", "filing_date", "report_date", "fiscal_year", "fiscal_period",
            "form", "accession_number", "revenue", "net_income", "operating_income", "gross_profit",
            "assets", "current_assets", "liabilities", "current_liabilities", "equity", "debt", "cash",
            "operating_cash_flow", "capex", "free_cash_flow", "shares_outstanding", "diluted_shares",
            "eps", "gross_margin", "operating_margin", "net_margin", "fcf_margin", "roe", "roa", "roic",
            "debt_equity", "current_ratio", "revenue_growth_1y", "revenue_growth_3y", "net_income_growth_1y",
            "net_income_growth_3y", "fcf_growth_1y", "fcf_growth_3y", "eps_growth_1y", "pe_ratio",
            "pfcf_ratio", "ps_ratio", "ev_ebitda", "moat_score", "data_quality_flags"
        ]

        col_str = ", ".join(columns)
        val_placeholders = ", ".join([f":{c}" for c in columns])

        update_assignments = [f"{c} = excluded.{c}" for c in columns if c not in ("cik", "report_date", "fiscal_period", "form")]
        update_str = ", ".join(update_assignments)

        sql = f"""
        INSERT INTO fundamentals ({col_str}, created_at)
        VALUES ({val_placeholders}, datetime('now'))
        ON CONFLICT(cik, report_date, fiscal_period, form) DO UPDATE SET
            {update_str};
        """

        clean_params = []
        for r in records:
            param_dict = {c: r.get(c, None) for c in columns}
            clean_params.append(param_dict)

        self.conn.executemany(sql, clean_params)
        return len(records)

    def get_latest_fundamental(
        self,
        cik: int,
        max_filing_date: str,
        annual_only: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Point-in-time query: get the most recent fundamental report available ON OR BEFORE max_filing_date.

        CRITICAL FOR NO LOOK-AHEAD:
        Filing date MUST be <= max_filing_date (e.g. 2016-12-31).
        """
        query = """
        SELECT * FROM fundamentals
        WHERE cik = ? AND filing_date <= ?
        """
        params: List[Any] = [cik, max_filing_date]

        if annual_only:
            query += " AND (form = '10-K' OR fiscal_period = 'FY')"

        query += " ORDER BY filing_date DESC, report_date DESC LIMIT 1"
        cursor = self.conn.execute(query, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_history_point_in_time(
        self,
        cik: int,
        max_filing_date: str,
        limit: int = 5,
        annual_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Point-in-time query: get the N most recent historical reports filed on or before max_filing_date."""
        query = """
        SELECT * FROM fundamentals
        WHERE cik = ? AND filing_date <= ?
        """
        params: List[Any] = [cik, max_filing_date]

        if annual_only:
            query += " AND (form = '10-K' OR fiscal_period = 'FY')"

        query += " ORDER BY filing_date DESC, report_date DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
