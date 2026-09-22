"""Security classification engine for SEC filers and listings.

Distinguishes common stock investment opportunities from preferred shares,
debt/notes, REITs, funds/ETFs, ADRs, warrants, and other instruments.

Classification Categories:
- 'COMMON_EQUITY': Standard common stock of US operating corporation
- 'PREFERRED': Preferred stock, depositary shares representing preferred
- 'DEBT': Corporate notes, baby bonds, debentures, senior notes
- 'REIT': Real Estate Investment Trust (SIC 6798)
- 'ETF/FUND': Registered investment companies, closed-end funds, ETFs (SIC 6722, 6726)
- 'ADR': American Depositary Receipts / foreign equity (Forms 20-F, 40-F)
- 'OTHER': Warrants, rights, units, special purpose vehicles
"""

import re
from typing import Any, Dict, List, Optional


def classify_security_type(
    ticker: Optional[str] = None,
    company_name: Optional[str] = None,
    sic: Optional[int] = None,
    forms: Optional[List[str]] = None,
    title: Optional[str] = None,
) -> str:
    """Classify a security into one of the canonical security types.

    Args:
        ticker: Stock ticker symbol (e.g. 'AAPL', 'WRB-PH', 'RAD', 'AKZOY').
        company_name: Official SEC entity or registrant name.
        sic: Standard Industrial Classification 4-digit code.
        forms: List of historical filing form types (e.g. ['10-K', '20-F', 'N-CSR']).
        title: Title of security from cover page / dei:Security12bTitle.

    Returns:
        One of: 'COMMON_EQUITY', 'PREFERRED', 'DEBT', 'ETF/FUND', 'REIT', 'ADR', 'OTHER'.
    """
    t_clean = (ticker or "").strip().upper()
    n_clean = (company_name or "").strip().upper()
    tit_clean = (title or "").strip().upper()
    forms_set = set(f.strip().upper() for f in (forms or []))

    # 1. Preferred Stocks
    # Ticker conventions: FRT-PC, USB-PS, BOH-PB, BAC-PA, WRB-PH, or /PRA, .PR
    if re.search(r"[-/.](?:P[A-Z]|PR[A-Z]?|PFD)$", t_clean) or t_clean.endswith("PR"):
        return "PREFERRED"
    if any(k in n_clean for k in [" PREFERRED", " PFD ", " % CUM", "SERIES A PFD", "SERIES B PFD"]):
        return "PREFERRED"
    if any(k in tit_clean for k in ["PREFERRED STOCK", "PREFERRED SHARES", "DEPOSITARY SHARES REPRESENTING"]):
        return "PREFERRED"

    # 2. Debt / Notes / Baby Bonds
    if re.search(r"[-/.](?:NT|DB|CL|NOTES)$", t_clean):
        return "DEBT"
    if any(k in n_clean for k in [" SENIOR NOTES", " DEBENTURE", " DEBENTURES", " NOTES DUE ", " BOND FUND"]):
        # Disambiguate funds
        if "FUND" in n_clean:
            return "ETF/FUND"
        return "DEBT"
    if any(k in tit_clean for k in ["SENIOR NOTES", "NOTES DUE", "DEBENTURES DUE", "SUBORDINATED DEBENTURES"]):
        return "DEBT"

    # 3. REITs (Real Estate Investment Trusts)
    if sic == 6798:
        return "REIT"
    if any(k in n_clean for k in [" REIT", "REAL ESTATE INVESTMENT TRUST", "REALTY TRUST"]):
        return "REIT"

    # 4. ETFs & Investment Funds
    if sic in (6722, 6726):
        return "ETF/FUND"
    if any(f.startswith("N-") for f in forms_set):
        return "ETF/FUND"
    if any(k in n_clean for k in ["INCOME FUND", "HIGH YIELD FUND", "CLOSED-END FUND", "INDEX FUND", "EQUITY TRUST", "MUNICIPAL FUND"]):
        return "ETF/FUND"

    # 5. ADRs (American Depositary Receipts / Foreign Issuers)
    if any(f in forms_set for f in ["20-F", "40-F", "6-K"]):
        return "ADR"
    if any(k in n_clean for k in [" ADR", " ADS", "AMERICAN DEPOSITARY", "SPONSORED ADR"]):
        return "ADR"
    if len(t_clean) == 5 and t_clean.endswith("Y"):
        return "ADR"

    # 6. Warrants / Rights / Units
    if re.search(r"[-/.](?:WS|WT|RT|UN|U)$", t_clean) or t_clean.endswith("WS") or t_clean.endswith("WT"):
        return "OTHER"
    if any(k in n_clean for k in [" WARRANT", " WARRANTS", " RIGHTS", " ACQUISITION CORP"]):
        return "OTHER"

    # 7. Common Equity
    return "COMMON_EQUITY"
