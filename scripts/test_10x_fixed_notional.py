"""Fixed 10x Notional PnL test with deep margin buffer and plotting."""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backtest.data import load_candles

FIG_DIR = Path("reports/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

df = load_candles("1h")
n = len(df)
closes = df["close"].to_numpy()
highs = df["high"].to_numpy()
lows = df["low"].to_numpy()
opens = df["open"].to_numpy()
dts = df["datetime_utc"].to_numpy()
timestamps = df["timestamp"].to_numpy()
sma200 = pd.Series(closes).rolling(200).mean().to_numpy()

fixed_notional = 100_000.0  # 10x of $10,000 initial margin


def test_fixed_notional(mode="long_only"):
    trade_pnls = []
    in_pos = False
    entry_p = 0.0
    cost_basis_p = 0.0
    shares = 0.0
    entry_dt = ""
    cum_pnl = 0.0
    pnl_history = []
    funding_total = 0.0
    fees_total = 0.0

    for t in range(200, n):
        prev_c = closes[t - 1]
        prev_sma = sma200[t - 1]
        open_p = opens[t]
        curr_dt = dts[t]

        target = 0
        if prev_c > prev_sma:
            target = 1
        elif prev_c < prev_sma:
            target = -1 if mode == "long_short" else 0

        prev_target = 0
        if t > 200:
            if closes[t - 2] > sma200[t - 2]:
                prev_target = 1
            elif closes[t - 2] < sma200[t - 2]:
                prev_target = -1 if mode == "long_short" else 0

        # Rebalance
        if target != prev_target:
            if in_pos:
                cost = abs(shares) * open_p * 0.0005
                fees_total += cost
                if shares > 0:
                    trade_pnl = shares * (open_p - entry_p) - cost
                else:
                    trade_pnl = abs(shares) * (cost_basis_p - open_p) - cost
                cum_pnl += trade_pnl
                trade_pnls.append({
                    "entry_dt": entry_dt,
                    "exit_dt": curr_dt,
                    "pnl": trade_pnl,
                    "entry_p": entry_p,
                    "exit_p": open_p,
                })
                in_pos = False
                shares = 0.0

            if target != 0:
                shares = (target * fixed_notional) / open_p
                cost = abs(shares) * open_p * 0.0005
                fees_total += cost
                cum_pnl -= cost
                entry_p = open_p
                cost_basis_p = open_p
                entry_dt = curr_dt
                in_pos = True

        # Funding rate (00:00, 08:00, 16:00 UTC)
        hour = int(curr_dt[11:13])
        minute = int(curr_dt[14:16])
        if hour in (0, 8, 16) and minute == 0 and in_pos:
            f = -shares * open_p * 0.0001
            funding_total += f
            cum_pnl += f

        unrealized = 0.0
        if in_pos:
            if shares > 0:
                unrealized = shares * (closes[t] - entry_p)
            else:
                unrealized = abs(shares) * (entry_p - closes[t])
        pnl_history.append(cum_pnl + unrealized)

    df_pnl = pd.DataFrame(trade_pnls)
    pnl_series = pd.Series(pnl_history, index=pd.to_datetime(timestamps[200:], unit="ms", utc=True))

    yearly_pnl = pnl_series.resample("YE").last().diff()
    yearly_pnl.iloc[0] = pnl_series.resample("YE").last().iloc[0]

    return {
        "total_pnl": cum_pnl,
        "fees": fees_total,
        "funding": funding_total,
        "trades": len(df_pnl),
        "win_rate": (df_pnl["pnl"] > 0).mean() if len(df_pnl) > 0 else 0,
        "max_drawdown_dollars": float((pnl_series - pnl_series.cummax()).min()),
        "yearly_pnl": yearly_pnl,
        "pnl_series": pnl_series,
    }


res_lo = test_fixed_notional(mode="long_only")
res_ls = test_fixed_notional(mode="long_short")

# Generate plot
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)

ax1.plot(res_lo["pnl_series"].iloc[::20], label=f"10x Long-Only (Net PnL: ${res_lo['total_pnl']:+,.0f})", color="#2ca02c", lw=1.5)
ax1.plot(res_ls["pnl_series"].iloc[::20], label=f"10x Long-Short (Net PnL: ${res_ls['total_pnl']:+,.0f})", color="#1f77b4", lw=1.5)
ax1.axhline(0, color="black", ls="--", alpha=0.5)
ax1.set_title("Normal 1h 200 SMA at 10x Leverage ($100k Fixed Notional, Deep Margin Buffer)", fontsize=13, fontweight="bold")
ax1.set_ylabel("Cumulative Net PnL ($)", fontsize=11)
ax1.legend(loc="upper left", fontsize=10)
ax1.grid(True, alpha=0.3)

# Drawdown plot
dd_lo = res_lo["pnl_series"] - res_lo["pnl_series"].cummax()
dd_ls = res_ls["pnl_series"] - res_ls["pnl_series"].cummax()
ax2.plot(dd_lo.iloc[::20], label=f"Long-Only Max DD: ${res_lo['max_drawdown_dollars']:,.0f}", color="#d62728", lw=1.2)
ax2.plot(dd_ls.iloc[::20], label=f"Long-Short Max DD: ${res_ls['max_drawdown_dollars']:,.0f}", color="#ff7f0e", lw=1.2)
ax2.set_title("Drawdown in Dollars from Peak ($)", fontsize=12, fontweight="bold")
ax2.set_ylabel("Drawdown ($)", fontsize=11)
ax2.set_xlabel("Date", fontsize=11)
ax2.legend(loc="lower left", fontsize=10)
ax2.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(FIG_DIR / "normal_ma200_10x_deep_margin_curve.png", dpi=180)
plt.close(fig)
print("Saved normal_ma200_10x_deep_margin_curve.png")
