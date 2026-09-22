"""Repository for backtest runs and positions."""

from typing import Any, Dict, List, Optional
import sqlite3


class BacktestRepository:
    """Handles saving and querying backtest runs and position outcomes."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save_backtest_run(
        self,
        run_id: str,
        screen_run_id: str,
        strategy_name: str,
        start_date: str,
        end_date: str,
        investment_per_stock: float,
        total_initial: float,
        total_final: float,
        multiple: float,
        cagr: float,
    ) -> None:
        """Record a backtest run summary."""
        sql = """
        INSERT INTO backtest_runs (
            run_id, screen_run_id, strategy_name, start_date, end_date,
            investment_per_stock, total_initial, total_final, multiple, cagr, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(run_id) DO UPDATE SET
            total_initial = excluded.total_initial,
            total_final = excluded.total_final,
            multiple = excluded.multiple,
            cagr = excluded.cagr;
        """
        self.conn.execute(
            sql,
            (
                run_id,
                screen_run_id,
                strategy_name,
                start_date,
                end_date,
                investment_per_stock,
                total_initial,
                total_final,
                multiple,
                cagr,
            ),
        )

    def save_positions_batch(self, run_id: str, positions: List[Dict[str, Any]]) -> int:
        """Save position outcomes for a backtest run."""
        if not positions:
            return 0

        sql = """
        INSERT INTO backtest_positions (
            run_id, cik, ticker, company, initial_investment, start_price,
            end_price, final_value, multiple, cagr, final_status, notes
        ) VALUES (
            :run_id, :cik, :ticker, :company, :initial_investment, :start_price,
            :end_price, :final_value, :multiple, :cagr, :final_status, :notes
        )
        """
        params = []
        for p in positions:
            item = dict(p)
            item["run_id"] = run_id
            params.append(item)

        self.conn.executemany(sql, params)
        return len(positions)

    def get_backtest_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve backtest run by run_id."""
        cursor = self.conn.execute("SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_positions(self, run_id: str) -> List[Dict[str, Any]]:
        """Retrieve all position details for a backtest run."""
        cursor = self.conn.execute("SELECT * FROM backtest_positions WHERE run_id = ? ORDER BY final_value DESC", (run_id,))
        return [dict(row) for row in cursor.fetchall()]
