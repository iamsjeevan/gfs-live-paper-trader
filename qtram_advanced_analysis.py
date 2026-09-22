import sqlite3
import pandas as pd
import numpy as np
import bt
import json
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

INDIA_DB = "data/nse_stocks_all_years.db"

def load_data():
    conn = sqlite3.connect(INDIA_DB)
    prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE date >= '2016-01-01' AND close IS NOT NULL", conn)
    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    prices = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').ffill()
    
    comp_df = pd.read_sql_query("SELECT t.symbol AS Ticker, t.market_cap, c.sector FROM technical_valuation_data t LEFT JOIN company_master c ON t.symbol = c.symbol", conn)
    ratios_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, total_revenue, net_profit FROM financial_income_statement", conn)
    
    sector_dict = dict(zip(comp_df['Ticker'], comp_df['sector']))
    mkt_cap_dict = dict(zip(comp_df['Ticker'], comp_df['market_cap']))
    conn.close()
    
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
        qualifying_dict[y] = [s for s in prices.columns if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in q_set)]
        
    return prices, qualifying_dict, sector_dict

def run_strategy(prices, qualifying_dict, mom_lookback, vol_lookback, start_date, end_date, name):
    sma200 = prices.rolling(window=200).mean()
    sma50 = prices.rolling(window=50).mean()
    ret = prices.pct_change(mom_lookback)
    vol = prices.pct_change().rolling(vol_lookback).std()
    mom_score = ret / (vol + 1e-6)
    
    target_weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    dates_df = pd.DataFrame({'Date': prices.index})
    dates_df['ym'] = dates_df['Date'].dt.to_period('M')
    monthly_dates = set(dates_df.groupby('ym')['Date'].min().tolist())
    
    current_portfolio = []
    
    # Pre-filter days for speed
    mask = (prices.index >= start_date) & (prices.index <= end_date)
    sim_days = prices.index[mask]
    
    if len(sim_days) == 0: return None
    
    for date in sim_days:
        if date in monthly_dates:
            target_year = date.year - 1
            available = qualifying_dict.get(target_year, prices.columns.tolist())
            if date in mom_score.index:
                scores = mom_score.loc[date, available].dropna()
                valid = []
                for t in scores.index:
                    if prices.loc[date, t] > sma200.loc[date, t] and prices.loc[date, t] >= sma50.loc[date, t]:
                        valid.append(t)
                scores = scores.loc[valid]
                if not scores.empty:
                    current_portfolio = scores.nlargest(10).index.tolist()
                else:
                    current_portfolio = []
                    
        # Daily stop loss
        surviving = []
        for t in current_portfolio:
            if prices.loc[date, t] >= sma50.loc[date, t]:
                surviving.append(t)
        current_portfolio = surviving
        
        alloc = 1.0 / 10.0
        for t in current_portfolio:
            target_weights.loc[date, t] = alloc
            
    # Slice target weights for BT to save memory
    target_weights = target_weights.loc[sim_days]
    sim_prices = prices.loc[sim_days]
    
    strategy = bt.Strategy(name, [
        bt.algos.RunDaily(),
        bt.algos.SelectAll(),
        bt.algos.WeighTarget(target_weights),
        bt.algos.Rebalance()
    ])
    
    test = bt.Backtest(strategy, sim_prices, initial_capital=100000.0, integer_positions=False) # slip handled later
    res = bt.run(test)
    
    stats = res.stats.iloc[:, 0]
    eq = res.prices.iloc[:, 0]
    cagr = stats['cagr'] * 100
    mdd = stats['max_drawdown'] * 100
    sharpe = stats['daily_sharpe']
    
    # Calculate Turnover / Slippage deduction manually for cleaner metrics
    txns = res.get_transactions()
    return {
        "CAGR": cagr, "Max DD": mdd, "Sharpe": sharpe, 
        "res": res, "txns": txns, "weights": target_weights
    }

def main():
    prices, q_dict, sector_dict = load_data()
    out = {}
    
    # 1. Walk-Forward OOS
    print("Running OOS Split 1 (Train 2018-2022, Test 2023-2026)...")
    best_is_sharpe = -99
    best_params = None
    
    for m in [42, 63, 126]:
        for v in [30, 60, 90]:
            r = run_strategy(prices, q_dict, m, v, "2018-01-01", "2022-12-31", f"Train_{m}_{v}")
            if r and r['Sharpe'] > best_is_sharpe:
                best_is_sharpe = r['Sharpe']
                best_params = (m, v)
                
    m_best, v_best = best_params
    r_oos = run_strategy(prices, q_dict, m_best, v_best, "2023-01-01", "2026-08-31", "Test1")
    out['OOS_Split1'] = {
        "Train_Period": "2018-2022", "Train_Best_Params": f"Mom {m_best}, Vol {v_best}",
        "Train_Sharpe": best_is_sharpe,
        "Test_Period": "2023-2026", "Test_CAGR": r_oos['CAGR'], "Test_MaxDD": r_oos['Max DD'], "Test_Sharpe": r_oos['Sharpe']
    }
    
    print("Running OOS Split 2 (Train 2018-2020, Test 2021-2023)...")
    best_is_sharpe2 = -99
    best_params2 = None
    for m in [42, 63, 126]:
        for v in [30, 60, 90]:
            r = run_strategy(prices, q_dict, m, v, "2018-01-01", "2020-12-31", f"Train2_{m}_{v}")
            if r and r['Sharpe'] > best_is_sharpe2:
                best_is_sharpe2 = r['Sharpe']
                best_params2 = (m, v)
                
    m_best2, v_best2 = best_params2
    r_oos2 = run_strategy(prices, q_dict, m_best2, v_best2, "2021-01-01", "2023-12-31", "Test2")
    out['OOS_Split2'] = {
        "Train_Period": "2018-2020", "Train_Best_Params": f"Mom {m_best2}, Vol {v_best2}",
        "Train_Sharpe": best_is_sharpe2,
        "Test_Period": "2021-2023", "Test_CAGR": r_oos2['CAGR'], "Test_MaxDD": r_oos2['Max DD'], "Test_Sharpe": r_oos2['Sharpe']
    }
    
    # 2. Turnover 3m vs 6m
    print("Calculating turnover 3m vs 6m...")
    r3 = run_strategy(prices, q_dict, 63, 60, "2018-01-01", "2026-08-31", "Base3")
    r6 = run_strategy(prices, q_dict, 126, 60, "2018-01-01", "2026-08-31", "Base6")
    t3_count = len(r3['txns'])
    t6_count = len(r6['txns'])
    out['Mom_Comparison'] = {
        "3M_Trades": t3_count, "3M_CAGR": r3['CAGR'],
        "6M_Trades": t6_count, "6M_CAGR": r6['CAGR']
    }
    
    # 3. 2022 Drawdown Analysis
    print("Analyzing 2022 Drawdown...")
    r2022 = run_strategy(prices, q_dict, 63, 60, "2022-01-01", "2022-12-31", "y2022")
    eq = r2022['res'].prices.iloc[:, 0]
    peak = eq.cummax()
    dd = (eq - peak) / peak
    worst_day = dd.idxmin()
    
    # Get portfolio at worst day
    w_df = r2022['weights']
    worst_port = w_df.loc[worst_day]
    worst_port = worst_port[worst_port > 0].index.tolist()
    sectors = [sector_dict.get(t, 'Unknown') for t in worst_port]
    from collections import Counter
    sec_counts = Counter(sectors)
    
    out['2022_Drawdown'] = {
        "Worst_Day": str(worst_day.date()),
        "Max_DD": dd.min() * 100,
        "Sectors_At_Bottom": dict(sec_counts)
    }
    
    with open("advanced_analysis.json", "w") as f:
        json.dump(out, f, indent=2)
    print("Done!")

if __name__ == "__main__":
    main()
