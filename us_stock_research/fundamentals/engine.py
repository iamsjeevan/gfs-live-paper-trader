"""Point-in-Time Fundamental Analysis Engine.

Enforces:
1. Strict Point-in-Time Cutoff: filing_date <= screen_date (never use 2017+ filings).
2. True historical calculations for profitability, growth, leverage, cash generation, and valuation.
3. Quantitative Moat Proxy calculation based on observable financial persistence.
4. Comprehensive data completeness scoring and accounting flags.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from config.settings import DEFAULT_SCREEN_DATE, setup_logger
from data_sources.sec.companyfacts import fetch_company_facts
from data_sources.sec.parser import parse_company_facts
from .metrics import (
    compute_cagr,
    compute_enterprise_value,
    compute_growth_consistency,
    compute_roic,
    compute_yoy_growth,
)

logger = setup_logger("fundamental_engine", "screening.log")


class PointInTimeFundamentalsEngine:
    """Computes comprehensive fundamental metrics strictly as of screen_date."""

    def __init__(self, screen_date: str = DEFAULT_SCREEN_DATE):
        self.screen_date = screen_date

    def compute_company_fundamentals(
        self,
        cik: int,
        ticker: Optional[str] = None,
        market_cap_2016: Optional[float] = None,
        facts_json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Compute point-in-time fundamental metrics for a single CIK.

        Args:
            cik: Central Index Key.
            ticker: Stock ticker symbol.
            market_cap_2016: Confirmed 2016 point-in-time market cap in USD.
            facts_json: Optional pre-loaded SEC companyfacts JSON.

        Returns:
            Dict containing complete fundamental profile, scores, and data quality flags.
        """
        if facts_json is None:
            facts_json = fetch_company_facts(cik, refresh=False)

        # Initialize result dictionary with default Nones
        result: Dict[str, Any] = {
            "cik": cik,
            "ticker": ticker,
            "screen_date": self.screen_date,
            "market_cap_2016": market_cap_2016,
            "filing_date": None,
            "period_end": None,
            "form_type": None,
            "source": "sec_companyfacts",
            # Profitability
            "roe": None,
            "roic": None,
            "roic_gross": None,
            "roa": None,
            "gross_margin": None,
            "operating_margin": None,
            "net_margin": None,
            # Growth
            "revenue_growth": None,
            "revenue_cagr": None,
            "net_income_growth": None,
            "net_income_cagr": None,
            "operating_income_growth": None,
            "operating_income_cagr": None,
            "eps_growth": None,
            "eps_cagr": None,
            "fcf_growth": None,
            "fcf_cagr": None,
            "growth_consistency": 0.5,
            "growth_quality_flag": "UNKNOWN",
            # Balance Sheet & Leverage
            "debt": None,
            "cash": None,
            "equity": None,
            "debt_equity": None,
            "current_ratio": None,
            "net_debt_ebitda": None,
            "cash_debt": None,
            "interest_coverage": None,
            # Cash Generation
            "operating_cash_flow": None,
            "capex": None,
            "free_cash_flow": None,
            "fcf_margin": None,
            "fcf_conversion": None,
            # Valuation
            "pe": None,
            "ev_ebit": None,
            "ev_ebitda": None,
            "price_sales": None,
            "price_fcf": None,
            "ev_fcf": None,
            # Moat & Data Quality
            "quantitative_moat_score": 0.0,
            "moat_gm_stability": 0.0,
            "moat_op_persistence": 0.0,
            "moat_roic_spread": 0.0,
            "moat_fcf_durability": 0.0,
            "moat_capex_intensity": 0.0,
            "data_completeness_score": 0.0,
            "data_quality_flags": "MISSING_DATA",
            "is_valid": False,
        }

        if not facts_json or "facts" not in facts_json:
            return result

        # 1. Parse all annual facts
        all_annuals = parse_company_facts(facts_json, ticker=ticker, annual_only=True)
        if not all_annuals:
            return result

        # 2. Strict Point-in-Time Filter: filing_date <= screen_date
        raw_candidates = [
            r for r in all_annuals
            if r.get("filing_date") and r.get("filing_date") <= self.screen_date
            and (r.get("revenue") is not None or r.get("net_income") is not None)
        ]

        if not raw_candidates:
            logger.debug(f"CIK {cik}: No annual filings found filed on or before {self.screen_date}")
            return result

        # Deduplicate by report_date, keeping the latest filed version
        by_report: Dict[str, Dict[str, Any]] = {}
        for r in raw_candidates:
            rd = r["report_date"]
            if rd not in by_report or r["filing_date"] > by_report[rd]["filing_date"]:
                by_report[rd] = r

        all_sorted = sorted(by_report.values(), key=lambda x: x["report_date"])
        # Prefer periods with revenue reported
        rev_annuals = [r for r in all_sorted if r.get("revenue") is not None and r.get("revenue") > 0]
        base_annuals = rev_annuals if rev_annuals else all_sorted

        if not base_annuals:
            return result

        # Backward chain from latest report ensuring consecutive annual reports are separated by >= 300 days
        # This completely filters out quarterly footnote items (which are ~90 days apart)
        annual_chain = []
        curr = base_annuals[-1]
        annual_chain.append(curr)
        for prev in reversed(base_annuals[:-1]):
            try:
                d_curr = datetime.strptime(curr["report_date"], "%Y-%m-%d")
                d_prev = datetime.strptime(prev["report_date"], "%Y-%m-%d")
                if (d_curr - d_prev).days >= 300:
                    annual_chain.append(prev)
                    curr = prev
            except (ValueError, TypeError):
                continue
        annual_chain.reverse()  # Chronological order
        valid_annuals = annual_chain

        if not valid_annuals:
            return result


        # Latest available annual filing before screen_date (T0)
        t0 = valid_annuals[-1]
        result["filing_date"] = t0.get("filing_date")
        result["period_end"] = t0.get("report_date")
        result["form_type"] = t0.get("form")

        rev0 = t0.get("revenue")
        ni0 = t0.get("net_income")
        opinc0 = t0.get("operating_income")
        gp0 = t0.get("gross_profit")
        assets0 = t0.get("assets")
        eq0 = t0.get("equity")
        cash0 = t0.get("cash", 0.0) or 0.0
        debt0 = t0.get("debt", 0.0) or 0.0
        ocf0 = t0.get("operating_cash_flow")
        capex0 = t0.get("capex", 0.0) or 0.0
        fcf0 = t0.get("free_cash_flow")
        eps0 = t0.get("eps")

        # 3. Primary Financial Line Items
        result["revenue"] = rev0
        result["net_income"] = ni0
        result["operating_income"] = opinc0
        result["gross_profit"] = gp0
        result["assets"] = assets0
        result["equity"] = eq0
        result["debt"] = debt0
        result["cash"] = cash0
        result["operating_cash_flow"] = ocf0
        result["capex"] = capex0
        result["free_cash_flow"] = fcf0
        result["shares"] = t0.get("shares_outstanding")


        if rev0 and rev0 > 0:
            if gp0 is not None:
                result["gross_margin"] = float(gp0 / rev0)
            if opinc0 is not None:
                result["operating_margin"] = float(opinc0 / rev0)
            if ni0 is not None:
                result["net_margin"] = float(ni0 / rev0)
            if fcf0 is not None:
                result["fcf_margin"] = float(fcf0 / rev0)

        if ni0 is not None:
            if eq0 and eq0 > 0:
                result["roe"] = float(ni0 / eq0)
            if assets0 and assets0 > 0:
                result["roa"] = float(ni0 / assets0)

        result["roic"] = compute_roic(operating_income=opinc0, equity=eq0, debt=debt0, cash=cash0)
        if opinc0 is not None and eq0 and eq0 > 0:
            nopat = opinc0 * (1.0 - 0.21)
            gross_ic = (debt0 or 0.0) + eq0
            if gross_ic > 0:
                result["roic_gross"] = float(nopat / gross_ic)


        # 4. Leverage & Balance Sheet
        if eq0 and eq0 > 0:
            result["debt_equity"] = float(debt0 / eq0)
        if debt0 > 0:
            result["cash_debt"] = float(cash0 / debt0)

        ca0 = t0.get("current_assets")
        cl0 = t0.get("current_liabilities")
        if ca0 is not None and cl0 and cl0 > 0:
            result["current_ratio"] = float(ca0 / cl0)

        # EBITDA proxy = Operating Income + 0.5 * Capex (or Capex as D&A proxy)
        ebitda0 = None
        if opinc0 is not None:
            da_proxy = capex0 if capex0 > 0 else (assets0 * 0.04 if assets0 else 0.0)
            ebitda0 = opinc0 + da_proxy
            net_debt = debt0 - cash0
            if ebitda0 > 0:
                result["net_debt_ebitda"] = float(net_debt / ebitda0)

        if fcf0 is not None and ni0 and ni0 > 0:
            result["fcf_conversion"] = float(fcf0 / ni0)

        # 5. Multi-Year Growth & Consistency (YoY & 3-Year CAGR)
        num_years = len(valid_annuals)
        growth_rates: List[Optional[float]] = []

        if num_years >= 2:
            t_prev = valid_annuals[-2]
            result["revenue_growth"] = compute_yoy_growth(t_prev.get("revenue"), rev0)
            result["net_income_growth"] = compute_yoy_growth(t_prev.get("net_income"), ni0)
            result["operating_income_growth"] = compute_yoy_growth(t_prev.get("operating_income"), opinc0)
            result["eps_growth"] = compute_yoy_growth(t_prev.get("eps"), eps0)
            result["fcf_growth"] = compute_yoy_growth(t_prev.get("free_cash_flow"), fcf0)

            # Collect historical YoY revenue growth rates for consistency
            for i in range(1, num_years):
                g = compute_yoy_growth(valid_annuals[i - 1].get("revenue"), valid_annuals[i].get("revenue"))
                if g is not None:
                    growth_rates.append(g)

        if num_years >= 4:
            # 3-year CAGR (T-3 to T0)
            t_base = valid_annuals[-4]
            result["revenue_cagr"] = compute_cagr(t_base.get("revenue"), rev0, 3)
            result["net_income_cagr"] = compute_cagr(t_base.get("net_income"), ni0, 3)
            result["operating_income_cagr"] = compute_cagr(t_base.get("operating_income"), opinc0, 3)
            result["eps_cagr"] = compute_cagr(t_base.get("eps"), eps0, 3)
            result["fcf_cagr"] = compute_cagr(t_base.get("free_cash_flow"), fcf0, 3)
        elif num_years == 3:
            # 2-year CAGR fallback
            t_base = valid_annuals[-3]
            result["revenue_cagr"] = compute_cagr(t_base.get("revenue"), rev0, 2)
            result["net_income_cagr"] = compute_cagr(t_base.get("net_income"), ni0, 2)

        result["growth_consistency"] = compute_growth_consistency(growth_rates)

        # Assign growth_quality_flag
        if num_years < 3:
            result["growth_quality_flag"] = "UNKNOWN"
        else:
            max_yoy = max([g for g in growth_rates if g is not None], default=0.0)
            rev_cagr = result.get("revenue_cagr")
            if max_yoy > 0.50 or (rev_cagr is not None and rev_cagr > 0.30):
                result["growth_quality_flag"] = "ACQUISITION_INFLUENCED"
            else:
                result["growth_quality_flag"] = "ORGANIC_LIKELY"

        # 6. Valuation Multiples (Point-in-Time 2016)
        if market_cap_2016 and market_cap_2016 > 0:
            ev = compute_enterprise_value(market_cap=market_cap_2016, debt=debt0, cash=cash0)

            if ni0 and ni0 > 0:
                result["pe"] = float(market_cap_2016 / ni0)
            if opinc0 and opinc0 > 0:
                result["ev_ebit"] = float(ev / opinc0)
            if ebitda0 and ebitda0 > 0:
                result["ev_ebitda"] = float(ev / ebitda0)
            if rev0 and rev0 > 0:
                result["price_sales"] = float(market_cap_2016 / rev0)
            if fcf0 and fcf0 > 0:
                result["price_fcf"] = float(market_cap_2016 / fcf0)
                result["ev_fcf"] = float(ev / fcf0)

        # 7. Quantitative MOAT Proxy Calculation
        # Observable components:
        # a. Gross margin stability (std dev over available years)
        # b. Operating margin persistence (consistently positive)
        # c. ROIC durability (average ROIC > 10% cost of capital)
        # d. Low capital intensity (Capex / Revenue < 5%)
        # e. FCF durability (% of years with FCF > 0)
        moat_components = []

        gm_series = [r.get("gross_margin") for r in valid_annuals if r.get("gross_margin") is not None]
        if len(gm_series) >= 2:
            gm_std = float(np.std(gm_series))
            gm_stability = float(np.clip(1.0 - (gm_std / 0.10), 0.0, 1.0))
            result["moat_gm_stability"] = gm_stability
            moat_components.append(gm_stability * 0.25)
        elif len(gm_series) == 1:
            result["moat_gm_stability"] = 0.5
            moat_components.append(0.5 * 0.25)

        op_series = [r.get("operating_margin") for r in valid_annuals if r.get("operating_margin") is not None]
        if op_series:
            op_positive_pct = float(sum(1 for m in op_series if m > 0.08) / len(op_series))
            result["moat_op_persistence"] = op_positive_pct
            moat_components.append(op_positive_pct * 0.25)

        roic_series = [r.get("roic") for r in valid_annuals if r.get("roic") is not None]
        if roic_series:
            avg_roic = float(np.mean(roic_series))
            roic_spread = float(np.clip(avg_roic / 0.15, 0.0, 1.0))
            result["moat_roic_spread"] = roic_spread
            moat_components.append(roic_spread * 0.25)

        fcf_series = [r.get("free_cash_flow") for r in valid_annuals if r.get("free_cash_flow") is not None]
        if fcf_series:
            fcf_durability = float(sum(1 for f in fcf_series if f > 0) / len(fcf_series))
            result["moat_fcf_durability"] = fcf_durability
            moat_components.append(fcf_durability * 0.15)

        if rev0 and capex0 is not None:
            capex_intensity = float(capex0 / rev0)
            asset_light_score = float(np.clip(1.0 - (capex_intensity / 0.08), 0.0, 1.0))
            result["moat_capex_intensity"] = asset_light_score
            moat_components.append(asset_light_score * 0.10)

        result["quantitative_moat_score"] = float(np.clip(sum(moat_components), 0.0, 1.0))

        # 8. Data Completeness & Accounting Flags
        essential_metrics = [
            result["roe"],
            result["roic"],
            result["operating_margin"],
            result["free_cash_flow"],
            result["debt_equity"],
            result["revenue_growth"],
            result["pe"],
        ]
        non_null_count = sum(1 for m in essential_metrics if m is not None)
        result["data_completeness_score"] = float(non_null_count / len(essential_metrics))

        flags = []
        if eq0 and eq0 <= 0:
            flags.append("NEGATIVE_EQUITY")
        if ni0 and ni0 <= 0:
            flags.append("NEGATIVE_NET_INCOME")
        if ocf0 and ocf0 <= 0:
            flags.append("NEGATIVE_OCF")
        if fcf0 and fcf0 <= 0:
            flags.append("NEGATIVE_FCF")
        if rev0 and rev0 <= 0:
            flags.append("ZERO_OR_NEGATIVE_REVENUE")
        if result["roic"] is not None and result["roic"] > 1.0:
            flags.append("ROIC_EXTREME")
        if ni0 and ocf0 and abs(ocf0 - ni0) > abs(ni0) * 1.5:
            flags.append("LARGE_NI_OCF_DIVERGENCE")


        result["data_quality_flags"] = ";".join(flags) if flags else "CLEAN"
        result["is_valid"] = result["data_completeness_score"] >= 0.40

        return result
