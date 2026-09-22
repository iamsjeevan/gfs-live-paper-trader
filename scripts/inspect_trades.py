"""Inspect MAE and drawdowns of raw 200 MA trades."""

import numpy as np
import pandas as pd
from backtest.data import load_candles

df = load_candles("1h")
closes = df["close"].to_numpy()
highs = df["high"].to_numpy()
lows = df["low"].to_numpy()
opens = df["open"].to_numpy()
dts = df["datetime_utc"].to_numpy()
n = len(df)

sma200 = pd.Series(closes).rolling(200).mean().to_numpy()

trades = []
in_pos = False
entry_p = 0.0
entry_idx = 0
entry_dt = ""

for t in range(200, n):
    prev_c = closes[t - 1]
    prev_sma = sma200[t - 1]
    open_p = opens[t]

    sig = 1 if prev_c > prev_sma else 0
    prev_sig = 1 if (t > 200 and closes[t - 2] > sma200[t - 2]) else 0

    if sig == 1 and prev_sig == 0:
        in_pos = True
        entry_p = open_p
        entry_idx = t
        entry_dt = dts[t]
    elif sig == 0 and prev_sig == 1 and in_pos:
        exit_p = open_p
        ret = (exit_p - entry_p) / entry_p
        trade_lows = lows[entry_idx : t + 1]
        min_low = trade_lows.min()
        mae = (min_low - entry_p) / entry_p
        trades.append({
            "entry_dt": entry_dt,
            "exit_dt": dts[t],
            "entry_p": entry_p,
            "exit_p": exit_p,
            "ret_pct": ret * 100,
            "mae_pct": mae * 100,
            "bars": t - entry_idx,
        })
        in_pos = False

df_t = pd.DataFrame(trades)
print(f"Total Long-Only Trades: {len(df_t)}")
print(f"Average Return: {df_t['ret_pct'].mean():.2f}%")
worst_ret_idx = df_t['ret_pct'].idxmin()
print(f"Worst Trade Realized Return: {df_t['ret_pct'].min():.2f}% (on {df_t.loc[worst_ret_idx, 'entry_dt']})")
worst_mae_idx = df_t['mae_pct'].idxmin()
print(f"Worst Intraday Drawdown (MAE): {df_t['mae_pct'].min():.2f}% (on {df_t.loc[worst_mae_idx, 'entry_dt']})")

print("\nTrades by Maximum Unrealized Drawdown (MAE):")
c_10 = (df_t['mae_pct'] < -10).sum()
c_20 = (df_t['mae_pct'] < -20).sum()
c_30 = (df_t['mae_pct'] < -30).sum()
c_40 = (df_t['mae_pct'] < -40).sum()
c_50 = (df_t['mae_pct'] < -50).sum()
print(f"MAE worse than -10% (standard 10x liquidation): {c_10} trades ({c_10 / len(df_t) * 100:.1f}%)")
print(f"MAE worse than -20%: {c_20} trades")
print(f"MAE worse than -30%: {c_30} trades")
print(f"MAE worse than -40%: {c_40} trades")
print(f"MAE worse than -50%: {c_50} trades")

worst_5 = df_t.sort_values("mae_pct").head(5)
print("\nTop 5 Worst Flash Drops during a Long trade:")
for _, r in worst_5.iterrows():
    print(f"  {r['entry_dt'][:10]} to {r['exit_dt'][:10]}: Realized {r['ret_pct']:+6.1f}%, Intraday Drop {r['mae_pct']:6.1f}%")
