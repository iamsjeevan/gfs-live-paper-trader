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
SEC_HEADERS = {'User-Agent': 'InvestmentResearch admin@quantfirm.com'}
NON_EQUITY_TICKERS = {'SPY', 'QQQ', 'VOO', 'IVV', 'IWM', 'TLT', 'AGG', 'BND', 'GLD', 'SLV', 'VTI', 'VEA', 'VWO', 'EFA', 'EEM'}

db_lock = threading.Lock()

def fetch_smallcap_tickers_and_ciks():
    print("=" * 85, flush=True)
    print("STEP 1: FETCHING S&P 600 SMALL-CAP EQUITIES & MAPPING TO SEC CIKs...", flush=True)
    print("=" * 85, flush=True)

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    # S&P 600 Small-Cap
    r600 = requests.get('https://en.wikipedia.org/wiki/List_of_S%26P_600_companies', headers=headers)
    df600 = pd.read_html(io.StringIO(r600.text))[0]
    ticker_col = 'Symbol' if 'Symbol' in df600.columns else 'Ticker symbol'
    sp600_symbols = df600[ticker_col].str.replace('.', '-', regex=False).tolist()

    smallcap_tickers = sorted(list(set(sp600_symbols) - NON_EQUITY_TICKERS))

    # Fetch SEC CIK map
    r_cik = requests.get('https://www.sec.gov/files/company_tickers.json', headers=SEC_HEADERS)
    sec_ciks = r_cik.json()

    ticker_to_cik = {}
    for entry in sec_ciks.values():
        tk = entry['ticker'].upper().replace('.', '-')
        cik = entry['cik_str']
        ticker_to_cik[tk] = f"{cik:010d}"

    matched_map = {tk: ticker_to_cik[tk] for tk in smallcap_tickers if tk in ticker_to_cik}
    print(f"[SMALL-CAP OK] S&P 600 Small-Caps: {len(smallcap_tickers)} | Matched to SEC CIKs: {len(matched_map)}", flush=True)
    return matched_map

def download_smallcap_prices(smallcap_tickers):
    print("\n" + "=" * 85, flush=True)
    print("STEP 2: DOWNLOADING SMALL-CAP DAILY PRICES & VOLUME (2020 TO PRESENT)...", flush=True)
    print("=" * 85, flush=True)

    chunks = [smallcap_tickers[i:i + CHUNK_SIZE] for i in range(0, len(smallcap_tickers), CHUNK_SIZE)]
    total_saved_rows = 0

    for i, chunk in enumerate(chunks, 1):
        print(f"[SMALL-CAP PRICE CHUNK {i}/{len(chunks)}] Fetching batch of {len(chunk)} tickers...", flush=True)
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
                print(f"[SMALL-CAP PRICE CHUNK {i} SUCCESS] Saved {len(chunk_records):,} price rows.", flush=True)
        except Exception as e:
            print(f"[SMALL-CAP PRICE CHUNK {i} WARN] Error: {e}", flush=True)

    print(f"[SMALL-CAP PRICES OK] Total saved daily price records: {total_saved_rows:,}", flush=True)

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

                if form == target_form and fy is not None and 2014 <= fy <= 2026:
                    date_key = end_date[:10] if end_date else f"{fy}-12-31"
                    filtered_entries[date_key] = float(val)

            if filtered_entries:
                return filtered_entries
    return {}

def download_sec_facts_for_smallcap(item):
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

        rev_dict = extract_sec_fact_series(us_gaap, ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet'])
        net_inc_dict = extract_sec_fact_series(us_gaap, ['NetIncomeLoss', 'ProfitLoss'])
        op_inc_dict = extract_sec_fact_series(us_gaap, ['OperatingIncomeLoss'])
        gross_prof_dict = extract_sec_fact_series(us_gaap, ['GrossProfit'])

        assets_dict = extract_sec_fact_series(us_gaap, ['Assets'])
        liab_dict = extract_sec_fact_series(us_gaap, ['Liabilities', 'LiabilitiesAndStockholdersEquity'])
        equity_dict = extract_sec_fact_series(us_gaap, ['StockholdersEquity', 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'])

        all_dates = sorted(list(set(
            list(rev_dict.keys()) + list(net_inc_dict.keys()) + list(op_inc_dict.keys()) +
            list(assets_dict.keys()) + list(liab_dict.keys()) + list(equity_dict.keys())
        )))

        if not all_dates:
            return False

        inc_records = []
        bs_records = []

        for d in all_dates:
            inc_records.append((ticker, d, rev_dict.get(d), net_inc_dict.get(d), op_inc_dict.get(d), gross_prof_dict.get(d), None))
            bs_records.append((ticker, d, assets_dict.get(d), liab_dict.get(d), equity_dict.get(d), None, None, None))

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

def download_smallcap_sec_fundamentals(smallcap_map):
    print("\n" + "=" * 85, flush=True)
    print("STEP 3: EXTRACTING SEC EDGAR 10-K FILINGS FOR SMALL-CAPS (2014 - 2026)...", flush=True)
    print("=" * 85, flush=True)

    items = list(smallcap_map.items())
    completed = 0
    success = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_sec_facts_for_smallcap, item): item[0] for item in items}
        for future in as_completed(futures):
            completed += 1
            if future.result():
                success += 1
            if completed % 50 == 0 or completed == len(items):
                print(f"[SMALL-CAP SEC PROGRESS] Processed {completed}/{len(items)} companies (Successful: {success})", flush=True)

    print(f"[SMALL-CAP SEC OK] Completed processing {success}/{len(items)} small-cap companies.", flush=True)

def verify_and_summarize():
    print("\n" + "=" * 85, flush=True)
    print("STEP 4: UPDATED instocks.db SUMMARY (S&P 500 + S&P 400 + S&P 600 SMALL-CAPS)", flush=True)
    print("=" * 85, flush=True)

    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    tables = ['daily_prices', 'balance_sheets', 'income_statements', 'cash_flows', 'company_metrics']
    summary = []

    for t in tables:
        count = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        tickers_count = cur.execute(f"SELECT COUNT(DISTINCT Ticker) FROM {t}").fetchone()[0]
        summary.append({'Table Name': t, 'Total Records': f"{count:,}", 'Unique US Tickers': f"{tickers_count:,}"})

    conn.close()

    summary_df = pd.DataFrame(summary)
    print(summary_df.to_string(index=False), flush=True)
    print("=" * 85, flush=True)
    print(f"EXPANDED US SMALL-CAP PIPELINE COMPLETE! SQLite Database: {DB_NAME}", flush=True)

def main():
    smallcap_map = fetch_smallcap_tickers_and_ciks()
    download_smallcap_prices(list(smallcap_map.keys()))
    download_smallcap_sec_fundamentals(smallcap_map)
    verify_and_summarize()

if __name__ == "__main__":
    main()
