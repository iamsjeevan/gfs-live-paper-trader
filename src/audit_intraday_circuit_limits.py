import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0
STT_BROKERAGE = 0.0015 # 0.15% per round-trip trade

def load_data():
    conn = sqlite3.connect(DB_PATH)
    # Load all daily price records from 2021 to 2026
    df = pd.read_sql_query("""
    SELECT symbol, date, open, high, low, close, volume
    FROM daily_prices
    WHERE date >= '2021-01-01'
    ORDER BY date ASC
    """, conn)
    conn.close()
    df['date'] = pd.to_datetime(df['date'])
    return df

def audit_circuit_limits():
    print("=" * 95)
    print("      NSE CIRCUIT LIMIT & LIQUIDITY LOCK AUDIT FOR INTRADAY TRADING (2021-2026)      ")
    print("=" * 95)

    df = load_data()
    
    # Calculate daily price change %
    df['prev_close'] = df.groupby('symbol')['close'].shift(1)
    df['day_low_pct'] = (df['low'] - df['prev_close']) / df['prev_close']
    df['day_high_pct'] = (df['high'] - df['prev_close']) / df['prev_close']

    # Lower Circuit Identification: Low == Close and Day Low <= -4.9% (Non-F&O stocks lock at 5%, 10%, 20%)
    df['is_lower_circuit'] = (df['low'] == df['close']) & (df['day_low_pct'] <= -0.049)

    print(f"\n📊 Total Daily Stock Records Analyzed: {len(df):,}")
    lc_count = df['is_lower_circuit'].sum()
    print(f"⚠️ Total Lower Circuit Freeze Days Detected: {lc_count:,} instances ({lc_count/len(df)*100:.2f}% of all trading days)")

    # Test 1: Intraday Volume Breakout WITHOUT Circuit Checks (Naïve 1% Stop Loss)
    # Test 2: Intraday Volume Breakout WITH Lower Circuit Lock (If Locked at LC, cannot exit; forced overnight gap-down)
    # Test 3: Intraday Volume Breakout strictly on F&O Stocks Only (Dynamic Circuits, No Freeze Locks)

    # Top Liquid F&O Proxy Universe (Top 150 Liquid Stocks by Turnover)
    avg_turnover = df.groupby('symbol').apply(lambda x: (x['close'] * x['volume']).mean())
    fno_universe = avg_turnover.sort_values(ascending=False).head(150).index.tolist()
    non_fno_universe = avg_turnover.sort_values(ascending=False).tail(len(avg_turnover) - 150).index.tolist()

    print(f"\n📌 F&O Liquid Universe: {len(fno_universe)} stocks (Dynamic Circuits - Exchanges flex bands)")
    print(f"📌 Non-F&O Micro/Small Universe: {len(non_fno_universe)} stocks (Hard 5%/10% Circuit Freezes)")

    # Run Simulation 1: All Stocks (Naïve Intraday 1% Stop-Loss - Assumes immediate exit)
    # Run Simulation 2: All Stocks (Realistic Circuit Lock - If Lower Circuit occurs, exit at Next Day Open)
    # Run Simulation 3: F&O Stocks Only (Guaranteed Execution & Exit)

    pivoted_open = df.pivot(index='date', columns='symbol', values='open')
    pivoted_close = df.pivot(index='date', columns='symbol', values='close')
    pivoted_low = df.pivot(index='date', columns='symbol', values='low')
    pivoted_vol = df.pivot(index='date', columns='symbol', values='volume')
    pivoted_sma50 = pivoted_close.rolling(50).mean()
    pivoted_volsma = pivoted_vol.rolling(20).mean()

    dates = pivoted_close.index

    def run_sim(universe, check_circuit_lock=False):
        cash = INITIAL_CAPITAL
        history = []
        circuit_locked_trades = 0

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
            for s in universe:
                if pd.notna(prev_c[s]) and pd.notna(sma_row[s]) and prev_c[s] > sma_row[s]:
                    if pd.notna(v_row[s]) and pd.notna(v_sma[s]) and v_row[s] > 1.5 * v_sma[s]:
                        if o_row[s] > prev_c[s]:
                            candidates.append(s)

            top_picks = candidates[:5] if candidates else []

            if top_picks:
                alloc = cash / len(top_picks)
                daily_pnl = 0.0
                for s in top_picks:
                    drop_pct = (l_row[s] - o_row[s]) / o_row[s]
                    
                    if drop_pct <= -0.05 and check_circuit_lock: # Lower Circuit Freeze
                        circuit_locked_trades += 1
                        # Forced to exit at Close (or -5% circuit limit price)
                        ret = -0.05 - STT_BROKERAGE
                    elif drop_pct <= -0.01:
                        ret = -0.01 - STT_BROKERAGE
                    else:
                        ret = ((c_row[s] - o_row[s]) / o_row[s]) - STT_BROKERAGE
                    
                    daily_pnl += alloc * ret
                cash += daily_pnl

            history.append({'date': curr_d, 'value': cash})

        res_df = pd.DataFrame(history)
        final_val = res_df['value'].iloc[-1]
        years = (dates[-1] - dates[50]).days / 365.25
        cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0 if final_val > 0 else -100.0
        res_df['peak'] = res_df['value'].cummax()
        max_dd = ((res_df['value'] - res_df['peak']) / res_df['peak'] * 100.0).min()

        return round(final_val, 2), round(cagr, 2), round(max_dd, 2), circuit_locked_trades

    v1, cagr1, dd1, lc1 = run_sim(df['symbol'].unique()[:300], check_circuit_lock=False)
    v2, cagr2, dd2, lc2 = run_sim(df['symbol'].unique()[:300], check_circuit_lock=True)
    v3, cagr3, dd3, lc3 = run_sim(fno_universe, check_circuit_lock=False)

    print("\n--- INTRADAY CIRCUIT LIMIT SIMULATION RESULTS ---")
    print(f"1. Naïve All-Stock Intraday (Ignores Circuit Locks): Final ₹{v1:,.2f} | CAGR: {cagr1}% | Max DD: {dd1}%")
    print(f"2. Realistic All-Stock Intraday (With LC Locks):      Final ₹{v2:,.2f} | CAGR: {cagr2}% | Max DD: {dd2}% ({lc2} Circuit Freeze Locks)")
    print(f"3. Strict F&O Universe Only (Exchanges Flex Bands):   Final ₹{v3:,.2f} | CAGR: {cagr3}% | Max DD: {dd3}% (0 Circuit Locks)")

if __name__ == "__main__":
    audit_circuit_limits()
