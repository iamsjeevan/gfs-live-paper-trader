"""Corporate actions manager.

Tracks stock splits, reverse splits, ticker changes, mergers, and acquisitions
in the SQLite `corporate_actions` table.
"""

from typing import Any, Dict, List, Optional
import sqlite3
from pathlib import Path

from config.settings import DATABASE_PATH, setup_logger
from database.connection import get_connection

logger = setup_logger("corporate_actions", "price_download.log")


class CorporateActionManager:
    """Manages recording and looking up corporate actions."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DATABASE_PATH

    def record_action(
        self,
        action_date: str,
        action_type: str,
        old_ticker: Optional[str] = None,
        new_ticker: Optional[str] = None,
        ratio: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Record a single corporate action."""
        sql = """
        INSERT INTO corporate_actions (
            old_ticker, new_ticker, action_date, action_type, ratio, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """
        conn = get_connection(self.db_path)
        try:
            conn.execute(sql, (old_ticker, new_ticker, action_date, action_type, ratio, notes))
            conn.commit()
        finally:
            conn.close()

    def get_actions(
        self,
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve all corporate actions for a ticker."""
        ticker_clean = ticker.strip().upper()
        sql = """
        SELECT * FROM corporate_actions
        WHERE (old_ticker = ? OR new_ticker = ?)
        """
        params: List[Any] = [ticker_clean, ticker_clean]

        if start_date:
            sql += " AND action_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND action_date <= ?"
            params.append(end_date)

        sql += " ORDER BY action_date ASC"

        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()
