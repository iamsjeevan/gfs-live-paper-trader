"""Database management and SQLite schema definition for Live Paper Trading."""

import sqlite3
import logging
from pathlib import Path
from typing import Optional
from app.config import DEFAULT_DB_PATH, LOG_FILE

logger = logging.getLogger("paper_trading.db")

from typing import Optional, Union

def get_db_connection(db_path: Optional[Union[Path, str]] = None) -> sqlite3.Connection:
    """Return a configured sqlite3 connection with Row factory."""
    if db_path is None:
        path = DEFAULT_DB_PATH
    elif str(db_path) == ":memory:":
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn
    else:
        path = Path(db_path)

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_paper_trading_db(db_path: Optional[Path] = None) -> None:
    """Initialize all tables, constraints, and indexes for paper trading."""
    conn = get_db_connection(db_path)
    cur = conn.cursor()

    # 1. Securities Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS securities (
        symbol TEXT PRIMARY KEY,
        company_name TEXT,
        isin TEXT,
        sector TEXT,
        is_active INTEGER DEFAULT 1,
        avg_turnover_cr REAL DEFAULT 0.0,
        updated_at TEXT
    );
    """)

    # 2. Daily Prices Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_prices (
        symbol TEXT,
        date TEXT,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        turnover_cr REAL DEFAULT 0.0,
        ema21 REAL,
        resistance20 REAL,
        PRIMARY KEY (symbol, date)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_prices(date);")

    # 3. Monthly Prices & Indicators Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS monthly_prices (
        symbol TEXT,
        year_month TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL NOT NULL,
        volume REAL,
        rsi14 REAL,
        ema9 REAL,
        is_candidate INTEGER DEFAULT 0,
        end_date TEXT,
        PRIMARY KEY (symbol, year_month)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_monthly_cand ON monthly_prices(year_month, is_candidate);")

    # 4. Setups Table (Tracking Breakouts, Retests, Expirations)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS setups (
        setup_id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        breakout_date TEXT NOT NULL,
        resistance REAL NOT NULL,
        breakout_close REAL NOT NULL,
        retest_date TEXT,
        retested INTEGER DEFAULT 0,
        confirmed INTEGER DEFAULT 0,
        confirmation_date TEXT,
        status TEXT DEFAULT 'ACTIVE', -- ACTIVE, CONFIRMED, EXPIRED, INVALIDATED
        days_active INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_setup_status ON setups(symbol, status);")

    # 5. Signals Table (Deterministic record of all generated opportunities)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        signal_date TEXT NOT NULL,
        signal_type TEXT DEFAULT 'LONG_BREAKOUT_RETEST',
        monthly_rsi REAL,
        monthly_ema9 REAL,
        monthly_close REAL,
        daily_ema21 REAL,
        resistance REAL,
        breakout_price REAL,
        confirmation_price REAL,
        relative_volume REAL,
        ranking INTEGER,
        allocation REAL,
        status TEXT DEFAULT 'GENERATED', -- GENERATED, ACCEPTED, REJECTED_CAPACITY, REJECTED_LIQUIDITY
        reason TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_signal_date ON signals(signal_date);")

    # 6. Orders Table (Simulated Next-Day Orders)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id INTEGER,
        symbol TEXT NOT NULL,
        order_date TEXT NOT NULL,
        order_type TEXT DEFAULT 'SIMULATED_LIMIT_OPEN',
        side TEXT DEFAULT 'BUY', -- BUY, SELL
        status TEXT DEFAULT 'PENDING', -- PENDING, FILLED, REJECTED, CANCELLED
        raw_price REAL,
        simulated_price REAL,
        shares REAL,
        order_value REAL,
        slippage_bps REAL,
        capital_tier REAL DEFAULT 1000000.0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 7. Positions Table (Active Open Simulated Positions)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS positions (
        position_id INTEGER PRIMARY KEY AUTOINCREMENT,
        capital_tier REAL DEFAULT 1000000.0,
        symbol TEXT NOT NULL,
        entry_date TEXT NOT NULL,
        entry_price REAL NOT NULL,
        simulated_entry_price REAL NOT NULL,
        shares REAL NOT NULL,
        allocated_capital REAL NOT NULL,
        initial_stop REAL NOT NULL,
        plus_5_threshold REAL NOT NULL,
        plus_5_reached INTEGER DEFAULT 0,
        plus_5_date TEXT,
        highest_price REAL,
        status TEXT DEFAULT 'OPEN', -- OPEN, EXIT_PENDING, CLOSED, EXIT_BLOCKED_LOWER_CIRCUIT
        current_price REAL,
        unrealized_pnl REAL DEFAULT 0.0,
        unrealized_return_pct REAL DEFAULT 0.0,
        holding_days INTEGER DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pos_status ON positions(capital_tier, status);")

    # 8. Closed Trades Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS closed_trades (
        trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
        capital_tier REAL DEFAULT 1000000.0,
        symbol TEXT NOT NULL,
        entry_date TEXT NOT NULL,
        exit_date TEXT NOT NULL,
        entry_price REAL NOT NULL,
        exit_price REAL NOT NULL,
        shares REAL NOT NULL,
        return_pct REAL NOT NULL,
        pnl_rs REAL NOT NULL,
        holding_days INTEGER NOT NULL,
        exit_reason TEXT NOT NULL, -- INITIAL_STOP_LOSS, EMA21_TRAILING_EXIT, STOP_GAP_DOWN, FORCED_CLOSE
        mfe REAL DEFAULT 0.0,
        mae REAL DEFAULT 0.0,
        entry_friction_rs REAL DEFAULT 0.0,
        exit_friction_rs REAL DEFAULT 0.0,
        total_friction_rs REAL DEFAULT 0.0,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_closed_trades_date ON closed_trades(capital_tier, exit_date);")

    # 9. Portfolio Snapshots Table (Daily Mark-to-Market Record)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        capital_tier REAL DEFAULT 1000000.0,
        cash REAL NOT NULL,
        invested_val REAL NOT NULL,
        gross_market_val REAL NOT NULL,
        unrealized_pnl REAL NOT NULL,
        realized_pnl REAL NOT NULL,
        total_equity REAL NOT NULL,
        daily_return_pct REAL NOT NULL,
        cumulative_return_pct REAL NOT NULL,
        drawdown_pct REAL NOT NULL,
        peak_equity REAL NOT NULL,
        open_positions_count INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (date, capital_tier)
    );
    """)

    # 10. Execution Log
    cur.execute("""
    CREATE TABLE IF NOT EXISTS execution_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        level TEXT,
        event_type TEXT,
        message TEXT,
        details TEXT
    );
    """)

    # 11. Errors Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS errors (
        error_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        module TEXT,
        error_message TEXT,
        stack_trace TEXT,
        recovered INTEGER DEFAULT 0
    );
    """)

    # 12. System Heartbeat Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_heartbeat (
        heartbeat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
        status TEXT,
        last_data_update TEXT,
        open_positions INTEGER,
        cash REAL,
        total_equity REAL
    );
    """)

    conn.commit()
    conn.close()
    logger.info("Database schemas successfully initialized.")
