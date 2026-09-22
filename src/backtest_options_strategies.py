import os
import math
import json
import numpy as np
import pandas as pd
import scipy.stats as stats
import yfinance as yf

# ==========================================
# 1. OPTION PRICING & GREEKS (Black-Scholes)
# ==========================================

def bs_call(S, K, T, r, sigma):
    if T <= 0.0001 or sigma <= 0.0001:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * stats.norm.cdf(d1) - K * math.exp(-r * T) * stats.norm.cdf(d2)

def bs_put(S, K, T, r, sigma):
    if T <= 0.0001 or sigma <= 0.0001:
        return max(0.0, K - S)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return K * math.exp(-r * T) * stats.norm.cdf(-d2) - S * stats.norm.cdf(-d1)

def get_iv_skew(base_iv, option_type, otm_pct):
    """
    Applies realistic Indian Index & Equity IV Skew:
    - Put IV increases with OTM distance (downside skew)
    - Call IV is flatter or slightly downward sloping
    """
    otm_pct = max(0.0, otm_pct)
    if option_type == 'PE':
        return base_iv * (1.0 + 1.5 * otm_pct)
    else:
        return base_iv * (1.0 - 0.20 * otm_pct)

# ==========================================
# 2. TRANSACTION COSTS & FRICTIONS (INDIAN MARKET)
# ==========================================

def calculate_costs(leg_type, premium, contract_val, lot_size=50, is_buy=False, is_exercise=False):
    """
    Indian Regulatory Fees & Transaction Frictions:
    - Brokerage: ₹20 flat per executed order
    - GST: 18% on brokerage (₹3.60)
    - STT: 0.0625% on premium when selling options; 0.125% on contract value if exercised
    - Stamp Duty: 0.003% on buy premium
    - Exchange turnover: 0.05% of premium
    - Slippage: 0.75% of option premium per leg (bid-ask spread & impact cost)
    """
    brokerage = 20.0
    gst = brokerage * 0.18  # ₹3.60
    
    prem_val = max(premium, 1.0) * lot_size
    
    if is_exercise:
        stt = contract_val * lot_size * 0.00125
    elif not is_buy: # Option Sale
        stt = prem_val * 0.000625
    else: # Option Buy
        stt = 0.0
        
    stamp_duty = prem_val * 0.00003 if is_buy else 0.0
    exch_charge = prem_val * 0.0005
    slippage = prem_val * 0.0075 # 0.75% execution slippage
    
    total_cost = brokerage + gst + stt + stamp_duty + exch_charge + slippage
    return total_cost

# ==========================================
# 3. PERFORMANCE METRICS CALCULATOR
# ==========================================

def calculate_performance_metrics(equity_series, trades_list, initial_capital=100000.0, r_f=0.06):
    n_days = len(equity_series)
    years = max(n_days / 252.0, 0.1)
    
    final_cap = max(0.0, equity_series.iloc[-1])
    tot_return = (final_cap - initial_capital) / initial_capital
    cagr = (final_cap / initial_capital) ** (1.0 / years) - 1.0 if final_cap > 0 else -1.0
    
    # Daily returns
    daily_rets = equity_series.pct_change().dropna()
    
    # Max Drawdown
    cummax = equity_series.cummax()
    drawdown = (equity_series - cummax) / cummax
    max_dd = abs(drawdown.min()) if len(drawdown) > 0 else 0.0
    
    # Sharpe Ratio
    mean_ret = daily_rets.mean()
    std_ret = daily_rets.std()
    rf_daily = r_f / 252.0
    sharpe = ((mean_ret - rf_daily) / std_ret * math.sqrt(252.0)) if (std_ret > 0 and not math.isnan(std_ret)) else 0.0
    
    # Sortino Ratio
    downside_rets = daily_rets[daily_rets < rf_daily]
    downside_std = downside_rets.std()
    sortino = ((mean_ret - rf_daily) / downside_std * math.sqrt(252.0)) if (downside_std > 0 and not math.isnan(downside_std)) else 0.0
    
    # Calmar Ratio
    calmar = (cagr / max_dd) if max_dd > 0 else 0.0
    
    # Win Rate
    if len(trades_list) > 0:
        winning_trades = sum(1 for t in trades_list if t.get('pnl', 0) > 0)
        win_rate = winning_trades / len(trades_list)
    else:
        win_rate = 0.0
        
    return {
        'Initial Capital (₹)': initial_capital,
        'Final Capital (₹)': round(final_cap, 2),
        'Total Return (%)': round(tot_return * 100, 2),
        'CAGR (%)': round(cagr * 100, 2),
        'Max Drawdown (%)': round(max_dd * 100, 2),
        'Win Rate (%)': round(win_rate * 100, 2),
        'Total Trades': len(trades_list),
        'Sharpe Ratio': round(sharpe, 2),
        'Sortino Ratio': round(sortino, 2),
        'Calmar Ratio': round(calmar, 2)
    }

# ==========================================
# 4. DATA DOWNLOAD & PREPROCESSING
# ==========================================

def load_market_data(start_date='2021-01-01', end_date='2026-08-25'):
    print(f"Downloading historical data from {start_date} to {end_date}...")
    tickers = ['^NSEI', '^INDIAVIX', 'NIFTYBEES.NS', 'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'INFY.NS']
    raw_df = yf.download(tickers, start=start_date, end=end_date)
    
    close = raw_df['Close'].ffill().bfill()
    high = raw_df['High'].ffill().bfill()
    low = raw_df['Low'].ffill().bfill()
    open_p = raw_df['Open'].ffill().bfill()
    
    data = pd.DataFrame(index=close.index)
    data['NIFTY_Close'] = close['^NSEI']
    data['NIFTY_High'] = high['^NSEI']
    data['NIFTY_Low'] = low['^NSEI']
    data['NIFTY_Open'] = open_p['^NSEI']
    
    data['VIX'] = close['^INDIAVIX'] / 100.0
    data['NIFTYBEES'] = close['NIFTYBEES.NS']
    
    for stk in ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'INFY.NS']:
        clean_name = stk.replace('.NS', '')
        data[f'{clean_name}_Close'] = close[stk]
        data[f'{clean_name}_High'] = high[stk]
        data[f'{clean_name}_Low'] = low[stk]
        data[f'{clean_name}_Open'] = open_p[stk]
        
    data = data.dropna()
    print(f"Data successfully loaded. Total trading days: {len(data)}")
    return data

# ==========================================
# 5. STRATEGY IMPLEMENTATIONS
# ==========================================

# ------------------------------------------
# Strategy 1: Systematic Weekly Short Straddles / Strangles (25% SL per leg)
# ------------------------------------------
def backtest_short_straddle(df, initial_capital=100000.0):
    equity_curve = []
    trades = []
    
    lot_size = 50
    margin_per_lot = 85000.0
    r = 0.065
    
    dates = df.index
    i = 0
    current_cap = initial_capital
    
    while i < len(dates):
        entry_date = dates[i]
        
        if current_cap < margin_per_lot * 0.6:
            current_cap = max(0.0, current_cap * (1.0 + 0.05/252.0))
            equity_curve.append((entry_date, current_cap))
            i += 1
            continue
            
        S0 = df.loc[entry_date, 'NIFTY_Close']
        vix0 = df.loc[entry_date, 'VIX']
        
        expiry_idx = min(i + 4, len(dates) - 1)
        expiry_date = dates[expiry_idx]
        T0 = max((expiry_idx - i), 1) / 252.0
        
        K = round(S0 / 50.0) * 50.0
        
        c0 = bs_call(S0, K, T0, r, get_iv_skew(vix0, 'CE', 0.0))
        p0 = bs_put(S0, K, T0, r, get_iv_skew(vix0, 'PE', 0.0))
        
        c_sl = c0 * 1.25
        p_sl = p0 * 1.25
        
        entry_cost = calculate_costs('CE', c0, S0, lot_size, is_buy=False) + calculate_costs('PE', p0, S0, lot_size, is_buy=False)
        current_cap -= entry_cost
        
        call_stopped = False
        put_stopped = False
        c_exit_price = c0
        p_exit_price = p0
        
        for d_idx in range(i, expiry_idx + 1):
            curr_date = dates[d_idx]
            S_curr = df.loc[curr_date, 'NIFTY_Close']
            S_high = df.loc[curr_date, 'NIFTY_High']
            S_low = df.loc[curr_date, 'NIFTY_Low']
            vix_curr = df.loc[curr_date, 'VIX']
            
            rem_days = max(expiry_idx - d_idx, 0)
            T_curr = max(rem_days / 252.0, 0.001)
            
            c_peak = bs_call(S_high, K, T_curr, r, get_iv_skew(vix_curr, 'CE', max(0, (S_high-K)/K)))
            p_peak = bs_put(S_low, K, T_curr, r, get_iv_skew(vix_curr, 'PE', max(0, (K-S_low)/K)))
            
            if not call_stopped and c_peak >= c_sl:
                call_stopped = True
                c_exit_price = c_sl
                current_cap -= calculate_costs('CE', c_sl, S_curr, lot_size, is_buy=True)
                
            if not put_stopped and p_peak >= p_sl:
                put_stopped = True
                p_exit_price = p_sl
                current_cap -= calculate_costs('PE', p_sl, S_curr, lot_size, is_buy=True)
                
            if d_idx == expiry_idx:
                S_exp = df.loc[expiry_date, 'NIFTY_Close']
                if not call_stopped:
                    c_exit_price = max(0.0, S_exp - K)
                    current_cap -= calculate_costs('CE', c_exit_price, S_exp, lot_size, is_buy=True, is_exercise=(c_exit_price>0))
                if not put_stopped:
                    p_exit_price = max(0.0, K - S_exp)
                    current_cap -= calculate_costs('PE', p_exit_price, S_exp, lot_size, is_buy=True, is_exercise=(p_exit_price>0))
                
                net_pnl = ((c0 - c_exit_price) + (p0 - p_exit_price)) * lot_size
                current_cap += net_pnl
                trades.append({'entry_date': entry_date, 'exit_date': expiry_date, 'pnl': net_pnl})
                
            free_cash = max(0.0, current_cap - margin_per_lot)
            current_cap += free_cash * (0.05 / 252.0)
            equity_curve.append((curr_date, max(0.0, current_cap)))
            
        i = expiry_idx + 1

    eq_df = pd.DataFrame(equity_curve, columns=['Date', 'Capital']).set_index('Date')
    eq_df = eq_df[~eq_df.index.duplicated(keep='first')]
    return eq_df['Capital'], trades

# ------------------------------------------
# Strategy 2: Weekly Iron Condors (Defined Risk Option Selling)
# ------------------------------------------
def backtest_iron_condor(df, initial_capital=100000.0):
    equity_curve = []
    trades = []
    
    lot_size = 50
    num_lots = 2
    margin_per_lot = 22000.0
    r = 0.065
    
    dates = df.index
    i = 0
    current_cap = initial_capital
    
    while i < len(dates):
        entry_date = dates[i]
        
        if current_cap < margin_per_lot * num_lots * 0.5:
            current_cap = max(0.0, current_cap * (1.0 + 0.05/252.0))
            equity_curve.append((entry_date, current_cap))
            i += 1
            continue
            
        S0 = df.loc[entry_date, 'NIFTY_Close']
        vix0 = df.loc[entry_date, 'VIX']
        
        expiry_idx = min(i + 4, len(dates) - 1)
        expiry_date = dates[expiry_idx]
        T0 = max((expiry_idx - i), 1) / 252.0
        
        k_sc = round((S0 * 1.015) / 50.0) * 50.0
        k_lc = round((S0 * 1.030) / 50.0) * 50.0
        k_sp = round((S0 * 0.985) / 50.0) * 50.0
        k_lp = round((S0 * 0.970) / 50.0) * 50.0
        
        p_sc = bs_call(S0, k_sc, T0, r, get_iv_skew(vix0, 'CE', 0.015))
        p_lc = bs_call(S0, k_lc, T0, r, get_iv_skew(vix0, 'CE', 0.030))
        p_sp = bs_put(S0, k_sp, T0, r, get_iv_skew(vix0, 'PE', 0.015))
        p_lp = bs_put(S0, k_lp, T0, r, get_iv_skew(vix0, 'PE', 0.030))
        
        net_credit_per_share = max(0.0, (p_sc + p_sp) - (p_lc + p_lp))
        net_credit_total = net_credit_per_share * lot_size * num_lots
        
        cost_entry = (calculate_costs('CE', p_sc, S0, lot_size, False) +
                      calculate_costs('CE', p_lc, S0, lot_size, True) +
                      calculate_costs('PE', p_sp, S0, lot_size, False) +
                      calculate_costs('PE', p_lp, S0, lot_size, True)) * num_lots
        current_cap -= cost_entry
        
        for d_idx in range(i, expiry_idx + 1):
            curr_date = dates[d_idx]
            
            if d_idx == expiry_idx:
                S_exp = df.loc[expiry_date, 'NIFTY_Close']
                
                payoff_sc = max(0.0, S_exp - k_sc)
                payoff_lc = max(0.0, S_exp - k_lc)
                payoff_sp = max(0.0, k_sp - S_exp)
                payoff_lp = max(0.0, k_lp - S_exp)
                
                net_payoff_per_share = (payoff_sc - payoff_lc) + (payoff_sp - payoff_lp)
                net_pnl = (net_credit_per_share - net_payoff_per_share) * lot_size * num_lots
                
                cost_exit = (calculate_costs('CE', payoff_sc, S_exp, lot_size, True, is_exercise=(payoff_sc>0)) +
                            calculate_costs('CE', payoff_lc, S_exp, lot_size, False, is_exercise=(payoff_lc>0)) +
                            calculate_costs('PE', payoff_sp, S_exp, lot_size, True, is_exercise=(payoff_sp>0)) +
                            calculate_costs('PE', payoff_lp, S_exp, lot_size, False, is_exercise=(payoff_lp>0))) * num_lots
                
                current_cap += (net_pnl - cost_exit)
                trades.append({'entry_date': entry_date, 'exit_date': expiry_date, 'pnl': net_pnl - cost_exit})
                
            free_cash = max(0.0, current_cap - (margin_per_lot * num_lots))
            current_cap += free_cash * (0.05 / 252.0)
            equity_curve.append((curr_date, max(0.0, current_cap)))
            
        i = expiry_idx + 1

    eq_df = pd.DataFrame(equity_curve, columns=['Date', 'Capital']).set_index('Date')
    eq_df = eq_df[~eq_df.index.duplicated(keep='first')]
    return eq_df['Capital'], trades

# ------------------------------------------
# Strategy 3: Intraday 30-min Option Buying Momentum
# ------------------------------------------
def backtest_option_momentum(df, initial_capital=100000.0):
    current_cap = initial_capital
    equity_curve = []
    trades = []
    
    lot_size = 50
    r = 0.065
    
    for curr_date, row in df.iterrows():
        S_open = row['NIFTY_Open']
        S_high = row['NIFTY_High']
        S_low = row['NIFTY_Low']
        S_close = row['NIFTY_Close']
        vix = row['VIX']
        
        T = 2.0 / 252.0
        
        # Breakout triggers (> +0.6% or < -0.6% from Open)
        bullish_trigger = (S_high >= S_open * 1.006)
        bearish_trigger = (S_low <= S_open * 0.994)
        
        if bullish_trigger and not bearish_trigger:
            K = round(S_open / 50.0) * 50.0
            prem_entry = bs_call(S_open, K, T, r, get_iv_skew(vix, 'CE', 0.0))
            cost_entry = calculate_costs('CE', prem_entry, S_open, lot_size, is_buy=True)
            
            # Intraday momentum evaluation:
            # If day closed strong in breakout direction (S_close > S_open + 0.3%): Take Profit (25% gain)
            # Else (choppy or reversal day): Stop Loss (-20% loss on premium)
            if S_close >= S_open * 1.003:
                prem_exit = prem_entry * 1.25
            else:
                prem_exit = prem_entry * 0.80
                
            cost_exit = calculate_costs('CE', prem_exit, S_close, lot_size, is_buy=False)
            pnl = (prem_exit - prem_entry) * lot_size - (cost_entry + cost_exit)
            current_cap += pnl
            trades.append({'date': curr_date, 'type': 'CE_BUY', 'pnl': pnl})
            
        elif bearish_trigger and not bullish_trigger:
            K = round(S_open / 50.0) * 50.0
            prem_entry = bs_put(S_open, K, T, r, get_iv_skew(vix, 'PE', 0.0))
            cost_entry = calculate_costs('PE', prem_entry, S_open, lot_size, is_buy=True)
            
            if S_close <= S_open * 0.997:
                prem_exit = prem_entry * 1.25
            else:
                prem_exit = prem_entry * 0.80
                
            cost_exit = calculate_costs('PE', prem_exit, S_close, lot_size, is_buy=False)
            pnl = (prem_exit - prem_entry) * lot_size - (cost_entry + cost_exit)
            current_cap += pnl
            trades.append({'date': curr_date, 'type': 'PE_BUY', 'pnl': pnl})
            
        current_cap += current_cap * (0.05 / 252.0)
        equity_curve.append((curr_date, max(0.0, current_cap)))

    eq_df = pd.DataFrame(equity_curve, columns=['Date', 'Capital']).set_index('Date')
    eq_df = eq_df[~eq_df.index.duplicated(keep='first')]
    return eq_df['Capital'], trades

# ------------------------------------------
# Strategy 4: Systematic Covered Call Strategy (Nifty ETF + OTM Call Selling)
# ------------------------------------------
def backtest_covered_call(df, initial_capital=100000.0):
    etf_alloc = initial_capital * 0.82
    cash = initial_capital * 0.18
    
    first_date = df.index[0]
    p_etf0 = df.loc[first_date, 'NIFTYBEES']
    shares = etf_alloc / p_etf0
    
    equity_curve = []
    trades = []
    lot_size = 50
    r = 0.065
    
    dates = df.index
    i = 0
    
    while i < len(dates):
        entry_date = dates[i]
        S0 = df.loc[entry_date, 'NIFTY_Close']
        vix0 = df.loc[entry_date, 'VIX']
        
        expiry_idx = min(i + 14, len(dates) - 1)
        expiry_date = dates[expiry_idx]
        T0 = max((expiry_idx - i), 1) / 252.0
        
        K = round((S0 * 1.020) / 50.0) * 50.0
        prem0 = bs_call(S0, K, T0, r, get_iv_skew(vix0, 'CE', 0.020))
        
        cost_entry = calculate_costs('CE', prem0, S0, lot_size, is_buy=False)
        cash += (prem0 * lot_size) - cost_entry
        
        for d_idx in range(i, expiry_idx + 1):
            curr_date = dates[d_idx]
            p_etf_curr = df.loc[curr_date, 'NIFTYBEES']
            
            cash += (shares * p_etf_curr) * (0.012 / 252.0)
            
            if d_idx == expiry_idx:
                S_exp = df.loc[expiry_date, 'NIFTY_Close']
                call_payoff = max(0.0, S_exp - K)
                cost_exit = calculate_costs('CE', call_payoff, S_exp, lot_size, is_buy=True, is_exercise=(call_payoff>0))
                
                cash -= (call_payoff * lot_size) + cost_exit
                trades.append({'entry_date': entry_date, 'exit_date': expiry_date, 'pnl': (prem0 - call_payoff)*lot_size - (cost_entry + cost_exit)})
                
            tot_cap = (shares * p_etf_curr) + cash
            equity_curve.append((curr_date, max(0.0, tot_cap)))
            
        i = expiry_idx + 1

    eq_df = pd.DataFrame(equity_curve, columns=['Date', 'Capital']).set_index('Date')
    eq_df = eq_df[~eq_df.index.duplicated(keep='first')]
    return eq_df['Capital'], trades

# ------------------------------------------
# Strategy 5: Cash Secured Puts on Top Quality Stocks
# ------------------------------------------
def backtest_cash_secured_puts(df, initial_capital=100000.0):
    cash = initial_capital
    equity_curve = []
    trades = []
    
    stocks = ['RELIANCE', 'TCS', 'HDFCBANK', 'ICICIBANK', 'INFY']
    r = 0.065
    
    dates = df.index
    i = 0
    
    while i < len(dates):
        entry_date = dates[i]
        
        expiry_idx = min(i + 14, len(dates) - 1)
        expiry_date = dates[expiry_idx]
        T0 = max((expiry_idx - i), 1) / 252.0
        
        best_stk = 'RELIANCE'
        highest_mom = -999
        if i >= 20:
            for stk in stocks:
                sma20 = df.loc[dates[i-20:i], f'{stk}_Close'].mean()
                curr_p = df.loc[entry_date, f'{stk}_Close']
                mom = (curr_p - sma20) / sma20
                if mom > highest_mom:
                    highest_mom = mom
                    best_stk = stk
                    
        S0 = df.loc[entry_date, f'{best_stk}_Close']
        vix0 = df.loc[entry_date, 'VIX']
        
        lot_size = max(int(cash * 0.75 / S0), 10)
        
        K = round(S0 * 0.970, 1)
        prem0 = bs_put(S0, K, T0, r, get_iv_skew(vix0, 'PE', 0.030))
        
        cost_entry = calculate_costs('PE', prem0, S0, lot_size, is_buy=False)
        cash += (prem0 * lot_size) - cost_entry
        
        for d_idx in range(i, expiry_idx + 1):
            curr_date = dates[d_idx]
            
            cash += cash * (0.060 / 252.0)
            
            if d_idx == expiry_idx:
                S_exp = df.loc[expiry_date, f'{best_stk}_Close']
                put_payoff = max(0.0, K - S_exp)
                cost_exit = calculate_costs('PE', put_payoff, S_exp, lot_size, is_buy=True, is_exercise=(put_payoff>0))
                
                cash -= (put_payoff * lot_size) + cost_exit
                trades.append({'entry_date': entry_date, 'exit_date': expiry_date, 'stock': best_stk, 'pnl': (prem0 - put_payoff)*lot_size - (cost_entry + cost_exit)})
                
            equity_curve.append((curr_date, max(0.0, cash)))
            
        i = expiry_idx + 1

    eq_df = pd.DataFrame(equity_curve, columns=['Date', 'Capital']).set_index('Date')
    eq_df = eq_df[~eq_df.index.duplicated(keep='first')]
    return eq_df['Capital'], trades

# ------------------------------------------
# Benchmark: Nifty 50 Buy & Hold
# ------------------------------------------
def backtest_nifty_benchmark(df, initial_capital=100000.0):
    first_price = df['NIFTY_Close'].iloc[0]
    shares = initial_capital / first_price
    equity = df['NIFTY_Close'] * shares
    return equity, []

# ==========================================
# 6. MAIN EXECUTION & REPORT GENERATION
# ==========================================

def main():
    print("==================================================")
    print(" INDIAN MARKET OPTIONS TRADING STRATEGIES BACKTEST ")
    print(" Period: 2021 to 2026 | Initial Capital: ₹1,00,000 ")
    print("==================================================")
    
    df = load_market_data()
    
    strategies = {
        'Nifty Buy & Hold (Benchmark)': backtest_nifty_benchmark,
        'Short Straddle (25% SL)': backtest_short_straddle,
        'Iron Condor (Defined Risk)': backtest_iron_condor,
        'Intraday Momentum Buying': backtest_option_momentum,
        'Covered Call (Nifty ETF)': backtest_covered_call,
        'Cash Secured Puts (Blue Chips)': backtest_cash_secured_puts
    }
    
    results = {}
    
    for name, strat_func in strategies.items():
        print(f"\nRunning backtest for: {name}...")
        eq, trades = strat_func(df)
        metrics = calculate_performance_metrics(eq, trades)
        results[name] = metrics
        
        print(f" -> Final Capital: ₹{metrics['Final Capital (₹)']:,} | CAGR: {metrics['CAGR (%)']}% | Max DD: {metrics['Max Drawdown (%)']}% | Sharpe: {metrics['Sharpe Ratio']}")

    res_df = pd.DataFrame(results).T
    print("\n==================================================")
    print("              SUMMARY RESULTS TABLE               ")
    print("==================================================")
    print(res_df.to_string())
    
    os.makedirs('results', exist_ok=True)
    res_df.to_csv('results/options_strategies_backtest_results.csv')
    
    with open('results/options_strategies_performance.json', 'w') as f:
        json.dump(results, f, indent=4)
        
    print("\nResults successfully saved to 'results/options_strategies_backtest_results.csv' and 'results/options_strategies_performance.json'.")

if __name__ == '__main__':
    main()
