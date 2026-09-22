"""Universe package for US Stock Research framework."""

from .filters import (
    is_financial_sector,
    is_valid_exchange,
    is_in_market_cap_range,
    classify_company,
)
from .market_cap import (
    calculate_historical_market_cap,
    get_historical_shares_outstanding,
    extract_historical_shares_from_facts,
)
from .historical_universe import build_historical_smallcap_universe
from .survivorship_audit import (
    classify_historical_status,
    audit_price_coverage,
    audit_shares_filing_lag,
)

__all__ = [
    "is_financial_sector",
    "is_valid_exchange",
    "is_in_market_cap_range",
    "classify_company",
    "calculate_historical_market_cap",
    "get_historical_shares_outstanding",
    "extract_historical_shares_from_facts",
    "build_historical_smallcap_universe",
    "classify_historical_status",
    "audit_price_coverage",
    "audit_shares_filing_lag",
]
