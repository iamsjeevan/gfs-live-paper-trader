import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/crypto_prices.db"
INITIAL_CAPITAL = 10000.0
TRADING_FEE = 0.001

def load_crypto_data(symbol="BTC"):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT date, open, high, low, close, volume FROM daily_prices WHERE symbol = '{symbol}' ORDER BY date ASC", conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    return df

def run_symmetric_swing_backtest(df, symbol="BTC", breakout_window=15, max_hold_days=5, allow_short=True):
    df_sim = df.copy()
    df_sim['sma50'] = df_sim['close'].rolling(50).mean()
    df_sim['ema5'] = df_sim['close'].ewm(span=5, adjust=False).mean()
    df_sim['breakout_high'] = df_sim['high'].shift(1).rolling(breakout_window).max()
    df_sim['breakout_low'] = df_sim['low'].shift(1).rolling(breakout_window).min()

    cash = INITIAL_CAPITAL
    equity_curve = []
    trades = []
    
    in_trade = False
    position_type = None # 'LONG' or 'SHORT'
    entry_price = 0.0
    entry_date = None
    hold_days = 0
    units = 0.0

    dates = df_sim.index
    for i in range(200, len(df_sim)):
        current_date = dates[i]
        row = df_sim.iloc[i]
        close_p = row['close']

        if in_trade:
            hold_days += 1
            
            if position_type == 'LONG':
                current_val = units * close_p
                pct_change = (close_p - entry_price) / entry_price
            else: # SHORT
                # Short PnL: Profit when price drops
                current_val = cash + units * (entry_price - close_p)
                pct_change = (entry_price - close_p) / entry_price

            equity_curve.append({'date': current_date, 'value': current_val})

            # Check Exit Conditions (Symmetric for Long & Short)
            should_exit = False
            exit_reason = ""

            if pct_change <= -0.05:
                should_exit = True
                exit_reason = "Stop Loss (-5%)"
            elif hold_days >= max_hold_days:
                should_exit = True
                exit_reason = f"Max {max_hold_days}D Target"
            elif position_type == 'LONG' and close_p < row['ema5']:
                should_exit = True
                exit_reason = "EMA5 Cross Exit"
            elif position_type == 'SHORT' and close_p > row['ema5']:
                should_exit = True
                exit_reason = "EMA5 Cross Exit"

            if should_exit:
                if position_type == 'LONG':
                    exit_price = close_p * (1.0 - TRADING_FEE)
                    cash = units * exit_price
                    ret_pct = ((exit_price - entry_price) / entry_price) * 100.0
                else: # SHORT
                    exit_price = close_p * (1.0 + TRADING_FEE)
                    cash = cash + units * (entry_price - exit_price)
                    ret_pct = ((entry_price - exit_price) / entry_price) * 100.0

                trades.append({
                    'symbol': symbol,
                    'type': position_type,
                    'entry_date': entry_date,
                    'exit_date': current_date,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'hold_days': hold_days,
                    'return_pct': ret_pct,
                    'exit_reason': exit_reason
                })
                in_trade = False
                position_type = None
                units = 0.0

        else:
            equity_curve.append({'date': current_date, 'value': cash})

            # Long Entry: Price > 50 SMA AND Price > Breakout High (New High Breakout)
            if close_p > row['sma50'] and close_p > row['breakout_high']:
                entry_price = close_p * (1.0 + TRADING_FEE)
                units = cash / entry_price
                entry_date = current_date
                hold_days = 0
                in_trade = True
                position_type = 'LONG'

            # Short Entry: Price < 50 SMA AND Price < Breakout Low (New Downward Breakdown Signal)
            elif allow_short and close_p < row['sma50'] and close_p < row['breakout_low']:
                entry_price = close_p * (1.0 - TRADING_FEE)
                units = cash / entry_price
                entry_date = current_date
                hold_days = 0
                in_trade = True
                position_type = 'SHORT'

    eq_df = pd.DataFrame(equity_curve)
    if eq_df.empty:
        return None

    final_val = eq_df['value'].iloc[-1]
    num_years = (eq_df['date'].iloc[-1] - eq_df['date'].iloc[0]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / num_years) - 1.0) * 100.0 if final_val > 0 else -100.0

    eq_df['peak'] = eq_df['value'].cummax()
    max_dd = ((eq_df['value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    trades_df = pd.DataFrame(trades)
    win_rate = (len(trades_df[trades_df['return_pct'] > 0]) / len(trades_df) * 100.0) if not trades_df.empty else 0.0
    long_trades = trades_df[trades_df['type'] == 'LONG'] if not trades_df.empty else pd.DataFrame()
    short_trades = trades_df[trades_df['type'] == 'SHORT'] if not trades_df.empty else pd.DataFrame()

    long_win_rate = (len(long_trades[long_trades['return_pct'] > 0]) / len(long_trades) * 100.0) if not long_trades.empty else 0.0
    short_win_rate = (len(short_trades[short_trades['return_pct'] > 0]) / len(short_trades) * 100.0) if not short_trades.empty else 0.0

    return {
        "symbol": symbol,
        "mode": "LONG + SHORT (Symmetric Breakout)" if allow_short else "LONG ONLY",
        "final_val": round(final_val, 2),
        "cagr": round(cagr, 2),
        "max_dd": round(max_dd, 2),
        "total_win_rate": round(win_rate, 2),
        "total_trades": len(trades_df),
        "long_trades": len(long_trades),
        "long_win_rate": round(long_win_rate, 2),
        "short_trades": len(short_trades),
        "short_win_rate": round(short_win_rate, 2)
    }

def main():
    print("=" * 95, flush=True)
    print("      SYMMETRIC BREAKOUT SHORTING AUDIT: BITCOIN & ETHEREUM (2014 - 2026)      ", flush=True)
    print("=" * 95, flush=True)

    btc_df = load_crypto_data("BTC")
    eth_df = load_crypto_data("ETH")

    print("\n--- 1. BITCOIN (BTC-USD) ---")
    btc_long = run_symmetric_swing_backtest(btc_df, symbol="BTC", breakout_window=15, max_hold_days=5, allow_short=False)
    btc_both = run_symmetric_swing_backtest(btc_df, symbol="BTC", breakout_window=15, max_hold_days=5, allow_short=True)

    for r in [btc_long, btc_both]:
        print(f"\n📌 Strategy Mode: {r['mode']}")
        print(f"   - Final Value ($10k Start): ${r['final_val']:,.2f} | CAGR: {r['cagr']}% | Max DD: {r['max_dd']}%")
        print(f"   - Total Win Rate: {r['total_win_rate']}% ({r['total_trades']} Trades)")
        print(f"   - Long Trades: {r['long_trades']} (Win Rate: {r['long_win_rate']}%)")
        print(f"   - Short Trades: {r['short_trades']} (Win Rate: {r['short_win_rate']}%)")

    print("\n--- 2. ETHEREUM (ETH-USD) ---")
    eth_long = run_symmetric_swing_backtest(eth_df, symbol="ETH", breakout_window=30, max_hold_days=5, allow_short=False)
    eth_both = run_symmetric_swing_backtest(eth_df, symbol="ETH", breakout_window=30, max_hold_days=5, allow_short=True)

    for r in [eth_long, eth_both]:
        print(f"\n📌 Strategy Mode: {r['mode']}")
        print(f"   - Final Value ($10k Start): ${r['final_val']:,.2f} | CAGR: {r['cagr']}% | Max DD: {r['max_dd']}%")
        print(f"   - Total Win Rate: {r['total_win_rate']}% ({r['total_trades']} Trades)")
        print(f"   - Long Trades: {r['long_trades']} (Win Rate: {r['long_win_rate']}%)")
        print(f"   - Short Trades: {r['short_trades']} (Win Rate: {r['short_win_rate']}%)")

if __name__ == "__main__":
    main()
