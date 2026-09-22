import sqlite3
import pandas as pd
import numpy as np
import time
import os

# ==========================================
# CONFIGURATION & PARAMETERS
# ==========================================
DB_PATH = "data/nse_stocks_all_years.db"
START_DATE = "2021-01-01"
END_DATE = "2026-08-24"
INITIAL_CAPITAL = 100000.0  # ₹1 Lakh
ANNUAL_MTF_INTEREST_RATE = 0.12  # 12% p.a. MTF interest cost
FRICTION_PER_TRADE = 0.0025  # 0.25% (Brokerage + STT + DP + Slippage)
RISK_FREE_RATE = 0.06  # 6.0% p.a. risk-free rate for Sharpe/Sortino

# Minimum liquidity requirement (Average turnover >= 25 Lakhs)
MIN_AVG_TURNOVER = 2500000.0

def load_data():
    print("Loading data from SQLite database...", flush=True)
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    
    df = pd.read_sql_query(
        "SELECT symbol, date, open, high, low, close, volume FROM daily_prices WHERE date >= '2020-01-01' AND close IS NOT NULL",
        conn
    )
    conn.close()
    print(f"Loaded {len(df):,} price records in {time.time() - t0:.2f}s", flush=True)
    
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['symbol', 'date']).reset_index(drop=True)
    
    nifty_df = df[df['symbol'] == 'NIFTY50'].set_index('date')
    stock_df = df[df['symbol'] != 'NIFTY50']
    
    # Filter stocks by average turnover >= MIN_AVG_TURNOVER
    stock_df['turnover'] = stock_df['close'] * stock_df['volume']
    avg_turnover = stock_df.groupby('symbol')['turnover'].mean()
    valid_symbols = avg_turnover[avg_turnover >= MIN_AVG_TURNOVER].index
    stock_df = stock_df[stock_df['symbol'].isin(valid_symbols)]
    
    print(f"Filtered to {len(valid_symbols)} liquid stocks (avg turnover >= ₹25L)", flush=True)
    
    print("Pivoting data matrices...", flush=True)
    close_pivot = stock_df.pivot(index='date', columns='symbol', values='close').ffill()
    high_pivot = stock_df.pivot(index='date', columns='symbol', values='high').ffill()
    low_pivot = stock_df.pivot(index='date', columns='symbol', values='low').ffill()
    volume_pivot = stock_df.pivot(index='date', columns='symbol', values='volume').fillna(0)
    
    nifty_close = nifty_df['close'].reindex(close_pivot.index).ffill()
    
    return close_pivot, high_pivot, low_pivot, volume_pivot, nifty_close

def compute_indicators(close_pivot, high_pivot, low_pivot, nifty_close):
    print("Computing technical indicators and returns matrices...", flush=True)
    
    ema_20 = close_pivot.ewm(span=20, adjust=False).mean()
    sma_50 = close_pivot.rolling(window=50).mean()
    sma_150 = close_pivot.rolling(window=150).mean()
    sma_200 = close_pivot.rolling(window=200).mean()
    
    high_52w = high_pivot.rolling(window=252, min_periods=100).max()
    low_52w = low_pivot.rolling(window=252, min_periods=100).min()
    
    ret_1m = close_pivot.pct_change(21)
    ret_3m = close_pivot.pct_change(63)
    ret_6m = close_pivot.pct_change(126)
    ret_12m = close_pivot.pct_change(252)
    
    nifty_sma_200 = nifty_close.rolling(window=200).mean()
    nifty_ret_6m = nifty_close.pct_change(126)
    
    rs_nifty = ret_6m.sub(nifty_ret_6m, axis=0)
    
    delta = close_pivot.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / (avg_loss + 1e-8)
    rsi_14 = 100 - (100 / (1 + rs))
    
    daily_rets = close_pivot.pct_change()
    std_10d = daily_rets.rolling(10).std()
    std_30d = daily_rets.rolling(30).std()
    
    indicators = {
        'ema_20': ema_20,
        'sma_50': sma_50,
        'sma_150': sma_150,
        'sma_200': sma_200,
        'high_52w': high_52w,
        'low_52w': low_52w,
        'ret_1m': ret_1m,
        'ret_3m': ret_3m,
        'ret_6m': ret_6m,
        'ret_12m': ret_12m,
        'rs_nifty': rs_nifty,
        'rsi_14': rsi_14,
        'std_10d': std_10d,
        'std_30d': std_30d,
        'nifty_sma_200': nifty_sma_200,
        'nifty_ret_6m': nifty_ret_6m
    }
    return indicators

def precompute_rankings(strategy_type, close_pivot, high_pivot, low_pivot, nifty_close, indicators):
    dates = close_pivot.index
    symbols = close_pivot.columns
    
    c_arr = close_pivot.values
    h52_arr = indicators['high_52w'].values
    l52_arr = indicators['low_52w'].values
    s50_arr = indicators['sma_50'].values
    s150_arr = indicators['sma_150'].values
    s200_arr = indicators['sma_200'].values
    e20_arr = indicators['ema_20'].values
    r1m_arr = indicators['ret_1m'].values
    r3m_arr = indicators['ret_3m'].values
    r6m_arr = indicators['ret_6m'].values
    rsi_arr = indicators['rsi_14'].values
    rs_n_arr = indicators['rs_nifty'].values
    std10_arr = indicators['std_10d'].values
    std30_arr = indicators['std_30d'].values
    l_arr = low_pivot.values

    nifty_c_arr = nifty_close.values
    nifty_s200_arr = indicators['nifty_sma_200'].values

    ranked_dict = {}

    for t_idx, dt in enumerate(dates):
        if dt < pd.to_datetime("2021-01-01"):
            continue
            
        c = c_arr[t_idx]
        valid = ~np.isnan(c) & (c > 0)
        if not np.any(valid):
            ranked_dict[dt] = []
            continue
            
        if strategy_type == "52W_High":
            h52 = h52_arr[t_idx]
            s50 = s50_arr[t_idx]
            s200 = s200_arr[t_idx]
            r3m = r3m_arr[t_idx]
            mask = valid & (c >= 0.97 * h52) & (c > s50) & (s50 > s200)
            if not np.any(mask):
                ranked_dict[dt] = []
                continue
            idx = np.where(mask)[0]
            scores = (c[idx] / h52[idx]) * 0.5 + np.nan_to_num(r3m[idx]) * 0.5
            sorted_sub_idx = idx[np.argsort(-scores)]
            ranked_dict[dt] = symbols[sorted_sub_idx].tolist()

        elif strategy_type == "MultiFactor":
            rsi = rsi_arr[t_idx]
            s200 = s200_arr[t_idx]
            r1m = r1m_arr[t_idx]
            r3m = r3m_arr[t_idx]
            r6m = r6m_arr[t_idx]
            mask = valid & (rsi >= 45) & (rsi <= 75) & (c > s200)
            if not np.any(mask):
                ranked_dict[dt] = []
                continue
            idx = np.where(mask)[0]
            
            def safe_z(arr):
                sub = arr[idx]
                std = np.nanstd(sub)
                mean = np.nanmean(sub)
                return (sub - mean) / (std + 1e-6) if std > 0 else np.zeros_like(sub)

            z1 = safe_z(r1m)
            z3 = safe_z(r3m)
            z6 = safe_z(r6m)
            scores = z1 * 0.25 + z3 * 0.35 + z6 * 0.40
            sorted_sub_idx = idx[np.argsort(-scores)]
            ranked_dict[dt] = symbols[sorted_sub_idx].tolist()

        elif strategy_type == "Minervini_VCP":
            s50 = s50_arr[t_idx]
            s150 = s150_arr[t_idx]
            s200 = s200_arr[t_idx]
            h52 = h52_arr[t_idx]
            l52 = l52_arr[t_idx]
            std10 = std10_arr[t_idx]
            std30 = std30_arr[t_idx]
            r3m = r3m_arr[t_idx]
            
            mask = valid & (c > s150) & (c > s200) & (s150 > s200) & (c > s50) & (c >= 0.85 * h52) & (c >= 1.25 * l52) & (std10 < std30)
            if not np.any(mask):
                mask = valid & (c > s200) & (c >= 0.85 * h52) & (c > s50)
            if not np.any(mask):
                ranked_dict[dt] = []
                continue
            idx = np.where(mask)[0]
            scores = np.nan_to_num(r3m[idx])
            sorted_sub_idx = idx[np.argsort(-scores)]
            ranked_dict[dt] = symbols[sorted_sub_idx].tolist()

        elif strategy_type == "Dual_Mom":
            nc = nifty_c_arr[t_idx]
            ns200 = nifty_s200_arr[t_idx]
            if nc < ns200:
                ranked_dict[dt] = []
                continue
            r6m = r6m_arr[t_idx]
            rs_n = rs_n_arr[t_idx]
            s200 = s200_arr[t_idx]
            mask = valid & (r6m > 0) & (rs_n > 0) & (c > s200)
            if not np.any(mask):
                ranked_dict[dt] = []
                continue
            idx = np.where(mask)[0]
            scores = np.nan_to_num(rs_n[idx])
            sorted_sub_idx = idx[np.argsort(-scores)]
            ranked_dict[dt] = symbols[sorted_sub_idx].tolist()

        elif strategy_type == "EMA_Pullback":
            s50 = s50_arr[t_idx]
            s200 = s200_arr[t_idx]
            e20 = e20_arr[t_idx]
            low = l_arr[t_idx]
            r1m = r1m_arr[t_idx]
            mask = valid & (c > s200) & (e20 > s50) & (low <= e20 * 1.02) & (c >= e20)
            if not np.any(mask):
                ranked_dict[dt] = []
                continue
            idx = np.where(mask)[0]
            scores = np.nan_to_num(r1m[idx])
            sorted_sub_idx = idx[np.argsort(-scores)]
            ranked_dict[dt] = symbols[sorted_sub_idx].tolist()

    return ranked_dict

def run_backtest(strategy_name, ranked_dict, num_stocks, leverage_ratio, close_pivot, rebal_freq_days=14, stop_loss_pct=None):
    all_dates = close_pivot.index
    sim_dates = [d for d in all_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]
    rebal_dates = set(sim_dates[::rebal_freq_days])
    
    equity_nav = INITIAL_CAPITAL
    borrowed_debt = 0.0
    cash = INITIAL_CAPITAL
    
    holdings = {}  # {symbol: {'shares': x, 'entry_price': y}}
    equity_curve = []
    closed_trades = []  # track individual trade PnLs
    
    daily_mtf_rate = ANNUAL_MTF_INTEREST_RATE / 365.0
    
    for dt in sim_dates:
        # 1. Intra-day Stop Loss Check (if enabled for risk-managed MTF)
        if stop_loss_pct is not None and len(holdings) > 0:
            for sym in list(holdings.keys()):
                p = close_pivot.loc[dt, sym] if (dt in close_pivot.index and pd.notna(close_pivot.loc[dt, sym])) else holdings[sym]['entry_price']
                entry_p = holdings[sym]['entry_price']
                if p <= entry_p * (1.0 - stop_loss_pct):
                    # Trigger Stop Loss exit
                    shares = holdings[sym]['shares']
                    sell_val = shares * p
                    cash += sell_val * (1.0 - FRICTION_PER_TRADE)
                    pnl = (p - entry_p) * shares - (sell_val * FRICTION_PER_TRADE)
                    closed_trades.append({'symbol': sym, 'pnl': pnl, 'return': (p / entry_p) - 1.0})
                    del holdings[sym]

        # 2. Holdings valuation
        holdings_val = 0.0
        for sym, data in list(holdings.items()):
            p = close_pivot.loc[dt, sym] if (dt in close_pivot.index and pd.notna(close_pivot.loc[dt, sym])) else data['entry_price']
            holdings_val += data['shares'] * p
            
        # 3. MTF Daily Interest Cost
        interest_charge = borrowed_debt * daily_mtf_rate
        cash -= interest_charge
        
        # Current NAV before rebalance
        equity_nav = cash + holdings_val
        
        # Margin Call Safety Guard (Liquidation Guard)
        if leverage_ratio > 1.0 and holdings_val > 0:
            margin_ratio = equity_nav / holdings_val
            if margin_ratio < 0.15 or equity_nav <= 500.0:  # Force liquidation if margin falls below 15%
                for sym, data in list(holdings.items()):
                    p = close_pivot.loc[dt, sym] if (dt in close_pivot.index and pd.notna(close_pivot.loc[dt, sym])) else data['entry_price']
                    sell_val = data['shares'] * p
                    cash += sell_val * (1.0 - FRICTION_PER_TRADE)
                    pnl = (p - data['entry_price']) * data['shares']
                    closed_trades.append({'symbol': sym, 'pnl': pnl, 'return': (p / data['entry_price']) - 1.0})
                holdings = {}
                borrowed_debt = 0.0
                holdings_val = 0.0
                equity_nav = max(cash, 0.0)

        # 4. Rebalance Execution
        if dt in rebal_dates and equity_nav > 500.0:
            target_candidates = ranked_dict.get(dt, [])
            target_symbols = target_candidates[:num_stocks]
            
            target_portfolio_val = equity_nav * leverage_ratio
            
            if len(target_symbols) > 0:
                target_per_stock = target_portfolio_val / len(target_symbols)
                
                # Sell dropped stocks
                for sym in list(holdings.keys()):
                    if sym not in target_symbols:
                        p = close_pivot.loc[dt, sym]
                        data = holdings[sym]
                        sell_val = data['shares'] * p
                        cash += sell_val * (1.0 - FRICTION_PER_TRADE)
                        pnl = (p - data['entry_price']) * data['shares'] - (sell_val * FRICTION_PER_TRADE)
                        closed_trades.append({'symbol': sym, 'pnl': pnl, 'return': (p / data['entry_price']) - 1.0})
                        del holdings[sym]
                
                # Buy or adjust target stocks
                for sym in target_symbols:
                    p = close_pivot.loc[dt, sym]
                    if p <= 0 or pd.isna(p):
                        continue
                    current_shares = holdings[sym]['shares'] if sym in holdings else 0.0
                    current_val = current_shares * p
                    diff_val = target_per_stock - current_val
                    
                    if diff_val > 0:
                        add_val = diff_val * (1.0 - FRICTION_PER_TRADE)
                        add_shares = add_val / p
                        if sym in holdings:
                            holdings[sym]['shares'] += add_shares
                        else:
                            holdings[sym] = {'shares': add_shares, 'entry_price': p}
                        cash -= diff_val
                    elif diff_val < 0:
                        trim_val = abs(diff_val)
                        rem_shares = (trim_val * (1.0 - FRICTION_PER_TRADE)) / p
                        holdings[sym]['shares'] = max(holdings[sym]['shares'] - rem_shares, 0)
                        cash += trim_val * (1.0 - FRICTION_PER_TRADE)

                holdings_val = sum([data['shares'] * close_pivot.loc[dt, sym] for sym, data in holdings.items()])
                borrowed_debt = max(holdings_val - cash, 0.0) if leverage_ratio > 1.0 else 0.0
            else:
                # Cash regime
                for sym, data in list(holdings.items()):
                    p = close_pivot.loc[dt, sym] if pd.notna(close_pivot.loc[dt, sym]) else data['entry_price']
                    sell_val = data['shares'] * p
                    cash += sell_val * (1.0 - FRICTION_PER_TRADE)
                    pnl = (p - data['entry_price']) * data['shares']
                    closed_trades.append({'symbol': sym, 'pnl': pnl, 'return': (p / data['entry_price']) - 1.0})
                holdings = {}
                borrowed_debt = 0.0
                holdings_val = 0.0

        equity_nav = cash + holdings_val - borrowed_debt
        equity_curve.append({'date': dt, 'nav': max(equity_nav, 0.0)})

    eq_df = pd.DataFrame(equity_curve).set_index('date')
    return calculate_metrics(eq_df, closed_trades, INITIAL_CAPITAL)

def run_nifty_benchmark(nifty_close):
    all_dates = nifty_close.index
    sim_dates = [d for d in all_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]
    nifty_sub = nifty_close.reindex(sim_dates).ffill()
    
    start_val = nifty_sub.iloc[0]
    nav_series = INITIAL_CAPITAL * (nifty_sub / start_val)
    eq_df = pd.DataFrame({'nav': nav_series}, index=sim_dates)
    return calculate_metrics(eq_df, [], INITIAL_CAPITAL)

def calculate_metrics(eq_df, closed_trades, initial_capital):
    nav = eq_df['nav']
    final_capital = nav.iloc[-1]
    
    total_days = (nav.index[-1] - nav.index[0]).days
    years = total_days / 365.25
    cagr = ((final_capital / initial_capital) ** (1.0 / years) - 1.0) * 100.0 if final_capital > 0 else -100.0
    
    # Max Drawdown %
    peak = nav.cummax()
    drawdown = np.where(peak > 0, (nav - peak) / peak, 0.0)
    max_dd = np.min(drawdown) * 100.0
    
    # Daily Returns & Volatility
    daily_rets = nav.pct_change().dropna()
    rf_daily = RISK_FREE_RATE / 252.0
    excess_rets = daily_rets - rf_daily
    
    std_dev = daily_rets.std()
    sharpe = (excess_rets.mean() / (std_dev + 1e-8)) * np.sqrt(252) if (std_dev > 0 and final_capital > 0) else 0.0
    
    downside_rets = daily_rets[daily_rets < rf_daily] - rf_daily
    downside_std = np.sqrt(np.mean(downside_rets**2)) if len(downside_rets) > 0 else 1e-6
    sortino = (excess_rets.mean() / (downside_std + 1e-8)) * np.sqrt(252) if (downside_std > 0 and final_capital > 0) else 0.0
    
    # Win Rate & Profit Factor
    if len(closed_trades) >= 5:
        pnls = [t['pnl'] for t in closed_trades]
        wins = [p for p in pnls if p > 0]
        losses = [abs(p) for p in pnls if p < 0]
        win_rate = (len(wins) / len(pnls)) * 100.0 if len(pnls) > 0 else 0.0
        profit_factor = (sum(wins) / sum(losses)) if sum(losses) > 0 else (99.0 if sum(wins) > 0 else 1.0)
    else:
        # Fallback to 14-day holding period returns
        period_rets = nav.pct_change(14).dropna()
        wins = period_rets[period_rets > 0]
        losses = period_rets[period_rets < 0]
        win_rate = (len(wins) / len(period_rets)) * 100.0 if len(period_rets) > 0 else 0.0
        profit_factor = (wins.sum() / abs(losses.sum())) if abs(losses.sum()) > 0 else 1.0

    calmar = (cagr / abs(max_dd)) if (max_dd != 0 and not np.isnan(max_dd)) else 0.0
    
    return {
        'Final Capital (₹)': round(final_capital, 2),
        'CAGR (%)': round(cagr, 2),
        'Max Drawdown (%)': round(max_dd, 2),
        'Win Rate (%)': round(win_rate, 2),
        'Sharpe Ratio': round(sharpe, 2),
        'Sortino Ratio': round(sortino, 2),
        'Profit Factor': round(profit_factor, 2),
        'Calmar Ratio': round(calmar, 2)
    }

def main():
    print("=" * 80, flush=True)
    print("      INDIAN EQUITY SWING & MTF LEVERAGE STRATEGIES BACKTEST (2021-2026)      ", flush=True)
    print("=" * 80, flush=True)
    
    close_pivot, high_pivot, low_pivot, volume_pivot, nifty_close = load_data()
    indicators = compute_indicators(close_pivot, high_pivot, low_pivot, nifty_close)
    
    strategy_types = ["52W_High", "MultiFactor", "Minervini_VCP", "Dual_Mom", "EMA_Pullback"]
    precomputed_rankings = {}
    print("\nPrecomputing stock rankings for fast strategy execution...", flush=True)
    for st in strategy_types:
        t0 = time.time()
        precomputed_rankings[st] = precompute_rankings(st, close_pivot, high_pivot, low_pivot, nifty_close, indicators)
        print(f"Precomputed rankings for {st:<15} in {time.time()-t0:.2f}s", flush=True)
        
    strategies_config = [
        # (Strategy Name, Key, Num Stocks, Leverage, Stop Loss)
        ("52W High Breakout (10-Stock, 1x)", "52W_High", 10, 1.0, None),
        ("52W High Breakout (5-Stock Concentrated, 1x)", "52W_High", 5, 1.0, None),
        ("52W High Breakout (15-Stock Diversified, 1x)", "52W_High", 15, 1.0, None),
        
        ("Multi-Factor Momentum (10-Stock, 1x)", "MultiFactor", 10, 1.0, None),
        ("Multi-Factor Momentum (5-Stock Concentrated, 1x)", "MultiFactor", 5, 1.0, None),
        ("Multi-Factor Momentum (15-Stock Diversified, 1x)", "MultiFactor", 15, 1.0, None),
        
        ("Minervini VCP (10-Stock, 1x)", "Minervini_VCP", 10, 1.0, None),
        ("Minervini VCP (5-Stock Concentrated, 1x)", "Minervini_VCP", 5, 1.0, None),
        ("Minervini VCP (15-Stock Diversified, 1x)", "Minervini_VCP", 15, 1.0, None),
        
        ("Dual Momentum (10-Stock, 1x)", "Dual_Mom", 10, 1.0, None),
        ("Dual Momentum (5-Stock Concentrated, 1x)", "Dual_Mom", 5, 1.0, None),
        ("Dual Momentum (15-Stock Diversified, 1x)", "Dual_Mom", 15, 1.0, None),
        
        ("EMA Pullback Swing (10-Stock, 1x)", "EMA_Pullback", 10, 1.0, None),
        
        ("MTF 2x Multi-Factor Momentum (Unhedged, 12% Interest)", "MultiFactor", 10, 2.0, None),
        ("MTF 2x 52W High Breakout (Unhedged, 12% Interest)", "52W_High", 10, 2.0, None),
        ("MTF 2x Multi-Factor Momentum (8% Stop Loss, 12% Interest)", "MultiFactor", 10, 2.0, 0.08),
        
        ("MTF 3x Multi-Factor Momentum (Unhedged, 12% Interest)", "MultiFactor", 10, 3.0, None),
        ("MTF 3x Multi-Factor Momentum (8% Stop Loss, 12% Interest)", "MultiFactor", 10, 3.0, 0.08),
    ]
    
    results = []
    
    print("\nRunning backtests across 19 strategy variations...\n", flush=True)
    for name, strat_key, n_stocks, lev, sl_pct in strategies_config:
        t_s = time.time()
        res = run_backtest(name, precomputed_rankings[strat_key], n_stocks, lev, close_pivot, stop_loss_pct=sl_pct)
        res['Strategy Name'] = name
        res['Leverage'] = f"{lev}x"
        res['Portfolio Size'] = f"{n_stocks} Stocks"
        results.append(res)
        print(f"[{time.time()-t_s:.2f}s] Completed: {name:<58} -> Final: ₹{res['Final Capital (₹)']:,.2f} | CAGR: {res['CAGR (%)']}% | MaxDD: {res['Max Drawdown (%)']}% | WinRate: {res['Win Rate (%)']}% | Sharpe: {res['Sharpe Ratio']}", flush=True)
        
    bench_res = run_nifty_benchmark(nifty_close)
    bench_res['Strategy Name'] = "Nifty 50 Benchmark (Buy & Hold)"
    bench_res['Leverage'] = "1.0x"
    bench_res['Portfolio Size'] = "50 Stocks (Index)"
    results.append(bench_res)
    print(f"Completed: Nifty 50 Benchmark                                     -> Final: ₹{bench_res['Final Capital (₹)']:,.2f} | CAGR: {bench_res['CAGR (%)']}% | MaxDD: {bench_res['Max Drawdown (%)']}% | WinRate: {bench_res['Win Rate (%)']}% | Sharpe: {bench_res['Sharpe Ratio']}", flush=True)
    
    results_df = pd.DataFrame(results)
    
    os.makedirs("data", exist_ok=True)
    results_df.to_csv("data/equity_and_mtf_backtest_results.csv", index=False)
    print("\nResults successfully saved to data/equity_and_mtf_backtest_results.csv", flush=True)
    
    print("\n" + "=" * 110, flush=True)
    print("                                      SUMMARY RESULTS MATRIX                                      ", flush=True)
    print("=" * 110, flush=True)
    cols = ['Strategy Name', 'Final Capital (₹)', 'CAGR (%)', 'Max Drawdown (%)', 'Win Rate (%)', 'Sharpe Ratio', 'Sortino Ratio', 'Profit Factor', 'Calmar Ratio']
    print(results_df[cols].to_markdown(index=False), flush=True)

if __name__ == "__main__":
    main()
