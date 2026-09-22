"""Unit tests for historical universe filters and company classification."""

import pytest
from universe.filters import (
    is_financial_sector,
    is_valid_exchange,
    is_in_market_cap_range,
    classify_company,
)


def test_is_financial_sector():
    # Financial SIC codes (6000 - 6999)
    assert is_financial_sector(6021) is True   # National Commercial Banks
    assert is_financial_sector(6311) is True   # Life Insurance
    assert is_financial_sector(6770) is True   # Blank Checks / SPACs
    assert is_financial_sector(6798) is True   # Real Estate Investment Trusts (REITs)
    assert is_financial_sector("6211") is True # String format

    # Non-financial SIC codes
    assert is_financial_sector(7372) is False  # Prepackaged Software
    assert is_financial_sector(3571) is False  # Electronic Computers
    assert is_financial_sector(2834) is False  # Pharmaceutical Preparations
    assert is_financial_sector(None) is False


def test_is_valid_exchange():
    assert is_valid_exchange("Nasdaq") is True
    assert is_valid_exchange("NASDAQ") is True
    assert is_valid_exchange("NYSE") is True
    assert is_valid_exchange("AMEX") is True
    assert is_valid_exchange("NYSE American") is True
    assert is_valid_exchange("NYSE Arca") is True

    # Invalid / OTC / Foreign / None
    assert is_valid_exchange("OTC") is False
    assert is_valid_exchange("Pink Sheets") is False
    assert is_valid_exchange("LSE") is False
    assert is_valid_exchange(None) is False
    assert is_valid_exchange("") is False


def test_is_in_market_cap_range():
    min_c = 50_000_000.0
    max_c = 1_000_000_000.0

    assert is_in_market_cap_range(100_000_000, min_c, max_c) is True
    assert is_in_market_cap_range(50_000_000, min_c, max_c) is True
    assert is_in_market_cap_range(1_000_000_000, min_c, max_c) is True

    # Out of bounds
    assert is_in_market_cap_range(20_000_000, min_c, max_c) is False   # Too small
    assert is_in_market_cap_range(2_000_000_000, min_c, max_c) is False # Too large
    assert is_in_market_cap_range(None, min_c, max_c) is False


def test_classify_company_eligible():
    mcap_res = {
        "is_valid": True,
        "market_cap": 250_000_000.0,
        "price": 25.0,
        "shares": 10_000_000.0,
        "exclusion_reason": None,
    }
    status, reason = classify_company(
        market_cap_result=mcap_res,
        sic=7372,
        exchange="Nasdaq",
        exclude_financials=True,
        min_market_cap=50_000_000,
        max_market_cap=1_000_000_000,
    )
    assert status == "eligible"
    assert reason is None


def test_classify_company_financial_sector():
    mcap_res = {
        "is_valid": True,
        "market_cap": 250_000_000.0,
        "price": 25.0,
        "shares": 10_000_000.0,
    }
    status, reason = classify_company(
        market_cap_result=mcap_res,
        sic=6021,  # Commercial Bank
        exchange="Nasdaq",
        exclude_financials=True,
    )
    assert status == "financial_sector"
    assert "Financial sector" in reason


def test_classify_company_not_small_cap():
    # Large Cap ($5B)
    mcap_large = {"is_valid": True, "market_cap": 5_000_000_000.0}
    status_l, reason_l = classify_company(
        market_cap_result=mcap_large,
        sic=7372,
        exchange="NYSE",
        min_market_cap=50_000_000,
        max_market_cap=1_000_000_000,
    )
    assert status_l == "not_small_cap"
    assert "above maximum" in reason_l

    # Micro Cap ($10M)
    mcap_micro = {"is_valid": True, "market_cap": 10_000_000.0}
    status_m, reason_m = classify_company(
        market_cap_result=mcap_micro,
        sic=7372,
        exchange="NYSE",
        min_market_cap=50_000_000,
        max_market_cap=1_000_000_000,
    )
    assert status_m == "not_small_cap"
    assert "below minimum" in reason_m


def test_classify_company_missing_data():
    # Missing price
    mcap_no_price = {"is_valid": False, "exclusion_reason": "missing_price"}
    status_p, reason_p = classify_company(mcap_no_price, sic=7372, exchange="Nasdaq")
    assert status_p == "missing_price"

    # Missing shares
    mcap_no_shares = {"is_valid": False, "exclusion_reason": "missing_shares"}
    status_s, reason_s = classify_company(mcap_no_shares, sic=7372, exchange="Nasdaq")
    assert status_s == "missing_shares"
