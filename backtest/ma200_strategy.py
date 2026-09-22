"""1-Hour 200 Moving Average (MA 200) Trend Strategy with Leverage 1x to 10x."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from backtest.costs import CostModel
from backtest.data import load_candles
from backtest.metrics import calculate_period_returns

BASE_DIR = Path(__file__).resolve().parent.parent
FIGURES_DIR = BASE_DIR / "reports" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class MA200Result:
    """Simulation results for a single MA200 configuration."""
    leverage: float
    mode: str                  # 'long_short' or 'long_only'
    ma_type: str               # 'SMA' or 'EMA'
    cost_tier: str             # 'realistic' or 'zero'
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    turnover: float
    total_fees: float
    total_slippage: float
    total_borrow: float
    total_costs: float
    final_equity: float
    is_liquidated: bool
    liquidation_datetime: Optional[str]
    liquidation_price: Optional[float]
    best_year: Tuple[int, float]
    worst_year: Tuple[int, float]
    yearly_returns: pd.DataFrame
    equity_curve: pd.DataFrame


def run_ma200_simulation(
    df: pd.DataFrame,
    leverage: float = 1.0,
    mode: str = "long_short",
    ma_type: str = "SMA",
    ma_window: int = 200,
    cost_model: Optional[CostModel] = None,
    cost_tier_name: str = "realistic",
    initial_capital: float = 10_000.0,
    maintenance_margin_rate: float = 0.01,  # 1% maintenance margin
) -> MA200Result:
    """Simulate 200 MA crossover strategy on 1h candles with next-bar open execution.

    Trading Mechanics:
    - Signal is evaluated at bar t close.
    - If Close > MA 200: Target Signal = +1.0
    - If Close < MA 200: Target Signal = -1.0 (or 0.0 in long-only)
    - Rebalancing occurs at bar t+1 OPEN only on signal changes (crossovers).
    - Position is held between crossovers without continuous rebalancing noise.
    - Full trade accounting: fee, slippage, financing cost, and intraday liquidation.
    """
    costs = cost_model or CostModel.from_tier(cost_tier_name)
    n = len(df)
    opens = df["open"].to_numpy(dtype=np.float64)
    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    closes = df["close"].to_numpy(dtype=np.float64)
    timestamps = df["timestamp"].to_numpy()
    datetimes = df["datetime_utc"].to_numpy()

    # Calculate Moving Average
    close_series = pd.Series(closes)
    if ma_type.upper() == "EMA":
        ma_vals = close_series.ewm(span=ma_window, adjust=False).mean().to_numpy()
    else:
        ma_vals = close_series.rolling(ma_window).mean().to_numpy()

    # Directional signals
    raw_signals = np.zeros(n, dtype=np.float64)
    for i in range(ma_window, n):
        if closes[i] > ma_vals[i]:
            raw_signals[i] = 1.0
        elif closes[i] < ma_vals[i]:
            raw_signals[i] = -1.0 if mode == "long_short" else 0.0

    # Output arrays
    equity = np.zeros(n, dtype=np.float64)
    cash = np.zeros(n, dtype=np.float64)
    shares = np.zeros(n, dtype=np.float64)
    fees_paid = np.zeros(n, dtype=np.float64)
    slippage_paid = np.zeros(n, dtype=np.float64)
    borrow_paid = np.zeros(n, dtype=np.float64)
    drawdowns = np.zeros(n, dtype=np.float64)
    benchmark_equity = np.zeros(n, dtype=np.float64)

    curr_cash = float(initial_capital)
    curr_shares = 0.0
    equity[0] = curr_cash
    cash[0] = curr_cash
    peak_equity = curr_cash

    btc_start_price = closes[0]
    benchmark_equity[0] = initial_capital

    is_liquidated = False
    liq_dt = None
    liq_price = None

    ann_periods = 365 * 24  # 8,760 hours per year
    trade_pnls = []
    trade_returns = []
    trade_records = []
    cost_basis_price = 0.0

    for t in range(1, n):
        curr_ts = int(timestamps[t])
        curr_dt = str(datetimes[t])
        open_p = opens[t]
        high_p = highs[t]
        low_p = lows[t]
        close_p = closes[t]

        benchmark_equity[t] = initial_capital * (close_p / btc_start_price)

        if is_liquidated:
            equity[t] = 0.0
            drawdowns[t] = -1.0
            continue

        # Prior holding equity at open
        pre_equity = curr_cash + curr_shares * open_p
        if pre_equity <= 0.0:
            is_liquidated = True
            liq_dt = curr_dt
            liq_price = open_p
            equity[t] = 0.0
            drawdowns[t] = -1.0
            continue

        # Signal from bar t-1 close
        sig_prev = raw_signals[t - 1]
        sig_prev_prev = raw_signals[t - 2] if t >= 2 else 0.0
        sig_changed = (t == ma_window) or (sig_prev != sig_prev_prev)

        bar_fee = 0.0
        bar_slip = 0.0

        if sig_changed and sig_prev != 0.0:
            target_dollars = sig_prev * leverage * pre_equity
            target_shares = target_dollars / open_p
            delta_shares = target_shares - curr_shares

            if abs(delta_shares) > 1e-8:
                traded_dollars = abs(delta_shares) * open_p
                f, s, _ = costs.calculate_trade_cost(traded_dollars)
                bar_fee += f
                bar_slip += s

                # Track PnL on closing existing position
                if curr_shares != 0.0:
                    realized_pnl = 0.0
                    ret_pct = 0.0
                    if curr_shares > 0 and delta_shares < 0:
                        closed_s = min(curr_shares, abs(delta_shares))
                        realized_pnl = closed_s * (open_p - cost_basis_price) - (f + s)
                        ret_pct = (open_p - cost_basis_price) / cost_basis_price if cost_basis_price > 0 else 0.0
                    elif curr_shares < 0 and delta_shares > 0:
                        closed_s = min(abs(curr_shares), delta_shares)
                        realized_pnl = closed_s * (cost_basis_price - open_p) - (f + s)
                        ret_pct = (cost_basis_price - open_p) / cost_basis_price if cost_basis_price > 0 else 0.0
                    trade_pnls.append(realized_pnl)
                    trade_returns.append(ret_pct)

                curr_cash -= (delta_shares * open_p + f + s)
                cost_basis_price = open_p
                curr_shares = target_shares
                trade_records.append({"dt": curr_dt, "price": open_p, "shares": delta_shares, "dollars": traded_dollars})

        elif sig_changed and sig_prev == 0.0:
            # Exit position to cash (long-only exit)
            if abs(curr_shares) > 1e-8:
                traded_dollars = abs(curr_shares) * open_p
                f, s, _ = costs.calculate_trade_cost(traded_dollars)
                bar_fee += f
                bar_slip += s

                if curr_shares > 0:
                    realized_pnl = curr_shares * (open_p - cost_basis_price) - (f + s)
                    ret_pct = (open_p - cost_basis_price) / cost_basis_price if cost_basis_price > 0 else 0.0
                    trade_pnls.append(realized_pnl)
                    trade_returns.append(ret_pct)

                curr_cash += (curr_shares * open_p - (f + s))
                curr_shares = 0.0
                trade_records.append({"dt": curr_dt, "price": open_p, "shares": -curr_shares, "dollars": traded_dollars})

        # Financing cost over 1 hour
        pos_val_open = abs(curr_shares) * open_p
        is_short = curr_shares < 0
        eq_post_trade = curr_cash + curr_shares * open_p
        bar_borrow = costs.calculate_borrow_cost(pos_val_open, eq_post_trade, ann_periods, is_short=is_short)
        curr_cash -= bar_borrow

        # Intraday Margin / Liquidation Check using High & Low
        if curr_shares > 0:
            worst_eq = curr_cash + curr_shares * low_p
            worst_pos = curr_shares * low_p
            if worst_eq <= 0.0 or (worst_pos > 0 and (worst_eq / worst_pos) < maintenance_margin_rate):
                is_liquidated = True
                liq_dt = curr_dt
                liq_price = low_p
                curr_cash = 0.0
                curr_shares = 0.0
        elif curr_shares < 0:
            worst_eq = curr_cash + curr_shares * high_p
            worst_pos = abs(curr_shares) * high_p
            if worst_eq <= 0.0 or (worst_pos > 0 and (worst_eq / worst_pos) < maintenance_margin_rate):
                is_liquidated = True
                liq_dt = curr_dt
                liq_price = high_p
                curr_cash = 0.0
                curr_shares = 0.0

        # Bar Close Accounting
        if is_liquidated:
            equity[t] = 0.0
            drawdowns[t] = -1.0
        else:
            bar_close_eq = curr_cash + curr_shares * close_p
            if bar_close_eq <= 0.0:
                is_liquidated = True
                liq_dt = curr_dt
                liq_price = close_p
                bar_close_eq = 0.0
                curr_cash = 0.0
                curr_shares = 0.0

            equity[t] = bar_close_eq
            cash[t] = curr_cash
            shares[t] = curr_shares
            peak_equity = max(peak_equity, bar_close_eq)
            drawdowns[t] = (bar_close_eq - peak_equity) / peak_equity if peak_equity > 0 else -1.0

        fees_paid[t] = bar_fee
        slippage_paid[t] = bar_slip
        borrow_paid[t] = bar_borrow

    eq_df = pd.DataFrame({
        "timestamp": timestamps,
        "datetime_utc": datetimes,
        "equity": equity,
        "benchmark_equity": benchmark_equity,
        "cash": cash,
        "shares": shares,
        "fee": fees_paid,
        "slippage": slippage_paid,
        "borrow_cost": borrow_paid,
        "drawdown": drawdowns,
    })

    # Summary Statistics
    final_eq = float(equity[-1])
    days_elapsed = (pd.to_datetime(datetimes[-1], utc=True) - pd.to_datetime(datetimes[0], utc=True)).total_seconds() / 86400.0
    years_elapsed = days_elapsed / 365.25
    cagr = (final_eq / initial_capital) ** (1.0 / years_elapsed) - 1.0 if final_eq > 0 else -1.0

    pct_returns = pd.Series(equity).pct_change().dropna().replace([np.inf, -np.inf], 0.0)
    vol = pct_returns.std(ddof=1) * np.sqrt(ann_periods) if len(pct_returns) > 1 else 0.0
    sharpe = (pct_returns.mean() * ann_periods / vol) if vol > 1e-8 else 0.0

    downside = pct_returns[pct_returns < 0.0]
    downside_std = np.sqrt(np.mean(downside ** 2)) * np.sqrt(ann_periods) if len(downside) > 0 else 0.0
    sortino = (pct_returns.mean() * ann_periods / downside_std) if downside_std > 1e-8 else 0.0

    max_dd = float(drawdowns.min())
    calmar = (cagr / abs(max_dd)) if abs(max_dd) > 1e-6 else 0.0

    total_fees = float(fees_paid.sum())
    total_slippage = float(slippage_paid.sum())
    total_borrow = float(borrow_paid.sum())
    total_costs = total_fees + total_slippage + total_borrow

    total_traded_dollars = sum(t["dollars"] for t in trade_records)
    avg_eq = float(np.mean(equity[equity > 0])) if np.any(equity > 0) else initial_capital
    turnover = (total_traded_dollars / avg_eq / years_elapsed) if avg_eq > 0 else 0.0

    winning_trades = [p for p in trade_pnls if p > 0]
    losing_trades = [p for p in trade_pnls if p < 0]
    win_rate = (len(winning_trades) / len(trade_pnls)) if trade_pnls else 0.0
    profit_factor = (sum(winning_trades) / abs(sum(losing_trades))) if losing_trades and sum(losing_trades) != 0 else (999.0 if winning_trades else 0.0)

    # Periodic Yearly Returns
    _, yearly_df = calculate_period_returns(eq_df)
    
    # Identify Best & Worst Year
    if not yearly_df.empty:
        best_row = yearly_df.loc[yearly_df["return_pct"].idxmax()]
        worst_row = yearly_df.loc[yearly_df["return_pct"].idxmin()]
        best_year = (int(best_row["year"]), float(best_row["return_pct"]))
        worst_year = (int(worst_row["year"]), float(worst_row["return_pct"]))
    else:
        best_year = (2017, 0.0)
        worst_year = (2017, 0.0)

    return MA200Result(
        leverage=leverage,
        mode=mode,
        ma_type=ma_type,
        cost_tier=cost_tier_name,
        cagr=cagr,
        annualized_volatility=vol,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=max_dd,
        calmar_ratio=calmar,
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_trades=len(trade_records),
        turnover=turnover,
        total_fees=total_fees,
        total_slippage=total_slippage,
        total_borrow=total_borrow,
        total_costs=total_costs,
        final_equity=final_eq,
        is_liquidated=is_liquidated,
        liquidation_datetime=liq_dt,
        liquidation_price=liq_price,
        best_year=best_year,
        worst_year=worst_year,
        yearly_returns=yearly_df,
        equity_curve=eq_df,
    )


def run_ma200_leverage_sweep(
    df_1h: Optional[pd.DataFrame] = None,
    mode: str = "long_short",
    ma_type: str = "SMA",
    cost_tier: str = "realistic",
) -> List[MA200Result]:
    """Execute complete leverage sweep from 1x to 10x."""
    df = df_1h if df_1h is not None else load_candles("1h")
    results = []
    for lev in range(1, 11):
        res = run_ma200_simulation(
            df,
            leverage=float(lev),
            mode=mode,
            ma_type=ma_type,
            cost_tier_name=cost_tier,
        )
        results.append(res)
    return results


def plot_ma200_leverage_curves(results: List[MA200Result], save_name: str = "ma200_leverage_equity_curves.png"):
    """Plot cumulative equity curves across 1x to 10x leverage."""
    path = FIGURES_DIR / save_name
    fig, ax = plt.subplots(figsize=(12, 6))

    cmap = plt.get_cmap("turbo", len(results))
    first_res = results[0]

    for i, r in enumerate(results):
        eq = r.equity_curve
        dt = pd.to_datetime(eq["timestamp"], unit="ms", utc=True)
        # downsample for smooth plotting
        step = max(len(eq) // 2000, 1)
        lbl = f"{int(r.leverage)}x (${r.final_equity:,.0f})"
        if r.is_liquidated:
            lbl += f" [LIQ {r.liquidation_datetime[:7]}]"
        ax.plot(dt.iloc[::step], eq["equity"].iloc[::step], label=lbl, color=cmap(i), lw=1.5)

    # Benchmark
    dt_bench = pd.to_datetime(first_res.equity_curve["timestamp"], unit="ms", utc=True)
    step = max(len(dt_bench) // 2000, 1)
    ax.plot(dt_bench.iloc[::step], first_res.equity_curve["benchmark_equity"].iloc[::step],
            label="BTC Buy & Hold", color="black", lw=1.5, ls="--", alpha=0.7)

    ax.set_yscale("log")
    ax.set_ylabel("Portfolio Value ($ Log Scale)", fontsize=11)
    ax.set_xlabel("Date", fontsize=11)
    mode_str = "Long-Short" if first_res.mode == "long_short" else "Long-Only"
    ax.set_title(f"1-Hour 200 {first_res.ma_type} Trend Strategy: Leverage 1x to 10x ({mode_str})", fontsize=13, fontweight="bold")
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=True, fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    plt.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_best_worst_years(results: List[MA200Result], save_name: str = "ma200_best_worst_years.png"):
    """Plot bar chart comparing best and worst performing years across leverage levels."""
    path = FIGURES_DIR / save_name
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    levs = [int(r.leverage) for r in results]
    best_rets = [r.best_year[1] * 100 for r in results]
    best_labels = [f"L{r.leverage:.0f}\n({r.best_year[0]})" for r in results]

    worst_rets = [r.worst_year[1] * 100 for r in results]
    worst_labels = [f"L{r.leverage:.0f}\n({r.worst_year[0]})" for r in results]

    ax1.bar(levs, best_rets, color="#2ca02c", edgecolor="#333333")
    ax1.set_ylabel("Return in Best Year (%)", fontsize=11)
    ax1.set_title("Best Performing Year by Leverage Tier", fontsize=12, fontweight="bold")
    ax1.set_xticks(levs)
    ax1.set_xticklabels(best_labels, fontsize=9)
    ax1.grid(True, alpha=0.3)

    ax2.bar(levs, worst_rets, color="#d62728", edgecolor="#333333")
    ax2.set_ylabel("Return in Worst Year (%)", fontsize=11)
    ax2.set_title("Worst Performing Year by Leverage Tier", fontsize=12, fontweight="bold")
    ax2.set_xticks(levs)
    ax2.set_xticklabels(worst_labels, fontsize=9)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
