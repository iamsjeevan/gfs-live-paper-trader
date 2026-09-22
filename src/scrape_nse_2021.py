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
DB_PATH = "data/nse_stocks_2021.db"
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
    """Create fresh database schema with full comprehensive fundamental data."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"[DB INIT] Removed old database at {DB_PATH}", flush=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fundamental_data_2021 (
        symbol TEXT PRIMARY KEY,
        company_name TEXT,
        sc_id TEXT,
        mc_url_slug TEXT,
        sector TEXT,
        sub_sector TEXT,
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
        
        -- 2021 Income Statement
        revenue_2021 REAL,
        other_income_2021 REAL,
        total_revenue_2021 REAL,
        cost_of_materials_2021 REAL,
        employee_cost_2021 REAL,
        finance_costs_2021 REAL,
        depreciation_2021 REAL,
        other_expenses_2021 REAL,
        total_expenses_2021 REAL,
        pbt_2021 REAL,
        tax_expense_2021 REAL,
        net_profit_2021 REAL,
        eps_2021 REAL,
        diluted_eps_2021 REAL,
        
        -- 2021 Balance Sheet
        share_capital_2021 REAL,
        reserves_surplus_2021 REAL,
        equity_net_worth_2021 REAL,
        long_term_debt_2021 REAL,
        short_term_debt_2021 REAL,
        total_debt_2021 REAL,
        total_non_current_liabilities_2021 REAL,
        total_current_liabilities_2021 REAL,
        tangible_assets_2021 REAL,
        intangible_assets_2021 REAL,
        non_current_investments_2021 REAL,
        current_investments_2021 REAL,
        inventories_2021 REAL,
        trade_receivables_2021 REAL,
        cash_equivalents_2021 REAL,
        total_current_assets_2021 REAL,
        total_non_current_assets_2021 REAL,
        total_assets_2021 REAL,
        
        -- 2021 Financial Ratios
        roe_2021 REAL,
        roce_2021 REAL,
        debt_equity_2021 REAL,
        current_ratio_2021 REAL,
        net_margin_2021 REAL,
        
        -- Raw Financial Statement JSON dumps
        raw_pl_json_2021 TEXT,
        raw_bs_json_2021 TEXT,
        scraped_at TEXT
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS technical_data_2021 (
        symbol TEXT PRIMARY KEY,
        company_name TEXT,
        sc_id TEXT,
        mc_url_slug TEXT,
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
    print("[DB INIT] Fresh comprehensive database schema created successfully.", flush=True)

def load_2021_universe():
    """Load and merge 2021 Bhavcopy with Equity Master to avoid survivorship bias."""
    print("[UNIVERSE] Loading 2021 Bhavcopy and Equity Master...", flush=True)
    
    bhav_df = pd.read_csv(BHAVCOPY_PATH)
    bhav_df.columns = bhav_df.columns.str.strip()
    
    # Filter for Equity series (EQ)
    eq_bhav = bhav_df[bhav_df['SERIES'] == 'EQ'].copy()
    print(f"[UNIVERSE] Found {len(eq_bhav)} active EQ stocks in 2021 Bhavcopy.", flush=True)
    
    eq_master = pd.read_csv(EQUITY_MASTER_PATH)
    eq_master.columns = eq_master.columns.str.strip()
    
    # Merge on SYMBOL or ISIN
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
    """Scrape full fundamental and technical metrics for a single stock."""
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

    # Valuation & Header Fields
    sector, sub_sector = None, None
    mkt_cap, pe, pb, ind_pe, book_value = None, None, None, None, None
    cash_eps, div_yield, div_rate, face_value, shares_out = None, None, None, None, None

    # 2021 Income Statement Fields
    rev_2021, oth_inc_2021, tot_rev_2021 = None, None, None
    cost_mat_2021, emp_cost_2021, fin_cost_2021 = None, None, None
    depr_2021, oth_exp_2021, tot_exp_2021 = None, None, None
    pbt_2021, tax_2021, net_profit_2021 = None, None, None
    eps_2021, dil_eps_2021 = None, None

    # 2021 Balance Sheet Fields
    sh_cap_2021, res_surp_2021, equity_2021 = None, None, None
    lt_debt_2021, st_debt_2021, tot_debt_2021 = None, None, None
    tot_non_curr_liab_2021, tot_curr_liab_2021 = None, None
    tangible_ast_2021, intangible_ast_2021 = None, None
    non_curr_inv_2021, curr_inv_2021 = None, None
    inventories_2021, debtors_2021, cash_2021 = None, None, None
    tot_curr_ast_2021, tot_non_curr_ast_2021, tot_ast_2021 = None, None, None

    # 2021 Derived Ratios
    roe_2021, roce_2021, debt_eq_2021, curr_ratio_2021, net_margin_2021 = None, None, None, None, None

    # Raw JSON dumps
    raw_pl_json, raw_bs_json = None, None

    # Technical fields
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

    # 3. Scrape 2021 Profit & Loss
    try:
        pl_url = f"https://api.moneycontrol.com/mcapi/v1/quarterly-earning/profit-loss?sc_id={sc_id}&deviceType=W"
        pl_res = session.get(pl_url, headers=HEADERS, timeout=8)
        if pl_res.status_code == 200:
            pl_json = pl_res.json()
            pl_items = pl_json.get("data", {}).get("standardResult", [])
            for item in pl_items:
                if str(item.get("str_year")) == "2021" or item.get("yrc") == 202103:
                    raw_pl_json = json.dumps(item)
                    rev_2021 = to_float(item.get("RevenueFromOperationsNet") or item.get("InterestEarned") or item.get("TotalIncome"))
                    oth_inc_2021 = to_float(item.get("OtherIncome"))
                    tot_rev_2021 = to_float(item.get("TotalRevenue") or item.get("TotalIncome"))
                    if tot_rev_2021 is None:
                        if rev_2021 is not None and oth_inc_2021 is not None:
                            tot_rev_2021 = rev_2021 + oth_inc_2021
                        else:
                            tot_rev_2021 = rev_2021 or oth_inc_2021

                    cost_mat_2021 = to_float(item.get("CostOfMaterialsConsumed"))
                    emp_cost_2021 = to_float(item.get("EmployeeBenefitExpenses"))
                    fin_cost_2021 = to_float(item.get("FinanceCosts"))
                    depr_2021 = to_float(item.get("DepreciationAndAmortisationExpenses"))
                    oth_exp_2021 = to_float(item.get("OtherExpenses"))
                    tot_exp_2021 = to_float(item.get("TotalExpenses"))
                    pbt_2021 = to_float(item.get("ProfitLossBeforeTax"))
                    tax_2021 = to_float(item.get("TotalTaxExpensesContinuedOperations"))
                    net_profit_2021 = to_float(item.get("ProfitLossForThePeriod"))
                    eps_2021 = to_float(item.get("BasicEPS"))
                    dil_eps_2021 = to_float(item.get("DilutedEPS"))
                    break
    except Exception as e:
        print(f"[WARN] {symbol} P&L fetch error: {e}", flush=True)

    # 4. Scrape 2021 Balance Sheet
    try:
        bs_url = f"https://api.moneycontrol.com/mcapi/v1/quarterly-earning/balance-sheet?sc_id={sc_id}&deviceType=W"
        bs_res = session.get(bs_url, headers=HEADERS, timeout=8)
        if bs_res.status_code == 200:
            bs_json = bs_res.json()
            bs_items = bs_json.get("data", {}).get("standardResult", [])
            for item in bs_items:
                if str(item.get("str_year")) == "2021" or item.get("yrc") == 202103:
                    raw_bs_json = json.dumps(item)
                    sh_cap_2021 = to_float(item.get("TotalShareCapital") or item.get("EquityCapital"))
                    res_surp_2021 = to_float(item.get("ReservesAndSurplus") or item.get("TotalReservesAndSurplus"))
                    equity_2021 = to_float(item.get("TotalShareHoldersFunds"))
                    lt_debt_2021 = to_float(item.get("LongTermBorrowings"))
                    st_debt_2021 = to_float(item.get("ShortTermBorrowings"))
                    tot_debt_2021 = (lt_debt_2021 or 0) + (st_debt_2021 or 0) if (lt_debt_2021 is not None or st_debt_2021 is not None) else None
                    tot_non_curr_liab_2021 = to_float(item.get("TotalNonCurrentLiabilities"))
                    tot_curr_liab_2021 = to_float(item.get("TotalCurrentLiabilities"))
                    tangible_ast_2021 = to_float(item.get("TangibleAssets"))
                    intangible_ast_2021 = to_float(item.get("IntangibleAssets"))
                    non_curr_inv_2021 = to_float(item.get("NonCurrentInvestments"))
                    curr_inv_2021 = to_float(item.get("CurrentInvestments"))
                    inventories_2021 = to_float(item.get("Inventories"))
                    debtors_2021 = to_float(item.get("TradeReceivables"))
                    cash_2021 = to_float(item.get("CashAndCashEquivalents"))
                    tot_curr_ast_2021 = to_float(item.get("TotalCurrentAssets"))
                    tot_non_curr_ast_2021 = to_float(item.get("TotalNonCurrentAssets"))
                    tot_ast_2021 = to_float(item.get("TotalAssets"))
                    break
    except Exception as e:
        print(f"[WARN] {symbol} Balance Sheet fetch error: {e}", flush=True)

    # 5. Compute Financial Ratios
    if net_profit_2021 is not None and equity_2021 and equity_2021 > 0:
        roe_2021 = round((net_profit_2021 / equity_2021) * 100, 2)

    if pbt_2021 is not None and fin_cost_2021 is not None and equity_2021 and tot_debt_2021 is not None:
        capital_employed = equity_2021 + tot_debt_2021
        if capital_employed > 0:
            ebit = pbt_2021 + fin_cost_2021
            roce_2021 = round((ebit / capital_employed) * 100, 2)

    if tot_debt_2021 is not None and equity_2021 and equity_2021 > 0:
        debt_eq_2021 = round(tot_debt_2021 / equity_2021, 2)

    if tot_curr_ast_2021 and tot_curr_liab_2021 and tot_curr_liab_2021 > 0:
        curr_ratio_2021 = round(tot_curr_ast_2021 / tot_curr_liab_2021, 2)

    if net_profit_2021 is not None and tot_rev_2021 and tot_rev_2021 > 0:
        net_margin_2021 = round((net_profit_2021 / tot_rev_2021) * 100, 2)

    # 6. Scrape Technical Analysis Page
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

    fund_record = (
        symbol, company_name, sc_id, mc_slug, sector, sub_sector,
        mkt_cap, pe, pb, ind_pe, book_value, cash_eps, div_yield, div_rate, face_value, shares_out,
        rev_2021, oth_inc_2021, tot_rev_2021, cost_mat_2021, emp_cost_2021, fin_cost_2021,
        depr_2021, oth_exp_2021, tot_exp_2021, pbt_2021, tax_2021, net_profit_2021, eps_2021, dil_eps_2021,
        sh_cap_2021, res_surp_2021, equity_2021, lt_debt_2021, st_debt_2021, tot_debt_2021,
        tot_non_curr_liab_2021, tot_curr_liab_2021, tangible_ast_2021, intangible_ast_2021,
        non_curr_inv_2021, curr_inv_2021, inventories_2021, debtors_2021, cash_2021,
        tot_curr_ast_2021, tot_non_curr_ast_2021, tot_ast_2021,
        roe_2021, roce_2021, debt_eq_2021, curr_ratio_2021, net_margin_2021,
        raw_pl_json, raw_bs_json, timestamp
    )

    tech_record = (
        symbol, company_name, sc_id, mc_slug,
        sma_50, sma_200, rsi, high_52w, low_52w, timestamp
    )

    # 7. Thread-safe database write
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute("""
        INSERT OR REPLACE INTO fundamental_data_2021 VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?
        )
        """, fund_record)

        cursor.execute("""
        INSERT OR REPLACE INTO technical_data_2021 VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """, tech_record)
        
        conn.commit()
        conn.close()

    print(f"[SCRAPE OK & DB WRITE] {symbol} | MktCap: {mkt_cap} | P/E: {pe} | ROE: {roe_2021}% | ROCE: {roce_2021}% | Rev: {tot_rev_2021} | PAT: {net_profit_2021}", flush=True)
    return symbol

def main():
    print("=" * 70, flush=True)
    print("   NSE 2021 COMPREHENSIVE FUNDAMENTALS & TECHNICALS SCRAPER   ", flush=True)
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
    fund_cnt = cur.execute("SELECT COUNT(*) FROM fundamental_data_2021").fetchone()[0]
    tech_cnt = cur.execute("SELECT COUNT(*) FROM technical_data_2021").fetchone()[0]
    conn.close()

    print(f"Total Universe Processed: {total_stocks}", flush=True)
    print(f"Successfully Scraped & Resolved: {successful_scrapes}", flush=True)
    print(f"Fundamental Records in DB: {fund_cnt}", flush=True)
    print(f"Technical Records in DB: {tech_cnt}", flush=True)

if __name__ == "__main__":
    main()
