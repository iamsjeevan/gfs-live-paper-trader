import os
import json
import sqlite3
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================
START_DATE = "2021-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 100000.0  # ₹1 Lakh
MARGIN_PCT = 0.12           # 12% SPAN + Exposure Margin requirement
SLIPPAGE_PER_LEG = 0.0004   # 0.04% slippage + STT + brokerage per trade leg
ROLLOVER_COST = 0.0008      # 0.08% per month rollover cost (~0.96% p.a.)

NIFTY_LOT_SIZE = 25
BANKNIFTY_LOT_SIZE = 15

RESULTS_DIR = "results"
os.makedirs(RESULTS_DIR, exist_ok=True)

# ==========================================
# INDICATOR CALCULATION FUNCTIONS
# ==========================================
def compute_supertrend(df, period=10, multiplier=3.0):
    high = df['High']
    low = df['Low']
    close = df['Close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    hl2 = (high + low) / 2.0
    basic_ub = hl2 + (multiplier * atr)
    basic_lb = hl2 - (multiplier * atr)

    n = len(df)
    final_ub = np.zeros(n)
    final_lb = np.zeros(n)
    trend = np.zeros(n, dtype=int)  # 1 for Bullish, -1 for Bearish

    for i in range(1, n):
        if i < period:
            final_ub[i] = basic_ub.iloc[i] if not pd.isna(basic_ub.iloc[i]) else 0.0
            final_lb[i] = basic_lb.iloc[i] if not pd.isna(basic_lb.iloc[i]) else 0.0
            trend[i] = 1 if close.iloc[i] >= basic_lb.iloc[i] else -1
            continue

        # Upper Band
        if (basic_ub.iloc[i] < final_ub[i-1]) or (close.iloc[i-1] > final_ub[i-1]):
            final_ub[i] = basic_ub.iloc[i]
        else:
            final_ub[i] = final_ub[i-1]

        # Lower Band
        if (basic_lb.iloc[i] > final_lb[i-1]) or (close.iloc[i-1] < final_lb[i-1]):
            final_lb[i] = basic_lb.iloc[i]
        else:
            final_lb[i] = final_lb[i-1]

        # Trend Decision
        if trend[i-1] == 1:
            if close.iloc[i] < final_lb[i]:
                trend[i] = -1
            else:
                trend[i] = 1
        else:
            if close.iloc[i] > final_ub[i]:
                trend[i] = 1
            else:
                trend[i] = -1

    return pd.Series(trend, index=df.index)

def compute_signals(df):
    signals = {}
    close = df['Close']
    high = df['High']
    low = df['Low']

    # 1. Supertrend (10, 3.0)
    st_trend = compute_supertrend(df, period=10, multiplier=3.0)
    signals['Supertrend (10,3)'] = st_trend

    # 2. Supertrend (7, 2.0)
    st_fast_trend = compute_supertrend(df, period=7, multiplier=2.0)
    signals['Supertrend (7,2)'] = st_fast_trend

    # 3. Dual EMA (10/50)
    ema10 = close.ewm(span=10, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    signals['EMA 10/50 Crossover'] = pd.Series(np.where(ema10 > ema50, 1, -1), index=df.index)

    # 4. Dual SMA (20/200)
    sma20 = close.rolling(20).mean()
    sma200 = close.rolling(200).mean()
    signals['SMA 20/200 Crossover'] = pd.Series(np.where(sma20 > sma200, 1, -1), index=df.index)

    # 5. Donchian Channel Breakout (20-day High/Low, 10-day Mid Exit)
    donchian_high = high.shift(1).rolling(20).max()
    donchian_low = low.shift(1).rolling(20).min()
    donchian_mid = (high.shift(1).rolling(10).max() + low.shift(1).rolling(10).min()) / 2.0
    
    don_sig = np.zeros(len(df), dtype=int)
    curr_pos = 0
    for i in range(20, len(df)):
        c = close.iloc[i]
        dh = donchian_high.iloc[i]
        dl = donchian_low.iloc[i]
        dm = donchian_mid.iloc[i]

        if pd.isna(dh) or pd.isna(dl):
            continue

        if curr_pos == 0:
            if c > dh:
                curr_pos = 1
            elif c < dl:
                curr_pos = -1
        elif curr_pos == 1:
            if c < dm or c < dl:
                curr_pos = 0 if c >= dl else -1
        elif curr_pos == -1:
            if c > dm or c > dh:
                curr_pos = 0 if c <= dh else 1
        don_sig[i] = curr_pos
    signals['Donchian Breakout (20d)'] = pd.Series(don_sig, index=df.index)

    # 6. Volatility Expansion (ATR Breakout: 20 EMA +/- 1.5*ATR14)
    ema20 = close.ewm(span=20, adjust=False).mean()
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean()

    ub = ema20 + 1.5 * atr14
    lb = ema20 - 1.5 * atr14

    atr_sig = np.zeros(len(df), dtype=int)
    curr_pos = 0
    for i in range(20, len(df)):
        c = close.iloc[i]
        e = ema20.iloc[i]
        u = ub.iloc[i]
        l = lb.iloc[i]

        if pd.isna(u) or pd.isna(l):
            continue

        if curr_pos == 0:
            if c > u:
                curr_pos = 1
            elif c < l:
                curr_pos = -1
        elif curr_pos == 1:
            if c < e:
                curr_pos = 0 if c >= l else -1
        elif curr_pos == -1:
            if c > e:
                curr_pos = 0 if c <= u else 1
        atr_sig[i] = curr_pos
    signals['ATR Volatility Expansion'] = pd.Series(atr_sig, index=df.index)

    # 7. Benchmark Buy & Hold (Long Futures 1.0x)
    signals['Buy & Hold Benchmark'] = pd.Series(1, index=df.index)

    return signals

# ==========================================
# SIMULATION ENGINE
# ==========================================
def run_futures_backtest(df, signal_series, initial_capital=100000.0, mode='micro', leverage=1.0, lot_size=25):
    dates = df.index
    prices = df['Close'].values
    n = len(df)
    
    df_month = pd.Series(df.index.to_period('M'), index=df.index)
    is_month_end = (df_month != df_month.shift(-1)).values

    capital = float(initial_capital)
    equity = np.zeros(n)
    equity[0] = capital

    pos = 0  # Position: 1 for Long, -1 for Short, 0 for Cash
    trades = []
    entry_price = 0.0
    entry_date = None
    entry_capital = capital
    margin_calls = 0

    for t in range(1, n):
        prev_p = prices[t-1]
        curr_p = prices[t]
        date = dates[t]

        # 1. Update daily portfolio value based on previous day's position
        if mode == 'micro':
            if pos != 0:
                ret = pos * leverage * (curr_p - prev_p) / prev_p
                capital *= (1.0 + ret)
                if is_month_end[t]:
                    capital -= capital * leverage * ROLLOVER_COST
        else:  # '1lot'
            if pos != 0:
                pnl = pos * lot_size * (curr_p - prev_p)
                capital += pnl
                if is_month_end[t]:
                    capital -= lot_size * curr_p * ROLLOVER_COST
                
                req_margin = lot_size * curr_p * MARGIN_PCT
                if capital < req_margin:
                    margin_calls += 1

        # 2. Check position change based on signal evaluated at t-1
        target_sig = signal_series.iloc[t-1]
        if pd.isna(target_sig):
            target_sig = 0
        else:
            target_sig = int(target_sig)

        if target_sig != pos:
            # Close existing open trade
            if pos != 0:
                if mode == 'micro':
                    t_cost = capital * leverage * SLIPPAGE_PER_LEG
                    capital -= t_cost
                    trade_pnl = capital - entry_capital
                else:
                    t_cost = lot_size * curr_p * SLIPPAGE_PER_LEG
                    capital -= t_cost
                    trade_pnl = pos * lot_size * (curr_p - entry_price) - t_cost

                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'type': 'Long' if pos == 1 else 'Short',
                    'entry_price': entry_price,
                    'exit_price': curr_p,
                    'pnl': trade_pnl,
                    'pnl_pct': trade_pnl / entry_capital * 100.0 if mode == 'micro' else trade_pnl / (lot_size * entry_price * MARGIN_PCT) * 100.0
                })

            # Open new trade
            pos = target_sig
            if pos != 0:
                entry_price = curr_p
                entry_date = date
                entry_capital = capital
                if mode == 'micro':
                    t_cost = capital * leverage * SLIPPAGE_PER_LEG
                    capital -= t_cost
                else:
                    t_cost = lot_size * curr_p * SLIPPAGE_PER_LEG
                    capital -= t_cost

        equity[t] = max(capital, 0.0)

    # Performance metrics calculation
    eq_series = pd.Series(equity, index=dates)
    daily_rets = eq_series.pct_change().fillna(0.0)

    total_ret = (capital - initial_capital) / initial_capital * 100.0
    years = max((dates[-1] - dates[0]).days / 365.25, 0.5)
    cagr = ((max(capital, 0.0001) / initial_capital) ** (1.0 / years) - 1.0) * 100.0 if capital > 0 else -100.0

    peak = eq_series.cummax()
    dd = (peak - eq_series) / np.maximum(peak, 1.0)
    max_dd = dd.max() * 100.0

    win_trades = [tr for tr in trades if tr['pnl'] > 0]
    win_rate = len(win_trades) / len(trades) * 100.0 if len(trades) > 0 else 0.0

    gross_profit = sum([tr['pnl'] for tr in trades if tr['pnl'] > 0])
    gross_loss = abs(sum([tr['pnl'] for tr in trades if tr['pnl'] < 0]))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    mean_ret = daily_rets.mean()
    std_ret = daily_rets.std()
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0

    downside_std = daily_rets[daily_rets < 0].std()
    sortino = (mean_ret / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0

    return {
        'initial_capital': initial_capital,
        'final_capital': round(capital, 2),
        'total_return_pct': round(total_ret, 2),
        'cagr_pct': round(cagr, 2),
        'max_dd_pct': round(max_dd, 2),
        'total_trades': len(trades),
        'win_rate_pct': round(win_rate, 2),
        'gross_profit': round(gross_profit, 2),
        'gross_loss': round(gross_loss, 2),
        'profit_factor': round(profit_factor, 2),
        'sharpe_ratio': round(sharpe, 2),
        'sortino_ratio': round(sortino, 2),
        'margin_calls': margin_calls
    }

# ==========================================
# SYNTHETIC INTRADAY 30-MIN GENERATOR
# ==========================================
def generate_intraday_30m_data(daily_df):
    intraday_rows = []
    for date, row in daily_df.iterrows():
        o, h, l, c = row['Open'], row['High'], row['Low'], row['Close']
        if pd.isna(o) or pd.isna(c) or o <= 0:
            continue
        v = row['Volume'] / 12.0 if 'Volume' in row and pd.notna(row['Volume']) else 1000.0
        
        if c >= o:
            prices = [o, o + (h - o)*0.2, o - (o - l)*0.4, o + (h - o)*0.5, o + (h - o)*0.7, h, h - (h - c)*0.4, c]
        else:
            prices = [o, o - (o - l)*0.2, o + (h - o)*0.4, o - (o - l)*0.5, o - (o - l)*0.7, l, l + (c - l)*0.4, c]
        
        interp_prices = np.interp(np.linspace(0, len(prices)-1, 12), np.arange(len(prices)), prices)
        time_stamps = pd.date_range(start=f"{date.strftime('%Y-%m-%d')} 09:15:00", periods=12, freq='30min')
        
        for t, p in zip(time_stamps, interp_prices):
            intraday_rows.append({'Datetime': t, 'Open': p, 'High': p*1.0008, 'Low': p*0.9992, 'Close': p, 'Volume': v})

    df_30m = pd.DataFrame(intraday_rows).set_index('Datetime')
    return df_30m

# ==========================================
# MAIN EXECUTION ROUTINE
# ==========================================
def main():
    print("=" * 80)
    print(" INDIAN FUTURES & DERIVATIVES STRATEGY BACKTEST (2021 - 2026)")
    print(" Initial Capital: ₹1,000,000 / ₹100,000 | SPAN Margin: 12%")
    print(" Brokerage & Slippage: 0.04% / leg | Monthly Rollover Cost: 0.08%")
    print("=" * 80)

    # 1. Download Historical Data
    tickers = {
        'Nifty 50 Futures': {'symbol': '^NSEI', 'lot_size': NIFTY_LOT_SIZE},
        'BankNifty Futures': {'symbol': '^NSEBANK', 'lot_size': BANKNIFTY_LOT_SIZE}
    }

    all_results = []

    for name, info in tickers.items():
        print(f"\n[+] Processing {name} ({info['symbol']})...")
        df_daily = yf.download(info['symbol'], start=START_DATE, end=END_DATE)
        if isinstance(df_daily.columns, pd.MultiIndex):
            df_daily.columns = df_daily.columns.get_level_values(0)

        df_daily = df_daily.dropna(subset=['Close'])

        # Daily Signals
        daily_signals = compute_signals(df_daily)

        # 30-min Intraday Data & Supertrend (Intraday) Signal
        df_30m = generate_intraday_30m_data(df_daily)
        st_30m_trend = compute_supertrend(df_30m, period=10, multiplier=3.0)

        # Resample 30m Supertrend signal back to daily close for multi-timeframe comparison
        st_30m_daily = st_30m_trend.resample('D').last().reindex(df_daily.index).ffill().fillna(1)
        daily_signals['Supertrend (Intraday 30-min)'] = st_30m_daily

        # Run simulations across Sizing Modes
        modes = [
            ('Micro Futures 1.0x (Unleveraged)', 'micro', 1.0),
            ('Micro Futures 2.0x (Leveraged)', 'micro', 2.0),
            ('Fixed 1 Contract Lot (Real Margin Sized)', '1lot', 1.0)
        ]

        for strat_name, sig_series in daily_signals.items():
            for mode_label, mode_code, lev in modes:
                res = run_futures_backtest(
                    df_daily,
                    sig_series,
                    initial_capital=INITIAL_CAPITAL,
                    mode=mode_code,
                    leverage=lev,
                    lot_size=info['lot_size']
                )

                res_record = {
                    'Asset': name,
                    'Strategy': strat_name,
                    'Sizing_Mode': mode_label,
                    'Initial_Capital': res['initial_capital'],
                    'Final_Capital': res['final_capital'],
                    'Total_Return_Pct': res['total_return_pct'],
                    'CAGR_Pct': res['cagr_pct'],
                    'Max_Drawdown_Pct': res['max_dd_pct'],
                    'Total_Trades': res['total_trades'],
                    'Win_Rate_Pct': res['win_rate_pct'],
                    'Gross_Profit': res['gross_profit'],
                    'Gross_Loss': res['gross_loss'],
                    'Profit_Factor': res['profit_factor'],
                    'Sharpe_Ratio': res['sharpe_ratio'],
                    'Sortino_Ratio': res['sortino_ratio'],
                    'Margin_Calls': res['margin_calls']
                }
                all_results.append(res_record)

    # Convert to DataFrame
    results_df = pd.DataFrame(all_results)
    
    # Save CSV & JSON
    csv_path = os.path.join(RESULTS_DIR, "futures_strategies_summary.csv")
    json_path = os.path.join(RESULTS_DIR, "futures_backtest_results.json")
    results_df.to_csv(csv_path, index=False)
    
    with open(json_path, 'w') as f:
        json.dump(all_results, f, indent=4)

    print(f"\n[✓] Results successfully exported to:")
    print(f"    - CSV: {csv_path}")
    print(f"    - JSON: {json_path}")

    # Display Top Performing Strategies Table
    print("\n" + "=" * 120)
    print(" SUMMARY OF FUTURES STRATEGIES PERFORMANCE (NIFTY 50 & BANK NIFTY 2021-2026)")
    print("=" * 120)
    
    display_cols = ['Asset', 'Strategy', 'Sizing_Mode', 'Final_Capital', 'CAGR_Pct', 'Max_Drawdown_Pct', 'Win_Rate_Pct', 'Sharpe_Ratio', 'Sortino_Ratio', 'Profit_Factor']
    pd.set_option('display.max_columns', 15)
    pd.set_option('display.width', 1000)
    print(results_df[display_cols].to_string(index=False))

if __name__ == "__main__":
    main()
