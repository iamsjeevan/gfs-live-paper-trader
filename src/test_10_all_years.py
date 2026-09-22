import sys
import os
import sqlite3
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.scrape_all_years import init_database, load_2021_universe, scrape_single_stock

def main():
    print("=" * 70)
    print("     TESTING MULTI-YEAR SCRAPER ON 10 STOCKS                      ")
    print("=" * 70)

    # 1. Initialize fresh multi-year DB
    init_database()
    
    # 2. Load universe and pick 10 test stocks
    full_universe = load_2021_universe()
    sample_symbols = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', '20MICRONS', '3MINDIA', '5PAISA', '63MOONS', 'AARTIIND', 'ABB']
    sample_universe = [s for s in full_universe if s[0] in sample_symbols][:10]
    
    print(f"\nSelected 10 Test Stocks: {[s[0] for s in sample_universe]}\n")

    # 3. Scrape sequentially
    for stock in sample_universe:
        scrape_single_stock(stock)
        print("-" * 50)

    # 4. Display Database Status and Tables
    print("\n" + "=" * 70)
    print("                   DATABASE STATUS & RESULTS                       ")
    print("=" * 70)

    conn = sqlite3.connect("data/nse_stocks_all_years.db")
    
    print("\n--- TABLE: company_master ---")
    comp_df = pd.read_sql_query("SELECT symbol, company_name, sc_id, sector FROM company_master", conn)
    print(comp_df.to_string(index=False))

    print("\n--- HISTORICAL YEARS PER STOCK (P&L) ---")
    pl_summary = pd.read_sql_query("""
    SELECT symbol, COUNT(*) as total_years, MIN(year) as min_year, MAX(year) as max_year 
    FROM financial_income_statement 
    GROUP BY symbol
    """, conn)
    print(pl_summary.to_string(index=False))

    print("\n--- SAMPLE MULTI-YEAR FINANCIALS FOR RELIANCE ---")
    rel_df = pd.read_sql_query("""
    SELECT year, total_revenue, net_profit, eps_basic 
    FROM financial_income_statement 
    WHERE symbol='RELIANCE' 
    ORDER BY year DESC 
    LIMIT 10
    """, conn)
    print(rel_df.to_string(index=False))

    conn.close()

if __name__ == "__main__":
    main()
