import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/nse_stocks_all_years.db"
START_DATE = "2019-01-01"
END_DATE = "2026-08-01"
INITIAL_CAPITAL = 100000.0
SLIPPAGE = 0.003

def load_data():
    conn = sqlite3.connect(DB_PATH)
    prices_df = pd.read_sql_query("SELECT symbol, date, close, high_52w FROM daily_prices WHERE date >= '2018-01-01' AND close IS NOT NULL", conn)
    comp_df = pd.read_sql_query("SELECT symbol, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol, year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol, year, total_revenue, net_profit FROM financial_income_statement", conn)
    conn.close()

    prices_df['date'] = pd.to_datetime(prices_df['date'])
    return prices_df, comp_df, ratios_df, pl_df

def run_no_ma_backtest(num_stocks=10, use_ma_filter=False):
    prices_df, comp_df, ratios_df, pl_df = load_data()
    mkt_cap_dict = dict(zip(comp_df['symbol'], comp_df['market_cap']))

    dates = sorted(prices_df['date'].unique())
    dates_df = pd.DataFrame({'date': dates})
    dates_df['ym'] = dates_df['date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    price_pivot = prices_df.pivot(index='date', columns='symbol', values='close')
    high_52w_pivot = prices_df.pivot(index='date', columns='symbol', values='high_52w')
    mom_3m_pivot = price_pivot.pct_change(63)

    pl_sorted = pl_df.sort_values(['symbol', 'year'])
    pl_sorted['prev_net_profit'] = pl_sorted.groupby('symbol')['net_profit'].shift(1)
    pl_sorted['loss_decreasing'] = pl_sorted['net_profit'] > pl_sorted['prev_net_profit']

    current_cash = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]

        total_val = current_cash
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            total_val += pos['shares'] * p

        equity_curve.append({'date': rebal_date, 'value': total_val})

        target_year = rebal_date.year - 1
        r_sub = ratios_df[ratios_df['year'] == target_year]
        p_sub = pl_sorted[pl_sorted['year'] == target_year]
        merged = pd.merge(r_sub, p_sub[['symbol', 'year', 'net_profit', 'prev_net_profit', 'loss_decreasing']], on=['symbol', 'year'], how='inner')

        qualifying = set(merged[
            ((merged['net_profit'] > 0) | (merged['loss_decreasing'] == True)) &
            (merged['debt_equity'] <= 1.5)
        ]['symbol'])

        available = [
            s for s in price_pivot.columns 
            if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in qualifying)
        ]

        mom_scores = {}
        for s in available:
            if s in mom_3m_pivot.columns:
                m = mom_3m_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                h52 = high_52w_pivot.loc[rebal_date, s] if s in high_52w_pivot.columns else None

                if pd.notna(m) and pd.notna(p) and p > 0:
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

    num_years = (monthly_dates[-1] - monthly_dates[0]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / num_years) - 1.0) * 100.0

    eq_df = pd.DataFrame(equity_curve)
    eq_df['peak'] = eq_df['value'].cummax()
    max_dd = ((eq_df['value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    return round(final_val, 2), round(cagr, 2), round(max_dd, 2)

def main():
    print("=" * 80, flush=True)
    print("      BACKTEST RESULTS: WITH NO MOVING AVERAGE RULES      ", flush=True)
    print("=" * 80, flush=True)

    v1, c1, d1 = run_no_ma_backtest(num_stocks=10, use_ma_filter=False)
    v2, c2, d2 = run_no_ma_backtest(num_stocks=20, use_ma_filter=False)

    print(f"\n10-Stock Portfolio (No Moving Average Filter):")
    print(f"  - Final Portfolio Value: ₹{v1:,.2f} | CAGR: {c1}% | Max Drawdown: {d1}%")

    print(f"\n20-Stock Portfolio (No Moving Average Filter):")
    print(f"  - Final Portfolio Value: ₹{v2:,.2f} | CAGR: {c2}% | Max Drawdown: {d2}%")

if __name__ == "__main__":
    main()
