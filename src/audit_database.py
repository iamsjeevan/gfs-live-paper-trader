import sqlite3
import pandas as pd
import json

DB_PATH = "data/nse_stocks_all_years.db"
BHAVCOPY_PATH = "data/bhavcopy_2021.csv"

def audit_database():
    print("=" * 70)
    print("      DATA QUALITY & INTEGRITY AUDIT REPORT: nse_stocks_all_years.db      ")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Universe & Resolution Coverage
    bhav_df = pd.read_csv(BHAVCOPY_PATH)
    eq_bhav = bhav_df[bhav_df['SERIES'] == 'EQ']
    total_universe_count = len(eq_bhav)

    comp_df = pd.read_sql_query("SELECT * FROM company_master", conn)
    resolved_count = len(comp_df)
    missing_count = total_universe_count - resolved_count

    print("\n--- 1. UNIVERSE COVERAGE ---")
    print(f"Total 2021 Universe (EQ Series):  {total_universe_count:,}")
    print(f"Successfully Resolved & Saved:    {resolved_count:,} ({resolved_count/total_universe_count*100:.2f}%)")
    print(f"Failed / Unresolved Stocks:        {missing_count:,} ({missing_count/total_universe_count*100:.2f}%)")

    # 2. Duplicate Check Across All Tables
    print("\n--- 2. DUPLICATE RECORDS AUDIT ---")
    
    dup_comp_sym = cursor.execute("SELECT symbol, COUNT(*) FROM company_master GROUP BY symbol HAVING COUNT(*) > 1").fetchall()
    dup_comp_sc = cursor.execute("SELECT sc_id, COUNT(*) FROM company_master WHERE sc_id IS NOT NULL GROUP BY sc_id HAVING COUNT(*) > 1").fetchall()
    dup_pl = cursor.execute("SELECT symbol, year, COUNT(*) FROM financial_income_statement GROUP BY symbol, year HAVING COUNT(*) > 1").fetchall()
    dup_bs = cursor.execute("SELECT symbol, year, COUNT(*) FROM financial_balance_sheet GROUP BY symbol, year HAVING COUNT(*) > 1").fetchall()
    dup_ratios = cursor.execute("SELECT symbol, year, COUNT(*) FROM financial_ratios GROUP BY symbol, year HAVING COUNT(*) > 1").fetchall()
    dup_tech = cursor.execute("SELECT symbol, COUNT(*) FROM technical_valuation_data GROUP BY symbol HAVING COUNT(*) > 1").fetchall()

    print(f"Duplicate Symbols in company_master:            {len(dup_comp_sym)}")
    print(f"Duplicate SC_IDs in company_master:             {len(dup_comp_sc)}")
    print(f"Duplicate (symbol, year) in Income Statement:   {len(dup_pl)}")
    print(f"Duplicate (symbol, year) in Balance Sheet:      {len(dup_bs)}")
    print(f"Duplicate (symbol, year) in Ratios:             {len(dup_ratios)}")
    print(f"Duplicate Symbols in Technicals:               {len(dup_tech)}")

    # 3. Completeness & Data Quality Check
    print("\n--- 3. DATA COMPLETENESS & MISSING VALUES ---")
    
    # Financial Statement Coverage
    stocks_with_pl = cursor.execute("SELECT COUNT(DISTINCT symbol) FROM financial_income_statement").fetchone()[0]
    stocks_with_bs = cursor.execute("SELECT COUNT(DISTINCT symbol) FROM financial_balance_sheet").fetchone()[0]
    stocks_without_financials = resolved_count - stocks_with_pl

    print(f"Stocks with Income Statements (P&L):  {stocks_with_pl:,} ({stocks_with_pl/resolved_count*100:.2f}%)")
    print(f"Stocks with Balance Sheets:          {stocks_with_bs:,} ({stocks_with_bs/resolved_count*100:.2f}%)")
    print(f"Stocks with NO Financial Data:       {stocks_without_financials:,} ({stocks_without_financials/resolved_count*100:.2f}%)")

    # Column Null Counts in P&L
    pl_total_rows = cursor.execute("SELECT COUNT(*) FROM financial_income_statement").fetchone()[0]
    pl_null_rev = cursor.execute("SELECT COUNT(*) FROM financial_income_statement WHERE total_revenue IS NULL").fetchone()[0]
    pl_null_pat = cursor.execute("SELECT COUNT(*) FROM financial_income_statement WHERE net_profit IS NULL").fetchone()[0]
    pl_null_eps = cursor.execute("SELECT COUNT(*) FROM financial_income_statement WHERE eps_basic IS NULL").fetchone()[0]

    print(f"\nTotal P&L Rows across all years:     {pl_total_rows:,}")
    print(f"  - Rows missing Revenue:             {pl_null_rev:,} ({pl_null_rev/pl_total_rows*100:.2f}%)")
    print(f"  - Rows missing Net Profit:          {pl_null_pat:,} ({pl_null_pat/pl_total_rows*100:.2f}%)")
    print(f"  - Rows missing EPS:                 {pl_null_eps:,} ({pl_null_eps/pl_total_rows*100:.2f}%)")

    # Column Null Counts in Balance Sheet
    bs_total_rows = cursor.execute("SELECT COUNT(*) FROM financial_balance_sheet").fetchone()[0]
    bs_null_assets = cursor.execute("SELECT COUNT(*) FROM financial_balance_sheet WHERE total_assets IS NULL").fetchone()[0]
    bs_null_equity = cursor.execute("SELECT COUNT(*) FROM financial_balance_sheet WHERE total_shareholders_funds IS NULL").fetchone()[0]
    bs_null_debt = cursor.execute("SELECT COUNT(*) FROM financial_balance_sheet WHERE total_debt IS NULL").fetchone()[0]

    print(f"\nTotal Balance Sheet Rows across years:{bs_total_rows:,}")
    print(f"  - Rows missing Total Assets:        {bs_null_assets:,} ({bs_null_assets/bs_total_rows*100:.2f}%)")
    print(f"  - Rows missing Net Worth/Equity:    {bs_null_equity:,} ({bs_null_equity/bs_total_rows*100:.2f}%)")
    print(f"  - Rows missing Debt Info:           {bs_null_debt:,} ({bs_null_debt/bs_total_rows*100:.2f}%)")

    # 4. Historical Year Distribution
    print("\n--- 4. HISTORICAL YEARS DISTRIBUTION ---")
    years_df = pd.read_sql_query("""
    SELECT symbol, COUNT(*) as num_years, MIN(year) as min_year, MAX(year) as max_year
    FROM financial_income_statement
    GROUP BY symbol
    """, conn)

    print(f"Average Years of History per Stock:  {years_df['num_years'].mean():.1f} years")
    print(f"Min History Years for a Stock:      {years_df['num_years'].min()} years")
    print(f"Max History Years for a Stock:      {years_df['num_years'].max()} years")

    print("\nHistory Length Breakdown:")
    print("  - Stocks with 20+ Years History:    ", len(years_df[years_df['num_years'] >= 20]))
    print("  - Stocks with 15-19 Years History:  ", len(years_df[(years_df['num_years'] >= 15) & (years_df['num_years'] < 20)]))
    print("  - Stocks with 10-14 Years History:  ", len(years_df[(years_df['num_years'] >= 10) & (years_df['num_years'] < 15)]))
    print("  - Stocks with 5-9 Years History:    ", len(years_df[(years_df['num_years'] >= 5) & (years_df['num_years'] < 10)]))
    print("  - Stocks with <5 Years History:     ", len(years_df[years_df['num_years'] < 5]))

    # 5. Invalid / Anomaly Data Detection
    print("\n--- 5. ANOMALY & BAD DATA AUDIT ---")
    
    neg_assets = cursor.execute("SELECT COUNT(*) FROM financial_balance_sheet WHERE total_assets < 0").fetchone()[0]
    neg_revenue = cursor.execute("SELECT COUNT(*) FROM financial_income_statement WHERE total_revenue < 0").fetchone()[0]
    invalid_json = 0

    # Test raw JSON parsing
    sample_jsons = cursor.execute("SELECT raw_pl_json FROM financial_income_statement LIMIT 500").fetchall()
    for (rj,) in sample_jsons:
        if rj:
            try:
                json.loads(rj)
            except:
                invalid_json += 1

    print(f"Negative Total Assets:              {neg_assets}")
    print(f"Negative Total Revenue:             {neg_revenue}")
    print(f"Corrupted / Unparseable Raw JSONs: {invalid_json}")

    conn.close()
    print("\n" + "=" * 70)
    print("                       AUDIT COMPLETE                              ")
    print("=" * 70)

if __name__ == "__main__":
    audit_database()
