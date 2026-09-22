import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0  # ₹1 Lakh
SLIPPAGE = 0.005           # 0.5% trade execution cost

def load_prices():
    conn = sqlite3.connect(DB_PATH)
    prices_df = pd.read_sql_query("""
    SELECT symbol, date, close, high_52w, sma_50 
    FROM daily_prices 
    WHERE close IS NOT NULL
    """, conn)
    comp_df = pd.read_sql_query("SELECT symbol, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol, year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol, year, net_profit FROM financial_income_statement", conn)
    conn.close()

    prices_df['date'] = pd.to_datetime(prices_df['date'])
    return prices_df, comp_df, ratios_df, pl_df

def run_bear_scenario(scenario_name, start_date, end_date, num_stocks=10, use_quality=True):
    prices_df, comp_df, ratios_df, pl_df = load_prices()
    mkt_cap_dict = dict(zip(comp_df['symbol'], comp_df['market_cap']))

    dates = sorted(prices_df['date'].unique())
    dates_df = pd.DataFrame({'date': dates})
    dates_df['ym'] = dates_df['date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(start_date) <= d <= pd.to_datetime(end_date)]

    price_pivot = prices_df.pivot(index='date', columns='symbol', values='close')
    high_52w_pivot = prices_df.pivot(index='date', columns='symbol', values='high_52w')
    sma_50_pivot = prices_df.pivot(index='date', columns='symbol', values='sma_50')
    mom_3m_pivot = price_pivot.pct_change(63)

    current_cash = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

        # Evaluate portfolio value correctly: cash + current position value
        total_val = current_cash
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            total_val += pos['shares'] * p

        equity_curve.append({'date': rebal_date, 'value': total_val})

        # Qualification filter
        target_year = rebal_date.year - 1
        r_sub = ratios_df[ratios_df['year'] == target_year]
        p_sub = pl_df[pl_df['year'] == target_year]
        merged = pd.merge(r_sub, p_sub[['symbol', 'year', 'net_profit']], on=['symbol', 'year'], how='inner')

        qualifying_fund_syms = set(merged[
            (merged['roe'] >= 10.0) & 
            (merged['debt_equity'] <= 1.5) & 
            (merged['net_profit'] > 0)
        ]['symbol']) if use_quality else set(price_pivot.columns)

        available = [
            s for s in price_pivot.columns 
            if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in qualifying_fund_syms)
        ]

        mom_scores = {}
        for s in available:
            if s in mom_3m_pivot.columns:
                m = mom_3m_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                h52 = high_52w_pivot.loc[rebal_date, s] if s in high_52w_pivot.columns else None
                s50 = sma_50_pivot.loc[rebal_date, s] if s in sma_50_pivot.columns else None

                if pd.notna(m) and pd.notna(p) and p > 0:
                    if s50 is not None and pd.notna(s50) and p < s50: continue
                    prox = (p / h52) if (h52 and pd.notna(h52) and h52 > 0) else 0.8
                    mom_scores[s] = m * 0.7 + prox * 0.3

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
    for s, pos in current_positions.items():
        p = price_pivot.loc[final_date, s] if (final_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[final_date, s])) else pos['entry_price']
        final_val += pos['shares'] * p

    equity_curve.append({'date': final_date, 'value': final_val})
    eq_df = pd.DataFrame(equity_curve)

    eq_df['peak'] = eq_df['value'].cummax()
    eq_df['drawdown'] = (eq_df['value'] - eq_df['peak']) / eq_df['peak'] * 100.0
    
    max_drawdown = eq_df['drawdown'].min()
    lowest_portfolio_val = eq_df['value'].min()
    max_loss_pct = (lowest_portfolio_val - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100.0

    breakeven_row = eq_df[(eq_df['date'] > monthly_dates[0]) & (eq_df['value'] >= INITIAL_CAPITAL)].head(1)
    breakeven_months = (breakeven_row['date'].iloc[0] - monthly_dates[0]).days // 30 if not breakeven_row.empty else "Not Recovered"

    return {
        'Scenario': scenario_name,
        'Start Date': start_date,
        'End Date': end_date,
        'Initial Capital': f"₹{INITIAL_CAPITAL:,.0f}",
        'Worst Dip Value (Lowest ₹)': f"₹{lowest_portfolio_val:,.0f}",
        'Max Portfolio Loss (%)': f"{max_loss_pct:.2f}%",
        'Max Drawdown Peak-to-Trough (%)': f"{max_drawdown:.2f}%",
        'Months to Recovery / Breakeven': f"{breakeven_months} months",
        'Final Portfolio Value': f"₹{final_val:,.0f}"
    }

def main():
    print("=" * 85, flush=True)
    print("      BEAR MARKET & MARKET CRASH STRESS TEST (\"WORST TIME TO START\")      ", flush=True)
    print("=" * 85, flush=True)

    s1 = run_bear_scenario("COVID Crash (Started Jan 2020)", "2020-01-01", "2021-06-01", num_stocks=10)
    s2 = run_bear_scenario("Inflation Bear Market (Started Oct 2021)", "2021-10-01", "2023-01-01", num_stocks=10)
    s3 = run_bear_scenario("COVID Crash - 20 Stocks (Started Jan 2020)", "2020-01-01", "2021-06-01", num_stocks=20)

    res_df = pd.DataFrame([s1, s2, s3])
    print("\n" + res_df.to_string(index=False), flush=True)

if __name__ == "__main__":
    main()
