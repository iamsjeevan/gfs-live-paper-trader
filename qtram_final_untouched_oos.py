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
    # Get enough history for 200-day SMA, 126-day Mom, 90-day Vol (start 2015-01-01)
    prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE date >= '2015-01-01' AND date <= '2017-12-31' AND close IS NOT NULL", conn)
    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    prices = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').ffill()
    
    comp_df = pd.read_sql_query("SELECT t.symbol AS Ticker, t.market_cap, c.sector FROM technical_valuation_data t LEFT JOIN company_master c ON t.symbol = c.symbol", conn)
    ratios_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, roe, debt_equity FROM financial_ratios WHERE year >= 2015 AND year <= 2017", conn)
    pl_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, total_revenue, net_profit FROM financial_income_statement WHERE year >= 2015 AND year <= 2017", conn)
    
    mkt_cap_dict = dict(zip(comp_df['Ticker'], comp_df['market_cap']))
    conn.close()
    
    pl_sorted = pl_df.sort_values(['Ticker', 'Year'])
    pl_sorted['prev_net_profit'] = pl_sorted.groupby('Ticker')['net_profit'].shift(1)
    pl_sorted['loss_decreasing'] = (pl_sorted['net_profit'] < 0) & (pl_sorted['net_profit'] > pl_sorted['prev_net_profit'])
    pl_sorted['qualifies'] = (pl_sorted['net_profit'] > 0) | (pl_sorted['loss_decreasing'] == True)
    
    qualifying_dict = {}
    for y in [2015, 2016, 2017]:
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
    
    # 0.3% Slippage explicitly calculated via commissions parameter
    test = bt.Backtest(strategy, sim_prices, initial_capital=100000.0, commissions=lambda q, p: abs(q)*p*0.003, integer_positions=False)
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
    
    # Run the Frozen Strategy on 2016-2017
    # Frozen Params: 126m Mom, 90v Vol, Top 10, MC>500, DE<1.5, 0.3% slip
    r = run_strategy(prices, q_dict, 126, 90, "2016-01-01", "2017-12-31", "Untouched_OOS_16_17")
    
    if r:
        out['Untouched_OOS_16_17'] = {
            "CAGR": r['CAGR'],
            "MaxDD": r['Max DD'],
            "Sharpe": r['Sharpe']
        }
    else:
        out['Error'] = "No data to run"
    
    with open("untouched_oos.json", "w") as f:
        json.dump(out, f, indent=2)

if __name__ == "__main__":
    main()
