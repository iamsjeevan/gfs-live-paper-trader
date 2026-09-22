import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import io
import time

DB_NAME = "instocks.db"
START_DATE = "2007-01-01"
END_DATE = time.strftime("%Y-%m-%d")
CHUNK_SIZE = 50

def get_all_us_tickers():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    tickers = [row[0] for row in cur.execute("SELECT DISTINCT Ticker FROM company_metrics").fetchall()]
    conn.close()
    
    if not tickers:
        # Fallback to S&P 500 + 400 + 600 from wikipedia
        headers = {'User-Agent': 'Mozilla/5.0'}
        r500 = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers=headers)
        df500 = pd.read_html(io.StringIO(r500.text))[0]
        sp500 = df500['Symbol'].str.replace('.', '-', regex=False).tolist()

        r400 = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_400_companies', headers=headers)
        df400 = pd.read_html(io.StringIO(r400.text))[0]
        tc400 = 'Ticker symbol' if 'Ticker symbol' in df400.columns else 'Symbol'
        sp400 = df400[tc400].str.replace('.', '-', regex=False).tolist()

        r600 = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_600_companies', headers=headers)
        df600 = pd.read_html(io.StringIO(r600.text))[0]
        tc600 = 'Symbol' if 'Symbol' in df600.columns else 'Ticker symbol'
        sp600 = df600[tc600].str.replace('.', '-', regex=False).tolist()

        tickers = sorted(list(set(sp500 + sp400 + sp600)))

    return tickers

def download_2007_prices(tickers):
    print("=" * 85, flush=True)
    print("DOWNLOADING US DAILY PRICES & S&P 500 FROM 2007 TO PRESENT (2007 - 2026)...", flush=True)
    print("=" * 85, flush=True)

    all_tickers = tickers + ['^GSPC']
    chunks = [all_tickers[i:i + CHUNK_SIZE] for i in range(0, len(all_tickers), CHUNK_SIZE)]
    total_saved = 0

    for i, chunk in enumerate(chunks, 1):
        print(f"[PRICE CHUNK {i}/{len(chunks)}] Fetching 2007-2026 prices for {len(chunk)} tickers...", flush=True)
        try:
            data = yf.download(chunk, start=START_DATE, end=END_DATE, auto_adjust=True, progress=False, threads=True)
            chunk_records = []

            if isinstance(data.columns, pd.MultiIndex):
                close_df = data['Close']
                vol_df = data['Volume']
            else:
                close_df = pd.DataFrame({chunk[0]: data['Close']})
                vol_df = pd.DataFrame({chunk[0]: data['Volume']})

            for tk in chunk:
                if tk in close_df.columns:
                    tk_df = pd.DataFrame({
                        'Date': close_df.index.strftime('%Y-%m-%d'),
                        'Ticker': tk,
                        'Adj_Close': close_df[tk].values,
                        'Volume': vol_df[tk].values if tk in vol_df.columns else 0.0
                    }).dropna(subset=['Adj_Close'])

                    for _, row in tk_df.iterrows():
                        chunk_records.append((
                            str(row['Date']),
                            str(row['Ticker']),
                            float(row['Adj_Close']),
                            float(row['Volume']) if pd.notna(row['Volume']) else 0.0
                        ))

            if chunk_records:
                conn = sqlite3.connect(DB_NAME)
                cur = conn.cursor()
                cur.executemany("INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?, ?)", chunk_records)
                conn.commit()
                conn.close()
                total_saved += len(chunk_records)
                print(f"[PRICE CHUNK {i} SUCCESS] Saved {len(chunk_records):,} price rows. Cumulative: {total_saved:,}", flush=True)

        except Exception as e:
            print(f"[PRICE CHUNK {i} WARN] Error: {e}", flush=True)

    print(f"\n[2007 PRICES OK] Total saved daily price records in instocks.db: {total_saved:,}", flush=True)

def main():
    tickers = get_all_us_tickers()
    download_2007_prices(tickers)

if __name__ == "__main__":
    main()
