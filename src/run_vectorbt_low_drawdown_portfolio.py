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
    p_high = pivoted_high.loc[valid_idx]
    p_low = pivoted_low.loc[valid_idx]

    # Calculate indicators
    sma20 = p_close.vbt.rolling_mean(20)
    sma50 = p_close.vbt.rolling_mean(50)
    sma200 = p_close.vbt.rolling_mean(200)

    # Nifty Regime Shield (Only trade when Nifty > 200 SMA)
    nifty_merged = pd.DataFrame({'date': pivoted_close.index}).merge(nifty_df, on='date', how='left').ffill()
    nifty_close = nifty_merged['nifty_close'].astype(np.float64)
    nifty_sma200 = nifty_close.vbt.rolling_mean(200)
    
    nifty_bull_regime = (nifty_close > nifty_sma200).fillna(False).values[200:]
    nifty_shield_matrix = np.tile(nifty_bull_regime[:, None], (1, len(stocks)))

    # -----------------------------------------------------------------------
    # STRATEGY 1: Minervini Trend Swing + Nifty 200 SMA Shield
    # Entry: Close > 50 SMA & Close > 200 SMA & Nifty > 200 SMA
    # Exit: Close < 20 SMA
    # -----------------------------------------------------------------------
    entries_vcp = (p_close > sma50) & (p_close > sma200) & nifty_shield_matrix
    exits_vcp = (p_close < sma20)

    entries_vcp_clean, exits_vcp_clean = entries_vcp.vbt.signals.clean(exits_vcp)

    pf_vcp = vbt.Portfolio.from_signals(
        close=p_close,
        entries=entries_vcp_clean,
        exits=exits_vcp_clean,
        size=0.10, # 10% per stock = 10 stocks max
        size_type='percent',
        init_cash=INITIAL_CAPITAL,
        fees=0.0015,
        freq='1D'
    )

    # -----------------------------------------------------------------------
    # STRATEGY 2: 20 EMA Pullback Swing + Nifty 200 SMA Shield
    # Entry: Close > 200 SMA & Close > 20 EMA & Nifty > 200 SMA
    # Exit: Close < 20 EMA
    # -----------------------------------------------------------------------
    ema20 = p_close.vbt.ewm_mean(span=20)
    entries_ema = (p_close > sma200) & (p_close > ema20) & nifty_shield_matrix
    exits_ema = (p_close < ema20)

    entries_ema_clean, exits_ema_clean = entries_ema.vbt.signals.clean(exits_ema)

    pf_ema = vbt.Portfolio.from_signals(
        close=p_close,
        entries=entries_ema_clean,
        exits=exits_ema_clean,
        size=0.10,
        size_type='percent',
        init_cash=INITIAL_CAPITAL,
        fees=0.0015,
        freq='1D'
    )

    # Portfolio returns & statistics
    portfolio_equity_vcp = pf_vcp.value().sum(axis=1) - (INITIAL_CAPITAL * (len(stocks) - 1))
    portfolio_returns_vcp = portfolio_equity_vcp.pct_change().dropna()
    stats_vcp = portfolio_returns_vcp.vbt.returns(freq='1D').stats()

    portfolio_equity_ema = pf_ema.value().sum(axis=1) - (INITIAL_CAPITAL * (len(stocks) - 1))
    portfolio_returns_ema = portfolio_equity_ema.pct_change().dropna()
    stats_ema = portfolio_returns_ema.vbt.returns(freq='1D').stats()

    print("\n📊 OFFICIAL VECTORBT STATS REPORT (Minervini Trend Swing + Market Shield):")
    print("=" * 95)
    print(stats_vcp.to_string())

    print("\n" + "=" * 95)
    print("📊 OFFICIAL VECTORBT STATS REPORT (20 EMA Pullback + Market Shield):")
    print("=" * 95)
    print(stats_ema.to_string())
    print("=" * 95)

if __name__ == "__main__":
    main()
