"""Next-bar open execution simulation engine and trade accounting."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from backtest.costs import CostModel
from backtest.volatility import ANNUAL_PERIODS


@dataclass
class TradeRecord:
    """Individual trade execution record."""
    timestamp: int
    datetime_utc: str
    action: str             # 'BUY', 'SELL', 'SHORT', 'COVER'
    price: float
    shares: float
    traded_dollars: float
    fee: float
    slippage: float
    borrow_cost: float
    realized_pnl: float
    return_pct: float
    position_after: float   # shares after trade


@dataclass
class SimulationResult:
    """Complete results from backtest execution."""
    experiment_id: str
    timeframe: str
    initial_capital: float
    cost_model: CostModel
    equity_curve: pd.DataFrame
    trades: List[TradeRecord]
    metrics: Dict[str, float] = field(default_factory=dict)
    monthly_returns: Optional[pd.DataFrame] = None
    yearly_returns: Optional[pd.DataFrame] = None


def run_simulation(
    df: pd.DataFrame,
    experiment_id: str = "exp_default",
    timeframe: str = "1d",
    initial_capital: float = 10_000.0,
    cost_model: Optional[CostModel] = None,
    target_weight_col: str = "target_weight",
    maintenance_margin_rate: float = 0.10,  # 10% maintenance margin
) -> SimulationResult:
    """Execute continuous point-in-time bar-by-bar simulation.

    Execution Rule:
    Signal is determined at candle t close (stored in df[target_weight_col].iloc[t]).
    Execution happens at candle t+1 open price (df['open'].iloc[t+1]).
    Holding returns from t+1 open through t+1 close are credited to bar t+1.
    All costs (commission fees, execution slippage, borrowing financing) are explicitly accounted for.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame with calculated signals and target_weight_col.
    experiment_id : str
        Unique identifier for the run.
    timeframe : str
        Bar timeframe ('1d', '4h', '1h', '15m', '5m').
    initial_capital : float
        Starting account capital in USD.
    cost_model : Optional[CostModel]
        Fee, slippage, and borrow rate model. Defaults to realistic tier if None.
    target_weight_col : str
        Column containing target portfolio weight computed as of bar t close.
    maintenance_margin_rate : float
        Equity / Position Value threshold below which margin call / liquidation triggers.

    Returns
    -------
    SimulationResult
    """
    costs = cost_model or CostModel.from_tier("realistic")
    ann_periods = ANNUAL_PERIODS.get(timeframe.lower(), 365)

    n = len(df)
    if n < 2:
        raise ValueError("DataFrame must contain at least 2 bars for next-bar open execution.")

    timestamps = df["timestamp"].to_numpy()
    datetimes = df["datetime_utc"].to_numpy()
    opens = df["open"].to_numpy(dtype=np.float64)
    highs = df["high"].to_numpy(dtype=np.float64)
    lows = df["low"].to_numpy(dtype=np.float64)
    closes = df["close"].to_numpy(dtype=np.float64)
    target_weights = df[target_weight_col].fillna(0.0).to_numpy(dtype=np.float64)

    # Output arrays
    equity = np.zeros(n, dtype=np.float64)
    benchmark_equity = np.zeros(n, dtype=np.float64)
    cash = np.zeros(n, dtype=np.float64)
    shares = np.zeros(n, dtype=np.float64)
    position_weights = np.zeros(n, dtype=np.float64)
    fees_paid = np.zeros(n, dtype=np.float64)
    slippage_paid = np.zeros(n, dtype=np.float64)
    borrow_paid = np.zeros(n, dtype=np.float64)
    drawdowns = np.zeros(n, dtype=np.float64)

    # Initial state at bar 0
    curr_cash = float(initial_capital)
    curr_shares = 0.0
    equity[0] = curr_cash
    cash[0] = curr_cash
    shares[0] = 0.0
    position_weights[0] = 0.0

    # Benchmark: buy & hold starting from initial capital at bar 0 close
    btc_start_price = closes[0]
    benchmark_equity[0] = initial_capital
    peak_equity = float(initial_capital)
    drawdowns[0] = 0.0

    trades: List[TradeRecord] = []
    # Position cost basis tracking for realized PnL
    cost_basis_price = 0.0

    is_liquidated = False

    for t in range(1, n):
        curr_ts = int(timestamps[t])
        curr_dt = str(datetimes[t])
        open_p = opens[t]
        high_p = highs[t]
        low_p = lows[t]
        close_p = closes[t]

        # Benchmark equity
        benchmark_equity[t] = initial_capital * (close_p / btc_start_price)

        if is_liquidated:
            equity[t] = 0.0
            cash[t] = 0.0
            shares[t] = 0.0
            position_weights[t] = 0.0
            drawdowns[t] = -1.0
            continue

        # 1. Evaluate equity at bar t open before rebalancing
        # Any gap move from close[t-1] to open[t] applies to existing shares
        pre_equity = curr_cash + curr_shares * open_p

        # Check bankruptcy before rebalance
        if pre_equity <= 0.0:
            is_liquidated = True
            equity[t] = 0.0
            cash[t] = 0.0
            shares[t] = 0.0
            position_weights[t] = 0.0
            drawdowns[t] = -1.0
            continue

        # 2. Desired position determined by signal from candle t-1
        desired_weight = target_weights[t - 1]
        desired_dollars = desired_weight * pre_equity
        desired_shares = desired_dollars / open_p if open_p > 0 else 0.0

        # 3. Execution at open_p
        delta_shares = desired_shares - curr_shares
        bar_fee = 0.0
        bar_slip = 0.0
        bar_borrow = 0.0

        if abs(delta_shares) > 1e-8:
            traded_dollars = abs(delta_shares) * open_p
            f, s, _ = costs.calculate_trade_cost(traded_dollars)
            bar_fee += f
            bar_slip += s

            # Realized PnL calculation on reducing/closing positions
            realized_pnl = 0.0
            return_pct = 0.0
            action = "BUY" if delta_shares > 0 else "SELL"

            if curr_shares > 0 and delta_shares < 0:
                # Closing/reducing long
                closed_shares = min(curr_shares, abs(delta_shares))
                realized_pnl = closed_shares * (open_p - cost_basis_price) - (f + s)
                if cost_basis_price > 0:
                    return_pct = (open_p - cost_basis_price) / cost_basis_price
            elif curr_shares < 0 and delta_shares > 0:
                # Closing/reducing short
                closed_shares = min(abs(curr_shares), delta_shares)
                realized_pnl = closed_shares * (cost_basis_price - open_p) - (f + s)
                if cost_basis_price > 0:
                    return_pct = (cost_basis_price - open_p) / cost_basis_price

            # Update cash for trade execution
            curr_cash -= (delta_shares * open_p + f + s)

            # Update cost basis
            if curr_shares == 0.0:
                cost_basis_price = open_p
            elif (curr_shares > 0 and delta_shares > 0) or (curr_shares < 0 and delta_shares < 0):
                # Increasing position: weighted average cost basis
                new_shares = curr_shares + delta_shares
                cost_basis_price = (curr_shares * cost_basis_price + delta_shares * open_p) / new_shares
            elif (curr_shares > 0 and desired_shares <= 0) or (curr_shares < 0 and desired_shares >= 0):
                # Flips direction: cost basis becomes open_p for new direction
                cost_basis_price = open_p

            curr_shares = desired_shares

            trade_rec = TradeRecord(
                timestamp=curr_ts,
                datetime_utc=curr_dt,
                action=action,
                price=open_p,
                shares=delta_shares,
                traded_dollars=traded_dollars,
                fee=f,
                slippage=s,
                borrow_cost=0.0,
                realized_pnl=realized_pnl,
                return_pct=return_pct,
                position_after=curr_shares,
            )
            trades.append(trade_rec)

        # 4. Financing cost over the holding period of bar t
        pos_val_open = abs(curr_shares) * open_p
        is_short = curr_shares < 0
        eq_post_trade = curr_cash + curr_shares * open_p
        bar_borrow = costs.calculate_borrow_cost(pos_val_open, eq_post_trade, ann_periods, is_short=is_short)
        curr_cash -= bar_borrow

        # 5. Intraday margin / liquidation check using High and Low
        if curr_shares > 0:
            worst_equity = curr_cash + curr_shares * low_p
            pos_val_low = curr_shares * low_p
            if worst_equity <= 0 or (pos_val_low > 0 and (worst_equity / pos_val_low) < maintenance_margin_rate):
                # Long position liquidated intraday
                is_liquidated = True
                curr_cash = 0.0
                curr_shares = 0.0
        elif curr_shares < 0:
            worst_equity = curr_cash + curr_shares * high_p
            pos_val_high = abs(curr_shares) * high_p
            if worst_equity <= 0 or (pos_val_high > 0 and (worst_equity / pos_val_high) < maintenance_margin_rate):
                # Short position liquidated intraday
                is_liquidated = True
                curr_cash = 0.0
                curr_shares = 0.0

        # 6. End of bar t close accounting
        if is_liquidated:
            equity[t] = 0.0
            cash[t] = 0.0
            shares[t] = 0.0
            position_weights[t] = 0.0
            drawdowns[t] = -1.0
        else:
            bar_close_eq = curr_cash + curr_shares * close_p
            if bar_close_eq <= 0.0:
                is_liquidated = True
                bar_close_eq = 0.0
                curr_cash = 0.0
                curr_shares = 0.0

            equity[t] = bar_close_eq
            cash[t] = curr_cash
            shares[t] = curr_shares
            position_weights[t] = (curr_shares * close_p / bar_close_eq) if bar_close_eq > 0 else 0.0

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
        "position_weight": position_weights,
        "fee": fees_paid,
        "slippage": slippage_paid,
        "borrow_cost": borrow_paid,
        "drawdown": drawdowns,
    })

    return SimulationResult(
        experiment_id=experiment_id,
        timeframe=timeframe,
        initial_capital=initial_capital,
        cost_model=costs,
        equity_curve=eq_df,
        trades=trades,
    )
