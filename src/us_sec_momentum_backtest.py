import sqlite3
import pandas as pd
import numpy as np

DB_NAME = "instocks.db"
START_DATE = "2020-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 10000.0  # $10,000 Initial Capital
ANNUAL_SIP = 10000.0       # $10,000 Annual SIP
SLIPPAGE = 0.001          # 0.1% US equity trade execution cost

def load_sec_db_data():
    print("[SEC BACKTEST SETUP] Loading 10+ years SEC EDGAR fundamentals and daily prices from instocks.db...", flush=True)
    conn = sqlite3.connect(DB_NAME)

    # Load daily prices
    prices_df = pd.read_sql_query("""
    SELECT Ticker, Date, Adj_Close 
    FROM daily_prices 
    WHERE Date >= '2019-01-01' AND Adj_Close IS NOT NULL
    """, conn)

    # Load company metrics
    comp_df = pd.read_sql_query("SELECT Ticker, Market_Cap FROM company_metrics", conn)

    # Load Income Statements (SEC EDGAR)
    inc_df = pd.read_sql_query("""
    SELECT Ticker, Date, Total_Revenue, Net_Income 
    FROM income_statements 
    WHERE Net_Income IS NOT NULL
    """, conn)

    # Load Balance Sheets (SEC EDGAR)
    bs_df = pd.read_sql_query("""
    SELECT Ticker, Date, Total_Assets, Total_Liabilities, Total_Equity 
    FROM balance_sheets 
    WHERE Total_Equity IS NOT NULL AND Total_Equity > 0
    """, conn)

    conn.close()

    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    inc_df['Year'] = pd.to_datetime(inc_df['Date']).dt.year
    bs_df['Year'] = pd.to_datetime(bs_df['Date']).dt.year

    price_pivot = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').dropna(how='all').ffill().bfill()
    print(f"[DATA LOADED] Prices: {price_pivot.shape[0]} trading days across {price_pivot.shape[1]} US equities.", flush=True)
    return price_pivot, comp_df, inc_df, bs_df

def run_us_turnaround_loss_shrinking_backtest(num_stocks=10):
    price_pivot, comp_df, inc_df, bs_df = load_sec_db_data()

    dates = sorted(price_pivot.index)
    dates_df = pd.DataFrame({'Date': dates})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    high_52w_pivot = price_pivot.rolling(252).max()
    mom_3m_pivot = price_pivot.pct_change(63)

    # SEC Income Statements YoY profit calculation
    inc_sorted = inc_df.sort_values(['Ticker', 'Year'])
    inc_sorted['Prev_Net_Income'] = inc_sorted.groupby('Ticker')['Net_Income'].shift(1)
    
    # Explicit Rule:
    # 1. Profitable: Net_Income > 0
    # 2. Loss-Making Turnaround: Net_Income < 0 AND Net_Income > Prev_Net_Income (Loss Shrinking YoY!)
    inc_sorted['Loss_Making_And_Shrinking'] = (inc_sorted['Net_Income'] < 0) & (inc_sorted['Net_Income'] > inc_sorted['Prev_Net_Income'])
    inc_sorted['Profitable'] = inc_sorted['Net_Income'] > 0
    inc_sorted['Qualifies_Fundamental'] = inc_sorted['Profitable'] | inc_sorted['Loss_Making_And_Shrinking']

    current_cash = INITIAL_CAPITAL
    total_invested = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}
    completed_trades = []
    last_sip_year = None

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]
        next_rebal_date = monthly_dates[i + 1]

        # Annual SIP Cash Addition ($10,000 added every January)
        if last_sip_year is None or rebal_date.year > last_sip_year:
            if last_sip_year is not None:
                current_cash += ANNUAL_SIP
                total_invested += ANNUAL_SIP
            last_sip_year = rebal_date.year

        # Evaluate portfolio value before rebalance
        total_val = current_cash
        for sym, pos in current_positions.items():
            p = price_pivot.loc[rebal_date, sym] if (rebal_date in price_pivot.index and sym in price_pivot.columns and pd.notna(price_pivot.loc[rebal_date, sym])) else pos['entry_price']
            total_val += pos['shares'] * p

        equity_curve.append({'Date': rebal_date, 'Value': total_val, 'Invested': total_invested})

        if rebal_date not in mom_3m_pivot.index:
            continue

        target_year = rebal_date.year - 1
        inc_sub = inc_sorted[inc_sorted['Year'] == target_year]
        bs_sub = bs_df[bs_df['Year'] == target_year]
        merged = pd.merge(inc_sub, bs_sub[['Ticker', 'Year', 'Total_Liabilities', 'Total_Equity']], on=['Ticker', 'Year'], how='inner')
        merged['Debt_Equity'] = merged['Total_Liabilities'] / merged['Total_Equity']

        # Filter: Qualifies_Fundamental (Profitable OR Loss-Making but Shrinking Loss) AND Debt/Equity <= 1.5
        qualifying = set(merged[
            (merged['Qualifies_Fundamental'] == True) &
            (merged['Debt_Equity'] <= 1.5)
        ]['Ticker'])

        available_symbols = [s for s in price_pivot.columns if s in qualifying]

        # Rank Momentum Leaderboard (3M Return 70% + 52W High Proximity 30%)
        mom_scores = {}
        for s in available_symbols:
            if s in mom_3m_pivot.columns:
                m = mom_3m_pivot.loc[rebal_date, s]
                p = price_pivot.loc[rebal_date, s]
                h52 = high_52w_pivot.loc[rebal_date, s] if s in high_52w_pivot.columns else None

                if pd.notna(m) and pd.notna(p) and p > 0:
                    prox = (p / h52) if (h52 and pd.notna(h52) and h52 > 0) else 0.8
                    mom_scores[s] = m * 0.7 + prox * 0.3

        if not mom_scores:
            continue

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
            cost_basis = pos['shares'] * pos['entry_price']
            net_profit = proceeds - cost_basis
            
            completed_trades.append({
                'symbol': s,
                'entry_date': pos['entry_date'],
                'exit_date': rebal_date,
                'holding_days': (rebal_date - pos['entry_date']).days,
                'return_pct': (net_profit / cost_basis) * 100.0,
                'is_winner': net_profit > 0
            })

            current_cash += proceeds
            del current_positions[s]

        # Execute Buys
        if buys and current_cash > 0:
            alloc = current_cash / len(buys)
            for s in buys:
                p = price_pivot.loc[rebal_date, s]
                entry_p = p * (1.0 + SLIPPAGE)
                shares = alloc / entry_p
                current_positions[s] = {'entry_price': p, 'shares': shares, 'entry_date': rebal_date}
                current_cash -= alloc

    final_date = monthly_dates[-1]
    final_val = current_cash
    current_holdings_list = []
    for s, pos in current_positions.items():
        p = price_pivot.loc[final_date, s] if (final_date in price_pivot.index and s in price_pivot.columns and pd.notna(price_pivot.loc[final_date, s])) else pos['entry_price']
        pos_val = pos['shares'] * p
        gain_pct = (p - pos['entry_price']) / pos['entry_price'] * 100.0
        final_val += pos_val
        current_holdings_list.append({
            'symbol': s,
            'entry_price': round(pos['entry_price'], 2),
            'current_price': round(p, 2),
            'return_pct': f"{gain_pct:+.2f}%",
            'position_value': f"${pos_val:,.0f}"
        })

    net_profit = final_val - total_invested
    total_return = (net_profit / total_invested) * 100.0
    num_years = (monthly_dates[-1] - monthly_dates[0]).days / 365.25
    cagr = ((final_val / total_invested) ** (1.0 / num_years) - 1.0) * 100.0

    eq_df = pd.DataFrame(equity_curve)
    eq_df['peak'] = eq_df['Value'].cummax()
    max_dd = ((eq_df['Value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    trades_df = pd.DataFrame(completed_trades)
    winning_trades = trades_df[trades_df['is_winner'] == True] if not trades_df.empty else pd.DataFrame()
    losing_trades = trades_df[trades_df['is_winner'] == False] if not trades_df.empty else pd.DataFrame()

    win_rate = (len(winning_trades) / len(trades_df) * 100.0) if not trades_df.empty else 0.0
    avg_hold_win = winning_trades['holding_days'].mean() if not winning_trades.empty else 0.0
    avg_hold_loss = losing_trades['holding_days'].mean() if not losing_trades.empty else 0.0

    return {
        'num_stocks': num_stocks,
        'total_invested': total_invested,
        'final_val': final_val,
        'net_profit': net_profit,
        'total_return': total_return,
        'cagr': cagr,
        'max_dd': max_dd,
        'win_rate': win_rate,
        'avg_hold_win': avg_hold_win,
        'avg_hold_loss': avg_hold_loss,
        'holdings': current_holdings_list
    }

def main():
    print("=" * 90, flush=True)
    print(" US EQUITIES INCLUDING LOSS-MAKING TURNAROUND (SHRINKING LOSS) STOCKS BACKTEST ", flush=True)
    print("=" * 90, flush=True)

    res10 = run_us_turnaround_loss_shrinking_backtest(num_stocks=10)
    res20 = run_us_turnaround_loss_shrinking_backtest(num_stocks=20)

    print("\n--- 1. BACKTEST PERFORMANCE SUMMARY (2020 - 2026) ---", flush=True)
    print(f"Total Capital Invested:              ${res10['total_invested']:,.0f} ($10k Initial + $10k Annual SIP)")
    
    print(f"\n10-Stock US (Including Loss-Making Shrinking Loss Stocks):")
    print(f"  - Final Portfolio Value Today:      ${res10['final_val']:,.2f}")
    print(f"  - Net Profit Made:                  ${res10['net_profit']:,.2f}")
    print(f"  - Total Return (%):                 +{res10['total_return']:.2f}%")
    print(f"  - Compound Annual Growth (CAGR):    {res10['cagr']:.2f}%")
    print(f"  - Max Drawdown (%):                 {res10['max_dd']:.2f}%")
    print(f"  - Win Rate (%):                     {res10['win_rate']:.1f}%")
    print(f"  - Avg Hold Period (Winners):        {res10['avg_hold_win']:.0f} days")
    print(f"  - Avg Hold Period (Losers):         {res10['avg_hold_loss']:.0f} days")

    print(f"\n20-Stock US (Including Loss-Making Shrinking Loss Stocks):")
    print(f"  - Final Portfolio Value Today:      ${res20['final_val']:,.2f}")
    print(f"  - Net Profit Made:                  ${res20['net_profit']:,.2f}")
    print(f"  - Total Return (%):                 +{res20['total_return']:.2f}%")
    print(f"  - Compound Annual Growth (CAGR):    {res20['cagr']:.2f}%")
    print(f"  - Max Drawdown (%):                 {res20['max_dd']:.2f}%")
    print(f"  - Win Rate (%):                     {res20['win_rate']:.1f}%")
    print(f"  - Avg Hold Period (Winners):        {res20['avg_hold_win']:.0f} days")
    print(f"  - Avg Hold Period (Losers):         {res20['avg_hold_loss']:.0f} days")

    print("\n--- 2. CURRENT US 10-STOCK PORTFOLIO HOLDINGS TODAY (AUG 2026) ---", flush=True)
    h_df = pd.DataFrame(res10['holdings'])
    print(h_df.to_string(index=False), flush=True)

if __name__ == "__main__":
    main()
