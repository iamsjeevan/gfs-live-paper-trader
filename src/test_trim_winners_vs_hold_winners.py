import sqlite3
import pandas as pd
import numpy as np

INDIA_DB = "data/nse_stocks_all_years.db"
START_DATE = "2020-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 100000.0  # ₹1 Lakh
ANNUAL_SIP = 100000.0       # ₹1 Lakh
SLIPPAGE = 0.003

def load_india_data():
    conn = sqlite3.connect(INDIA_DB)
    prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE date >= '2019-01-01' AND close IS NOT NULL", conn)
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
    for y in range(2018, 2027):
        r_sub = ratios_df[ratios_df['Year'] == y]
        p_sub = pl_sorted[pl_sorted['Year'] == y]
        merged = pd.merge(r_sub, p_sub[['Ticker', 'Year', 'qualifies']], on=['Ticker', 'Year'], how='inner')
        q_set = set(merged[(merged['qualifies'] == True) & (merged['debt_equity'] <= 1.5)]['Ticker'])
        qualifying_dict[y] = [s for s in price_pivot.columns if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in q_set)]

    return price_pivot, qualifying_dict

def run_trimming_backtest(trim_winners_back_to_10=False):
    price_pivot, qualifying_dict = load_india_data()
    mom_3m_pivot = price_pivot.pct_change(63)

    all_dates = sorted(price_pivot.index)
    start_dt = pd.to_datetime(START_DATE)
    end_dt = pd.to_datetime(END_DATE)

    trading_dates = [d for d in all_dates if start_dt <= d <= end_dt]
    dates_df = pd.DataFrame({'Date': trading_dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    rebal_dates = dates_df.groupby('ym')['Date'].min().tolist()

    current_cash = INITIAL_CAPITAL
    total_invested = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}
    last_sip_year = None

    for i in range(len(rebal_dates) - 1):
        rebal_date = rebal_dates[i]

        # Annual SIP
        if last_sip_year is None or rebal_date.year > last_sip_year:
            if last_sip_year is not None:
                current_cash += ANNUAL_SIP
                total_invested += ANNUAL_SIP
            last_sip_year = rebal_date.year

        # Calculate Total Portfolio Equity
        total_val = current_cash
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            total_val += pos['shares'] * p

        equity_curve.append({'date': rebal_date, 'value': total_val})

        target_year = rebal_date.year - 1
        available = qualifying_dict.get(target_year, price_pivot.columns.tolist())

        scores = {}
        for s in available:
            if s in mom_3m_pivot.columns and rebal_date in mom_3m_pivot.index:
                val = mom_3m_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                if pd.notna(val) and pd.notna(p) and p > 0:
                    scores[s] = float(val)

        if not scores: continue

        sorted_candidates = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
        top_n = set([x[0] for x in sorted_candidates])

        current_holdings = set(current_positions.keys())
        retained = current_holdings.intersection(top_n)
        dropped = current_holdings - retained
        buys = top_n - retained

        # Execute Dropped Sells (100% exit for stocks out of Top 10)
        for s in dropped:
            pos = current_positions[s]
            p = price_pivot.loc[rebal_date, s] if (rebal_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, s])) else pos['entry_price']
            proceeds = pos['shares'] * p * (1.0 - SLIPPAGE)
            current_cash += proceeds
            del current_positions[s]

        # Execute Winner Trimming if enabled
        if trim_winners_back_to_10:
            target_cash_per_slot = total_val / 10.0
            for s in list(retained):
                pos = current_positions[s]
                p = price_pivot.loc[rebal_date, s]
                current_pos_val = pos['shares'] * p
                
                # If position drifted above 12% target weight, trim excess back to 10%
                if current_pos_val > (target_cash_per_slot * 1.2):
                    excess_val = current_pos_val - target_cash_per_slot
                    shares_to_sell = int(np.floor(excess_val / p))
                    if shares_to_sell > 0:
                        proceeds = shares_to_sell * p * (1.0 - SLIPPAGE)
                        pos['shares'] -= shares_to_sell
                        current_cash += proceeds

        # Execute Buys for new incoming stocks
        if buys and current_cash > 0:
            alloc = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + SLIPPAGE)
                shares = int(np.floor(alloc / entry_p))
                if shares > 0:
                    cost = shares * entry_p
                    current_positions[s] = {'entry_price': p, 'shares': shares}
                    current_cash -= cost

    final_date = rebal_dates[-1]
    final_val = current_cash
    for s, pos in current_positions.items():
        p = price_pivot.loc[final_date, s] if (final_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[final_date, s])) else pos['entry_price']
        final_val += pos['shares'] * p

    num_years = (rebal_dates[-1] - rebal_dates[0]).days / 365.25
    cagr = ((final_val / total_invested) ** (1.0 / num_years) - 1.0) * 100.0

    eq_df = pd.DataFrame(equity_curve)
    eq_df['peak'] = eq_df['value'].cummax()
    max_dd = ((eq_df['value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    return round(final_val, 2), round(cagr, 2), round(max_dd, 2)

def main():
    print("=" * 90, flush=True)
    print("  HEAD-TO-HEAD: TRIMMING SURGING WINNERS vs LETTING WINNERS RUN  ", flush=True)
    print("=" * 90, flush=True)

    # Option A: Let Winners Run (Leaderboard Retention)
    v1, c1, d1 = run_trimming_backtest(trim_winners_back_to_10=False)
    
    # Option B: Trim Winners back to 10% whenever they exceed 12% weight
    v2, c2, d2 = run_trimming_backtest(trim_winners_back_to_10=True)

    print("\n--- 1. LET WINNERS RUN (DO NOT TRIM RE-TAINED TOP 10 WINNERS) ---")
    print(f"  - Final Portfolio Value Today: ₹{v1:,.2f}")
    print(f"  - Compound Annual Growth (CAGR): {c1}%")
    print(f"  - Max Drawdown (%): {d1}%")

    print("\n--- 2. TRIM WINNERS (SELL EXCESS IF POSITION > 12% WEIGHT) ---")
    print(f"  - Final Portfolio Value Today: ₹{v2:,.2f}")
    print(f"  - Compound Annual Growth (CAGR): {c2}%")
    print(f"  - Max Drawdown (%): {d2}%")

if __name__ == "__main__":
    main()
