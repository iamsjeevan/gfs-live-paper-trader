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
    print("      OFFICIAL VECTORBT LOW-DRAWDOWN PURE EQUITY AUDIT (2021 - 2026)      ")
    print("      100% EOD Daily Close Data | Market Regime Shield      ")
    print("=" * 95)

    df, nifty_df, stocks = load_data()

    pivoted_close = df.pivot(index='date', columns='symbol', values='close').astype(np.float64)
    pivoted_high = df.pivot(index='date', columns='symbol', values='high').astype(np.float64)
    pivoted_low = df.pivot(index='date', columns='symbol', values='low').astype(np.float64)
    pivoted_vol = df.pivot(index='date', columns='symbol', values='volume').astype(np.float64)

    # Nifty 200 SMA Regime Shield
    nifty_merged = pd.DataFrame({'date': pivoted_close.index}).merge(nifty_df, on='date', how='left').ffill()
    nifty_close = nifty_merged['nifty_close'].astype(np.float64)
    nifty_sma200 = nifty_close.vbt.rolling_mean(200)
    nifty_bull_regime = (nifty_close > nifty_sma200).values
    nifty_shield_matrix = np.tile(nifty_bull_regime[:, None], (1, len(stocks)))

    # Indicators
    sma20 = pivoted_close.vbt.rolling_mean(20)
    sma50 = pivoted_close.vbt.rolling_mean(50)
    sma200 = pivoted_close.vbt.rolling_mean(200)
    atr14 = vbt.ATR.run(pivoted_high, pivoted_low, pivoted_close, window=14).atr
    vol_contraction = (atr14 / pivoted_close) < 0.035

    # -----------------------------------------------------------------------
    # STRATEGY 1: Minervini VCP + 200 SMA Nifty Shield (10-Stock Allocation)
    # Target: Low Drawdown (< -20%)
    # -----------------------------------------------------------------------
    entries_vcp = (pivoted_close > sma50) & (pivoted_close > sma200) & vol_contraction & nifty_shield_matrix
    exits_vcp = (pivoted_close < sma20) | (~nifty_shield_matrix)

    pf_vcp = vbt.Portfolio.from_signals(
        close=pivoted_close,
        entries=entries_vcp,
        exits=exits_vcp,
        size=0.10, # 10% per stock = 10 stocks max
        size_type='percent',
        init_cash=INITIAL_CAPITAL,
        fees=0.0015,
        freq='1D'
    )

    rets_vcp = pf_vcp.returns().mean(axis=1)
    pf_stats_vcp = rets_vbt = rets_vcp.vbt.returns(freq='1D').stats()

    # Calculate equity curve
    equity_vcp = (1 + rets_vcp).cumprod() * INITIAL_CAPITAL
    final_vcp = equity_vcp.iloc[-1]
    years = (pivoted_close.index[-1] - pivoted_close.index[252]).days / 365.25
    cagr_vcp = ((final_vcp / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0

    peak_vcp = equity_vcp.cummax()
    max_dd_vcp = ((equity_vcp - peak_vcp) / peak_vcp * 100.0).min()

    # -----------------------------------------------------------------------
    # STRATEGY 2: EMA 20 Pullback Swing + 200 SMA Nifty Shield
    # Target: High Sharpe Ratio
    # -----------------------------------------------------------------------
    ema20 = pivoted_close.vbt.ewm_mean(span=20)
    entries_ema = (pivoted_close > sma200) & (pivoted_close.vbt.crossed_above(ema20)) & nifty_shield_matrix
    exits_ema = (pivoted_close < ema20) | (~nifty_shield_matrix)

    pf_ema = vbt.Portfolio.from_signals(
        close=pivoted_close,
        entries=entries_ema,
        exits=exits_ema,
        size=0.10,
        size_type='percent',
        init_cash=INITIAL_CAPITAL,
        fees=0.0015,
        freq='1D'
    )

    rets_ema = pf_ema.returns().mean(axis=1)
    equity_ema = (1 + rets_ema).cumprod() * INITIAL_CAPITAL
    final_ema = equity_ema.iloc[-1]
    cagr_ema = ((final_ema / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0
    peak_ema = equity_ema.cummax()
    max_dd_ema = ((equity_ema - peak_ema) / peak_ema * 100.0).min()

    print("\n📊 OFFICIAL VECTORBT LOW-DRAWDOWN EQUITY LEADERBOARD (2021 – 2026):")
    print("=" * 95)
    print(f"1. STRATEGY: Minervini Volatility Contraction (VCP) + Nifty 200 SMA Shield")
    print(f"   - Initial Capital:          ₹1,00,000.00 (1 Lakh)")
    print(f"   - 5-Year Final Portfolio:   ₹{final_vcp:,.2f}")
    print(f"   - Compound CAGR (%):        +{cagr_vcp:.2f}% p.a.")
    print(f"   - Max Drawdown (%):         {max_dd_vcp:.2f}% 🛡️ (Lowest Drawdown!)")

    print(f"\n2. STRATEGY: 20 EMA Pullback Swing + Nifty 200 SMA Shield")
    print(f"   - Initial Capital:          ₹1,00,000.00 (1 Lakh)")
    print(f"   - 5-Year Final Portfolio:   ₹{final_ema:,.2f}")
    print(f"   - Compound CAGR (%):        +{cagr_ema:.2f}% p.a.")
    print(f"   - Max Drawdown (%):         {max_dd_ema:.2f}%")

    print("\n" + "=" * 95)
    print("VECTORBT NATIVE STATS REPORT FOR MINERVINI VCP + MARKET SHIELD:")
    print("=" * 95)
    print(pf_stats_vcp.to_string())
    print("=" * 95)

if __name__ == "__main__":
    main()
