"""Plot Binance Perpetual Futures equity curves and heatmap."""

from pathlib import Path
import sys
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from backtest.data import load_candles

FIG_DIR = Path("reports/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

df = load_candles("1h")
df["sma200"] = df["close"].rolling(200).mean()
df["sig"] = np.where(df["close"] > df["sma200"], 1.0, -1.0)
df.loc[df["sma200"].isna(), "sig"] = 0.0


def sim_curve(df, leverage=1.0, mode="long_short"):
    n = len(df)
    opens = df["open"].to_numpy(dtype=np.float64)
    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    closes = df["close"].to_numpy(dtype=np.float64)
    signals = df["sig"].to_numpy(dtype=np.float64)
    dts = df["datetime_utc"].to_numpy()
    if mode == "long_only":
        signals = np.maximum(0.0, signals)
    equity = np.zeros(n)
    curr_cash = 10000.0
    curr_shares = 0.0
    equity[0] = curr_cash
    is_liq = False
    for t in range(1, n):
        open_p = opens[t]
        high_p = highs[t]
        low_p = lows[t]
        close_p = closes[t]
        curr_dt = dts[t]
        if is_liq:
            equity[t] = 0.0
            continue
        pre_eq = curr_cash + curr_shares * open_p
        if pre_eq <= 0:
            is_liq = True
            equity[t] = 0.0
            continue
        prev_sig = signals[t - 1]
        sig_changed = (t == 200) or (signals[t - 1] != signals[t - 2])
        if sig_changed and prev_sig != 0.0:
            target_dollars = prev_sig * leverage * pre_eq
            target_shares = target_dollars / open_p
            delta_s = target_shares - curr_shares
            if abs(delta_s) > 1e-8:
                traded_dollars = abs(delta_s) * open_p
                cost = traded_dollars * 0.0005
                curr_cash -= (delta_s * open_p + cost)
                curr_shares = target_shares
        elif sig_changed and prev_sig == 0.0:
            if abs(curr_shares) > 1e-8:
                traded_dollars = abs(curr_shares) * open_p
                cost = traded_dollars * 0.0005
                curr_cash += (curr_shares * open_p - cost)
                curr_shares = 0.0
        hour = int(curr_dt[11:13])
        minute = int(curr_dt[14:16])
        if hour in (0, 8, 16) and minute == 0:
            curr_cash += (-curr_shares * open_p * 0.0001)
        if curr_shares > 0:
            worst_eq = curr_cash + curr_shares * low_p
            if worst_eq <= 0.0 or (worst_eq / (curr_shares * low_p)) < 0.004:
                is_liq = True
                curr_cash = 0.0
                curr_shares = 0.0
        elif curr_shares < 0:
            worst_eq = curr_cash + curr_shares * high_p
            if worst_eq <= 0.0 or (worst_eq / (abs(curr_shares) * high_p)) < 0.004:
                is_liq = True
                curr_cash = 0.0
                curr_shares = 0.0
        if is_liq:
            equity[t] = 0.0
        else:
            bar_eq = curr_cash + curr_shares * close_p
            if bar_eq <= 0:
                is_liq = True
                bar_eq = 0.0
                curr_cash = 0.0
                curr_shares = 0.0
            equity[t] = bar_eq
    return pd.Series(equity, index=pd.to_datetime(df["timestamp"], unit="ms", utc=True))


print("Generating Binance Perp Figures...")
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 10), sharex=True)
cmap = plt.get_cmap("turbo", 10)
bench = (df["close"] / df["close"].iloc[0]) * 10000.0
bench_s = pd.Series(bench.values, index=pd.to_datetime(df["timestamp"], unit="ms", utc=True))

for lev in range(1, 11):
    s_ls = sim_curve(df, leverage=float(lev), mode="long_short")
    s_lo = sim_curve(df, leverage=float(lev), mode="long_only")
    ax1.plot(s_ls.iloc[::20], label=f"{lev}x (${s_ls.iloc[-1]:,.0f})", color=cmap(lev - 1), lw=1.3)
    ax2.plot(s_lo.iloc[::20], label=f"{lev}x (${s_lo.iloc[-1]:,.0f})", color=cmap(lev - 1), lw=1.3)

ax1.plot(bench_s.iloc[::20], label="BTC Buy & Hold", color="black", ls="--", lw=1.5, alpha=0.7)
ax2.plot(bench_s.iloc[::20], label="BTC Buy & Hold", color="black", ls="--", lw=1.5, alpha=0.7)

ax1.set_yscale("log")
ax2.set_yscale("log")
ax1.set_title("Binance USDT-M Futures: 1h 200 SMA LONG-SHORT (Leverage 1x to 10x)", fontsize=12, fontweight="bold")
ax2.set_title("Binance USDT-M Futures: 1h 200 SMA LONG-ONLY (Leverage 1x to 10x)", fontsize=12, fontweight="bold")
ax1.set_ylabel("Portfolio Value ($ Log Scale)")
ax2.set_ylabel("Portfolio Value ($ Log Scale)")
ax1.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8)
ax2.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8)
ax1.grid(True, alpha=0.3)
ax2.grid(True, alpha=0.3)
plt.tight_layout()
fig.savefig(FIG_DIR / "binance_perp_ma200_leverage_curves.png", dpi=180, bbox_inches="tight")
plt.close(fig)
print("Saved binance_perp_ma200_leverage_curves.png")

# 2. Yearly Heatmap for Long-Only
yearly_dict = {}
for lev in range(1, 11):
    s = sim_curve(df, leverage=float(lev), mode="long_only")
    y = s.resample("YE").last()
    y_ret = y.pct_change()
    if len(y) > 0:
        y_ret.iloc[0] = (y.iloc[0] - 10000.0) / 10000.0
    yearly_dict[f"{lev}x"] = y_ret.replace([np.inf, -np.inf], 0.0).fillna(0.0) * 100

df_heat = pd.DataFrame(yearly_dict)
df_heat.index = df_heat.index.year

fig2, ax = plt.subplots(figsize=(12, 6))
sns.heatmap(df_heat, annot=True, fmt=".1f", cmap="RdYlGn", center=0.0, ax=ax, cbar_kws={"label": "Annual Return (%)"})
ax.set_title("Binance USDT-M Futures: 1h 200 SMA Long-Only Annual Return (%) by Leverage (1x to 10x)", fontsize=13, fontweight="bold")
ax.set_ylabel("Year", fontsize=11)
ax.set_xlabel("Leverage Tier", fontsize=11)
plt.tight_layout()
fig2.savefig(FIG_DIR / "binance_perp_yearly_heatmap.png", dpi=180)
plt.close(fig2)
print("Saved binance_perp_yearly_heatmap.png")
