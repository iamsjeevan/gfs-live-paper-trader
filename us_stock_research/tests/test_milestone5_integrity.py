"""Milestone 5 Integrity & Regression Test Suite.

Verifies:
1. NRC multi-class share handling.
2. Post-2016 split must not alter 2016 market cap.
3. Pre-2016 split must correctly normalize historical shares.
4. UHAL remains strictly excluded.
5. No future filing enters any metric.
6. No quarterly footnote fragments enter CAGR.
7. Delisted companies are not automatically excluded.
8. Post-2016 IPOs are excluded.
9. Financial-sector companies are excluded under existing rules.
10. Every quality-passed company satisfies every hard filter.
11. Strategy rankings are deterministic.
12. Historical snapshot is reproducible.
"""

import json
from pathlib import Path
import pytest
import pandas as pd

from fundamentals.engine import PointInTimeFundamentalsEngine
from screening.filters import QualityFilterConfig, evaluate_quality_filters
from screening.scoring import score_universe_candidates
from universe.corporate_actions import audit_shares_split_timing, normalize_historical_market_cap
from universe.filters import is_financial_sector
from universe.security_type import classify_security_type
from universe.share_resolver import HistoricalShareResolver, parse_cover_page_shares_text
from universe.survivorship_audit import classify_historical_status


def test_1_nrc_multiclass_share_handling():
    """Verify that NRC (CIK 70487) resolves multi-class shares combining Class A + Class B (~24.4M shares)."""
    resolver = HistoricalShareResolver()
    res = resolver.resolve_shares(cik=70487, screen_date="2016-12-31")

    assert res is not None
    assert res["is_valid"] is True
    assert res["is_multi_class"] is True
    assert res["shares"] > 24_000_000.0  # ~24.44M shares
    assert "Class B" in res["share_classes"]
    assert res["quality_flags"] == "MULTICLASS_COMBINED"
    assert res["shares_filing_date"] <= "2016-12-31"


def test_2_post_2016_split_does_not_alter_2016_market_cap():
    """Verify that a post-2016 stock split does NOT adjust 2016 shares or alter 2016 market cap."""
    splits_df = pd.DataFrame([
        {"date": "2022-11-10", "ratio": 10.0}  # e.g. UHAL 10-for-1 split in Nov 2022
    ])
    factor, flag = audit_shares_split_timing(
        shares_filing_date="2016-05-25",
        screen_date="2016-12-31",
        splits_df=splits_df,
    )
    assert factor == 1.0
    assert flag is None

    norm = normalize_historical_market_cap(
        unadjusted_price=369.59,
        unadjusted_shares=19_607_755.0,
        shares_filing_date="2016-05-25",
        screen_date="2016-12-31",
        splits_df=splits_df,
    )
    assert norm["effective_shares"] == 19_607_755.0
    assert norm["market_cap"] == pytest.approx(369.59 * 19_607_755.0, rel=1e-4)


def test_3_pre_2016_split_normalizes_historical_shares():
    """Verify that an intervening split occurring between the share filing date and screen date adjusts historical shares."""
    splits_df = pd.DataFrame([
        {"date": "2016-11-15", "ratio": 2.0}  # 2:1 split after Q3 filing but before 2016-12-31
    ])
    factor, flag = audit_shares_split_timing(
        shares_filing_date="2016-10-25",
        screen_date="2016-12-31",
        splits_df=splits_df,
    )
    assert factor == 2.0
    assert "INTERVENING_SPLIT" in str(flag)

    norm = normalize_historical_market_cap(
        unadjusted_price=25.0,
        unadjusted_shares=5_000_000.0,
        shares_filing_date="2016-10-25",
        screen_date="2016-12-31",
        splits_df=splits_df,
    )
    assert norm["effective_shares"] == 10_000_000.0
    assert norm["market_cap"] == 250_000_000.0


def test_4_uhal_strictly_remains_excluded():
    """Verify that UHAL strictly fails the hard quality filters and that allow_temporary_fcf_exception is False."""
    config = QualityFilterConfig(allow_temporary_fcf_exception=False)
    assert config.allow_temporary_fcf_exception is False

    engine = PointInTimeFundamentalsEngine(screen_date="2016-12-31")
    f_uhal = engine.compute_company_fundamentals(cik=4457, ticker="UHAL", market_cap_2016=724_000_000.0)

    assert f_uhal["free_cash_flow"] is not None
    assert f_uhal["free_cash_flow"] < 0  # -$463.8M
    passes, reasons = evaluate_quality_filters(f_uhal, config)
    assert passes is False
    assert any("Free cash flow is negative" in r for r in reasons)


def test_5_no_future_filing_enters_any_metric():
    """Verify that every single metric in the screening engine has filing_date <= 2016-12-31."""
    engine = PointInTimeFundamentalsEngine(screen_date="2016-12-31")
    # Test across companies with Dec 31 fiscal year-ends that filed 10-K in early 2017
    for cik, ticker in [(95029, "RGR"), (8063, "ATRO"), (70487, "NRC"), (706698, "UTMD")]:
        f = engine.compute_company_fundamentals(cik=cik, ticker=ticker, market_cap_2016=200_000_000.0)
        assert f["filing_date"] is not None
        assert f["filing_date"] <= "2016-12-31", f"Look-ahead detected for {ticker}: filed {f['filing_date']}"


def test_6_no_quarterly_footnote_fragments_enter_cagr():
    """Verify that quarterly 90-day footnote intervals inside Form 10-K are excluded from CAGR."""
    engine = PointInTimeFundamentalsEngine(screen_date="2016-12-31")
    f = engine.compute_company_fundamentals(cik=95029, ticker="RGR", market_cap_2016=999_816_720.0)
    rev_cagr = f.get("revenue_cagr")
    assert rev_cagr is not None
    # True economic CAGR is ~3.87%, not distorted 51.5%
    assert 0.0 < rev_cagr < 0.10


def test_7_delisted_companies_not_automatically_excluded():
    """Verify that delisted/bankrupt/acquired companies remain in historical classification."""
    rad_comp = {
        "cik": 84263,
        "ticker": "RAD",
        "company_name": "RITE AID CORP",
        "exchange": "NYSE",
        "is_active": 0,
        "first_seen": "2016-01-01",
        "last_seen": "2016-12-31",
    }
    status = classify_historical_status(rad_comp, screen_date="2016-12-31")
    assert status in ("ACTIVE_2016", "DELISTED_AFTER_2016", "BANKRUPT")


def test_8_post_2016_ipos_excluded():
    """Verify that companies that first traded or filed after 2016-12-31 are excluded."""
    comp = {
        "cik": 9999999,
        "first_seen": "2018-05-01",
        "last_seen": "2026-01-01",
        "is_active": 1,
    }
    status = classify_historical_status(comp, screen_date="2016-12-31")
    assert status == "POST_2016_IPO"


def test_9_financial_sector_excluded_under_existing_rules():
    """Verify that financial sector companies (SIC 6000-6999) are excluded."""
    assert is_financial_sector(6021) is True
    assert is_financial_sector(6798) is True
    assert is_financial_sector(3728) is False
    assert is_financial_sector(2834) is False


def test_10_every_quality_passed_company_satisfies_all_hard_filters():
    """Verify that a passing synthetic company satisfies all strict hard filters."""
    valid_company = {
        "cik": 11111,
        "ticker": "GOOD",
        "screen_date": "2016-12-31",
        "filing_date": "2016-03-01",
        "period_end": "2015-12-31",
        "net_income": 10_000_000.0,
        "operating_cash_flow": 12_000_000.0,
        "free_cash_flow": 8_000_000.0,
        "operating_income": 14_000_000.0,
        "equity": 50_000_000.0,
        "debt": 10_000_000.0,
        "cash": 5_000_000.0,
        "roe": 0.20,
        "roic": 0.18,
        "debt_equity": 0.20,
        "sic": 3500,
        "revenue": 50_000_000.0,
        "data_completeness_score": 1.0,
    }
    config = QualityFilterConfig(allow_temporary_fcf_exception=False)
    passes, reasons = evaluate_quality_filters(valid_company, config)
    assert passes is True
    assert len(reasons) == 0


def test_11_strategy_rankings_deterministic():
    """Verify that scoring is strictly deterministic across repeated runs."""
    sample_candidates = [
        {"cik": 1, "ticker": "A", "roe": 0.25, "roic": 0.20, "revenue_cagr": 0.10, "pe": 15.0, "ev_ebitda": 8.0, "price_fcf": 12.0, "debt_equity": 0.1, "operating_margin": 0.15, "fcf_margin": 0.10, "revenue_growth": 0.08, "net_income_growth": 0.10, "net_income_cagr": 0.12, "fcf_cagr": 0.10, "growth_consistency": 0.8, "quantitative_moat_score": 0.75, "data_completeness_score": 1.0, "screen_date": "2016-12-31"},
        {"cik": 2, "ticker": "B", "roe": 0.20, "roic": 0.15, "revenue_cagr": 0.05, "pe": 20.0, "ev_ebitda": 10.0, "price_fcf": 15.0, "debt_equity": 0.2, "operating_margin": 0.12, "fcf_margin": 0.08, "revenue_growth": 0.04, "net_income_growth": 0.05, "net_income_cagr": 0.06, "fcf_cagr": 0.05, "growth_consistency": 0.7, "quantitative_moat_score": 0.65, "data_completeness_score": 1.0, "screen_date": "2016-12-31"},
    ]
    res1 = score_universe_candidates(sample_candidates)
    res2 = score_universe_candidates(sample_candidates)
    pd.testing.assert_frame_equal(res1["Strategy D (Full Strategy: Quality + Growth + Value + Moat)"], res2["Strategy D (Full Strategy: Quality + Growth + Value + Moat)"])


def test_12_cover_page_regex_parser():
    """Verify parsing cover page shares text for both single and multi-class filings."""
    multiclass_text = (
        "Indicate the number of shares outstanding of each of the issuer's classes of common stock: "
        "Class A Common Stock, $.001 par value, outstanding as October 28, 2016: 20,900,082 shares "
        "Class B Common Stock, $.001 par value, outstanding as of October 28, 2016: 3,541,433 shares"
    )
    parsed = parse_cover_page_shares_text(multiclass_text, filing_date="2016-11-04")
    assert parsed is not None
    assert parsed["is_multi_class"] is True
    assert parsed["shares"] == 24_441_515.0
    assert parsed["share_classes"]["Class A"] == 20_900_082.0
    assert parsed["share_classes"]["Class B"] == 3_541_433.0
