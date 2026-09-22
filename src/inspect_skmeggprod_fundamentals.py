import sqlite3
import pandas as pd

DB_PATH = "data/nse_stocks_all_years.db"

def inspect_fundamentals(symbol="SKMEGGPROD"):
    conn = sqlite3.connect(DB_PATH)
    
    # 1. Company Info
    comp_df = pd.read_sql_query(f"SELECT * FROM company_master WHERE symbol = '{symbol}'", conn)
    tech_df = pd.read_sql_query(f"SELECT * FROM technical_valuation_data WHERE symbol = '{symbol}'", conn)
    
    # 2. Income Statement (P&L)
    pl_df = pd.read_sql_query(f"SELECT year, total_revenue, net_profit, eps_basic FROM financial_income_statement WHERE symbol = '{symbol}' ORDER BY year DESC", conn)
    
    # 3. Balance Sheet
    bs_df = pd.read_sql_query(f"SELECT year, total_assets, total_shareholders_funds, total_debt FROM financial_balance_sheet WHERE symbol = '{symbol}' ORDER BY year DESC", conn)
    
    # 4. Ratios
    ratio_df = pd.read_sql_query(f"SELECT year, roe, debt_equity, net_margin FROM financial_ratios WHERE symbol = '{symbol}' ORDER BY year DESC", conn)
    
    conn.close()

    print("=" * 80)
    print(f"      FUNDAMENTAL AUDIT REPORT FOR: {symbol}      ")
    print("=" * 80)

    if not comp_df.empty:
        print(f"\nCompany Name: {comp_df['company_name'].iloc[0]}")
        print(f"Industry / Sector: {comp_df['industry'].iloc[0] if 'industry' in comp_df.columns else 'Agro / FMCG / Poultry Exports'}")
    
    if not tech_df.empty:
        print(f"Market Cap: ₹{tech_df['market_cap'].iloc[0]:,.2f} Cr")
        print(f"P/E Ratio:  {tech_df['pe_ratio'].iloc[0]}")
        print(f"P/B Ratio:  {tech_df['pb_ratio'].iloc[0]}")

    print("\n--- HISTORICAL FINANCIAL RATIOS (Last 10 Years) ---")
    print(ratio_df.head(10).to_string(index=False))

    print("\n--- HISTORICAL P&L (Total Revenue & Net Profit in ₹ Cr) ---")
    print(pl_df.head(10).to_string(index=False))

    print("\n--- HISTORICAL BALANCE SHEET (Total Assets & Equity in ₹ Cr) ---")
    print(bs_df.head(10).to_string(index=False))

if __name__ == "__main__":
    inspect_fundamentals("SKMEGGPROD")
