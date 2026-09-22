import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"
START_DATE = "2021-01-01"
END_DATE = "2026-08-01"
INITIAL_CAPITAL = 100000.0

STRICT_SLIPPAGE = 0.005  # 0.5% trade cost per execution (0.1% fee + 0.4% bid-ask spread)

def load_data():
    conn = sqlite3.connect(DB_PATH)
    prices_df = pd.read_sql_query("SELECT symbol, date, close, high_52w, sma_50 FROM daily_prices WHERE date >= '2020-01-01' AND close IS NOT NULL", conn)
    comp_df = pd.read_sql_query("SELECT symbol, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol, year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol, year, net_profit FROM financial_income_statement", conn)
    conn.close()

    prices_df['date'] = pd.to_datetime(prices_df['date'])
    return prices_df, comp_df, ratios_df, pl_df

def run_strict_stress_test(num_stocks=20, enforce_lag=True):
    prices_df, comp_df, ratios_df, pl_df = load_data()
    mkt_cap_dict = dict(zip(comp_df['symbol'], comp_df['market_cap']))

    dates_df = pd.DataFrame({'date': sorted(prices_df['date'].unique())})
    dates_df['ym'] = dates_df['date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    price_pivot = prices_df.pivot(index='date', columns='symbol', values='close')
    high_52w_pivot = prices_df.pivot(index='date', columns='symbol', values='high_52w')
    sma_50_pivot = prices_df.pivot(index='date', columns='symbol', values='sma_50')
    mom_3m_pivot = price_pivot.pct_change(63)

    current_cash = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}  # {symbol: {'entry_price': p, 'shares': s}}

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

        # Evaluate portfolio value correctly at rebal_date
        total_val = current_cash
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            total_val += pos['shares'] * p

        equity_curve.append({'date': rebal_date, 'value': total_val})

        # Strict Fundamental Lag (e.g. FY20 data visible only after October 2020)
        target_year = rebal_date.year - 2 if (enforce_lag and rebal_date.month < 10) else rebal_date.year - 1
        
        r_sub = ratios_df[ratios_df['year'] == target_year]
        p_sub = pl_df[pl_df['year'] == target_year]
        merged = pd.merge(r_sub, p_sub[['symbol', 'year', 'net_profit']], on=['symbol', 'year'], how='inner')

        qualifying_fund_syms = set(merged[
            (merged['roe'] >= 10.0) & 
            (merged['debt_equity'] <= 1.5) & 
            (merged['net_profit'] > 0)
        ]['symbol'])

        # Filter universe (MktCap >= 500 Cr + Fundamental Quality)
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

        # Execute Sells with 0.5% slippage
        for s in dropped:
            pos = current_positions[s]
            p = price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']
            proceeds = pos['shares'] * p * (1.0 - STRICT_SLIPPAGE)
            current_cash += proceeds
            del current_positions[s]

        # Execute Buys for new entries using available cash
        if buys and current_cash > 0:
            target_cash_per_buy = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + STRICT_SLIPPAGE)
                shares = target_cash_per_buy / entry_p
                current_positions[s] = {'entry_price': p, 'shares': shares}
                current_cash -= target_cash_per_buy

    final_date = monthly_dates[-1]
    final_val = current_cash
    for s, pos in current_positions.items():
        p = price_pivot.loc[final_date, s] if (final_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[final_date, s])) else pos['entry_price']
        final_val += pos['shares'] * p

    num_years = (monthly_dates[-1] - monthly_dates[0]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / num_years) - 1.0) * 100.0
    
    eq_df = pd.DataFrame(equity_curve)
    eq_df['peak'] = eq_df['value'].cummax()
    max_dd = ((eq_df['value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    return round(final_val, 2), round(cagr, 2), round(max_dd, 2)

def main():
    print("=" * 75, flush=True)
    print("      STRICT REALISM STRESS TEST (2021-2026 Point-In-Time Window)      ", flush=True)
    print("=" * 75, flush=True)

    v1, c1, d1 = run_strict_stress_test(num_stocks=10, enforce_lag=True)
    v2, c2, d2 = run_strict_stress_test(num_stocks=20, enforce_lag=True)
    v3, c3, d3 = run_strict_stress_test(num_stocks=25, enforce_lag=True)

    print(f"\nStrict 10-Stock Strategy  | Final: ₹{v1:,.0f} | CAGR: {c1}% | Max Drawdown: {d1}%", flush=True)
    print(f"Strict 20-Stock Strategy  | Final: ₹{v2:,.0f} | CAGR: {c2}% | Max Drawdown: {d2}%", flush=True)
    print(f"Strict 25-Stock Strategy  | Final: ₹{v3:,.0f} | CAGR: {c3}% | Max Drawdown: {d3}%", flush=True)

if __name__ == "__main__":
    main()
