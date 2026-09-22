import sqlite3
import pandas as pd
import numpy as np

INDIA_DB = "data/nse_stocks_all_years.db"
US_DB = "instocks.db"

def analyze_india_monthly_stats():
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

    trading_dates = [d for d in price_pivot.index if pd.to_datetime("2018-01-01") <= d <= pd.to_datetime("2026-08-25")]
    dates_df = pd.DataFrame({'Date': trading_dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()

    sma_200_pivot = price_pivot.rolling(200).mean()
    m3 = price_pivot.pct_change(63)
    vol60 = price_pivot.pct_change().rolling(60).std()
    mom_pivot = m3 / (vol60 + 1e-6)

    current_cash = 100000.0
    equity_curve = []
    current_positions = {}
    all_tickers = price_pivot.columns.tolist()
    full_cash_months = []

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
                s200 = sma_200_pivot.loc[rebal_date, s] if rebal_date in sma_200_pivot.index else None
                if pd.notna(m) and pd.notna(p) and p > 0:
                    if s200 is not None and pd.notna(s200) and p < s200:
                        continue  # Refuse buy if below 200 SMA
                    mom_scores[s] = float(m)

        if not mom_scores:
            full_cash_months.append(rebal_date)
            continue

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
    eq_df['Monthly_Return'] = eq_df['Value'].pct_change() * 100.0
    
    total_months = len(eq_df.dropna())
    profit_months = len(eq_df[eq_df['Monthly_Return'] > 0])
    loss_months = len(eq_df[eq_df['Monthly_Return'] < 0])
    win_month_pct = (profit_months / total_months) * 100.0

    return total_months, profit_months, loss_months, win_month_pct, full_cash_months

def main():
    print("=" * 90, flush=True)
    print("    MONTHLY LOSSES & 100% CASH OUT BREAKDOWN (2018 - 2026)    ", flush=True)
    print("=" * 90, flush=True)

    tot, win, loss, win_pct, cash_m = analyze_india_monthly_stats()

    print(f"\n--- 🇮🇳 INDIAN EQUITIES MONTHLY PERFORMANCE BREAKDOWN ---")
    print(f"Total Months Evaluated:     {tot} months (2018 - 2026)")
    print(f"Profit Months (Green):      {win} months ({win_pct:.1f}% of all months)")
    print(f"Loss Months (Red):          {loss} months ({(loss/tot)*100.0:.1f}% of all months)")
    print(f"Months Forced into 100% Cash: {len(cash_m)} months")
    
    if cash_m:
        print("  Dates of 100% Cash Out:")
        for d in cash_m:
            print(f"    - {d.strftime('%B %Y')}")

if __name__ == "__main__":
    main()
