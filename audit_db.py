import sqlite3
import pandas as pd

def audit_database(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall()]
    
    print("=== DATABASE AUDIT ===")
    
    for table in tables:
        print(f"\n--- Table: {table} ---")
        
        # Schema and Data Types
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        print("Columns & Types:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
            
        # Row count
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        row_count = cursor.fetchone()[0]
        print(f"Total Rows: {row_count}")
        
        # Specific checks based on common column names
        col_names = [c[1] for c in columns]
        
        if 'Ticker' in col_names or 'symbol' in col_names:
            ticker_col = 'Ticker' if 'Ticker' in col_names else 'symbol'
            cursor.execute(f"SELECT COUNT(DISTINCT {ticker_col}) FROM {table}")
            num_stocks = cursor.fetchone()[0]
            print(f"Unique Stocks: {num_stocks}")
            
        if 'Date' in col_names or 'date' in col_names:
            date_col = 'Date' if 'Date' in col_names else 'date'
            cursor.execute(f"SELECT MIN({date_col}), MAX({date_col}) FROM {table}")
            min_date, max_date = cursor.fetchone()
            print(f"Date Range: {min_date} to {max_date}")

        if 'fiscalDateEnding' in col_names:
            cursor.execute(f"SELECT MIN(fiscalDateEnding), MAX(fiscalDateEnding) FROM {table}")
            min_date, max_date = cursor.fetchone()
            print(f"Date Range (fiscalDateEnding): {min_date} to {max_date}")

    conn.close()

if __name__ == "__main__":
    audit_database("instocks.db")
