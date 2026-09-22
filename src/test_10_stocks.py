import sys
import os
import sqlite3
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.scrape_nse_2021 import init_database, load_2021_universe, scrape_single_stock

def main():
    print("=" * 70)
    print("     TESTING SCRAPER ON 10 STOCKS WITH COMPREHENSIVE FUNDAMENTALS  ")
    print("=" * 70)

    # 1. Initialize fresh DB with full schema
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

    conn = sqlite3.connect("data/nse_stocks_2021.db")
    
    print("\n--- TABLE: fundamental_data_2021 (Key Summary View) ---")
    query = """
    SELECT 
        symbol, sc_id, sector, market_cap, pe_ratio, pb_ratio, book_value, dividend_yield,
        revenue_2021, net_profit_2021, total_assets_2021, equity_net_worth_2021, total_debt_2021,
        roe_2021, roce_2021, debt_equity_2021, current_ratio_2021, net_margin_2021
    FROM fundamental_data_2021
    """
    fund_df = pd.read_sql_query(query, conn)
    print(fund_df.to_string(index=False))

    conn.close()

if __name__ == "__main__":
    main()
