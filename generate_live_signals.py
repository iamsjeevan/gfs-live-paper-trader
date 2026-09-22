import sqlite3
import pandas as pd
import numpy as np
import yfinance as yf
import json
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

INDIA_DB = "data/nse_stocks_all_years.db"

def get_latest_fundamentals():
    print("Loading fundamental universe from database...")
    conn = sqlite3.connect(INDIA_DB)
    comp_df = pd.read_sql_query("SELECT symbol AS Ticker, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, total_revenue, net_profit FROM financial_income_statement", conn)
    conn.close()

    mkt_cap_dict = dict(zip(comp_df['Ticker'], comp_df['market_cap']))
    
    pl_sorted = pl_df.sort_values(['Ticker', 'Year'])
    pl_sorted['prev_net_profit'] = pl_sorted.groupby('Ticker')['net_profit'].shift(1)
    pl_sorted['loss_decreasing'] = (pl_sorted['net_profit'] < 0) & (pl_sorted['net_profit'] > pl_sorted['prev_net_profit'])
    pl_sorted['qualifies'] = (pl_sorted['net_profit'] > 0) | (pl_sorted['loss_decreasing'] == True)

    # Get the latest year available in the DB for each ticker
    latest_ratios = ratios_df.sort_values('Year').groupby('Ticker').last().reset_index()
    latest_pl = pl_sorted.sort_values('Year').groupby('Ticker').last().reset_index()
    
    merged = pd.merge(latest_ratios, latest_pl[['Ticker', 'qualifies']], on='Ticker', how='inner')
    
    # Apply Filters
    q_set = set(merged[(merged['qualifies'] == True) & (merged['debt_equity'] <= 1.5)]['Ticker'])
    
    eligible_tickers = [s for s in mkt_cap_dict.keys() if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in q_set)]
    
    # Format for yfinance (.NS for NSE)
    yf_tickers = [t + ".NS" for t in eligible_tickers]
    return eligible_tickers, yf_tickers

def generate_live_signals():
    eligible_tickers, yf_tickers = get_latest_fundamentals()
    print(f"Found {len(yf_tickers)} fundamentally eligible stocks.")
    
    print("Downloading last 250 days of live market data from Yahoo Finance...")
    # Group in chunks of 500 to avoid yf limits
    all_data = pd.DataFrame()
    chunk_size = 500
    for i in range(0, len(yf_tickers), chunk_size):
        chunk = yf_tickers[i:i+chunk_size]
        data = yf.download(chunk, period="1y", interval="1d", auto_adjust=True, progress=False)['Close']
        if all_data.empty:
            all_data = data
        else:
            all_data = all_data.join(data, how='outer')
            
    # Clean column names (remove .NS)
    all_data.columns = [c.replace('.NS', '') for c in all_data.columns]
    all_data = all_data.ffill()

    print("Calculating Technicals & Momentum...")
    sma200 = all_data.rolling(window=200).mean().iloc[-1]
    sma50 = all_data.rolling(window=50).mean().iloc[-1]
    current_prices = all_data.iloc[-1]
    
    ret_3m = all_data.pct_change(63).iloc[-1]
    vol_60d = all_data.pct_change().rolling(window=60).std().iloc[-1]
    mom_score = ret_3m / (vol_60d + 1e-6)
    
    print("Filtering Technical Entries...")
    valid_entry = []
    for t in all_data.columns:
        p = current_prices.get(t, np.nan)
        s200 = sma200.get(t, np.nan)
        s50 = sma50.get(t, np.nan)
        if pd.notna(p) and pd.notna(s200) and pd.notna(s50):
            if p > s200 and p >= s50:
                valid_entry.append(t)
                
    valid_scores = mom_score.loc[valid_entry].dropna()
    top_10 = valid_scores.nlargest(10)
    
    # Build JSON output
    dashboard_data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "top_10_portfolio": [],
        "market_status": "OPEN"
    }
    
    for t in top_10.index:
        dashboard_data["top_10_portfolio"].append({
            "ticker": t,
            "current_price": round(current_prices[t], 2),
            "sma_50": round(sma50[t], 2),
            "sma_200": round(sma200[t], 2),
            "momentum_score": round(top_10[t], 2),
            "buffer_to_50sma": round(((current_prices[t] - sma50[t]) / current_prices[t]) * 100, 2)
        })
        
    with open('live_dashboard.json', 'w') as f:
        json.dump(dashboard_data, f, indent=4)
        
    print("\n" + "="*50)
    print(" LIVE TOP 10 PORTFOLIO FOR TODAY ")
    print("="*50)
    for idx, row in enumerate(dashboard_data["top_10_portfolio"]):
        print(f"{idx+1}. {row['ticker']} | Price: {row['current_price']} | Buffer to 50SMA: {row['buffer_to_50sma']}%")
    print("\nSaved data to 'live_dashboard.json'")

if __name__ == "__main__":
    generate_live_signals()
