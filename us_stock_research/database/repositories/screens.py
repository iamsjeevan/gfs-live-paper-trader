"""Repository for screen runs and results."""

from typing import Any, Dict, List, Optional
import json
import sqlite3


class ScreenRepository:
    """Handles saving and querying screen runs and individual screened company results."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save_screen_run(
        self,
        run_id: str,
        screen_date: str,
        strategy_name: str,
        min_market_cap: float,
        max_market_cap: float,
        weights: Dict[str, Any],
        hard_filters: Dict[str, Any],
    ) -> None:
        """Record a screen run."""
        sql = """
        INSERT INTO screen_runs (
            run_id, screen_date, strategy_name, universe_min_market_cap,
            universe_max_market_cap, weights_json, hard_filters_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(run_id) DO UPDATE SET
            screen_date = excluded.screen_date,
            strategy_name = excluded.strategy_name,
            universe_min_market_cap = excluded.universe_min_market_cap,
            universe_max_market_cap = excluded.universe_max_market_cap,
            weights_json = excluded.weights_json,
            hard_filters_json = excluded.hard_filters_json;
        """
        self.conn.execute(
            sql,
            (
                run_id,
                screen_date,
                strategy_name,
                min_market_cap,
                max_market_cap,
                json.dumps(weights),
                json.dumps(hard_filters),
            ),
        )

    def save_screen_results_batch(self, run_id: str, results: List[Dict[str, Any]]) -> int:
        """Save ranked results for a screen run."""
        if not results:
            return 0

        sql = """
        INSERT INTO screen_results (
            run_id, cik, ticker, company_name, score, rank, market_cap,
            price, roe, roic, revenue_growth, earnings_growth, fcf_growth,
            debt_equity, operating_margin, fcf_margin, moat_score, data_quality_flags
        ) VALUES (
            :run_id, :cik, :ticker, :company_name, :score, :rank, :market_cap,
            :price, :roe, :roic, :revenue_growth, :earnings_growth, :fcf_growth,
            :debt_equity, :operating_margin, :fcf_margin, :moat_score, :data_quality_flags
        )
        """
        params = []
        for r in results:
            item = dict(r)
            item["run_id"] = run_id
            params.append(item)

        self.conn.executemany(sql, params)
        return len(results)

    def get_screen_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve screen run details."""
        cursor = self.conn.execute("SELECT * FROM screen_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_screen_results(self, run_id: str, top_n: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve results for a screen run ordered by rank."""
        sql = "SELECT * FROM screen_results WHERE run_id = ? ORDER BY rank ASC"
        if top_n is not None:
            sql += f" LIMIT {top_n}"
        cursor = self.conn.execute(sql, (run_id,))
        return [dict(row) for row in cursor.fetchall()]
