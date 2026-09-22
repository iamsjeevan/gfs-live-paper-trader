"""Universe filtering rules and classification.

Applies exclusion criteria:
- Financial sector exclusion via SIC codes (6000-6999)
- Major US exchange validation (NYSE, NASDAQ, AMEX)
- Small-cap market capitalization boundaries
- Status tagging: 'eligible', 'not_small_cap', 'not_listed', 'financial_sector',
  'missing_price', 'missing_shares', 'insufficient_data'
"""

from typing import Any, Dict, Optional, Tuple

VALID_US_EXCHANGES = {
    "NYSE",
    "NASDAQ",
    "AMEX",
    "NYSEMKT",
    "BATS",
    "ARCA",
    "NYSE ARCA",
    "NYSE AMERICAN",
}


def is_financial_sector(sic: Optional[int]) -> bool:
    """Check if company belongs to the Financial sector (SIC codes 6000 to 6999).

    Includes:
    - 6000-6099: Depository Institutions (Commercial banks, savings banks)
    - 6100-6199: Nondepository Credit Institutions
    - 6200-6299: Security and Commodity Brokers & Dealers
    - 6300-6399: Insurance Carriers
    - 6400-6499: Insurance Agents & Brokers
    - 6500-6599: Real Estate
    - 6700-6799: Holding and Other Investment Offices (including REITs, closed-end funds, SPACs)
    """
    if sic is None:
        return False
    try:
        sic_code = int(sic)
        return 6000 <= sic_code <= 6999
    except (ValueError, TypeError):
        return False


def is_valid_exchange(exchange: Optional[str]) -> bool:
    """Check if the exchange is a major US public exchange (not OTC / Pink Sheets)."""
    if not exchange:
        return False
    ex_upper = str(exchange).strip().upper()
    for valid_ex in VALID_US_EXCHANGES:
        if valid_ex in ex_upper:
            return True
    return False


def is_in_market_cap_range(
    market_cap: Optional[float],
    min_market_cap: float = 50_000_000.0,
    max_market_cap: float = 1_000_000_000.0,
) -> bool:
    """Check if market capitalization falls within specified small-cap bounds."""
    if market_cap is None:
        return False
    return min_market_cap <= market_cap <= max_market_cap


def classify_company(
    market_cap_result: Dict[str, Any],
    sic: Optional[int] = None,
    exchange: Optional[str] = None,
    exclude_financials: bool = True,
    min_market_cap: float = 50_000_000.0,
    max_market_cap: float = 1_000_000_000.0,
    require_major_exchange: bool = True,
) -> Tuple[str, Optional[str]]:
    """Determine universe eligibility status and specific exclusion reason.

    Returns:
        (status, reason_description)
        Possible statuses:
        - 'eligible'
        - 'financial_sector'
        - 'not_listed'
        - 'missing_price'
        - 'missing_shares'
        - 'not_small_cap'
        - 'insufficient_data'
    """
    # 1. Financial Sector Filter
    if exclude_financials and is_financial_sector(sic):
        return "financial_sector", f"Excluded: Financial sector (SIC {sic})"

    # 2. Exchange Filter
    if require_major_exchange and not is_valid_exchange(exchange):
        return "not_listed", f"Excluded: Not listed on major US exchange (Exchange: {exchange or 'Unknown'})"

    # 3. Market Cap Validity Check
    if not market_cap_result.get("is_valid", False):
        err = market_cap_result.get("exclusion_reason", "insufficient_data")
        if err == "missing_price":
            return "missing_price", "Excluded: Missing historical price on or before screen date"
        elif err == "missing_shares":
            return "missing_shares", "Excluded: Missing SEC-reported historical shares outstanding"
        elif err == "missing_ticker":
            return "not_listed", "Excluded: Missing valid ticker symbol"
        return "insufficient_data", f"Excluded: {err}"

    # 4. Market Cap Bounds Check
    mcap = market_cap_result.get("market_cap")
    if not is_in_market_cap_range(mcap, min_market_cap, max_market_cap):
        if mcap < min_market_cap:
            return "not_small_cap", f"Excluded: Market cap ${mcap/1e6:.1f}M below minimum ${min_market_cap/1e6:.1f}M (micro/nano-cap)"
        else:
            return "not_small_cap", f"Excluded: Market cap ${mcap/1e6:.1f}M above maximum ${max_market_cap/1e6:.1f}M (mid/large-cap)"

    # All criteria passed!
    return "eligible", None
