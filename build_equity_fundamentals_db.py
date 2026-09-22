import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

DB_NAME = "instocks.db"
START_DATE = "2020-01-01"
END_DATE = time.strftime("%Y-%m-%d")
MAX_WORKERS = 10
CHUNK_SIZE = 50

db_lock = threading.Lock()

# Non-equities to explicitly drop if present
NON_EQUITY_TICKERS = {'SPY', 'QQQ', 'VOO', 'IVV', 'IWM', 'TLT', 'AGG', 'BND', 'GLD', 'SLV', 'VTI', 'VEA', 'VWO', 'EFA', 'EEM'}

def fetch_equity_tickers():
    print("=" * 80, flush=True)
    print("STEP 1: FETCHING TOP ~1,000 ACTIVE US EQUITIES (S&P 500 & S&P 400)...", flush=True)
    print("=" * 80, flush=True)

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    # S&P 500
    r500 = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers=headers)
    df500 = pd.read_html(io.StringIO(r500.text))[0]
    sp500_symbols = df500['Symbol'].str.replace('.', '-', regex=False).tolist()

    # S&P 400 MidCap
    r400 = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_400_companies', headers=headers)
    df400 = pd.read_html(io.StringIO(r400.text))[0]
    ticker_col = 'Ticker symbol' if 'Ticker symbol' in df400.columns else 'Symbol'
    sp400_symbols = df400[ticker_col].str.replace('.', '-', regex=False).tolist()

    combined_tickers = set(sp500_symbols + sp400_symbols) - NON_EQUITY_TICKERS
    tickers = sorted(list(combined_tickers))

    print(f"[TICKERS OK] S&P 500 ({len(sp500_symbols)}) + S&P 400 ({len(sp400_symbols)}) = Total Combined Equities: {len(tickers)}", flush=True)
    return tickers

def init_database():
    print("\n" + "=" * 80, flush=True)
    print("STEP 2: INITIALIZING SQLITE DATABASE ARCHITECTURE (instocks.db)...", flush=True)
    print("=" * 80, flush=True)

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS daily_prices (
        Date TEXT,
        Ticker TEXT,
        Adj_Close REAL,
        Volume REAL,
        PRIMARY KEY (Ticker, Date)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS balance_sheets (
        Ticker TEXT,
        Date TEXT,
        Total_Assets REAL,
        Total_Liabilities REAL,
        Total_Equity REAL,
        Cash_And_Equivalents REAL,
        Long_Term_Debt REAL,
        Net_Debt REAL,
        PRIMARY KEY (Ticker, Date)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS income_statements (
        Ticker TEXT,
        Date TEXT,
        Total_Revenue REAL,
        Net_Income REAL,
        Operating_Income REAL,
        Gross_Profit REAL,
        EBITDA REAL,
        PRIMARY KEY (Ticker, Date)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cash_flows (
        Ticker TEXT,
        Date TEXT,
        Operating_Cash_Flow REAL,
        Capital_Expenditures REAL,
        Free_Cash_Flow REAL,
        PRIMARY KEY (Ticker, Date)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS company_metrics (
        Ticker TEXT PRIMARY KEY,
        Market_Cap REAL,
        PE_Ratio REAL,
        PB_Ratio REAL,
        Debt_To_Equity REAL,
        ROE REAL,
        Sector TEXT,
        Industry TEXT
    );
    """)

    # Create Indexes for Backtest Query Optimization
    cur.execute("CREATE INDEX IF NOT EXISTS idx_price_ticker_date ON daily_prices(Ticker, Date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bs_ticker_date ON balance_sheets(Ticker, Date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inc_ticker_date ON income_statements(Ticker, Date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cf_ticker_date ON cash_flows(Ticker, Date);")

    conn.commit()
    conn.close()
    print("[DB INIT OK] Schema and indexes initialized successfully.", flush=True)

def download_daily_prices(tickers):
    print("\n" + "=" * 80, flush=True)
    print("STEP 3: DOWNLOADING HISTORICAL DAILY PRICES & VOLUME (2020 TO PRESENT)...", flush=True)
    print("=" * 80, flush=True)

    chunks = [tickers[i:i + CHUNK_SIZE] for i in range(0, len(tickers), CHUNK_SIZE)]
    total_saved_rows = 0

    for i, chunk in enumerate(chunks, 1):
        print(f"[PRICE CHUNK {i}/{len(chunks)}] Fetching batch of {len(chunk)} tickers...", flush=True)
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
                total_saved_rows += len(chunk_records)
                print(f"[PRICE CHUNK {i} SUCCESS] Saved {len(chunk_records):,} price rows. Cumulative: {total_saved_rows:,}", flush=True)
        except Exception as e:
            print(f"[PRICE CHUNK {i} WARN] Error downloading price batch: {e}", flush=True)

    print(f"[DAILY PRICES OK] Total saved daily price records: {total_saved_rows:,}", flush=True)

def safe_extract_metric(df, possible_keys):
    if df is None or df.empty:
        return None
    for key in possible_keys:
        if key in df.index:
            return df.loc[key]
    return None

def process_single_ticker_fundamentals(ticker_symbol):
    try:
        tk = yf.Ticker(ticker_symbol)
        
        # 1. Balance Sheet
        bs_df = tk.balance_sheet
        if bs_df is None or bs_df.empty:
            bs_df = tk.quarterly_balance_sheet

        bs_records = []
        if bs_df is not None and not bs_df.empty:
            tot_assets = safe_extract_metric(bs_df, ['Total Assets'])
            tot_liab = safe_extract_metric(bs_df, ['Total Liabilities Net Minority Interest', 'Total Debt'])
            tot_equity = safe_extract_metric(bs_df, ['Stockholders Equity', 'Total Equity Gross Minority Interest'])
            cash_eq = safe_extract_metric(bs_df, ['Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments'])
            lt_debt = safe_extract_metric(bs_df, ['Long Term Debt', 'Long Term Debt And Capital Lease Obligation'])
            net_debt = safe_extract_metric(bs_df, ['Net Debt'])

            for date_col in bs_df.columns:
                date_str = date_col.strftime('%Y-%m-%d') if hasattr(date_col, 'strftime') else str(date_col)[:10]
                
                get_val = lambda ser: float(ser[date_col]) if (ser is not None and date_col in ser.index and pd.notna(ser[date_col])) else None

                bs_records.append((
                    ticker_symbol, date_str,
                    get_val(tot_assets), get_val(tot_liab), get_val(tot_equity),
                    get_val(cash_eq), get_val(lt_debt), get_val(net_debt)
                ))

        # 2. Income Statement
        inc_df = tk.financials
        if inc_df is None or inc_df.empty:
            inc_df = tk.quarterly_financials

        inc_records = []
        if inc_df is not None and not inc_df.empty:
            tot_rev = safe_extract_metric(inc_df, ['Total Revenue', 'Operating Revenue'])
            net_inc = safe_extract_metric(inc_df, ['Net Income Common Stockholders', 'Net Income'])
            op_inc = safe_extract_metric(inc_df, ['Operating Income', 'EBIT'])
            gross_prof = safe_extract_metric(inc_df, ['Gross Profit'])
            ebitda = safe_extract_metric(inc_df, ['EBITDA', 'Normalized EBITDA'])

            for date_col in inc_df.columns:
                date_str = date_col.strftime('%Y-%m-%d') if hasattr(date_col, 'strftime') else str(date_col)[:10]
                get_val = lambda ser: float(ser[date_col]) if (ser is not None and date_col in ser.index and pd.notna(ser[date_col])) else None

                inc_records.append((
                    ticker_symbol, date_str,
                    get_val(tot_rev), get_val(net_inc), get_val(op_inc),
                    get_val(gross_prof), get_val(ebitda)
                ))

        # 3. Cash Flows
        cf_df = tk.cashflow
        if cf_df is None or cf_df.empty:
            cf_df = tk.quarterly_cashflow

        cf_records = []
        if cf_df is not None and not cf_df.empty:
            op_cf = safe_extract_metric(cf_df, ['Operating Cash Flow'])
            cap_exp = safe_extract_metric(cf_df, ['Capital Expenditure'])
            fcf = safe_extract_metric(cf_df, ['Free Cash Flow'])

            for date_col in cf_df.columns:
                date_str = date_col.strftime('%Y-%m-%d') if hasattr(date_col, 'strftime') else str(date_col)[:10]
                get_val = lambda ser: float(ser[date_col]) if (ser is not None and date_col in ser.index and pd.notna(ser[date_col])) else None

                cf_records.append((
                    ticker_symbol, date_str,
                    get_val(op_cf), get_val(cap_exp), get_val(fcf)
                ))

        # 4. Company Metrics
        info = tk.info or {}
        company_metric_tuple = (
            ticker_symbol,
            float(info['marketCap']) if info.get('marketCap') is not None else None,
            float(info['trailingPE']) if info.get('trailingPE') is not None else float(info['forwardPE']) if info.get('forwardPE') is not None else None,
            float(info['priceToBook']) if info.get('priceToBook') is not None else None,
            float(info['debtToEquity']) if info.get('debtToEquity') is not None else None,
            float(info['returnOnEquity']) if info.get('returnOnEquity') is not None else None,
            str(info.get('sector')) if info.get('sector') else None,
            str(info.get('industry')) if info.get('industry') else None
        )

        with db_lock:
            conn = sqlite3.connect(DB_NAME)
            cur = conn.cursor()
            
            if bs_records:
                cur.executemany("INSERT OR REPLACE INTO balance_sheets VALUES (?, ?, ?, ?, ?, ?, ?, ?)", bs_records)
            if inc_records:
                cur.executemany("INSERT OR REPLACE INTO income_statements VALUES (?, ?, ?, ?, ?, ?, ?)", inc_records)
            if cf_records:
                cur.executemany("INSERT OR REPLACE INTO cash_flows VALUES (?, ?, ?, ?, ?)", cf_records)
            
            cur.execute("INSERT OR REPLACE INTO company_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?)", company_metric_tuple)
            
            conn.commit()
            conn.close()

        return True
    except Exception as e:
        return False

def download_all_fundamentals(tickers):
    print("\n" + "=" * 80, flush=True)
    print("STEP 4: EXTRACTING FINANCIAL STATEMENTS & KEY METRICS (yfinance.Ticker)...", flush=True)
    print("=" * 80, flush=True)

    completed = 0
    success = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_ticker_fundamentals, t): t for t in tickers}
        for future in as_completed(futures):
            completed += 1
            if future.result():
                success += 1
            if completed % 50 == 0 or completed == len(tickers):
                print(f"[FUNDAMENTALS PROGRESS] Processed {completed}/{len(tickers)} tickers (Successful: {success})", flush=True)

    print(f"[FUNDAMENTALS OK] Completed processing fundamentals for {success}/{len(tickers)} tickers.", flush=True)

def verify_and_summarize():
    print("\n" + "=" * 80, flush=True)
    print("STEP 5: VERIFICATION SUMMARY & DATABASE ROW COUNTS (instocks.db)", flush=True)
    print("=" * 80, flush=True)

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    tables = ['daily_prices', 'balance_sheets', 'income_statements', 'cash_flows', 'company_metrics']
    summary = []

    for t in tables:
        count = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        tickers_count = cur.execute(f"SELECT COUNT(DISTINCT Ticker) FROM {t}").fetchone()[0]
        summary.append({'Table Name': t, 'Total Records': f"{count:,}", 'Unique Tickers': f"{tickers_count:,}"})

    conn.close()

    summary_df = pd.DataFrame(summary)
    print(summary_df.to_string(index=False), flush=True)
    print("=" * 80, flush=True)
    print(f"DATABASE PIPELINE COMPLETE! Local SQLite database saved at: {DB_NAME}", flush=True)

def main():
    tickers = fetch_equity_tickers()
    init_database()
    download_daily_prices(tickers)
    download_all_fundamentals(tickers)
    verify_and_summarize()

if __name__ == "__main__":
    main()
