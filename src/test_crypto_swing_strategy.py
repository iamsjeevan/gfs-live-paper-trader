import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/crypto_prices.db"
INITIAL_CAPITAL = 10000.0  # $10,000 Starting Capital
TRADING_FEE = 0.001        # 0.1% Binance / Coinbase Fee per trade

def load_crypto_data(symbol="BTC"):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT date, open, high, low, close, volume FROM daily_prices WHERE symbol = '{symbol}' ORDER BY date ASC", conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    return df

def calculate_indicators(df):
    df['sma50'] = df['close'].rolling(50).mean()
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    df['high_20'] = df['high'].shift(1).rolling(20).max()
    df['low_20'] = df['low'].shift(1).rolling(20).min()

    # 2-Period RSI for short-term swing dip buying
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(2).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(2).mean()
    rs = gain / (loss + 1e-6)
    df['rsi2'] = 100 - (100 / (1 + rs))

    # Bollinger Band Width
    sma20 = df['close'].rolling(20).mean()
    std20 = df['close'].rolling(20).std()
    df['bb_upper'] = sma20 + (2 * std20)
    df['bb_lower'] = sma20 - (2 * std20)
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / (sma20 + 1e-6)
    df['bb_squeeze'] = df['bb_width'] < df['bb_width'].rolling(100).quantile(0.25)

    return df

def run_2_3_day_swing_backtest(df, strategy_type="RSI_DIP", max_hold_days=3):
    cash = INITIAL_CAPITAL
    equity_curve = []
    trades = []
    in_trade = False
    entry_price = 0.0
    entry_date = None
    hold_days = 0
    shares = 0.0

    dates = df.index
    for i in range(50, len(df)):
        current_date = dates[i]
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        close_p = row['close']

        if in_trade:
            hold_days += 1
            current_portfolio = shares * close_p
            equity_curve.append({'date': current_date, 'value': current_portfolio})

            # Check Exit Conditions
            should_exit = False
            exit_reason = ""

            if hold_days >= max_hold_days:
                should_exit = True
                exit_reason = f"Max {max_hold_days}-Day Target"
            elif strategy_type == "RSI_DIP" and row['rsi2'] > 70:
                should_exit = True
                exit_reason = "RSI2 > 70 Profit Take"
            elif strategy_type == "BREAKOUT" and close_p < row['ema5']:
                should_exit = True
                exit_reason = "EMA5 Exit"

            if should_exit:
                exit_price = close_p * (1.0 - TRADING_FEE)
                cash = shares * exit_price
                ret_pct = ((exit_price - entry_price) / entry_price) * 100.0
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': current_date,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'hold_days': hold_days,
                    'return_pct': ret_pct,
                    'exit_reason': exit_reason
                })
                in_trade = False
                shares = 0.0

        else:
            equity_curve.append({'date': current_date, 'value': cash})

            # Check Entry Conditions
            should_enter = False
            if strategy_type == "RSI_DIP":
                # Entry: Trend is Bullish (Price > 50 SMA) AND Short-term Oversold (RSI2 < 25)
                if row['close'] > row['sma50'] and row['rsi2'] < 25:
                    should_enter = True

            elif strategy_type == "BREAKOUT":
                # Entry: Squeeze + 20-Day Breakout + Price > 50 SMA
                if row['close'] > row['high_20'] and row['close'] > row['sma50']:
                    should_enter = True

            elif strategy_type == "MOMENTUM_PULSE":
                # Entry: 3-Day surge > +5% with price > 50 SMA
                ret3d = (row['close'] / df.iloc[i-3]['close']) - 1.0
                if ret3d > 0.05 and row['close'] > row['sma50']:
                    should_enter = True

            if should_enter:
                entry_price = close_p * (1.0 + TRADING_FEE)
                shares = cash / entry_price
                entry_date = current_date
                hold_days = 0
                in_trade = True

    eq_df = pd.DataFrame(equity_curve)
    if eq_df.empty:
        return 0, 0, 0, 0, 0, 0

    final_val = eq_df['value'].iloc[-1]
    num_years = (eq_df['date'].iloc[-1] - eq_df['date'].iloc[0]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / num_years) - 1.0) * 100.0 if final_val > 0 else -100.0

    eq_df['peak'] = eq_df['value'].cummax()
    max_dd = ((eq_df['value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    trades_df = pd.DataFrame(trades)
    win_rate = (len(trades_df[trades_df['return_pct'] > 0]) / len(trades_df) * 100.0) if not trades_df.empty else 0.0
    avg_hold = trades_df['hold_days'].mean() if not trades_df.empty else 0.0
    total_trades = len(trades_df)

    return round(final_val, 2), round(cagr, 2), round(max_dd, 2), round(win_rate, 2), round(avg_hold, 1), total_trades

def main():
    print("=" * 90, flush=True)
    print("   CRYPTO 2-3 DAY SHORT-TERM SWING STRATEGY AUDIT (BITCOIN & ETHEREUM)   ", flush=True)
    print("=" * 90, flush=True)

    btc_df = calculate_indicators(load_crypto_data("BTC"))
    eth_df = calculate_indicators(load_crypto_data("ETH"))

    strategies = [
        ("RSI_DIP", "RSI2 Oversold Pullback (2-3 Day Hold)"),
        ("BREAKOUT", "20-Day Momentum Breakout (2-3 Day Hold)"),
        ("MOMENTUM_PULSE", "+5% Momentum Pulse Surge (2-3 Day Hold)")
    ]

    print("\n--- 1. BITCOIN (BTC-USD) SHORT-TERM 2-3 DAY SWING RESULTS (2014 - 2026) ---")
    for strat_code, strat_name in strategies:
        v, c, d, w, h, t = run_2_3_day_swing_backtest(btc_df, strategy_type=strat_code, max_hold_days=3)
        print(f"\n📌 Strategy: {strat_name}")
        print(f"   - Final Value ($10k Start): ${v:,.2f} | CAGR: {c}% | Max DD: {d}% | Win Rate: {w}% | Avg Hold: {h} days | Trades: {t}")

    print("\n--- 2. ETHEREUM (ETH-USD) SHORT-TERM 2-3 DAY SWING RESULTS (2017 - 2026) ---")
    for strat_code, strat_name in strategies:
        v, c, d, w, h, t = run_2_3_day_swing_backtest(eth_df, strategy_type=strat_code, max_hold_days=3)
        print(f"\n📌 Strategy: {strat_name}")
        print(f"   - Final Value ($10k Start): ${v:,.2f} | CAGR: {c}% | Max DD: {d}% | Win Rate: {w}% | Avg Hold: {h} days | Trades: {t}")

if __name__ == "__main__":
    main()
