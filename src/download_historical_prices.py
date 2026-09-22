import sqlite3
import pandas as pd
import yfinance as yf
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"
START_DATE = "2018-01-01"
END_DATE = "2026-08-25"
CHUNK_SIZE = 50

def init_price_table():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_prices (
        symbol TEXT,
        date TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        sma_50 REAL,
        sma_200 REAL,
        high_52w REAL,
        drawdown REAL,
        PRIMARY KEY (symbol, date)
    );
    """)
    conn.commit()
    conn.close()
    print("[DB INIT] Table daily_prices initialized.", flush=True)

def download_benchmark():
    print("[BENCHMARK] Downloading Nifty 50 (^NSEI) daily data...", flush=True)
    try:
        data = yf.download("^NSEI", start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            close = data["Close"].iloc[:, 0]
        else:
            close = data["Close"]
        
        df = pd.DataFrame({
            "symbol": "NIFTY50",
            "date": close.index.strftime("%Y-%m-%d"),
            "open": close.values,
            "high": close.values,
            "low": close.values,
            "close": close.values,
            "volume": 0,
            "sma_50": close.rolling(50).mean().values,
            "sma_200": close.rolling(200).mean().values,
            "high_52w": close.rolling(252).max().values,
            "drawdown": (close / close.rolling(252).max() - 1.0).values
        })
        
        records = [
            (
                row["symbol"], row["date"],
                float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"]),
                float(row["sma_50"]) if pd.notna(row["sma_50"]) else None,
                float(row["sma_200"]) if pd.notna(row["sma_200"]) else None,
                float(row["high_52w"]) if pd.notna(row["high_52w"]) else None,
                float(row["drawdown"]) if pd.notna(row["drawdown"]) else None
            )
            for _, row in df.iterrows()
        ]

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", records)
        conn.commit()
        conn.close()

        print(f"[BENCHMARK OK] Nifty 50 downloaded: {len(records)} rows.", flush=True)
    except Exception as e:
        print(f"[BENCHMARK WARN] Failed to download Nifty 50: {e}", flush=True)

def main():
    print("=" * 70, flush=True)
    print("  FAST CHUNKED HISTORICAL PRICE DOWNLOADER (YFINANCE)  ", flush=True)
    print("=" * 70, flush=True)

    init_price_table()
    download_benchmark()

    conn = sqlite3.connect(DB_PATH)
    symbols = [row[0] for row in conn.execute("SELECT symbol FROM company_master").fetchall()]
    conn.close()

    print(f"Total symbols to process: {len(symbols)}", flush=True)

    # Chunk symbols into groups of 50
    chunks = [symbols[i:i + CHUNK_SIZE] for i in range(0, len(symbols), CHUNK_SIZE)]
    total_saved_rows = 0

    for i, chunk in enumerate(chunks, 1):
        tickers = [f"{s}.NS" for s in chunk]
        print(f"[CHUNK {i}/{len(chunks)}] Downloading batch of {len(tickers)} stocks...", flush=True)
        
        try:
            data = yf.download(tickers, start=START_DATE, end=END_DATE, group_by='ticker', auto_adjust=True, progress=False, threads=True)
            
            chunk_records = []
            for sym in chunk:
                tk = f"{sym}.NS"
                try:
                    if len(chunk) == 1:
                        df = data.copy()
                    else:
                        if tk not in data.columns.levels[0]:
                            continue
                        df = data[tk].dropna(how='all').copy()

                    if df.empty or 'Close' not in df.columns:
                        continue

                    close = df['Close'].dropna()
                    if close.empty:
                        continue

                    sub_df = pd.DataFrame({
                        'open': df['Open'],
                        'high': df['High'],
                        'low': df['Low'],
                        'close': close,
                        'volume': df['Volume']
                    }).dropna(subset=['close'])

                    sub_df['symbol'] = sym
                    sub_df['date'] = sub_df.index.strftime('%Y-%m-%d')
                    sub_df['sma_50'] = sub_df['close'].rolling(50).mean()
                    sub_df['sma_200'] = sub_df['close'].rolling(200).mean()
                    sub_df['high_52w'] = sub_df['close'].rolling(252).max()
                    sub_df['drawdown'] = (sub_df['close'] / sub_df['high_52w']) - 1.0

                    for _, row in sub_df.iterrows():
                        chunk_records.append((
                            row['symbol'], row['date'],
                            float(row['open']) if pd.notna(row['open']) else float(row['close']),
                            float(row['high']) if pd.notna(row['high']) else float(row['close']),
                            float(row['low']) if pd.notna(row['low']) else float(row['close']),
                            float(row['close']),
                            float(row['volume']) if pd.notna(row['volume']) else 0.0,
                            float(row['sma_50']) if pd.notna(row['sma_50']) else None,
                            float(row['sma_200']) if pd.notna(row['sma_200']) else None,
                            float(row['high_52w']) if pd.notna(row['high_52w']) else None,
                            float(row['drawdown']) if pd.notna(row['drawdown']) else None
                        ))
                except Exception as e:
                    continue

            if chunk_records:
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", chunk_records)
                conn.commit()
                conn.close()
                total_saved_rows += len(chunk_records)
                print(f"[CHUNK {i}/{len(chunks)} SUCCESS] Saved {len(chunk_records):,} records. Cumulative: {total_saved_rows:,}", flush=True)

        except Exception as e:
            print(f"[CHUNK {i} ERROR] {e}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print(f"HISTORICAL PRICE DOWNLOAD COMPLETE: {total_saved_rows:,} records saved into DB.", flush=True)
    print("=" * 70, flush=True)

if __name__ == "__main__":
    main()
