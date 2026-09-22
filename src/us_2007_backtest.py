import sqlite3
import pandas as pd
import numpy as np

DB_NAME = "instocks.db"
START_DATE = "2007-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 10000.0  # $10,000 Initial Capital
ANNUAL_SIP = 10000.0       # $10,000 Annual SIP
SLIPPAGE = 0.001          # 0.1% transaction cost

def load_sec_2007_data():
    print("[2007 US BACKTEST SETUP] Loading 2007-2026 prices and SEC EDGAR fundamentals from instocks.db...", flush=True)
    conn = sqlite3.connect(DB_NAME)

    # Daily prices from 2006 to 2026
    prices_df = pd.read_sql_query("SELECT Ticker, Date, Adj_Close FROM daily_prices WHERE Date >= '2006-01-01' AND Adj_Close IS NOT NULL", conn)
    inc_df = pd.read_sql_query("SELECT Ticker, Date, Net_Income FROM income_statements WHERE Net_Income IS NOT NULL", conn)
    bs_df = pd.read_sql_query("SELECT Ticker, Date, Total_Liabilities, Total_Equity FROM balance_sheets WHERE Total_Equity IS NOT NULL AND Total_Equity > 0", conn)
    conn.close()

    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    inc_df['Year'] = pd.to_datetime(inc_df['Date']).dt.year
    bs_df['Year'] = pd.to_datetime(bs_df['Date']).dt.year

    price_pivot = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').dropna(how='all').ffill().bfill()
    print(f"[DATA LOADED] Prices: {price_pivot.shape[0]} trading days from 2006 to 2026 across {price_pivot.shape[1]} US tickers.", flush=True)

    inc_sorted = inc_df.sort_values(['Ticker', 'Year'])
    inc_sorted['Prev_Net_Income'] = inc_sorted.groupby('Ticker')['Net_Income'].shift(1)
    inc_sorted['Qualifies'] = (inc_sorted['Net_Income'] > 0) | ((inc_sorted['Net_Income'] < 0) & (inc_sorted['Net_Income'] > inc_sorted['Prev_Net_Income']))

    return price_pivot, inc_sorted, bs_df

def run_us_2007_backtest(num_stocks=10):
    price_pivot, inc_sorted, bs_df = load_sec_2007_data()
    sp50_series = price_pivot['^GSPC'].dropna() if '^GSPC' in price_pivot.columns else price_pivot.iloc[:, 0]
    stock_tickers = [c for c in price_pivot.columns if c != '^GSPC']

    dates = sorted(price_pivot.index)
    dates_df = pd.DataFrame({'Date': dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    mom_3m_pivot = price_pivot[stock_tickers].pct_change(63)

    current_cash = INITIAL_CAPITAL
    total_invested = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}
    last_sip_year = None

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

        # Annual SIP Cash Addition ($10,000 added every January)
        if last_sip_year is None or rebal_date.year > last_sip_year:
            if last_sip_year is not None:
                current_cash += ANNUAL_SIP
                total_invested += ANNUAL_SIP
            last_sip_year = rebal_date.year

        # Evaluate Total Portfolio Equity
        total_val = current_cash
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            total_val += pos['shares'] * p

        equity_curve.append({'Date': rebal_date, 'Value': total_val, 'Invested': total_invested})

        if rebal_date not in mom_3m_pivot.index:
            continue

        target_year = rebal_date.year - 1
        inc_sub = inc_sorted[inc_sorted['Year'] == target_year]
        bs_sub = bs_df[bs_df['Year'] == target_year]
        merged = pd.merge(inc_sub, bs_sub[['Ticker', 'Year', 'Total_Liabilities', 'Total_Equity']], on=['Ticker', 'Year'], how='inner')
        merged['Debt_Equity'] = merged['Total_Liabilities'] / merged['Total_Equity']

        qualifying = set(merged[
            (merged['Qualifies'] == True) &
            (merged['Debt_Equity'] <= 1.5)
        ]['Ticker'])

        available = [s for s in stock_tickers if (s in qualifying or not qualifying)]

        mom_scores = {}
        for s in available:
            if s in mom_3m_pivot.columns:
                m = mom_3m_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                if pd.notna(m) and pd.notna(p) and p > 0:
                    mom_scores[s] = float(m)  # Pure 3M Price Return

        if not mom_scores:
            continue

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
            current_cash += proceeds
            del current_positions[s]

        # Execute Buys
        if buys and current_cash > 0:
            alloc = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + SLIPPAGE)
                shares = alloc / entry_p
                current_positions[s] = {'entry_price': p, 'shares': shares}
                current_cash -= alloc

    final_date = monthly_dates[-1]
    final_val = current_cash
    current_holdings_list = []
    for s, pos in current_positions.items():
        p = price_pivot.loc[final_date, s] if (final_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[final_date, s])) else pos['entry_price']
        pos_val = pos['shares'] * p
        gain_pct = (p - pos['entry_price']) / pos['entry_price'] * 100.0
        final_val += pos_val
        current_holdings_list.append({
            'symbol': s,
            'entry_price': round(pos['entry_price'], 2),
            'current_price': round(p, 2),
            'return_pct': f"{gain_pct:+.2f}%",
            'position_value': f"${pos_val:,.0f}"
        })

    net_profit = final_val - total_invested
    total_return = (net_profit / total_invested) * 100.0
    num_years = (monthly_dates[-1] - monthly_dates[0]).days / 365.25
    cagr = ((final_val / total_invested) ** (1.0 / num_years) - 1.0) * 100.0

    eq_df = pd.DataFrame(equity_curve)
    eq_df['peak'] = eq_df['Value'].cummax()
    max_dd = ((eq_df['Value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    # Benchmark calculation with iloc
    start_idx = sp50_series.index.get_indexer([monthly_dates[0]], method='nearest')[0]
    bench_start_p = float(sp50_series.iloc[start_idx])
    bench_units = INITIAL_CAPITAL / bench_start_p
    bench_invested = INITIAL_CAPITAL
    last_bench_year = None
    for d in monthly_dates:
        if last_bench_year is None or d.year > last_bench_year:
            if last_bench_year is not None:
                d_idx = sp50_series.index.get_indexer([d], method='nearest')[0]
                p = float(sp50_series.iloc[d_idx])
                bench_units += ANNUAL_SIP / p
                bench_invested += ANNUAL_SIP
            last_bench_year = d.year

    end_idx = sp50_series.index.get_indexer([monthly_dates[-1]], method='nearest')[0]
    bench_end_p = float(sp50_series.iloc[end_idx])
    bench_final = bench_units * bench_end_p
    bench_tot_ret = (bench_final - bench_invested) / bench_invested * 100.0
    bench_cagr = ((bench_final / bench_invested) ** (1.0 / num_years) - 1.0) * 100.0

    return {
        'num_stocks': num_stocks,
        'total_invested': total_invested,
        'final_val': final_val,
        'net_profit': net_profit,
        'total_return': total_return,
        'cagr': cagr,
        'max_dd': max_dd,
        'bench_final': bench_final,
        'bench_cagr': bench_cagr,
        'bench_ret': bench_tot_ret,
        'holdings': current_holdings_list,
        'equity_curve': eq_df
    }

def main():
    print("=" * 90, flush=True)
    print("    US EQUITIES BACKTEST FROM 2007 TO 2026 (SPANNING 2008 FINANCIAL CRISIS)    ", flush=True)
    print("=" * 90, flush=True)

    res10 = run_us_2007_backtest(num_stocks=10)
    res20 = run_us_2007_backtest(num_stocks=20)

    print("\n--- 1. LONG-TERM US PERFORMANCE VS S&P 500 (2007 - 2026: 19.5 YEARS) ---", flush=True)
    print(f"Total Capital Invested:              ${res10['total_invested']:,.0f} ($10k Initial + $10k Annual SIP)")
    
    print(f"\n10-Stock US Quality Momentum (2007-2026):")
    print(f"  - Final Portfolio Value Today:      ${res10['final_val']:,.2f}")
    print(f"  - Net Profit Made:                  ${res10['net_profit']:,.2f}")
    print(f"  - Total Return (%):                 +{res10['total_return']:.2f}%")
    print(f"  - Compound Annual Growth (CAGR):    {res10['cagr']:.2f}%")
    print(f"  - Max Drawdown (%):                 {res10['max_dd']:.2f}%")

    print(f"\n20-Stock US Quality Momentum (2007-2026):")
    print(f"  - Final Portfolio Value Today:      ${res20['final_val']:,.2f}")
    print(f"  - Net Profit Made:                  ${res20['net_profit']:,.2f}")
    print(f"  - Total Return (%):                 +{res20['total_return']:.2f}%")
    print(f"  - Compound Annual Growth (CAGR):    {res20['cagr']:.2f}%")
    print(f"  - Max Drawdown (%):                 {res20['max_dd']:.2f}%")

    print(f"\nS&P 500 Index Benchmark (^GSPC SIP 2007-2026):")
    print(f"  - Final Benchmark Value Today:      ${res10['bench_final']:,.2f}")
    print(f"  - Total Return (%):                 +{res10['bench_ret']:.2f}%")
    print(f"  - Compound Annual Growth (CAGR):    {res10['bench_cagr']:.2f}%")

    print("\n--- 2. CURRENT US 10-STOCK PORTFOLIO HOLDINGS TODAY (AUG 2026) ---", flush=True)
    h_df = pd.DataFrame(res10['holdings'])
    print(h_df.to_string(index=False), flush=True)

if __name__ == "__main__":
    main()
