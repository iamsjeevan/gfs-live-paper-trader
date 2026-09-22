"""Full report and visualization for the Dual-Timeframe Adaptive 200 MA Strategy."""

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

sma200_1h = pd.Series(closes).rolling(200).mean().to_numpy()
sma200_daily = pd.Series(closes).rolling(200 * 24).mean().to_numpy()

prev_close = np.roll(closes, 1)
prev_close[0] = closes[0]
tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
atr14 = pd.Series(tr).rolling(14).mean().to_numpy()

start_idx = 4800 # 200 days warmup for Daily 200 SMA

def run_adaptive_strategy(bull_lev=3.0, bear_lev=0.0, name="Adaptive 3x Bull / 0x Bear"):
    equity = np.zeros(n)
    cash = np.zeros(n)
    shares = np.zeros(n)
    fees_paid = np.zeros(n)
    funding_paid = np.zeros(n)

    curr_cash = 10000.0
    curr_shares = 0.0
    equity[0] = curr_cash
    is_liq = False

    entry_p = 0.0
    entry_atr = 0.0
    current_lev = 0.0
    in_pos = False

    total_trades = 0
    trade_pnls = []
    regime = 0

    for t in range(start_idx, n):
        open_p = opens[t]
        high_p = highs[t]
        low_p = lows[t]
        close_p = closes[t]
        curr_dt = dts[t]

        prev_c = closes[t - 1]
        prev_sma = sma200_1h[t - 1]
        prev_daily_sma = sma200_daily[t - 1]
        prev_atr = atr14[t - 1]

        if is_liq:
            equity[t] = 0.0
            continue

        pre_eq = curr_cash + curr_shares * open_p
        if pre_eq <= 0.0:
            is_liq = True
            equity[t] = 0.0
            continue

        # 1. Stop-loss check (2.5x ATR)
        stopped_out = False
        bar_fee = 0.0

        if in_pos:
            sl_level = entry_p - 2.5 * entry_atr
            if low_p <= sl_level:
                exit_p = min(open_p, sl_level) if open_p <= sl_level else sl_level
                cost = abs(curr_shares) * exit_p * 0.0005
                bar_fee += cost
                pnl = curr_shares * (exit_p - entry_p) - cost
                trade_pnls.append(pnl)
                curr_cash += (curr_shares * exit_p - cost)
                curr_shares = 0.0
                in_pos = False
                current_lev = 0.0
                stopped_out = True

        # 2. 1h 200 SMA Hysteresis (0.5x ATR)
        upper_band = prev_sma + 0.5 * prev_atr
        lower_band = prev_sma - 0.5 * prev_atr

        regime_changed = False
        if prev_c > upper_band:
            if regime != 1:
                regime = 1
                regime_changed = True
        elif prev_c < lower_band:
            if regime != -1:
                regime = -1
                regime_changed = True

        # 3. Dynamic Leverage: Good Time (Bull) vs Bad Time (Bear)
        is_bull = (prev_c > prev_daily_sma)
        target_lev = 0.0
        if regime == 1:
            target_lev = bull_lev if is_bull else bear_lev
        else:
            target_lev = 0.0

        # 4. Rebalance on target leverage change or stop-out
        if not stopped_out and target_lev != current_lev:
            target_dollars = target_lev * pre_eq
            target_shares = target_dollars / open_p
            delta_s = target_shares - curr_shares

            if abs(delta_s) > 1e-8:
                cost = abs(delta_s) * open_p * 0.0005
                bar_fee += cost

                if curr_shares != 0.0:
                    closed_s = min(abs(curr_shares), abs(delta_s))
                    pnl = closed_s * (open_p - entry_p) - cost
                    trade_pnls.append(pnl)

                curr_cash -= (delta_s * open_p + cost)
                curr_shares = target_shares
                current_lev = target_lev
                if target_lev > 0:
                    if not in_pos:
                        total_trades += 1
                        entry_p = open_p
                        entry_atr = prev_atr
                        in_pos = True
                else:
                    in_pos = False

        # 5. Funding fee
        hour = int(curr_dt[11:13])
        minute = int(curr_dt[14:16])
        bar_funding = 0.0
        if hour in (0, 8, 16) and minute == 0 and curr_shares != 0.0:
            bar_funding = -curr_shares * open_p * 0.0001
            curr_cash += bar_funding

        # Liquidation check (0.4% MMR)
        if curr_shares > 0:
            worst_eq = curr_cash + curr_shares * low_p
            if worst_eq <= 0.0 or (worst_eq / (curr_shares * low_p)) < 0.004:
                is_liq = True
                curr_cash = 0.0
                curr_shares = 0.0

        if is_liq:
            equity[t] = 0.0
        else:
            bar_eq = curr_cash + curr_shares * close_p
            if bar_eq <= 0.0:
                is_liq = True
                equity[t] = 0.0
            else:
                equity[t] = bar_eq

        cash[t] = curr_cash
        shares[t] = curr_shares
        fees_paid[t] = bar_fee
        funding_paid[t] = bar_funding

    final_eq = float(equity[-1])
    years = (n - start_idx) / (365.25 * 24)
    cagr = (final_eq / 10000.0) ** (1.0 / years) - 1.0 if final_eq > 0 else -1.0

    eq_series = pd.Series(equity[start_idx:], index=pd.to_datetime(timestamps[start_idx:], unit="ms", utc=True))
    peaks = eq_series.cummax()
    dds = (eq_series - peaks) / peaks.replace(0.0, 1.0)
    max_dd = float(dds.min())

    ann_periods = 365 * 24
    pct_rets = eq_series.pct_change().dropna().replace([np.inf, -np.inf], 0.0)
    vol = float(pct_rets.std(ddof=1) * np.sqrt(ann_periods)) if len(pct_rets) > 1 else 0.0
    sharpe = float(pct_rets.mean() * ann_periods / vol) if vol > 1e-8 else 0.0

    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    win_rate = len(wins) / len(trade_pnls) if trade_pnls else 0.0
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else (999.0 if wins else 0.0)

    y_eq = eq_series.resample("YE").last()
    y_ret = y_eq.pct_change()
    if len(y_ret) > 0:
        y_ret.iloc[0] = (y_eq.iloc[0] - 10000.0) / 10000.0
    yearly_returns = y_ret.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    best_year = (int(yearly_returns.idxmax().year), float(yearly_returns.max()))
    worst_year = (int(yearly_returns.idxmin().year), float(yearly_returns.min()))

    return {
        "name": name,
        "final_equity": final_eq,
        "cagr": cagr,
        "volatility": vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "trades": total_trades,
        "win_rate": win_rate,
        "pf": pf,
        "best_year": best_year,
        "worst_year": worst_year,
        "yearly_returns": yearly_returns,
        "equity_series": eq_series,
        "fees": float(fees_paid.sum()),
        "funding": float(funding_paid.sum()),
        "is_liq": is_liq,
    }

print("Running strategic models...")
r_static1 = run_adaptive_strategy(bull_lev=1.0, bear_lev=1.0, name="Static 1x 200 SMA")
r_static3 = run_adaptive_strategy(bull_lev=3.0, bear_lev=3.0, name="Static 3x 200 SMA")
r_adapt2 = run_adaptive_strategy(bull_lev=2.0, bear_lev=0.0, name="Adaptive 2x (Good: 2x, Bad: 0x)")
r_adapt3 = run_adaptive_strategy(bull_lev=3.0, bear_lev=0.0, name="Adaptive 3x (Good: 3x, Bad: 0x)")
r_adapt4 = run_adaptive_strategy(bull_lev=4.0, bear_lev=0.0, name="Adaptive 4x (Good: 4x, Bad: 0x)")

# Benchmark
bench_s = (pd.Series(closes[start_idx:], index=pd.to_datetime(timestamps[start_idx:], unit="ms", utc=True)) / closes[start_idx]) * 10000.0

# 1. Plot Equity Curves
fig, ax = plt.subplots(figsize=(13, 7))
ax.plot(bench_s.iloc[::20], label=f"BTC Buy & Hold (${bench_s.iloc[-1]:,.0f})", color="black", ls="--", lw=1.5, alpha=0.7)
ax.plot(r_static1["equity_series"].iloc[::20], label=f"Static 1x 200 SMA (${r_static1['final_equity']:,.0f}, MaxDD {r_static1['max_dd']*100:.1f}%)", color="#7f7f7f", lw=1.3)
ax.plot(r_static3["equity_series"].iloc[::20], label=f"Static 3x 200 SMA (${r_static3['final_equity']:,.0f}, MaxDD {r_static3['max_dd']*100:.1f}%)", color="#d62728", lw=1.3)
ax.plot(r_adapt2["equity_series"].iloc[::20], label=f"Adaptive 2x: Good=2x / Bad=0x (${r_adapt2['final_equity']:,.0f}, MaxDD {r_adapt2['max_dd']*100:.1f}%)", color="#1f77b4", lw=1.8)
ax.plot(r_adapt3["equity_series"].iloc[::20], label=f"Adaptive 3x: Good=3x / Bad=0x (${r_adapt3['final_equity']:,.0f}, MaxDD {r_adapt3['max_dd']*100:.1f}%)", color="#2ca02c", lw=2.0)
ax.plot(r_adapt4["equity_series"].iloc[::20], label=f"Adaptive 4x: Good=4x / Bad=0x (${r_adapt4['final_equity']:,.0f}, MaxDD {r_adapt4['max_dd']*100:.1f}%)", color="#ff7f0e", lw=1.8)

ax.set_yscale("log")
ax.set_title("Dual-Timeframe Adaptive 200 MA Strategy: High Leverage in Bull, Zero in Bear", fontsize=13, fontweight="bold")
ax.set_ylabel("Portfolio Value ($ Log Scale)", fontsize=11)
ax.set_xlabel("Date", fontsize=11)
ax.legend(loc="upper left", fontsize=9)
ax.grid(True, alpha=0.3)
plt.tight_layout()
fig.savefig(FIG_DIR / "adaptive_200ma_equity_curves.png", dpi=180)
plt.close(fig)
print("Saved adaptive_200ma_equity_curves.png")

# 2. Heatmap of Yearly Returns
df_heat = pd.DataFrame({
    "Static 1x": r_static1["yearly_returns"] * 100,
    "Static 3x": r_static3["yearly_returns"] * 100,
    "Adaptive 2x": r_adapt2["yearly_returns"] * 100,
    "Adaptive 3x": r_adapt3["yearly_returns"] * 100,
    "Adaptive 4x": r_adapt4["yearly_returns"] * 100,
})
df_heat.index = df_heat.index.year

fig, ax = plt.subplots(figsize=(11, 6))
sns.heatmap(df_heat, annot=True, fmt=".1f", cmap="RdYlGn", center=0.0, ax=ax, cbar_kws={"label": "Yearly Return (%)"})
ax.set_title("Annual Returns (%): Static 200 MA vs Adaptive Leverage Models", fontsize=13, fontweight="bold")
ax.set_ylabel("Year", fontsize=11)
ax.set_xlabel("Strategy Model", fontsize=11)
plt.tight_layout()
fig.savefig(FIG_DIR / "adaptive_200ma_yearly_heatmap.png", dpi=180)
plt.close(fig)
print("Saved adaptive_200ma_yearly_heatmap.png")

# Summary Table Output
models = [r_static1, r_static3, r_adapt2, r_adapt3, r_adapt4]
summary_rows = []
for r in models:
    summary_rows.append({
        "Strategy Model": r["name"],
        "Final Equity ($)": f"${r['final_equity']:10,.0f}",
        "CAGR (%)": f"{r['cagr']*100:6.1f}%",
        "Sharpe": f"{r['sharpe']:5.2f}",
        "Max Drawdown": f"{r['max_dd']*100:6.1f}%",
        "Profit Factor": f"{r['pf']:5.2f}",
        "Trades": r["trades"],
        "Best Year": f"{r['best_year'][0]}: {r['best_year'][1]*100:+6.1f}%",
        "Worst Year": f"{r['worst_year'][0]}: {r['worst_year'][1]*100:+6.1f}%",
    })

print("\n" + "=" * 110)
print("COMPREHENSIVE BENCHMARK: DUAL-TIMEFRAME ADAPTIVE 200 MA STRATEGY")
print("=" * 110)
print(pd.DataFrame(summary_rows).to_string(index=False))

print("\n" + "=" * 80)
print("YEAR-BY-YEAR RETURN MATRIX (2018 - 2026):")
print("=" * 80)
print(df_heat.round(1).to_string())
