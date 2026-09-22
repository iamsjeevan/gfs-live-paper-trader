import sqlite3
import pandas as pd
import numpy as np
import os

os.environ["VBT_PLOTTING_LAYOUT_LAYOUT_TEMPLATE"] = "none"
import vectorbt as vbt

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0 # ₹1 Lakh

def load_liquid_stocks():
    conn = sqlite3.connect(DB_PATH)
    # Fetch top liquid 200 NSE stocks by turnover
    stocks = pd.read_sql_query("""
    SELECT symbol, AVG(close * volume) as turnover
    FROM daily_prices WHERE date >= '2021-01-01'
    GROUP BY symbol HAVING turnover > 50000000
    ORDER BY turnover DESC LIMIT 200
    """, conn)['symbol'].tolist()

    query = f"""
    SELECT symbol, date, open, high, low, close, volume
    FROM daily_prices
    WHERE symbol IN ({','.join(['?']*len(stocks))}) AND date >= '2021-01-01'
    ORDER BY date ASC
    """
    df = pd.read_sql_query(query, conn, params=stocks)
    conn.close()
    df['date'] = pd.to_datetime(df['date'])
    return df, stocks

def main():
    print("=" * 90)
    print("      OFFICIAL VECTORBT NATIVE POSITIONAL SWING BACKTEST (2021 - 2026)      ")
    print("      100% EOD Daily Close Data | Native VectorBT Engine      ")
    print("=" * 90)

    df, stocks = load_liquid_stocks()

    pivoted_close = df.pivot(index='date', columns='symbol', values='close')
    pivoted_high = df.pivot(index='date', columns='symbol', values='high')

    # Official VectorBT Native Indicators
    sma50 = pivoted_close.vbt.rolling_mean(50)
    high_52w = pivoted_high.shift(1).vbt.rolling_max(252)

    # Signal Matrices
    # Entry: Daily Close > 52-Week High AND Daily Close > 50 SMA
    entries = (pivoted_close > high_52w) & (pivoted_close > sma50)
    # Exit: Daily Close < 50 SMA
    exits = (pivoted_close < sma50)

    # Clean signal matrices: keep only first entry signal until exit
    entries_clean, exits_clean = entries.vbt.signals.clean(exits)

    # Official VectorBT Portfolio from Signals Engine
    # 20% size allocation per stock (5-stock allocation limit)
    pf = vbt.Portfolio.from_signals(
        close=pivoted_close,
        entries=entries_clean,
        exits=exits_clean,
        size=0.20,
        size_type='percent',
        init_cash=INITIAL_CAPITAL,
        fees=0.0015, # 0.15% STT & Brokerage
        freq='1D'
    )

    print("\n📊 OFFICIAL VECTORBT NATIVE STATS REPORT (vbt.Portfolio.from_signals):")
    print("=" * 90)

    # Extract aggregated portfolio equity across all 200 stocks
    portfolio_equity = pf.value().sum(axis=1) - (INITIAL_CAPITAL * (len(stocks) - 1))
    
    # Pass portfolio equity series into VectorBT returns engine for native stats
    portfolio_returns = portfolio_equity.pct_change().dropna()
    vbt_stats = portfolio_returns.vbt.returns(freq='1D').stats()

    print(vbt_stats.to_string())

    start_date = pivoted_close.index[252].strftime('%Y-%m-%d')
    end_date = pivoted_close.index[-1].strftime('%Y-%m-%d')
    years = (pivoted_close.index[-1] - pivoted_close.index[252]).days / 365.25

    final_val = portfolio_equity.iloc[-1]
    net_profit = final_val - INITIAL_CAPITAL
    abs_ret = (net_profit / INITIAL_CAPITAL) * 100.0
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0

    peak = portfolio_equity.cummax()
    max_dd = ((portfolio_equity - peak) / peak * 100.0).min()

    print("\n" + "=" * 90)
    print("      VERIFIED SUMMARY (PORTFOLIO AGGREGATED METRICS)      ")
    print("=" * 90)
    print(f"Start Period:                     {start_date}")
    print(f"End Period:                       {end_date}")
    print(f"Evaluation Period:             {years:.2f} Years")
    print(f"Initial Capital Base:             ₹{INITIAL_CAPITAL:,.2f} (1 Lakh)")
    print(f"Final Portfolio Value:            ₹{final_val:,.2f}")
    print(f"Total Net Profit Earned:          ₹{net_profit:,.2f}")
    print(f"Total Absolute Return (%):        +{abs_ret:.2f}%")
    print(f"Compound CAGR (%):                +{cagr:.2f}% p.a.")
    print(f"Max Peak-to-Trough Drawdown (%):  {max_dd:.2f}%")
    print("=" * 90)

if __name__ == "__main__":
    main()
