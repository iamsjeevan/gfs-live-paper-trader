import sqlite3
import pandas as pd

DB_PATH = "data/nse_stocks_all_years.db"

def trace_stock(target_symbol="SKMEGGPROD"):
    conn = sqlite3.connect(DB_PATH)
    
    # Load prices for SKMEGGPROD between Aug 2025 and Aug 2026
    df = pd.read_sql_query(f"""
    SELECT date, close, sma_50, high_52w 
    FROM daily_prices 
    WHERE symbol = '{target_symbol}' AND date >= '2025-08-01'
    ORDER BY date
    """, conn)
    
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    df['drawdown_from_peak'] = (df['close'] / df['close'].cummax() - 1.0) * 100.0
    
    print(f"=== TRACE HISTORY FOR {target_symbol} (AUG 2025 - AUG 2026) ===")
    print(f"Total trading days: {len(df)}")
    print(f"Max Price: ₹{df['close'].max():.2f} on {df.loc[df['close'].idxmax(), 'date'].strftime('%Y-%m-%d')}")
    print(f"Min Price: ₹{df['close'].min():.2f} on {df.loc[df['close'].idxmin(), 'date'].strftime('%Y-%m-%d')}")
    print(f"Latest Price Today (Aug 25, 2026): ₹{df['close'].iloc[-1]:.2f}")

    print("\nMonthly Snapshots (1st Trading Day of Each Month):")
    df['ym'] = df['date'].dt.to_period('M')
    monthly_snaps = df.groupby('ym').first()
    for ym, r in monthly_snaps.iterrows():
        print(f"Date: {r['date'].strftime('%Y-%m-%d')} | Close: ₹{r['close']:.2f} | 50 SMA: ₹{r['sma_50']:.2f} | Peak: ₹{r['high_52w']:.2f}")

if __name__ == "__main__":
    trace_stock("SKMEGGPROD")
