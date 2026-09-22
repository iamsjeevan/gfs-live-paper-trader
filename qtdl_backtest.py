import sqlite3
import pandas as pd
import numpy as np

# Suppress warnings for cleaner output
import warnings
warnings.filterwarnings('ignore')

DB_PATH = "instocks.db"

def run_backtest():
    print("Loading data from database...")
    conn = sqlite3.connect(DB_PATH)
    
    # Load prices
    prices_df = pd.read_sql("SELECT Date, Ticker, Adj_Close FROM daily_prices", conn)
    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    
    # Pivot prices
    print("Pivoting price data...")
    price_matrix = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').ffill()
    
    # Extract Nifty 500
    if 'NIFTY500' in price_matrix.columns:
        nifty = price_matrix['NIFTY500']
        price_matrix = price_matrix.drop(columns=['NIFTY500'])
    else:
        print("ERROR: NIFTY500 not found.")
        return
        
    # Load Estimated Shares
    shares_df = pd.read_sql("SELECT Ticker, Implied_Shares FROM estimated_shares", conn)
    shares_dict = shares_df.set_index('Ticker')['Implied_Shares'].to_dict()
    
    # Load Balance Sheets for D/E
    # D/E = (Net_Debt + Cash_And_Equivalents) / Total_Equity
    bs_df = pd.read_sql("SELECT Date, Ticker, Net_Debt, Cash_And_Equivalents, Total_Equity FROM balance_sheets", conn)
    bs_df['Date'] = pd.to_datetime(bs_df['Date'])
    bs_df['Total_Debt'] = bs_df['Net_Debt'].fillna(0) + bs_df['Cash_And_Equivalents'].fillna(0)
    bs_df['D_E'] = bs_df['Total_Debt'] / bs_df['Total_Equity']
    
    # Load Income Statements for Turnaround
    is_df = pd.read_sql("SELECT Date, Ticker, Net_Income FROM income_statements", conn)
    is_df['Date'] = pd.to_datetime(is_df['Date'])
    is_df = is_df.sort_values(by=['Ticker', 'Date'])
    is_df['Prev_Net_Income'] = is_df.groupby('Ticker')['Net_Income'].shift(1)
    
    # Turnaround Rule: Net Income > 0 OR (Net Income < 0 AND Net Income > Prev_Net_Income)
    # Note: if loss is smaller, Net Income is a smaller negative number, so it's > Prev
    is_df['Quality_Pass'] = (is_df['Net_Income'] > 0) | ((is_df['Net_Income'] < 0) & (is_df['Net_Income'] > is_df['Prev_Net_Income']))
    
    print("Calculating technical indicators...")
    # 200 SMA
    sma200 = price_matrix.rolling(window=200).mean().resample('ME').last()
    
    # 3-Month Return (approx 63 trading days)
    ret_3m = price_matrix.pct_change(63)
    
    # 60-day volatility
    vol_60d = price_matrix.pct_change().rolling(window=60).std()
    
    # Momentum Ranking: Risk-adjusted 3-month momentum
    mom_rank = (ret_3m / vol_60d).resample('ME').last()
    
    # Market Regime
    nifty_sma200 = nifty.rolling(window=200).mean()
    nifty_diff = (nifty - nifty_sma200) / nifty_sma200
    
    print("Aligning fundamental data...")
    # To avoid lookahead bias and complex merges, we will create a monthly rebalance loop
    # We will resample dates to Month End
    monthly_prices = price_matrix.resample('ME').last()
    month_ends = monthly_prices.index
    
    # Start backtest from 2011 to allow for SMA and previous year financials to populate
    month_ends = month_ends[month_ends >= '2011-01-01']
    
    portfolio_returns = []
    
    # Vectorize Fundamental Data via Pivot and FFill
    # D_E Matrix
    de_matrix = bs_df.drop_duplicates(subset=['Date', 'Ticker']).pivot(index='Date', columns='Ticker', values='D_E')
    de_matrix = de_matrix.reindex(price_matrix.index, method='ffill')
    
    # Quality Pass Matrix
    qual_matrix = is_df.drop_duplicates(subset=['Date', 'Ticker']).pivot(index='Date', columns='Ticker', values='Quality_Pass')
    qual_matrix = qual_matrix.reindex(price_matrix.index, method='ffill')
    
    print(f"Running monthly backtest across {len(month_ends)} months...")
    
    for i in range(len(month_ends) - 1):
        rebalance_date = month_ends[i]
        next_rebalance_date = month_ends[i+1]
        
        # 1. Market Regime & Leverage
        n_diff = nifty_diff.loc[:rebalance_date].iloc[-1]
        if n_diff > 0:
            leverage = 1.5
        elif -0.05 <= n_diff <= 0:
            leverage = 1.25
        else:
            leverage = 1.0 # Tier 3: > 5% below (assuming >10% meant further below)
            
        # 2. Filter Universe at rebalance_date
        current_prices = monthly_prices.loc[rebalance_date]
        current_de = de_matrix.loc[rebalance_date] if rebalance_date in de_matrix.index else de_matrix.loc[:rebalance_date].iloc[-1]
        current_qual = qual_matrix.loc[rebalance_date] if rebalance_date in qual_matrix.index else qual_matrix.loc[:rebalance_date].iloc[-1]
        current_sma = sma200.loc[rebalance_date]
        
        valid_technicals = []
        for t, p in current_prices.items():
            if pd.isna(p): continue
            
            # Liquidity
            shares = shares_dict.get(t, 0)
            mcap = p * shares
            if mcap < 5000000000: continue
            
            # Solvency
            de = current_de.get(t, np.nan)
            if pd.isna(de) or de > 1.5: continue
            
            # Quality
            qual = current_qual.get(t, False)
            if not qual: continue
            
            # Trend
            s200 = current_sma.get(t, np.nan)
            if pd.isna(s200) or p <= s200: continue
            
            valid_technicals.append(t)
                
        # Rank by Momentum
        if not valid_technicals:
            portfolio_returns.append(0) # Cash
            continue
            
        current_mom = mom_rank.loc[:rebalance_date, valid_technicals].iloc[-1].dropna()
        top_10 = current_mom.nlargest(10).index.tolist()
        
        # 3. Calculate next month return
        # Equal weight
        next_month_prices = monthly_prices.loc[next_rebalance_date, top_10]
        current_month_prices = monthly_prices.loc[rebalance_date, top_10]
        
        stock_returns = (next_month_prices - current_month_prices) / current_month_prices
        port_return = stock_returns.mean() # Equal weight
        
        # Apply Leverage
        leveraged_return = port_return * leverage
        
        portfolio_returns.append(leveraged_return)

    # Performance Statistics
    port_series = pd.Series(portfolio_returns, index=month_ends[1:])
    cum_ret = (1 + port_series).cumprod()
    
    nifty_monthly = nifty.resample('ME').last()
    nifty_ret = nifty_monthly.pct_change().dropna()
    nifty_ret = nifty_ret.loc[port_series.index]
    nifty_cum = (1 + nifty_ret).cumprod()
    
    total_ret = (cum_ret.iloc[-1] - 1) * 100
    nifty_total = (nifty_cum.iloc[-1] - 1) * 100
    
    years = len(port_series) / 12
    cagr = ((cum_ret.iloc[-1] ** (1/years)) - 1) * 100
    nifty_cagr = ((nifty_cum.iloc[-1] ** (1/years)) - 1) * 100
    
    print("\n=== QTDL-Momentum Strategy Results ===")
    print(f"Backtest Period: {port_series.index[0].strftime('%Y-%m')} to {port_series.index[-1].strftime('%Y-%m')}")
    print(f"Total Return: {total_ret:.2f}% (NIFTY 500: {nifty_total:.2f}%)")
    print(f"CAGR: {cagr:.2f}% (NIFTY 500: {nifty_cagr:.2f}%)")
    
    # Max Drawdown
    roll_max = cum_ret.cummax()
    drawdown = (cum_ret - roll_max) / roll_max
    max_dd = drawdown.min() * 100
    print(f"Max Drawdown: {max_dd:.2f}%")
    
    conn.close()

if __name__ == "__main__":
    run_backtest()
