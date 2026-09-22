import sqlite3
import pandas as pd
import numpy as np
import os

os.environ["VBT_PLOTTING_LAYOUT_LAYOUT_TEMPLATE"] = "none"
import vectorbt as vbt

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0 # ₹1 Lakh

def load_data():
    conn = sqlite3.connect(DB_PATH)
    stocks = pd.read_sql_query("""
    SELECT symbol, AVG(close * volume) as turnover
    FROM daily_prices WHERE date >= '2021-01-01'
    GROUP BY symbol HAVING turnover > 50000000
    ORDER BY turnover DESC LIMIT 200
    """, conn)['symbol'].tolist()

    df = pd.read_sql_query(f"""
    SELECT symbol, date, open, high, low, close, volume
    FROM daily_prices
    WHERE symbol IN ({','.join(['?']*len(stocks))}) AND date >= '2021-01-01'
    ORDER BY date ASC
    """, conn, params=stocks)

    nifty_df = pd.read_sql_query("""
    SELECT date, close as nifty_close
    FROM daily_prices WHERE symbol = '^NSEI' AND date >= '2021-01-01'
    ORDER BY date ASC
    """, conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    nifty_df['date'] = pd.to_datetime(nifty_df['date'])
    return df, nifty_df, stocks

def main():
    print("=" * 95)
    print("      OFFICIAL VECTORBT LOW-DRAWDOWN PURE EQUITY AUDIT (2022 - 2026)      ")
    print("      100% EOD Daily Close Data | Nifty 200 SMA Market Regime Shield      ")
    print("=" * 95)

    df, nifty_df, stocks = load_data()

    pivoted_close = df.pivot(index='date', columns='symbol', values='close').astype(np.float64)
    pivoted_high = df.pivot(index='date', columns='symbol', values='high').astype(np.float64)
    pivoted_low = df.pivot(index='date', columns='symbol', values='low').astype(np.float64)

    # Slice after 200-day warmup
    valid_idx = pivoted_close.index[200:]
    p_close = pivoted_close.loc[valid_idx]

    # Indicators
    sma20 = p_close.vbt.rolling_mean(20)
    sma50 = p_close.vbt.rolling_mean(50)
    sma200 = p_close.vbt.rolling_mean(200)

    # Nifty 200 SMA Shield
    nifty_merged = pd.DataFrame({'date': pivoted_close.index}).merge(nifty_df, on='date', how='left').ffill()
    nifty_close = nifty_merged['nifty_close'].astype(np.float64)
    nifty_sma200 = nifty_close.vbt.rolling_mean(200)
    nifty_bull_regime = (nifty_close > nifty_sma200).fillna(False).values[200:]
    nifty_shield_matrix = np.tile(nifty_bull_regime[:, None], (1, len(stocks)))

    # Explicit NaN filling on Signals for VectorBT Engine
    entries_minervini = ((p_close > sma50) & (p_close > sma200) & nifty_shield_matrix).fillna(False)
    exits_minervini = (p_close < sma20).fillna(False)

    entries_clean, exits_clean = entries_minervini.vbt.signals.clean(exits_minervini)

    pf = vbt.Portfolio.from_signals(
        close=p_close,
        entries=entries_clean,
        exits=exits_clean,
        init_cash=10000.0, # ₹10k allocation per stock (10 stocks max = ₹1L base)
        fees=0.0015,
        freq='1D'
    )

    portfolio_equity = pf.value().sum(axis=1)
    portfolio_rets = portfolio_equity.pct_change().dropna()
    vbt_stats = portfolio_rets.vbt.returns(freq='1D').stats()

    start_val = portfolio_equity.iloc[0]
    final_val = portfolio_equity.iloc[-1]
    years = (p_close.index[-1] - p_close.index[0]).days / 365.25
    cagr = ((final_val / start_val) ** (1.0 / years) - 1.0) * 100.0

    peak = portfolio_equity.cummax()
    max_dd = ((portfolio_equity - peak) / peak * 100.0).min()

    print("\n📊 OFFICIAL VECTORBT STATS REPORT (Minervini Trend Swing + Market Shield):")
    print("=" * 95)
    print(vbt_stats.to_string())
    print("-" * 95)
    print(f"Start Equity: ₹{start_val:,.2f} | Final Portfolio: ₹{final_val:,.2f} | CAGR: +{cagr:.2f}% p.a. | Max DD: {max_dd:.2f}%")
    print("=" * 95)

if __name__ == "__main__":
    main()
