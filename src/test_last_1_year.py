import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"
START_DATE = "2025-08-25"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 100000.0
COST_PER_TRADE = 0.003  # 0.3% total slippage & brokerage

def load_data():
    conn = sqlite3.connect(DB_PATH)
    prices_df = pd.read_sql_query("""
    SELECT symbol, date, close, high_52w, sma_50 
    FROM daily_prices 
    WHERE date >= '2024-08-01' AND close IS NOT NULL
    """, conn)
    comp_df = pd.read_sql_query("SELECT symbol, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol, year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol, year, net_profit FROM financial_income_statement", conn)
    conn.close()

    prices_df['date'] = pd.to_datetime(prices_df['date'])
    return prices_df, comp_df, ratios_df, pl_df

def run_1year_test(num_stocks=10, use_quality=True):
    prices_df, comp_df, ratios_df, pl_df = load_data()
    mkt_cap_dict = dict(zip(comp_df['symbol'], comp_df['market_cap']))

    dates = sorted(prices_df['date'].unique())
    dates_df = pd.DataFrame({'date': dates})
    dates_df['ym'] = dates_df['date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    price_pivot = prices_df.pivot(index='date', columns='symbol', values='close')
    high_52w_pivot = prices_df.pivot(index='date', columns='symbol', values='high_52w')
    sma_50_pivot = prices_df.pivot(index='date', columns='symbol', values='sma_50')
    mom_3m_pivot = price_pivot.pct_change(63)

    current_cash = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}
    monthly_trade_history = []

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

        # Portfolio value before rebalance
        total_val = current_cash
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            total_val += pos['shares'] * p

        equity_curve.append({'date': rebal_date, 'value': total_val})

        # Fundamentals filter (FY24 / FY25 reporting)
        target_year = 2024 if rebal_date.year == 2025 else 2025
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
            proceeds = pos['shares'] * p * (1.0 - COST_PER_TRADE)
            current_cash += proceeds
            del current_positions[s]

        # Execute Buys
        if buys and current_cash > 0:
            alloc = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + COST_PER_TRADE)
                shares = alloc / entry_p
                current_positions[s] = {'entry_price': p, 'shares': shares}
                current_cash -= alloc

        monthly_trade_history.append({
            'date': rebal_date.strftime('%Y-%m-%d'),
            'portfolio_value': round(total_val, 2),
            'retained_count': len(retained),
            'buys': list(buys),
            'sells': list(dropped)
        })

    # Evaluate final value today (Aug 25, 2026)
    final_date = monthly_dates[-1]
    final_val = current_cash
    current_portfolio_holdings = []
    for s, pos in current_positions.items():
        p = price_pivot.loc[final_date, s] if (final_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[final_date, s])) else pos['entry_price']
        pos_val = pos['shares'] * p
        gain_pct = (p - pos['entry_price']) / pos['entry_price'] * 100.0
        final_val += pos_val
        current_portfolio_holdings.append({
            'symbol': s,
            'entry_price': round(pos['entry_price'], 2),
            'current_price': round(p, 2),
            'return_pct': f"{gain_pct:+.2f}%",
            'holding_value': f"₹{pos_val:,.0f}"
        })

    net_profit = final_val - INITIAL_CAPITAL
    return_pct = (net_profit / INITIAL_CAPITAL) * 100.0

    return {
        'num_stocks': num_stocks,
        'start_date': START_DATE,
        'end_date': END_DATE,
        'initial_capital': INITIAL_CAPITAL,
        'final_value': round(final_val, 2),
        'net_profit': round(net_profit, 2),
        'return_pct': round(return_pct, 2),
        'holdings': current_portfolio_holdings,
        'history': monthly_trade_history
    }

def main():
    print("=" * 80, flush=True)
    print("   EXACT 1-YEAR TEST: AUG 25, 2025 TO AUG 25, 2026 (INITIAL ₹1 LAKH)   ", flush=True)
    print("=" * 80, flush=True)

    res_10 = run_1year_test(num_stocks=10, use_quality=True)
    res_20 = run_1year_test(num_stocks=20, use_quality=True)

    print("\n--- 1. OVERALL 1-YEAR PERFORMANCE SUMMARY ---", flush=True)
    print(f"Starting Capital (Aug 25, 2025):  ₹1,00,000")
    print(f"\n10-Stock Quality Momentum:")
    print(f"  - Final Portfolio Value Today:  ₹{res_10['final_value']:,.2f}")
    print(f"  - Net Profit Made in 1 Year:   ₹{res_10['net_profit']:,.2f}")
    print(f"  - 1-Year Total Return (%):      +{res_10['return_pct']:.2f}%")

    print(f"\n20-Stock Quality Momentum:")
    print(f"  - Final Portfolio Value Today:  ₹{res_20['final_value']:,.2f}")
    print(f"  - Net Profit Made in 1 Year:   ₹{res_20['net_profit']:,.2f}")
    print(f"  - 1-Year Total Return (%):      +{res_20['return_pct']:.2f}%")

    print("\n--- 2. CURRENT 10-STOCK PORTFOLIO HOLDINGS TODAY (AUG 25, 2026) ---", flush=True)
    h_df = pd.DataFrame(res_10['holdings'])
    print(h_df.to_string(index=False), flush=True)

if __name__ == "__main__":
    main()
