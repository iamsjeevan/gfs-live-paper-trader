"""Point-in-time 2016 fundamental metrics extraction and moat calculation for Milestone 7."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

from config.settings import setup_logger
from fundamentals.engine import PointInTimeFundamentalsEngine
from screening.filters import QualityFilterConfig, evaluate_quality_filters

logger = setup_logger("retrospective_metrics", "screening.log")


def extract_2016_fundamentals(
    eligible_df: pd.DataFrame,
    screen_date: str = "2016-12-31",
) -> pd.DataFrame:
    """Extract complete point-in-time 2016 fundamentals across the eligible universe.

    Ensures zero look-ahead bias: strictly filing_date <= screen_date.
    """
    engine = PointInTimeFundamentalsEngine(screen_date=screen_date)
    filter_config = QualityFilterConfig(allow_temporary_fcf_exception=False)

    records: List[Dict[str, Any]] = []

    for _, row in eligible_df.iterrows():
        cik = int(row["cik"])
        ticker = row["ticker"]
        mcap = float(row.get("market_cap_2016", 0.0))
        price = float(row.get("price_2016", 0.0))
        name = row.get("company_name", ticker)
        exchange = row.get("exchange", "UNKNOWN")
        sic = row.get("sic", "")

        fund = engine.compute_company_fundamentals(
            cik=cik,
            ticker=ticker,
            market_cap_2016=mcap,
        )

        # Evaluate quality filters
        passes, fail_reasons = evaluate_quality_filters(fund, filter_config)

        # Extract filing date for strict look-ahead verification
        filing_dt = fund.get("filing_date")
        is_strictly_pit = (str(filing_dt) <= screen_date) if filing_dt else True

        # Extract fundamental metrics
        rev = fund.get("revenue")
        net_inc = fund.get("net_income")
        op_inc = fund.get("operating_income")
        ocf = fund.get("operating_cash_flow")
        fcf = fund.get("free_cash_flow")
        capex = fund.get("capex")
        equity = fund.get("equity")
        debt = fund.get("debt")
        cash = fund.get("cash")

        # Ratios
        roe = fund.get("roe")
        roic = fund.get("roic")
        roic_gross = fund.get("roic_gross")
        debt_eq = fund.get("debt_equity")
        op_margin = fund.get("operating_margin")
        gross_margin = fund.get("gross_margin")
        fcf_margin = fund.get("fcf_margin")

        # Growth
        rev_cagr = fund.get("revenue_cagr")
        ni_cagr = fund.get("net_income_cagr")
        fcf_cagr = fund.get("fcf_cagr")
        growth_const = fund.get("growth_consistency")
        growth_flag = fund.get("growth_quality_flag", "CLEAN")

        # Valuation
        pe = fund.get("pe")
        ev_ebitda = fund.get("ev_ebitda")
        pfcf = fund.get("price_fcf")
        ps = (mcap / rev) if (rev and rev > 0 and mcap > 0) else None

        # Quantitative Moat Score (25/25/25/15/10 weighting)
        moat_score = fund.get("quantitative_moat_score")
        moat_gm = fund.get("moat_gm_stability")
        moat_op = fund.get("moat_op_persistence")
        moat_roic = fund.get("moat_roic_spread")
        moat_fcf = fund.get("moat_fcf_durability")
        moat_capex = fund.get("moat_capex_intensity")

        records.append({
            "cik": cik,
            "ticker": ticker,
            "company_name": name,
            "exchange": exchange,
            "sic": sic,
            "screen_date": screen_date,
            "filing_date": filing_dt,
            "period_end": fund.get("period_end"),
            "is_strictly_pit": is_strictly_pit,
            "market_cap_2016": mcap,
            "price_2016": price,
            # Financial size
            "revenue_2016": rev,
            "net_income_2016": net_inc,
            "operating_income_2016": op_inc,
            "operating_cash_flow_2016": ocf,
            "free_cash_flow_2016": fcf,
            "capex_2016": capex,
            "equity_2016": equity,
            "debt_2016": debt,
            "cash_2016": cash,
            # Quality
            "roe": roe,
            "roic": roic,
            "roic_gross": roic_gross,
            "debt_equity": debt_eq,
            "operating_margin": op_margin,
            "gross_margin": gross_margin,
            "fcf_margin": fcf_margin,
            # Growth
            "revenue_cagr_3y": rev_cagr,
            "net_income_cagr_3y": ni_cagr,
            "fcf_cagr_3y": fcf_cagr,
            "growth_consistency": growth_const,
            "growth_quality_flag": growth_flag,
            # Valuation
            "pe_ratio": pe,
            "ev_ebitda": ev_ebitda,
            "price_fcf": pfcf,
            "price_sales": ps,
            # Moat
            "quantitative_moat_score": moat_score,
            "moat_gm_stability": moat_gm,
            "moat_op_persistence": moat_op,
            "moat_roic_spread": moat_roic,
            "moat_fcf_durability": moat_fcf,
            "moat_capex_discipline": moat_capex,
            # Quality screen evaluation
            "passes_quality_filters": passes,
            "failure_reasons": "; ".join(fail_reasons) if fail_reasons else "NONE",
            "has_positive_fcf": bool(fcf and fcf > 0),
            "has_low_debt": bool(debt_eq is not None and debt_eq <= 1.5),
            "has_high_roic": bool(roic and roic >= 0.12),
            "has_positive_op_inc": bool(op_inc and op_inc > 0),
        })

    return pd.DataFrame(records)
