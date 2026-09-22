import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor
import os

DB_PATH = "data/crypto_prices.db"
CRYPTO_TICKERS = ["BTC-USD", "ETH-USD"]

def fetch_crypto_ticker(ticker):
    print(f"Starting download for {ticker}...", flush=True)
    try:
        data = yf.Ticker(ticker)
        df = data.history(period="max", interval="1d")
        if df.empty:
            print(f"Warning: No data returned for {ticker}", flush=True)
            return None
        
        df = df.reset_index()
        df['symbol'] = ticker.replace("-USD", "")
        df['date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
        
        # Lowercase all column names
        df.columns = [c.lower() for c in df.columns]
        
        if 'close' not in df.columns:
            print(f"Error: close not in columns for {ticker}", flush=True)
            return None

        # Standardize columns
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        res_df = df[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']].copy()
        print(f"Successfully downloaded {len(res_df)} rows for {ticker} ({res_df['date'].min()} to {res_df['date'].max()})", flush=True)
        return res_df
    except Exception as e:
        print(f"Error downloading {ticker}: {e}", flush=True)
        return None

def main():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS daily_prices")
    cursor.execute("""
    CREATE TABLE daily_prices (
        symbol TEXT,
        date TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        PRIMARY KEY (symbol, date)
    )
    """)
    conn.commit()

    print("Fetching BTC and ETH historical data in parallel...", flush=True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(fetch_crypto_ticker, CRYPTO_TICKERS))

    for df in results:
        if df is not None and not df.empty:
            df.to_sql("daily_prices", conn, if_exists="append", index=False)
            print(f"Saved {len(df)} rows into crypto_prices.db for {df['symbol'].iloc[0]}")

    conn.commit()
    conn.close()
    print("Crypto database download complete!")

if __name__ == "__main__":
    main()
