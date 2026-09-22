import sqlite3
import pandas as pd
import numpy as np

INDIA_DB = "data/nse_stocks_all_years.db"
US_DB = "instocks.db"

START_DATE = "2020-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 100000.0  # ₹1 Lakh / $10k
ANNUAL_SIP = 100000.0       # ₹1 Lakh / $10k
SLIPPAGE = 0.003

def load_prices_and_qualifying(db_path, market_type="INDIA"):
    conn = sqlite3.connect(db_path)
    
    if market_type == "INDIA":
        prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE date >= '2019-01-01' AND close IS NOT NULL", conn)
        comp_df = pd.read_sql_query("SELECT symbol AS Ticker, market_cap FROM technical_valuation_data", conn)
        ratios_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, roe, debt_equity FROM financial_ratios", conn)
        pl_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, total_revenue, net_profit FROM financial_income_statement", conn)
        conn.close()

        prices_df['Date'] = pd.to_datetime(prices_df['Date'])
        price_pivot = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').dropna(how='all').ffill().bfill()
        mkt_cap_dict = dict(zip(comp_df['Ticker'], comp_df['market_cap']))

        pl_sorted = pl_df.sort_values(['Ticker', 'Year'])
        pl_sorted['prev_net_profit'] = pl_sorted.groupby('Ticker')['net_profit'].shift(1)
        pl_sorted['loss_decreasing'] = (pl_sorted['net_profit'] < 0) & (pl_sorted['net_profit'] > pl_sorted['prev_net_profit'])
        pl_sorted['qualifies'] = (pl_sorted['net_profit'] > 0) | (pl_sorted['loss_decreasing'] == True)

        qualifying_dict = {}
        for y in range(2018, 2027):
            r_sub = ratios_df[ratios_df['Year'] == y]
            p_sub = pl_sorted[pl_sorted['Year'] == y]
            merged = pd.merge(r_sub, p_sub[['Ticker', 'Year', 'qualifies']], on=['Ticker', 'Year'], how='inner')
            q_set = set(merged[(merged['qualifies'] == True) & (merged['debt_equity'] <= 1.5)]['Ticker'])
            qualifying_dict[y] = [s for s in price_pivot.columns if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in q_set)]

        return price_pivot, qualifying_dict

    else:
        prices_df = pd.read_sql_query("SELECT Ticker, Date, Adj_Close FROM daily_prices WHERE Date >= '2019-01-01' AND Adj_Close IS NOT NULL", conn)
        inc_df = pd.read_sql_query("SELECT Ticker, Date, Net_Income FROM income_statements WHERE Net_Income IS NOT NULL", conn)
        bs_df = pd.read_sql_query("SELECT Ticker, Date, Total_Liabilities, Total_Equity FROM balance_sheets WHERE Total_Equity IS NOT NULL AND Total_Equity > 0", conn)
        conn.close()

        prices_df['Date'] = pd.to_datetime(prices_df['Date'])
        inc_df['Year'] = pd.to_datetime(inc_df['Date']).dt.year
        bs_df['Year'] = pd.to_datetime(bs_df['Date']).dt.year

        price_pivot = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').dropna(how='all').ffill().bfill()
        
        inc_sorted = inc_df.sort_values(['Ticker', 'Year'])
        inc_sorted['Prev_Net_Income'] = inc_sorted.groupby('Ticker')['Net_Income'].shift(1)
        inc_sorted['Qualifies'] = (inc_sorted['Net_Income'] > 0) | ((inc_sorted['Net_Income'] < 0) & (inc_sorted['Net_Income'] > inc_sorted['Prev_Net_Income']))

        qualifying_dict = {}
        for y in range(2018, 2027):
            inc_sub = inc_sorted[inc_sorted['Year'] == y]
            bs_sub = bs_df[bs_df['Year'] == y]
            merged = pd.merge(inc_sub, bs_sub[['Ticker', 'Year', 'Total_Liabilities', 'Total_Equity']], on=['Ticker', 'Year'], how='inner')
            merged['Debt_Equity'] = merged['Total_Liabilities'] / merged['Total_Equity']
            q_set = set(merged[(merged['Qualifies'] == True) & (merged['Debt_Equity'] <= 1.5)]['Ticker'])
            qualifying_dict[y] = [s for s in price_pivot.columns if s in q_set]

        return price_pivot, qualifying_dict

def compute_momentum_signals(price_pivot):
    m1 = price_pivot.pct_change(21)
    m3 = price_pivot.pct_change(63)
    m6 = price_pivot.pct_change(126)
    
    # Academic 12M-1M Momentum (Fama-French & Carhart standard)
    m12_1m = (price_pivot.shift(21) / price_pivot.shift(252)) - 1.0

    # Risk-Adjusted Momentum (3M Return / 60D Price Volatility)
    vol_60d = price_pivot.pct_change().rolling(60).std()
    sharpe_3m = m3 / (vol_60d + 1e-6)

    return {
        'M1 (1-Month Return)': m1,
        'M3 (3-Month Return)': m3,
        'M6 (6-Month Return)': m6,
        'M12-1M (Academic 12M-1M)': m12_1m,
        'Sharpe_3M (Risk-Adjusted Momentum)': sharpe_3m
    }

def run_single_matrix_backtest(price_pivot, qualifying_dict, signal_pivot, rebal_step_days=21, num_stocks=10):
    all_dates = sorted(price_pivot.index)
    start_dt = pd.to_datetime(START_DATE)
    end_dt = pd.to_datetime(END_DATE)

    trading_dates = [d for d in all_dates if start_dt <= d <= end_dt]
    rebal_dates = trading_dates[::rebal_step_days]

    current_cash = INITIAL_CAPITAL
    total_invested = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}
    last_sip_year = None

    for i in range(len(rebal_dates) - 1):
        rebal_date = rebal_dates[i]

        if last_sip_year is None or rebal_date.year > last_sip_year:
            if last_sip_year is not None:
                current_cash += ANNUAL_SIP
                total_invested += ANNUAL_SIP
            last_sip_year = rebal_date.year

        total_val = current_cash
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            total_val += pos['shares'] * p

        equity_curve.append({'date': rebal_date, 'value': total_val})

        target_year = rebal_date.year - 1
        available = qualifying_dict.get(target_year, price_pivot.columns.tolist())
        if not available:
            available = price_pivot.columns.tolist()

        scores = {}
        for s in available:
            if s in signal_pivot.columns and rebal_date in signal_pivot.index:
                val = signal_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                if pd.notna(val) and pd.notna(p) and p > 0:
                    scores[s] = float(val)

        if not scores: continue

        sorted_candidates = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:num_stocks]
        top_n = set([x[0] for x in sorted_candidates])

        current_holdings = set(current_positions.keys())
        retained = current_holdings.intersection(top_n)
        dropped = current_holdings - retained
        buys = top_n - retained

        for s in dropped:
            pos = current_positions[s]
            p = price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']
            proceeds = pos['shares'] * p * (1.0 - SLIPPAGE)
            current_cash += proceeds
            del current_positions[s]

        if buys and current_cash > 0:
            alloc = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + SLIPPAGE)
                shares = alloc / entry_p
                current_positions[s] = {'entry_price': p, 'shares': shares}
                current_cash -= alloc

    final_date = rebal_dates[-1]
    final_val = current_cash
    for s, pos in current_positions.items():
        p = price_pivot.loc[final_date, s] if (final_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[final_date, s])) else pos['entry_price']
        final_val += pos['shares'] * p

    num_years = (rebal_dates[-1] - rebal_dates[0]).days / 365.25
    cagr = ((final_val / total_invested) ** (1.0 / num_years) - 1.0) * 100.0

    eq_df = pd.DataFrame(equity_curve)
    eq_df['peak'] = eq_df['value'].cummax()
    max_dd = ((eq_df['value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    return round(final_val, 2), round(cagr, 2), round(max_dd, 2)

def main():
    print("=" * 90, flush=True)
    print("      RESEARCH MATRIX: REBALANCE FREQUENCY × MOMENTUM METHODOLOGIES      ", flush=True)
    print("=" * 90, flush=True)

    frequencies = [
        ('Weekly (Every 5 Days)', 5),
        ('Bi-Weekly (Every 10 Days)', 10),
        ('3-Weekly (Every 15 Days)', 15),
        ('Monthly (Every 21 Days)', 21)
    ]

    print("\n[RESEARCH TASK] Running full grid search across India (NSE) & US Markets...", flush=True)

    # 1. India Market Grid Search
    ind_prices, ind_qualifying = load_prices_and_qualifying(INDIA_DB, market_type="INDIA")
    ind_signals = compute_momentum_signals(ind_prices)

    ind_results = []
    for freq_name, step_days in frequencies:
        for sig_name, sig_pivot in ind_signals.items():
            f_val, cagr, max_dd = run_single_matrix_backtest(ind_prices, ind_qualifying, sig_pivot, rebal_step_days=step_days)
            ind_results.append({
                'Rebalance Frequency': freq_name,
                'Momentum Formula': sig_name,
                'Final Value (₹)': f"₹{f_val:,.0f}",
                'CAGR (%)': f"{cagr:.2f}%",
                'Max Drawdown (%)': f"{max_dd:.2f}%",
                'raw_cagr': cagr
            })

    # 2. US Market Grid Search
    us_prices, us_qualifying = load_prices_and_qualifying(US_DB, market_type="US")
    us_signals = compute_momentum_signals(us_prices)

    us_results = []
    for freq_name, step_days in frequencies:
        for sig_name, sig_pivot in us_signals.items():
            f_val, cagr, max_dd = run_single_matrix_backtest(us_prices, us_qualifying, sig_pivot, rebal_step_days=step_days)
            us_results.append({
                'Rebalance Frequency': freq_name,
                'Momentum Formula': sig_name,
                'Final Value ($)': f"${f_val:,.0f}",
                'CAGR (%)': f"{cagr:.2f}%",
                'Max Drawdown (%)': f"{max_dd:.2f}%",
                'raw_cagr': cagr
            })

    print("\n" + "=" * 90, flush=True)
    print("--- 1. INDIAN MARKET MATRIX RESULTS (NSE 1,480+ STOCKS) ---", flush=True)
    ind_df = pd.DataFrame(ind_results).sort_values('raw_cagr', ascending=False)
    print(ind_df[['Rebalance Frequency', 'Momentum Formula', 'Final Value (₹)', 'CAGR (%)', 'Max Drawdown (%)']].to_string(index=False), flush=True)

    print("\n" + "=" * 90, flush=True)
    print("--- 2. US MARKET MATRIX RESULTS (S&P 500 & 400 EQUITIES) ---", flush=True)
    us_df = pd.DataFrame(us_results).sort_values('raw_cagr', ascending=False)
    print(us_df[['Rebalance Frequency', 'Momentum Formula', 'Final Value ($)', 'CAGR (%)', 'Max Drawdown (%)']].to_string(index=False), flush=True)

if __name__ == "__main__":
    main()
