"""Portfolio attribution, concentration analysis, and robustness tools."""

from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from .engine import BacktestEngine


def compute_holding_attribution(
    attribution_df: pd.DataFrame,
    initial_capital: float = 10_000.0,
) -> pd.DataFrame:
    """Format and enrich holding attribution records."""
    df = attribution_df.copy()
    if "total_ending_value" in df.columns and "initial_allocation" in df.columns:
        df["profit_loss"] = df["total_ending_value"] - df["initial_allocation"]
        df["contribution_to_portfolio_return"] = df["profit_loss"] / initial_capital
    return df


def compute_concentration_metrics(attribution_df: pd.DataFrame) -> Dict[str, float]:
    """Calculate concentration metrics across portfolio holdings."""
    df = attribution_df.sort_values("total_ending_value", ascending=False).copy()
    total_port_ending = df["total_ending_value"].sum()
    total_port_profit = (df["total_ending_value"] - df["initial_allocation"]).sum()

    # Share of ending portfolio value
    top1_val_pct = float(df.iloc[0]["total_ending_value"] / total_port_ending) if total_port_ending > 0 else 0.0
    top3_val_pct = float(df.iloc[:3]["total_ending_value"].sum() / total_port_ending) if total_port_ending > 0 else 0.0
    top5_val_pct = float(df.iloc[:5]["total_ending_value"].sum() / total_port_ending) if total_port_ending > 0 else 0.0

    # Share of total portfolio profit (gain contribution)
    if total_port_profit > 0:
        top1_profit_pct = float((df.iloc[0]["total_ending_value"] - df.iloc[0]["initial_allocation"]) / total_port_profit)
        top3_profit_pct = float((df.iloc[:3]["total_ending_value"] - df.iloc[:3]["initial_allocation"]).sum() / total_port_profit)
        top5_profit_pct = float((df.iloc[:5]["total_ending_value"] - df.iloc[:5]["initial_allocation"]).sum() / total_port_profit)
    else:
        top1_profit_pct = top3_profit_pct = top5_profit_pct = 0.0

    # HHI (Herfindahl-Hirschman Index) of ending weights (0 to 10,000)
    weights = df["total_ending_value"] / total_port_ending
    hhi = float((weights ** 2).sum() * 10_000)

    return {
        "top1_ticker": df.iloc[0]["ticker"],
        "top1_value_share_pct": top1_val_pct,
        "top3_value_share_pct": top3_val_pct,
        "top5_value_share_pct": top5_val_pct,
        "top1_profit_share_pct": top1_profit_pct,
        "top3_profit_share_pct": top3_profit_pct,
        "top5_profit_share_pct": top5_profit_pct,
        "ending_hhi": hhi,
    }


def compute_leave_one_out(
    engine: BacktestEngine,
    strategy_name: str,
    holdings: List[Dict[str, Any]],
    exclude_ticker: str = "IRMD",
    reinvest_dividends: bool = False,
) -> Dict[str, Any]:
    """Simulate the portfolio without the excluded holding to measure fragility.

    Allocates $10,000 equally across the remaining 9 holdings ($1,111.11 each).
    """
    remaining = [h for h in holdings if h["ticker"].upper() != exclude_ticker.upper()]
    if not remaining:
        raise ValueError("Cannot exclude all holdings.")

    res = engine.run_backtest(
        f"{strategy_name} (ex-{exclude_ticker})",
        remaining,
        reinvest_dividends=reinvest_dividends,
    )
    return res


def compute_annual_returns_table(daily_df: pd.DataFrame, strategy_name: str) -> pd.DataFrame:
    """Generate calendar year-by-year valuation and return breakdown."""
    df = daily_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year

    annual_rows = []
    # Base entry value at 2016-12-30
    prev_val = df.iloc[0]["total_value"]

    years = sorted(df["year"].unique())
    cum_divs_prev = 0.0

    for yr in years:
        sub = df[df["year"] == yr]
        end_row = sub.iloc[-1]
        end_val = float(end_row["total_value"])
        end_eq = float(end_row["equity_value"])
        end_cash = float(end_row["cash_balance"])
        cum_divs = float(end_row["dividends_received_cumulative"])
        annual_divs = cum_divs - cum_divs_prev
        cum_divs_prev = cum_divs

        annual_ret = (end_val - prev_val) / prev_val if prev_val > 0 else 0.0
        cum_ret = (end_val - df.iloc[0]["total_value"]) / df.iloc[0]["total_value"]

        annual_rows.append({
            "year": yr,
            "strategy": strategy_name,
            "as_of_date": end_row["date"].strftime("%Y-%m-%d"),
            "starting_value": prev_val,
            "ending_value": end_val,
            "equity_value": end_eq,
            "cash_balance": end_cash,
            "annual_dividends_paid": annual_divs,
            "annual_return": annual_ret,
            "cumulative_return": cum_ret,
        })
        prev_val = end_val

    return pd.DataFrame(annual_rows)
