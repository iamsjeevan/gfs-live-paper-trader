"""Test Macro-Adaptive Dynamic Leverage Strategy on 1h 200 MA."""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backtest.data import load_candles

df = load_candles("1h")
n = len(df)
closes = df["close"].to_numpy(dtype=np.float64)
highs = df["high"].to_numpy(dtype=np.float64)
lows = df["low"].to_numpy(dtype=np.float64)
opens = df["open"].to_numpy(dtype=np.float64)
dts = df["datetime_utc"].to_numpy()
timestamps = df["timestamp"].to_numpy()

# 1h 200 SMA
sma200_1h = pd.Series(closes).rolling(200).mean().to_numpy()
# Daily 200 SMA (4800 1h bars)
sma200_daily = pd.Series(closes).rolling(200 * 24).mean().to_numpy()

# 1h ATR 14
prev_close = np.roll(closes, 1)
prev_close[0] = closes[0]
tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
atr14 = pd.Series(tr).rolling(14).mean().to_numpy()

def run_macro_adaptive_sim(
    bull_leverage: float = 4.0,
    bear_leverage: float = 0.0, # 0.0 = Cash in bear market, 1.0 = 1x in bear
    band_atr_mult: float = 0.5,
    sl_atr_mult: float = 2.5,
):
    equity = np.zeros(n)
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
    fees_total = 0.0
    funding_total = 0.0

    start_idx = 4800

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

        # 1. Stop-Loss check
        stopped_out = False
        if in_pos and sl_atr_mult > 0.0:
            if curr_shares > 0:
                sl_level = entry_p - sl_atr_mult * entry_atr
                if low_p <= sl_level:
                    exit_p = min(open_p, sl_level) if open_p <= sl_level else sl_level
                    cost = abs(curr_shares) * exit_p * 0.0005
                    fees_total += cost
                    pnl = curr_shares * (exit_p - entry_p) - cost
                    trade_pnls.append(pnl)
                    curr_cash += (curr_shares * exit_p - cost)
                    curr_shares = 0.0
                    in_pos = False
                    current_lev = 0.0
                    stopped_out = True

        # 2. 1h 200 SMA Hysteresis
        upper_band = prev_sma + band_atr_mult * prev_atr
        lower_band = prev_sma - band_atr_mult * prev_atr

        regime_changed = False
        if prev_c > upper_band:
            if regime != 1:
                regime = 1
                regime_changed = True
        elif prev_c < lower_band:
            if regime != -1:
                regime = -1
                regime_changed = True

        # 3. Dynamic Leverage Target
        # Good time: prev_c > prev_daily_sma
        # Bad time: prev_c < prev_daily_sma
        is_bull = (prev_c > prev_daily_sma)
        target_lev = 0.0

        if regime == 1:
            target_lev = bull_leverage if is_bull else bear_leverage
        else:
            target_lev = 0.0 # flat when 1h 200 SMA breaks down

        # Rebalance only when target leverage changes or stopped out
        if not stopped_out and target_lev != current_lev:
            target_dollars = target_lev * pre_eq
            target_shares = target_dollars / open_p
            delta_s = target_shares - curr_shares

            if abs(delta_s) > 1e-8:
                cost = abs(delta_s) * open_p * 0.0005
                fees_total += cost

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

        # Funding fee
        hour = int(curr_dt[11:13])
        minute = int(curr_dt[14:16])
        if hour in (0, 8, 16) and minute == 0 and curr_shares != 0.0:
            f = -curr_shares * open_p * 0.0001
            funding_total += f
            curr_cash += f

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

    final_eq = equity[-1]
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

    best_year = (int(yearly_returns.idxmax().year), float(yearly_returns.max())) if len(yearly_returns) > 0 else (2018, 0.0)
    worst_year = (int(yearly_returns.idxmin().year), float(yearly_returns.min())) if len(yearly_returns) > 0 else (2018, 0.0)

    return {
        "bull_lev": bull_leverage,
        "bear_lev": bear_leverage,
        "final_equity": final_eq,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "trades": total_trades,
        "win_rate": win_rate,
        "pf": pf,
        "best_year": best_year,
        "worst_year": worst_year,
        "yearly_returns": yearly_returns,
        "equity_series": eq_series,
        "fees": fees_total,
        "funding": funding_total,
        "is_liq": is_liq,
    }

print("=== MACRO-ADAPTIVE DYNAMIC LEVERAGE SWEEP (BULL 1x to 10x, BEAR = 0x / CASH) ===")
print("In Bear Market (Price < Daily 200 SMA): 0x (Completely Flat, No Churn)")
print("In Bull Market (Price > Daily 200 SMA): 1x to 10x Leverage on 1h 200 SMA Breakouts")
print("-" * 95)

for lev in range(1, 11):
    res = run_macro_adaptive_sim(bull_leverage=float(lev), bear_leverage=0.0)
    status = "LIQUIDATED" if res["is_liq"] else f"${res['final_equity']:11,.0f}"
    print(f"Bull Lev: {lev:2d}x | Final: {status} | CAGR: {res['cagr']*100:5.1f}% | Sharpe: {res['sharpe']:4.2f} | MaxDD: {res['max_dd']*100:5.1f}% | PF: {res['pf']:4.2f} | Best: {res['best_year'][0]} ({res['best_year'][1]*100:+5.1f}%) | Worst: {res['worst_year'][0]} ({res['worst_year'][1]*100:+5.1f}%)")

print("\n=== MACRO-ADAPTIVE DYNAMIC LEVERAGE SWEEP (BULL 1x to 10x, BEAR = 1x DEFENSIVE) ===")
for lev in range(1, 11):
    res = run_macro_adaptive_sim(bull_leverage=float(lev), bear_leverage=1.0)
    status = "LIQUIDATED" if res["is_liq"] else f"${res['final_equity']:11,.0f}"
    print(f"Bull Lev: {lev:2d}x | Final: {status} | CAGR: {res['cagr']*100:5.1f}% | Sharpe: {res['sharpe']:4.2f} | MaxDD: {res['max_dd']*100:5.1f}% | PF: {res['pf']:4.2f} | Best: {res['best_year'][0]} ({res['best_year'][1]*100:+5.1f}%) | Worst: {res['worst_year'][0]} ({res['worst_year'][1]*100:+5.1f}%)")
