import sqlite3
import pandas as pd
import numpy as np
import os

os.environ["VBT_PLOTTING_LAYOUT_LAYOUT_TEMPLATE"] = "none"
import vectorbt as vbt

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0
STT_BROKERAGE_SLIPPAGE = 0.0015 # 0.15% round-trip

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

def main():
    df, fno_symbols = load_fno_data()

    pivoted_open = df.pivot(index='date', columns='symbol', values='open')
    pivoted_close = df.pivot(index='date', columns='symbol', values='close')
    pivoted_low = df.pivot(index='date', columns='symbol', values='low')
    pivoted_vol = df.pivot(index='date', columns='symbol', values='volume')

    sma50 = pivoted_close.rolling(50).mean()
    vol_sma20 = pivoted_vol.rolling(20).mean()
    prev_close = pivoted_close.shift(1)

    entries = (prev_close > sma50.shift(1)) & (pivoted_vol > 1.5 * vol_sma20.shift(1)) & (pivoted_open > prev_close)
    vol_surge_rank = (pivoted_vol / vol_sma20.shift(1)).where(entries)
    top_5_mask = entries & (vol_surge_rank.rank(axis=1, ascending=False, method='first') <= 5)

    dates = pivoted_close.index
    portfolio_daily_returns = []

    for i in range(50, len(dates)):
        curr_d = dates[i]
        valid_stocks = top_5_mask.loc[curr_d]
        active_symbols = valid_stocks[valid_stocks].index.tolist()

        if active_symbols:
            n_picks = len(active_symbols)
            # 5.0x Intraday Exposure = 1.0 size per stock across 5 picks
            alloc_per_stock = 5.0 / n_picks
            
            o_vals = pivoted_open.loc[curr_d, active_symbols]
            c_vals = pivoted_close.loc[curr_d, active_symbols]
            l_vals = pivoted_low.loc[curr_d, active_symbols]

            drop_pcts = (l_vals - o_vals) / o_vals
            
            # 1% Stop Loss Exit or Close Exit
            rets = np.where(drop_pcts <= -0.01, -0.01 - STT_BROKERAGE_SLIPPAGE, ((c_vals - o_vals) / o_vals) - STT_BROKERAGE_SLIPPAGE)
            
            day_ret = np.sum(alloc_per_stock * rets)
            portfolio_daily_returns.append(day_ret)
        else:
            portfolio_daily_returns.append(0.0)

    returns_series = pd.Series(portfolio_daily_returns, index=dates[50:])

    # Official VectorBT Returns Accessor Stats
    print("\n" + "=" * 80)
    print("      OFFICIAL VECTORBT ENGINE NATIVE STATS OUTPUT (vbt.returns.stats)      ")
    print("=" * 80)
    stats_out = returns_series.vbt.returns(freq='1D').stats()
    print(stats_out.to_string())
    print("=" * 80)

if __name__ == "__main__":
    main()
