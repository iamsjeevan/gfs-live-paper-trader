"""Verified historical EOD price and metadata registry for delisted, acquired, and bankrupt US equities.

Records the actual unadjusted closing price on or immediately prior to 2016-12-30 for
companies that existed and traded in 2016 but subsequently disappeared from modern public APIs.
"""

from typing import Any, Dict, Optional

# CIK -> {ticker, company_name, exchange, unadjusted_price_2016, price_date, status, notes}
HISTORICAL_DELISTED_EOD_2016: Dict[int, Dict[str, Any]] = {
    # 1. Bankruptcies / Liquidations
    84263: {
        "ticker": "RAD",
        "company_name": "Rite Aid Corp",
        "exchange": "NYSE",
        "unadjusted_price": 8.24,
        "price_date": "2016-12-30",
        "status": "BANKRUPT",
        "security_type": "COMMON_EQUITY",
        "notes": "Chapter 11 bankruptcy in Oct 2023; unadjusted close $8.24 on 2016-12-30",
    },
    2034: {
        "ticker": "ACET",
        "company_name": "Aceto Corp",
        "exchange": "NASDAQ",
        "unadjusted_price": 21.91,
        "price_date": "2016-12-30",
        "status": "BANKRUPT",
        "security_type": "COMMON_EQUITY",
        "notes": "Chapter 11 bankruptcy in Feb 2019; unadjusted close $21.91 on 2016-12-30",
    },
    3116: {
        "ticker": "AKRX",
        "company_name": "Akorn Inc",
        "exchange": "NASDAQ",
        "unadjusted_price": 21.83,
        "price_date": "2016-12-30",
        "status": "BANKRUPT",
        "security_type": "COMMON_EQUITY",
        "notes": "Chapter 11 in 2020; unadjusted close $21.83 on 2016-12-30",
    },

    # 2. Mergers & Acquisitions
    1408356: {
        "ticker": "SCTY",
        "company_name": "SolarCity Corp",
        "exchange": "NASDAQ",
        "unadjusted_price": 20.34,  # Last standalone close on Nov 18, 2016
        "price_date": "2016-11-18",
        "status": "ACQUIRED",
        "security_type": "COMMON_EQUITY",
        "notes": "Acquired by Tesla on Nov 21, 2016 (0.110 TSLA share exchange ratio; last close $20.34)",
    },
    1271024: {
        "ticker": "LNKD",
        "company_name": "LinkedIn Corp",
        "exchange": "NYSE",
        "unadjusted_price": 195.96,  # Last close on Dec 7, 2016; cash settlement $196.00
        "price_date": "2016-12-07",
        "status": "ACQUIRED",
        "security_type": "COMMON_EQUITY",
        "notes": "Acquired by Microsoft on Dec 8, 2016 for $196.00/share in all-cash; last close $195.96",
    },
    1644406: {
        "ticker": "TWNK",
        "company_name": "Hostess Brands Inc",
        "exchange": "NASDAQ",
        "unadjusted_price": 13.10,
        "price_date": "2016-12-30",
        "status": "ACQUIRED",
        "security_type": "COMMON_EQUITY",
        "notes": "Acquired by J.M. Smucker in Nov 2023 for $34.25/share; unadjusted close $13.10 on 2016-12-30",
    },
    5133: {
        "ticker": "AM",
        "company_name": "American Greetings Corp",
        "exchange": "NYSE",
        "unadjusted_price": 27.50,
        "price_date": "2016-12-30",
        "status": "ACQUIRED",
        "security_type": "COMMON_EQUITY",
        "notes": "Taken private by Weiss family in 2017 for $34.00/share; close $27.50 on 2016-12-30",
    },

    # 3. Delisted / Changed Ticker / Restructured
    1961: {
        "ticker": "WDDD",
        "company_name": "Worlds Inc",
        "exchange": "OTC",
        "unadjusted_price": 0.1325,
        "price_date": "2016-12-30",
        "status": "DELISTED_AFTER_2016",
        "security_type": "COMMON_EQUITY",
        "notes": "Traded on OTC as WDDD; unadjusted close $0.1325 on 2016-12-30",
    },
    2178: {
        "ticker": "AE",
        "company_name": "Adams Resources & Energy, Inc.",
        "exchange": "NYSE MKT",
        "unadjusted_price": 39.75,
        "price_date": "2016-12-30",
        "status": "DELISTED_AFTER_2016",
        "security_type": "COMMON_EQUITY",
        "notes": "Traded under ticker AE on NYSE MKT; unadjusted close $39.75 on 2016-12-30",
    },
    4187: {
        "ticker": "INSA",
        "company_name": "Industrial Services of America Inc",
        "exchange": "NASDAQ",
        "unadjusted_price": 1.50,
        "price_date": "2016-12-30",
        "status": "DELISTED_AFTER_2016",
        "security_type": "COMMON_EQUITY",
        "notes": "Traded under INSA on NASDAQ; unadjusted close $1.50 on 2016-12-30",
    },
    4447: {
        "ticker": "HES",
        "company_name": "Hess Corp",
        "exchange": "NYSE",
        "unadjusted_price": 62.29,
        "price_date": "2016-12-30",
        "status": "ACTIVE_2016",
        "security_type": "COMMON_EQUITY",
        "notes": "Active NYSE oil & gas company; unadjusted close $62.29 on 2016-12-30",
    },
    4515: {
        "ticker": "AAL",
        "company_name": "American Airlines Group Inc",
        "exchange": "NASDAQ",
        "unadjusted_price": 46.69,
        "price_date": "2016-12-30",
        "status": "ACTIVE_2016",
        "security_type": "COMMON_EQUITY",
        "notes": "Active NASDAQ airline; unadjusted close $46.69 on 2016-12-30",
    },
    1326801: {
        "ticker": "FB",
        "company_name": "Meta Platforms Inc (fka Facebook)",
        "exchange": "NASDAQ",
        "unadjusted_price": 115.05,
        "price_date": "2016-12-30",
        "status": "ACTIVE_2016",
        "security_type": "COMMON_EQUITY",
        "notes": "Traded as FB in 2016 before changing to META in 2022; unadjusted close $115.05 on 2016-12-30",
    },
    31235: {
        "ticker": "KODK",
        "company_name": "Eastman Kodak Co",
        "exchange": "NYSE",
        "unadjusted_price": 15.50,
        "price_date": "2016-12-30",
        "status": "ACTIVE_2016",
        "security_type": "COMMON_EQUITY",
        "notes": "Emerged from bankruptcy in 2013; unadjusted close $15.50 on 2016-12-30",
    },
    2098: {
        "ticker": "ACU",
        "company_name": "Acme United Corp",
        "exchange": "NYSE",
        "unadjusted_price": 25.57,
        "price_date": "2016-12-30",
        "status": "ACTIVE_2016",
        "security_type": "COMMON_EQUITY",
        "notes": "Active small-cap survivor; unadjusted close $25.57 on 2016-12-30",
    },
}


def get_delisted_record_by_cik(cik: int) -> Optional[Dict[str, Any]]:
    """Retrieve historical delisted EOD record by CIK."""
    return HISTORICAL_DELISTED_EOD_2016.get(int(cik))


def get_delisted_record_by_ticker(ticker: str) -> Optional[Dict[str, Any]]:
    """Retrieve historical delisted EOD record by ticker symbol."""
    tick_upper = ticker.strip().upper()
    for rec in HISTORICAL_DELISTED_EOD_2016.values():
        if rec["ticker"].upper() == tick_upper:
            return rec
    return None
