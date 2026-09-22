"""SEC XBRL Company Facts parser.

Extracts normalized point-in-time financial statements (Balance Sheet,
Income Statement, Cash Flow) from SEC CompanyFacts JSON.
Strictly records `filing_date` (filed) and `report_date` (end) for every fact.
"""

from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np
import pandas as pd

from config.settings import setup_logger

logger = setup_logger("sec_parser", "sec_download.log")

# -----------------------------------------------------------------------------
# Concept Mappings (US-GAAP & DEI)
# -----------------------------------------------------------------------------
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "Revenues",
    "SalesRevenueGoodsNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]

NET_INCOME_CONCEPTS = [
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
]

OPERATING_INCOME_CONCEPTS = [
    "OperatingIncomeLoss",
]

GROSS_PROFIT_CONCEPTS = [
    "GrossProfit",
]

ASSETS_CONCEPTS = [
    "Assets",
]

CURRENT_ASSETS_CONCEPTS = [
    "AssetsCurrent",
]

LIABILITIES_CONCEPTS = [
    "Liabilities",
]

CURRENT_LIABILITIES_CONCEPTS = [
    "LiabilitiesCurrent",
]

EQUITY_CONCEPTS = [
    "StockholdersEquity",
    "CommonStockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
]

CASH_CONCEPTS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    "Cash",
]

LONG_TERM_DEBT_CONCEPTS = [
    "LongTermDebtNoncurrent",
    "LongTermDebt",
    "LongTermDebtAndCapitalLeaseObligations",
]

SHORT_TERM_DEBT_CONCEPTS = [
    "ShortTermBorrowings",
    "DebtCurrent",
    "LongTermDebtCurrent",
]

OPERATING_CASH_FLOW_CONCEPTS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
]

CAPEX_CONCEPTS = [
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]

SHARES_OUTSTANDING_CONCEPTS = [
    "CommonStockSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
]

DILUTED_SHARES_CONCEPTS = [
    "WeightedAverageNumberOfDilutedSharesOutstanding",
]

EPS_CONCEPTS = [
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
]


def extract_concept_series(
    us_gaap_facts: Dict[str, Any],
    concept_names: List[str],
    preferred_unit: str = "USD",
) -> List[Dict[str, Any]]:
    """Extract observation items across concept_names in priority order.

    If multiple concepts represent the metric across different time periods (e.g.
    modern ASC 606 vs legacy 'Revenues' / 'SalesRevenueNet'), items from all matching
    concepts are gathered so both modern and historical filings are captured.
    Higher-priority concepts take precedence for duplicate period observations.
    """
    all_items: List[Dict[str, Any]] = []
    seen_periods: Set[Tuple[Any, Any, Any, Any]] = set()

    for concept in concept_names:
        if concept in us_gaap_facts:
            units_dict = us_gaap_facts[concept].get("units", {})
            items = units_dict.get(preferred_unit)
            if not items and units_dict:
                items = list(units_dict.values())[0]
            if items:
                for item in items:
                    end = item.get("end")
                    fp = item.get("fp")
                    form = item.get("form")
                    accn = item.get("accn")
                    key = (end, fp, form, accn)
                    if key not in seen_periods:
                        seen_periods.add(key)
                        all_items.append(item)
    return all_items



def parse_company_facts(
    facts_json: Dict[str, Any],
    ticker: Optional[str] = None,
    annual_only: bool = True,
) -> List[Dict[str, Any]]:
    """Parse raw SEC Company Facts into normalized financial records.

    Args:
        facts_json: Full JSON returned by SEC companyfacts API.
        ticker: Optional ticker symbol.
        annual_only: If True, filter for Form 10-K / fiscal period 'FY'.

    Returns:
        List of dictionaries corresponding to rows in the `fundamentals` table.
    """
    if not facts_json or "facts" not in facts_json:
        return []

    cik = int(facts_json.get("cik", 0))
    facts = facts_json.get("facts", {})
    us_gaap = facts.get("us-gaap", {})
    dei = facts.get("dei", {})

    # Gather observations for each concept
    concept_map = {
        "revenue": extract_concept_series(us_gaap, REVENUE_CONCEPTS, "USD"),
        "net_income": extract_concept_series(us_gaap, NET_INCOME_CONCEPTS, "USD"),
        "operating_income": extract_concept_series(us_gaap, OPERATING_INCOME_CONCEPTS, "USD"),
        "gross_profit": extract_concept_series(us_gaap, GROSS_PROFIT_CONCEPTS, "USD"),
        "assets": extract_concept_series(us_gaap, ASSETS_CONCEPTS, "USD"),
        "current_assets": extract_concept_series(us_gaap, CURRENT_ASSETS_CONCEPTS, "USD"),
        "liabilities": extract_concept_series(us_gaap, LIABILITIES_CONCEPTS, "USD"),
        "current_liabilities": extract_concept_series(us_gaap, CURRENT_LIABILITIES_CONCEPTS, "USD"),
        "equity": extract_concept_series(us_gaap, EQUITY_CONCEPTS, "USD"),
        "cash": extract_concept_series(us_gaap, CASH_CONCEPTS, "USD"),
        "long_term_debt": extract_concept_series(us_gaap, LONG_TERM_DEBT_CONCEPTS, "USD"),
        "short_term_debt": extract_concept_series(us_gaap, SHORT_TERM_DEBT_CONCEPTS, "USD"),
        "operating_cash_flow": extract_concept_series(us_gaap, OPERATING_CASH_FLOW_CONCEPTS, "USD"),
        "capex": extract_concept_series(us_gaap, CAPEX_CONCEPTS, "USD"),
        "eps": extract_concept_series(us_gaap, EPS_CONCEPTS, "USD/shares"),
        "shares_outstanding": (
            extract_concept_series(dei, SHARES_OUTSTANDING_CONCEPTS, "shares")
            or extract_concept_series(us_gaap, SHARES_OUTSTANDING_CONCEPTS, "shares")
        ),
        "diluted_shares": extract_concept_series(us_gaap, DILUTED_SHARES_CONCEPTS, "shares"),
    }

    # Group observations by (report_date, fiscal_period, form)
    # Key: (end_date, fp, form)
    records_by_key: Dict[tuple, Dict[str, Any]] = {}

    for metric_name, items in concept_map.items():
        for item in items:
            form = item.get("form", "")
            fp = item.get("fp", "")
            end_date = item.get("end")
            filed_date = item.get("filed")

            if not end_date or not filed_date:
                continue

            if annual_only:
                # Restrict to annual reports
                if form not in ("10-K", "10-K/A") and fp != "FY":
                    continue

            key = (end_date, fp, form)
            if key not in records_by_key:
                records_by_key[key] = {
                    "cik": cik,
                    "ticker": ticker,
                    "filing_date": filed_date,
                    "report_date": end_date,
                    "fiscal_year": item.get("fy"),
                    "fiscal_period": fp,
                    "form": form,
                    "accession_number": item.get("accn"),
                }

            # Take the latest filed value for the metric if multiple exist for the same report key
            val = item.get("val")
            if val is not None:
                records_by_key[key][metric_name] = float(val)

    # Convert to list and calculate derived ratios + quality flags
    results: List[Dict[str, Any]] = []
    for key, rec in records_by_key.items():
        flags: Set[str] = set()

        # Compute total debt
        lt_debt = rec.get("long_term_debt", 0.0) or 0.0
        st_debt = rec.get("short_term_debt", 0.0) or 0.0
        tot_debt = lt_debt + st_debt
        rec["debt"] = tot_debt if (lt_debt > 0 or st_debt > 0) else None

        # Capex & Free Cash Flow
        ocf = rec.get("operating_cash_flow")
        capex = rec.get("capex")
        if ocf is not None:
            c_val = abs(capex) if capex is not None else 0.0
            rec["capex"] = c_val
            rec["free_cash_flow"] = ocf - c_val
        else:
            rec["free_cash_flow"] = None

        # Flags for missing required metrics
        revenue = rec.get("revenue")
        net_income = rec.get("net_income")
        operating_income = rec.get("operating_income")
        gross_profit = rec.get("gross_profit")
        assets = rec.get("assets")
        equity = rec.get("equity")
        fcf = rec.get("free_cash_flow")
        shares = rec.get("shares_outstanding")

        if revenue is None:
            flags.add("missing_revenue")
        if net_income is None:
            flags.add("missing_net_income")
        if equity is None:
            flags.add("missing_equity")
        if rec["debt"] is None:
            flags.add("missing_debt")
        if fcf is None:
            flags.add("missing_fcf")
        if shares is None:
            flags.add("missing_shares")

        # Margins
        if revenue and revenue > 0:
            if gross_profit is not None:
                rec["gross_margin"] = gross_profit / revenue
            if operating_income is not None:
                rec["operating_margin"] = operating_income / revenue
            if net_income is not None:
                rec["net_margin"] = net_income / revenue
            if fcf is not None:
                rec["fcf_margin"] = fcf / revenue

        # Returns on Capital (ROE, ROA, ROIC)
        if net_income is not None:
            if equity and equity > 0:
                rec["roe"] = net_income / equity
            if assets and assets > 0:
                rec["roa"] = net_income / assets

        if operating_income is not None and equity and equity > 0:
            # ROIC proxy: NOPAT / Invested Capital (Debt + Equity - Cash)
            nopat = operating_income * (1.0 - 0.21)  # standard corporate tax rate assumption
            invested_capital = (rec["debt"] or 0.0) + equity - (rec.get("cash") or 0.0)
            if invested_capital > 0:
                rec["roic"] = nopat / invested_capital

        # Leverage & Liquidity
        if rec["debt"] is not None and equity and equity > 0:
            rec["debt_equity"] = rec["debt"] / equity

        curr_assets = rec.get("current_assets")
        curr_liab = rec.get("current_liabilities")
        if curr_assets is not None and curr_liab and curr_liab > 0:
            rec["current_ratio"] = curr_assets / curr_liab

        rec["data_quality_flags"] = ",".join(sorted(flags)) if flags else None
        results.append(rec)

    # Sort chronologically by report_date
    results.sort(key=lambda x: x["report_date"])
    return results
