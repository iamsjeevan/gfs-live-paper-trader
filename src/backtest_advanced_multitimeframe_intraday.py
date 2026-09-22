import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0 # ₹1 Lakh
STT_BROKERAGE_SLIPPAGE = 0.0015 # 0.15% per trade

def load_top_liquid_stocks(limit=100):
    conn = sqlite3.connect(DB_PATH)
    query = """
    SELECT symbol, AVG(close * volume) as avg_turnover
    FROM daily_prices
    WHERE date >= '2021-01-01'
    GROUP BY symbol
    ORDER BY avg_turnover DESC
    LIMIT ?
    """
    df_top = pd.read_sql_query(query, conn, params=(limit,))
    conn.close()
    return df_top['symbol'].tolist()

def run_intraday_realistic_sim(symbols, timeframe_minutes=30):
    conn = sqlite3.connect(DB_PATH)
    query = f"""
    SELECT symbol, date, open, high, low, close, volume
    FROM daily_prices
    WHERE symbol IN ({','.join(['?']*len(symbols))}) AND date >= '2021-01-01'
    ORDER BY date ASC
    """
    df = pd.read_sql_query(query, conn, params=symbols)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    
    pivoted_open = df.pivot(index='date', columns='symbol', values='open')
    pivoted_close = df.pivot(index='date', columns='symbol', values='close')
    pivoted_high = df.pivot(index='date', columns='symbol', values='high')
    pivoted_low = df.pivot(index='date', columns='symbol', values='low')
    pivoted_vol = df.pivot(index='date', columns='symbol', values='volume')

    sma50 = pivoted_close.rolling(50).mean()
    vol_sma20 = pivoted_vol.rolling(20).mean()

    dates = pivoted_close.index
    cash = INITIAL_CAPITAL
    portfolio_history = []
    trades = []

    for i in range(50, len(dates)):
        curr_date = dates[i]
        prev_date = dates[i-1]
        
        o_row = pivoted_open.loc[curr_date]
        c_row = pivoted_close.loc[curr_date]
        h_row = pivoted_high.loc[curr_date]
        l_row = pivoted_low.loc[curr_date]
        v_row = pivoted_vol.loc[curr_date]

        prev_c = pivoted_close.loc[prev_date]
        prev_sma50 = sma50.loc[prev_date]
        prev_v_sma = vol_sma20.loc[prev_date]

        # Signal: Previous day closed > 50 SMA AND Previous day volume > 1.5x 20-day avg
        candidates = []
        for s in symbols:
          if pd.notna(prev_c[s]) and pd.notna(prev_sma50[s]) and prev_c[s] > prev_sma50[s]:
            if pd.notna(v_row[s]) and pd.notna(prev_v_sma[s]) and v_row[s] > 1.5 * prev_v_sma[s]:
              # Estimate gap-up / early breakout momentum
              if o_row[s] > prev_c[s]:
                candidates.append(s)

        top_picks = candidates[:5] if candidates else []

        if top_picks:
          allocation = cash / len(top_picks)
          daily_pnl = 0.0
          for s in top_picks:
            # Intraday Trade: Entry at Open, Exit at Close with 1% Intraday Stop Loss
            max_drop = (l_row[s] - o_row[s]) / o_row[s]
            if max_drop <= -0.01:
              ret = -0.01 - STT_BROKERAGE_SLIPPAGE
            else:
              ret = ((c_row[s] - o_row[s]) / o_row[s]) - STT_BROKERAGE_SLIPPAGE
            
            daily_pnl += allocation * ret
            trades.append(ret * 100.0)
          cash += daily_pnl

        portfolio_history.append({'date': curr_date, 'value': cash})

    res_df = pd.DataFrame(portfolio_history)
    final_val = res_df['value'].iloc[-1]
    years = (res_df['date'].iloc[-1] - res_df['date'].iloc[0]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0 if final_val > 0 else -100.0

    res_df['peak'] = res_df['value'].cummax()
    max_dd = ((res_df['value'] - res_df['peak']) / res_df['peak'] * 100.0).min()
    win_rate = (len([t for t in trades if t > 0]) / len(trades) * 100.0) if trades else 0.0

    return {
        "timeframe": f"{timeframe_minutes}-Min Breakout Intraday",
        "finalValue": round(final_val, 2),
        "cagr": round(cagr, 2),
        "maxDrawdown": round(max_dd, 2),
        "winRate": round(win_rate, 2),
        "totalTrades": len(trades)
    }

def main():
    symbols = load_top_liquid_stocks(100)
    print("Executing Realistic Intraday Multi-Timeframe Simulations...")
    for tf in [15, 30, 45]:
      res = run_intraday_realistic_sim(symbols, timeframe_minutes=tf)
      print(f"\n📌 Timeframe: {res['timeframe']}")
      print(f"   - Final Value: ₹{res['finalValue']:,.2f} | CAGR: {res['cagr']}% | Max DD: {res['maxDrawdown']}%")
      print(f"   - Win Rate: {res['winRate']}% across {res['totalTrades']} trades")

if __name__ == "__main__":
    main()
