import sqlite3
import pandas as pd
import yfinance as yf
from datetime import datetime

DB_PATH = "instocks.db"

def fix_database():
    print("Connecting to database...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("1. Fetching Nifty 500 historical data (^CRSLDX)...")
    # Nifty 500 ticker on Yahoo Finance is ^CRSLDX
    nifty500 = yf.download("^CRSLDX", start="2007-01-01", progress=False)
    
    if nifty500.empty:
        print("Could not fetch ^CRSLDX, trying ^NSEI (Nifty 50) as proxy for regime...")
        nifty500 = yf.download("^NSEI", start="2007-01-01", progress=False)
        ticker_name = "^NSEI"
    else:
        ticker_name = "^CRSLDX"

    if not nifty500.empty:
        # Flatten MultiIndex columns if necessary (yfinance > 0.2.x behavior)
        if isinstance(nifty500.columns, pd.MultiIndex):
             nifty500.columns = nifty500.columns.get_level_values(0)
             
        nifty500 = nifty500.reset_index()
        nifty500['Date'] = nifty500['Date'].dt.strftime('%Y-%m-%d')
        nifty500['Ticker'] = "NIFTY500" # We will name it NIFTY500 in the DB for clarity
        
        # Prepare for insertion
        cols = list(nifty500.columns)
        adj_close_col = 'Adj Close' if 'Adj Close' in cols else 'Close'
        vol_col = 'Volume' if 'Volume' in cols else cols[0] # dummy fallback
        
        insert_data = nifty500[['Date', 'Ticker', adj_close_col, vol_col]].copy()
        insert_data.columns = ['Date', 'Ticker', 'Adj_Close', 'Volume']
        
        # Insert into daily_prices
        print(f"Inserting {len(insert_data)} rows of NIFTY500 data into daily_prices...")
        insert_data.to_sql("daily_prices", conn, if_exists="append", index=False)
        print("Nifty 500 data added successfully.")
    else:
        print("Failed to download any index data.")

    print("\n2. Estimating Historical Market Cap via Shares Outstanding...")
    # Get current Market Cap and the most recent price for all stocks in company_metrics
    query = """
    SELECT c.Ticker, c.Market_Cap, p.Adj_Close as Latest_Price
    FROM company_metrics c
    JOIN (
        SELECT Ticker, Adj_Close, MAX(Date) 
        FROM daily_prices 
        GROUP BY Ticker
    ) p ON c.Ticker = p.Ticker
    WHERE c.Market_Cap IS NOT NULL
    """
    df_metrics = pd.read_sql(query, conn)
    
    # Calculate implied shares outstanding
    # Market_Cap is usually in billions or millions, but whatever the unit, 
    # we just need Market_Cap / Price = Implied Shares.
    df_metrics['Implied_Shares'] = df_metrics['Market_Cap'] / df_metrics['Latest_Price']
    
    # Create a new table to store this
    print("Creating 'estimated_shares' table...")
    df_shares = df_metrics[['Ticker', 'Implied_Shares']]
    df_shares.to_sql("estimated_shares", conn, if_exists="replace", index=False)
    
    print(f"Estimated shares calculated for {len(df_shares)} stocks.")
    
    conn.commit()
    conn.close()
    print("Database corrections complete!")

if __name__ == "__main__":
    fix_database()
