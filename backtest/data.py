"""Database connections, candle fetching, and results schema management."""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

logger = logging.getLogger("backtest_data")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MARKET_DB_PATH = DATA_DIR / "bitcoin_market.db"
RESULTS_DB_PATH = DATA_DIR / "backtest_results.db"


def get_market_db(path: Optional[Path] = None) -> sqlite3.Connection:
    """Connect to market database with read-optimized pragmas."""
    target = path or MARKET_DB_PATH
    conn = sqlite3.connect(str(target), timeout=60.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA query_only = ON;")
    return conn


def get_results_db(path: Optional[Path] = None) -> sqlite3.Connection:
    """Connect to results database and initialize schema."""
    target = path or RESULTS_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=60.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    init_results_db(conn)
    return conn


def init_results_db(conn: sqlite3.Connection):
    """Initialize relational schema for backtesting experiments and analytics."""
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                lookbacks TEXT NOT NULL,
                leverage REAL NOT NULL,
                volatility_lookback INTEGER NOT NULL,
                target_volatility REAL NOT NULL,
                sizing_mode TEXT NOT NULL,
                direction_mode TEXT NOT NULL,
                fee_rate REAL NOT NULL,
                slippage_rate REAL NOT NULL,
                borrow_rate_apr REAL NOT NULL,
                start_datetime TEXT NOT NULL,
                end_datetime TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                experiment_id TEXT PRIMARY KEY,
                total_return REAL NOT NULL,
                cagr REAL NOT NULL,
                annualized_volatility REAL NOT NULL,
                sharpe_ratio REAL NOT NULL,
                sortino_ratio REAL NOT NULL,
                max_drawdown REAL NOT NULL,
                calmar_ratio REAL NOT NULL,
                win_rate REAL NOT NULL,
                profit_factor REAL NOT NULL,
                total_trades INTEGER NOT NULL,
                turnover REAL NOT NULL,
                total_fees REAL NOT NULL,
                total_slippage REAL NOT NULL,
                total_costs REAL NOT NULL,
                exposure_pct REAL NOT NULL,
                avg_position_size REAL NOT NULL,
                avg_win_pct REAL NOT NULL,
                avg_loss_pct REAL NOT NULL,
                best_trade_pct REAL NOT NULL,
                worst_trade_pct REAL NOT NULL,
                longest_win_streak INTEGER NOT NULL,
                longest_loss_streak INTEGER NOT NULL,
                benchmark_total_return REAL NOT NULL,
                benchmark_cagr REAL NOT NULL,
                benchmark_sharpe REAL NOT NULL,
                benchmark_max_drawdown REAL NOT NULL,
                alpha_cagr REAL NOT NULL,
                FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS equity_curves (
                experiment_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                datetime_utc TEXT NOT NULL,
                equity REAL NOT NULL,
                benchmark_equity REAL NOT NULL,
                cash REAL NOT NULL,
                position_weight REAL NOT NULL,
                drawdown REAL NOT NULL,
                PRIMARY KEY(experiment_id, timestamp),
                FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS monthly_returns (
                experiment_id TEXT NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                return_pct REAL NOT NULL,
                PRIMARY KEY(experiment_id, year, month),
                FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS yearly_returns (
                experiment_id TEXT NOT NULL,
                year INTEGER NOT NULL,
                return_pct REAL NOT NULL,
                PRIMARY KEY(experiment_id, year),
                FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS regime_metrics (
                experiment_id TEXT NOT NULL,
                regime_name TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                strategy_return REAL NOT NULL,
                benchmark_return REAL NOT NULL,
                strategy_sharpe REAL NOT NULL,
                strategy_max_dd REAL NOT NULL,
                PRIMARY KEY(experiment_id, regime_name),
                FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
            );
        """)


def load_candles(
    timeframe: str = "1d",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Load OHLCV candles from the SQLite market database for a given timeframe.

    Timeframe must be one of: '1d', '4h', '1h', '15m', '5m', '1m'.
    """
    table_map = {
        "1d": "btc_usdt_1d",
        "4h": "btc_usdt_4h",
        "1h": "btc_usdt_1h",
        "15m": "btc_usdt_15m",
        "5m": "btc_usdt_5m",
        "1m": "btc_usdt_1m",
    }
    tbl = table_map.get(timeframe.lower())
    if not tbl:
        raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {list(table_map.keys())}")

    conn = get_market_db(db_path)
    # Check if table exists
    cursor = conn.cursor()
    cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}';")
    if not cursor.fetchone():
        conn.close()
        raise FileNotFoundError(f"Table '{tbl}' does not exist in market database. Run aggregation first.")

    where_clauses = []
    params = []
    if start_date:
        where_clauses.append("datetime_utc >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("datetime_utc <= ?")
        params.append(end_date)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"""
        SELECT timestamp, datetime_utc, open, high, low, close, volume, quote_volume, trades
        FROM {tbl}
        {where_sql}
        ORDER BY timestamp ASC;
    """
    df = pd.read_sql(query, conn, params=params)
    conn.close()

    if not df.empty:
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df
