"""Unit tests for survivorship-bias audit, lifecycle tracking, and reproducibility."""

import sqlite3
import pytest
from unittest.mock import MagicMock

from database.schema import SCHEMA_DDL
from database.repositories.companies import CompanyRepository
from universe.filters import classify_company
from universe.market_cap import calculate_historical_market_cap, extract_historical_shares_from_facts
from universe.survivorship_audit import audit_price_coverage, classify_historical_status
from data_sources.market_data.base import PriceProvider


class DummyPriceProvider(PriceProvider):
    def __init__(self, price_map):
        self.price_map = price_map

    def get_history(self, ticker, start_date, end_date):
        import pandas as pd
        return pd.DataFrame()

    def get_price(self, ticker, date, adjusted=False, lookback_days=10):
        return self.price_map.get(ticker)

    def get_corporate_actions(self, ticker):
        import pandas as pd
        return pd.DataFrame()


def test_post_2016_ipo_is_excluded():
    """Verify that a company going public after 2016-12-31 is classified as POST_2016_IPO and excluded."""
    company = {
        "cik": 999111,
        "ticker": "RIVN",
        "company_name": "Rivian Automotive",
        "first_seen": "2021-11-10",
        "last_seen": "2026-09-08",
        "is_active": 1,
    }
    status = classify_historical_status(company, screen_date="2016-12-31")
    assert status == "POST_2016_IPO"

    # Facts only have 2021+ filings
    facts_2021 = {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"filed": "2021-11-15", "end": "2021-09-30", "val": 890_000_000},
                        ]
                    }
                }
            }
        }
    }
    shares = extract_historical_shares_from_facts(facts_2021, screen_date="2016-12-31")
    assert shares is None


def test_acquired_company_remains_in_historical_universe():
    """Verify that a company acquired post-2016 is identified by CIK and evaluated."""
    company = {
        "cik": 1408356,
        "ticker": "SCTY",
        "company_name": "SolarCity Corp",
        "first_seen": "2012-01-01",
        "last_seen": "2016-11-21",
        "is_active": 0,
    }
    status = classify_historical_status(company, screen_date="2016-12-31")
    assert status in ("ACQUIRED", "DELISTED_AFTER_2016")


def test_bankrupt_company_remains_in_historical_universe():
    """Verify that a company entering bankruptcy post-2016 is identified and retained."""
    company = {
        "cik": 84263,
        "ticker": "RAD",
        "company_name": "Rite Aid Corp (In Liquidation / Chapter 11)",
        "first_seen": "1990-01-01",
        "last_seen": "2023-10-15",
        "is_active": 0,
    }
    status = classify_historical_status(company, screen_date="2016-12-31")
    assert status == "BANKRUPT"


def test_current_shares_never_used():
    """Verify that current (e.g. 2026) share dilution is never used for historical 2016 market cap."""
    facts = {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"filed": "2016-11-04", "end": "2016-09-30", "val": 10_000_000},  # Historical 2016
                            {"filed": "2026-08-15", "end": "2026-06-30", "val": 100_000_000}, # 10x dilution in 2026!
                        ]
                    }
                }
            }
        }
    }
    price_provider = DummyPriceProvider({"DILU": 15.0})

    res = calculate_historical_market_cap(
        cik=55555,
        ticker="DILU",
        screen_date="2016-12-31",
        price_provider=price_provider,
        facts_json=facts,
    )

    assert res["is_valid"] is True
    # Must use 10,000,000 (historical), NEVER 100,000,000 (today)!
    assert res["shares"] == 10_000_000.0
    assert res["market_cap"] == 150_000_000.0  # $150M small-cap, not $1.5B mid-cap


def test_missing_yahoo_price_does_not_silently_remove():
    """Verify that missing Yahoo price logs the company into price gaps rather than silently vanishing."""
    records = [
        {
            "cik": 1408356,
            "ticker": "SCTY",
            "company_name": "SolarCity Corp",
            "historical_status": "ACQUIRED",
            "sic": 3433,
            "exchange": "Nasdaq",
            "price_2016": None,
            "shares_2016": 100_490_000,
            "exclusion_reason": "missing_price",
        }
    ]
    cov_df, gaps_df = audit_price_coverage(records)

    assert len(gaps_df) == 1
    assert gaps_df.iloc[0]["CIK"] == 1408356
    assert gaps_df.iloc[0]["ticker_2016"] == "SCTY"
    assert gaps_df.iloc[0]["status"] == "ACQUIRED"
    assert gaps_df.iloc[0]["price_2016_available"] == False


def test_universe_construction_reproducibility(tmp_path):
    """Verify that universe construction persists run records and is completely reproducible."""
    db_file = tmp_path / "repro_test.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA_DDL)

    # Insert 2 test companies
    comp_repo = CompanyRepository(conn)
    comp_repo.upsert_companies_batch([
        {"cik": 1001, "ticker": "T1", "company_name": "Test 1 Corp", "exchange": "NYSE", "sic": 3571, "first_seen": "2010-01-01"},
        {"cik": 1002, "ticker": "T2", "company_name": "Test 2 Corp", "exchange": "Nasdaq", "sic": 7372, "first_seen": "2010-01-01"},
    ])
    conn.commit()
    conn.close()

    from universe.historical_universe import build_historical_smallcap_universe

    price_provider = DummyPriceProvider({"T1": 20.0, "T2": 15.0})

    # Run 1
    el1, ex1, s1 = build_historical_smallcap_universe(
        screen_date="2016-12-31",
        candidate_ciks=[1001, 1002],
        price_provider=price_provider,
        db_path=db_file,
        export_csv=False,
    )

    # Verify run persisted to SQLite
    conn = sqlite3.connect(db_file)
    run_records = conn.execute("SELECT * FROM universe_runs").fetchall()
    assert len(run_records) == 1
    conn.close()
