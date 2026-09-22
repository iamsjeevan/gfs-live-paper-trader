import sqlite3
import pandas as pd
import numpy as np
import json
import warnings
warnings.filterwarnings('ignore')

DB_PATH = "instocks.db"
INDIA_DB = "data/nse_stocks_all_years.db"

def run_export():
    print("Loading data...")
    # Load prices
    conn = sqlite3.connect(INDIA_DB)
    prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE date >= '2016-01-01' AND close IS NOT NULL", conn)
    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    price_matrix = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').ffill()
    
    # Load Fundamentals
    comp_df = pd.read_sql_query("SELECT symbol AS Ticker, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, total_revenue, net_profit FROM financial_income_statement", conn)
    conn.close()

    mkt_cap_dict = dict(zip(comp_df['Ticker'], comp_df['market_cap']))
    
    pl_sorted = pl_df.sort_values(['Ticker', 'Year'])
    pl_sorted['prev_net_profit'] = pl_sorted.groupby('Ticker')['net_profit'].shift(1)
    pl_sorted['loss_decreasing'] = (pl_sorted['net_profit'] < 0) & (pl_sorted['net_profit'] > pl_sorted['prev_net_profit'])
    pl_sorted['qualifies'] = (pl_sorted['net_profit'] > 0) | (pl_sorted['loss_decreasing'] == True)

    qualifying_dict = {}
    for y in range(2016, 2027):
        r_sub = ratios_df[ratios_df['Year'] == y]
        p_sub = pl_sorted[pl_sorted['Year'] == y]
        merged = pd.merge(r_sub, p_sub[['Ticker', 'Year', 'qualifies']], on=['Ticker', 'Year'], how='inner')
        q_set = set(merged[(merged['qualifies'] == True) & (merged['debt_equity'] <= 1.5)]['Ticker'])
        qualifying_dict[y] = [s for s in price_matrix.columns if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in q_set)]

    print("Calculating technicals...")
    sma200 = price_matrix.rolling(window=200).mean()
    sma50 = price_matrix.rolling(window=50).mean() # NEW EXIT RULE
    
    ret_3m = price_matrix.pct_change(63)
    vol_60d = price_matrix.pct_change().rolling(window=60).std()
    mom_score = ret_3m / (vol_60d + 1e-6)

    # Dates
    dates = price_matrix.index
    start_idx = dates.get_loc(dates[dates >= '2018-01-01'][0])
    dates = dates[start_idx:]
    
    dates_df = pd.DataFrame({'Date': dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    rebalance_dates = set(dates_df.groupby('ym')['Date'].min().tolist())

    print("Simulating daily portfolio...")
    cash = 100000.0
    positions = {} # ticker -> shares
    
    daily_state = []
    
    for i, date in enumerate(dates):
        current_prices = price_matrix.loc[date]
        current_sma50 = sma50.loc[date]
        
        # Check Mid-Month 50 SMA Exits
        sold_tickers = []
        for ticker, shares in positions.items():
            price = current_prices.get(ticker, np.nan)
            s50 = current_sma50.get(ticker, np.nan)
            
            # EXIT RULE: Price < 50 SMA
            if pd.notna(price) and pd.notna(s50) and price < s50:
                proceeds = shares * price * (1 - 0.003) # 0.3% slippage
                cash += proceeds
                sold_tickers.append(ticker)
        
        for t in sold_tickers:
            del positions[t]
        
        # Monthly Rebalance
        is_rebal = date in rebalance_dates
        if is_rebal:
            target_year = date.year - 1
            available = qualifying_dict.get(target_year, [])
            
            # Technical Entry Filter
            c_sma200 = sma200.loc[date]
            c_sma50 = sma50.loc[date]
            
            valid_entry = []
            for t in available:
                p = current_prices.get(t, np.nan)
                s200 = c_sma200.get(t, np.nan)
                s50 = c_sma50.get(t, np.nan)
                # Entry: Price > 200 SMA AND Price > 50 SMA (must not immediately trigger exit)
                if pd.notna(p) and pd.notna(s200) and p > s200 and pd.notna(s50) and p >= s50:
                    valid_entry.append(t)
            
            current_mom = mom_score.loc[date, valid_entry].dropna()
            top_10 = current_mom.nlargest(10).index.tolist()
            
            # Sell what's not in top 10 (Drop-outs)
            sold = []
            for ticker in list(positions.keys()):
                if ticker not in top_10:
                    p = current_prices.get(ticker, np.nan)
                    if pd.notna(p):
                        cash += positions[ticker] * p * (1 - 0.003)
                    sold.append(ticker)
            for t in sold:
                del positions[t]
                
            # Buy new allocations (No-Trim "Let Winners Ride" Logic)
            nav = cash + sum([positions[t] * current_prices.get(t, 0) for t in positions])
            target_per_stock = nav / 10.0
            
            # Figure out who needs cash
            shortfalls = {}
            total_shortfall = 0.0
            
            for ticker in top_10:
                p = current_prices.get(ticker, np.nan)
                if pd.isna(p): continue
                
                current_value = positions.get(ticker, 0) * p
                
                if current_value < target_per_stock:
                    shortfall = target_per_stock - current_value
                    shortfalls[ticker] = shortfall
                    total_shortfall += shortfall
                # If current_value >= target_per_stock, we DO NOTHING (Never sell winners!)
                
            # Allocate available cash proportionally to the shortfalls
            if total_shortfall > 0 and cash > 0:
                for ticker, shortfall in shortfalls.items():
                    p = current_prices.get(ticker, np.nan)
                    
                    # If we don't have enough cash for all shortfalls, distribute proportionally
                    if cash < total_shortfall:
                        buy_amount = (shortfall / total_shortfall) * cash
                    else:
                        buy_amount = shortfall
                        
                    buy_shares = int(buy_amount / (p * 1.003)) # 0.3% slippage on entry
                    if buy_shares > 0:
                        positions[ticker] = positions.get(ticker, 0) + buy_shares
                        cash -= (buy_shares * p * 1.003)
        
        # Record State
        holdings = []
        port_val = cash
        for t, s in positions.items():
            p = current_prices.get(t, 0)
            val = s * p
            port_val += val
            holdings.append({
                "ticker": t,
                "shares": s,
                "price": round(p, 2),
                "value": round(val, 2),
                "weight": round((val / port_val) * 100, 2) if port_val > 0 else 0
            })
            
        holdings = sorted(holdings, key=lambda x: x['value'], reverse=True)
            
        daily_state.append({
            "date": date.strftime('%Y-%m-%d'),
            "nav": round(port_val, 2),
            "cash": round(cash, 2),
            "is_rebalance": is_rebal,
            "holdings": holdings
        })

    print(f"Exporting {len(daily_state)} days to JSON...")
    with open('portfolio_data.json', 'w') as f:
        json.dump(daily_state, f)
        
    print("Done! Final NAV:", daily_state[-1]['nav'])

if __name__ == "__main__":
    run_export()
