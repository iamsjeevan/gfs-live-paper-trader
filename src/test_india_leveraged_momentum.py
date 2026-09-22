import sqlite3
import pandas as pd
import numpy as np

INDIA_DB = "data/nse_stocks_all_years.db"
START_DATE = "2018-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 100000.0  # ₹1 Lakh
ANNUAL_SIP = 100000.0       # ₹1 Lakh
INDIAN_MTF_INTEREST = 0.10  # 10% annual MTF interest rate in India
SLIPPAGE = 0.003            # 0.3% slippage + STT

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

def run_india_leveraged_backtest(leverage_ratio=1.0, num_stocks=10):
    price_pivot, qualifying_dict = load_india_data()
    all_tickers = price_pivot.columns.tolist()

    dates = sorted(price_pivot.index)
    dates_df = pd.DataFrame({'Date': dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    # Sharpe 3M Risk-Adjusted Momentum Formula
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

        # Evaluate portfolio NAV
        pos_val_sum = sum([pos['shares'] * (price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']) for s, pos in current_positions.items()])
        current_nav = current_cash + pos_val_sum

        if current_nav <= 0:
            equity_curve.append({'Date': rebal_date, 'Value': 0.0})
            break

        # Deduct margin interest if leveraged
        if leverage_ratio > 1.0:
            borrowed_debt = current_nav * (leverage_ratio - 1.0)
            monthly_interest = borrowed_debt * (INDIAN_MTF_INTEREST / 12.0)
            current_nav -= monthly_interest

        equity_curve.append({'Date': rebal_date, 'Value': current_nav})

        if rebal_date not in mom_pivot.index:
            continue

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

        sorted_candidates = sorted(mom_scores.items(), key=lambda x: x[1], reverse=True)[:num_stocks]
        top_n = set([x[0] for x in sorted_candidates])

        current_holdings = set(current_positions.keys())
        retained = current_holdings.intersection(top_n)
        dropped = current_holdings - retained
        buys = top_n - retained

        # Sell dropped
        for s in dropped:
            pos = current_positions[s]
            p = price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']
            proceeds = pos['shares'] * p * (1.0 - SLIPPAGE)
            current_cash += proceeds
            del current_positions[s]

        # Allocate purchasing power with leverage ratio
        target_purchasing_power = current_nav * leverage_ratio
        current_cash = target_purchasing_power - sum([pos['shares'] * (price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']) for s, pos in current_positions.items()])

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
    if leverage_ratio > 1.0:
        final_val = final_val - (final_val * (leverage_ratio - 1.0) / leverage_ratio)

    num_years = (monthly_dates[-1] - monthly_dates[0]).days / 365.25
    cagr = ((final_val / total_invested) ** (1.0 / num_years) - 1.0) * 100.0 if final_val > 0 else -100.0

    eq_df = pd.DataFrame(equity_curve)
    eq_df['peak'] = eq_df['Value'].cummax()
    max_dd = ((eq_df['Value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min() if not eq_df.empty else -100.0

    return round(final_val, 2), round(cagr, 2), round(max_dd, 2)

def main():
    print("=" * 90, flush=True)
    print("   INDIAN STOCK MARKET LEVERAGED BACKTEST (MTF / FUTURES) (2018 - 2026)   ", flush=True)
    print("=" * 90, flush=True)

    v1, c1, d1 = run_india_leveraged_backtest(leverage_ratio=1.0, num_stocks=10)
    v12, c12, d12 = run_india_leveraged_backtest(leverage_ratio=1.2, num_stocks=10)
    v15, c15, d15 = run_india_leveraged_backtest(leverage_ratio=1.5, num_stocks=10)

    print("\n--- PERFORMANCE ACROSS LEVERAGE RATIOS IN INDIA (2018 - 2026: 8.5 YEARS) ---")
    print(f"1.0x Unleveraged Equity:")
    print(f"  - Final Portfolio Value Today:  ₹{v1:,.2f} | CAGR: {c1}% | Max Drawdown: {d1}%")

    print(f"\n1.2x Moderate MTF Leverage (20% Extra Exposure):")
    print(f"  - Final Portfolio Value Today:  ₹{v12:,.2f} | CAGR: {c12}% | Max Drawdown: {d12}%")

    print(f"\n1.5x Aggressive MTF Leverage (50% Extra Exposure):")
    print(f"  - Final Portfolio Value Today:  ₹{v15:,.2f} | CAGR: {c15}% | Max Drawdown: {d15}%")

if __name__ == "__main__":
    main()
