"""Fundamental metric calculation functions.

All calculations strictly enforce point-in-time rules and prevent look-ahead bias.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np


def compute_cagr(start_val: Optional[float], end_val: Optional[float], periods: int) -> Optional[float]:
    """Compute Compound Annual Growth Rate (CAGR) over `periods` years.

    Returns None if either start_val or end_val is non-positive or missing.
    """
    if start_val is None or end_val is None or periods <= 0:
        return None
    if start_val <= 0 or end_val <= 0:
        # Negative bases cannot compute a standard CAGR
        return None
    try:
        cagr = (end_val / start_val) ** (1.0 / periods) - 1.0
        return float(cagr)
    except (ZeroDivisionError, OverflowError, ValueError):
        return None


def compute_yoy_growth(prev_val: Optional[float], curr_val: Optional[float]) -> Optional[float]:
    """Compute Year-over-Year (YoY) growth percentage."""
    if prev_val is None or curr_val is None or prev_val == 0:
        return None
    if prev_val < 0:
        # If base is negative, conventional percentage is distorted
        return float((curr_val - prev_val) / abs(prev_val))
    return float((curr_val - prev_val) / prev_val)


def compute_growth_consistency(growth_rates: List[Optional[float]]) -> float:
    """Calculate growth consistency score in [0.0, 1.0].

    Rewards steady positive growth (e.g. 18%, 20%, 22%) and penalizes
    erratic volatility or alternating signs (e.g. 80%, -40%, 90%).
    """
    valid = [g for g in growth_rates if g is not None]
    if not valid:
        return 0.5
    if len(valid) == 1:
        return 0.7 if valid[0] > 0 else 0.3

    # Fraction of positive growth periods
    positive_pct = sum(1 for g in valid if g > 0) / len(valid)

    # Volatility penalty based on standard deviation of growth rates
    std_dev = float(np.std(valid))
    # std_dev of 0.10 (10% spread) gives factor near 0.9; std_dev of 0.80 gives factor near 0.2
    vol_penalty = 1.0 / (1.0 + std_dev * 2.5)

    consistency = 0.5 * positive_pct + 0.5 * vol_penalty
    return float(np.clip(consistency, 0.0, 1.0))


def compute_roic(
    operating_income: Optional[float],
    equity: Optional[float],
    debt: Optional[float],
    cash: Optional[float],
    tax_rate: float = 0.21,
) -> Optional[float]:
    """Compute Return on Invested Capital (ROIC).

    ROIC = NOPAT / Invested Capital
    NOPAT = Operating Income × (1 - tax_rate)
    Invested Capital = Total Debt + Stockholders Equity - Cash
    """
    if operating_income is None or equity is None:
        return None

    nopat = operating_income * (1.0 - tax_rate)
    tot_debt = debt or 0.0
    tot_cash = cash or 0.0
    invested_capital = tot_debt + equity - tot_cash

    if invested_capital <= 0:
        return None

    return float(nopat / invested_capital)


def compute_enterprise_value(
    market_cap: float,
    debt: Optional[float],
    cash: Optional[float],
) -> float:
    """Compute Enterprise Value (EV).

    EV = Market Cap + Total Debt - Cash & Equivalents
    """
    tot_debt = debt or 0.0
    tot_cash = cash or 0.0
    return max(0.0, market_cap + tot_debt - tot_cash)
