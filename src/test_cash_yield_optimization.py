import sqlite3
import pandas as pd
import numpy as np

INDIA_DB = "data/nse_stocks_all_years.db"
START_DATE = "2018-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 100000.0  # ₹1 Lakh
ANNUAL_SIP = 100000.0       # ₹1 Lakh
IDLE_CASH_YIELD = 0.07      # 7% P.A. Liquid ETF / Arbitrage Yield
SLIPPAGE = 0.003

def load_india_data():
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

    return price_pivot, qualifying_dict

def run_cash_yield_backtest(enable_liquid_yield=True):
    price_pivot, qualifying_dict = load_india_data()
    all_tickers = price_pivot.columns.tolist()

    dates = sorted(price_pivot.index)
    dates_df = pd.DataFrame({'Date': dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    sma_200_pivot = price_pivot.rolling(200).mean()
    m3 = price_pivot.pct_change(63)
    vol60 = price_pivot.pct_change().rolling(60).std()
    mom_pivot = m3 / (vol60 + 1e-6)

    current_cash = INITIAL_CAPITAL
    total_invested = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}
    last_sip_year = None

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

        # Annual SIP
        if last_sip_year is None or rebal_date.year > last_sip_year:
            if last_sip_year is not None:
                current_cash += ANNUAL_SIP
                total_invested += ANNUAL_SIP
            last_sip_year = rebal_date.year

        # Earn 7% P.A. monthly yield on uninvested cash balance if enabled
        if enable_liquid_yield and current_cash > 0:
            monthly_yield = current_cash * (IDLE_CASH_YIELD / 12.0)
            current_cash += monthly_yield

        pos_val_sum = sum([pos['shares'] * (price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']) for s, pos in current_positions.items()])
        total_val = current_cash + pos_val_sum
        equity_curve.append({'Date': rebal_date, 'Value': total_val})

        if rebal_date not in mom_pivot.index:
            continue

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
                        continue
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
            proceeds = pos['shares'] * p * (1.0 - SLIPPAGE)
            current_cash += proceeds
            del current_positions[s]

        if buys and current_cash > 0:
            alloc_per_buy = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + SLIPPAGE)
                shares = int(np.floor(alloc_per_buy / entry_p))
                if shares > 0:
                    cost = shares * entry_p
                    current_positions[s] = {'entry_price': p, 'shares': shares}
                    current_cash -= cost

    final_date = monthly_dates[-1]
    pos_val_sum = sum([pos['shares'] * (price_pivot.loc[final_date, s] if (final_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[final_date, s])) else pos['entry_price']) for s, pos in current_positions.items()])
    final_val = current_cash + pos_val_sum

    num_years = (monthly_dates[-1] - monthly_dates[0]).days / 365.25
    cagr = ((final_val / total_invested) ** (1.0 / num_years) - 1.0) * 100.0

    eq_df = pd.DataFrame(equity_curve)
    eq_df['peak'] = eq_df['Value'].cummax()
    max_dd = ((eq_df['Value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    return round(final_val, 2), round(cagr, 2), round(max_dd, 2)

def main():
    print("=" * 90, flush=True)
    print("     IDLE CASH YIELD OPTIMIZATION (EARNING 7% P.A. ON LIQUID ETFs / ARBITRAGE)     ", flush=True)
    print("=" * 90, flush=True)

    v_idle, c_idle, d_idle = run_cash_yield_backtest(enable_liquid_yield=False)
    v_yield, c_yield, d_yield = run_cash_yield_backtest(enable_liquid_yield=True)

    print("\n--- 1. IDLE CASH (0% INTEREST ON UNINVESTED CASH) ---")
    print(f"  - Final Portfolio Value Today: ₹{v_idle:,.2f}")
    print(f"  - Compound Annual Growth (CAGR): {c_idle}%")

    print("\n--- 2. 🏆 LIQUID ETF / ARBITRAGE FUND YIELD (7% P.A. ON UNINVESTED CASH) ---")
    print(f"  - Final Portfolio Value Today: ₹{v_yield:,.2f}")
    print(f"  - Compound Annual Growth (CAGR): {c_yield}%")
    print(f"  - Net Extra Yield Boost: +₹{v_yield - v_idle:,.2f} extra profit!")

if __name__ == "__main__":
    main()
