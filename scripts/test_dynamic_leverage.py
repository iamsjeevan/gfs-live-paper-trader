"""Benchmark Dynamic Leverage models on 1h 200 MA (more leverage in good times, less in bad times)."""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backtest.data import load_candles

print("Loading candles...")
df = load_candles("1h")
n = len(df)
closes = df["close"].to_numpy(dtype=np.float64)
highs = df["high"].to_numpy(dtype=np.float64)
lows = df["low"].to_numpy(dtype=np.float64)
opens = df["open"].to_numpy(dtype=np.float64)
dts = df["datetime_utc"].to_numpy()
timestamps = df["timestamp"].to_numpy()

# 1. 1h 200 SMA
sma200_1h = pd.Series(closes).rolling(200).mean().to_numpy()

# 2. Daily 200 SMA (200 days = 4800 hours)
sma200_daily = pd.Series(closes).rolling(200 * 24).mean().to_numpy()

# 3. 1h EMA 21
ema21_1h = pd.Series(closes).ewm(span=21, adjust=False).mean().to_numpy()

# 4. 1h EMA 9
ema9_1h = pd.Series(closes).ewm(span=9, adjust=False).mean().to_numpy()

# 5. 1h ATR 14
prev_close = np.roll(closes, 1)
prev_close[0] = closes[0]
tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))
atr14 = pd.Series(tr).rolling(14).mean().to_numpy()

# 6. 200 SMA Slope (over 24 hours)
sma200_slope = (sma200_1h - np.roll(sma200_1h, 24)) / np.maximum(atr14, 1.0)

print("Indicators ready.")

# Let's test different Dynamic Leverage strategies
# We will test on a $10,000 account with compounding (or fixed base capital)

def run_dynamic_strategy(
    strategy_name: str,
    get_target_leverage_fn,
    use_sl: bool = True,
    sl_atr_mult: float = 2.5,
    band_atr_mult: float = 0.5,
    mode: str = "long_only",
):
    equity = np.zeros(n)
    curr_cash = 10000.0
    curr_shares = 0.0
    equity[0] = curr_cash
    is_liq = False

    entry_p = 0.0
    entry_atr = 0.0
    shares = 0.0
    current_lev = 0.0
    in_pos = False

    total_trades = 0
    trade_pnls = []
    regime = 0
    fees_total = 0.0
    funding_total = 0.0

    start_idx = 4800 # after daily 200 SMA is warm

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
        prev_ema9 = ema9_1h[t - 1]
        prev_ema21 = ema21_1h[t - 1]
        prev_slope = sma200_slope[t - 1]

        if is_liq:
            equity[t] = 0.0
            continue

        pre_eq = curr_cash + curr_shares * open_p
        if pre_eq <= 0.0:
            is_liq = True
            equity[t] = 0.0
            continue

        # 1. Stop-Loss Check during bar t
        stopped_out = False
        if in_pos and use_sl:
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

        # 2. Hysteresis Regime Determination
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

        # 3. Determine Dynamic Leverage
        # Context dict passed to function
        ctx = {
            "prev_close": prev_c,
            "sma_1h": prev_sma,
            "sma_daily": prev_daily_sma,
            "ema9": prev_ema9,
            "ema21": prev_ema21,
            "atr": prev_atr,
            "slope": prev_slope,
            "regime": regime,
            "in_pos": in_pos,
            "entry_p": entry_p,
            "current_lev": current_lev,
            "t": t,
        }

        target_lev = get_target_leverage_fn(ctx)

        # 4. Rebalancing if leverage changed or stopped out
        if not stopped_out and target_lev != current_lev:
            target_dollars = target_lev * pre_eq
            target_shares = target_dollars / open_p
            delta_s = target_shares - curr_shares

            if abs(delta_s) > 1e-8:
                cost = abs(delta_s) * open_p * 0.0005
                fees_total += cost

                if curr_shares != 0.0:
                    closed_s = min(abs(curr_shares), abs(delta_s))
                    pnl = closed_s * (open_p - entry_p) - cost if curr_shares > 0 else closed_s * (entry_p - open_p) - cost
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
        "name": strategy_name,
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

# MODEL 1: Macro Trend Regime (Daily 200 MA + 1h 200 MA)
# When Daily > Daily 200 SMA: Good time -> 5x leverage
# When Daily < Daily 200 SMA: Bad time -> 1x leverage (or 0x)
def lev_macro_regime(ctx):
    if ctx["regime"] != 1:
        return 0.0
    # Good time: Price above Daily 200 MA
    if ctx["prev_close"] > ctx["sma_daily"]:
        return 5.0  # High leverage in macro bull
    else:
        return 1.0  # Low leverage in macro bear/uncertainty

# MODEL 2: Trend Alignment Tiering (Triple Confirmation)
# Tier 1 (Good): Price > EMA 9 > EMA 21 > SMA 200 & Slope > 0 -> 6x leverage
# Tier 2 (Moderate): Price > SMA 200 & Slope > 0 -> 3x leverage
# Tier 3 (Weak/Early): Price > SMA 200 & Slope <= 0 -> 1x leverage
def lev_trend_tiering(ctx):
    if ctx["regime"] != 1:
        return 0.0
    is_strong = (ctx["prev_close"] > ctx["ema9"] > ctx["ema21"] > ctx["sma_1h"]) and (ctx["slope"] > 0.5)
    if is_strong:
        return 6.0
    elif ctx["slope"] > 0:
        return 3.0
    else:
        return 1.0

# MODEL 3: Progressive Pyramiding (Scale into Winners)
# Start trade at 1.5x on breakout
# If profit > 1.5x ATR -> scale to 4x
# If profit > 3.0x ATR -> scale to 8x
def lev_pyramiding(ctx):
    if ctx["regime"] != 1:
        return 0.0
    if not ctx["in_pos"]:
        return 1.5 # base initial leverage
    # If in pos, check unrealized gain in ATRs
    gain_atr = (ctx["prev_close"] - ctx["entry_p"]) / ctx["atr"] if ctx["atr"] > 0 else 0.0
    if gain_atr >= 3.0:
        return 8.0
    elif gain_atr >= 1.5:
        return 4.0
    else:
        return 1.5

# MODEL 4: The Master Hybrid Strategy:
# 1. Macro Regime: Must be above Daily 200 MA for high leverage.
# 2. Pyramiding: Start at 2x. If trend runs (+2x ATR), ramp to 6x, if strong (+4x ATR), ramp to 10x!
# 3. Bad times (Daily < Daily 200 MA): Cap leverage at 1x!
def lev_master_hybrid(ctx):
    if ctx["regime"] != 1:
        return 0.0
    is_macro_bull = ctx["prev_close"] > ctx["sma_daily"]
    if not ctx["in_pos"]:
        return 2.0 if is_macro_bull else 1.0
    gain_atr = (ctx["prev_close"] - ctx["entry_p"]) / ctx["atr"] if ctx["atr"] > 0 else 0.0
    if is_macro_bull:
        if gain_atr >= 4.0:
            return 8.0
        elif gain_atr >= 2.0:
            return 5.0
        else:
            return 2.0
    else:
        return 1.0 # Bad time: keep at 1x max

# Benchmarks
def lev_static_1x(ctx):
    return 1.0 if ctx["regime"] == 1 else 0.0

def lev_static_3x(ctx):
    return 3.0 if ctx["regime"] == 1 else 0.0

def lev_static_5x(ctx):
    return 5.0 if ctx["regime"] == 1 else 0.0

models = [
    ("Static 1x (Baseline)", lev_static_1x),
    ("Static 3x (Baseline)", lev_static_3x),
    ("Static 5x (Baseline)", lev_static_5x),
    ("Dynamic Model 1: Macro Regime (1x Bear / 5x Bull)", lev_macro_regime),
    ("Dynamic Model 2: Trend Alignment (1x / 3x / 6x)", lev_trend_tiering),
    ("Dynamic Model 3: Pyramiding into Winners (1.5x / 4x / 8x)", lev_pyramiding),
    ("Dynamic Model 4: Master Hybrid (Pyramid to 8x in Bull, 1x in Bear)", lev_master_hybrid),
]

print("\nRunning Dynamic Leverage Strategies...")
results = []
for name, fn in models:
    res = run_dynamic_strategy(name, fn, use_sl=True, sl_atr_mult=2.5, band_atr_mult=0.5)
    results.append(res)
    liq_str = " [LIQUIDATED]" if res["is_liq"] else ""
    print(f"{name:55s} | Final: ${res['final_equity']:11,.0f} | CAGR: {res['cagr']*100:5.1f}% | Sharpe: {res['sharpe']:4.2f} | MaxDD: {res['max_dd']*100:5.1f}% | PF: {res['pf']:4.2f}{liq_str}")
