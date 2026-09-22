import sqlite3
import pandas as pd
import numpy as np

INDIA_DB = "data/nse_stocks_all_years.db"
US_DB = "instocks.db"

def analyze_india_worst_years():
    conn = sqlite3.connect(INDIA_DB)
    prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE date >= '2017-01-01' AND close IS NOT NULL", conn)
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
    for y in range(2016, 2027):
        r_sub = ratios_df[ratios_df['Year'] == y]
        p_sub = pl_sorted[pl_sorted['Year'] == y]
        merged = pd.merge(r_sub, p_sub[['Ticker', 'Year', 'qualifies']], on=['Ticker', 'Year'], how='inner')
        q_set = set(merged[(merged['qualifies'] == True) & (merged['debt_equity'] <= 1.5)]['Ticker'])
        qualifying_dict[y] = [s for s in price_pivot.columns if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in q_set)]

    # Run Monthly Rebalance & calculate annual returns
    trading_dates = [d for d in price_pivot.index if pd.to_datetime("2018-01-01") <= d <= pd.to_datetime("2026-08-25")]
    dates_df = pd.DataFrame({'Date': trading_dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()

    m3 = price_pivot.pct_change(63)
    vol60 = price_pivot.pct_change().rolling(60).std()
    mom_pivot = m3 / (vol60 + 1e-6)

    current_cash = 100000.0
    equity_curve = []
    current_positions = {}
    all_tickers = price_pivot.columns.tolist()

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

        pos_val_sum = sum([pos['shares'] * (price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']) for s, pos in current_positions.items()])
        total_val = current_cash + pos_val_sum
        equity_curve.append({'Date': rebal_date, 'Value': total_val})

        target_year = rebal_date.year - 1
        available = qualifying_dict.get(target_year, all_tickers)

        mom_scores = {}
        for s in available:
            if s in mom_pivot.columns:
                m = mom_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                if pd.notna(m) and pd.notna(p) and p > 0:
                    mom_scores[s] = float(m)

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
            proceeds = pos['shares'] * p * (1.0 - 0.003)
            current_cash += proceeds
            del current_positions[s]

        if buys and current_cash > 0:
            alloc_per_buy = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + 0.003)
                shares = int(np.floor(alloc_per_buy / entry_p))
                if shares > 0:
                    cost = shares * entry_p
                    current_positions[s] = {'entry_price': p, 'shares': shares}
                    current_cash -= cost

    eq_df = pd.DataFrame(equity_curve)
    eq_df['Year'] = eq_df['Date'].dt.year

    # Annual Return per year
    annual_df = eq_df.groupby('Year')['Value'].agg(['first', 'last'])
    annual_df['Return_Pct'] = (annual_df['last'] - annual_df['first']) / annual_df['first'] * 100.0

    # Rolling 12-Month Returns
    eq_df['Rolling_12M_Return'] = eq_df['Value'].pct_change(12) * 100.0
    worst_rolling_12m = eq_df['Rolling_12M_Return'].min()

    return annual_df, worst_rolling_12m

def analyze_us_worst_years():
    conn = sqlite3.connect(US_DB)
    prices_df = pd.read_sql_query("SELECT Ticker, Date, Adj_Close FROM daily_prices WHERE Date >= '2006-01-01' AND Adj_Close IS NOT NULL", conn)
    inc_df = pd.read_sql_query("SELECT Ticker, Date, Net_Income FROM income_statements WHERE Net_Income IS NOT NULL", conn)
    bs_df = pd.read_sql_query("SELECT Ticker, Date, Total_Liabilities, Total_Equity FROM balance_sheets WHERE Total_Equity IS NOT NULL AND Total_Equity > 0", conn)
    conn.close()

    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    inc_df['Year'] = pd.to_datetime(inc_df['Date']).dt.year
    bs_df['Year'] = pd.to_datetime(bs_df['Date']).dt.year

    price_pivot = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').dropna(how='all').ffill().bfill()
    stock_tickers = [c for c in price_pivot.columns if c != '^GSPC']

    inc_sorted = inc_df.sort_values(['Ticker', 'Year'])
    inc_sorted['Prev_Net_Income'] = inc_sorted.groupby('Ticker')['Net_Income'].shift(1)
    inc_sorted['Qualifies'] = (inc_sorted['Net_Income'] > 0) | ((inc_sorted['Net_Income'] < 0) & (inc_sorted['Net_Income'] > inc_sorted['Prev_Net_Income']))

    trading_dates = [d for d in price_pivot.index if pd.to_datetime("2007-01-01") <= d <= pd.to_datetime("2026-08-25")]
    dates_df = pd.DataFrame({'Date': trading_dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()

    m6_1m = (price_pivot[stock_tickers].shift(21) / price_pivot[stock_tickers].shift(126)) - 1.0
    vol60 = price_pivot[stock_tickers].pct_change().rolling(60).std()
    mom_pivot = m6_1m / (vol60 + 1e-6)

    current_cash = 10000.0
    equity_curve = []
    current_positions = {}

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

        pos_val_sum = sum([pos['shares'] * (price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']) for s, pos in current_positions.items()])
        total_val = current_cash + pos_val_sum
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

        available = [s for s in stock_tickers if (s in qualifying or not qualifying)]

        mom_scores = {}
        for s in available:
            if s in mom_pivot.columns:
                m = mom_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                if pd.notna(m) and pd.notna(p) and p > 0:
                    mom_scores[s] = float(m)

        if not mom_scores: continue
        sorted_candidates = sorted(mom_scores.items(), key=lambda x: x[1], reverse=True)[:20]
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
            alloc_per_buy = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + 0.001)
                shares = alloc_per_buy / entry_p
                current_positions[s] = {'entry_price': p, 'shares': shares}
                current_cash -= alloc_per_buy

    eq_df = pd.DataFrame(equity_curve)
    eq_df['Year'] = eq_df['Date'].dt.year

    annual_df = eq_df.groupby('Year')['Value'].agg(['first', 'last'])
    annual_df['Return_Pct'] = (annual_df['last'] - annual_df['first']) / annual_df['first'] * 100.0

    eq_df['Rolling_12M_Return'] = eq_df['Value'].pct_change(12) * 100.0
    worst_rolling_12m = eq_df['Rolling_12M_Return'].min()

    return annual_df, worst_rolling_12m

def main():
    print("=" * 90, flush=True)
    print("        WORST SINGLE-YEAR RETURNS & PSYCHOLOGICAL RISK PREPARATION AUDIT        ", flush=True)
    print("=" * 90, flush=True)

    ind_annual, ind_rolling = analyze_india_worst_years()
    us_annual, us_rolling = analyze_us_worst_years()

    print("\n--- 1. 🇮🇳 INDIAN EQUITIES ANNUAL RETURNS YEAR-BY-YEAR (2018 - 2026) ---")
    for yr, row in ind_annual.iterrows():
        print(f"  - Year {yr}: {row['Return_Pct']:+.2f}%")
    print(f"\n👉 WORST SINGLE CALENDAR YEAR IN INDIA: {ind_annual['Return_Pct'].min():.2f}%")
    print(f"👉 WORST ROLLING 12-MONTH PERIOD IN INDIA: {ind_rolling:.2f}%")

    print("\n--- 2. 🇺🇸 US EQUITIES ANNUAL RETURNS YEAR-BY-YEAR (2007 - 2026) ---")
    for yr, row in us_annual.iterrows():
        print(f"  - Year {yr}: {row['Return_Pct']:+.2f}%")
    print(f"\n👉 WORST SINGLE CALENDAR YEAR IN US (2008 Crisis): {us_annual['Return_Pct'].min():.2f}%")
    print(f"👉 WORST ROLLING 12-MONTH PERIOD IN US: {us_rolling:.2f}%")

if __name__ == "__main__":
    main()
