"""SQLite database connection manager.

Provides robust connection management with:
- WAL mode (Write-Ahead Logging) for high concurrency
- Foreign keys enforcement
- Row factory returning dict-accessible sqlite3.Row objects
- Context manager support for transactions
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional, Union

from config.settings import DATABASE_PATH


def get_connection(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    """Create and configure a SQLite connection.

    Args:
        db_path: Path to SQLite database file. Defaults to config.DATABASE_PATH.

    Returns:
        Configured sqlite3.Connection.
    """
    path = Path(db_path) if db_path else DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row

    # Performance and integrity pragmas
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")

    return conn


@contextmanager
def get_db_cursor(db_path: Optional[Union[str, Path]] = None) -> Generator[sqlite3.Cursor, None, None]:
    """Context manager for automatic transaction commit/rollback.

    Yields:
        sqlite3.Cursor
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
