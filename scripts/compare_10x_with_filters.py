"""Compare 10x Raw MA 200 vs 10x with Risk Management Filters (ATR Band, EMA 9, Stop Loss)."""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backtest.data import load_candles

FIG_DIR = Path("reports/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

df = load_candles("1h")
n = len(df)
closes = df["close"].to_numpy(dtype=np.float64)
highs = df["high"].to_numpy(dtype=np.float64)
lows = df["low"].to_numpy(dtype=np.float64)
opens = df["open"].to_numpy(dtype=np.float64)
dts = df["datetime_utc"].to_numpy()
timestamps = df["timestamp"].to_numpy()

sma200 = pd.Series(closes).rolling(200).mean().to_numpy()
ema9 = pd.Series(closes).ewm(span=9, adjust=False).mean().to_numpy()

prev_close = np.roll(closes, 1)
prev_close[0] = closes[0]
tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
atr14 = pd.Series(tr).rolling(14).mean().to_numpy()

delta = pd.Series(closes).diff()
gain = delta.clip(lower=0.0)
loss = -delta.clip(upper=0.0)
avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
rs = avg_gain / avg_loss.replace(0.0, 1e-9)
rsi14 = (100.0 - (100.0 / (1.0 + rs))).to_numpy()


def run_10x_fixed_notional(
    mode="long_only",
    fixed_notional=100_000.0,
    band_atr_mult=0.0,
    filter_type="none",
    sl_atr_mult=0.0,
):
    trade_pnls = []
    in_pos = False
    entry_p = 0.0
    cost_basis_p = 0.0
    entry_atr = 0.0
    shares = 0.0
    entry_dt = ""
    cum_pnl = 0.0
    pnl_history = []
    funding_total = 0.0
    fees_total = 0.0
    regime = 0
    current_target = 0

    for t in range(200, n):
        prev_c = closes[t - 1]
        prev_sma = sma200[t - 1]
        prev_atr = atr14[t - 1]
        prev_ema = ema9[t - 1]
        prev_rsi = rsi14[t - 1]
        open_p = opens[t]
        high_p = highs[t]
        low_p = lows[t]
        close_p = closes[t]
        curr_dt = dts[t]

        # 1. Stop-Loss Check during bar t
        stopped_out = False
        if in_pos and sl_atr_mult > 0.0:
            if shares > 0:
                sl_level = entry_p - sl_atr_mult * entry_atr
                if low_p <= sl_level:
                    exit_p = min(open_p, sl_level) if open_p <= sl_level else sl_level
                    cost = abs(shares) * exit_p * 0.0005
                    fees_total += cost
                    trade_pnl = shares * (exit_p - entry_p) - cost
                    cum_pnl += trade_pnl
                    trade_pnls.append({
                        "entry_dt": entry_dt, "exit_dt": curr_dt,
                        "pnl": trade_pnl, "ret_pct": (exit_p - entry_p) / entry_p,
                        "type": "SL"
                    })
                    in_pos = False
                    shares = 0.0
                    current_target = 0
                    stopped_out = True
            elif shares < 0:
                sl_level = entry_p + sl_atr_mult * entry_atr
                if high_p >= sl_level:
                    exit_p = max(open_p, sl_level) if open_p >= sl_level else sl_level
                    cost = abs(shares) * exit_p * 0.0005
                    fees_total += cost
                    trade_pnl = abs(shares) * (entry_p - exit_p) - cost
                    cum_pnl += trade_pnl
                    trade_pnls.append({
                        "entry_dt": entry_dt, "exit_dt": curr_dt,
                        "pnl": trade_pnl, "ret_pct": (entry_p - exit_p) / entry_p,
                        "type": "SL"
                    })
                    in_pos = False
                    shares = 0.0
                    current_target = 0
                    stopped_out = True

        # 2. Regime and Crossover Target
        upper_band = prev_sma + band_atr_mult * prev_atr
        lower_band = prev_sma - band_atr_mult * prev_atr

        regime_changed = False
        if band_atr_mult > 0.0:
            if prev_c > upper_band:
                if regime != 1:
                    regime = 1
                    regime_changed = True
            elif prev_c < lower_band:
                if regime != -1:
                    regime = -1
                    regime_changed = True
        else:
            if prev_c > prev_sma:
                if regime != 1:
                    regime = 1
                    regime_changed = True
            elif prev_c < prev_sma:
                if regime != -1:
                    regime = -1
                    regime_changed = True

        new_target = current_target
        if regime_changed:
            if regime == 1:
                valid = True
                if filter_type == "ema9_entry" and not (prev_c > prev_ema and prev_ema > prev_sma):
                    valid = False
                elif filter_type == "rsi_entry" and not (prev_rsi > 50.0):
                    valid = False
                new_target = 1 if valid else 0
            elif regime == -1:
                if mode == "long_short":
                    valid = True
                    if filter_type == "ema9_entry" and not (prev_c < prev_ema and prev_ema < prev_sma):
                        valid = False
                    elif filter_type == "rsi_entry" and not (prev_rsi < 50.0):
                        valid = False
                    new_target = -1 if valid else 0
                else:
                    new_target = 0

        # 3. Position Rebalance at Open if target changed and not stopped out on this bar
        if not stopped_out and new_target != current_target:
            if in_pos:
                cost = abs(shares) * open_p * 0.0005
                fees_total += cost
                if shares > 0:
                    trade_pnl = shares * (open_p - entry_p) - cost
                else:
                    trade_pnl = abs(shares) * (cost_basis_p - open_p) - cost
                cum_pnl += trade_pnl
                trade_pnls.append({
                    "entry_dt": entry_dt, "exit_dt": curr_dt,
                    "pnl": trade_pnl,
                    "ret_pct": (open_p - entry_p) / entry_p if shares > 0 else (cost_basis_p - open_p) / cost_basis_p,
                    "type": "NORMAL"
                })
                in_pos = False
                shares = 0.0

            if new_target != 0:
                shares = (new_target * fixed_notional) / open_p
                cost = abs(shares) * open_p * 0.0005
                fees_total += cost
                cum_pnl -= cost
                entry_p = open_p
                cost_basis_p = open_p
                entry_atr = prev_atr
                entry_dt = curr_dt
                in_pos = True

            current_target = new_target

        # 4. Binance Funding Fee (00:00, 08:00, 16:00 UTC)
        hour = int(curr_dt[11:13])
        minute = int(curr_dt[14:16])
        if hour in (0, 8, 16) and minute == 0 and in_pos:
            f = -shares * open_p * 0.0001
            funding_total += f
            cum_pnl += f

        # Unrealized PnL for bar
        unrealized = 0.0
        if in_pos:
            if shares > 0:
                unrealized = shares * (close_p - entry_p)
            else:
                unrealized = abs(shares) * (entry_p - close_p)
        pnl_history.append(cum_pnl + unrealized)

    df_pnl = pd.DataFrame(trade_pnls)
    pnl_series = pd.Series(pnl_history, index=pd.to_datetime(timestamps[200:], unit="ms", utc=True))

    yearly_pnl = pnl_series.resample("YE").last().diff()
    yearly_pnl.iloc[0] = pnl_series.resample("YE").last().iloc[0]

    wins = df_pnl[df_pnl["pnl"] > 0]["pnl"] if len(df_pnl) > 0 else []
    losses = df_pnl[df_pnl["pnl"] < 0]["pnl"] if len(df_pnl) > 0 else []
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 0.0
    win_rate = len(wins) / len(df_pnl) if len(df_pnl) > 0 else 0.0

    return {
        "total_pnl": cum_pnl,
        "fees": fees_total,
        "funding": funding_total,
        "trades": len(df_pnl),
        "win_rate": win_rate,
        "pf": pf,
        "max_drawdown_dollars": float((pnl_series - pnl_series.cummax()).min()),
        "yearly_pnl": yearly_pnl,
        "pnl_series": pnl_series,
    }

print("Simulating 10x configurations with added risk management...")

configs = [
    ("1. Raw 200 SMA (Baseline 10x)", dict(band_atr_mult=0.0, filter_type="none", sl_atr_mult=0.0)),
    ("2. + ATR Band 0.5x (Whipsaw Filter)", dict(band_atr_mult=0.5, filter_type="none", sl_atr_mult=0.0)),
    ("3. + ATR Band 0.5x + Stop-Loss 2.5x", dict(band_atr_mult=0.5, filter_type="none", sl_atr_mult=2.5)),
    ("4. + ATR Band + EMA 9 + Stop-Loss", dict(band_atr_mult=0.5, filter_type="ema9_entry", sl_atr_mult=2.5)),
]

results_lo = {}
for name, cfg in configs:
    res = run_10x_fixed_notional(mode="long_only", **cfg)
    results_lo[name] = res

results_ls = {}
for name, cfg in configs:
    res = run_10x_fixed_notional(mode="long_short", **cfg)
    results_ls[name] = res

# Print Table for Long-Only
print("\n" + "=" * 105)
print("10x LEVERAGE ($100k NOTIONAL) COMPARISON: LONG-ONLY")
print("=" * 105)
rows_lo = []
for name, res in results_lo.items():
    rows_lo.append({
        "Configuration": name,
        "Net Profit ($)": f"${res['total_pnl']:+12,.2f}",
        "Binance Fees ($)": f"${res['fees']:10,.2f}",
        "Funding ($)": f"${res['funding']:10,.2f}",
        "Max Drawdown ($)": f"${res['max_drawdown_dollars']:11,.2f}",
        "Trades": res["trades"],
        "Win Rate": f"{res['win_rate']*100:5.1f}%",
        "PF": f"{res['pf']:4.2f}",
    })
print(pd.DataFrame(rows_lo).to_string(index=False))

# Print Table for Long-Short
print("\n" + "=" * 105)
print("10x LEVERAGE ($100k NOTIONAL) COMPARISON: LONG-SHORT")
print("=" * 105)
rows_ls = []
for name, res in results_ls.items():
    rows_ls.append({
        "Configuration": name,
        "Net Profit ($)": f"${res['total_pnl']:+12,.2f}",
        "Binance Fees ($)": f"${res['fees']:10,.2f}",
        "Funding ($)": f"${res['funding']:10,.2f}",
        "Max Drawdown ($)": f"${res['max_drawdown_dollars']:11,.2f}",
        "Trades": res["trades"],
        "Win Rate": f"{res['win_rate']*100:5.1f}%",
        "PF": f"{res['pf']:4.2f}",
    })
print(pd.DataFrame(rows_ls).to_string(index=False))

# Year-by-Year Table for Long-Only
df_years = pd.DataFrame({
    "Raw 200 SMA": results_lo["1. Raw 200 SMA (Baseline 10x)"]["yearly_pnl"],
    "+ ATR Band 0.5x": results_lo["2. + ATR Band 0.5x (Whipsaw Filter)"]["yearly_pnl"],
    "+ Band & SL 2.5x": results_lo["3. + ATR Band 0.5x + Stop-Loss 2.5x"]["yearly_pnl"],
    "+ Band, EMA9, SL": results_lo["4. + ATR Band + EMA 9 + Stop-Loss"]["yearly_pnl"],
})
df_years.index = df_years.index.year
print("\n" + "=" * 80)
print("YEAR-BY-YEAR DOLLAR PnL ($) ACROSS 10x CONFIGURATIONS (LONG-ONLY):")
print("=" * 80)
print(df_years.map(lambda x: f"${x:+10,.2f}").to_string())

# Plot Cumulative Curves
fig, ax = plt.subplots(figsize=(13, 7))
colors = ["#d62728", "#1f77b4", "#9467bd", "#2ca02c"]
for i, (name, res) in enumerate(results_lo.items()):
    ax.plot(res["pnl_series"].iloc[::20], label=f"{name} (${res['total_pnl']:+,.0f})", color=colors[i], lw=1.6)

ax.axhline(0, color="black", ls="--", alpha=0.5)
ax.set_title("10x Leverage ($100k Position): Raw 200 SMA vs Adding Risk Management Filters", fontsize=13, fontweight="bold")
ax.set_ylabel("Cumulative Net Profit ($)", fontsize=11)
ax.set_xlabel("Date", fontsize=11)
ax.legend(loc="upper left", fontsize=9.5)
ax.grid(True, alpha=0.3)
plt.tight_layout()
fig.savefig(FIG_DIR / "10x_raw_vs_risk_managed_comparison.png", dpi=180)
plt.close(fig)
print("\nSaved 10x_raw_vs_risk_managed_comparison.png")
