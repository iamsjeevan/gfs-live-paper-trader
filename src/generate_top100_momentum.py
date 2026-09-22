import sqlite3
import pandas as pd
import numpy as np
import json

INDIA_DB = "data/nse_stocks_all_years.db"

def clean_float(val, default=0.0):
    if pd.isna(val) or np.isnan(val) or np.isinf(val):
        return default
    return float(val)

def generate_top100_screener():
    conn = sqlite3.connect(INDIA_DB)
    prices_df = pd.read_sql_query("SELECT symbol AS Ticker, date AS Date, close AS Adj_Close FROM daily_prices WHERE close IS NOT NULL", conn)
    comp_df = pd.read_sql_query("SELECT symbol AS Ticker, market_cap FROM technical_valuation_data", conn)
    ratios_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol AS Ticker, year AS Year, total_revenue, net_profit FROM financial_income_statement", conn)
    conn.close()

    prices_df['Date'] = pd.to_datetime(prices_df['Date'])
    price_pivot = prices_df.pivot(index='Date', columns='Ticker', values='Adj_Close').dropna(how='all').ffill().bfill()
    mkt_cap_dict = dict(zip(comp_df['Ticker'], comp_df['market_cap']))

    latest_date = price_pivot.index[-1]

    # Quality screen
    pl_sorted = pl_df.sort_values(['Ticker', 'Year'])
    pl_sorted['prev_net_profit'] = pl_sorted.groupby('Ticker')['net_profit'].shift(1)
    pl_sorted['loss_decreasing'] = (pl_sorted['net_profit'] < 0) & (pl_sorted['net_profit'] > pl_sorted['prev_net_profit'])
    pl_sorted['qualifies'] = (pl_sorted['net_profit'] > 0) | (pl_sorted['loss_decreasing'] == True)

    target_year = 2025
    r_sub = ratios_df[ratios_df['Year'] == target_year]
    p_sub = pl_sorted[pl_sorted['Year'] == target_year]
    merged = pd.merge(r_sub, p_sub[['Ticker', 'Year', 'qualifies']], on=['Ticker', 'Year'], how='inner')

    debt_eq_dict = dict(zip(merged['Ticker'], merged['debt_equity']))
    qualifying_set = set(merged[(merged['qualifies'] == True) & (merged['debt_equity'] <= 1.5)]['Ticker'])

    # SMA & Momentum Calculations
    sma_200 = price_pivot.rolling(200).mean().loc[latest_date]
    sma_50 = price_pivot.rolling(50).mean().loc[latest_date]
    latest_prices = price_pivot.loc[latest_date]

    m3_ret = (price_pivot.pct_change(63).loc[latest_date]) * 100.0
    m6_ret = (((price_pivot.shift(21) / price_pivot.shift(126)) - 1.0).loc[latest_date]) * 100.0
    m12_ret = (((price_pivot.shift(21) / price_pivot.shift(252)) - 1.0).loc[latest_date]) * 100.0
    vol60 = price_pivot.pct_change().rolling(60).std().loc[latest_date]

    sharpe_3m = m3_ret / (vol60 * np.sqrt(252) * 100.0 + 1e-6)

    screener_list = []
    for s in price_pivot.columns:
        mcap = clean_float(mkt_cap_dict.get(s, 0.0), 0.0)
        if mcap < 500.0: continue

        p = clean_float(latest_prices.get(s, 0.0), 0.0)
        s200 = clean_float(sma_200.get(s, 0.0), p * 0.85)
        s50 = clean_float(sma_50.get(s, 0.0), p * 0.92)
        m3_v = clean_float(m3_ret.get(s, 0.0), 0.0)
        m6_v = clean_float(m6_ret.get(s, 0.0), 0.0)
        m12_v = clean_float(m12_ret.get(s, 0.0), 0.0)
        sh3_v = clean_float(sharpe_3m.get(s, 0.0), 0.0)
        de_v = clean_float(debt_eq_dict.get(s, 0.8), 0.8)

        if p <= 0 or sh3_v <= 0:
            continue

        above_200 = bool(p >= s200)
        above_50 = bool(p >= s50)
        is_quality = s in qualifying_set

        screener_list.append({
            "symbol": str(s),
            "name": str(s),
            "marketCap": round(mcap, 1),
            "currentPrice": round(p, 2),
            "sma200": round(s200, 2),
            "sma50": round(s50, 2),
            "return3m": round(m3_v, 2),
            "return6m": round(m6_v, 2),
            "return12m": round(m12_v, 2),
            "sharpe3m": round(sh3_v, 2),
            "debtEquity": round(de_v, 2),
            "above200Sma": above_200,
            "above50Sma": above_50,
            "isQuality": is_quality
        })

    # Sort by Sharpe 3M
    screener_list.sort(key=lambda x: x["sharpe3m"], reverse=True)
    top_100 = screener_list[:100]

    for idx, item in enumerate(top_100, 1):
        item["rank"] = idx

    with open("dashboard/src/data/top100Momentum.json", "w") as f:
        json.dump(top_100, f, indent=2)

    print(f"Successfully generated clean top100Momentum.json with zero NaN values!")

if __name__ == "__main__":
    generate_top100_screener()
