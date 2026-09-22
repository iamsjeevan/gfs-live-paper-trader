"""Unit tests for the SQLite database schema and repository layers."""

import sqlite3
import pytest
from pathlib import Path

from database.connection import get_connection
from database.schema import init_db
from database.repositories.companies import CompanyRepository
from database.repositories.filings import FilingRepository
from database.repositories.fundamentals import FundamentalRepository
from database.repositories.prices import PriceRepository
from database.repositories.downloads import DownloadStatusRepository


@pytest.fixture
def memory_db():
    """Create an in-memory SQLite database initialized with schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Apply schema
    from database.schema import SCHEMA_DDL
    conn.executescript(SCHEMA_DDL)
    conn.commit()
    yield conn
    conn.close()


def test_company_repository(memory_db):
    repo = CompanyRepository(memory_db)

    # Upsert single company
    repo.upsert_company({
        "cik": 1000,
        "ticker": "TEST",
        "company_name": "Test Micro Cap Inc.",
        "exchange": "Nasdaq",
        "sic": 7372,
    })
    memory_db.commit()

    comp = repo.get_by_cik(1000)
    assert comp is not None
    assert comp["ticker"] == "TEST"
    assert comp["company_name"] == "Test Micro Cap Inc."
    assert comp["sic"] == 7372

    # Query by ticker case-insensitive
    comp_t = repo.get_by_ticker("test")
    assert comp_t is not None
    assert comp_t["cik"] == 1000

    # Batch upsert
    batch = [
        {"cik": 2000, "ticker": "AAA", "company_name": "Triple A Corp"},
        {"cik": 3000, "ticker": "BBB", "company_name": "Triple B Corp"},
    ]
    inserted = repo.upsert_companies_batch(batch)
    memory_db.commit()
    assert inserted == 2
    assert repo.count() == 3


def test_filings_repository_point_in_time(memory_db):
    comp_repo = CompanyRepository(memory_db)
    comp_repo.upsert_company({"cik": 1000, "company_name": "Test Inc"})

    filing_repo = FilingRepository(memory_db)
    filings = [
        {
            "accession_number": "0001-16-01",
            "cik": 1000,
            "form": "10-K",
            "filing_date": "2016-03-15",
            "report_date": "2015-12-31",
            "fiscal_year": 2015,
            "fiscal_period": "FY",
        },
        {
            "accession_number": "0001-17-01",
            "cik": 1000,
            "form": "10-K",
            "filing_date": "2017-02-28",  # Filed in 2017!
            "report_date": "2016-12-31",
            "fiscal_year": 2016,
            "fiscal_period": "FY",
        },
    ]
    filing_repo.upsert_filings_batch(filings)
    memory_db.commit()

    # Query point-in-time as of 2016-12-31: should ONLY return the 2016-03-15 filing!
    pit_filings = filing_repo.get_by_cik(1000, max_filing_date="2016-12-31")
    assert len(pit_filings) == 1
    assert pit_filings[0]["accession_number"] == "0001-16-01"
    assert pit_filings[0]["filing_date"] <= "2016-12-31"

    # Query all filings as of 2017-12-31: should return both
    all_filings = filing_repo.get_by_cik(1000, max_filing_date="2017-12-31")
    assert len(all_filings) == 2


def test_fundamental_repository_point_in_time(memory_db):
    comp_repo = CompanyRepository(memory_db)
    comp_repo.upsert_company({"cik": 1000, "company_name": "Test Inc"})

    fund_repo = FundamentalRepository(memory_db)

    records = [
        {
            "cik": 1000,
            "ticker": "TEST",
            "filing_date": "2016-03-15",
            "report_date": "2015-12-31",
            "fiscal_year": 2015,
            "fiscal_period": "FY",
            "form": "10-K",
            "revenue": 100_000_000,
            "net_income": 10_000_000,
            "roe": 0.15,
        },
        {
            "cik": 1000,
            "ticker": "TEST",
            "filing_date": "2017-02-20",  # Filed in 2017!
            "report_date": "2016-12-31",
            "fiscal_year": 2016,
            "fiscal_period": "FY",
            "form": "10-K",
            "revenue": 150_000_000,
            "net_income": 20_000_000,
            "roe": 0.25,
        },
    ]
    fund_repo.upsert_fundamentals_batch(records)
    memory_db.commit()

    # Point-in-time check on 2016-12-31:
    latest = fund_repo.get_latest_fundamental(1000, max_filing_date="2016-12-31")
    assert latest is not None
    assert latest["filing_date"] == "2016-03-15"
    assert latest["revenue"] == 100_000_000
    assert latest["fiscal_year"] == 2015

    # As of 2017-03-01, the 2017 filing is available
    latest_2017 = fund_repo.get_latest_fundamental(1000, max_filing_date="2017-03-01")
    assert latest_2017 is not None
    assert latest_2017["filing_date"] == "2017-02-20"
    assert latest_2017["revenue"] == 150_000_000


def test_price_repository(memory_db):
    price_repo = PriceRepository(memory_db)
    prices = [
        {"ticker": "TEST", "date": "2016-12-28", "close": 10.0, "adjusted_close": 10.0, "volume": 50000},
        {"ticker": "TEST", "date": "2016-12-29", "close": 10.5, "adjusted_close": 10.5, "volume": 60000},
        {"ticker": "TEST", "date": "2016-12-30", "close": 11.0, "adjusted_close": 11.0, "volume": 55000},
    ]
    price_repo.upsert_prices_batch(prices)
    memory_db.commit()

    # Get price on weekend 2016-12-31 (Saturday) -> should return Friday 2016-12-30 price of 11.0!
    weekend_price = price_repo.get_price_on_or_before("TEST", "2016-12-31")
    assert weekend_price is not None
    assert weekend_price["date"] == "2016-12-30"
    assert weekend_price["close"] == 11.0


def test_download_status_repository(memory_db):
    repo = DownloadStatusRepository(memory_db)

    # Record start
    repo.record_start("sec_companyfacts", "1000", source_url="https://sec.gov/1000")
    memory_db.commit()

    status = repo.get_status("sec_companyfacts", "1000")
    assert status["status"] == "IN_PROGRESS"
    assert status["attempts"] == 1

    # Record success
    repo.record_success("sec_companyfacts", "1000", http_status=200, file_path="data/raw/1000.json")
    memory_db.commit()

    assert repo.is_completed("sec_companyfacts", "1000") is True
    assert "1000" in repo.get_completed_entity_ids("sec_companyfacts")

    # Record failure for another
    repo.record_failure("sec_companyfacts", "2000", error_message="Not found", http_status=404)
    memory_db.commit()

    assert repo.is_completed("sec_companyfacts", "2000") is False
    st_404 = repo.get_status("sec_companyfacts", "2000")
    assert st_404["status"] == "NOT_FOUND"
