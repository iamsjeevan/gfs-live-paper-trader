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

def run_vbt_strategy(p_close, p_high, p_low, entries, exits, strat_name):
    entries_clean, exits_clean = entries.vbt.signals.clean(exits)

    pf = vbt.Portfolio.from_signals(
        close=p_close,
        entries=entries_clean,
        exits=exits_clean,
        size=0.10, # 10% per stock allocation
        size_type='percent',
        init_cash=INITIAL_CAPITAL,
        fees=0.0015,
        freq='1D'
    )

    # Compute portfolio value aggregated across all stocks
    portfolio_val = pf.value().sum(axis=1) - (INITIAL_CAPITAL * (len(p_close.columns) - 1))
    portfolio_rets = portfolio_val.pct_change().dropna()
    vbt_stats = portfolio_rets.vbt.returns(freq='1D').stats()

    final_val = portfolio_val.iloc[-1]
    years = (p_close.index[-1] - p_close.index[0]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0

    peak = portfolio_val.cummax()
    max_dd = ((portfolio_val - peak) / peak * 100.0).min()

    print(f"\n==========================================================================================")
    print(f"📊 VECTORBT NATIVE REPORT: {strat_name}")
    print(f"==========================================================================================")
    print(vbt_stats.to_string())
    print(f"------------------------------------------------------------------------------------------")
    print(f"Final Capital: ₹{final_val:,.2f} | CAGR: +{cagr:.2f}% p.a. | Max DD: {max_dd:.2f}%")
    print(f"==========================================================================================")

def main():
    df, nifty_df, stocks = load_data()

    pivoted_close = df.pivot(index='date', columns='symbol', values='close').astype(np.float64)
    pivoted_high = df.pivot(index='date', columns='symbol', values='high').astype(np.float64)
    pivoted_low = df.pivot(index='date', columns='symbol', values='low').astype(np.float64)

    # Slice after 200-day warmup
    valid_idx = pivoted_close.index[200:]
    p_close = pivoted_close.loc[valid_idx]
    p_high = pivoted_high.loc[valid_idx]
    p_low = pivoted_low.loc[valid_idx]

    # VectorBT Indicators
    sma20 = p_close.vbt.rolling_mean(20)
    sma50 = p_close.vbt.rolling_mean(50)
    sma200 = p_close.vbt.rolling_mean(200)
    atr14 = vbt.ATR.run(p_high, p_low, p_close, window=14).atr

    # Nifty 200 SMA Shield
    nifty_merged = pd.DataFrame({'date': pivoted_close.index}).merge(nifty_df, on='date', how='left').ffill()
    nifty_close = nifty_merged['nifty_close'].astype(np.float64)
    nifty_sma200 = nifty_close.vbt.rolling_mean(200)
    nifty_bull_regime = (nifty_close > nifty_sma200).fillna(False).values[200:]
    nifty_shield_matrix = np.tile(nifty_bull_regime[:, None], (1, len(stocks)))

    # 1. Minervini Trend Swing + Nifty 200 SMA Shield
    vol_contraction = (atr14 / p_close) < 0.04
    entries_vcp = (p_close > sma50) & (p_close > sma200) & vol_contraction & nifty_shield_matrix
    exits_vcp = (p_close < sma20)
    run_vbt_strategy(p_close, p_high, p_low, entries_vcp, exits_vcp, "Minervini VCP + Market Shield (Low Drawdown Target)")

    # 2. 20 EMA Pullback Swing + Nifty 200 SMA Shield
    ema20 = p_close.vbt.ewm_mean(span=20)
    entries_ema = (p_close > sma200) & (p_close > ema20) & nifty_shield_matrix
    exits_ema = (p_close < ema20)
    run_vbt_strategy(p_close, p_high, p_low, entries_ema, exits_ema, "20 EMA Pullback Swing + Market Shield")

if __name__ == "__main__":
    main()
