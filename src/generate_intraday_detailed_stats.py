import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"

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

def generate_stats():
    df, fno_symbols = load_fno_data()

    pivoted_open = df.pivot(index='date', columns='symbol', values='open')
    pivoted_close = df.pivot(index='date', columns='symbol', values='close')
    pivoted_low = df.pivot(index='date', columns='symbol', values='low')
    pivoted_vol = df.pivot(index='date', columns='symbol', values='volume')
    pivoted_sma50 = pivoted_close.rolling(50).mean()
    pivoted_volsma = pivoted_vol.rolling(20).mean()

    dates = pivoted_close.index
    total_trading_days = len(dates) - 50

    active_days = 0
    no_stock_days = 0
    
    stock_count_distribution = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    daily_returns = []
    trade_returns = []

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

        num_picks = min(5, len(candidates))
        stock_count_distribution[num_picks] += 1

        if num_picks > 0:
            active_days += 1
            top_picks = candidates[:num_picks]
            day_pnl_pct = 0.0
            for s in top_picks:
                drop_pct = (l_row[s] - o_row[s]) / o_row[s]
                if drop_pct <= -0.01:
                    ret = -0.01 - 0.0015
                else:
                    ret = ((c_row[s] - o_row[s]) / o_row[s]) - 0.0015
                trade_returns.append(ret * 100.0)
                day_pnl_pct += ret
            daily_returns.append(day_pnl_pct / num_picks)
        else:
            no_stock_days += 1
            daily_returns.append(0.0)

    # Streak Calculations
    win_streaks = []
    loss_streaks = []
    curr_win = 0
    curr_loss = 0

    for r in daily_returns:
        if r > 0:
            curr_win += 1
            if curr_loss > 0:
                loss_streaks.append(curr_loss)
                curr_loss = 0
        elif r < 0:
            curr_loss += 1
            if curr_win > 0:
                win_streaks.append(curr_win)
                curr_win = 0

    if curr_win > 0: win_streaks.append(curr_win)
    if curr_loss > 0: loss_streaks.append(curr_loss)

    max_win_streak = max(win_streaks) if win_streaks else 0
    max_loss_streak = max(loss_streaks) if loss_streaks else 0

    winning_trades = [t for t in trade_returns if t > 0]
    losing_trades = [t for t in trade_returns if t < 0]

    avg_win_pct = np.mean(winning_trades) if winning_trades else 0.0
    avg_loss_pct = np.mean(losing_trades) if losing_trades else 0.0
    profit_factor = abs(sum(winning_trades) / sum(losing_trades)) if losing_trades else 0.0

    print("=" * 95)
    print("      INTRADAY VOLUME BREAKOUT STRATEGY: DETAILED DAY & TRADE STATISTICS      ")
    print("=" * 95)

    print(f"\n📅 TOTAL TRADING DAYS EVALUATED: {total_trading_days} Days (2021 – 2026)")
    print(f"✅ Active Trading Days (≥1 Stock Signal): {active_days} Days ({active_days/total_trading_days*100:.1f}%)")
    print(f"💤 No-Trade Cash Days (0 Signals):       {no_stock_days} Days ({no_stock_days/total_trading_days*100:.1f}%)")

    print("\n📊 DAILY STOCK PICKS DISTRIBUTION:")
    for count in range(6):
        d_cnt = stock_count_distribution[count]
        pct = (d_cnt / total_trading_days) * 100.0
        label = "Full 5 Picks" if count == 5 else f"{count} Stock(s)"
        print(f"   - Days with {label}: {d_cnt} Days ({pct:.1f}%)")

    print("\n🔥 PERFORMANCE & STREAK METRICS:")
    print(f"   - Total Trades Executed: {len(trade_returns)} Trades")
    print(f"   - Winning Trades: {len(winning_trades)} ({len(winning_trades)/len(trade_returns)*100:.2f}%)")
    print(f"   - Losing Trades:  {len(losing_trades)} ({len(losing_trades)/len(trade_returns)*100:.2f}%)")
    print(f"   - Average Winning Trade Return: +{avg_win_pct:.2f}%")
    print(f"   - Average Losing Trade Return:  {avg_loss_pct:.2f}%")
    print(f"   - Profit Factor: {profit_factor:.2f}")
    print(f"   - Longest Winning Day Streak: {max_win_streak} Consecutive Days")
    print(f"   - Longest Losing Day Streak:  {max_loss_streak} Consecutive Days")

if __name__ == "__main__":
    generate_stats()
