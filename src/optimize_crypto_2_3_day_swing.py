import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/crypto_prices.db"
INITIAL_CAPITAL = 10000.0  # $10,000 Starting Capital
TRADING_FEE = 0.001        # 0.1% Binance/Coinbase fee per trade

def load_crypto_data(symbol="BTC"):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(f"SELECT date, open, high, low, close, volume FROM daily_prices WHERE symbol = '{symbol}' ORDER BY date ASC", conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    return df

def run_parameter_simulation(df, breakout_window, max_hold_days, regime_filter="SMA50", stop_loss_pct=0.04):
    # Pre-calculate indicators
    df_sim = df.copy()
    df_sim['sma50'] = df_sim['close'].rolling(50).mean()
    df_sim['sma200'] = df_sim['close'].rolling(200).mean()
    df_sim['ema5'] = df_sim['close'].ewm(span=5, adjust=False).mean()
    df_sim['breakout_high'] = df_sim['high'].shift(1).rolling(breakout_window).max()

    cash = INITIAL_CAPITAL
    equity_curve = []
    trades = []
    in_trade = False
    entry_price = 0.0
    entry_date = None
    hold_days = 0
    shares = 0.0

    dates = df_sim.index
    for i in range(200, len(df_sim)):
        current_date = dates[i]
        row = df_sim.iloc[i]
        close_p = row['close']

        if in_trade:
            hold_days += 1
            current_portfolio = shares * close_p
            equity_curve.append({'date': current_date, 'value': current_portfolio})

            # Exit logic checks
            pct_change_since_entry = (close_p - entry_price) / entry_price
            
            should_exit = False
            exit_reason = ""

            # Stop loss check
            if stop_loss_pct > 0 and pct_change_since_entry <= -stop_loss_pct:
                should_exit = True
                exit_reason = f"Stop Loss ({int(stop_loss_pct*100)}%)"
            elif hold_days >= max_hold_days:
                should_exit = True
                exit_reason = f"Max {max_hold_days}-Day Window"
            elif close_p < row['ema5']:
                should_exit = True
                exit_reason = "EMA5 Cross Exit"

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

            # Check Trend Regime Filter
            regime_ok = False
            if regime_filter == "SMA50" and close_p > row['sma50']:
                regime_ok = True
            elif regime_filter == "SMA200" and close_p > row['sma200']:
                regime_ok = True
            elif regime_filter == "DUAL" and close_p > row['sma50'] and row['sma50'] > row['sma200']:
                regime_ok = True

            # Entry Trigger: Daily Close > N-Day Breakout High
            if regime_ok and close_p > row['breakout_high']:
                entry_price = close_p * (1.0 + TRADING_FEE)
                shares = cash / entry_price
                entry_date = current_date
                hold_days = 0
                in_trade = True

    eq_df = pd.DataFrame(equity_curve)
    if eq_df.empty or len(trades) < 10:
        return None

    final_val = eq_df['value'].iloc[-1]
    num_years = (eq_df['date'].iloc[-1] - eq_df['date'].iloc[0]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / num_years) - 1.0) * 100.0 if final_val > 0 else -100.0

    eq_df['peak'] = eq_df['value'].cummax()
    max_dd = ((eq_df['value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    trades_df = pd.DataFrame(trades)
    win_rate = (len(trades_df[trades_df['return_pct'] > 0]) / len(trades_df) * 100.0)
    avg_hold = trades_df['hold_days'].mean()
    total_trades = len(trades_df)
    profit_factor = (trades_df[trades_df['return_pct'] > 0]['return_pct'].sum() / 
                     abs(trades_df[trades_df['return_pct'] < 0]['return_pct'].sum()) 
                     if abs(trades_df[trades_df['return_pct'] < 0]['return_pct'].sum()) > 0 else np.nan)

    return {
        "final_val": round(final_val, 2),
        "cagr": round(cagr, 2),
        "max_dd": round(max_dd, 2),
        "win_rate": round(win_rate, 2),
        "avg_hold": round(avg_hold, 1),
        "trades": total_trades,
        "profit_factor": round(profit_factor, 2) if pd.notna(profit_factor) else 0.0,
        "breakout_window": breakout_window,
        "max_hold_days": max_hold_days,
        "regime_filter": regime_filter,
        "stop_loss_pct": stop_loss_pct
    }

def main():
    print("=" * 100, flush=True)
    print("      DEEP PARAMETER OPTIMIZATION: BITCOIN & ETHEREUM 2-3 DAY SWING TRADING      ", flush=True)
    print("=" * 100, flush=True)

    btc_df = load_crypto_data("BTC")
    eth_df = load_crypto_data("ETH")

    breakout_windows = [10, 15, 20, 30]
    hold_days_list = [1, 2, 3, 4, 5]
    regime_filters = ["SMA50", "SMA200", "DUAL"]
    stop_losses = [0.03, 0.04, 0.05, 0.0]

    for symbol, df in [("BITCOIN (BTC-USD)", btc_df), ("ETHEREUM (ETH-USD)", eth_df)]:
        print(f"\n==================== GRID SEARCH RESULTS FOR {symbol} ====================", flush=True)
        results = []

        for bw in breakout_windows:
            for hd in hold_days_list:
                for rf in regime_filters:
                    for sl in stop_losses:
                        res = run_parameter_simulation(df, breakout_window=bw, max_hold_days=hd, regime_filter=rf, stop_loss_pct=sl)
                        if res:
                            results.append(res)

        res_df = pd.DataFrame(results)
        
        # Sort by highest CAGR
        top_cagr = res_df.sort_values(by="cagr", ascending=False).head(5)
        print(f"\n--- TOP 5 STRATEGIES BY CAGR FOR {symbol} ---")
        for idx, r in top_cagr.iterrows():
            print(f"🥇 CAGR: {r['cagr']}% | Final: ${r['final_val']:,.2f} | Max DD: {r['max_dd']}% | Win Rate: {r['win_rate']}% | Breakout: {r['breakout_window']}D | Hold: {r['max_hold_days']}D | Regime: {r['regime_filter']} | StopLoss: {int(r['stop_loss_pct']*100)}% | Trades: {r['trades']}")

        # Sort by best Risk-Adjusted Ratio (CAGR / |MaxDD|)
        res_df['calmar'] = res_df['cagr'] / abs(res_df['max_dd'] + 1e-6)
        top_calmar = res_df.sort_values(by="calmar", ascending=False).head(5)
        print(f"\n--- TOP 5 LOWEST DRAWDOWN / HIGHEST CALMAR STRATEGIES FOR {symbol} ---")
        for idx, r in top_calmar.iterrows():
            print(f"🛡️ Calmar: {r['calmar']:.2f} | CAGR: {r['cagr']}% | Max DD: {r['max_dd']}% | Win Rate: {r['win_rate']}% | Breakout: {r['breakout_window']}D | Hold: {r['max_hold_days']}D | Regime: {r['regime_filter']} | StopLoss: {int(r['stop_loss_pct']*100)}%")

if __name__ == "__main__":
    main()
