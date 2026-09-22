"""Generate full detailed metrics, best/worst years, and figures for Risk-Managed 200 MA."""

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

print("Loading candles...")
df = load_candles("1h")
n = len(df)
closes = df["close"].to_numpy(dtype=np.float64)
highs = df["high"].to_numpy(dtype=np.float64)
lows = df["low"].to_numpy(dtype=np.float64)
opens = df["open"].to_numpy(dtype=np.float64)
dts = df["datetime_utc"].to_numpy()
timestamps = df["timestamp"].to_numpy()

# Indicators
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


def run_full_simulation(
    leverage: float = 1.0,
    mode: str = "long_only",
    band_atr_mult: float = 0.5,
    filter_type: str = "ema9_entry",
    sl_atr_mult: float = 2.5,
    tp_atr_mult: float = 0.0,
):
    equity = np.zeros(n)
    cash = np.zeros(n)
    shares = np.zeros(n)
    fees_paid = np.zeros(n)
    funding_paid = np.zeros(n)

    curr_cash = 10000.0
    curr_shares = 0.0
    equity[0] = curr_cash
    is_liq = False
    liq_dt = None
    liq_price = None

    entry_price = 0.0
    entry_atr = 0.0
    current_pos = 0

    total_trades = 0
    trade_pnls = []
    regime = 0

    for t in range(200, n):
        open_p = opens[t]
        high_p = highs[t]
        low_p = lows[t]
        close_p = closes[t]
        curr_dt = dts[t]
        prev_close_p = closes[t - 1]
        prev_sma = sma200[t - 1]
        prev_atr = atr14[t - 1]
        prev_ema = ema9[t - 1]
        prev_rsi = rsi14[t - 1]

        if is_liq:
            equity[t] = 0.0
            continue

        pre_eq = curr_cash + curr_shares * open_p
        if pre_eq <= 0:
            is_liq = True
            liq_dt = curr_dt
            liq_price = open_p
            equity[t] = 0.0
            continue

        # 1. Stop-Loss / Take-Profit check
        stopped_out = False
        bar_fee = 0.0

        if curr_shares != 0.0:
            exit_price = 0.0
            if curr_shares > 0:
                if sl_atr_mult > 0.0:
                    sl_level = entry_price - sl_atr_mult * entry_atr
                    if low_p <= sl_level:
                        exit_price = min(open_p, sl_level) if open_p <= sl_level else sl_level
                        stopped_out = True
                if not stopped_out and tp_atr_mult > 0.0:
                    tp_level = entry_price + tp_atr_mult * entry_atr
                    if high_p >= tp_level:
                        exit_price = max(open_p, tp_level) if open_p >= tp_level else tp_level
                        stopped_out = True

                if stopped_out:
                    traded_dollars = curr_shares * exit_price
                    fee_slip = traded_dollars * 0.0005
                    bar_fee += fee_slip
                    pnl = curr_shares * (exit_price - entry_price) - fee_slip
                    trade_pnls.append(pnl)
                    curr_cash += (curr_shares * exit_price - fee_slip)
                    curr_shares = 0.0
                    current_pos = 0

            elif curr_shares < 0:
                if sl_atr_mult > 0.0:
                    sl_level = entry_price + sl_atr_mult * entry_atr
                    if high_p >= sl_level:
                        exit_price = max(open_p, sl_level) if open_p >= sl_level else sl_level
                        stopped_out = True
                if not stopped_out and tp_atr_mult > 0.0:
                    tp_level = entry_price - tp_atr_mult * entry_atr
                    if low_p <= tp_level:
                        exit_price = min(open_p, tp_level) if open_p <= tp_level else tp_level
                        stopped_out = True

                if stopped_out:
                    traded_dollars = abs(curr_shares) * exit_price
                    fee_slip = traded_dollars * 0.0005
                    bar_fee += fee_slip
                    pnl = abs(curr_shares) * (entry_price - exit_price) - fee_slip
                    trade_pnls.append(pnl)
                    curr_cash -= (abs(curr_shares) * exit_price + fee_slip)
                    curr_shares = 0.0
                    current_pos = 0

        # 2. Hysteresis Regime Determination
        upper_band = prev_sma + band_atr_mult * prev_atr
        lower_band = prev_sma - band_atr_mult * prev_atr

        regime_changed = False
        if prev_close_p > upper_band:
            if regime != 1:
                regime = 1
                regime_changed = True
        elif prev_close_p < lower_band:
            if regime != -1:
                regime = -1
                regime_changed = True

        target_signal = current_pos
        if regime_changed:
            if regime == 1:
                valid = True
                if filter_type == "ema9_entry" and not (prev_close_p > prev_ema and prev_ema > prev_sma):
                    valid = False
                elif filter_type == "rsi_entry" and not (prev_rsi > 50.0):
                    valid = False
                target_signal = 1 if valid else 0
            elif regime == -1:
                if mode == "long_short":
                    valid = True
                    if filter_type == "ema9_entry" and not (prev_close_p < prev_ema and prev_ema < prev_sma):
                        valid = False
                    elif filter_type == "rsi_entry" and not (prev_rsi < 50.0):
                        valid = False
                    target_signal = -1 if valid else 0
                else:
                    target_signal = 0

        # 3. Position Rebalancing
        if not stopped_out and target_signal != current_pos:
            pre_eq = curr_cash + curr_shares * open_p
            if pre_eq > 0:
                target_dollars = float(target_signal) * leverage * pre_eq
                target_shares = target_dollars / open_p
                delta_s = target_shares - curr_shares

                if abs(delta_s) > 1e-8:
                    traded_dollars = abs(delta_s) * open_p
                    cost = traded_dollars * 0.0005
                    bar_fee += cost

                    if curr_shares != 0.0:
                        if curr_shares > 0:
                            closed_s = min(curr_shares, abs(delta_s))
                            pnl = closed_s * (open_p - entry_price) - (closed_s * open_p * 0.0005)
                        else:
                            closed_s = min(abs(curr_shares), delta_s)
                            pnl = closed_s * (entry_price - open_p) - (closed_s * open_p * 0.0005)
                        trade_pnls.append(pnl)

                    curr_cash -= (delta_s * open_p + cost)
                    curr_shares = target_shares
                    current_pos = target_signal
                    if target_signal != 0:
                        total_trades += 1
                        entry_price = open_p
                        entry_atr = prev_atr

        # 4. Binance Funding Fee (00:00, 08:00, 16:00 UTC)
        hour = int(curr_dt[11:13])
        minute = int(curr_dt[14:16])
        bar_funding = 0.0
        if hour in (0, 8, 16) and minute == 0 and curr_shares != 0.0:
            bar_funding = -curr_shares * open_p * 0.0001
            curr_cash += bar_funding

        # 5. Binance Intraday Liquidation Check (0.4% MMR)
        if curr_shares > 0:
            worst_eq = curr_cash + curr_shares * low_p
            if worst_eq <= 0.0 or (worst_eq / (curr_shares * low_p)) < 0.004:
                is_liq = True
                liq_dt = curr_dt
                liq_price = low_p
                curr_cash = 0.0
                curr_shares = 0.0
        elif curr_shares < 0:
            worst_eq = curr_cash + curr_shares * high_p
            if worst_eq <= 0.0 or (worst_eq / (abs(curr_shares) * high_p)) < 0.004:
                is_liq = True
                liq_dt = curr_dt
                liq_price = high_p
                curr_cash = 0.0
                curr_shares = 0.0

        if is_liq:
            equity[t] = 0.0
        else:
            bar_eq = curr_cash + curr_shares * close_p
            if bar_eq <= 0:
                is_liq = True
                liq_dt = curr_dt
                liq_price = close_p
                equity[t] = 0.0
                curr_cash = 0.0
                curr_shares = 0.0
            else:
                equity[t] = bar_eq

        cash[t] = curr_cash
        shares[t] = curr_shares
        fees_paid[t] = bar_fee
        funding_paid[t] = bar_funding

    # Metrics
    final_eq = float(equity[-1])
    years = (n - 200) / (365.25 * 24)
    cagr = (final_eq / 10000.0) ** (1.0 / years) - 1.0 if final_eq > 0 else -1.0

    eq_series = pd.Series(equity[200:], index=pd.to_datetime(timestamps[200:], unit="ms", utc=True))
    peaks = eq_series.cummax()
    dds = (eq_series - peaks) / peaks.replace(0.0, 1.0)
    max_dd = float(dds.min())

    ann_periods = 365 * 24
    pct_rets = eq_series.pct_change().dropna().replace([np.inf, -np.inf], 0.0)
    vol = float(pct_rets.std(ddof=1) * np.sqrt(ann_periods)) if len(pct_rets) > 1 else 0.0
    sharpe = float(pct_rets.mean() * ann_periods / vol) if vol > 1e-8 else 0.0

    downside = pct_rets[pct_rets < 0.0]
    down_vol = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(ann_periods)) if len(downside) > 0 else 0.0
    sortino = float(pct_rets.mean() * ann_periods / down_vol) if down_vol > 1e-8 else 0.0
    calmar = float(cagr / abs(max_dd)) if abs(max_dd) > 1e-6 else 0.0

    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    win_rate = len(wins) / len(trade_pnls) if trade_pnls else 0.0
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else (999.0 if wins else 0.0)

    # Yearly returns
    y_eq = eq_series.resample("YE").last()
    y_ret = y_eq.pct_change()
    if len(y_ret) > 0:
        y_ret.iloc[0] = (y_eq.iloc[0] - 10000.0) / 10000.0
    yearly_returns = y_ret.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    best_year = (int(yearly_returns.idxmax().year), float(yearly_returns.max())) if len(yearly_returns) > 0 else (2017, 0.0)
    worst_year = (int(yearly_returns.idxmin().year), float(yearly_returns.min())) if len(yearly_returns) > 0 else (2017, 0.0)

    return {
        "leverage": leverage,
        "mode": mode,
        "final_equity": final_eq,
        "cagr": cagr,
        "volatility": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_dd": max_dd,
        "calmar": calmar,
        "trades": total_trades,
        "win_rate": win_rate,
        "pf": pf,
        "is_liquidated": is_liq,
        "liq_dt": liq_dt,
        "liq_price": liq_price,
        "total_fees": float(fees_paid.sum()),
        "total_funding": float(funding_paid.sum()),
        "best_year": best_year,
        "worst_year": worst_year,
        "yearly_returns": yearly_returns,
        "equity_series": eq_series,
    }

print("Simulating all models across 1x to 10x leverage...")

# Run 3 suites:
# 1. Raw Baseline Long-Only
raw_lo = [run_full_simulation(lev, mode="long_only", band_atr_mult=0.0, filter_type="none", sl_atr_mult=0.0) for lev in range(1, 11)]

# 2. Risk-Managed: ATR Band 0.5x + SL 2.5x (Trend Runner)
atr_lo = [run_full_simulation(lev, mode="long_only", band_atr_mult=0.5, filter_type="none", sl_atr_mult=2.5) for lev in range(1, 11)]

# 3. Risk-Managed: ATR Band 0.5x + EMA 9 Confirmation + SL 2.5x (Smooth Trend)
ema_lo = [run_full_simulation(lev, mode="long_only", band_atr_mult=0.5, filter_type="ema9_entry", sl_atr_mult=2.5) for lev in range(1, 11)]

# 4. Risk-Managed: ATR Band 0.5x + EMA 9 + SL 2.5x (Long-Short)
ema_ls = [run_full_simulation(lev, mode="long_short", band_atr_mult=0.5, filter_type="ema9_entry", sl_atr_mult=2.5) for lev in range(1, 11)]

# Plot 1: Risk-Managed 1x to 10x Equity Curves (EMA 9 + SL 2.5x Long-Only)
fig, ax = plt.subplots(figsize=(13, 7))
cmap = plt.get_cmap("turbo", 10)
bench_s = (pd.Series(closes[200:], index=pd.to_datetime(timestamps[200:], unit="ms", utc=True)) / closes[200]) * 10000.0

for r in ema_lo:
    lev = int(r["leverage"])
    eq = r["equity_series"]
    lbl = f"{lev}x: ${r['final_equity']:,.0f} (MaxDD {r['max_dd']*100:.1f}%)"
    ax.plot(eq.iloc[::20], label=lbl, color=cmap(lev - 1), lw=1.6)

ax.plot(bench_s.iloc[::20], label=f"BTC Buy & Hold (${bench_s.iloc[-1]:,.0f})", color="black", ls="--", lw=1.5, alpha=0.7)
ax.set_yscale("log")
ax.set_title("Risk-Managed 1h 200 SMA: 1x to 10x Leverage (ATR Band 0.5x + EMA 9 Confirm + 2.5x SL)", fontsize=13, fontweight="bold")
ax.set_ylabel("Portfolio Value ($ Log Scale)", fontsize=11)
ax.set_xlabel("Year", fontsize=11)
ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8.5)
ax.grid(True, alpha=0.3)
plt.tight_layout()
fig.savefig(FIG_DIR / "risk_managed_ema9_leverage_curves.png", dpi=180, bbox_inches="tight")
plt.close(fig)
print("Saved risk_managed_ema9_leverage_curves.png")

# Plot 2: ATR Band 0.5x + SL 2.5x Leverage Curves
fig, ax = plt.subplots(figsize=(13, 7))
for r in atr_lo:
    lev = int(r["leverage"])
    eq = r["equity_series"]
    lbl = f"{lev}x: ${r['final_equity']:,.0f} (MaxDD {r['max_dd']*100:.1f}%)"
    ax.plot(eq.iloc[::20], label=lbl, color=cmap(lev - 1), lw=1.6)

ax.plot(bench_s.iloc[::20], label=f"BTC Buy & Hold (${bench_s.iloc[-1]:,.0f})", color="black", ls="--", lw=1.5, alpha=0.7)
ax.set_yscale("log")
ax.set_title("Risk-Managed 1h 200 SMA: 1x to 10x Leverage (ATR Band 0.5x + 2.5x ATR Stop-Loss)", fontsize=13, fontweight="bold")
ax.set_ylabel("Portfolio Value ($ Log Scale)", fontsize=11)
ax.set_xlabel("Year", fontsize=11)
ax.legend(bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8.5)
ax.grid(True, alpha=0.3)
plt.tight_layout()
fig.savefig(FIG_DIR / "risk_managed_atr_band_leverage_curves.png", dpi=180, bbox_inches="tight")
plt.close(fig)
print("Saved risk_managed_atr_band_leverage_curves.png")

# Plot 3: Heatmap of Yearly Returns for EMA 9 + SL 2.5x Long-Only
heat_dict = {}
for r in ema_lo:
    heat_dict[f"{int(r['leverage'])}x"] = r["yearly_returns"] * 100

df_heat = pd.DataFrame(heat_dict)
df_heat.index = df_heat.index.year

fig, ax = plt.subplots(figsize=(12, 6))
sns.heatmap(df_heat, annot=True, fmt=".1f", cmap="RdYlGn", center=0.0, ax=ax, cbar_kws={"label": "Yearly Return (%)"})
ax.set_title("Risk-Managed (ATR Band + EMA 9 + SL): Annual Return (%) across 1x-10x Leverage", fontsize=13, fontweight="bold")
ax.set_ylabel("Year", fontsize=11)
ax.set_xlabel("Leverage Tier", fontsize=11)
plt.tight_layout()
fig.savefig(FIG_DIR / "risk_managed_yearly_heatmap.png", dpi=180)
plt.close(fig)
print("Saved risk_managed_yearly_heatmap.png")

# Plot 4: Direct Comparison: Raw 200 SMA vs Risk-Managed at 2x and 3x Leverage
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9), sharex=True)

# 2x comparison
ax1.plot(raw_lo[1]["equity_series"].iloc[::20], label=f"Raw 200 SMA 2x: ${raw_lo[1]['final_equity']:,.0f} (MaxDD {raw_lo[1]['max_dd']*100:.1f}%)", color="#d62728", lw=1.5)
ax1.plot(atr_lo[1]["equity_series"].iloc[::20], label=f"ATR Band + SL 2x: ${atr_lo[1]['final_equity']:,.0f} (MaxDD {atr_lo[1]['max_dd']*100:.1f}%)", color="#1f77b4", lw=1.5)
ax1.plot(ema_lo[1]["equity_series"].iloc[::20], label=f"ATR + EMA9 + SL 2x: ${ema_lo[1]['final_equity']:,.0f} (MaxDD {ema_lo[1]['max_dd']*100:.1f}%)", color="#2ca02c", lw=1.5)
ax1.plot(bench_s.iloc[::20], label="BTC Buy & Hold", color="black", ls="--", lw=1.2, alpha=0.6)
ax1.set_yscale("log")
ax1.set_title("2x Leverage: Raw 200 SMA vs Risk-Managed Variants", fontsize=12, fontweight="bold")
ax1.set_ylabel("Portfolio Value ($ Log Scale)")
ax1.legend(loc="upper left")
ax1.grid(True, alpha=0.3)

# 3x comparison
ax2.plot(raw_lo[2]["equity_series"].iloc[::20], label=f"Raw 200 SMA 3x: ${raw_lo[2]['final_equity']:,.0f} (MaxDD {raw_lo[2]['max_dd']*100:.1f}%)", color="#d62728", lw=1.5)
ax2.plot(atr_lo[2]["equity_series"].iloc[::20], label=f"ATR Band + SL 3x: ${atr_lo[2]['final_equity']:,.0f} (MaxDD {atr_lo[2]['max_dd']*100:.1f}%)", color="#1f77b4", lw=1.5)
ax2.plot(ema_lo[2]["equity_series"].iloc[::20], label=f"ATR + EMA9 + SL 3x: ${ema_lo[2]['final_equity']:,.0f} (MaxDD {ema_lo[2]['max_dd']*100:.1f}%)", color="#2ca02c", lw=1.5)
ax2.plot(bench_s.iloc[::20], label="BTC Buy & Hold", color="black", ls="--", lw=1.2, alpha=0.6)
ax2.set_yscale("log")
ax2.set_title("3x Leverage: Raw 200 SMA vs Risk-Managed Variants", fontsize=12, fontweight="bold")
ax2.set_ylabel("Portfolio Value ($ Log Scale)")
ax2.legend(loc="upper left")
ax2.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(FIG_DIR / "risk_managed_vs_raw_comparison.png", dpi=180)
plt.close(fig)
print("Saved risk_managed_vs_raw_comparison.png")

# Print Summary Tables for Output
print("\n" + "=" * 100)
print("TABLE 1: RISK-MANAGED 200 SMA (ATR BAND 0.5x + EMA 9 CONFIRMATION + SL 2.5x ATR) - LONG-ONLY")
print("=" * 100)
rows = []
for r in ema_lo:
    rows.append({
        "Lev": f"{int(r['leverage'])}x",
        "Final ($)": f"${r['final_equity']:10,.0f}",
        "CAGR": f"{r['cagr']*100:6.1f}%",
        "Sharpe": f"{r['sharpe']:5.2f}",
        "Sortino": f"{r['sortino']:5.2f}",
        "MaxDD": f"{r['max_dd']*100:6.1f}%",
        "Calmar": f"{r['calmar']:5.2f}",
        "WinRate": f"{r['win_rate']*100:5.1f}%",
        "PF": f"{r['pf']:5.2f}",
        "Trades": r["trades"],
        "Best Year": f"{r['best_year'][0]}: {r['best_year'][1]*100:+6.1f}%",
        "Worst Year": f"{r['worst_year'][0]}: {r['worst_year'][1]*100:+6.1f}%",
        "Status": "SURVIVED (No Liq)" if not r["is_liquidated"] else "LIQUIDATED",
    })
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 100)
print("TABLE 2: RISK-MANAGED 200 SMA (ATR BAND 0.5x + SL 2.5x ATR) - LONG-ONLY")
print("=" * 100)
rows_atr = []
for r in atr_lo:
    rows_atr.append({
        "Lev": f"{int(r['leverage'])}x",
        "Final ($)": f"${r['final_equity']:10,.0f}",
        "CAGR": f"{r['cagr']*100:6.1f}%",
        "Sharpe": f"{r['sharpe']:5.2f}",
        "Sortino": f"{r['sortino']:5.2f}",
        "MaxDD": f"{r['max_dd']*100:6.1f}%",
        "Calmar": f"{r['calmar']:5.2f}",
        "WinRate": f"{r['win_rate']*100:5.1f}%",
        "PF": f"{r['pf']:5.2f}",
        "Trades": r["trades"],
        "Best Year": f"{r['best_year'][0]}: {r['best_year'][1]*100:+6.1f}%",
        "Worst Year": f"{r['worst_year'][0]}: {r['worst_year'][1]*100:+6.1f}%",
        "Status": "SURVIVED (No Liq)" if not r["is_liquidated"] else "LIQUIDATED",
    })
print(pd.DataFrame(rows_atr).to_string(index=False))

print("\n" + "=" * 100)
print("TABLE 3: RISK-MANAGED 200 SMA (ATR BAND 0.5x + EMA 9 CONFIRMATION + SL 2.5x ATR) - LONG-SHORT")
print("=" * 100)
rows_ls = []
for r in ema_ls:
    rows_ls.append({
        "Lev": f"{int(r['leverage'])}x",
        "Final ($)": f"${r['final_equity']:10,.0f}",
        "CAGR": f"{r['cagr']*100:6.1f}%",
        "Sharpe": f"{r['sharpe']:5.2f}",
        "Sortino": f"{r['sortino']:5.2f}",
        "MaxDD": f"{r['max_dd']*100:6.1f}%",
        "Calmar": f"{r['calmar']:5.2f}",
        "WinRate": f"{r['win_rate']*100:5.1f}%",
        "PF": f"{r['pf']:5.2f}",
        "Trades": r["trades"],
        "Best Year": f"{r['best_year'][0]}: {r['best_year'][1]*100:+6.1f}%",
        "Worst Year": f"{r['worst_year'][0]}: {r['worst_year'][1]*100:+6.1f}%",
        "Status": "SURVIVED (No Liq)" if not r["is_liquidated"] else "LIQUIDATED",
    })
print(pd.DataFrame(rows_ls).to_string(index=False))

print("\n" + "=" * 100)
print("YEAR-BY-YEAR RETURN MATRIX (EMA 9 + SL 2.5x LONG-ONLY):")
print(df_heat.round(1).to_string())
