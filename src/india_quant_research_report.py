import sqlite3
import pandas as pd
import numpy as np

INDIA_DB = "data/nse_stocks_all_years.db"
START_DATE = "2018-01-01"
END_DATE = "2026-08-25"
RISK_FREE_RATE = 0.05  # 5% annual risk-free rate in India
SLIPPAGE = 0.003       # 0.3% slippage + STT + brokerage in India

def load_india_data():
    print("[INDIA QUANT RESEARCH] Loading daily prices and financial statements from nse_stocks_all_years.db...", flush=True)
    conn = sqlite3.connect(INDIA_DB)

    prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE date >= '2017-01-01' AND close IS NOT NULL", conn)
    comp_df = pd.read_sql_query("SELECT symbol AS Ticker, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, total_revenue, net_profit FROM financial_income_statement", conn)
    conn.close()

    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    price_pivot = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').dropna(how='all').ffill().bfill()
    mkt_cap_dict = dict(zip(comp_df['Ticker'], comp_df['market_cap']))

    print(f"[DATA READY] {price_pivot.shape[0]} trading days across {price_pivot.shape[1]} Indian NSE tickers.", flush=True)

    # EXACT NET INCOME PROFIT & SHRINKING LOSS TURNAROUND SCREEN:
    pl_sorted = pl_df.sort_values(['Ticker', 'Year'])
    pl_sorted['prev_net_profit'] = pl_sorted.groupby('Ticker')['net_profit'].shift(1)
    pl_sorted['loss_decreasing'] = (pl_sorted['net_profit'] < 0) & (pl_sorted['net_profit'] > pl_sorted['prev_net_profit'])
    pl_sorted['qualifies'] = (pl_sorted['net_profit'] > 0) | (pl_sorted['loss_decreasing'] == True)

    qualifying_dict = {}
    for y in range(2016, 2027):
        r_sub = ratios_df[ratios_df['Year'] == y]
        p_sub = pl_sorted[pl_sorted['Year'] == y]
        merged = pd.merge(r_sub, p_sub[['Ticker', 'Year', 'qualifies']], on=['Ticker', 'Year'], how='inner')
        q_set = set(merged[(merged['qualifies'] == True) & (merged['debt_equity'] <= 1.5)]['Ticker'])
        qualifying_dict[y] = [s for s in price_pivot.columns if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in q_set)]

    return price_pivot, qualifying_dict

def compute_performance_metrics(equity_series, daily_returns, trade_list):
    if equity_series.empty or len(equity_series) < 10:
        return {}

    total_invested = equity_series['Invested'].iloc[-1] if 'Invested' in equity_series.columns else 100000.0
    final_val = equity_series['Value'].iloc[-1]
    net_profit = final_val - total_invested
    total_return = (net_profit / total_invested) * 100.0

    num_years = (equity_series['Date'].iloc[-1] - equity_series['Date'].iloc[0]).days / 365.25
    cagr = ((final_val / total_invested) ** (1.0 / max(num_years, 0.1)) - 1.0) * 100.0

    # Drawdown & Recovery Time
    peak = equity_series['Value'].cummax()
    drawdown = (equity_series['Value'] - peak) / peak
    max_dd = drawdown.min() * 100.0

    # Sharpe & Sortino Ratio
    ret_series = daily_returns.dropna()
    mean_ret = ret_series.mean() * 252.0
    vol_ret = ret_series.std() * np.sqrt(252.0)
    sharpe = (mean_ret - RISK_FREE_RATE) / (vol_ret + 1e-6)

    downside_rets = ret_series[ret_series < 0]
    downside_std = downside_rets.std() * np.sqrt(252.0)
    sortino = (mean_ret - RISK_FREE_RATE) / (downside_std + 1e-6)

    # Trade stats
    trades_df = pd.DataFrame(trade_list)
    total_trades = len(trades_df)
    if total_trades > 0:
        win_rate = (len(trades_df[trades_df['return_pct'] > 0]) / total_trades) * 100.0
        avg_hold_win = trades_df[trades_df['return_pct'] > 0]['holding_days'].mean() if not trades_df[trades_df['return_pct'] > 0].empty else 0.0
        avg_hold_loss = trades_df[trades_df['return_pct'] <= 0]['holding_days'].mean() if not trades_df[trades_df['return_pct'] <= 0].empty else 0.0
    else:
        win_rate, avg_hold_win, avg_hold_loss = 0.0, 0.0, 0.0

    return {
        'Final_Value': final_val,
        'Net_Profit': net_profit,
        'Total_Return': total_return,
        'CAGR': cagr,
        'Max_Drawdown': max_dd,
        'Sharpe': sharpe,
        'Sortino': sortino,
        'Total_Trades': total_trades,
        'Win_Rate': win_rate,
        'Avg_Hold_Win': avg_hold_win,
        'Avg_Hold_Loss': avg_hold_loss
    }

def run_india_backtest_engine(price_pivot, qualifying_dict, start_dt, end_dt, trend_filter="NONE", mom_formula="M3", num_stocks=10, initial_cap=100000.0, annual_sip=100000.0):
    all_tickers = price_pivot.columns.tolist()
    
    dates = sorted(price_pivot.index)
    start_dt = pd.to_datetime(start_dt)
    end_dt = pd.to_datetime(end_dt)
    
    trading_dates = [d for d in dates if start_dt <= d <= end_dt]
    dates_df = pd.DataFrame({'Date': trading_dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()

    # Pre-calculate Trend Filters
    if trend_filter == "SMA_50":
        sma_pivot = price_pivot.rolling(50).mean()
    elif trend_filter == "SMA_100":
        sma_pivot = price_pivot.rolling(100).mean()
    elif trend_filter == "SMA_200":
        sma_pivot = price_pivot.rolling(200).mean()
    else:
        sma_pivot = None

    # Pre-calculate Momentum Formulas
    if mom_formula == "M3":
        mom_pivot = price_pivot.pct_change(63)
    elif mom_formula == "M12_6_3":
        m12 = price_pivot.pct_change(252)
        m6 = price_pivot.pct_change(126)
        m3 = price_pivot.pct_change(63)
        mom_pivot = m12 * 0.5 + m6 * 0.3 + m3 * 0.2
    elif mom_formula == "M12_1M":
        mom_pivot = (price_pivot.shift(21) / price_pivot.shift(252)) - 1.0
    elif mom_formula == "SHARPE_3M":
        m3 = price_pivot.pct_change(63)
        vol60 = price_pivot.pct_change().rolling(60).std()
        mom_pivot = m3 / (vol60 + 1e-6)
    elif mom_formula == "VOL_ADJ_M6":
        m6_1m = (price_pivot.shift(21) / price_pivot.shift(126)) - 1.0
        vol60 = price_pivot.pct_change().rolling(60).std()
        mom_pivot = m6_1m / (vol60 + 1e-6)
    else:
        mom_pivot = price_pivot.pct_change(63)

    current_cash = initial_cap
    total_invested = initial_cap
    equity_curve = []
    current_positions = {}
    completed_trades = []
    last_sip_year = None

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

        # Annual SIP
        if last_sip_year is None or rebal_date.year > last_sip_year:
            if last_sip_year is not None:
                current_cash += annual_sip
                total_invested += annual_sip
            last_sip_year = rebal_date.year

        # Evaluate portfolio
        total_val = current_cash
        for sym in list(current_positions.keys()):
            pos = current_positions[sym]
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            
            if sma_pivot is not None and rebal_date in sma_pivot.index and sym in sma_pivot.columns:
                sma_val = sma_pivot.loc[rebal_date, sym]
                if pd.notna(sma_val) and p < sma_val:
                    proceeds = pos['shares'] * p * (1.0 - SLIPPAGE)
                    cost = pos['shares'] * pos['entry_price']
                    completed_trades.append({
                        'symbol': sym,
                        'entry_date': pos['entry_date'],
                        'exit_date': rebal_date,
                        'holding_days': (rebal_date - pos['entry_date']).days,
                        'return_pct': (proceeds - cost) / cost * 100.0
                    })
                    current_cash += proceeds
                    del current_positions[sym]
                    continue

            total_val += pos['shares'] * p

        equity_curve.append({'Date': rebal_date, 'Value': total_val, 'Invested': total_invested})

        if rebal_date not in mom_pivot.index:
            continue

        target_year = rebal_date.year - 1
        available = qualifying_dict.get(target_year, all_tickers)

        mom_scores = {}
        for s in available:
            if s in mom_pivot.columns:
                m = mom_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                sma_val = sma_pivot.loc[rebal_date, s] if (sma_pivot is not None and rebal_date in sma_pivot.index) else None

                if pd.notna(m) and pd.notna(p) and p > 0:
                    if sma_pivot is not None and sma_val is not None and pd.notna(sma_val) and p < sma_val:
                        continue
                    mom_scores[s] = float(m)

        if not mom_scores: continue

        sorted_candidates = sorted(mom_scores.items(), key=lambda x: x[1], reverse=True)[:num_stocks]
        top_n = set([x[0] for x in sorted_candidates])

        current_holdings = set(current_positions.keys())
        retained = current_holdings.intersection(top_n)
        dropped = current_holdings - retained
        buys = top_n - retained

        # Execute Sells
        for s in dropped:
            pos = current_positions[s]
            p = price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']
            proceeds = pos['shares'] * p * (1.0 - SLIPPAGE)
            cost = pos['shares'] * pos['entry_price']
            completed_trades.append({
                'symbol': s,
                'entry_date': pos['entry_date'],
                'exit_date': rebal_date,
                'holding_days': (rebal_date - pos['entry_date']).days,
                'return_pct': (proceeds - cost) / cost * 100.0
            })
            current_cash += proceeds
            del current_positions[s]

        # Execute Buys (Integer Whole Shares for India)
        if buys and current_cash > 0:
            alloc = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + SLIPPAGE)
                shares = int(np.floor(alloc / entry_p))
                if shares > 0:
                    cost = shares * entry_p
                    current_positions[s] = {'entry_price': p, 'shares': shares, 'entry_date': rebal_date}
                    current_cash -= cost

    eq_df = pd.DataFrame(equity_curve)
    if eq_df.empty: return {}, eq_df

    eq_df['Daily_Return'] = eq_df['Value'].pct_change().fillna(0)
    metrics = compute_performance_metrics(eq_df, eq_df['Daily_Return'], completed_trades)
    return metrics, eq_df

def main():
    price_pivot, qualifying_dict = load_india_data()
    print("\n" + "=" * 90, flush=True)
    print("      INDIAN STOCK MARKET QUANT RESEARCH AUDIT (2018 - 2026)      ", flush=True)
    print("=" * 90, flush=True)

    # 1. Test 1 Trend Filters in India
    trend_options = [
        ("Strategy A (No Trend Filter)", "NONE"),
        ("Strategy B (Price > 50 SMA)", "SMA_50"),
        ("Strategy C (Price > 100 SMA)", "SMA_100"),
        ("Strategy D (Price > 200 SMA)", "SMA_200")
    ]
    stock_counts = [5, 10, 15, 20, 30]

    test1_results = []
    for t_label, t_code in trend_options:
        for n in stock_counts:
            metrics, _ = run_india_backtest_engine(price_pivot, qualifying_dict, "2018-01-01", "2026-08-25", trend_filter=t_code, mom_formula="M3", num_stocks=n)
            test1_results.append({
                'Trend Filter': t_label,
                'Stocks Count': n,
                'CAGR (%)': f"{metrics.get('CAGR', 0):.2f}%",
                'Total Return (%)': f"{metrics.get('Total_Return', 0):.2f}%",
                'Max Drawdown (%)': f"{metrics.get('Max_Drawdown', 0):.2f}%",
                'Sharpe': f"{metrics.get('Sharpe', 0):.2f}",
                'Sortino': f"{metrics.get('Sortino', 0):.2f}",
                'Total Trades': metrics.get('Total_Trades', 0)
            })

    print("--- 1. INDIA TEST 1: TREND FILTER OPTIMIZATION ---", flush=True)
    print(pd.DataFrame(test1_results).to_string(index=False), flush=True)

    # 2. Test 2 Momentum Formulas in India (10-stock & 20-stock)
    formulas = [
        ("Momentum A (100% 3M Return)", "M3"),
        ("Momentum B (50% 12M + 30% 6M + 20% 3M)", "M12_6_3"),
        ("Momentum C (12M-1M Academic)", "M12_1M"),
        ("Momentum D (Sharpe 3M Risk-Adjusted)", "SHARPE_3M"),
        ("Momentum E (Vol-Adjusted 6M-1M)", "VOL_ADJ_M6")
    ]

    test2_results = []
    for f_label, f_code in formulas:
        m, _ = run_india_backtest_engine(price_pivot, qualifying_dict, "2018-01-01", "2026-08-25", trend_filter="NONE", mom_formula=f_code, num_stocks=10)
        test2_results.append({
            'Momentum Formula': f_label,
            'CAGR (%)': f"{m.get('CAGR', 0):.2f}%",
            'Max Drawdown (%)': f"{m.get('Max_Drawdown', 0):.2f}%",
            'Sharpe': f"{m.get('Sharpe', 0):.2f}",
            'Sortino': f"{m.get('Sortino', 0):.2f}",
            'Win Rate (%)': f"{m.get('Win_Rate', 0):.1f}%",
            'Avg Win Hold (Days)': f"{m.get('Avg_Hold_Win', 0):.0f}",
            'Avg Loss Hold (Days)': f"{m.get('Avg_Hold_Loss', 0):.0f}"
        })

    print("\n--- 2. INDIA TEST 2: MOMENTUM FORMULA AUDIT (10-STOCK PORTFOLIO) ---", flush=True)
    print(pd.DataFrame(test2_results).to_string(index=False), flush=True)

    # 3. Test 3 In-Sample (2018-2022) vs Out-of-Sample (2023-2026) in India
    tr_m, _ = run_india_backtest_engine(price_pivot, qualifying_dict, "2018-01-01", "2022-12-31", trend_filter="NONE", mom_formula="SHARPE_3M", num_stocks=10)
    te_m, _ = run_india_backtest_engine(price_pivot, qualifying_dict, "2023-01-01", "2026-08-25", trend_filter="NONE", mom_formula="SHARPE_3M", num_stocks=10)

    print("\n--- 3. INDIA TEST 3: IN-SAMPLE (2018-2022) VS OUT-OF-SAMPLE (2023-2026) ---", flush=True)
    print(f"Training In-Sample (2018-2022):   CAGR: {tr_m.get('CAGR', 0):.2f}% | Max DD: {tr_m.get('Max_Drawdown', 0):.2f}% | Sharpe: {tr_m.get('Sharpe', 0):.2f}")
    print(f"Testing Out-of-Sample (2023-2026): CAGR: {te_m.get('CAGR', 0):.2f}% | Max DD: {te_m.get('Max_Drawdown', 0):.2f}% | Sharpe: {te_m.get('Sharpe', 0):.2f}")

if __name__ == "__main__":
    main()
