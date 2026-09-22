import sqlite3
import pandas as pd
import numpy as np
import bt
import warnings
warnings.filterwarnings('ignore')

print("Loading Data for bt framework...")
INDIA_DB = "data/nse_stocks_all_years.db"

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

qualifying_dict = {}
for y in range(2016, 2027):
    r_sub = ratios_df[ratios_df['Year'] == y]
    p_sub = pl_sorted[pl_sorted['Year'] == y]
    merged = pd.merge(r_sub, p_sub[['Ticker', 'Year', 'qualifies']], on=['Ticker', 'Year'], how='inner')
    q_set = set(merged[(merged['qualifies'] == True) & (merged['debt_equity'] <= 1.5)]['Ticker'])
    qualifying_dict[y] = [s for s in prices.columns if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in q_set)]

print("Calculating technicals for different metrics...")
sma200 = prices.rolling(window=200).mean()
sma50 = prices.rolling(window=50).mean()

# Core Indicators
ret_3m = prices.pct_change(63)
ret_6m = prices.pct_change(126)
vol_60d = prices.pct_change().rolling(60).std()
vol_120d = prices.pct_change().rolling(120).std()

# Momentum Metric Definitions
metrics = {
    "Pure_Return_3M": ret_3m,
    "Sharpe_RiskAdj_3M": ret_3m / (vol_60d + 1e-6),
    "Sharpe_RiskAdj_6M": ret_6m / (vol_120d + 1e-6)
}

dates_df = pd.DataFrame({'Date': prices.index})
dates_df['ym'] = dates_df['Date'].dt.to_period('M')
monthly_dates = dates_df.groupby('ym')['Date'].min().tolist()
start_date = pd.to_datetime('2018-01-01')
monthly_dates = [d for d in monthly_dates if d >= start_date]
all_days = prices.index[prices.index >= start_date]
rebal_set = set(monthly_dates)

results = []

print("Running Backtest Matrix (Metrics x Weightings)...\n")

for mom_name, mom_score in metrics.items():
    for weight_type in ["Equal_Weight", "Inverse_Volatility"]:
        print(f"Testing -> Score: {mom_name} | Weights: {weight_type}")
        
        target_weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        current_portfolio = []
        current_weights_dict = {}

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
                        top_10 = current_scores.nlargest(10).index.tolist()
                        current_portfolio = top_10
                        
                        # Weighting Logic
                        if weight_type == "Equal_Weight":
                            w = 1.0 / len(top_10)
                            current_weights_dict = {t: w for t in top_10}
                        elif weight_type == "Inverse_Volatility":
                            vols = vol_60d.loc[date, top_10]
                            inv_vols = 1.0 / (vols + 1e-6)
                            total_inv_vol = inv_vols.sum()
                            current_weights_dict = {t: inv_vols[t] / total_inv_vol for t in top_10}
                    else:
                        current_portfolio = []
                        current_weights_dict = {}
                        
            # Daily 50 SMA Exit Check
            surviving_portfolio = []
            for t in current_portfolio:
                p = prices.loc[date, t]
                s50 = sma50.loc[date, t]
                if p >= s50:
                    surviving_portfolio.append(t)
                    
            current_portfolio = surviving_portfolio
            
            # If a stock was dropped mid-month, we just set its weight to 0. 
            # The cash is naturally held by the algo until the next rebalance.
            # Normalizing weights for survivors is optional, but setting dropped to 0 holds them in cash.
            for t in current_portfolio:
                target_weights.loc[date, t] = current_weights_dict.get(t, 0)

        # Build Strategy
        strategy = bt.Strategy(f'{mom_name}_{weight_type}', [
            bt.algos.RunDaily(),
            bt.algos.SelectAll(),
            bt.algos.WeighTarget(target_weights),
            bt.algos.Rebalance()
        ])

        test = bt.Backtest(strategy, prices, initial_capital=100000.0, commissions=lambda q, p: abs(q)*p*0.003)
        res = bt.run(test)
        
        stats = res.stats.iloc[:, 0]
        cagr = stats['cagr'] * 100
        mdd = stats['max_drawdown'] * 100
        sharpe = stats['daily_sharpe']
        
        results.append({
            "Momentum Score": mom_name,
            "Weighting": weight_type,
            "CAGR (%)": round(cagr, 2),
            "Max DD (%)": round(mdd, 2),
            "Sharpe": round(sharpe, 2)
        })

print("\n" + "="*70)
print("              STRATEGY LEADERBOARD (2018 - 2026)")
print("="*70)
res_df = pd.DataFrame(results).sort_values(by="CAGR (%)", ascending=False).reset_index(drop=True)
print(res_df.to_string())
print("="*70)
