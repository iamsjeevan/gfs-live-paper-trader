import sqlite3
import pandas as pd
import numpy as np
import bt
import ffn
import warnings
warnings.filterwarnings('ignore')

print("Loading Data for bt framework...")
INDIA_DB = "data/nse_stocks_all_years.db"

# Load prices
conn = sqlite3.connect(INDIA_DB)
prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE date >= '2016-01-01' AND close IS NOT NULL", conn)
prices_df['Date'] = pd.to_datetime(prices_df['Date'])
prices = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').ffill()

# Load fundamentals
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
    qualifying_dict[y] = [s for s in prices.columns if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in q_set)]

print("Calculating technical indicators...")
sma200 = prices.rolling(window=200).mean()
sma50 = prices.rolling(window=50).mean()

m3 = prices.pct_change(63)
vol60 = prices.pct_change().rolling(60).std()
mom_score = m3 / (vol60 + 1e-6)

print("Calculating Daily Target Weights (with 50 SMA Exit)...")
# We will create a daily weights dataframe
target_weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

dates_df = pd.DataFrame({'Date': prices.index})
dates_df['ym'] = dates_df['Date'].dt.to_period('M')
# Month ends
monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()
start_date = pd.to_datetime('2018-01-01')
monthly_dates = [d for d in monthly_dates if d >= start_date]

# Create a list of all trading days
all_days = prices.index[prices.index >= start_date]
rebal_set = set(monthly_dates)

current_portfolio = []
current_alloc = 0.0

for date in all_days:
    if date in rebal_set:
        # Rebalance Day: Select new Top 10
        target_year = date.year - 1
        available = qualifying_dict.get(target_year, prices.columns.tolist())
        
        # Get scores
        if date in mom_score.index:
            current_scores = mom_score.loc[date, available].dropna()
            
            # Entry Filter: Price > 200 SMA AND Price >= 50 SMA
            valid_entry = []
            for t in current_scores.index:
                p = prices.loc[date, t]
                s200 = sma200.loc[date, t]
                s50 = sma50.loc[date, t]
                if p > s200 and p >= s50:
                    valid_entry.append(t)
            
            current_scores = current_scores.loc[valid_entry]
            
            if not current_scores.empty:
                top_10 = current_scores.nlargest(10).index.tolist()
                current_portfolio = top_10
                current_alloc = 1.0 / len(top_10)
            else:
                current_portfolio = []
                current_alloc = 0.0
                
    # On EVERY day (including rebalance days), check 50 SMA Exit
    # If a stock drops below 50 SMA, we remove it from current_portfolio for the rest of the month
    surviving_portfolio = []
    for t in current_portfolio:
        p = prices.loc[date, t]
        s50 = sma50.loc[date, t]
        if p >= s50:
            surviving_portfolio.append(t)
            
    current_portfolio = surviving_portfolio
    
    # Assign weights for today
    for t in current_portfolio:
        target_weights.loc[date, t] = current_alloc


print("Setting up bt Strategy...")
# Since target_weights changes daily (when a stock drops below 50 SMA), 
# we run the algo daily to catch exits immediately.
strategy = bt.Strategy('QTDL_Momentum_50SMA', [
    bt.algos.RunDaily(),
    bt.algos.SelectAll(),
    bt.algos.WeighTarget(target_weights),
    bt.algos.Rebalance()
])

# Create backtest
test = bt.Backtest(strategy, prices, initial_capital=100000.0, commissions=lambda q, p: abs(q)*p*0.003)

print("Running bt backtest...")
res = bt.run(test)

print("\n=== RESULTS FROM 'bt' LIBRARY (WITH 50 SMA EXIT) ===")
res.display()

stats = res.stats.loc[:, 'QTDL_Momentum_50SMA']
print(f"\nFinal Value (Lump Sum 100k, No SIP): ₹{stats['end']:,.2f}")
print(f"CAGR: {stats['cagr']*100:.2f}%")
print(f"Max Drawdown: {stats['max_drawdown']*100:.2f}%")
print(f"Sharpe Ratio: {stats['daily_sharpe']:.2f}")

