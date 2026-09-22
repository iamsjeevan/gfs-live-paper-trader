import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0 # ₹1 Lakh
STT_BROKERAGE_SLIPPAGE = 0.0015 # 0.15% round-trip transaction fee

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

def run_pure_vectorized_sim(leverage=5.0):
    df, fno_symbols = load_fno_data()

    pivoted_open = df.pivot(index='date', columns='symbol', values='open')
    pivoted_close = df.pivot(index='date', columns='symbol', values='close')
    pivoted_low = df.pivot(index='date', columns='symbol', values='low')
    pivoted_vol = df.pivot(index='date', columns='symbol', values='volume')

    # Vectorized Rolling Means
    sma50 = pivoted_close.rolling(50).mean()
    vol_sma20 = pivoted_vol.rolling(20).mean()
    prev_close = pivoted_close.shift(1)

    # Signal Matrix
    cond_sma = prev_close > sma50.shift(1)
    cond_vol = pivoted_vol > 1.5 * vol_sma20.shift(1)
    cond_gap = pivoted_open > prev_close
    entries = cond_sma & cond_vol & cond_gap

    vol_surge_rank = (pivoted_vol / vol_sma20.shift(1)).where(entries)
    top_5_mask = entries & (vol_surge_rank.rank(axis=1, ascending=False, method='first') <= 5)

    dates = pivoted_close.index
    cash = INITIAL_CAPITAL
    equity_curve = []
    daily_returns = []

    for i in range(50, len(dates)):
        curr_d = dates[i]
        valid_stocks = top_5_mask.loc[curr_d]
        active_symbols = valid_stocks[valid_stocks].index.tolist()

        if active_symbols:
            n_picks = len(active_symbols)
            # 5.0x Sizing: Total Position Exposure = Cash * leverage
            # Position per stock = (Cash * leverage) / n_picks
            alloc_per_stock = (cash * leverage) / n_picks
            
            o_vals = pivoted_open.loc[curr_d, active_symbols]
            c_vals = pivoted_close.loc[curr_d, active_symbols]
            l_vals = pivoted_low.loc[curr_d, active_symbols]

            drop_pcts = (l_vals - o_vals) / o_vals
            
            # Vectorized trade return calculation with 1% Stop Loss
            returns = np.where(drop_pcts <= -0.01, -0.01 - STT_BROKERAGE_SLIPPAGE, ((c_vals - o_vals) / o_vals) - STT_BROKERAGE_SLIPPAGE)
            
            day_pnl = np.sum(alloc_per_stock * returns)
            cash += day_pnl
            daily_returns.append(day_pnl / (cash - day_pnl))
        else:
            daily_returns.append(0.0)

        equity_curve.append({'date': curr_d, 'value': cash})

    eq_df = pd.DataFrame(equity_curve)
    final_val = eq_df['value'].iloc[-1]
    years = (dates[-1] - dates[50]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0 if final_val > 0 else -100.0

    eq_df['peak'] = eq_df['value'].cummax()
    eq_df['drawdown'] = (eq_df['value'] - eq_df['peak']) / eq_df['peak']
    max_dd = eq_df['drawdown'].min() * 100.0

    absolute_profit = final_val - INITIAL_CAPITAL
    absolute_return_pct = (absolute_profit / INITIAL_CAPITAL) * 100.0

    daily_ret_s = pd.Series(daily_returns)
    sharpe = (daily_ret_s.mean() / daily_ret_s.std()) * np.sqrt(252) if daily_ret_s.std() > 0 else 0.0
    
    downside_std = daily_ret_s[daily_ret_s < 0].std()
    sortino = (daily_ret_s.mean() / downside_std) * np.sqrt(252) if downside_std > 0 else 0.0

    print("=" * 95)
    print("      VECTORIZED NUMPY/PANDAS 5X LEVERAGE INTRADAY BACKTEST RESULTS      ")
    print("=" * 95)
    print(f"💰 Starting Capital Base:        ₹1,00,000.00 (1 Lakh)")
    print(f"💵 Absolute Profit Earned:        ₹{absolute_profit:,.2f}")
    print(f"📈 Total Absolute Return:        +{absolute_return_pct:,.2f}%")
    print(f"🚀 Compound CAGR (5 Years):      +{cagr:.2f}% per year")
    print(f"🔻 Max Peak-to-Trough Drawdown:  {max_dd:.2f}%")
    print(f"📊 Portfolio Sharpe Ratio:       {sharpe:.2f}")
    print(f"🎯 Portfolio Sortino Ratio:      {sortino:.2f}")
    print(f"⚡ Execution Leverage Sizing:    5.0x SEBI Intraday MIS Exposure")

if __name__ == "__main__":
    run_pure_vectorized_sim(leverage=5.0)
