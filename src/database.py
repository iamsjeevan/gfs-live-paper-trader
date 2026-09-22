import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "stocks.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def create_tables():

    conn = get_connection()
    cur = conn.cursor()

    # Historical prices
    cur.execute("""
    CREATE TABLE IF NOT EXISTS prices (
        date TEXT,
        ticker TEXT,
        close REAL,
        high_52w REAL,
        drawdown REAL,
        PRIMARY KEY(date, ticker)
    )
    """)


    # Historical fundamentals
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fundamentals (
        date TEXT,
        ticker TEXT,
        roe REAL,
        roce REAL,
        debt_equity REAL,
        operating_cf REAL,
        net_profit REAL,
        pe REAL,
        pb REAL,
        PRIMARY KEY(date, ticker)
    )
    """)


    # Historical universe
    cur.execute("""
    CREATE TABLE IF NOT EXISTS universe (
        date TEXT,
        ticker TEXT,
        active INTEGER,
        PRIMARY KEY(date, ticker)
    )
    """)


    # Portfolio trades
    cur.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        date TEXT,
        ticker TEXT,
        action TEXT,
        quantity REAL,
        price REAL
    )
    """)


    conn.commit()
    conn.close()


if __name__ == "__main__":

    create_tables()

    print("SQLite database created:")
    print(DB_PATH)
