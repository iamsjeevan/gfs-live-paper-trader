import sqlite3
import pandas as pd
import vectorbt as vbt
import numpy as np
import warnings
warnings.filterwarnings("ignore")

print("Loading data from database...")
conn = sqlite3.connect("instocks.db")

# Load daily prices. To save memory and time for this initial test, we'll use a subset if needed, 
# but let's try loading all.
df = pd.read_sql("SELECT Date, Ticker, Adj_Close FROM daily_prices", conn)
df['Date'] = pd.to_datetime(df['Date'])

# Pivot to wide format (Dates as index, Tickers as columns)
print("Pivoting data...")
price = df.pivot(index='Date', columns='Ticker', values='Adj_Close')

# Forward fill missing values and drop columns that are mostly NaN
price = price.ffill()

# Let's run a simple moving average (SMA) crossover momentum strategy
# Fast SMA: 50 days, Slow SMA: 200 days
print("Calculating moving averages...")
fast_ma = vbt.MA.run(price, 50)
slow_ma = vbt.MA.run(price, 200)

# Generate signals
# Buy when 50-day MA crosses above 200-day MA
# Sell when 50-day MA crosses below 200-day MA
entries = fast_ma.ma_crossed_above(slow_ma)
exits = fast_ma.ma_crossed_below(slow_ma)

# Run backtest
# 1x money (cash sharing = True for portfolio level or just independent backtests)
# We will do independent backtests and then aggregate to see the average performance
print("Running vectorbt backtest...")
portfolio = vbt.Portfolio.from_signals(
    price,
    entries,
    exits,
    freq='1D',
    init_cash=10000,
    fees=0.001, # 0.1% slippage/fees
    cash_sharing=False # Each stock traded independently to get average stats
)

print("\n--- Strategy Results (Mean across all 1505 Indian stocks) ---")
# Get metrics for all and average them
stats = portfolio.stats()
print(stats)
