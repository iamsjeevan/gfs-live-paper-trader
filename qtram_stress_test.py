import sqlite3
import pandas as pd
import numpy as np
import bt
import json
import warnings
warnings.filterwarnings('ignore')

INDIA_DB = "data/nse_stocks_all_years.db"

# Base Parameters
BASE_MCAP = 500.0
BASE_DE = 1.5
BASE_SIZE = 10
BASE_MOM = 63
BASE_VOL = 60
BASE_SLIP = 0.003

def load_data():
    conn = sqlite3.connect(INDIA_DB)
    prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE date >= '2016-01-01' AND close IS NOT NULL", conn)
    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    prices = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').ffill()
    
    comp_df = pd.read_sql_query("SELECT symbol AS Ticker, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, total_revenue, net_profit FROM financial_income_statement", conn)
    conn.close()
    
    mkt_cap_dict = dict(zip(comp_df['Ticker'], comp_df['market_cap']))
    pl_sorted = pl_df.sort_values(['Ticker', 'Year'])
    pl_sorted['prev_net_profit'] = pl_sorted.groupby('Ticker')['net_profit'].shift(1)
    pl_sorted['loss_decreasing'] = (pl_sorted['net_profit'] < 0) & (pl_sorted['net_profit'] > pl_sorted['prev_net_profit'])
    pl_sorted['qualifies'] = (pl_sorted['net_profit'] > 0) | (pl_sorted['loss_decreasing'] == True)
    
    return prices, mkt_cap_dict, ratios_df, pl_sorted

def run_backtest(prices, mkt_cap_dict, ratios_df, pl_sorted, mcap_cutoff, de_cutoff, top_n, mom_lookback, vol_lookback, slippage, name):
    qualifying_dict = {}
    for y in range(2016, 2027):
        r_sub = ratios_df[ratios_df['Year'] == y]
        p_sub = pl_sorted[pl_sorted['Year'] == y]
        merged = pd.merge(r_sub, p_sub[['Ticker', 'Year', 'qualifies']], on=['Ticker', 'Year'], how='inner')
        q_set = set(merged[(merged['qualifies'] == True) & (merged['debt_equity'] <= de_cutoff)]['Ticker'])
        qualifying_dict[y] = [s for s in prices.columns if (mkt_cap_dict.get(s, 0) >= mcap_cutoff) and (s in q_set)]
        
    sma200 = prices.rolling(window=200).mean()
    sma50 = prices.rolling(window=50).mean()
    
    ret = prices.pct_change(mom_lookback)
    vol = prices.pct_change().rolling(vol_lookback).std()
    mom_score = ret / (vol + 1e-6)
    
    target_weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    dates_df = pd.DataFrame({'Date': prices.index})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()
    start_date = pd.to_datetime('2018-01-01')
    rebal_set = set([d for d in monthly_dates if d >= start_date])
    all_days = prices.index[prices.index >= start_date]
    
    current_portfolio = []
    current_alloc = 0.0
    
    for date in all_days:
        if date in rebal_set:
            target_year = date.year - 1
            available = qualifying_dict.get(target_year, prices.columns.tolist())
            if date in mom_score.index:
                current_scores = mom_score.loc[date, available].dropna()
                valid_entry = []
                for t in current_scores.index:
                    p = prices.loc[date, t]
                    s200 = sma200.loc[date, t]
                    s50 = sma50.loc[date, t]
                    if p > s200 and p >= s50:
                        valid_entry.append(t)
                current_scores = current_scores.loc[valid_entry]
                if not current_scores.empty:
                    top = current_scores.nlargest(top_n).index.tolist()
                    current_portfolio = top
                    current_alloc = 1.0 / len(top)
                else:
                    current_portfolio = []
                    current_alloc = 0.0
                    
        surviving = []
        for t in current_portfolio:
            if prices.loc[date, t] >= sma50.loc[date, t]:
                surviving.append(t)
        current_portfolio = surviving
        
        for t in current_portfolio:
            target_weights.loc[date, t] = current_alloc

    strategy = bt.Strategy(name, [
        bt.algos.RunDaily(),
        bt.algos.SelectAll(),
        bt.algos.WeighTarget(target_weights),
        bt.algos.Rebalance()
    ])
    
    test = bt.Backtest(strategy, prices, initial_capital=100000.0, commissions=lambda q, p: abs(q)*p*slippage, integer_positions=False)
    res = bt.run(test)
    stats = res.stats.iloc[:, 0]
    return {
        "Name": name,
        "CAGR": stats['cagr'] * 100,
        "Max DD": stats['max_drawdown'] * 100,
        "Sharpe": stats['daily_sharpe'],
        "res": res
    }

def main():
    print("Loading data...")
    prices, mkt_cap_dict, ratios_df, pl_sorted = load_data()
    
    results = []
    
    # Base
    base_res = run_backtest(prices, mkt_cap_dict, ratios_df, pl_sorted, BASE_MCAP, BASE_DE, BASE_SIZE, BASE_MOM, BASE_VOL, BASE_SLIP, "Base")
    results.append(base_res)
    
    # MCap Sens
    for v in [300, 750, 1000]:
        results.append(run_backtest(prices, mkt_cap_dict, ratios_df, pl_sorted, v, BASE_DE, BASE_SIZE, BASE_MOM, BASE_VOL, BASE_SLIP, f"MCap_{v}"))
        
    # DE Sens
    for v in [1.0, 2.0]:
        results.append(run_backtest(prices, mkt_cap_dict, ratios_df, pl_sorted, BASE_MCAP, v, BASE_SIZE, BASE_MOM, BASE_VOL, BASE_SLIP, f"DE_{v}"))
        
    # Size Sens
    for v in [5, 15, 20]:
        results.append(run_backtest(prices, mkt_cap_dict, ratios_df, pl_sorted, BASE_MCAP, BASE_DE, v, BASE_MOM, BASE_VOL, BASE_SLIP, f"Size_{v}"))
        
    # Mom Sens
    for v in [42, 126]:
        results.append(run_backtest(prices, mkt_cap_dict, ratios_df, pl_sorted, BASE_MCAP, BASE_DE, BASE_SIZE, v, BASE_VOL, BASE_SLIP, f"Mom_{v}"))
        
    # Vol Sens
    for v in [30, 90]:
        results.append(run_backtest(prices, mkt_cap_dict, ratios_df, pl_sorted, BASE_MCAP, BASE_DE, BASE_SIZE, BASE_MOM, v, BASE_SLIP, f"Vol_{v}"))
        
    # Slip Sens
    for v in [0.005, 0.0075, 0.010]:
        results.append(run_backtest(prices, mkt_cap_dict, ratios_df, pl_sorted, BASE_MCAP, BASE_DE, BASE_SIZE, BASE_MOM, BASE_VOL, v, f"Slip_{v}"))
        
    # Sub-periods on Base
    eq_curve = base_res['res'].prices.iloc[:, 0]
    
    periods = {
        "Pre-COVID Bull (2018-2019)": ("2018-01-01", "2019-12-31"),
        "COVID Crash (Feb-Apr 2020)": ("2020-02-01", "2020-04-30"),
        "Post-COVID Bull (May 2020 - 2021)": ("2020-05-01", "2021-12-31"),
        "Correction (2022)": ("2022-01-01", "2022-12-31"),
        "Recent Bull (2023-2026)": ("2023-01-01", "2026-08-31"),
    }
    
    sub_results = []
    for p_name, (start, end) in periods.items():
        sub_eq = eq_curve.loc[start:end]
        if len(sub_eq) > 0:
            ret = (sub_eq.iloc[-1] / sub_eq.iloc[0]) - 1
            days = (sub_eq.index[-1] - sub_eq.index[0]).days
            cagr = ((1 + ret) ** (365.25 / max(1, days)) - 1) * 100 if days > 0 else 0
            peak = sub_eq.cummax()
            dd = ((sub_eq - peak) / peak).min() * 100
            sub_results.append({
                "Period": p_name,
                "CAGR": cagr,
                "Max DD": dd
            })
            
    out = {
        "Sensitivity": [{"Name": r["Name"], "CAGR": r["CAGR"], "Max DD": r["Max DD"], "Sharpe": r["Sharpe"]} for r in results],
        "SubPeriods": sub_results
    }
    
    with open("stress_test_results.json", "w") as f:
        json.dump(out, f, indent=2)
        
    print("Stress test complete. Results saved to stress_test_results.json")

if __name__ == "__main__":
    main()
