import sqlite3
import pandas as pd
import numpy as np
import os

os.environ["VBT_PLOTTING_LAYOUT_LAYOUT_TEMPLATE"] = "none"
import vectorbt as vbt

DB_PATH = "data/nse_stocks_all_years.db"
INITIAL_CAPITAL = 100000.0 # ₹1 Lakh
STT_FEE = 0.0015 # 0.15%

def load_data():
    conn = sqlite3.connect(DB_PATH)
    stocks = pd.read_sql_query("""
    SELECT symbol, AVG(close * volume) as turnover
    FROM daily_prices WHERE date >= '2021-01-01'
    GROUP BY symbol HAVING turnover > 50000000
    ORDER BY turnover DESC LIMIT 200
    """, conn)['symbol'].tolist()

    df = pd.read_sql_query(f"""
    SELECT symbol, date, open, high, low, close, volume
    FROM daily_prices
    WHERE symbol IN ({','.join(['?']*len(stocks))}) AND date >= '2021-01-01'
    ORDER BY date ASC
    """, conn, params=stocks)

    nifty_df = pd.read_sql_query("""
    SELECT date, close as nifty_close
    FROM daily_prices WHERE symbol = '^NSEI' AND date >= '2021-01-01'
    ORDER BY date ASC
    """, conn)
    conn.close()

    df['date'] = pd.to_datetime(df['date'])
    nifty_df['date'] = pd.to_datetime(nifty_df['date'])
    return df, nifty_df, stocks

def run_strategy_backtest(df, nifty_df, stocks, strat_type):
    pivoted_close = df.pivot(index='date', columns='symbol', values='close').astype(np.float64)
    pivoted_high = df.pivot(index='date', columns='symbol', values='high').astype(np.float64)
    pivoted_low = df.pivot(index='date', columns='symbol', values='low').astype(np.float64)

    # Nifty 200 SMA Shield
    nifty_merged = pd.DataFrame({'date': pivoted_close.index}).merge(nifty_df, on='date', how='left').ffill()
    nifty_close = nifty_merged['nifty_close'].astype(np.float64)
    nifty_sma200 = nifty_close.vbt.rolling_mean(200)
    nifty_bull = (nifty_close > nifty_sma200).fillna(False)

    sma20 = pivoted_close.vbt.rolling_mean(20)
    sma50 = pivoted_close.vbt.rolling_mean(50)
    sma200 = pivoted_close.vbt.rolling_mean(200)
    atr14 = vbt.ATR.run(pivoted_high, pivoted_low, pivoted_close, window=14).atr
    ret_6m = pivoted_close.pct_change(126)

    dates = pivoted_close.index
    cash = INITIAL_CAPITAL
    active_positions = {}
    history = []

    for i in range(200, len(dates)):
        curr_d = dates[i]
        curr_d_str = curr_d.strftime('%Y-%m-%d')
        is_nifty_bull = nifty_bull.loc[i]

        c_row = pivoted_close.loc[curr_d]
        sma20_row = sma20.loc[curr_d]
        sma50_row = sma50.loc[curr_d]
        sma200_row = sma200.loc[curr_d]
        atr_row = atr14.loc[curr_d]

        # 1. Process Exits
        to_exit = []
        for sym, pos in list(active_positions.items()):
            cp = c_row[sym]
            s20 = sma20_row[sym]
            s50 = sma50_row[sym]

            # Market regime exit or trailing stop exit
            if not is_nifty_bull:
                to_exit.append((sym, "Nifty < 200 SMA Market Shield"))
            elif strat_type == "VCP" and cp < s20:
                to_exit.append((sym, "Close < 20 SMA Exit"))
            elif strat_type == "DUAL_MOMENTUM" and cp < s50:
                to_exit.append((sym, "Close < 50 SMA Exit"))
            elif strat_type == "EMA_PULLBACK" and cp < s20:
                to_exit.append((sym, "Close < 20 EMA Exit"))

        for sym, reason in to_exit:
            pos = active_positions.pop(sym)
            cp = c_row[sym]
            proceeds = pos['shares'] * cp * (1.0 - STT_FEE)
            cash += proceeds

        # 2. Process Entries if Nifty is Bullish and portfolio has slots
        slots = 10 - len(active_positions)
        if is_nifty_bull and slots > 0:
            candidates = []
            for s in stocks:
                if s not in active_positions:
                    cp = c_row[s]
                    s20v = sma20_row[s]
                    s50v = sma50_row[s]
                    s200v = sma200_row[s]
                    atrv = atr_row[s]

                    if pd.notna(cp) and pd.notna(s50v) and pd.notna(s200v):
                        if strat_type == "VCP":
                            # Minervini VCP: Tight consolidation + Uptrend
                            if cp > s50v and cp > s200v and pd.notna(atrv) and (atrv/cp) < 0.035:
                                candidates.append(s)
                        elif strat_type == "DUAL_MOMENTUM":
                            # Dual Momentum: Top 6-month momentum + Uptrend
                            r6 = ret_6m.loc[curr_d, s]
                            if cp > s50v and cp > s200v and pd.notna(r6) and r6 > 0.10:
                                candidates.append(s)
                        elif strat_type == "EMA_PULLBACK":
                            # 20 EMA Pullback Bounce
                            if cp > s200v and cp > s20v:
                                candidates.append(s)

            if candidates:
                selected = candidates[:slots]
                tot_val = cash + sum([pos['shares'] * c_row[sym] for sym, pos in active_positions.items() if pd.notna(c_row[sym])])
                target_alloc = tot_val * 0.10 # 10% per stock

                for s in selected:
                    buy_price = c_row[s] * (1.0 + STT_FEE)
                    alloc = min(cash, target_alloc)
                    if alloc > 1000:
                        shares = alloc / buy_price
                        cash -= alloc
                        active_positions[s] = {"entry_price": buy_price, "shares": shares}

        eq_val = cash + sum([pos['shares'] * c_row[sym] for sym, pos in active_positions.items() if pd.notna(c_row[sym])])
        history.append(eq_val)

    equity_series = pd.Series(history, index=dates[200:])
    returns_series = equity_series.pct_change().dropna()
    vbt_stats = returns_series.vbt.returns(freq='1D').stats()

    final_val = equity_series.iloc[-1]
    years = (dates[-1] - dates[200]).days / 365.25
    cagr = ((final_val / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0
    peak = equity_series.cummax()
    max_dd = ((equity_series - peak) / peak * 100.0).min()

    return vbt_stats, final_val, cagr, max_dd

def main():
    print("=" * 95)
    print("      OFFICIAL VECTORBT LOW-DRAWDOWN PURE EQUITY AUDIT (2021 - 2026)      ")
    print("      100% EOD Daily Close Data | Nifty 200 SMA Market Regime Shield      ")
    print("=" * 95)

    df, nifty_df, stocks = load_data()

    strats = [
        ("VCP", "Minervini Volatility Contraction (VCP) + Nifty 200 SMA Shield"),
        ("DUAL_MOMENTUM", "Dual Momentum Relative Strength + Nifty 200 SMA Shield"),
        ("EMA_PULLBACK", "20 EMA Pullback Bounce + Nifty 200 SMA Shield")
    ]

    for code, name in strats:
        vbt_stats, final_val, cagr, max_dd = run_strategy_backtest(df, nifty_df, stocks, code)
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
