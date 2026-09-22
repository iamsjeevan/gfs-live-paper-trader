"""Historical Point-in-Time Market Capitalization Engine.

Computes market cap strictly as of a historical date:
    market_cap = historical_unadjusted_price × historical_shares_outstanding

Rules:
- Strictly enforces point-in-time discipline:
  1. Price: Closing price on or immediately prior to `screen_date` (e.g. 2016-12-30 for weekend 2016-12-31).
     Uses UNADJUSTED close price to properly match unadjusted historical shares.
  2. Shares: The most recent SEC-reported common shares outstanding observation filed ON OR BEFORE `screen_date`.
- If either price or shares cannot be confirmed historically, the company is flagged with an explicit exclusion reason.
- Never substitutes today's price or today's shares.
"""

from typing import Any, Dict, List, Optional, Tuple
import sqlite3
import pandas as pd

from config.settings import setup_logger
from data_sources.market_data.base import PriceProvider
from data_sources.sec.companyfacts import fetch_company_facts

logger = setup_logger("market_cap", "screening.log")

SHARE_CONCEPTS = [
    "EntityCommonStockSharesOutstanding",
    "CommonStockSharesOutstanding",
    "WeightedAverageNumberOfSharesOutstandingBasic",
]


def extract_historical_shares_from_facts(
    facts_json: Dict[str, Any],
    screen_date: str,
) -> Optional[Tuple[float, str, str, str]]:
    """Extract the most recent common shares outstanding filed on or before screen_date.

    Args:
        facts_json: SEC companyfacts JSON dictionary.
        screen_date: 'YYYY-MM-DD' cutoff date.

    Returns:
        Tuple of (shares_count, filing_date, report_date, concept_name) or None.
    """
    if not facts_json or "facts" not in facts_json:
        return None

    facts = facts_json.get("facts", {})
    candidates = []

    # Priority 1: dei.EntityCommonStockSharesOutstanding (cover page of 10-K/10-Q)
    # Priority 2: us-gaap.CommonStockSharesOutstanding
    # Priority 3: us-gaap.WeightedAverageNumberOfSharesOutstandingBasic
    for taxonomy in ["dei", "us-gaap"]:
        tax_dict = facts.get(taxonomy, {})
        for concept in SHARE_CONCEPTS:
            if concept in tax_dict:
                items = tax_dict[concept].get("units", {}).get("shares", [])
                for item in items:
                    filed = item.get("filed", "")
                    end_dt = item.get("end", "")
                    val = item.get("val")

                    # Strictly enforce filing_date <= screen_date
                    if filed and filed <= screen_date and val is not None:
                        try:
                            s_val = float(val)
                            if s_val > 0:
                                candidates.append((filed, end_dt, s_val, f"{taxonomy}:{concept}"))
                        except (ValueError, TypeError):
                            continue

    if not candidates:
        return None

    # Sort primarily by filing_date ascending (latest filed wins)
    candidates.sort(key=lambda x: (x[0], x[1]))
    latest_filed, latest_end, latest_val, latest_concept = candidates[-1]
    return (latest_val, latest_filed, latest_end, latest_concept)


from universe.share_resolver import HistoricalShareResolver

_share_resolver = HistoricalShareResolver()


def get_historical_shares_outstanding(
    cik: int,
    screen_date: str,
    conn: Optional[sqlite3.Connection] = None,
    facts_json: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[float, str, str, str]]:
    """Get historical shares outstanding for CIK as of screen_date.

    Args:
        cik: Company CIK.
        screen_date: Cutoff date string 'YYYY-MM-DD'.
        conn: Optional SQLite connection.
        facts_json: Pre-loaded companyfacts dict.

    Returns:
        (shares, filing_date, report_date, source_concept) or None.
    """
    res = _share_resolver.resolve_shares(
        cik=cik,
        screen_date=screen_date,
        conn=conn,
        facts_json=facts_json,
    )
    if res and res.get("is_valid"):
        return (
            res["shares"],
            res["shares_filing_date"],
            res["shares_report_date"],
            res["source"],
        )
    return None


def calculate_historical_market_cap(
    cik: int,
    ticker: Optional[str],
    screen_date: str,
    price_provider: PriceProvider,
    conn: Optional[sqlite3.Connection] = None,
    facts_json: Optional[Dict[str, Any]] = None,
    max_price_lookback_days: int = 10,
) -> Dict[str, Any]:
    """Calculate historical point-in-time market capitalization for a single company.

    Returns:
        Dict with keys:
        ['cik', 'ticker', 'screen_date', 'price', 'price_date', 'shares',
         'shares_filing_date', 'shares_report_date', 'market_cap', 'is_valid', 'exclusion_reason']
    """
    result = {
        "cik": cik,
        "ticker": ticker,
        "screen_date": screen_date,
        "price": None,
        "shares": None,
        "shares_filing_date": None,
        "shares_report_date": None,
        "shares_source": None,
        "market_cap": None,
        "is_valid": False,
        "exclusion_reason": None,
    }

    # 1. Historical Shares (filed on or before screen_date)
    shares_tuple = get_historical_shares_outstanding(
        cik=cik,
        screen_date=screen_date,
        conn=conn,
        facts_json=facts_json,
    )

    if shares_tuple is None:
        result["exclusion_reason"] = "missing_shares"
        return result

    shares_val, s_filed, s_report, s_concept = shares_tuple
    result["shares"] = shares_val
    result["shares_filing_date"] = s_filed
    result["shares_report_date"] = s_report
    result["shares_source"] = s_concept

    # 2. Historical Price (unadjusted closing price on or immediately prior to screen_date)
    price_val = None
    provider_name = None
    data_quality = "CLEAN"

    if hasattr(price_provider, "resolve_price"):
        res = price_provider.resolve_price(
            cik=cik,
            ticker=ticker,
            date=screen_date,
            prefer_unadjusted=True,
            max_lookback_days=max_price_lookback_days,
        )
        if res.get("is_valid"):
            price_val = res.get("price")
            provider_name = res.get("provider")
            data_quality = res.get("data_quality")
            result["price_date"] = res.get("price_date")
    elif ticker:
        price_val = price_provider.get_price(
            ticker=ticker,
            date=screen_date,
            adjusted=False,  # Strictly UNADJUSTED price
            lookback_days=max_price_lookback_days,
        )
        provider_name = getattr(price_provider, "name", "price_provider")

    if price_val is None or price_val <= 0:
        result["exclusion_reason"] = "missing_price" if ticker else "missing_ticker"
        return result

    result["price"] = price_val
    result["provider"] = provider_name
    result["data_quality"] = data_quality

    # 3. Market Capitalization
    market_cap = price_val * shares_val
    result["market_cap"] = market_cap
    result["is_valid"] = True
    result["exclusion_reason"] = None

    return result
