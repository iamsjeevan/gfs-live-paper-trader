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
prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE date >= '2017-01-01' AND close IS NOT NULL", conn)
prices_df['Date'] = pd.to_datetime(prices_df['Date'])
prices = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').ffill()

# Load fundamental qualifying dict (from user's logic)
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
# Momentum: 3M return / 60-day volatility
m3 = prices.pct_change(63)
vol60 = prices.pct_change().rolling(60).std()
mom_score = m3 / (vol60 + 1e-6)

# Create a signal DataFrame where True means we want to hold it
# We need to rank them and select top 10 per month
# We can do this outside bt to create target weights
print("Calculating Target Weights...")
target_weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

# We only update weights at month ends
dates_df = pd.DataFrame({'Date': prices.index})
dates_df['ym'] = dates_df['Date'].dt.to_period('M')
monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()
monthly_dates = [d for d in monthly_dates if d >= pd.to_datetime('2018-01-01')]

for date in monthly_dates:
    if date not in mom_score.index: continue
    
    target_year = date.year - 1
    available = qualifying_dict.get(target_year, prices.columns.tolist())
    
    # Get scores for available stocks
    current_scores = mom_score.loc[date, available].dropna()
    current_scores = current_scores[prices.loc[date, current_scores.index] > 0]
    
    if current_scores.empty: continue
    
    # Top 10
    top_10 = current_scores.nlargest(10).index
    
    # Assign equal weights (10% each)
    target_weights.loc[date, top_10] = 1.0 / len(top_10)

# Forward fill weights so bt knows what to hold throughout the month, 
# although we only rebalance on the specific dates when target_weights changes.
# Actually, bt.algos.WeighTarget uses the target weights directly.

print("Setting up bt Strategy...")
# bt strategy
strategy = bt.Strategy('QTDL_Momentum_bt', [
    bt.algos.RunMonthly(),
    bt.algos.SelectAll(),
    bt.algos.WeighTarget(target_weights),
    bt.algos.Rebalance()
])

# Create backtest
# Note: This is lump sum 100k, not SIP. 
test = bt.Backtest(strategy, prices, initial_capital=100000.0, commissions=lambda q, p: abs(q)*p*0.003)

print("Running bt backtest...")
res = bt.run(test)

print("\n=== RESULTS FROM 'bt' LIBRARY ===")
res.display()

# Also get exact values
stats = res.stats.loc[:, 'QTDL_Momentum_bt']
print(f"\nFinal Value (Lump Sum 100k, No SIP): ₹{stats['end']:,.2f}")
print(f"CAGR: {stats['cagr']*100:.2f}%")
print(f"Max Drawdown: {stats['max_drawdown']*100:.2f}%")
print(f"Sharpe Ratio: {stats['daily_sharpe']:.2f}")

