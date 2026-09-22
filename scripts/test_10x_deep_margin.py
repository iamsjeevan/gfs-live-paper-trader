"""Simulate Normal MA 200 with 10x leverage assuming deep margin buffer (no liquidation)."""

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

df = load_candles("1h")
n = len(df)
closes = df["close"].to_numpy(dtype=np.float64)
highs = df["high"].to_numpy(dtype=np.float64)
lows = df["low"].to_numpy(dtype=np.float64)
opens = df["open"].to_numpy(dtype=np.float64)
dts = df["datetime_utc"].to_numpy()
timestamps = df["timestamp"].to_numpy()

sma200 = pd.Series(closes).rolling(200).mean().to_numpy()

def run_normal_ma200_10x(
    mode="long_only",
    leverage=10.0,
    can_liquidate=False,
    max_margin_drawdown_pct=0.50, # 50% real btc drop tolerance
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

    raw_signals = np.zeros(n)
    for i in range(200, n):
        if closes[i] > sma200[i]:
            raw_signals[i] = 1.0
        elif closes[i] < sma200[i]:
            raw_signals[i] = -1.0 if mode == "long_short" else 0.0

    trade_pnls = []
    trade_records = []
    cost_basis_p = 0.0

    for t in range(201, n):
        open_p = opens[t]
        high_p = highs[t]
        low_p = lows[t]
        close_p = closes[t]
        curr_dt = dts[t]

        if is_liq:
            equity[t] = 0.0
            continue

        pre_eq = curr_cash + curr_shares * open_p
        if pre_eq <= 0.0 and can_liquidate:
            is_liq = True
            liq_dt = curr_dt
            liq_price = open_p
            equity[t] = 0.0
            continue

        sig_prev = raw_signals[t - 1]
        sig_prev_prev = raw_signals[t - 2]
        sig_changed = (sig_prev != sig_prev_prev)

        bar_fee = 0.0

        # Crossover rebalance
        if sig_changed:
            target_dollars = sig_prev * leverage * max(pre_eq, 100.0) # floor to maintain trading if equity dips
            target_shares = target_dollars / open_p
            delta_s = target_shares - curr_shares

            if abs(delta_s) > 1e-8:
                cost = abs(delta_s) * open_p * 0.0005 # 5 bps fee + slippage
                bar_fee += cost

                if curr_shares != 0.0:
                    if curr_shares > 0:
                        closed_s = min(curr_shares, abs(delta_s))
                        pnl = closed_s * (open_p - cost_basis_p) - cost
                    else:
                        closed_s = min(abs(curr_shares), delta_s)
                        pnl = closed_s * (cost_basis_p - open_p) - cost
                    trade_pnls.append(pnl)

                curr_cash -= (delta_s * open_p + cost)
                curr_shares = target_shares
                cost_basis_p = open_p
                if target_shares != 0.0:
                    trade_records.append({"dt": curr_dt, "price": open_p, "shares": delta_s})

        # Funding fee (every 8h: 00:00, 08:00, 16:00 UTC)
        hour = int(curr_dt[11:13])
        minute = int(curr_dt[14:16])
        bar_funding = 0.0
        if hour in (0, 8, 16) and minute == 0 and curr_shares != 0.0:
            bar_funding = -curr_shares * open_p * 0.0001
            curr_cash += bar_funding

        # Liquidation check if enabled (50% real btc drop tolerance)
        if can_liquidate:
            if curr_shares > 0:
                drop_pct = (cost_basis_p - low_p) / cost_basis_p
                if drop_pct >= max_margin_drawdown_pct:
                    is_liq = True
                    liq_dt = curr_dt
                    liq_price = low_p
                    curr_cash = 0.0
                    curr_shares = 0.0
            elif curr_shares < 0:
                rise_pct = (high_p - cost_basis_p) / cost_basis_p
                if rise_pct >= max_margin_drawdown_pct:
                    is_liq = True
                    liq_dt = curr_dt
                    liq_price = high_p
                    curr_cash = 0.0
                    curr_shares = 0.0

        bar_eq = curr_cash + curr_shares * close_p
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

    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p < 0]
    win_rate = len(wins) / len(trade_pnls) if trade_pnls else 0.0
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else (999.0 if wins else 0.0)

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
        "max_dd": max_dd,
        "trades": len(trade_records),
        "win_rate": win_rate,
        "pf": pf,
        "is_liquidated": is_liq,
        "liq_dt": liq_dt,
        "best_year": best_year,
        "worst_year": worst_year,
        "yearly_returns": yearly_returns,
        "equity_series": eq_series,
        "total_fees": float(fees_paid.sum()),
        "total_funding": float(funding_paid.sum()),
    }

print("Running Normal 200 MA at 10x with NO LIQUIDATION (50% real btc drop buffer)...")
r_lo = run_normal_ma200_10x(mode="long_only", leverage=10.0, can_liquidate=False)
r_ls = run_normal_ma200_10x(mode="long_short", leverage=10.0, can_liquidate=False)

print(f"\n--- NORMAL 200 MA (LONG-ONLY, 10x LEVERAGE, NO LIQUIDATION) ---")
print(f"Final Equity:     ${r_lo['final_equity']:,.2f}")
print(f"CAGR:             {r_lo['cagr']*100:.2f}%")
print(f"Sharpe Ratio:     {r_lo['sharpe']:.2f}")
print(f"Max Drawdown:     {r_lo['max_dd']*100:.2f}%")
print(f"Total Trades:     {r_lo['trades']:,}")
print(f"Win Rate:         {r_lo['win_rate']*100:.2f}%")
print(f"Profit Factor:    {r_lo['pf']:.2f}")
print(f"Best Year:        {r_lo['best_year'][0]}: {r_lo['best_year'][1]*100:+.2f}%")
print(f"Worst Year:       {r_lo['worst_year'][0]}: {r_lo['worst_year'][1]*100:+.2f}%")
print(f"Total Fees Paid:  ${r_lo['total_fees']:,.2f}")
print(f"Total Funding:    ${r_lo['total_funding']:,.2f}")

print(f"\n--- NORMAL 200 MA (LONG-SHORT, 10x LEVERAGE, NO LIQUIDATION) ---")
print(f"Final Equity:     ${r_ls['final_equity']:,.2f}")
print(f"CAGR:             {r_ls['cagr']*100:.2f}%")
print(f"Sharpe Ratio:     {r_ls['sharpe']:.2f}")
print(f"Max Drawdown:     {r_ls['max_dd']*100:.2f}%")
print(f"Total Trades:     {r_ls['trades']:,}")
print(f"Win Rate:         {r_ls['win_rate']*100:.2f}%")
print(f"Profit Factor:    {r_ls['pf']:.2f}")
print(f"Best Year:        {r_ls['best_year'][0]}: {r_ls['best_year'][1]*100:+.2f}%")
print(f"Worst Year:       {r_ls['worst_year'][0]}: {r_ls['worst_year'][1]*100:+.2f}%")

print("\nYearly Returns for Normal 200 MA Long-Only 10x:")
for yr, val in r_lo['yearly_returns'].items():
    print(f"  {yr.year}: {val*100:+8.2f}%")
