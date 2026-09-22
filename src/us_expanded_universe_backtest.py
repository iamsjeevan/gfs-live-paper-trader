import pandas as pd
import numpy as np
import yfinance as yf
import datetime

START_DATE = "2019-01-01"
END_DATE = "2026-08-25"
INITIAL_CAPITAL = 10000.0  # $10,000 initial capital
ANNUAL_SIP = 10000.0       # $10,000 annual SIP
SLIPPAGE = 0.001          # 0.1% brokerage + slippage on INDmoney / US brokers

# Expanded US Stocks Universe (Top US Stocks across Tech, Mid-Caps, Small-Caps, Growth, Turnaround)
EXPANDED_US_TICKERS = [
    # Tech Giants & Semiconductors
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'AMD', 'AVGO', 'NFLX',
    'AMAT', 'LRCX', 'KLAC', 'QCOM', 'TXN', 'MU', 'ARM', 'SMCI', 'INTC', 'MRVL',
    
    # High-Growth & SaaS Tech
    'PLTR', 'CRM', 'ORCL', 'ADBE', 'NOW', 'SNOW', 'DDOG', 'NET', 'CRWD', 'PANW',
    'ZS', 'MDB', 'TEAM', 'HUBS', 'PATH', 'SHOP', 'COIN', 'HOOD', 'U',

    # Consumer & Retail
    'COST', 'WMT', 'TGT', 'HD', 'LOW', 'NKE', 'LULU', 'SBUX', 'CMG', 'ROST',
    'TJX', 'BKNG', 'ABNB', 'MAR', 'HLT', 'RCL', 'CCL', 'UBER', 'DASH', 'MELI',

    # Healthcare & Biotech
    'LLY', 'UNH', 'JNJ', 'MRK', 'ABBV', 'PFE', 'TMO', 'DHR', 'ABT', 'ISRG',
    'REGN', 'VRTX', 'BIIB', 'DXCM', 'EW', 'IDXX', 'IQV', 'RMD', 'BMY',

    # Financials & Fintech
    'V', 'MA', 'JPM', 'BAC', 'WFC', 'C', 'GS', 'MS', 'BLK', 'SPGI',
    'MCO', 'SCHW', 'AXP', 'PYPL', 'NU', 'AFRM', 'SOFI', 'UPST', 'COF', 'FITB',

    # Industrials, Aerospace & Energy
    'CAT', 'DE', 'GE', 'HON', 'MMM', 'UNP', 'LMT', 'NOC', 'RTX', 'BA',
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'MPC', 'VLO', 'PSX', 'OXY',

    # Turnaround & High-Beta Momentum
    'ENPH', 'FSLR', 'SEDG', 'RIVN', 'LCID', 'DKNG', 'RBLX', 'CVNA'
]

def download_us_expanded_prices():
    print(f"[INDMONEY US DOWNLOAD] Downloading price data for {len(EXPANDED_US_TICKERS)} INDmoney US stocks + S&P 500 benchmark (^GSPC)...", flush=True)
    all_tickers = EXPANDED_US_TICKERS + ['^GSPC']
    data = yf.download(all_tickers, start="2018-01-01", end=END_DATE, auto_adjust=True, progress=False, threads=True)
    
    if isinstance(data.columns, pd.MultiIndex):
        close_df = data['Close']
    else:
        close_df = data
    
    print(f"[DOWNLOAD SUCCESS] Loaded price matrix: {close_df.shape[0]} trading days across {close_df.shape[1]} tickers.", flush=True)
    return close_df

def run_us_momentum_backtest(close_df, num_stocks=10):
    sp50_prices = close_df['^GSPC'].dropna()
    valid_tickers = [t for t in EXPANDED_US_TICKERS if t in close_df.columns]
    stock_prices = close_df[valid_tickers].dropna(how='all').ffill().bfill()

    dates = sorted(stock_prices.index)
    dates_df = pd.DataFrame({'date': dates})
    dates_df['ym'] = dates_df['date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['date'].min().tolist()
    monthly_dates = [d for d in monthly_dates if pd.to_datetime(START_DATE) <= d <= pd.to_datetime(END_DATE)]

    sma_50_pivot = stock_prices.rolling(50).mean()
    high_52w_pivot = stock_prices.rolling(252).max()
    mom_3m_pivot = stock_prices.pct_change(63)

    current_cash = INITIAL_CAPITAL
    total_invested = INITIAL_CAPITAL
    equity_curve = []
    current_positions = {}
    last_sip_year = None

    for i in range(len(monthly_dates) - 1):
        rebal_date = monthly_dates[i]
        next_rebal_date = monthly_dates[i + 1]

        # Annual SIP Inflow ($10,000 added every January)
        if last_sip_year is None or rebal_date.year > last_sip_year:
            if last_sip_year is not None:
                current_cash += ANNUAL_SIP
                total_invested += ANNUAL_SIP
            last_sip_year = rebal_date.year

        # Evaluate portfolio value before rebalance
        total_val = current_cash
        for sym, pos in current_positions.items():
            if rebal_date in stock_prices.index and sym in stock_prices.columns:
                p_val = stock_prices.loc[rebal_date, sym]
                p = float(p_val.iloc[0]) if isinstance(p_val, pd.Series) else float(p_val)
                if pd.isna(p): p = pos['entry_price']
            else:
                p = pos['entry_price']
            total_val += pos['shares'] * p

        equity_curve.append({'date': rebal_date, 'value': total_val})

        if rebal_date not in mom_3m_pivot.index:
            continue

        available_symbols = stock_prices.columns.tolist()

        mom_scores = {}
        for s in available_symbols:
            if s in mom_3m_pivot.columns:
                m_val = mom_3m_pivot.loc[rebal_date, s]
                p_val = stock_prices.loc[rebal_date, s]
                h52_val = high_52w_pivot.loc[rebal_date, s] if s in high_52w_pivot.columns else None
                s50_val = sma_50_pivot.loc[rebal_date, s] if s in sma_50_pivot.columns else None

                m = float(m_val.iloc[0]) if isinstance(m_val, pd.Series) else float(m_val)
                p = float(p_val.iloc[0]) if isinstance(p_val, pd.Series) else float(p_val)
                h52 = float(h52_val.iloc[0]) if (h52_val is not None and isinstance(h52_val, pd.Series)) else float(h52_val) if h52_val is not None else None
                s50 = float(s50_val.iloc[0]) if (s50_val is not None and isinstance(s50_val, pd.Series)) else float(s50_val) if s50_val is not None else None

                if pd.notna(m) and pd.notna(p) and p > 0:
                    if s50 is not None and pd.notna(s50) and p < s50:
                        continue
                    
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
            if rebal_date in stock_prices.index and s in stock_prices.columns:
                p_val = stock_prices.loc[rebal_date, s]
                p = float(p_val.iloc[0]) if isinstance(p_val, pd.Series) else float(p_val)
            else:
                p = pos['entry_price']
            
            proceeds = pos['shares'] * p * (1.0 - SLIPPAGE)
            current_cash += proceeds
            del current_positions[s]

        # Execute Buys
        if buys and current_cash > 0:
            alloc = current_cash / len(buys)
            for s in buys:
                p_val = stock_prices.loc[rebal_date, s]
                p = float(p_val.iloc[0]) if isinstance(p_val, pd.Series) else float(p_val)
                entry_p = p * (1.0 + SLIPPAGE)
                shares = alloc / entry_p
                current_positions[s] = {'entry_price': p, 'shares': shares}
                current_cash -= alloc

    final_date = monthly_dates[-1]
    final_val = current_cash
    current_holdings_list = []
    for s, pos in current_positions.items():
        if final_date in stock_prices.index and s in stock_prices.columns:
            p_val = stock_prices.loc[final_date, s]
            p = float(p_val.iloc[0]) if isinstance(p_val, pd.Series) else float(p_val)
        else:
            p = pos['entry_price']
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
    eq_df['peak'] = eq_df['value'].cummax()
    max_dd = ((eq_df['value'] - eq_df['peak']) / eq_df['peak'] * 100.0).min()

    # Benchmark calculation
    bench_p0 = sp50_prices.loc[monthly_dates[0]]
    p0_val = float(bench_p0.iloc[0]) if isinstance(bench_p0, pd.Series) else float(bench_p0)
    bench_units = INITIAL_CAPITAL / p0_val
    bench_invested = INITIAL_CAPITAL
    last_bench_year = None
    for d in monthly_dates:
        if last_bench_year is None or d.year > last_bench_year:
            if last_bench_year is not None:
                p_val = sp50_prices.loc[d]
                p = float(p_val.iloc[0]) if isinstance(p_val, pd.Series) else float(p_val)
                bench_units += ANNUAL_SIP / p
                bench_invested += ANNUAL_SIP
            last_bench_year = d.year
    
    bench_p_end = sp50_prices.loc[monthly_dates[-1]]
    pend_val = float(bench_p_end.iloc[0]) if isinstance(bench_p_end, pd.Series) else float(bench_p_end)
    bench_final = bench_units * pend_val
    bench_tot_ret = (bench_final - bench_invested) / bench_invested * 100.0
    bench_cagr = ((bench_final / bench_invested) ** (1.0 / num_years) - 1.0) * 100.0

    return {
        'num_stocks': num_stocks,
        'total_invested': total_invested,
        'final_val': final_val,
        'net_profit': net_profit,
        'total_return': total_return,
        'cagr': cagr,
        'max_dd': max_dd,
        'bench_final': bench_final,
        'bench_cagr': bench_cagr,
        'bench_ret': bench_tot_ret,
        'holdings': current_holdings_list
    }

def main():
    print("=" * 90, flush=True)
    print("    INDMONEY EXPANDED US STOCKS UNIVERSE (100+ STOCKS) MOMENTUM BACKTEST    ", flush=True)
    print("=" * 90, flush=True)

    close_df = download_us_expanded_prices()
    res10 = run_us_momentum_backtest(close_df, num_stocks=10)
    res20 = run_us_momentum_backtest(close_df, num_stocks=20)

    print("\n--- 1. PERFORMANCE COMPARISON VS S&P 500 BENCHMARK (2019 - 2026) ---", flush=True)
    print(f"Total Capital Invested:              ${res10['total_invested']:,.0f} ($10k Initial + $10k Annual SIP)")
    
    print(f"\n10-Stock Expanded US Momentum:")
    print(f"  - Final Portfolio Value:            ${res10['final_val']:,.2f}")
    print(f"  - Net Profit Made:                  ${res10['net_profit']:,.2f}")
    print(f"  - Total Return (%):                 +{res10['total_return']:.2f}%")
    print(f"  - CAGR (%):                         {res10['cagr']:.2f}%")
    print(f"  - Max Drawdown (%):                 {res10['max_dd']:.2f}%")

    print(f"\n20-Stock Expanded US Momentum:")
    print(f"  - Final Portfolio Value:            ${res20['final_val']:,.2f}")
    print(f"  - Net Profit Made:                  ${res20['net_profit']:,.2f}")
    print(f"  - Total Return (%):                 +{res20['total_return']:.2f}%")
    print(f"  - CAGR (%):                         {res20['cagr']:.2f}%")
    print(f"  - Max Drawdown (%):                 {res20['max_dd']:.2f}%")

    print(f"\nS&P 500 Benchmark (^GSPC SIP):")
    print(f"  - Final Benchmark Value:            ${res10['bench_final']:,.2f}")
    print(f"  - Total Return (%):                 +{res10['bench_ret']:.2f}%")
    print(f"  - CAGR (%):                         {res10['bench_cagr']:.2f}%")

    print("\n--- 2. CURRENT EXPANDED US 10-STOCK PORTFOLIO HOLDINGS TODAY (AUG 2026) ---", flush=True)
    h_df = pd.DataFrame(res10['holdings'])
    print(h_df.to_string(index=False), flush=True)

if __name__ == "__main__":
    main()
