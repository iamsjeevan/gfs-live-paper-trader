import sqlite3
import pandas as pd
import numpy as np

DB_NAME = "instocks.db"
START_DATE = "2007-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 10000.0  # $10,000 Initial Capital
ANNUAL_SIP = 10000.0       # $10,000 Annual SIP
MARGIN_INTEREST_RATE = 0.05  # 5% annual margin borrowing rate
SLIPPAGE = 0.001

def load_sec_2007_data():
    conn = sqlite3.connect(DB_NAME)
    prices_df = pd.read_sql_query("SELECT Ticker, Date, Adj_Close FROM daily_prices WHERE Date >= '2006-01-01' AND Adj_Close IS NOT NULL", conn)
    inc_df = pd.read_sql_query("SELECT Ticker, Date, Net_Income FROM income_statements WHERE Net_Income IS NOT NULL", conn)
    bs_df = pd.read_sql_query("SELECT Ticker, Date, Total_Liabilities, Total_Equity FROM balance_sheets WHERE Total_Equity IS NOT NULL AND Total_Equity > 0", conn)
    conn.close()

    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    inc_df['Year'] = pd.to_datetime(inc_df['Date']).dt.year
    bs_df['Year'] = pd.to_datetime(bs_df['Date']).dt.year

    price_pivot = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').dropna(how='all').ffill().bfill()

    inc_sorted = inc_df.sort_values(['Ticker', 'Year'])
    inc_sorted['Prev_Net_Income'] = inc_sorted.groupby('Ticker')['Net_Income'].shift(1)
    inc_sorted['Qualifies'] = (inc_sorted['Net_Income'] > 0) | ((inc_sorted['Net_Income'] < 0) & (inc_sorted['Net_Income'] > inc_sorted['Prev_Net_Income']))

    return price_pivot, inc_sorted, bs_df

def run_leveraged_backtest(leverage_ratio=1.0, num_stocks=20):
    price_pivot, inc_sorted, bs_df = load_sec_2007_data()
    stock_tickers = [c for c in price_pivot.columns if c != '^GSPC']

    dates = sorted(price_pivot.index)
    dates_df = pd.DataFrame({'Date': dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    # Vol-Adjusted 6M-1M Momentum Formula
    m6_1m = (price_pivot[stock_tickers].shift(21) / price_pivot[stock_tickers].shift(126)) - 1.0
    vol60 = price_pivot[stock_tickers].pct_change().rolling(60).std()
    mom_pivot = m6_1m / (vol60 + 1e-6)

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
        pos_val_sum = 0.0
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            pos_val_sum += pos['shares'] * p

        current_nav = current_cash + pos_val_sum
        if current_nav <= 0:
            equity_curve.append({'Date': rebal_date, 'Value': 0.0})
            break

        # Deduct margin cost if leveraged
        if leverage_ratio > 1.0:
            margin_debt = current_nav * (leverage_ratio - 1.0)
            monthly_interest = margin_debt * (MARGIN_INTEREST_RATE / 12.0)
            current_nav -= monthly_interest

        equity_curve.append({'Date': rebal_date, 'Value': current_nav})

        if rebal_date not in mom_pivot.index:
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
                shares = alloc_per_buy / entry_p
                current_positions[s] = {'entry_price': p, 'shares': shares}
                current_cash -= alloc_per_buy

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
    print("      US LEVERAGED QUANT MOMENTUM BACKTEST (2007 - 2026: 19.5 YEARS)      ", flush=True)
    print("=" * 90, flush=True)

    v1, c1, d1 = run_leveraged_backtest(leverage_ratio=1.0, num_stocks=20)
    v12, c12, d12 = run_leveraged_backtest(leverage_ratio=1.2, num_stocks=20)
    v15, c15, d15 = run_leveraged_backtest(leverage_ratio=1.5, num_stocks=20)

    print("\n--- PERFORMANCE ACROSS LEVERAGE RATIOS (2007 - 2026: 19.5 YEARS) ---")
    print(f"1.0x Leverage (No Margin):")
    print(f"  - Final Portfolio Value Today:  ${v1:,.2f} | CAGR: {c1}% | Max Drawdown: {d1}%")

    print(f"\n1.2x Moderate Leverage (20% Margin):")
    print(f"  - Final Portfolio Value Today:  ${v12:,.2f} | CAGR: {c12}% | Max Drawdown: {d12}%")

    print(f"\n1.5x Aggressive Leverage (50% Margin):")
    print(f"  - Final Portfolio Value Today:  ${v15:,.2f} | CAGR: {c15}% | Max Drawdown: {d15}%")

if __name__ == "__main__":
    main()
