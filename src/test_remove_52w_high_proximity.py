import sqlite3
import pandas as pd
import numpy as np

# Data paths
INDIA_DB = "data/nse_stocks_all_years.db"
US_DB = "instocks.db"

START_DATE = "2020-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 100000.0  # ₹1 Lakh / $10k
ANNUAL_SIP = 100000.0       # ₹1 Lakh / $10k
SLIPPAGE = 0.003

def run_india_test(use_52w_high=True):
    conn = sqlite3.connect(INDIA_DB)
    prices_df = pd.read_sql_query("SELECT symbol, date, close, high_52w FROM daily_prices WHERE date >= '2019-01-01' AND close IS NOT NULL", conn)
    comp_df = pd.read_sql_query("SELECT symbol, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol, year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol, year, total_revenue, net_profit FROM financial_income_statement", conn)
    conn.close()

    prices_df['date'] = pd.to_datetime(prices_df['date'])
    price_pivot = prices_df.pivot(index='date', columns='symbol', values='close').dropna(how='all').ffill().bfill()
    high_52w_pivot = prices_df.pivot(index='date', columns='symbol', values='high_52w').dropna(how='all').ffill().bfill()
    mom_3m_pivot = price_pivot.pct_change(63)

    mkt_cap_dict = dict(zip(comp_df['symbol'], comp_df['market_cap']))

    pl_sorted = pl_df.sort_values(['symbol', 'year'])
    pl_sorted['prev_net_profit'] = pl_sorted.groupby('symbol')['net_profit'].shift(1)
    pl_sorted['loss_decreasing'] = (pl_sorted['net_profit'] < 0) & (pl_sorted['net_profit'] > pl_sorted['prev_net_profit'])
    pl_sorted['qualifies'] = (pl_sorted['net_profit'] > 0) | (pl_sorted['loss_decreasing'] == True)

    dates = sorted(price_pivot.index)
    dates_df = pd.DataFrame({'date': dates})
    dates_df['ym'] = dates_df['date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    current_cash = INITIAL_CAPITAL
    total_invested = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}
    last_sip_year = None

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

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
        r_sub = ratios_df[ratios_df['year'] == target_year]
        p_sub = pl_sorted[pl_sorted['year'] == target_year]
        merged = pd.merge(r_sub, p_sub[['symbol', 'year', 'qualifies']], on=['symbol', 'year'], how='inner')

        qualifying = set(merged[
            (merged['qualifies'] == True) &
            (merged['debt_equity'] <= 1.5)
        ]['symbol'])

        available = [s for s in price_pivot.columns if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in qualifying)]

        mom_scores = {}
        for s in available:
            if s in mom_3m_pivot.columns:
                m = mom_3m_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                h52 = high_52w_pivot.loc[rebal_date, s] if s in high_52w_pivot.columns else None

                if pd.notna(m) and pd.notna(p) and p > 0:
                    if use_52w_high:
                        prox = (p / h52) if (h52 and pd.notna(h52) and h52 > 0) else 0.8
                        mom_scores[s] = m * 0.7 + prox * 0.3
                    else:
                        mom_scores[s] = m  # 100% Pure 3M Price Return

        if not mom_scores: continue

        sorted_candidates = sorted(mom_scores.items(), key=lambda x: x[1], reverse=True)[:10]
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

    final_date = monthly_dates[-1]
    final_val = current_cash
    for s, pos in current_positions.items():
        p = price_pivot.loc[final_date, s] if (final_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[final_date, s])) else pos['entry_price']
        final_val += pos['shares'] * p

    num_years = (monthly_dates[-1] - monthly_dates[0]).days / 365.25
    cagr = ((final_val / total_invested) ** (1.0 / num_years) - 1.0) * 100.0

    eq_df = pd.DataFrame(equity_curve)
    eq_df['peak'] = eq_df['value'].cummax()
    max_dd = ((eq_df['value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    return round(final_val, 2), round(cagr, 2), round(max_dd, 2)

def run_us_test(use_52w_high=True):
    conn = sqlite3.connect(US_DB)
    prices_df = pd.read_sql_query("SELECT Ticker, Date, Adj_Close FROM daily_prices WHERE Date >= '2019-01-01' AND Adj_Close IS NOT NULL", conn)
    inc_df = pd.read_sql_query("SELECT Ticker, Date, Net_Income FROM income_statements WHERE Net_Income IS NOT NULL", conn)
    bs_df = pd.read_sql_query("SELECT Ticker, Date, Total_Liabilities, Total_Equity FROM balance_sheets WHERE Total_Equity IS NOT NULL AND Total_Equity > 0", conn)
    conn.close()

    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    inc_df['Year'] = pd.to_datetime(inc_df['Date']).dt.year
    bs_df['Year'] = pd.to_datetime(bs_df['Date']).dt.year

    price_pivot = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').dropna(how='all').ffill().bfill()
    high_52w_pivot = price_pivot.rolling(252).max()
    mom_3m_pivot = price_pivot.pct_change(63)

    inc_sorted = inc_df.sort_values(['Ticker', 'Year'])
    inc_sorted['Prev_Net_Income'] = inc_sorted.groupby('Ticker')['Net_Income'].shift(1)
    inc_sorted['Qualifies'] = (inc_sorted['Net_Income'] > 0) | ((inc_sorted['Net_Income'] < 0) & (inc_sorted['Net_Income'] > inc_sorted['Prev_Net_Income']))

    dates = sorted(price_pivot.index)
    dates_df = pd.DataFrame({'Date': dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    current_cash = 10000.0
    total_invested = 10000.0
    equity_curve = []
    current_positions = {}
    last_sip_year = None

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

        if last_sip_year is None or rebal_date.year > last_sip_year:
            if last_sip_year is not None:
                current_cash += 10000.0
                total_invested += 10000.0
            last_sip_year = rebal_date.year

        total_val = current_cash
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            total_val += pos['shares'] * p

        equity_curve.append({'Date': rebal_date, 'Value': total_val})

        target_year = rebal_date.year - 1
        inc_sub = inc_sorted[inc_sorted['Year'] == target_year]
        bs_sub = bs_df[bs_df['Year'] == target_year]
        merged = pd.merge(inc_sub, bs_sub[['Ticker', 'Year', 'Total_Liabilities', 'Total_Equity']], on=['Ticker', 'Year'], how='inner')
        merged['Debt_Equity'] = merged['Total_Liabilities'] / merged['Total_Equity']

        qualifying = set(merged[
            (merged['Qualifies'] == True) &
            (merged['Debt_Equity'] <= 1.5)
        ]['Ticker'])

        available = [s for s in price_pivot.columns if s in qualifying]

        mom_scores = {}
        for s in available:
            if s in mom_3m_pivot.columns:
                m = mom_3m_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                h52 = high_52w_pivot.loc[rebal_date, s] if s in high_52w_pivot.columns else None

                if pd.notna(m) and pd.notna(p) and p > 0:
                    if use_52w_high:
                        prox = (p / h52) if (h52 and pd.notna(h52) and h52 > 0) else 0.8
                        mom_scores[s] = m * 0.7 + prox * 0.3
                    else:
                        mom_scores[s] = m  # 100% Pure 3M Price Return

        if not mom_scores: continue

        sorted_candidates = sorted(mom_scores.items(), key=lambda x: x[1], reverse=True)[:10]
        top_n = set([x[0] for x in sorted_candidates])

        current_holdings = set(current_positions.keys())
        retained = current_holdings.intersection(top_n)
        dropped = current_holdings - retained
        buys = top_n - retained

        for s in dropped:
            pos = current_positions[s]
            p = price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']
            proceeds = pos['shares'] * p * (1.0 - 0.001)
            current_cash += proceeds
            del current_positions[s]

        if buys and current_cash > 0:
            alloc = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + 0.001)
                shares = alloc / entry_p
                current_positions[s] = {'entry_price': p, 'shares': shares}
                current_cash -= alloc

    final_date = monthly_dates[-1]
    final_val = current_cash
    for s, pos in current_positions.items():
        p = price_pivot.loc[final_date, s] if (final_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[final_date, s])) else pos['entry_price']
        final_val += pos['shares'] * p

    num_years = (monthly_dates[-1] - monthly_dates[0]).days / 365.25
    cagr = ((final_val / total_invested) ** (1.0 / num_years) - 1.0) * 100.0

    eq_df = pd.DataFrame(equity_curve)
    eq_df['peak'] = eq_df['Value'].cummax()
    max_dd = ((eq_df['Value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    return round(final_val, 2), round(cagr, 2), round(max_dd, 2)

def main():
    print("=" * 85, flush=True)
    print("    COMPARING 52-WEEK HIGH PROXIMITY (WITH vs WITHOUT) IN INDIA & US    ", flush=True)
    print("=" * 85, flush=True)

    # India Tests
    ind_v1, ind_c1, ind_d1 = run_india_test(use_52w_high=True)
    ind_v2, ind_c2, ind_d2 = run_india_test(use_52w_high=False)

    # US Tests
    us_v1, us_c1, us_d1 = run_us_test(use_52w_high=True)
    us_v2, us_c2, us_d2 = run_us_test(use_52w_high=False)

    print("\n--- 1. INDIAN MARKET (NSE 1,480+ STOCKS) RESULTS ---")
    print(f"WITH 52W High Proximity (70% 3M + 30% 52W High):")
    print(f"  - Final Value: ₹{ind_v1:,.2f} | CAGR: {ind_c1}% | Max DD: {ind_d1}%")
    print(f"WITHOUT 52W High Proximity (100% Pure 3M Return):")
    print(f"  - Final Value: ₹{ind_v2:,.2f} | CAGR: {ind_c2}% | Max DD: {ind_d2}%")

    print("\n--- 2. US MARKET (S&P 500 & S&P 400 903 STOCKS) RESULTS ---")
    print(f"WITH 52W High Proximity (70% 3M + 30% 52W High):")
    print(f"  - Final Value: ${us_v1:,.2f} | CAGR: {us_c1}% | Max DD: {us_d1}%")
    print(f"WITHOUT 52W High Proximity (100% Pure 3M Return):")
    print(f"  - Final Value: ${us_v2:,.2f} | CAGR: {us_c2}% | Max DD: {us_d2}%")

if __name__ == "__main__":
    main()
