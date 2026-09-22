import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0 # ₹1 Lakh
STT_BROKERAGE_SLIPPAGE = 0.0015 # 0.15% round-trip

def load_fno_universe():
    conn = sqlite3.connect(DB_PATH)
    # Fetch top 150 liquid F&O stocks by turnover
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

def run_intraday_leverage_sim(leverage=1.0):
    df, fno_symbols = load_fno_universe()

    pivoted_open = df.pivot(index='date', columns='symbol', values='open')
    pivoted_close = df.pivot(index='date', columns='symbol', values='close')
    pivoted_low = df.pivot(index='date', columns='symbol', values='low')
    pivoted_vol = df.pivot(index='date', columns='symbol', values='volume')
    pivoted_sma50 = pivoted_close.rolling(50).mean()
    pivoted_volsma = pivoted_vol.rolling(20).mean()

    dates = pivoted_close.index
    cash = INITIAL_CAPITAL
    history = []
    trades = []

    for i in range(50, len(dates)):
        curr_d = dates[i]
        prev_d = dates[i-1]

        o_row = pivoted_open.loc[curr_d]
        c_row = pivoted_close.loc[curr_d]
        l_row = pivoted_low.loc[curr_d]
        v_row = pivoted_vol.loc[curr_d]
        prev_c = pivoted_close.loc[prev_d]
        sma_row = pivoted_sma50.loc[prev_d]
        v_sma = pivoted_volsma.loc[prev_d]

        candidates = []
        for s in fno_symbols:
            if pd.notna(prev_c[s]) and pd.notna(sma_row[s]) and prev_c[s] > sma_row[s]:
                if pd.notna(v_row[s]) and pd.notna(v_sma[s]) and v_row[s] > 1.5 * v_sma[s]:
                    if o_row[s] > prev_c[s]:
                        candidates.append(s)

        top_picks = candidates[:5] if candidates else []

        if top_picks:
            # Total Position Value = cash * leverage
            total_exposure = cash * leverage
            alloc_per_stock = total_exposure / len(top_picks)
            daily_pnl = 0.0

            for s in top_picks:
                drop_pct = (l_row[s] - o_row[s]) / o_row[s]
                # 1% Intraday Stop Loss
                if drop_pct <= -0.01:
                    ret = -0.01 - STT_BROKERAGE_SLIPPAGE
                else:
                    ret = ((c_row[s] - o_row[s]) / o_row[s]) - STT_BROKERAGE_SLIPPAGE

                daily_pnl += alloc_per_stock * ret
                trades.append(ret * 100.0)

            cash += daily_pnl

        history.append({'date': curr_d, 'value': cash})

    res_df = pd.DataFrame(history)
    final_val = res_df['value'].iloc[-1]
    years = (dates[-1] - dates[50]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0 if final_val > 0 else -100.0
    res_df['peak'] = res_df['value'].cummax()
    max_dd = ((res_df['value'] - res_df['peak']) / res_df['peak'] * 100.0).min()
    win_rate = (len([t for t in trades if t > 0]) / len(trades) * 100.0) if trades else 0.0

    return {
        "leverage": f"{leverage}x Leverage",
        "finalVal": round(final_val, 2),
        "cagr": round(cagr, 2),
        "maxDD": round(max_dd, 2),
        "winRate": round(win_rate, 2),
        "totalTrades": len(trades)
    }

def main():
    print("=" * 95)
    print("      INTRADAY LEVERAGE COMPARISON: 1.0x (NO LEVERAGE) vs 5.0x (SEBI MIS LEVERAGE)      ")
    print("=" * 95)

    r1 = run_intraday_leverage_sim(leverage=1.0)
    r5 = run_intraday_leverage_sim(leverage=5.0)

    for r in [r1, r5]:
        print(f"\n📌 Sizing Mode: {r['leverage']}")
        print(f"   - Final Value (₹1 Lakh Start): ₹{r['finalVal']:,.2f}")
        print(f"   - Compound CAGR: {r['cagr']}%")
        print(f"   - Max Drawdown: {r['maxDD']}%")
        print(f"   - Win Rate: {r['winRate']}% ({r['totalTrades']} Trades)")

if __name__ == "__main__":
    main()
