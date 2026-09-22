import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0 # ₹1 Lakh
STT_BROKERAGE = 0.0015 # 0.15% round-trip fees

def load_liquid_stocks():
    conn = sqlite3.connect(DB_PATH)
    # Fetch top liquid 200 NSE stocks
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
    conn.close()
    df['date'] = pd.to_datetime(df['date'])
    return df, stocks

def run_pure_daily_positional_backtest():
    print("=" * 95)
    print("      PURE DAILY DATA POSITIONAL SWING STRATEGY AUDIT (2021 - 2026)      ")
    print("      Zero Intraday Assumptions | 100% EOD Daily Execution      ")
    print("=" * 95)

    df, stocks = load_liquid_stocks()

    pivoted_open = df.pivot(index='date', columns='symbol', values='open')
    pivoted_close = df.pivot(index='date', columns='symbol', values='close')
    pivoted_high = df.pivot(index='date', columns='symbol', values='high')
    pivoted_low = df.pivot(index='date', columns='symbol', values='low')

    # Indicators on Daily Close
    sma50 = pivoted_close.rolling(50).mean()
    high_52w = pivoted_high.shift(1).rolling(252).max()

    dates = pivoted_close.index
    
    # -------------------------------------------------------------------
    # STRATEGY: 52-Week High Breakout (5-Stock Concentrated, Daily EOD)
    # Entry Rule: Daily Close > 52-Week High AND Daily Close > 50 SMA
    # Execution: Buy at Daily Close (or Next Open)
    # Exit Rule: Exit when Daily Close < 50 SMA (or Stop Loss -10%)
    # Position Sizing: 20% Capital per Stock (5 Stocks Max)
    # -------------------------------------------------------------------

    cash = INITIAL_CAPITAL
    portfolio_history = []
    active_positions = {} # symbol -> {entry_price, entry_date, shares}

    for i in range(252, len(dates)):
        curr_d = dates[i]
        curr_d_str = curr_d.strftime('%Y-%m-%d')
        
        c_row = pivoted_close.loc[curr_d]
        sma_row = sma50.loc[curr_d]
        h52_row = high_52w.loc[curr_d]

        # 1. Manage Exits first
        symbols_to_exit = []
        for sym, pos in list(active_positions.items()):
            curr_price = c_row[sym]
            sma_val = sma_row[sym]
            entry_p = pos['entry_price']

            ret_pct = (curr_price - entry_p) / entry_p

            # Exit Condition: Price drops below 50 SMA or Stop Loss -10%
            if curr_price < sma_val or ret_pct <= -0.10:
                symbols_to_exit.append(sym)

        for sym in symbols_to_exit:
            pos = active_positions.pop(sym)
            curr_price = c_row[sym]
            proceeds = pos['shares'] * curr_price * (1.0 - STT_BROKERAGE)
            cash += proceeds

        # 2. Check Entries for Available Portfolio Slots (Max 5 Stocks)
        slots_available = 5 - len(active_positions)

        if slots_available > 0:
            candidates = []
            for s in stocks:
                if s not in active_positions:
                    cp = c_row[s]
                    h52 = h52_row[s]
                    sma_v = sma_row[s]

                    if pd.notna(cp) and pd.notna(h52) and pd.notna(sma_v):
                        if cp > h52 and cp > sma_v:
                            candidates.append(s)

            if candidates:
                # Rank candidates by 12-month return
                selected = candidates[:slots_available]
                # Portfolio value
                total_portfolio_val = cash + sum([pos['shares'] * c_row[sym] for sym, pos in active_positions.items()])
                target_alloc = (total_portfolio_val * 0.20) # 20% per stock

                for s in selected:
                    buy_price = c_row[s] * (1.0 + STT_BROKERAGE)
                    alloc = min(cash, target_alloc)
                    if alloc > 1000:
                        shares = alloc / buy_price
                        cash -= alloc
                        active_positions[s] = {
                            "entry_price": buy_price,
                            "entry_date": curr_d_str,
                            "shares": shares
                        }

        # Calculate Total End-of-Day Equity Value
        equity_val = cash + sum([pos['shares'] * c_row[sym] for sym, pos in active_positions.items() if pd.notna(c_row[sym])])
        portfolio_history.append({'date': curr_d, 'value': equity_val})

    res_df = pd.DataFrame(portfolio_history)
    final_val = res_df['value'].iloc[-1]
    years = (dates[-1] - dates[252]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0

    res_df['peak'] = res_df['value'].cummax()
    max_dd = ((res_df['value'] - res_df['peak']) / res_df['peak'] * 100.0).min()

    print(f"Start Date:                    {dates[252].strftime('%Y-%m-%d')}")
    print(f"End Date:                      {dates[-1].strftime('%Y-%m-%d')}")
    print(f"Evaluation Period:             {years:.2f} Years")
    print(f"Initial Capital Base:          ₹{INITIAL_CAPITAL:,.2f} (1 Lakh)")
    print(f"Final Portfolio Value:         ₹{final_val:,.2f}")
    print(f"Total Net Profit Earned:       ₹{final_val - INITIAL_CAPITAL:,.2f}")
    print(f"Total Absolute Return (%):     +{((final_val - INITIAL_CAPITAL)/INITIAL_CAPITAL)*100:.2f}%")
    print(f"Compound Annual Growth (CAGR): +{cagr:.2f}% p.a.")
    print(f"Max Drawdown (Peak Loss):      {max_dd:.2f}%")

if __name__ == "__main__":
    run_pure_daily_positional_backtest()
