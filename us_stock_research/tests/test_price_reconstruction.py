"""Tests for Milestone 3: Historical Price Reconstruction and Delisted Resolution."""

import pytest
import sqlite3
import pandas as pd

from database.schema import init_db
from database.repositories.prices import PriceRepository
from database.repositories.historical_listings import HistoricalListingRepository
from data_sources.market_data.delisted_provider import DelistedHistoricalPriceProvider
from data_sources.market_data.resolver import HistoricalPriceResolver
from universe.security_type import classify_security_type
from universe.corporate_actions import audit_shares_split_timing, normalize_historical_market_cap
from universe.market_cap import calculate_historical_market_cap


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_research.db"
    init_db(db_file)
    return db_file


def test_security_type_classification():
    """Verify security classification isolates common equity from preferred, debt, REIT, and fund."""
    assert classify_security_type(ticker="AAPL", company_name="Apple Inc", sic=3571) == "COMMON_EQUITY"
    assert classify_security_type(ticker="WRB-PH", company_name="W.R. Berkley Corp", sic=6331) == "PREFERRED"
    assert classify_security_type(ticker="FRT-PC", company_name="Federal Realty", sic=6798) == "PREFERRED"
    assert classify_security_type(ticker="ALX", company_name="Alexanders Inc", sic=6798) == "REIT"
    assert classify_security_type(ticker="VBF", company_name="Invesco Bond Fund", sic=6722) == "ETF/FUND"
    assert classify_security_type(ticker="AKZOY", company_name="Akzo Nobel N.V.", forms=["20-F"]) == "ADR"
    assert classify_security_type(ticker="ACET", company_name="Aceto Corp", sic=5122) == "COMMON_EQUITY"
    assert classify_security_type(ticker="RAD", company_name="Rite Aid Corp", sic=5912) == "COMMON_EQUITY"


def test_historical_listings_repository(temp_db):
    """Verify historical_listings table stores and retrieves records with confidence."""
    conn = sqlite3.connect(temp_db)
    repo = HistoricalListingRepository(conn)

    record = {
        "cik": 84263,
        "ticker": "RAD",
        "company_name": "Rite Aid Corp",
        "exchange": "NYSE",
        "security_type": "COMMON_EQUITY",
        "listing_start_date": "1994-01-01",
        "listing_end_date": "2023-10-15",
        "source": "sec_filings",
        "confidence": 1.0,
    }
    repo.upsert_listing(record)
    conn.commit()

    listings = repo.get_by_cik(84263)
    assert len(listings) == 1
    assert listings[0]["ticker"] == "RAD"
    assert listings[0]["security_type"] == "COMMON_EQUITY"

    conn.close()


def test_delisted_price_provider_bankrupt_company(temp_db):
    """Verify delisted price provider recovers unadjusted price for bankrupt company (RAD & ACET)."""
    provider = DelistedHistoricalPriceProvider(db_path=temp_db)

    # RAD (Rite Aid)
    price_rad = provider.get_price(ticker="RAD", date="2016-12-31", cik=84263)
    assert price_rad == 8.24

    # ACET (Aceto Corp)
    price_acet = provider.get_price(ticker="ACET", date="2016-12-31", cik=2034)
    assert price_acet == 21.91


def test_delisted_price_provider_acquired_company(temp_db):
    """Verify delisted provider recovers price for acquired companies (LNKD & TWNK & SCTY)."""
    provider = DelistedHistoricalPriceProvider(db_path=temp_db)

    price_lnkd = provider.get_price(ticker="LNKD", date="2016-12-31", cik=1271024, lookback_days=45)
    assert price_lnkd == 195.96

    price_scty = provider.get_price(ticker="SCTY", date="2016-12-31", cik=1408356, lookback_days=45)
    assert price_scty == 20.34

    price_twnk = provider.get_price(ticker="TWNK", date="2016-12-31", cik=1644406)
    assert price_twnk == 13.10


def test_historical_price_resolver_fallback_chain(temp_db):
    """Verify resolver queries providers in priority order and records full provenance."""
    resolver = HistoricalPriceResolver(db_path=temp_db)

    # 1. Delisted stock RAD
    res_rad = resolver.resolve_price(cik=84263, ticker="RAD", date="2016-12-31")
    assert res_rad["is_valid"] is True
    assert res_rad["price"] == 8.24
    assert res_rad["provider"] == "delisted_historical_archive"
    assert res_rad["adjustment_type"] == "UNADJUSTED_CLOSE"

    # 2. Acquired stock LNKD
    res_lnkd = resolver.resolve_price(cik=1271024, ticker="LNKD", date="2016-12-31", max_lookback_days=45)
    assert res_lnkd["is_valid"] is True
    assert res_lnkd["price"] == 195.96


def test_corporate_actions_split_timing_audit():
    """Verify split occurring between shares filing date and screen date adjusts shares."""
    splits_data = pd.DataFrame([
        {"date": "2016-06-15", "ratio": 2.0},  # Before Q3 10-Q filing
        {"date": "2016-12-15", "ratio": 3.0},  # After Q3 10-Q filing, before screen date
    ])

    # If shares filed on 2016-11-04, June split is already in the filing, but Dec split is NOT
    factor, flag = audit_shares_split_timing(
        shares_filing_date="2016-11-04",
        screen_date="2016-12-31",
        splits_df=splits_data,
    )
    assert factor == 3.0
    assert "INTERVENING_SPLIT" in flag

    # Market cap normalization
    norm = normalize_historical_market_cap(
        unadjusted_price=10.0,
        unadjusted_shares=5_000_000,
        shares_filing_date="2016-11-04",
        screen_date="2016-12-31",
        splits_df=splits_data,
    )
    assert norm["effective_shares"] == 15_000_000
    assert norm["market_cap"] == 150_000_000.0


def test_unadjusted_vs_adjusted_close_distinction(temp_db):
    """Verify PriceRepository preserves both raw close and adjusted close without confusion."""
    conn = sqlite3.connect(temp_db)
    repo = PriceRepository(conn)

    # Insert test row where stock split occurred years later: unadjusted=50.0, adjusted=12.50
    repo.upsert_prices_batch([{
        "ticker": "TESTSPLIT",
        "date": "2016-12-30",
        "cik": 999999,
        "close": 50.0,
        "adjusted_close": 12.5,
        "provider": "test",
        "adjustment_type": "UNADJUSTED_CLOSE",
    }])
    conn.commit()

    # Query unadjusted (for historical market cap)
    row = repo.get_price_on_or_before("TESTSPLIT", "2016-12-31")
    assert row["close"] == 50.0
    assert row["adjusted_close"] == 12.50
    conn.close()
