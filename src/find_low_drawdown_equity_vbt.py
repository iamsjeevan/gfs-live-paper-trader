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
    # Fetch top liquid 200 NSE stocks + Nifty 50 Index
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

    # Load Nifty 50 Benchmark for Market Shield
    nifty_df = pd.read_sql_query("""
    SELECT date, close as nifty_close
    FROM daily_prices WHERE symbol = '^NSEI' AND date >= '2021-01-01'
    ORDER BY date ASC
    """, conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    nifty_df['date'] = pd.to_datetime(nifty_df['date'])

    return df, nifty_df, stocks

def evaluate_vbt_strategy(close_df, high_df, low_df, entries, exits, strat_name):
    # Clean signals to eliminate duplicate entries
    entries_clean, exits_clean = entries.vbt.signals.clean(exits)

    pf = vbt.Portfolio.from_signals(
        close=close_df,
        entries=entries_clean,
        exits=exits_clean,
        size=0.10, # 10-stock diversification (10% allocation per stock)
        size_type='percent',
        init_cash=INITIAL_CAPITAL,
        fees=0.0015,
        freq='1D'
    )

    portfolio_equity = pf.value().sum(axis=1) - (INITIAL_CAPITAL * (len(close_df.columns) - 1))
    portfolio_returns = portfolio_equity.pct_change().dropna()
    
    final_val = portfolio_equity.iloc[-1]
    years = (close_df.index[-1] - close_df.index[252]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0 if final_val > 0 else -100.0
    
    peak = portfolio_equity.cummax()
    max_dd = ((portfolio_equity - peak) / peak * 100.0).min()

    sharpe = (portfolio_returns.mean() / portfolio_returns.std()) * np.sqrt(252) if portfolio_returns.std() > 0 else 0.0
    downside_std = portfolio_returns[portfolio_returns < 0].std()
    sortino = (portfolio_returns.mean() / downside_std) * np.sqrt(252) if downside_std > 0 else 0.0

    return {
        "name": strat_name,
        "finalVal": round(final_val, 2),
        "cagr": round(cagr, 2),
        "maxDD": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2)
    }

def main():
    print("=" * 95)
    print("      LOW-DRAWDOWN PURE EQUITY STRATEGY SEARCH (VECTORBT ENGINE)      ")
    print("      Target: High Sharpe Ratio | Low Max Drawdown (< -25%) | 100% EOD Daily Data      ")
    print("=" * 95)

    df, nifty_df, stocks = load_data()

    pivoted_close = df.pivot(index='date', columns='symbol', values='close').astype(np.float64)
    pivoted_high = df.pivot(index='date', columns='symbol', values='high').astype(np.float64)
    pivoted_low = df.pivot(index='date', columns='symbol', values='low').astype(np.float64)
    pivoted_vol = df.pivot(index='date', columns='symbol', values='volume').astype(np.float64)

    # Nifty 200 SMA Shield (Go 100% Cash when Nifty < 200 SMA)
    nifty_merged = pd.DataFrame({'date': pivoted_close.index}).merge(nifty_df, on='date', how='left').ffill()
    nifty_close = nifty_merged['nifty_close'].astype(np.float64)
    nifty_sma200 = nifty_close.vbt.rolling_mean(200)
    nifty_bull_regime = (nifty_close > nifty_sma200).values # Boolean Array

    # Broaden Boolean Array to 2D Matrix matching pivoted_close shape
    nifty_shield_matrix = np.tile(nifty_bull_regime[:, None], (1, len(stocks)))

    # VectorBT Indicators
    sma20 = pivoted_close.vbt.rolling_mean(20)
    sma50 = pivoted_close.vbt.rolling_mean(50)
    sma200 = pivoted_close.vbt.rolling_mean(200)
    rsi14 = vbt.RSI.run(pivoted_close, window=14).rsi
    atr14 = vbt.ATR.run(pivoted_high, pivoted_low, pivoted_close, window=14).atr

    results = []

    # -------------------------------------------------------------------------
    # STRATEGY 1: Minervini VCP + 200 SMA Market Shield (10-Stock Diversified)
    # Entry: Close > 50 SMA & Close > 200 SMA & Volatility Contraction (ATR/Close < 0.03) & Nifty > 200 SMA
    # Exit: Close < 20 SMA OR Nifty < 200 SMA
    # -------------------------------------------------------------------------
    vol_contraction = (atr14 / pivoted_close) < 0.035
    entries_vcp = (pivoted_close > sma50) & (pivoted_close > sma200) & vol_contraction & nifty_shield_matrix
    exits_vcp = (pivoted_close < sma20) | (~nifty_shield_matrix)
    results.append(evaluate_vbt_strategy(pivoted_close, pivoted_high, pivoted_low, entries_vcp, exits_vcp, "Minervini VCP + Market Shield"))

    # -------------------------------------------------------------------------
    # STRATEGY 2: 20 EMA Pullback Bounce + 200 SMA Shield
    # Entry: Close > 200 SMA & Close crosses above 20 EMA & Nifty > 200 SMA
    # Exit: Close < 20 EMA OR Nifty < 200 SMA
    # -------------------------------------------------------------------------
    ema20 = pivoted_close.vbt.ewm_mean(span=20)
    entries_pullback = (pivoted_close > sma200) & (pivoted_close.vbt.crossed_above(ema20)) & nifty_shield_matrix
    exits_pullback = (pivoted_close < ema20) | (~nifty_shield_matrix)
    results.append(evaluate_vbt_strategy(pivoted_close, pivoted_high, pivoted_low, entries_pullback, exits_pullback, "EMA 20 Pullback + Market Shield"))

    # -------------------------------------------------------------------------
    # STRATEGY 3: RSI Trend Mean-Reversion + Market Shield
    # Entry: Close > 200 SMA & RSI < 40 (Oversold Dip in Bull Trend) & Nifty > 200 SMA
    # Exit: RSI > 65 OR Nifty < 200 SMA
    # -------------------------------------------------------------------------
    entries_rsi = (pivoted_close > sma200) & (rsi14 < 40) & nifty_shield_matrix
    exits_rsi = (rsi14 > 65) | (~nifty_shield_matrix)
    results.append(evaluate_vbt_strategy(pivoted_close, pivoted_high, pivoted_low, entries_rsi, exits_rsi, "RSI Dip Pullback + Market Shield"))

    # -------------------------------------------------------------------------
    # STRATEGY 4: Dual Momentum Relative Strength + Market Shield
    # Entry: 6-Month Return > Nifty 6-Month Return & Close > 50 SMA & Nifty > 200 SMA
    # Exit: Close < 50 SMA OR Nifty < 200 SMA
    # -------------------------------------------------------------------------
    ret_6m = pivoted_close.pct_change(126)
    entries_dual = (ret_6m > 0.15) & (pivoted_close > sma50) & nifty_shield_matrix
    exits_dual = (pivoted_close < sma50) | (~nifty_shield_matrix)
    results.append(evaluate_vbt_strategy(pivoted_close, pivoted_high, pivoted_low, entries_dual, exits_dual, "Dual Relative Momentum + Shield"))

    # Print Official Summary Matrix
    res_df = pd.DataFrame(results).sort_values(by="sharpe", ascending=False)
    print("\n📊 VECTORBT LOW-DRAWDOWN EQUITY LEADERBOARD:")
    print("=" * 95)
    print(res_df.to_string(index=False))
    print("=" * 95)

if __name__ == "__main__":
    main()
