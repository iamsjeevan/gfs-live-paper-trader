import sqlite3
import pandas as pd
import numpy as np
import requests
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

DB_NAME = "instocks.db"
START_YEAR = 2014
END_YEAR = 2026
MAX_WORKERS = 10
SEC_HEADERS = {'User-Agent': 'InvestmentResearch admin@quantfirm.com'}

db_lock = threading.Lock()
NON_EQUITY_TICKERS = {'SPY', 'QQQ', 'VOO', 'IVV', 'IWM', 'TLT', 'AGG', 'BND', 'GLD', 'SLV', 'VTI', 'VEA', 'VWO', 'EFA', 'EEM'}

def fetch_target_tickers_and_cik_map():
    print("=" * 80, flush=True)
    print("STEP 1: FETCHING S&P 500 & S&P 400 EQUITIES AND MAPPING TO SEC CIKs...", flush=True)
    print("=" * 80, flush=True)

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    # 1. Fetch S&P 500 & S&P 400 Tickers
    r500 = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', headers=headers)
    df500 = pd.read_html(io.StringIO(r500.text))[0]
    sp500_symbols = df500['Symbol'].str.replace('.', '-', regex=False).tolist()

    r400 = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_400_companies', headers=headers)
    df400 = pd.read_html(io.StringIO(r400.text))[0]
    ticker_col = 'Ticker symbol' if 'Ticker symbol' in df400.columns else 'Symbol'
    sp400_symbols = df400[ticker_col].str.replace('.', '-', regex=False).tolist()

    target_tickers = sorted(list(set(sp500_symbols + sp400_symbols) - NON_EQUITY_TICKERS))

    # 2. Fetch Official SEC CIK Mapping
    r_cik = requests.get('https://www.sec.gov/files/company_tickers.json', headers=SEC_HEADERS)
    sec_ciks = r_cik.json()

    ticker_to_cik = {}
    for entry in sec_ciks.values():
        tk = entry['ticker'].upper().replace('.', '-')
        cik = entry['cik_str']
        ticker_to_cik[tk] = f"{cik:010d}"

    matched_map = {tk: ticker_to_cik[tk] for tk in target_tickers if tk in ticker_to_cik}
    print(f"[CIK MATCH OK] Target Equities: {len(target_tickers)} | Matched to SEC CIKs: {len(matched_map)}", flush=True)
    return matched_map

def init_database():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

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

    cur.execute("CREATE INDEX IF NOT EXISTS idx_bs_ticker_date ON balance_sheets(Ticker, Date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_inc_ticker_date ON income_statements(Ticker, Date);")

    conn.commit()
    conn.close()

def extract_sec_fact_series(us_gaap_facts, possible_concept_keys, target_form='10-K'):
    for concept in possible_concept_keys:
        if concept in us_gaap_facts:
            units = us_gaap_facts[concept].get('units', {})
            usd_entries = units.get('USD', [])
            if not usd_entries:
                continue

            filtered_entries = {}
            for entry in usd_entries:
                form = entry.get('form', '')
                fy = entry.get('fy')
                val = entry.get('val')
                end_date = entry.get('end', '')

                if form == target_form and fy is not None and START_YEAR <= fy <= END_YEAR:
                    date_key = end_date[:10] if end_date else f"{fy}-12-31"
                    filtered_entries[date_key] = float(val)

            if filtered_entries:
                return filtered_entries
    return {}

def download_sec_facts_for_company(item):
    ticker, cik_str = item
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_str}.json"
    
    try:
        r = requests.get(url, headers=SEC_HEADERS, timeout=10)
        if r.status_code != 200:
            return False

        facts_json = r.json()
        us_gaap = facts_json.get('facts', {}).get('us-gaap', {})
        if not us_gaap:
            return False

        # 1. Income Statement Concepts
        rev_dict = extract_sec_fact_series(us_gaap, ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet'])
        net_inc_dict = extract_sec_fact_series(us_gaap, ['NetIncomeLoss', 'ProfitLoss'])
        op_inc_dict = extract_sec_fact_series(us_gaap, ['OperatingIncomeLoss'])
        gross_prof_dict = extract_sec_fact_series(us_gaap, ['GrossProfit'])

        # 2. Balance Sheet Concepts
        assets_dict = extract_sec_fact_series(us_gaap, ['Assets'])
        liab_dict = extract_sec_fact_series(us_gaap, ['Liabilities', 'LiabilitiesAndStockholdersEquity'])
        equity_dict = extract_sec_fact_series(us_gaap, ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'])

        # Collect unique filing dates across all metrics
        all_dates = sorted(list(set(
            list(rev_dict.keys()) + list(net_inc_dict.keys()) + list(op_inc_dict.keys()) +
            list(assets_dict.keys()) + list(liab_dict.keys()) + list(equity_dict.keys())
        )))

        if not all_dates:
            return False

        inc_records = []
        bs_records = []

        for d in all_dates:
            inc_records.append((
                ticker, d,
                rev_dict.get(d),
                net_inc_dict.get(d),
                op_inc_dict.get(d),
                gross_prof_dict.get(d),
                None  # EBITDA
            ))

            bs_records.append((
                ticker, d,
                assets_dict.get(d),
                liab_dict.get(d),
                equity_dict.get(d),
                None, None, None
            ))

        with db_lock:
            conn = sqlite3.connect(DB_NAME)
            cur = conn.cursor()
            cur.executemany("INSERT OR REPLACE INTO income_statements VALUES (?, ?, ?, ?, ?, ?, ?)", inc_records)
            cur.executemany("INSERT OR REPLACE INTO balance_sheets VALUES (?, ?, ?, ?, ?, ?, ?, ?)", bs_records)
            conn.commit()
            conn.close()

        return True

    except Exception as e:
        return False

def main():
    print("=" * 80, flush=True)
    print("      DOWNLOAD 10+ YEARS SEC EDGAR FUNDAMENTALS INTO instocks.db      ", flush=True)
    print("=" * 80, flush=True)

    init_database()
    ticker_to_cik = fetch_target_tickers_and_cik_map()
    items = list(ticker_to_cik.items())

    print(f"\n[SEC EDGAR FETCH] Downloading 10+ years historical 10-K filings for {len(items)} US equities...", flush=True)

    completed = 0
    success = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_sec_facts_for_company, item): item[0] for item in items}
        for future in as_completed(futures):
            completed += 1
            if future.result():
                success += 1
            if completed % 50 == 0 or completed == len(items):
                print(f"[SEC PROGRESS] Processed {completed}/{len(items)} companies (Successful: {success})", flush=True)

    print("\n" + "=" * 80, flush=True)
    print("      VERIFICATION SUMMARY & DATABASE ROW COUNTS (instocks.db)      ", flush=True)
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
    print(f"SEC FUNDAMENTALS PIPELINE COMPLETE! SQLite Database: {DB_NAME}", flush=True)

if __name__ == "__main__":
    main()
