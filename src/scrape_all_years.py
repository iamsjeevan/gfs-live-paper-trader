import os
import sys
import re
import json
import sqlite3
import datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Force unbuffered stdout output
sys.stdout.reconfigure(line_buffering=True)

# Configuration
DB_PATH = "data/nse_stocks_all_years.db"
BHAVCOPY_PATH = "data/bhavcopy_2021.csv"
EQUITY_MASTER_PATH = "data/equity_master.csv"
MAX_WORKERS = 12
AUTOSUGGEST_URL = "https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*"
}

db_lock = threading.Lock()

def init_database():
    """Create fresh database schema for multi-year full financial data."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"[DB INIT] Removed old database at {DB_PATH}", flush=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Company Master
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS company_master (
        symbol TEXT PRIMARY KEY,
        company_name TEXT,
        sc_id TEXT,
        mc_url_slug TEXT,
        sector TEXT,
        sub_sector TEXT,
        isin TEXT,
        scraped_at TEXT
    );
    """)

    # 2. Income Statement (All Years)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS financial_income_statement (
        symbol TEXT,
        year INTEGER,
        str_year TEXT,
        yrc INTEGER,
        period_months TEXT,
        revenue_from_operations REAL,
        other_income REAL,
        total_revenue REAL,
        cost_of_materials REAL,
        purchase_of_stock_in_trade REAL,
        employee_cost REAL,
        finance_costs REAL,
        depreciation_amortisation REAL,
        other_expenses REAL,
        total_expenses REAL,
        profit_before_tax REAL,
        tax_expense REAL,
        net_profit REAL,
        eps_basic REAL,
        eps_diluted REAL,
        raw_pl_json TEXT,
        PRIMARY KEY (symbol, year)
    );
    """)

    # 3. Balance Sheet (All Years)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS financial_balance_sheet (
        symbol TEXT,
        year INTEGER,
        str_year TEXT,
        yrc INTEGER,
        share_capital REAL,
        reserves_surplus REAL,
        total_shareholders_funds REAL,
        long_term_borrowings REAL,
        short_term_borrowings REAL,
        total_debt REAL,
        trade_payables REAL,
        total_current_liabilities REAL,
        total_non_current_liabilities REAL,
        total_liabilities REAL,
        tangible_assets REAL,
        intangible_assets REAL,
        non_current_investments REAL,
        current_investments REAL,
        inventories REAL,
        trade_receivables REAL,
        cash_equivalents REAL,
        total_current_assets REAL,
        total_non_current_assets REAL,
        total_assets REAL,
        raw_bs_json TEXT,
        PRIMARY KEY (symbol, year)
    );
    """)

    # 4. Financial Ratios (All Years)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS financial_ratios (
        symbol TEXT,
        year INTEGER,
        roe REAL,
        roce REAL,
        debt_equity REAL,
        current_ratio REAL,
        net_margin REAL,
        operating_margin REAL,
        PRIMARY KEY (symbol, year)
    );
    """)

    # 5. Technical & Valuation Snapshot
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS technical_valuation_data (
        symbol TEXT PRIMARY KEY,
        company_name TEXT,
        sc_id TEXT,
        mc_url_slug TEXT,
        market_cap REAL,
        pe_ratio REAL,
        pb_ratio REAL,
        industry_pe REAL,
        book_value REAL,
        cash_eps REAL,
        dividend_yield REAL,
        dividend_rate REAL,
        face_value REAL,
        shares_outstanding REAL,
        sma_50 REAL,
        sma_200 REAL,
        rsi REAL,
        high_52w REAL,
        low_52w REAL,
        scraped_at TEXT
    );
    """)
    
    conn.commit()
    conn.close()
    print("[DB INIT] Multi-year comprehensive database schema created successfully.", flush=True)

def load_2021_universe():
    """Load and merge 2021 Bhavcopy with Equity Master."""
    print("[UNIVERSE] Loading 2021 Bhavcopy and Equity Master...", flush=True)
    
    bhav_df = pd.read_csv(BHAVCOPY_PATH)
    bhav_df.columns = bhav_df.columns.str.strip()
    
    eq_bhav = bhav_df[bhav_df['SERIES'] == 'EQ'].copy()
    print(f"[UNIVERSE] Found {len(eq_bhav)} active EQ stocks in 2021 Bhavcopy.", flush=True)
    
    eq_master = pd.read_csv(EQUITY_MASTER_PATH)
    eq_master.columns = eq_master.columns.str.strip()
    
    merged = pd.merge(
        eq_bhav,
        eq_master[['SYMBOL', 'NAME OF COMPANY', 'ISIN NUMBER']],
        on='SYMBOL',
        how='left'
    )
    
    universe = []
    for _, row in merged.iterrows():
        symbol = str(row['SYMBOL']).strip()
        comp_name = str(row['NAME OF COMPANY']).strip() if pd.notna(row['NAME OF COMPANY']) else symbol
        isin = str(row['ISIN']).strip() if pd.notna(row['ISIN']) else (str(row['ISIN NUMBER']).strip() if pd.notna(row['ISIN NUMBER']) else '')
        universe.append((symbol, comp_name, isin))
        
    print(f"[UNIVERSE] Universe loaded with {len(universe)} stocks.", flush=True)
    return universe

def to_float(val):
    """Safely convert value to float or None."""
    if val is None or val == '' or str(val).strip() in ['-', 'NA', 'null', 'None']:
        return None
    try:
        return float(str(val).replace(',', '').strip())
    except:
        return None

def resolve_moneycontrol_url(company_name, symbol, isin, session):
    """Lookup Moneycontrol internal URL slug & sc_id using Company Name."""
    queries = []
    if company_name and company_name != symbol:
        clean_name = re.sub(r'\b(Limited|Ltd|LTD|LIMITED|INC|CORP)\b', '', company_name, flags=re.IGNORECASE).strip()
        queries.append(company_name)
        if clean_name and clean_name != company_name:
            queries.append(clean_name)
    queries.append(symbol)

    for q in queries:
        params = {
            "classic": "true",
            "query": q,
            "type": "1",
            "format": "json",
            "callback": "suggest1"
        }
        try:
            r = session.get(AUTOSUGGEST_URL, params=params, headers=HEADERS, timeout=8)
            text = r.text
            if text.startswith("suggest1("):
                text = text[9:-1]
            data = json.loads(text)
            
            if not isinstance(data, list) or not data:
                continue

            for item in data:
                pdt = item.get("pdt_dis_nm", "")
                sc_id = item.get("sc_id") or item.get("id")
                link_src = item.get("link_src", "")

                if isin and isin in pdt:
                    slug = "/".join(link_src.strip("/").split("/")[-3:]) if link_src else None
                    return sc_id, slug, item.get("name") or item.get("stock_name")
                
                if symbol and (f", {symbol}," in pdt or f" {symbol} " in pdt or f">{symbol}<" in pdt or f", {symbol}<" in pdt):
                    slug = "/".join(link_src.strip("/").split("/")[-3:]) if link_src else None
                    return sc_id, slug, item.get("name") or item.get("stock_name")

            top_item = data[0]
            sc_id = top_item.get("sc_id") or top_item.get("id")
            link_src = top_item.get("link_src", "")
            slug = "/".join(link_src.strip("/").split("/")[-3:]) if link_src else None
            return sc_id, slug, top_item.get("name") or top_item.get("stock_name")

        except Exception:
            continue

    return None, None, None

def scrape_single_stock(stock_tuple):
    """Scrape all historical years for a single stock."""
    symbol, company_name, isin = stock_tuple
    session = requests.Session()
    timestamp = datetime.datetime.now().isoformat()

    print(f"[START] {symbol} | Company Name: '{company_name}'", flush=True)

    # 1. Company Name Lookup
    sc_id, mc_slug, mc_name = resolve_moneycontrol_url(company_name, symbol, isin, session)
    
    if not sc_id:
        print(f"[LOOKUP FAILED] {symbol} | Company Name query could not resolve Moneycontrol SC_ID.", flush=True)
        return None

    print(f"[LOOKUP SUCCESS] {symbol} -> SC_ID: '{sc_id}' | Slug: '{mc_slug}' | MC Name: '{mc_name}'", flush=True)

    # Valuation & Technical Header
    sector, sub_sector = None, None
    mkt_cap, pe, pb, ind_pe, book_value = None, None, None, None, None
    cash_eps, div_yield, div_rate, face_value, shares_out = None, None, None, None, None
    sma_50, sma_200, rsi, high_52w, low_52w = None, None, None, None, None

    # 2. Scrape Pricefeed Header API
    try:
        header_url = f"https://priceapi.moneycontrol.com/pricefeed/nse/equitycash/{sc_id}"
        h_res = session.get(header_url, headers=HEADERS, timeout=8)
        if h_res.status_code == 200:
            h_data = h_res.json().get("data", {})
            sector = h_data.get("main_sector")
            sub_sector = h_data.get("SC_SUBSEC")
            mkt_cap = to_float(h_data.get("MKTCAP"))
            pe = to_float(h_data.get("PE") or h_data.get("PECONS"))
            pb = to_float(h_data.get("PB") or h_data.get("PBCONS"))
            ind_pe = to_float(h_data.get("IND_PE"))
            book_value = to_float(h_data.get("BV") or h_data.get("BVCONS"))
            cash_eps = to_float(h_data.get("CEPS"))
            div_yield = to_float(h_data.get("DY") or h_data.get("DYCONS"))
            div_rate = to_float(h_data.get("DIVPR"))
            face_value = to_float(h_data.get("FV"))
            shares_out = to_float(h_data.get("SHRS"))
            sma_50 = to_float(h_data.get("50DayAvg"))
            sma_200 = to_float(h_data.get("200DayAvg"))
            high_52w = to_float(h_data.get("52H"))
            low_52w = to_float(h_data.get("52L"))
    except Exception as e:
        print(f"[WARN] {symbol} Header API error: {e}", flush=True)

    # 3. Scrape Technical Analysis Page
    try:
        tech_url = f"https://www.moneycontrol.com/technical-analysis/a/{sc_id}/daily"
        t_res = session.get(tech_url, headers=HEADERS, timeout=8)
        if t_res.status_code == 200:
            soup = BeautifulSoup(t_res.text, "html.parser")
            for tr in soup.find_all("tr"):
                text = tr.get_text()
                if "RSI(14)" in text:
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if len(cells) >= 2:
                        rsi = to_float(cells[1])
                if sma_50 is None and "50" in text and "SMA" in text:
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if len(cells) >= 2:
                        sma_50 = to_float(cells[1])
                if sma_200 is None and "200" in text and "SMA" in text:
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                    if len(cells) >= 2:
                        sma_200 = to_float(cells[1])
    except Exception as e:
        print(f"[WARN] {symbol} Technical page error: {e}", flush=True)

    # 4. Scrape ALL Historical Income Statements (P&L)
    pl_records_by_year = {}
    try:
        pl_url = f"https://api.moneycontrol.com/mcapi/v1/quarterly-earning/profit-loss?sc_id={sc_id}&deviceType=W"
        pl_res = session.get(pl_url, headers=HEADERS, timeout=8)
        if pl_res.status_code == 200:
            pl_json = pl_res.json()
            pl_items = pl_json.get("data", {}).get("standardResult", [])
            for item in pl_items:
                try:
                    str_year = str(item.get("str_year"))
                    yrc = item.get("yrc")
                    if not yrc or not str_year.isdigit():
                        continue
                    year = int(str(yrc)[:4])
                    
                    rev_ops = to_float(item.get("RevenueFromOperationsNet") or item.get("InterestEarned") or item.get("TotalIncome"))
                    oth_inc = to_float(item.get("OtherIncome"))
                    tot_rev = to_float(item.get("TotalRevenue") or item.get("TotalIncome"))
                    if tot_rev is None:
                        tot_rev = (rev_ops + oth_inc) if (rev_ops is not None and oth_inc is not None) else (rev_ops or oth_inc)

                    c_mat = to_float(item.get("CostOfMaterialsConsumed"))
                    purch_stock = to_float(item.get("PurchaseOfStockInTrade"))
                    emp_cost = to_float(item.get("EmployeeBenefitExpenses"))
                    fin_cost = to_float(item.get("FinanceCosts"))
                    depr = to_float(item.get("DepreciationAndAmortisationExpenses"))
                    oth_exp = to_float(item.get("OtherExpenses"))
                    tot_exp = to_float(item.get("TotalExpenses"))
                    pbt = to_float(item.get("ProfitLossBeforeTax"))
                    tax_exp = to_float(item.get("TotalTaxExpensesContinuedOperations"))
                    net_prof = to_float(item.get("ProfitLossForThePeriod"))
                    eps = to_float(item.get("BasicEPS"))
                    dil_eps = to_float(item.get("DilutedEPS"))
                    period_m = item.get("noofmonths")

                    pl_records_by_year[year] = (
                        symbol, year, str_year, yrc, period_m,
                        rev_ops, oth_inc, tot_rev, c_mat, purch_stock, emp_cost,
                        fin_cost, depr, oth_exp, tot_exp, pbt, tax_exp, net_prof,
                        eps, dil_eps, json.dumps(item)
                    )
                except Exception:
                    continue
    except Exception as e:
        print(f"[WARN] {symbol} All P&L fetch error: {e}", flush=True)

    # 5. Scrape ALL Historical Balance Sheets
    bs_records_by_year = {}
    try:
        bs_url = f"https://api.moneycontrol.com/mcapi/v1/quarterly-earning/balance-sheet?sc_id={sc_id}&deviceType=W"
        bs_res = session.get(bs_url, headers=HEADERS, timeout=8)
        if bs_res.status_code == 200:
            bs_json = bs_res.json()
            bs_items = bs_json.get("data", {}).get("standardResult", [])
            for item in bs_items:
                try:
                    str_year = str(item.get("str_year"))
                    yrc = item.get("yrc")
                    if not yrc or not str_year.isdigit():
                        continue
                    year = int(str(yrc)[:4])

                    sh_cap = to_float(item.get("TotalShareCapital") or item.get("EquityCapital"))
                    res_surp = to_float(item.get("ReservesAndSurplus") or item.get("TotalReservesAndSurplus"))
                    equity = to_float(item.get("TotalShareHoldersFunds"))
                    lt_debt = to_float(item.get("LongTermBorrowings"))
                    st_debt = to_float(item.get("ShortTermBorrowings"))
                    tot_debt = (lt_debt or 0) + (st_debt or 0) if (lt_debt is not None or st_debt is not None) else None
                    trade_pay = to_float(item.get("TradePayables"))
                    tot_curr_liab = to_float(item.get("TotalCurrentLiabilities"))
                    tot_non_curr_liab = to_float(item.get("TotalNonCurrentLiabilities"))
                    tot_liab = to_float(item.get("TotalCapitalAndLiabilities"))
                    tangible_ast = to_float(item.get("TangibleAssets"))
                    intangible_ast = to_float(item.get("IntangibleAssets"))
                    non_curr_inv = to_float(item.get("NonCurrentInvestments"))
                    curr_inv = to_float(item.get("CurrentInvestments"))
                    inventories = to_float(item.get("Inventories"))
                    debtors = to_float(item.get("TradeReceivables"))
                    cash = to_float(item.get("CashAndCashEquivalents"))
                    tot_curr_ast = to_float(item.get("TotalCurrentAssets"))
                    tot_non_curr_ast = to_float(item.get("TotalNonCurrentAssets"))
                    tot_ast = to_float(item.get("TotalAssets"))

                    bs_records_by_year[year] = (
                        symbol, year, str_year, yrc,
                        sh_cap, res_surp, equity, lt_debt, st_debt, tot_debt,
                        trade_pay, tot_curr_liab, tot_non_curr_liab, tot_liab,
                        tangible_ast, intangible_ast, non_curr_inv, curr_inv,
                        inventories, debtors, cash, tot_curr_ast, tot_non_curr_ast, tot_ast,
                        json.dumps(item)
                    )
                except Exception:
                    continue
    except Exception as e:
        print(f"[WARN] {symbol} All Balance Sheet fetch error: {e}", flush=True)

    # 6. Compute Multi-Year Ratios
    ratio_records = []
    all_years = sorted(list(set(list(pl_records_by_year.keys()) + list(bs_records_by_year.keys()))))
    
    for y in all_years:
        pl_rec = pl_records_by_year.get(y)
        bs_rec = bs_records_by_year.get(y)

        net_prof = pl_rec[17] if pl_rec else None
        pbt = pl_rec[15] if pl_rec else None
        fin_cost = pl_rec[11] if pl_rec else None
        tot_rev = pl_rec[7] if pl_rec else None

        equity = bs_rec[6] if bs_rec else None
        tot_debt = bs_rec[9] if bs_rec else None
        tot_curr_ast = bs_rec[21] if bs_rec else None
        tot_curr_liab = bs_rec[11] if bs_rec else None

        roe, roce, debt_eq, curr_ratio, net_margin, op_margin = None, None, None, None, None, None

        if net_prof is not None and equity and equity > 0:
            roe = round((net_prof / equity) * 100, 2)

        if pbt is not None and fin_cost is not None and equity and tot_debt is not None:
            cap_emp = equity + tot_debt
            if cap_emp > 0:
                roce = round(((pbt + fin_cost) / cap_emp) * 100, 2)

        if tot_debt is not None and equity and equity > 0:
            debt_eq = round(tot_debt / equity, 2)

        if tot_curr_ast and tot_curr_liab and tot_curr_liab > 0:
            curr_ratio = round(tot_curr_ast / tot_curr_liab, 2)

        if net_prof is not None and tot_rev and tot_rev > 0:
            net_margin = round((net_prof / tot_rev) * 100, 2)

        ratio_records.append((symbol, y, roe, roce, debt_eq, curr_ratio, net_margin, op_margin))

    # Master and Technical Records
    company_record = (symbol, company_name, sc_id, mc_slug, sector, sub_sector, isin, timestamp)
    tech_record = (
        symbol, company_name, sc_id, mc_slug,
        mkt_cap, pe, pb, ind_pe, book_value, cash_eps, div_yield, div_rate, face_value, shares_out,
        sma_50, sma_200, rsi, high_52w, low_52w, timestamp
    )

    # 7. Thread-safe database write
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("INSERT OR REPLACE INTO company_master VALUES (?, ?, ?, ?, ?, ?, ?, ?)", company_record)
        cursor.execute("INSERT OR REPLACE INTO technical_valuation_data VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", tech_record)

        for rec in pl_records_by_year.values():
            cursor.execute("INSERT OR REPLACE INTO financial_income_statement VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rec)

        for rec in bs_records_by_year.values():
            cursor.execute("INSERT OR REPLACE INTO financial_balance_sheet VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rec)

        for rec in ratio_records:
            cursor.execute("INSERT OR REPLACE INTO financial_ratios VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rec)

        conn.commit()
        conn.close()

    years_str = f"{min(all_years)}-{max(all_years)}" if all_years else "None"
    print(f"[SCRAPE OK & DB WRITE] {symbol} | Years: {len(all_years)} ({years_str}) | MktCap: {mkt_cap} | P/E: {pe}", flush=True)
    return symbol

def main():
    print("=" * 70, flush=True)
    print("   NSE MULTI-YEAR COMPREHENSIVE FINANCIALS SCRAPER (MONEYCONTROL)   ", flush=True)
    print("=" * 70, flush=True)

    init_database()
    universe = load_2021_universe()
    
    total_stocks = len(universe)
    completed = 0
    successful_scrapes = 0

    print(f"\n[EXECUTION] Starting parallel scraping with {MAX_WORKERS} workers...\n", flush=True)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_stock = {executor.submit(scrape_single_stock, stock): stock for stock in universe}

        for future in as_completed(future_to_stock):
            completed += 1
            res = future.result()
            if res:
                successful_scrapes += 1
            print(f"--- [PROGRESS] {completed}/{total_stocks} stocks completed ({(completed/total_stocks)*100:.1f}%) ---", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("                      SCRAPING COMPLETE                            ", flush=True)
    print("=" * 70, flush=True)
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    comp_cnt = cur.execute("SELECT COUNT(*) FROM company_master").fetchone()[0]
    pl_cnt = cur.execute("SELECT COUNT(*) FROM financial_income_statement").fetchone()[0]
    bs_cnt = cur.execute("SELECT COUNT(*) FROM financial_balance_sheet").fetchone()[0]
    conn.close()

    print(f"Total Universe Processed: {total_stocks}", flush=True)
    print(f"Successfully Scraped & Resolved: {successful_scrapes}", flush=True)
    print(f"Companies in DB: {comp_cnt}", flush=True)
    print(f"Total Income Statement Rows (All Years): {pl_cnt}", flush=True)
    print(f"Total Balance Sheet Rows (All Years): {bs_cnt}", flush=True)

if __name__ == "__main__":
    main()
