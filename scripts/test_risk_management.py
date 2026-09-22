"""Benchmarking Risk Management filters, Stop-Loss, and Take-Profit for 1h 200 MA."""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
sys.path.insert(0, str(BASE_DIR))

from backtest.data import load_candles

df = load_candles("1h")
n = len(df)
closes = df["close"].to_numpy(dtype=np.float64)
highs = df["high"].to_numpy(dtype=np.float64)
lows = df["low"].to_numpy(dtype=np.float64)
opens = df["open"].to_numpy(dtype=np.float64)
dts = df["datetime_utc"].to_numpy()

# Calculate indicators
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

def run_sim(
    leverage: float = 1.0,
    mode: str = "long_short",
    band_atr_mult: float = 0.5,
    filter_type: str = "none",  # 'none', 'ema9_entry', 'rsi_entry', 'ema9_and_rsi'
    sl_atr_mult: float = 0.0,   # e.g. 2.0, 2.5, 3.0
    tp_atr_mult: float = 0.0,   # e.g. 4.0, 6.0
    trail_atr_mult: float = 0.0,
):
    equity = np.zeros(n)
    curr_cash = 10000.0
    curr_shares = 0.0
    equity[0] = curr_cash
    is_liq = False

    entry_price = 0.0
    entry_atr = 0.0
    extreme_price = 0.0
    current_pos = 0 # +1, -1, 0

    total_trades = 0
    trade_pnls = []
    regime = 0 # current trend regime: +1 bullish, -1 bearish
    prev_regime = 0

    for t in range(200, n):
        open_p = opens[t]
        high_p = highs[t]
        low_p = lows[t]
        close_p = closes[t]
        curr_dt = dts[t]
        prev_close_p = closes[t-1]
        prev_sma = sma200[t-1]
        prev_atr = atr14[t-1]
        prev_ema = ema9[t-1]
        prev_rsi = rsi14[t-1]

        if is_liq:
            equity[t] = 0.0
            continue

        pre_eq = curr_cash + curr_shares * open_p
        if pre_eq <= 0:
            is_liq = True
            equity[t] = 0.0
            continue

        # 1. Intraday Stop-Loss / Take-Profit check
        stopped_out = False
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
                if not stopped_out and trail_atr_mult > 0.0:
                    trail_level = extreme_price - trail_atr_mult * entry_atr
                    if low_p <= trail_level:
                        exit_price = min(open_p, trail_level) if open_p <= trail_level else trail_level
                        stopped_out = True
                    extreme_price = max(extreme_price, high_p)

                if stopped_out:
                    traded_dollars = curr_shares * exit_price
                    fee_slip = traded_dollars * 0.0005
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
                if not stopped_out and trail_atr_mult > 0.0:
                    trail_level = extreme_price + trail_atr_mult * entry_atr
                    if high_p >= trail_level:
                        exit_price = max(open_p, trail_level) if open_p >= trail_level else trail_level
                        stopped_out = True
                    extreme_price = min(extreme_price, low_p)

                if stopped_out:
                    traded_dollars = abs(curr_shares) * exit_price
                    fee_slip = traded_dollars * 0.0005
                    pnl = abs(curr_shares) * (entry_price - exit_price) - fee_slip
                    trade_pnls.append(pnl)
                    curr_cash -= (abs(curr_shares) * exit_price + fee_slip)
                    curr_shares = 0.0
                    current_pos = 0

        # 2. Determine Regime from bar t-1 close
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

        # Target signal logic:
        # If stopped out, we don't re-enter in the SAME regime unless a NEW regime crossover happens!
        target_signal = current_pos
        if regime_changed:
            if regime == 1:
                # Check Entry Filters
                valid = True
                if filter_type == "ema9_entry" and not (prev_close_p > prev_ema and prev_ema > prev_sma):
                    valid = False
                elif filter_type == "rsi_entry" and not (prev_rsi > 50.0):
                    valid = False
                elif filter_type == "ema9_and_rsi" and not (prev_close_p > prev_ema and prev_rsi > 50.0):
                    valid = False
                
                target_signal = 1 if valid else 0
            elif regime == -1:
                if mode == "long_short":
                    valid = True
                    if filter_type == "ema9_entry" and not (prev_close_p < prev_ema and prev_ema < prev_sma):
                        valid = False
                    elif filter_type == "rsi_entry" and not (prev_rsi < 50.0):
                        valid = False
                    elif filter_type == "ema9_and_rsi" and not (prev_close_p < prev_ema and prev_rsi < 50.0):
                        valid = False
                    target_signal = -1 if valid else 0
                else:
                    target_signal = 0 # flat in long-only

        # 3. Position Rebalancing at Open
        if not stopped_out and target_signal != current_pos:
            pre_eq = curr_cash + curr_shares * open_p
            if pre_eq > 0:
                target_dollars = float(target_signal) * leverage * pre_eq
                target_shares = target_dollars / open_p
                delta_s = target_shares - curr_shares

                if abs(delta_s) > 1e-8:
                    traded_dollars = abs(delta_s) * open_p
                    cost = traded_dollars * 0.0005
                    
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
                        extreme_price = open_p

        # 4. Binance Funding Fee (00:00, 08:00, 16:00 UTC)
        hour = int(curr_dt[11:13])
        minute = int(curr_dt[14:16])
        if hour in (0, 8, 16) and minute == 0 and curr_shares != 0.0:
            curr_cash += (-curr_shares * open_p * 0.0001)

        # 5. Binance Intraday Liquidation Check (0.4% MMR)
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
                equity[t] = 0.0
            else:
                equity[t] = bar_eq

    final_eq = equity[-1]
    years = (n - 200) / (365.25 * 24)
    cagr = (final_eq / 10000.0) ** (1.0 / years) - 1.0 if final_eq > 0 else -1.0
    
    eq_series = pd.Series(equity[200:])
    peaks = eq_series.cummax()
    dds = (eq_series - peaks) / peaks.replace(0.0, 1.0)
    max_dd = dds.min()

    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    win_rate = len(wins) / len(trade_pnls) if trade_pnls else 0.0
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else (999.0 if wins else 0.0)

    return {
        "final_eq": final_eq,
        "cagr": cagr,
        "max_dd": max_dd,
        "trades": total_trades,
        "win_rate": win_rate,
        "pf": pf,
        "is_liq": is_liq,
    }

print("Testing proper entry filter & stop-loss configurations...")
test_configs = [
    ("Raw 200 SMA Baseline", dict(band_atr_mult=0.0, filter_type="none", sl_atr_mult=0.0, tp_atr_mult=0.0)),
    ("ATR Band 0.5x Only", dict(band_atr_mult=0.5, filter_type="none", sl_atr_mult=0.0, tp_atr_mult=0.0)),
    ("ATR Band 0.5x + EMA 9 Entry Confirm", dict(band_atr_mult=0.5, filter_type="ema9_entry", sl_atr_mult=0.0, tp_atr_mult=0.0)),
    ("ATR Band 0.5x + RSI 50 Entry Confirm", dict(band_atr_mult=0.5, filter_type="rsi_entry", sl_atr_mult=0.0, tp_atr_mult=0.0)),
    ("ATR Band 0.5x + EMA 9 & RSI Confirm", dict(band_atr_mult=0.5, filter_type="ema9_and_rsi", sl_atr_mult=0.0, tp_atr_mult=0.0)),
    ("ATR Band 0.5x + SL 2.5x ATR", dict(band_atr_mult=0.5, filter_type="none", sl_atr_mult=2.5, tp_atr_mult=0.0)),
    ("ATR Band 0.5x + SL 3.0x ATR", dict(band_atr_mult=0.5, filter_type="none", sl_atr_mult=3.0, tp_atr_mult=0.0)),
    ("ATR Band 0.5x + SL 2.5x + TP 5.0x", dict(band_atr_mult=0.5, filter_type="none", sl_atr_mult=2.5, tp_atr_mult=5.0)),
    ("ATR Band 0.5x + EMA 9 + SL 2.5x", dict(band_atr_mult=0.5, filter_type="ema9_entry", sl_atr_mult=2.5, tp_atr_mult=0.0)),
    ("ATR Band 0.5x + EMA 9 + SL 3.0x", dict(band_atr_mult=0.5, filter_type="ema9_entry", sl_atr_mult=3.0, tp_atr_mult=0.0)),
]

print("\n=== LONG-SHORT 1x LEVERAGE ===")
for name, cfg in test_configs:
    r = run_sim(leverage=1.0, mode="long_short", **cfg)
    print(f"{name:40s} | Trades: {r['trades']:5d} | WR: {r['win_rate']*100:4.1f}% | PF: {r['pf']:4.2f} | Final: ${r['final_eq']:10,.0f} | CAGR: {r['cagr']*100:5.1f}% | MaxDD: {r['max_dd']*100:5.1f}%")

print("\n=== LONG-ONLY 1x LEVERAGE ===")
for name, cfg in test_configs:
    r = run_sim(leverage=1.0, mode="long_only", **cfg)
    print(f"{name:40s} | Trades: {r['trades']:5d} | WR: {r['win_rate']*100:4.1f}% | PF: {r['pf']:4.2f} | Final: ${r['final_eq']:10,.0f} | CAGR: {r['cagr']*100:5.1f}% | MaxDD: {r['max_dd']*100:5.1f}%")

print("\n=== LONG-ONLY 2x LEVERAGE ===")
for name, cfg in test_configs:
    r = run_sim(leverage=2.0, mode="long_only", **cfg)
    status = "LIQ" if r['is_liq'] else f"${r['final_eq']:10,.0f}"
    print(f"{name:40s} | Status: {status:12s} | Trades: {r['trades']:5d} | CAGR: {r['cagr']*100:5.1f}% | MaxDD: {r['max_dd']*100:5.1f}%")

print("\n=== LONG-ONLY 3x LEVERAGE ===")
for name, cfg in test_configs:
    r = run_sim(leverage=3.0, mode="long_only", **cfg)
    status = "LIQ" if r['is_liq'] else f"${r['final_eq']:10,.0f}"
    print(f"{name:40s} | Status: {status:12s} | Trades: {r['trades']:5d} | CAGR: {r['cagr']*100:5.1f}% | MaxDD: {r['max_dd']*100:5.1f}%")
