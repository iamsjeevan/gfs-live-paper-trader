import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"

def find_trade_examples():
    conn = sqlite3.connect(DB_PATH)
    
    # Load prices for two famous momentum stocks: WELCORP and INDOTECH
    welcorp_df = pd.read_sql_query("""
    SELECT date, close, sma_50, high_52w 
    FROM daily_prices 
    WHERE symbol = 'WELCORP' AND date >= '2024-01-01'
    ORDER BY date
    """, conn)
    
    indotech_df = pd.read_sql_query("""
    SELECT date, close, sma_50, high_52w 
    FROM daily_prices 
    WHERE symbol = 'INDOTECH' AND date >= '2024-01-01'
    ORDER BY date
    """, conn)

    conn.close()

    welcorp_df['date'] = pd.to_datetime(welcorp_df['date'])
    indotech_df['date'] = pd.to_datetime(indotech_df['date'])

    print("=" * 80)
    print("      MOMENTUM CASE STUDIES: MULTI-BAGGER WINNER vs CLIMAX TOP BUY      ")
    print("=" * 80)

    print("\n--- 1. WINNER CASE STUDY: WELCORP (Welspun Corp Ltd) ---")
    print(f"Start Price (Jan 2024): ₹{welcorp_df['close'].iloc[0]:.2f}")
    print(f"Price on Entry (Aug 2025): ₹{welcorp_df[welcorp_df['date'] >= '2025-08-25']['close'].iloc[0]:.2f}")
    print(f"Current Price (Aug 2026): ₹{welcorp_df['close'].iloc[-1]:.2f}")
    mult = (welcorp_df['close'].iloc[-1] - welcorp_df[welcorp_df['date'] >= '2025-08-25']['close'].iloc[0]) / welcorp_df[welcorp_df['date'] >= '2025-08-25']['close'].iloc[0] * 100
    print(f"Net Gain After Buying Momentum: +{mult:.2f}%")

    print("\n--- 2. WINNER CASE STUDY: INDOTECH (Indo Tech Transformers Ltd) ---")
    print(f"Start Price (Jan 2024): ₹{indotech_df['close'].iloc[0]:.2f}")
    print(f"Price on Entry (Aug 2025): ₹{indotech_df[indotech_df['date'] >= '2025-08-25']['close'].iloc[0]:.2f}")
    print(f"Current Price (Aug 2026): ₹{indotech_df['close'].iloc[-1]:.2f}")
    mult_indo = (indotech_df['close'].iloc[-1] - indotech_df[indotech_df['date'] >= '2025-08-25']['close'].iloc[0]) / indotech_df[indotech_df['date'] >= '2025-08-25']['close'].iloc[0] * 100
    print(f"Net Gain After Buying Momentum: +{mult_indo:.2f}%")

if __name__ == "__main__":
    find_trade_examples()
