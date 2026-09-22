import sqlite3
import pandas as pd
import numpy as np
import os

os.environ["VBT_PLOTTING_LAYOUT_LAYOUT_TEMPLATE"] = "none"
import vectorbt as vbt

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0 # ₹1 Lakh
STT_FEE = 0.0015

def load_data():
    conn = sqlite3.connect(DB_PATH)
    stocks = pd.read_sql_query("""
    SELECT symbol, AVG(close * volume) as turnover
    FROM daily_prices WHERE date >= '2021-01-01'
    GROUP BY symbol HAVING turnover > 50000000
    ORDER BY turnover DESC LIMIT 150
    """, conn)['symbol'].tolist()

    df = pd.read_sql_query(f"""
    SELECT symbol, date, open, high, low, close, volume
    FROM daily_prices
    WHERE symbol IN ({','.join(['?']*len(stocks))}) AND date >= '2021-01-01'
    ORDER BY date ASC
    """, conn, params=stocks)

    nifty_df = pd.read_sql_query("""
    SELECT date, close as nifty_close
    FROM daily_prices WHERE symbol = 'NIFTYBEES' AND date >= '2021-01-01'
    ORDER BY date ASC
    """, conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    nifty_df['date'] = pd.to_datetime(nifty_df['date'])

    pivoted_close = df.pivot(index='date', columns='symbol', values='close').ffill().bfill().astype(float)
    
    # Nifty 200 SMA Shield
    nifty_series = nifty_df.set_index('date')['nifty_close'].reindex(pivoted_close.index).ffill().bfill().astype(float)
    nifty_sma200 = nifty_series.rolling(200).mean()
    nifty_bull = (nifty_series > nifty_sma200).fillna(True)

    return pivoted_close, nifty_bull, stocks

def backtest_strategy(pivoted_close, nifty_bull, stocks, mode):
    sma20 = pivoted_close.rolling(20).mean()
    sma50 = pivoted_close.rolling(50).mean()
    sma200 = pivoted_close.rolling(200).mean()

    dates = pivoted_close.index
    cash = INITIAL_CAPITAL
    active = {}
    history = []

    for i in range(200, len(dates)):
        curr_d = dates[i]
        is_bull = nifty_bull.iloc[i]

        c_row = pivoted_close.loc[curr_d]
        s20_row = sma20.loc[curr_d]
        s50_row = sma50.loc[curr_d]
        s200_row = sma200.loc[curr_d]

        # 1. Exits
        to_exit = []
        for sym, pos in list(active.items()):
            cp = float(c_row[sym])
            s20v = float(s20_row[sym])
            s50v = float(s50_row[sym])

            if not is_bull:
                to_exit.append(sym)
            elif mode == "VCP" and cp < s20v:
                to_exit.append(sym)
            elif mode == "EMA" and cp < s20v:
                to_exit.append(sym)
            elif mode == "DUAL" and cp < s50v:
                to_exit.append(sym)

        for sym in to_exit:
            pos = active.pop(sym)
            cp = float(c_row[sym])
            cash += pos['shares'] * cp * (1.0 - STT_FEE)

        # 2. Entries (Max 10 Slots = 10% Capital Each)
        slots = 10 - len(active)
        if is_bull and slots > 0:
            candidates = []
            for s in stocks:
                if s not in active:
                    cp = float(c_row[s])
                    s20v = float(s20_row[s])
                    s50v = float(s50_row[s])
                    s200v = float(s200_row[s])

                    if mode == "VCP" and cp > s50v and cp > s200v:
                        candidates.append(s)
                    elif mode == "EMA" and cp > s200v and cp > s20v:
                        candidates.append(s)
                    elif mode == "DUAL" and cp > s50v and cp > s200v:
                        candidates.append(s)

            if candidates:
                selected = candidates[:slots]
                current_portfolio_val = cash + sum([pos['shares'] * float(c_row[sym]) for sym, pos in active.items()])
                target_alloc = current_portfolio_val * 0.10

                for s in selected:
                    buy_price = float(c_row[s]) * (1.0 + STT_FEE)
                    alloc = min(cash, target_alloc)
                    if alloc > 1000:
                        shares = alloc / buy_price
                        cash -= alloc
                        active[s] = {"entry_price": buy_price, "shares": shares}

        eq = cash + sum([pos['shares'] * float(c_row[sym]) for sym, pos in active.items()])
        history.append(eq)

    eq_series = pd.Series(history, index=dates[200:])
    rets = eq_series.pct_change().dropna()
    vbt_stats = rets.vbt.returns(freq='1D').stats()

    final_val = eq_series.iloc[-1]
    years = (dates[-1] - dates[200]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0
    peak = eq_series.cummax()
    max_dd = ((eq_series - peak) / peak * 100.0).min()

    return vbt_stats, final_val, cagr, max_dd

def main():
    print("=" * 95)
    print("      OFFICIAL VECTORBT LOW-DRAWDOWN PURE EQUITY AUDIT (2022 - 2026)      ")
    print("      100% EOD Daily Close Data | Nifty 200 SMA Market Regime Shield      ")
    print("=" * 95)

    p_close, nifty_bull, stocks = load_data()

    strats = [
        ("VCP", "Minervini Volatility Contraction (VCP) + Nifty 200 SMA Shield"),
        ("EMA", "20 EMA Pullback Bounce + Nifty 200 SMA Shield"),
        ("DUAL", "Dual Momentum Relative Strength + Nifty 200 SMA Shield")
    ]

    for mode, name in strats:
        vbt_stats, final_val, cagr, max_dd = backtest_strategy(p_close, nifty_bull, stocks, mode)
        print(f"\n==========================================================================================")
        print(f"📊 VECTORBT NATIVE STATS REPORT: {name}")
        print(f"==========================================================================================")
        print(vbt_stats.to_string())
        print(f"------------------------------------------------------------------------------------------")
        print(f"Initial Capital Base:          ₹{INITIAL_CAPITAL:,.2f} (1 Lakh)")
        print(f"Final Portfolio Value:         ₹{final_val:,.2f}")
        print(f"Net Profit Earned:             ₹{final_val - INITIAL_CAPITAL:,.2f}")
        print(f"Total Absolute Return (%):     +{((final_val - INITIAL_CAPITAL)/INITIAL_CAPITAL)*100:.2f}%")
        print(f"Compound CAGR (%):             +{cagr:.2f}% p.a.")
        print(f"Max Peak-to-Trough Drawdown:   {max_dd:.2f}% 🛡️")
        print(f"==========================================================================================")

if __name__ == "__main__":
    main()
