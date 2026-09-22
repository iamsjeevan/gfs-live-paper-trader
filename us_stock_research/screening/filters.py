"""Fundamental quality screening filters.

Applies configurable hard criteria to evaluate if a point-in-time company profile
meets baseline profitability, leverage, and cash generation standards.
"""

from typing import Any, Dict, List, Optional, Tuple


class QualityFilterConfig:
    """Configurable thresholds for fundamental quality screening."""

    def __init__(
        self,
        min_roe: float = 0.12,                  # 12.0%
        min_roic: float = 0.10,                 # 10.0%
        max_debt_equity: float = 0.75,          # 0.75x
        require_positive_ocf: bool = True,
        require_positive_fcf: bool = True,
        require_positive_net_income: bool = True,
        require_positive_revenue: bool = True,
        min_data_completeness: float = 0.50,    # At least 50% of core metrics available
        allow_temporary_fcf_exception: bool = False,
    ):
        self.min_roe = min_roe
        self.min_roic = min_roic
        self.max_debt_equity = max_debt_equity
        self.require_positive_ocf = require_positive_ocf
        self.require_positive_fcf = require_positive_fcf
        self.require_positive_net_income = require_positive_net_income
        self.require_positive_revenue = require_positive_revenue
        self.min_data_completeness = min_data_completeness
        self.allow_temporary_fcf_exception = allow_temporary_fcf_exception

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_roe": self.min_roe,
            "min_roic": self.min_roic,
            "max_debt_equity": self.max_debt_equity,
            "require_positive_ocf": self.require_positive_ocf,
            "require_positive_fcf": self.require_positive_fcf,
            "require_positive_net_income": self.require_positive_net_income,
            "require_positive_revenue": self.require_positive_revenue,
            "min_data_completeness": self.min_data_completeness,
            "allow_temporary_fcf_exception": self.allow_temporary_fcf_exception,
        }


def evaluate_quality_filters(
    fundamentals: Dict[str, Any],
    config: Optional[QualityFilterConfig] = None,
) -> Tuple[bool, List[str]]:
    """Evaluate whether a company passes all fundamental quality filters.

    Returns:
        (passes_all: bool, failure_reasons: List[str])
    """
    cfg = config or QualityFilterConfig()
    failures: List[str] = []

    # 1. Minimum Data Completeness
    comp_score = fundamentals.get("data_completeness_score", 0.0) or 0.0
    if comp_score < cfg.min_data_completeness:
        failures.append(f"Insufficient data completeness ({comp_score:.1%} < {cfg.min_data_completeness:.1%})")

    # 2. Positive Revenue
    rev = fundamentals.get("revenue") or fundamentals.get("sales")
    if cfg.require_positive_revenue:
        if rev is None:
            failures.append("Missing revenue observation")
        elif rev <= 0:
            failures.append(f"Non-positive revenue (${rev/1e6:.1f}M <= $0)")

    # 3. Positive Net Income
    ni = fundamentals.get("net_income")
    pe = fundamentals.get("pe")
    roe = fundamentals.get("roe")
    if cfg.require_positive_net_income:
        if ni is not None and ni <= 0:
            failures.append(f"Non-positive net income (${ni/1e6:.2f}M <= $0)")
        elif roe is not None and roe <= 0:
            failures.append(f"Non-positive net income (ROE {roe:.1%})")
        elif pe is not None and pe <= 0:
            failures.append("Negative earnings")
        elif ni is None and roe is None:
            failures.append("Missing net income observation")

    # 4. ROE Threshold (>= 12%)
    if roe is not None:
        if roe < cfg.min_roe:
            failures.append(f"ROE {roe:.1%} below minimum threshold {cfg.min_roe:.1%}")
    else:
        failures.append("Missing ROE observation")

    # 5. ROIC Threshold (>= 10%)
    roic = fundamentals.get("roic")
    if roic is not None:
        if roic < cfg.min_roic:
            failures.append(f"ROIC {roic:.1%} below minimum threshold {cfg.min_roic:.1%}")
    else:
        # Fallback to ROE if capital structure has zero debt and ROIC is uncomputed
        de = fundamentals.get("debt_equity")
        if de == 0.0 and roe is not None and roe >= cfg.min_roic:
            pass  # Zero debt means ROE ≈ ROIC
        else:
            failures.append("Missing or unconfirmed ROIC observation")

    # 6. Debt / Equity Threshold (<= 0.75)
    de = fundamentals.get("debt_equity")
    if de is not None:
        if de > cfg.max_debt_equity:
            failures.append(f"Debt/Equity {de:.2f} exceeds maximum threshold {cfg.max_debt_equity:.2f}")
    # Note: if Debt/Equity is None because company has 0 debt, it passes.

    # 7. Operating Cash Flow (> 0)
    ocf = fundamentals.get("operating_cash_flow")
    if cfg.require_positive_ocf:
        if ocf is None:
            failures.append("Missing operating cash flow observation")
        elif ocf <= 0:
            failures.append(f"Operating cash flow is non-positive (${ocf/1e6:.2f}M <= $0)")

    # 8. Free Cash Flow (> 0, strict zero-exception)
    fcf = fundamentals.get("free_cash_flow")
    if cfg.require_positive_fcf:
        if fcf is None:
            failures.append("Missing free cash flow observation")
        elif fcf <= 0:
            if cfg.allow_temporary_fcf_exception and ocf is not None and ocf > 0:
                pass
            else:
                failures.append(f"Free cash flow is negative (${fcf/1e6:.2f}M <= $0)")


    passes = len(failures) == 0
    return passes, failures
