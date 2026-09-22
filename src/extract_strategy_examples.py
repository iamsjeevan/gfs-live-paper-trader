import sqlite3
import pandas as pd
import numpy as np
import json
import os

DB_PATH = "data/nse_stocks_all_years.db"

def load_stock_daily(symbol):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT date, open, high, low, close, volume FROM daily_prices WHERE symbol = ? AND date >= '2021-01-01' ORDER BY date ASC", conn, params=(symbol,))
    conn.close()
    df['date'] = pd.to_datetime(df['date'])
    return df

def find_52w_high_examples():
    conn = sqlite3.connect(DB_PATH)
    # Fetch top liquid stocks
    top_stocks = pd.read_sql_query("""
    SELECT symbol, AVG(close * volume) as turnover
    FROM daily_prices WHERE date >= '2021-01-01'
    GROUP BY symbol HAVING turnover > 50000000
    ORDER BY turnover DESC LIMIT 200
    """, conn)['symbol'].tolist()
    conn.close()

    trades = []
    
    for s in top_stocks:
        df = load_stock_daily(s)
        if len(df) < 260:
            continue

        df['sma50'] = df['close'].rolling(50).mean()
        df['high_52w'] = df['high'].shift(1).rolling(252).max()

        in_trade = False
        entry_date = None
        entry_price = 0.0
        hold_days = 0

        for i in range(252, len(df)):
            row = df.iloc[i]
            d_str = row['date'].strftime('%Y-%m-%d')
            close_p = row['close']

            if in_trade:
                hold_days += 1
                ret_pct = ((close_p - entry_price) / entry_price) * 100.0

                # Exit when price drops below 50 SMA or 60 days max hold
                if close_p < row['sma50'] or hold_days >= 60 or ret_pct <= -10.0:
                    exit_reason = "50 SMA Break" if close_p < row['sma50'] else ("Max 60D Hold" if hold_days >= 60 else "Stop Loss (-10%)")
                    trades.append({
                        "strategy": "52W_HIGH",
                        "symbol": s,
                        "entryDate": entry_date,
                        "exitDate": d_str,
                        "entryPrice": round(entry_price, 2),
                        "exitPrice": round(close_p, 2),
                        "returnPct": round(ret_pct, 2),
                        "holdDays": hold_days,
                        "exitReason": exit_reason
                    })
                    in_trade = False
            else:
                # Entry: Price > 50 SMA and Price > 52-Week High
                if pd.notna(row['high_52w']) and pd.notna(row['sma50']) and close_p > row['high_52w'] and close_p > row['sma50']:
                    entry_price = close_p
                    entry_date = d_str
                    hold_days = 0
                    in_trade = True

    trades_df = pd.DataFrame(trades)
    winners = trades_df[trades_df['returnPct'] > 15.0].sort_values(by='returnPct', ascending=False).head(5).to_dict('records')
    losers = trades_df[trades_df['returnPct'] < -5.0].sort_values(by='returnPct', ascending=True).head(5).to_dict('records')

    return winners, losers

def find_intraday_volume_examples():
    conn = sqlite3.connect(DB_PATH)
    top_stocks = pd.read_sql_query("""
    SELECT symbol, AVG(close * volume) as turnover
    FROM daily_prices WHERE date >= '2023-01-01'
    GROUP BY symbol HAVING turnover > 100000000
    ORDER BY turnover DESC LIMIT 150
    """, conn)['symbol'].tolist()
    conn.close()

    trades = []

    for s in top_stocks[:50]:
        df = load_stock_daily(s)
        if len(df) < 50:
            continue

        df['sma50'] = df['close'].rolling(50).mean()
        df['vol_sma20'] = df['volume'].rolling(20).mean()

        for i in range(50, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i-1]
            d_str = row['date'].strftime('%Y-%m-%d')

            # Intraday Signal: Price > 50 SMA AND Volume > 2.0x 20-day avg AND Open > Prev Close
            if row['close'] > row['sma50'] and row['volume'] > 2.0 * prev_row['vol_sma20'] and row['open'] > prev_row['close']:
                entry_price = row['open']
                # Intraday Exit at Close with 1.5% Stop Loss
                low_drop = (row['low'] - entry_price) / entry_price
                if low_drop <= -0.015:
                    exit_price = entry_price * 0.985
                    ret_pct = -1.5
                    exit_reason = "Intraday Stop Loss (-1.5%)"
                else:
                    exit_price = row['close']
                    ret_pct = ((exit_price - entry_price) / entry_price) * 100.0
                    exit_reason = "3:15 PM Intraday Close"

                trades.append({
                    "strategy": "INTRADAY_VOL",
                    "symbol": s,
                    "entryDate": d_str,
                    "exitDate": d_str,
                    "entryPrice": round(entry_price, 2),
                    "exitPrice": round(exit_price, 2),
                    "returnPct": round(ret_pct, 2),
                    "holdDays": 1,
                    "exitReason": exit_reason
                })

    trades_df = pd.DataFrame(trades)
    winners = trades_df[trades_df['returnPct'] > 2.5].sort_values(by='returnPct', ascending=False).head(5).to_dict('records')
    losers = trades_df[trades_df['returnPct'] <= -1.5].sort_values(by='returnPct', ascending=True).head(5).to_dict('records')

    return winners, losers

def extract_candle_window(symbol, start_date_str, end_date_str, padding_days=30):
    df = load_stock_daily(symbol)
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    
    idx_list = df[df['date_str'] == start_date_str].index
    if len(idx_list) == 0:
        return []
    start_idx = max(0, idx_list[0] - padding_days)
    
    end_idx_list = df[df['date_str'] == end_date_str].index
    end_idx = min(len(df) - 1, (end_idx_list[0] + padding_days) if len(end_idx_list) > 0 else (start_idx + padding_days + 30))
    
    sub_df = df.iloc[start_idx:end_idx+1]
    
    candles = []
    for _, row in sub_df.iterrows():
        candles.append({
            "time": row['date_str'],
            "open": round(float(row['open']), 2),
            "high": round(float(row['high']), 2),
            "low": round(float(row['low']), 2),
            "close": round(float(row['close']), 2),
            "volume": round(float(row['volume']), 2)
        })
    return candles

def main():
    print("Extracting Winner and Loser Trade Examples...")
    w_52w, l_52w = find_52w_high_examples()
    w_intra, l_intra = find_intraday_volume_examples()

    all_examples = []

    print(f"Found {len(w_52w)} 52W High Winners, {len(l_52w)} 52W High Losers")
    print(f"Found {len(w_intra)} Intraday Winners, {len(l_intra)} Intraday Losers")

    # Combine into structured dataset
    for t in w_52w:
        t['tag'] = 'WINNER'
        t['candles'] = extract_candle_window(t['symbol'], t['entryDate'], t['exitDate'])
        all_examples.append(t)
    for t in l_52w:
        t['tag'] = 'LOSER'
        t['candles'] = extract_candle_window(t['symbol'], t['entryDate'], t['exitDate'])
        all_examples.append(t)

    for t in w_intra:
        t['tag'] = 'WINNER'
        t['candles'] = extract_candle_window(t['symbol'], t['entryDate'], t['exitDate'], padding_days=15)
        all_examples.append(t)
    for t in l_intra:
        t['tag'] = 'LOSER'
        t['candles'] = extract_candle_window(t['symbol'], t['entryDate'], t['exitDate'], padding_days=15)
        all_examples.append(t)

    os.makedirs("strategy_showcase/public", exist_ok=True)
    with open("strategy_showcase/public/examples.json", "w") as f:
        json.dump(all_examples, f, indent=2)

    print("Saved strategy_showcase/public/examples.json successfully!")

if __name__ == "__main__":
    main()
