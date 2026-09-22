"""Generate monthly_ohlcv table from daily_ohlcv in data/indian_market.db."""

import sqlite3
import pandas as pd
import time

def build_monthly():
    t0 = time.time()
    conn = sqlite3.connect("data/indian_market.db")
    print("Reading daily_ohlcv...")
    df = pd.read_sql("SELECT security_id, date, open, high, low, close, volume FROM daily_ohlcv ORDER BY security_id, date ASC;", conn)
    print(f"Read {len(df):,} rows in {time.time() - t0:.2f}s")

    t1 = time.time()
    df["date"] = pd.to_datetime(df["date"])
    df["year_month"] = df["date"].dt.strftime("%Y-%m")

    monthly = df.groupby(["security_id", "year_month"]).agg(
        start_date=("date", "first"),
        end_date=("date", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum")
    ).reset_index()

    monthly["start_date"] = monthly["start_date"].dt.strftime("%Y-%m-%d")
    monthly["end_date"] = monthly["end_date"].dt.strftime("%Y-%m-%d")

    print(f"Aggregated {len(monthly):,} monthly rows in {time.time() - t1:.2f}s")

    t2 = time.time()
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS monthly_ohlcv;")
    cur.execute("""
    CREATE TABLE monthly_ohlcv (
        security_id INTEGER NOT NULL,
        year_month TEXT NOT NULL,
        start_date TEXT,
        end_date TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        PRIMARY KEY (security_id, year_month),
        FOREIGN KEY (security_id) REFERENCES securities(security_id)
    );
    """)
    monthly.to_sql("monthly_ohlcv", conn, if_exists="append", index=False)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_monthly_sec_ym ON monthly_ohlcv(security_id, year_month);")
    conn.commit()
    print(f"Inserted into monthly_ohlcv in {time.time() - t2:.2f}s")

    # Sample for BLISSGVS
    sec_bliss = cur.execute("SELECT security_id FROM securities WHERE symbol='BLISSGVS';").fetchone()
    if sec_bliss:
        sec_id = sec_bliss[0]
        bliss = pd.read_sql(f"SELECT * FROM monthly_ohlcv WHERE security_id={sec_id} ORDER BY year_month ASC;", conn)
        print(f"BLISSGVS has {len(bliss)} monthly candles from {bliss.iloc[0]['year_month']} to {bliss.iloc[-1]['year_month']}")
        print(bliss.tail(3))
    conn.close()

if __name__ == "__main__":
    build_monthly()
