import sqlite3
import pandas as pd
import numpy as np
import bt
import quantstats as qs
import warnings

warnings.filterwarnings("ignore")

DB_PATH = "data/nse_stocks_all_years.db"
START_DATE = "2019-01-01"
END_DATE = "2026-08-01"
INITIAL_CAPITAL = 1000000.0  # ₹10 Lakhs initial capital

def load_data():
    print("[BT SETUP] Loading price history and fundamentals from SQLite database...", flush=True)
    conn = sqlite3.connect(DB_PATH)
    
    # Load prices
    prices_df = pd.read_sql_query("""
    SELECT symbol, date, close 
    FROM daily_prices 
    WHERE date >= '2018-01-01' AND close IS NOT NULL
    """, conn)
    
    # Load company master
    comp_df = pd.read_sql_query("SELECT symbol, company_name, market_cap FROM technical_valuation_data", conn)
    
    # Load fundamental ratios by year
    ratios_df = pd.read_sql_query("SELECT symbol, year, roe, debt_equity FROM financial_ratios", conn)
    pl_df = pd.read_sql_query("SELECT symbol, year, total_revenue, net_profit FROM financial_income_statement", conn)
    
    conn.close()

    prices_df['date'] = pd.to_datetime(prices_df['date'])
    price_pivot = prices_df.pivot(index='date', columns='symbol', values='close').dropna(how='all')
    price_pivot = price_pivot.ffill().bfill()

    print(f"[DATA LOADED] Price matrix shape: {price_pivot.shape} ({price_pivot.shape[1]} stocks across {price_pivot.shape[0]} trading days)", flush=True)
    return price_pivot, comp_df, ratios_df, pl_df

# Custom BT Algo for Fundamental Quality Screening
class SelectQualityUniverse(bt.Algo):
    def __init__(self, comp_df, ratios_df, pl_df, min_mcap=500.0, min_roe=10.0, max_de=1.5):
        super(SelectQualityUniverse, self).__init__()
        self.mkt_cap_dict = dict(zip(comp_df['symbol'], comp_df['market_cap']))
        self.ratios_df = ratios_df
        self.pl_df = pl_df
        self.min_mcap = min_mcap
        self.min_roe = min_roe
        self.max_de = max_de

    def __call__(self, target):
        current_date = target.now
        target_year = current_date.year - 1

        # Point-in-time fundamentals
        r_sub = self.ratios_df[self.ratios_df['year'] == target_year]
        p_sub = self.pl_df[self.pl_df['year'] == target_year]
        merged = pd.merge(r_sub, p_sub[['symbol', 'year', 'net_profit']], on=['symbol', 'year'], how='inner')

        qualifying = set(merged[
            (merged['roe'] >= self.min_roe) & 
            (merged['debt_equity'] <= self.max_de) & 
            (merged['net_profit'] > 0)
        ]['symbol'])

        selected = [
            s for s in target.temp['selected']
            if (s in qualifying) and (self.mkt_cap_dict.get(s, 0) >= self.min_mcap)
        ]
        target.temp['selected'] = selected
        return True

# Custom BT Algo for Momentum Ranking (3-Month Rate of Change)
class SelectMomentumTopN(bt.Algo):
    def __init__(self, n=10, lookback_days=63):
        super(SelectMomentumTopN, self).__init__()
        self.n = n
        self.lookback_days = lookback_days

    def __call__(self, target):
        selected = target.temp['selected']
        if not selected:
            return True

        prices = target.universe.loc[:target.now, selected]
        if len(prices) < self.lookback_days:
            return True

        # Calculate 3-month momentum score
        start_prices = prices.iloc[-self.lookback_days]
        end_prices = prices.iloc[-1]
        mom_scores = (end_prices / start_prices) - 1.0

        top_n = mom_scores.sort_values(ascending=False).head(self.n).index.tolist()
        target.temp['selected'] = top_n
        return True

def create_bt_strategy(name, price_pivot, comp_df, ratios_df, pl_df, num_stocks=10, use_quality=True, min_mcap=500.0):
    algos = [
        bt.algos.RunMonthly(),
        bt.algos.SelectAll(),
    ]

    if use_quality:
        algos.append(SelectQualityUniverse(comp_df, ratios_df, pl_df, min_mcap=min_mcap))

    algos.extend([
        SelectMomentumTopN(n=num_stocks, lookback_days=63),
        bt.algos.WeighEqually(),
        bt.algos.Rebalance()
    ])

    s = bt.Strategy(name, algos)
    return bt.Backtest(s, price_pivot, initial_capital=INITIAL_CAPITAL)

def main():
    price_pivot, comp_df, ratios_df, pl_df = load_data()
    
    # Filter price matrix between START_DATE and END_DATE
    price_pivot = price_pivot.loc[START_DATE:END_DATE]

    print("\n[BT FRAMEWORK] Constructing strategies using BT (Python Backtesting Framework)...", flush=True)

    # Define Backtests using 'bt' library
    b0 = create_bt_strategy("Nifty_Benchmark", price_pivot[['NIFTY50']].dropna(), comp_df, ratios_df, pl_df, num_stocks=1, use_quality=False, min_mcap=0)
    b1 = create_bt_strategy("Pure_Momentum_10", price_pivot, comp_df, ratios_df, pl_df, num_stocks=10, use_quality=False, min_mcap=0)
    b2 = create_bt_strategy("Liquid_Momentum_10", price_pivot, comp_df, ratios_df, pl_df, num_stocks=10, use_quality=False, min_mcap=500.0)
    b3 = create_bt_strategy("Quality_Momentum_10", price_pivot, comp_df, ratios_df, pl_df, num_stocks=10, use_quality=True, min_mcap=500.0)

    print("[BT RUNNER] Executing backtests via bt.run()...", flush=True)
    res = bt.run(b0, b1, b2, b3)

    print("\n" + "=" * 90)
    print("      OFFICIAL 'BT' LIBRARY BACKTEST PERFORMANCE REPORT      ")
    print("=" * 90)
    res.display()

    # Generate QuantStats Tearsheet for Winning Strategy
    print("\n[QUANTSTATS] Computing institutional tearsheet metrics...", flush=True)
    win_returns = res.get_security_weights('Quality_Momentum_10').pct_change().dropna()
    print(f"Quality Momentum Sharpe Ratio: {res.stats.loc['daily_sharpe', 'Quality_Momentum_10']:.2f}")
    print(f"Quality Momentum Max Drawdown: {res.stats.loc['max_drawdown', 'Quality_Momentum_10']*100:.2f}%")
    print(f"Quality Momentum CAGR: {res.stats.loc['cagr', 'Quality_Momentum_10']*100:.2f}%")

if __name__ == "__main__":
    main()
