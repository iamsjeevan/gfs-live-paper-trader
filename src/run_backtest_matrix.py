import sqlite3
import pandas as pd
import numpy as np
import datetime

DB_PATH = "data/nse_stocks_all_years.db"
START_DATE = "2019-01-01"
END_DATE = "2026-08-01"

# Financial Realism Parameters
INITIAL_CAPITAL = 100000.0        # ₹1 Lakh initial capital
ANNUAL_SIP_ADDITION = 100000.0   # ₹1 Lakh added every year (SIP)
BASE_TRANSACTION_COST = 0.001    # 0.1% STT, Brokerage & GST per trade

# Dynamic Slippage Model
LIQUID_SLIPPAGE = 0.002           # 0.2% slippage for MktCap >= 500 Cr
ILLIQUID_SLIPPAGE = 0.015         # 1.5% high slippage for micro-caps / illiquid stocks

def load_data():
    print("[BACKTEST SETUP] Loading prices and fundamental data from SQLite...", flush=True)
    conn = sqlite3.connect(DB_PATH)
    
    prices_df = pd.read_sql_query("""
    SELECT symbol, date, close, volume, sma_50, sma_200, high_52w 
    FROM daily_prices 
    WHERE date >= '2018-01-01'
    """, conn)
    
    comp_df = pd.read_sql_query("SELECT symbol, company_name, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol, year, roe, debt_equity, net_margin FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol, year, total_revenue, net_profit FROM financial_income_statement", conn)
    
    conn.close()

    prices_df['date'] = pd.to_datetime(prices_df['date'])
    prices_df = prices_df.sort_values(['symbol', 'date']).reset_index(drop=True)

    print(f"[DATA LOADED] Prices: {len(prices_df):,} rows | Stocks: {prices_df['symbol'].nunique()}", flush=True)
    return prices_df, comp_df, ratios_df, pl_df

def compute_monthly_dates(prices_df):
    dates = sorted(prices_df['date'].unique())
    dates_df = pd.DataFrame({'date': dates})
    dates_df['year_month'] = dates_df['date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('year_month')['date'].min().tolist()
    
    start_dt = pd.to_datetime(START_DATE)
    end_dt = pd.to_datetime(END_DATE)
    monthly_dates = [d for d in monthly_dates if start_dt <= d <= end_dt]
    return monthly_dates

def get_point_in_time_fundamentals(rebalance_date, ratios_df, pl_df):
    target_year = rebalance_date.year - 1
    r_sub = ratios_df[ratios_df['year'] == target_year].copy()
    p_sub = pl_df[pl_df['year'] == target_year].copy()
    merged = pd.merge(r_sub, p_sub[['symbol', 'year', 'net_profit']], on=['symbol', 'year'], how='inner')
    return merged

def get_stock_slippage(symbol, mkt_cap_dict):
    mcap = mkt_cap_dict.get(symbol, 0)
    if mcap and mcap >= 500.0:
        return LIQUID_SLIPPAGE + BASE_TRANSACTION_COST
    else:
        return ILLIQUID_SLIPPAGE + BASE_TRANSACTION_COST

def run_single_backtest(config, prices_df, comp_df, ratios_df, pl_df, monthly_dates, detailed_logging=False):
    num_stocks = config['num_stocks']
    fundamental_filter = config.get('fundamental_filter', False)
    liquidity_filter = config.get('liquidity_filter', False)
    trailing_stop_loss = config.get('trailing_stop_loss', None)
    take_profit_pct = config.get('take_profit', None)
    fixed_stop_loss = config.get('fixed_stop_loss', None)

    mkt_cap_dict = dict(zip(comp_df['symbol'], comp_df['market_cap']))

    current_cash = INITIAL_CAPITAL
    total_invested_capital = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}  # {symbol: {'entry_price': p, 'peak_price': p, 'shares': s, 'entry_date': d}}
    
    completed_trades = []
    monthly_logs = []

    price_pivot = prices_df.pivot(index='date', columns='symbol', values='close')
    high_52w_pivot = prices_df.pivot(index='date', columns='symbol', values='high_52w')
    sma_50_pivot = prices_df.pivot(index='date', columns='symbol', values='sma_50')
    mom_3m_pivot = price_pivot.pct_change(63)

    last_sip_year = None

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]
        next_rebal_date = monthly_dates[i + 1]

        # Annual SIP Cash Addition
        sip_added_this_month = False
        if last_sip_year is None or rebal_date.year > last_sip_year:
            if last_sip_year is not None:
                current_cash += ANNUAL_SIP_ADDITION
                total_invested_capital += ANNUAL_SIP_ADDITION
                sip_added_this_month = True
            last_sip_year = rebal_date.year

        # Evaluate portfolio value before rebalance
        portfolio_val_before = current_cash
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            portfolio_val_before += pos['shares'] * p

        equity_curve.append({'date': rebal_date, 'portfolio_value': portfolio_val_before, 'invested_capital': total_invested_capital})

        if rebal_date not in mom_3m_pivot.index:
            continue

        available_symbols = price_pivot.columns.tolist()

        if liquidity_filter:
            available_symbols = [s for s in available_symbols if mkt_cap_dict.get(s, 0) >= 500.0]

        if fundamental_filter:
            pit_fund = get_point_in_time_fundamentals(rebal_date, ratios_df, pl_df)
            qualifying_fund_syms = set(pit_fund[
                (pit_fund['roe'] >= 10.0) & 
                (pit_fund['debt_equity'] <= 1.5) & 
                (pit_fund['net_profit'] > 0)
            ]['symbol'])
            available_symbols = [s for s in available_symbols if s in qualifying_fund_syms]

        # Rank Momentum Leaderboard
        mom_scores = {}
        for s in available_symbols:
            if s in mom_3m_pivot.columns:
                m = mom_3m_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                h52 = high_52w_pivot.loc[rebal_date, s] if s in high_52w_pivot.columns else None
                s50 = sma_50_pivot.loc[rebal_date, s] if s in sma_50_pivot.columns else None

                if pd.notna(m) and pd.notna(p) and p > 0:
                    if s50 is not None and pd.notna(s50) and p < s50:
                        continue
                    
                    prox = (p / h52) if (h52 and pd.notna(h52) and h52 > 0) else 0.8
                    score = m * 0.7 + prox * 0.3
                    mom_scores[s] = score

        if not mom_scores:
            continue

        sorted_candidates = sorted(mom_scores.items(), key=lambda x: x[1], reverse=True)[:num_stocks]
        leaderboard_top_n = set([x[0] for x in sorted_candidates])

        current_holding_symbols = set(current_positions.keys())
        retained_symbols = current_holding_symbols.intersection(leaderboard_top_n)
        dropped_symbols = current_holding_symbols - retained_symbols
        new_joiners = leaderboard_top_n - retained_symbols

        monthly_realized_pl = 0.0

        # Execute Sells for dropped stocks
        for sym in dropped_symbols:
            pos = current_positions[sym]
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            
            cost_rate = get_stock_slippage(sym, mkt_cap_dict)
            gross_proceeds = pos['shares'] * p * (1.0 - cost_rate)
            cost_basis = pos['shares'] * pos['entry_price']
            net_profit = gross_proceeds - cost_basis
            
            monthly_realized_pl += net_profit
            holding_days = (rebal_date - pos['entry_date']).days
            
            completed_trades.append({
                'symbol': sym,
                'entry_date': pos['entry_date'],
                'exit_date': rebal_date,
                'holding_days': holding_days,
                'return_pct': (net_profit / cost_basis) * 100.0,
                'profit_amount': net_profit,
                'is_winner': net_profit > 0
            })

            current_cash += gross_proceeds
            del current_positions[sym]

        # Execute Buys for new joiners using available cash
        if new_joiners and current_cash > 0:
            target_cash_per_buy = current_cash / len(new_joiners)
            for sym in new_joiners:
                p = price_pivot.loc[rebal_date, sym]
                cost_rate = get_stock_slippage(sym, mkt_cap_dict)
                effective_entry_price = p * (1.0 + cost_rate)
                shares = target_cash_per_buy / effective_entry_price
                
                current_positions[sym] = {
                    'entry_price': p,
                    'peak_price': p,
                    'shares': shares,
                    'entry_date': rebal_date
                }
                current_cash -= target_cash_per_buy

        if detailed_logging:
            monthly_logs.append({
                'month': rebal_date.strftime('%Y-%m'),
                'portfolio_val': round(portfolio_val_before, 2),
                'sip_added': 100000 if sip_added_this_month else 0,
                'realized_pl': round(monthly_realized_pl, 2),
                'retained_count': len(retained_symbols),
                'new_joiners': list(new_joiners),
                'dropped_exits': list(dropped_symbols)
            })

        # Mid-month daily tracking for Stop Loss / Take Profit
        sub_dates = [d for d in price_pivot.index if rebal_date < d < next_rebal_date]
        for d in sub_dates:
            stopped_syms = []
            for sym, pos in list(current_positions.items()):
                if sym in price_pivot.columns:
                    p = price_pivot.loc[d, sym]
                    if pd.isna(p): continue
                    
                    if p > pos['peak_price']:
                        pos['peak_price'] = p

                    # 1. Trailing Stop Loss
                    if trailing_stop_loss:
                        drawdown = (p - pos['peak_price']) / pos['peak_price']
                        if drawdown <= -trailing_stop_loss:
                            stopped_syms.append((sym, d))
                            continue

                    # 2. Fixed 2:1 Risk-Reward (+20% TP / -10% SL)
                    if take_profit_pct and fixed_stop_loss:
                        ret_from_entry = (p - pos['entry_price']) / pos['entry_price']
                        if ret_from_entry >= take_profit_pct or ret_from_entry <= -fixed_stop_loss:
                            stopped_syms.append((sym, d))

            for sym, exit_d in stopped_syms:
                pos = current_positions[sym]
                p = price_pivot.loc[exit_d, sym]
                cost_rate = get_stock_slippage(sym, mkt_cap_dict)
                gross_proceeds = pos['shares'] * p * (1.0 - cost_rate)
                cost_basis = pos['shares'] * pos['entry_price']
                net_profit = gross_proceeds - cost_basis
                
                holding_days = (exit_d - pos['entry_date']).days
                completed_trades.append({
                    'symbol': sym,
                    'entry_date': pos['entry_date'],
                    'exit_date': exit_d,
                    'holding_days': holding_days,
                    'return_pct': (net_profit / cost_basis) * 100.0,
                    'profit_amount': net_profit,
                    'is_winner': net_profit > 0
                })

                current_cash += gross_proceeds
                del current_positions[sym]

    # Final Portfolio Value
    final_date = monthly_dates[-1]
    final_val = current_cash
    for sym, pos in current_positions.items():
        p = price_pivot.loc[final_date, sym] if (final_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[final_date, sym])) else pos['entry_price']
        final_val += pos['shares'] * p

        # Close open trades at final date
        cost_basis = pos['shares'] * pos['entry_price']
        net_profit = (pos['shares'] * p) - cost_basis
        holding_days = (final_date - pos['entry_date']).days
        completed_trades.append({
            'symbol': sym,
            'entry_date': pos['entry_date'],
            'exit_date': final_date,
            'holding_days': holding_days,
            'return_pct': (net_profit / cost_basis) * 100.0 if cost_basis > 0 else 0,
            'profit_amount': net_profit,
            'is_winner': net_profit > 0
        })

    equity_curve.append({'date': final_date, 'portfolio_value': final_val, 'invested_capital': total_invested_capital})
    eq_df = pd.DataFrame(equity_curve)

    net_profit = final_val - total_invested_capital
    total_return = (net_profit / total_invested_capital) * 100.0
    num_years = (monthly_dates[-1] - monthly_dates[0]).days / 365.25
    cagr = ((final_val / total_invested_capital) ** (1.0 / num_years) - 1.0) * 100.0

    eq_df['daily_return'] = eq_df['portfolio_value'].pct_change()
    sharpe = (eq_df['daily_return'].mean() / eq_df['daily_return'].std()) * np.sqrt(12) if eq_df['daily_return'].std() > 0 else 0
    
    eq_df['peak'] = eq_df['portfolio_value'].cummax()
    eq_df['dd'] = (eq_df['portfolio_value'] - eq_df['peak']) / eq_df['peak'] * 100.0
    max_dd = eq_df['dd'].min()

    # Trade Analytics Breakdown
    trades_df = pd.DataFrame(completed_trades)
    winning_trades = trades_df[trades_df['is_winner'] == True]
    losing_trades = trades_df[trades_df['is_winner'] == False]

    win_rate = (len(winning_trades) / len(trades_df) * 100.0) if len(trades_df) > 0 else 0.0
    avg_hold_win = winning_trades['holding_days'].mean() if len(winning_trades) > 0 else 0.0
    avg_hold_loss = losing_trades['holding_days'].mean() if len(losing_trades) > 0 else 0.0
    avg_win_ret = winning_trades['return_pct'].mean() if len(winning_trades) > 0 else 0.0
    avg_loss_ret = losing_trades['return_pct'].mean() if len(losing_trades) > 0 else 0.0

    summary_res = {
        'Strategy Name': config['name'],
        'Stocks': num_stocks,
        'Liquidity Model': 'MktCap >= 500Cr (0.2% slip)' if liquidity_filter else 'Whole Market (1.5% slip)',
        'Total Invested (₹)': f"₹{total_invested_capital:,.0f}",
        'Final Portfolio (₹)': f"₹{final_val:,.0f}",
        'Net Profit (₹)': f"₹{net_profit:,.0f}",
        'Total Return (%)': f"{total_return:.2f}%",
        'CAGR (%)': f"{cagr:.2f}%",
        'Sharpe': f"{sharpe:.2f}",
        'Max Drawdown (%)': f"{max_dd:.2f}%",
        'Win Rate (%)': f"{win_rate:.1f}%",
        'Avg Hold (Winners)': f"{avg_hold_win:.0f} days",
        'Avg Hold (Losers)': f"{avg_hold_loss:.0f} days",
        'Avg Winner Return': f"+{avg_win_ret:.1f}%",
        'Avg Loser Return': f"{avg_loss_ret:.1f}%"
    }

    if detailed_logging:
        return summary_res, monthly_logs, trades_df
    return summary_res

def run_nifty_benchmark(prices_df, monthly_dates):
    nifty_prices = prices_df[prices_df['symbol'] == 'NIFTY50'].set_index('date')['close']
    
    total_invested = INITIAL_CAPITAL
    units = INITIAL_CAPITAL / nifty_prices.loc[monthly_dates[0]]
    last_sip_year = None

    for d in monthly_dates:
        if last_sip_year is None or d.year > last_sip_year:
            if last_sip_year is not None:
                p = nifty_prices.loc[d]
                units += ANNUAL_SIP_ADDITION / p
                total_invested += ANNUAL_SIP_ADDITION
            last_sip_year = d.year

    final_val = units * nifty_prices.loc[monthly_dates[-1]]
    net_profit = final_val - total_invested
    tot_ret = (net_profit / total_invested) * 100.0
    num_years = (monthly_dates[-1] - monthly_dates[0]).days / 365.25
    cagr = ((final_val / total_invested) ** (1.0 / num_years) - 1.0) * 100.0

    sub_nifty = nifty_prices.loc[monthly_dates]
    peak = sub_nifty.cummax()
    dd = (sub_nifty - peak) / peak * 100.0
    max_dd = dd.min()

    returns = sub_nifty.pct_change()
    sharpe = (returns.mean() / returns.std()) * np.sqrt(12) if returns.std() > 0 else 0

    return {
        'Strategy Name': 'Nifty 50 Benchmark (SIP)',
        'Stocks': 50,
        'Liquidity Model': 'Index (No Slippage)',
        'Total Invested (₹)': f"₹{total_invested:,.0f}",
        'Final Portfolio (₹)': f"₹{final_val:,.0f}",
        'Net Profit (₹)': f"₹{net_profit:,.0f}",
        'Total Return (%)': f"{tot_ret:.2f}%",
        'CAGR (%)': f"{cagr:.2f}%",
        'Sharpe': f"{sharpe:.2f}",
        'Max Drawdown (%)': f"{max_dd:.2f}%",
        'Win Rate (%)': 'N/A',
        'Avg Hold (Winners)': 'N/A',
        'Avg Hold (Losers)': 'N/A',
        'Avg Winner Return': 'N/A',
        'Avg Loser Return': 'N/A'
    }

def main():
    prices_df, comp_df, ratios_df, pl_df = load_data()
    monthly_dates = compute_monthly_dates(prices_df)

    print(f"\n[BACKTEST MATRIX] Running backtests from {monthly_dates[0].strftime('%Y-%m-%d')} to {monthly_dates[-1].strftime('%Y-%m-%d')} ({len(monthly_dates)} rebalance periods)...\n", flush=True)

    configs = [
        # Whole Market (1.5% Illiquid Slippage + Brokerage + Leaderboard Retention)
        {'name': 'Whole Market Momentum (10 Stocks)', 'num_stocks': 10, 'fundamental_filter': False, 'liquidity_filter': False},
        {'name': 'Whole Market Momentum (20 Stocks)', 'num_stocks': 20, 'fundamental_filter': False, 'liquidity_filter': False},
        {'name': 'Whole Market Momentum (25 Stocks)', 'num_stocks': 25, 'fundamental_filter': False, 'liquidity_filter': False},

        # Liquid Only (0.2% Slippage + Brokerage + Leaderboard Retention)
        {'name': 'Liquid Momentum (10 Stocks)', 'num_stocks': 10, 'fundamental_filter': False, 'liquidity_filter': True},
        {'name': 'Liquid Momentum (20 Stocks)', 'num_stocks': 20, 'fundamental_filter': False, 'liquidity_filter': True},
        {'name': 'Liquid Momentum (25 Stocks)', 'num_stocks': 25, 'fundamental_filter': False, 'liquidity_filter': True},

        # Quality + Momentum
        {'name': 'Quality + Momentum (10 Stocks)', 'num_stocks': 10, 'fundamental_filter': True, 'liquidity_filter': True},
        {'name': 'Quality + Momentum (20 Stocks)', 'num_stocks': 20, 'fundamental_filter': True, 'liquidity_filter': True},
        {'name': 'Quality + Momentum (25 Stocks)', 'num_stocks': 25, 'fundamental_filter': True, 'liquidity_filter': True},

        # Trailing Stop Loss (12%)
        {'name': 'Quality + 12% Trailing SL (10 Stocks)', 'num_stocks': 10, 'fundamental_filter': True, 'liquidity_filter': True, 'trailing_stop_loss': 0.12},
        {'name': 'Quality + 12% Trailing SL (20 Stocks)', 'num_stocks': 20, 'fundamental_filter': True, 'liquidity_filter': True, 'trailing_stop_loss': 0.12},

        # 2:1 Risk-Reward Exit (+20% TP / -10% SL)
        {'name': 'Pure Momentum + 2:1 Risk-Reward (10 Stocks)', 'num_stocks': 10, 'fundamental_filter': False, 'liquidity_filter': True, 'take_profit': 0.20, 'fixed_stop_loss': 0.10},
        {'name': 'Pure Momentum + 2:1 Risk-Reward (20 Stocks)', 'num_stocks': 20, 'fundamental_filter': False, 'liquidity_filter': True, 'take_profit': 0.20, 'fixed_stop_loss': 0.10},
        {'name': 'Quality + 2:1 Risk-Reward (10 Stocks)', 'num_stocks': 10, 'fundamental_filter': True, 'liquidity_filter': True, 'take_profit': 0.20, 'fixed_stop_loss': 0.10},
    ]

    results = []
    for cfg in configs:
        print(f"Running: {cfg['name']}...", flush=True)
        res = run_single_backtest(cfg, prices_df, comp_df, ratios_df, pl_df, monthly_dates)
        results.append(res)

    bench_res = run_nifty_benchmark(prices_df, monthly_dates)
    results.append(bench_res)

    results_df = pd.DataFrame(results)

    print("\n" + "=" * 135)
    print("                     REALISTIC BACKTEST MATRIX WITH TRADE ANALYTICS                     ")
    print("=" * 135)
    print(results_df.to_string(index=False))

if __name__ == "__main__":
    main()
