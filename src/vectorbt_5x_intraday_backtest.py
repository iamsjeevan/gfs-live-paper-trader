import sqlite3
import pandas as pd
import numpy as np
import os

# Disable vectorbt plotting layout auto-init to avoid plotly version mismatch
os.environ["VBT_PLOTTING_LAYOUT_LAYOUT_TEMPLATE"] = "none"

import vectorbt as vbt

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0 # ₹1 Lakh

def load_fno_data():
    conn = sqlite3.connect(DB_PATH)
    fno_symbols = pd.read_sql_query("""
    SELECT symbol, AVG(close * volume) as turnover
    FROM daily_prices WHERE date >= '2021-01-01'
    GROUP BY symbol HAVING turnover > 100000000
    ORDER BY turnover DESC LIMIT 150
    """, conn)['symbol'].tolist()

    query = f"""
    SELECT symbol, date, open, high, low, close, volume
    FROM daily_prices
    WHERE symbol IN ({','.join(['?']*len(fno_symbols))}) AND date >= '2021-01-01'
    ORDER BY date ASC
    """
    df = pd.read_sql_query(query, conn, params=fno_symbols)
    conn.close()
    df['date'] = pd.to_datetime(df['date'])
    return df, fno_symbols

def run_vbt_backtest():
    print("=" * 95)
    print("      OFFICIAL VECTORBT 5X LEVERAGE INTRADAY BACKTEST ENGINE (2021 - 2026)      ")
    print("=" * 95)

    df, fno_symbols = load_fno_data()

    pivoted_open = df.pivot(index='date', columns='symbol', values='open')
    pivoted_close = df.pivot(index='date', columns='symbol', values='close')
    pivoted_high = df.pivot(index='date', columns='symbol', values='high')
    pivoted_low = df.pivot(index='date', columns='symbol', values='low')
    pivoted_vol = df.pivot(index='date', columns='symbol', values='volume')

    # Indicator Matrices using VectorBT
    sma50 = pivoted_close.vbt.rolling_mean(50)
    vol_sma20 = pivoted_vol.vbt.rolling_mean(20)
    prev_close = pivoted_close.shift(1)

    # Vectorized Entry Signal Matrix
    entries = (prev_close > sma50.shift(1)) & (pivoted_vol > 1.5 * vol_sma20.shift(1)) & (pivoted_open > prev_close)

    vol_surge_rank = (pivoted_vol / vol_sma20.shift(1)).where(entries)
    top_5_entries = entries & (vol_surge_rank.rank(axis=1, ascending=False, method='first') <= 5)

    # Exit prices calculation
    price_drops = (pivoted_low - pivoted_open) / pivoted_open
    stop_loss_hit = price_drops <= -0.01

    exit_prices = pivoted_close.copy()
    exit_prices[stop_loss_hit] = pivoted_open[stop_loss_hit] * 0.99
    
    # Portfolio creation with 5.0x intraday leverage using VectorBT from_signals
    pf = vbt.Portfolio.from_signals(
        close=exit_prices,
        entries=top_5_entries,
        exits=top_5_entries,
        size=1.0, # 100% portfolio size per pick = 5x leverage across 5 picks
        size_type='percent',
        init_cash=INITIAL_CAPITAL,
        fees=0.0015, # 0.15% STT + Brokerage + Slippage
        freq='1D'
    )

    # Calculate aggregated portfolio equity curve across all symbols
    portfolio_value_curve = pf.value().sum(axis=1) - (INITIAL_CAPITAL * (len(fno_symbols) - 1))
    
    final_val = portfolio_value_curve.iloc[-1]
    total_profit = final_val - INITIAL_CAPITAL
    total_return = (total_profit / INITIAL_CAPITAL) * 100.0
    
    years = (pivoted_close.index[-1] - pivoted_close.index[50]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0 if final_val > 0 else -100.0
    
    peak = portfolio_value_curve.cummax()
    max_dd = ((portfolio_value_curve - peak) / peak * 100.0).min()

    print("\n" + "=" * 95)
    print("      SUMMARY PERFORMANCE HIGHLIGHTS (VECTORBT ENGINE)      ")
    print("=" * 95)
    print(f"💰 Starting Capital Base:        ₹1,00,000.00 (1 Lakh)")
    print(f"💵 Absolute Profit Earned:        ₹{total_profit:,.2f}")
    print(f"📈 Total Absolute Return:        +{total_return:,.2f}%")
    print(f"🚀 Compound CAGR (5 Years):      +{cagr:.2f}% per year")
    print(f"🔻 Max Peak-to-Trough Drawdown:  {max_dd:.2f}%")
    print(f"⚡ Intraday Leverage Used:       5.0x SEBI MIS Exposure")

if __name__ == "__main__":
    run_vbt_backtest()
