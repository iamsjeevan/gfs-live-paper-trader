import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"

def audit_database_quality():
    print("=" * 90)
    print("      STEP 1: DATABASE DATA QUALITY & OUTLIER AUDIT      ")
    print("=" * 90)

    conn = sqlite3.connect(DB_PATH)
    
    # Check for extreme price jumps (single-day returns > 50% or < -50%)
    df = pd.read_sql_query("""
    SELECT symbol, date, open, high, low, close, volume,
           ((close - open) / open * 100.0) as intraday_ret,
           ((close - LAG(close) OVER (PARTITION BY symbol ORDER BY date)) / LAG(close) OVER (PARTITION BY symbol ORDER BY date) * 100.0) as daily_ret
    FROM daily_prices
    WHERE date >= '2021-01-01'
    """, conn)
    conn.close()

    outliers_high = df[df['intraday_ret'] > 30.0]
    outliers_low = df[df['intraday_ret'] < -30.0]

    print(f"Total Daily Stock Rows: {len(df):,}")
    print(f"⚠️ Extreme Intraday Outliers (> +30% move): {len(outliers_high)} rows")
    print(f"⚠️ Extreme Intraday Outliers (< -30% move): {len(outliers_low)} rows")

    if len(outliers_high) > 0:
        print("\nTop 5 Extreme Positive Intraday Outliers:")
        print(outliers_high[['symbol', 'date', 'open', 'close', 'intraday_ret']].head(5).to_string())

def audit_strategy_execution_clean():
    print("\n" + "=" * 90)
    print("      STEP 2: REALISTIC FIXED CAPITAL (NON-COMPOUNDED) BACKTEST AUDIT      ")
    print("=" * 90)

    conn = sqlite3.connect(DB_PATH)
    fno_symbols = pd.read_sql_query("""
    SELECT symbol, AVG(close * volume) as turnover
    FROM daily_prices WHERE date >= '2021-01-01'
    GROUP BY symbol HAVING turnover > 100000000
    ORDER BY turnover DESC LIMIT 150
    """, conn)['symbol'].tolist()

    df = pd.read_sql_query(f"""
    SELECT symbol, date, open, high, low, close, volume
    FROM daily_prices
    WHERE symbol IN ({','.join(['?']*len(fno_symbols))}) AND date >= '2021-01-01'
    ORDER BY date ASC
    """, conn, params=fno_symbols)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])

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
    
    # -------------------------------------------------------------
    # REALISTIC POSITION SIZING MODEL:
    # Initial Capital: ₹1,00,000 (1 Lakh)
    # Trade Allocation: Fixed ₹20,000 cash per stock (1.0x Cash)
    # or Fixed ₹1,00,000 exposure per stock (5.0x MIS Leverage)
    # NO REINVESTMENT OF MULTI-MILLION COMPOUNDING TO PREVENT FAKE NUMBERS
    # -------------------------------------------------------------

    cash_1x = 100000.0
    cash_5x_mis = 100000.0
    stt_fee = 0.0015 # 0.15% round-trip tax/brokerage/slippage

    history_1x = []
    history_5x = []

    trade_logs = []

    for i in range(50, len(dates)):
        curr_d = dates[i]
        valid_stocks = top_5_mask.loc[curr_d]
        active_symbols = valid_stocks[valid_stocks].index.tolist()

        if active_symbols:
            n_picks = len(active_symbols)
            
            o_vals = pivoted_open.loc[curr_d, active_symbols]
            c_vals = pivoted_close.loc[curr_d, active_symbols]
            l_vals = pivoted_low.loc[curr_d, active_symbols]

            drop_pcts = (l_vals - o_vals) / o_vals
            
            # 1% Stop Loss Exit
            trade_rets = np.where(drop_pcts <= -0.01, -0.01 - stt_fee, ((c_vals - o_vals) / o_vals) - stt_fee)

            for idx, sym in enumerate(active_symbols):
                trade_logs.append({
                    "date": curr_d.strftime("%Y-%m-%d"),
                    "symbol": sym,
                    "open": round(o_vals[sym], 2),
                    "close": round(c_vals[sym], 2),
                    "return_pct": round(trade_rets[idx] * 100.0, 2)
                })

            # 1x Cash Mode: ₹20,000 per pick
            pnl_1x = np.sum(20000.0 * trade_rets)
            cash_1x += pnl_1x

            # 5x MIS Mode: ₹1,00,000 position exposure per pick (5x leverage on ₹1L cash)
            pnl_5x = np.sum(100000.0 * trade_rets)
            cash_5x_mis += pnl_5x

        history_1x.append(cash_1x)
        history_5x.append(cash_5x_mis)

    print(f"\n📊 REALISTIC UNCOMPOUNDED (FIXED RUPEE SIZING) 5-YEAR RESULTS (2021 – 2026):")
    print(f"Total Trading Days: {len(dates)-50} Days")
    print(f"Total Individual Trades Executed: {len(trade_logs)} Trades")
    
    print(f"\n1. 1.0x CASH MARGIN (Fixed ₹20,000 per stock pick):")
    print(f"   - Initial Capital: ₹1,00,000.00")
    print(f"   - Final Value:     ₹{cash_1x:,.2f}")
    print(f"   - Total Profit:    ₹{cash_1x - 100000.0:,.2f} (+{((cash_1x - 100000)/100000)*100:.2f}%)")

    print(f"\n2. 5.0x SEBI MIS LEVERAGE (Fixed ₹1,00,000 position size per stock pick):")
    print(f"   - Initial Capital: ₹1,00,000.00")
    print(f"   - Final Value:     ₹{cash_5x_mis:,.2f}")
    print(f"   - Total Profit:    ₹{cash_5x_mis - 100000.0:,.2f} (+{((cash_5x_mis - 100000)/100000)*100:.2f}%)")

    trade_df = pd.DataFrame(trade_logs)
    print("\nSAMPLE RECENT 10 TRADES LOG:")
    print(trade_df.tail(10).to_string())

if __name__ == "__main__":
    audit_database_quality()
    audit_strategy_execution_clean()
