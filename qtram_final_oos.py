import sqlite3
import pandas as pd
import numpy as np
import bt
import json
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
        
    return prices, qualifying_dict

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
                    
        surviving = []
        for t in current_portfolio:
            if prices.loc[date, t] >= sma50.loc[date, t]:
                surviving.append(t)
        current_portfolio = surviving
        
        alloc = 1.0 / 10.0
        for t in current_portfolio:
            target_weights.loc[date, t] = alloc
            
    target_weights = target_weights.loc[sim_days]
    sim_prices = prices.loc[sim_days]
    
    strategy = bt.Strategy(name, [
        bt.algos.RunDaily(),
        bt.algos.SelectAll(),
        bt.algos.WeighTarget(target_weights),
        bt.algos.Rebalance()
    ])
    
    test = bt.Backtest(strategy, sim_prices, initial_capital=100000.0, integer_positions=False)
    res = bt.run(test)
    
    stats = res.stats.iloc[:, 0]
    return {
        "CAGR": stats['cagr'] * 100, 
        "Max DD": stats['max_drawdown'] * 100, 
        "Sharpe": stats['daily_sharpe']
    }

def main():
    prices, q_dict = load_data()
    out = {}
    
    # 1. Train 2018-2021, Test 2022
    best_sharpe = -99
    best_params = None
    for m in [42, 63, 126]:
        for v in [30, 60, 90]:
            r = run_strategy(prices, q_dict, m, v, "2018-01-01", "2021-12-31", f"T1_{m}_{v}")
            if r and r['Sharpe'] > best_sharpe:
                best_sharpe = r['Sharpe']
                best_params = (m, v)
                
    r_oos = run_strategy(prices, q_dict, best_params[0], best_params[1], "2022-01-01", "2022-12-31", "Test_2022")
    out['OOS_2022'] = {
        "Train_Params": best_params, "Test_CAGR": r_oos['CAGR'], "Test_MaxDD": r_oos['Max DD'], "Test_Sharpe": r_oos['Sharpe']
    }
    
    # 2. Train 2020-2023, Test 2018-2019
    best_sharpe2 = -99
    best_params2 = None
    for m in [42, 63, 126]:
        for v in [30, 60, 90]:
            r = run_strategy(prices, q_dict, m, v, "2020-01-01", "2023-12-31", f"T2_{m}_{v}")
            if r and r['Sharpe'] > best_sharpe2:
                best_sharpe2 = r['Sharpe']
                best_params2 = (m, v)
                
    r_oos2 = run_strategy(prices, q_dict, best_params2[0], best_params2[1], "2018-01-01", "2019-12-31", "Test_1819")
    out['OOS_1819'] = {
        "Train_Params": best_params2, "Test_CAGR": r_oos2['CAGR'], "Test_MaxDD": r_oos2['Max DD'], "Test_Sharpe": r_oos2['Sharpe']
    }
    
    # 3. Explicitly test 6-Month hypothesis (126m, 60v) on the worst regimes
    r_6m_2022 = run_strategy(prices, q_dict, 126, 60, "2022-01-01", "2022-12-31", "6M_2022")
    r_6m_1819 = run_strategy(prices, q_dict, 126, 60, "2018-01-01", "2019-12-31", "6M_1819")
    
    out['Fixed_6M_Tests'] = {
        "2022_CAGR": r_6m_2022['CAGR'], "2022_MaxDD": r_6m_2022['Max DD'], "2022_Sharpe": r_6m_2022['Sharpe'],
        "1819_CAGR": r_6m_1819['CAGR'], "1819_MaxDD": r_6m_1819['Max DD'], "1819_Sharpe": r_6m_1819['Sharpe']
    }
    
    with open("final_oos.json", "w") as f:
        json.dump(out, f, indent=2)

if __name__ == "__main__":
    main()
