import sqlite3
import pandas as pd
import numpy as np
import json

INDIA_DB = "data/nse_stocks_all_years.db"
START_CAPITAL = 100000.0  # ₹1 Lakh

def generate_live_portfolios():
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
    print(f"Latest Price Date in DB: {latest_date.strftime('%Y-%m-%d')}")

    # Net Income Profitability / Turnaround filter
    pl_sorted = pl_df.sort_values(['Ticker', 'Year'])
    pl_sorted['prev_net_profit'] = pl_sorted.groupby('Ticker')['net_profit'].shift(1)
    pl_sorted['loss_decreasing'] = (pl_sorted['net_profit'] < 0) & (pl_sorted['net_profit'] > pl_sorted['prev_net_profit'])
    pl_sorted['qualifies'] = (pl_sorted['net_profit'] > 0) | (pl_sorted['loss_decreasing'] == True)

    target_year = 2025
    r_sub = ratios_df[ratios_df['Year'] == target_year]
    p_sub = pl_sorted[pl_sorted['Year'] == target_year]
    merged = pd.merge(r_sub, p_sub[['Ticker', 'Year', 'qualifies']], on=['Ticker', 'Year'], how='inner')
    q_set = set(merged[(merged['qualifies'] == True) & (merged['debt_equity'] <= 1.5)]['Ticker'])
    qualifying_stocks = [s for s in price_pivot.columns if (mkt_cap_dict.get(s, 0) >= 500.0) and (s in q_set)]

    # Calculate 200 SMA & 50 SMA
    sma_200 = price_pivot.rolling(200).mean().loc[latest_date]
    sma_50 = price_pivot.rolling(50).mean().loc[latest_date]
    latest_prices = price_pivot.loc[latest_date]

    # Momentum Formulas
    m3_ret = price_pivot.pct_change(63).loc[latest_date]
    m6_1m_ret = ((price_pivot.shift(21) / price_pivot.shift(126)) - 1.0).loc[latest_date]
    m12_1m_ret = ((price_pivot.shift(21) / price_pivot.shift(252)) - 1.0).loc[latest_date]
    vol60 = price_pivot.pct_change().rolling(60).std().loc[latest_date]

    sharpe_3m = m3_ret / (vol60 + 1e-6)
    vol_adj_6m = m6_1m_ret / (vol60 + 1e-6)

    # 10 Portfolio Variant Definitions
    portfolio_configs = [
      {"id": 1, "name": "P1: Flagship 10-Stock (3-Tier Dynamic + Sharpe 3M + 200 SMA)", "stocks": 10, "mom": "SHARPE_3M", "trend": "200SMA", "leverage": "3TIER", "target_lev": 1.5},
      {"id": 2, "name": "P2: 20-Stock Diversified (3-Tier Dynamic + Sharpe 3M + 200 SMA)", "stocks": 20, "mom": "SHARPE_3M", "trend": "200SMA", "leverage": "3TIER", "target_lev": 1.5},
      {"id": 3, "name": "P3: Pure 1.0x Cash Only (10-Stock + 200 SMA)", "stocks": 10, "mom": "SHARPE_3M", "trend": "200SMA", "leverage": "1.0", "target_lev": 1.0},
      {"id": 4, "name": "P4: Moderate 1.25x MTF Leverage (10-Stock + 200 SMA)", "stocks": 10, "mom": "SHARPE_3M", "trend": "200SMA", "leverage": "1.25", "target_lev": 1.25},
      {"id": 5, "name": "P5: Aggressive 1.5x MTF Leverage (10-Stock + 200 SMA)", "stocks": 10, "mom": "SHARPE_3M", "trend": "200SMA", "leverage": "1.5", "target_lev": 1.5},
      {"id": 6, "name": "P6: Vol-Adjusted 6M-1M Momentum (10-Stock + 3-Tier)", "stocks": 10, "mom": "VOL_ADJ_6M", "trend": "200SMA", "leverage": "3TIER", "target_lev": 1.5},
      {"id": 7, "name": "P7: Academic 12M-1M Momentum (10-Stock + 3-Tier)", "stocks": 10, "mom": "M12_1M", "trend": "200SMA", "leverage": "3TIER", "target_lev": 1.5},
      {"id": 8, "name": "P8: Fast 50 SMA Trend Filter (10-Stock + 3-Tier)", "stocks": 10, "mom": "SHARPE_3M", "trend": "50SMA", "leverage": "3TIER", "target_lev": 1.5},
      {"id": 9, "name": "P9: No Trend Filter Aggressive (10-Stock + 1.5x MTF)", "stocks": 10, "mom": "SHARPE_3M", "trend": "NONE", "leverage": "1.5", "target_lev": 1.5},
      {"id": 10, "name": "P10: 20-Stock Academic 12M-1M (1.25x MTF)", "stocks": 20, "mom": "M12_1M", "trend": "200SMA", "leverage": "1.25", "target_lev": 1.25},
    ]

    all_portfolios_json = []

    for cfg in portfolio_configs:
      num_s = cfg["stocks"]
      mom_type = cfg["mom"]
      trend_type = cfg["trend"]
      target_lev = cfg["target_lev"]

      # Select momentum series
      if mom_type == "SHARPE_3M":
        scores = sharpe_3m
      elif mom_type == "VOL_ADJ_6M":
        scores = vol_adj_6m
      elif mom_type == "M12_1M":
        scores = m12_1m_ret
      else:
        scores = m3_ret

      eligible = []
      for s in qualifying_stocks:
        p = latest_prices.get(s, 0)
        s200_val = sma_200.get(s, 0)
        s50_val = sma_50.get(s, 0)
        sc = scores.get(s, np.nan)

        if pd.isna(p) or p <= 0 or pd.isna(sc):
          continue

        if trend_type == "200SMA" and (pd.isna(s200_val) or p < s200_val):
          continue
        elif trend_type == "50SMA" and (pd.isna(s50_val) or p < s50_val):
          continue

        eligible.append((s, float(sc), float(p), float(s200_val) if pd.notna(s200_val) else p * 0.85))

      eligible.sort(key=lambda x: x[1], reverse=True)
      selected = eligible[:num_s]

      total_purchasing_power = START_CAPITAL * target_lev
      alloc_per_stock = total_purchasing_power / num_s

      holdings_list = []
      for rank, (sym, score, p, s200_v) in enumerate(selected, 1):
        shares = int(np.floor(alloc_per_stock / (p * 1.003)))
        pos_val = shares * p
        mtf_exp = max(pos_val - (START_CAPITAL / num_s), 0.0)

        holdings_list.append({
          "symbol": sym,
          "name": sym,
          "entryPrice": round(p, 2),
          "currentPrice": round(p, 2),
          "shares": shares,
          "positionValue": round(pos_val, 2),
          "returnPct": 0.0,
          "stopLossPrice": round(s200_v, 2),
          "sma200": round(s200_v, 2),
          "status": "HOLDING",
          "momentumRank": rank,
          "mtfExposure": round(mtf_exp, 2)
        })

      all_portfolios_json.append({
        "id": cfg["id"],
        "name": cfg["name"],
        "numStocks": num_s,
        "momentumFormula": mom_type,
        "trendFilter": trend_type,
        "leverageMode": cfg["leverage"],
        "targetLeverage": target_lev,
        "initialCapital": START_CAPITAL,
        "currentNav": START_CAPITAL,
        "holdings": holdings_list
      })

    with open("dashboard/src/data/live10Portfolios.json", "w") as f:
      json.dump(all_portfolios_json, f, indent=2)

    print("Successfully generated live10Portfolios.json with 10 starting portfolios initialized TODAY!")

if __name__ == "__main__":
    generate_live_portfolios()
