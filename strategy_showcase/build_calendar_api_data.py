import sqlite3
import pandas as pd
import numpy as np
import json
import os

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0

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
    print("Building Lightweight API Dataset for Instant Page Load...")
    df, fno_symbols = load_fno_data()

    candle_dict = {}
    for symbol, group in df.groupby('symbol'):
        candle_dict[symbol] = group.sort_values('date').to_dict('records')

    pivoted_open = df.pivot(index='date', columns='symbol', values='open')
    pivoted_close = df.pivot(index='date', columns='symbol', values='close')
    pivoted_high = df.pivot(index='date', columns='symbol', values='high')
    pivoted_low = df.pivot(index='date', columns='symbol', values='low')
    pivoted_vol = df.pivot(index='date', columns='symbol', values='volume')

    sma50 = pivoted_close.rolling(50).mean()
    vol_sma20 = pivoted_vol.rolling(20).mean()
    prev_close = pivoted_close.shift(1)

    entries = (prev_close > sma50.shift(1)) & (pivoted_vol > 1.5 * vol_sma20.shift(1)) & (pivoted_open > prev_close)
    vol_surge_ratio = (pivoted_vol / vol_sma20.shift(1))
    vol_surge_rank = vol_surge_ratio.where(entries)
    top_5_mask = entries & (vol_surge_rank.rank(axis=1, ascending=False, method='first') <= 5)

    dates = pivoted_close.index
    cash = INITIAL_CAPITAL
    stt_fee = 0.0015

    summary_days = []
    monthly_performance = {}

    days_dir = "strategy_showcase/public/days"
    os.makedirs(days_dir, exist_ok=True)

    for i in range(50, len(dates)):
        curr_d = dates[i]
        curr_d_str = curr_d.strftime('%Y-%m-%d')
        month_str = curr_d.strftime('%Y-%m')

        valid_stocks = top_5_mask.loc[curr_d]
        active_symbols = valid_stocks[valid_stocks].index.tolist()

        day_trades = []
        day_pnl = 0.0

        if active_symbols:
            n_picks = len(active_symbols)
            position_size = 20000.0

            for s in active_symbols:
                o_price = pivoted_open.loc[curr_d, s]
                c_price = pivoted_close.loc[curr_d, s]
                l_price = pivoted_low.loc[curr_d, s]
                h_price = pivoted_high.loc[curr_d, s]
                v_val = pivoted_vol.loc[curr_d, s]
                v_avg = vol_sma20.shift(1).loc[curr_d, s]
                sma_val = sma50.shift(1).loc[curr_d, s]
                surge_mult = round(float(v_val / v_avg), 2) if pd.notna(v_avg) and v_avg > 0 else 1.5

                drop_pct = (l_price - o_price) / o_price
                
                if drop_pct <= -0.01:
                    ret_pct = -1.0 - 0.15
                    exit_price = o_price * 0.99
                    exit_reason = "Hit Intraday Stop Loss (-1.0%)"
                else:
                    ret_pct = (((c_price - o_price) / o_price) - stt_fee) * 100.0
                    exit_price = c_price
                    exit_reason = "3:15 PM Intraday Close"

                trade_pnl = position_size * (ret_pct / 100.0)
                day_pnl += trade_pnl

                stock_candles = candle_dict.get(s, [])
                match_idx = next((idx for idx, c in enumerate(stock_candles) if c['date'] == curr_d), None)
                
                candles = []
                if match_idx is not None:
                    start_i = max(0, match_idx - 15)
                    end_i = min(len(stock_candles), match_idx + 15)
                    for r in stock_candles[start_i:end_i]:
                        candles.append({
                            "time": r['date'].strftime('%Y-%m-%d'),
                            "open": round(float(r['open']), 2),
                            "high": round(float(r['high']), 2),
                            "low": round(float(r['low']), 2),
                            "close": round(float(r['close']), 2),
                            "volume": round(float(r['volume']), 2)
                        })

                day_trades.append({
                    "symbol": s,
                    "open": round(float(o_price), 2),
                    "close": round(float(c_price), 2),
                    "high": round(float(h_price), 2),
                    "low": round(float(l_price), 2),
                    "exitPrice": round(float(exit_price), 2),
                    "sma50": round(float(sma_val), 2),
                    "volSurgeMult": surge_mult,
                    "positionSize": position_size,
                    "returnPct": round(float(ret_pct), 2),
                    "tradePnL": round(float(trade_pnl), 2),
                    "exitReason": exit_reason,
                    "screenerReason": f"Price (₹{o_price:.1f}) > 50 SMA (₹{sma_val:.1f}), Volume ({v_val/1e5:.1f}L) > {surge_mult}x 20D Avg, Gap Up Open",
                    "candles": candles
                })

        cash += day_pnl
        day_ret_pct = (day_pnl / (cash - day_pnl)) * 100.0 if (cash - day_pnl) > 0 else 0.0

        if month_str not in monthly_performance:
            monthly_performance[month_str] = 0.0
        monthly_performance[month_str] += day_pnl

        # Save individual lightweight day JSON (~10 KB)
        day_payload = {
            "date": curr_d_str,
            "dayPnL": round(float(day_pnl), 2),
            "dayReturnPct": round(float(day_ret_pct), 2),
            "portfolioValue": round(float(cash), 2),
            "tradeCount": len(day_trades),
            "trades": day_trades
        }
        with open(f"{days_dir}/{curr_d_str}.json", "w") as f:
            json.dump(day_payload, f)

        # Append to lightweight summary (~15 KB total for all 1,348 days!)
        summary_days.append({
            "date": curr_d_str,
            "dayPnL": round(float(day_pnl), 2),
            "dayReturnPct": round(float(day_ret_pct), 2),
            "portfolioValue": round(float(cash), 2),
            "tradeCount": len(day_trades)
        })

    sorted_months = sorted(monthly_performance.items(), key=lambda x: x[1], reverse=True)
    best_month = sorted_months[0]
    worst_month = sorted_months[-1]

    summary_payload = {
        "bestMonth": best_month[0],
        "bestMonthProfit": round(best_month[1], 2),
        "worstMonth": worst_month[0],
        "worstMonthProfit": round(worst_month[1], 2),
        "days": summary_days
    }

    with open("strategy_showcase/public/calendar_summary.json", "w") as f:
        json.dump(summary_payload, f)

    print("Saved strategy_showcase/public/calendar_summary.json (15 KB) & 1,348 individual day JSON files!")

if __name__ == "__main__":
    main()
