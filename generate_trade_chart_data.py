import sqlite3
import pandas as pd
import numpy as np
import json
import os

DB_PATH = "data/crypto_prices.db"
TRADING_FEE = 0.001

def load_data(symbol="BTC"):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT date, open, high, low, close, volume FROM daily_prices WHERE symbol = '{symbol}' ORDER BY date ASC", conn)
    conn.close()
    df['date'] = pd.to_datetime(df['date'])
    return df

def generate_long_only_payload(symbol="BTC", breakout_window=15, max_hold=5):
    df = load_data(symbol)
    df['sma50'] = df['close'].rolling(50).mean()
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    df['breakout_high'] = df['high'].shift(1).rolling(breakout_window).max()

    dates = []
    opens, highs, lows, closes, volumes = [], [], [], [], []
    sma50_vals, ema5_vals, breakout_vals = [], [], []

    for i, row in df.iterrows():
        d_str = row['date'].strftime('%Y-%m-%d')
        dates.append(d_str)
        opens.append(round(float(row['open']), 2))
        highs.append(round(float(row['high']), 2))
        lows.append(round(float(row['low']), 2))
        closes.append(round(float(row['close']), 2))
        volumes.append(round(float(row['volume']), 2))

        sma50_vals.append(round(float(row['sma50']), 2) if pd.notna(row['sma50']) else None)
        ema5_vals.append(round(float(row['ema5']), 2) if pd.notna(row['ema5']) else None)
        breakout_vals.append(round(float(row['breakout_high']), 2) if pd.notna(row['breakout_high']) else None)

    cash = 10000.0
    trades = []
    clean_markers = []
    trade_map = {} # date -> trade info
    in_trade = False
    entry_price = 0.0
    entry_date = None
    hold_days = 0
    shares = 0.0

    equity_curve = []
    initial_asset_price = df.iloc[200]['close']

    for i in range(200, len(df)):
        row = df.iloc[i]
        d_str = row['date'].strftime('%Y-%m-%d')
        close_p = row['close']

        if in_trade:
            hold_days += 1
            pct_change = (close_p - entry_price) / entry_price
            current_portfolio_val = shares * close_p
            
            should_exit = False
            exit_reason = ""

            if pct_change <= -0.05:
                should_exit = True
                exit_reason = "Stop Loss (-5%)"
            elif hold_days >= max_hold:
                should_exit = True
                exit_reason = f"Max {max_hold}D Target"
            elif close_p < row['ema5']:
                should_exit = True
                exit_reason = "EMA5 Exit"

            if should_exit:
                exit_price = close_p * (1.0 - TRADING_FEE)
                cash = shares * exit_price
                profit_dollars = round(cash - (shares * entry_price), 2)
                ret_pct = round(((exit_price - entry_price) / entry_price) * 100.0, 2)
                
                t_obj = {
                    "id": len(trades) + 1,
                    "type": "LONG",
                    "entryDate": entry_date,
                    "exitDate": d_str,
                    "entryPrice": round(entry_price, 2),
                    "exitPrice": round(exit_price, 2),
                    "returnPct": ret_pct,
                    "profitDollars": profit_dollars,
                    "holdDays": hold_days,
                    "reason": exit_reason,
                    "portfolioValue": round(cash, 2)
                }
                trades.append(t_obj)
                trade_map[d_str] = {"type": "SELL", "info": t_obj}

                clean_markers.append({
                    "time": d_str,
                    "position": "aboveBar",
                    "color": "#10b981" if ret_pct > 0 else "#ef4444",
                    "shape": "arrowDown",
                    "size": 1,
                    "id": f"sell_{t_obj['id']}"
                })

                in_trade = False
                shares = 0.0

            equity_curve.append({
                "time": d_str,
                "strategyValue": round(current_portfolio_val, 2),
                "buyHoldValue": round(10000.0 * (close_p / initial_asset_price), 2)
            })

        else:
            if close_p > row['sma50'] and close_p > row['breakout_high']:
                entry_price = close_p * (1.0 + TRADING_FEE)
                shares = cash / entry_price
                entry_date = d_str
                hold_days = 0
                in_trade = True

                t_info = {
                    "id": len(trades) + 1,
                    "type": "BUY",
                    "entryDate": d_str,
                    "entryPrice": round(entry_price, 2),
                    "portfolioValue": round(cash, 2)
                }
                trade_map[d_str] = {"type": "BUY", "info": t_info}

                clean_markers.append({
                    "time": d_str,
                    "position": "belowBar",
                    "color": "#3b82f6",
                    "shape": "arrowUp",
                    "size": 1,
                    "id": f"buy_{len(trades)+1}"
                })

            equity_curve.append({
                "time": d_str,
                "strategyValue": round(cash, 2),
                "buyHoldValue": round(10000.0 * (close_p / initial_asset_price), 2)
            })

    trades_df = pd.DataFrame(trades)
    win_rate = round(len(trades_df[trades_df['returnPct'] > 0]) / len(trades_df) * 100.0, 1) if not trades_df.empty else 0.0
    total_trades = len(trades)
    final_val = round(cash, 2)
    cagr = round((((final_val / 10000.0) ** (1.0 / 11.9)) - 1.0) * 100.0, 2) if symbol=="BTC" else round((((final_val / 10000.0) ** (1.0 / 8.8)) - 1.0) * 100.0, 2)

    return {
        "symbol": symbol,
        "name": "Bitcoin (BTC-USD)" if symbol == "BTC" else "Ethereum (ETH-USD)",
        "breakoutWindow": breakout_window,
        "maxHoldDays": max_hold,
        "dates": dates,
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "volumes": volumes,
        "sma50": sma50_vals,
        "ema5": ema5_vals,
        "breakoutHigh": breakout_vals,
        "markers": clean_markers,
        "tradeMap": trade_map,
        "equityCurve": equity_curve,
        "trades": trades,
        "summary": {
            "symbol": symbol,
            "startingCapital": 10000.0,
            "finalValue": final_val,
            "cagr": cagr,
            "totalReturn": round(((final_val - 10000.0)/10000.0)*100.0, 1),
            "winRate": win_rate,
            "totalTrades": total_trades
        }
    }

def main():
    os.makedirs("crypto_chart_viewer/public", exist_ok=True)
    payload = {
        "BTC": generate_long_only_payload("BTC", breakout_window=15, max_hold=5),
        "ETH": generate_long_only_payload("ETH", breakout_window=30, max_hold=5)
    }

    with open("crypto_chart_viewer/public/data.json", "w") as f:
        json.dump(payload, f, indent=2)

    print("Successfully generated clean TradingView dataset with clean markers & equity curves!")

if __name__ == "__main__":
    main()
