import sqlite3
import pandas as pd
import numpy as np
import os

os.environ["VBT_PLOTTING_LAYOUT_LAYOUT_TEMPLATE"] = "none"
import vectorbt as vbt

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0

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
    print("      OFFICIAL VECTORBT LOW-DRAWDOWN PURE EQUITY BACKTEST (2022 - 2026)      ")
    print("      100% EOD Daily Close Data | Nifty 200 SMA Market Regime Shield      ")
    print("=" * 95)

    df, nifty_df, stocks = load_data()

    pivoted_close = df.pivot(index='date', columns='symbol', values='close').astype(np.float64)
    pivoted_high = df.pivot(index='date', columns='symbol', values='high').astype(np.float64)
    pivoted_low = df.pivot(index='date', columns='symbol', values='low').astype(np.float64)

    # Calculate indicators
    sma20 = pivoted_close.vbt.rolling_mean(20)
    sma50 = pivoted_close.vbt.rolling_mean(50)
    sma200 = pivoted_close.vbt.rolling_mean(200)
    atr14 = vbt.ATR.run(pivoted_high, pivoted_low, pivoted_close, window=14).atr

    # Nifty Regime Shield
    nifty_merged = pd.DataFrame({'date': pivoted_close.index}).merge(nifty_df, on='date', how='left').ffill()
    nifty_close = nifty_merged['nifty_close'].astype(np.float64)
    nifty_sma200 = nifty_close.vbt.rolling_mean(200)
    
    # Fill NA to prevent early exits during 200-day warmup
    nifty_bull_regime = (nifty_close > nifty_sma200).fillna(False).values
    nifty_shield_matrix = np.tile(nifty_bull_regime[:, None], (1, len(stocks)))

    # Slice after 200-day warmup period so indicators are valid
    valid_idx = pivoted_close.index[200:]

    p_close = pivoted_close.loc[valid_idx]
    s_sma20 = sma20.loc[valid_idx]
    s_sma50 = sma50.loc[valid_idx]
    s_sma200 = sma200.loc[valid_idx]
    s_atr14 = atr14.loc[valid_idx]
    n_shield = nifty_shield_matrix[200:]

    # -----------------------------------------------------------------------
    # STRATEGY A: Minervini VCP + Market Shield
    # Entry: Close > 50 SMA & Volatility Contraction (ATR/Close < 0.035) & Nifty > 200 SMA
    # Exit: Close < 20 SMA OR Nifty < 200 SMA
    # -----------------------------------------------------------------------
    vol_contraction = (s_atr14 / p_close) < 0.035
    entries_vcp = (p_close > s_sma50) & (p_close > s_sma200) & vol_contraction & n_shield
    exits_vcp = (p_close < s_sma20) | (~n_shield)

    entries_vcp_clean, exits_vcp_clean = entries_vcp.vbt.signals.clean(exits_vcp)

    pf_vcp = vbt.Portfolio.from_signals(
        close=p_close,
        entries=entries_vcp_clean,
        exits=exits_vcp_clean,
        size=0.10, # 10% sizing = 10-stock portfolio limit
        size_type='percent',
        init_cash=INITIAL_CAPITAL,
        fees=0.0015,
        freq='1D'
    )

    # -----------------------------------------------------------------------
    # STRATEGY B: 20 EMA Pullback Swing + Market Shield
    # Entry: Close > 200 SMA & Close > 20 EMA & Nifty > 200 SMA
    # Exit: Close < 20 EMA OR Nifty < 200 SMA
    # -----------------------------------------------------------------------
    s_ema20 = p_close.vbt.ewm_mean(span=20)
    entries_ema = (p_close > s_sma200) & (p_close > s_ema20) & n_shield
    exits_ema = (p_close < s_ema20) | (~n_shield)

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

    print("\n📊 VECTORBT NATIVE STATS REPORT (Minervini VCP + Market Shield):")
    print("=" * 95)
    print(pf_vcp.stats().to_string())

    print("\n" + "=" * 95)
    print("📊 VECTORBT NATIVE STATS REPORT (20 EMA Pullback + Market Shield):")
    print("=" * 95)
    print(pf_ema.stats().to_string())
    print("=" * 95)

if __name__ == "__main__":
    main()
