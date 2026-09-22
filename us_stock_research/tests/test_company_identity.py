"""Unit tests for company identity resolution via CIK."""

import sqlite3
import pytest
from database.schema import SCHEMA_DDL
from database.repositories.companies import CompanyRepository


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_DDL)
    conn.commit()
    yield conn
    conn.close()


def test_cik_identity_survives_ticker_change(memory_db):
    """Verify that a company is identified by CIK even when its ticker symbol changes over time."""
    repo = CompanyRepository(memory_db)

    # Initial state: company listed as 'OLDT' in 2016
    repo.upsert_company({
        "cik": 1234567,
        "ticker": "OLDT",
        "company_name": "Transforming Tech Corp",
        "exchange": "Nasdaq",
        "first_seen": "2010-01-01",
        "last_seen": "2016-12-31",
    })
    memory_db.commit()

    c1 = repo.get_by_cik(1234567)
    assert c1["ticker"] == "OLDT"

    # In 2020, ticker changes to 'NEWT'
    repo.upsert_company({
        "cik": 1234567,
        "ticker": "NEWT",
        "company_name": "Transforming Tech Corp",
        "exchange": "Nasdaq",
        "last_seen": "2026-09-08",
    })
    memory_db.commit()

    # The company is still uniquely found by CIK
    c2 = repo.get_by_cik(1234567)
    assert c2["cik"] == 1234567
    assert c2["ticker"] == "NEWT"
    # first_seen is preserved from initial record
    assert c2["first_seen"] == "2010-01-01"


def test_cik_unique_identity_for_different_companies_with_similar_names(memory_db):
    """Verify CIK prevents collision between different companies."""
    repo = CompanyRepository(memory_db)
    repo.upsert_companies_batch([
        {"cik": 111, "ticker": "ABC", "company_name": "ABC Industrial Holdings Inc"},
        {"cik": 222, "ticker": "ABCD", "company_name": "ABC Digital Technologies Inc"},
    ])
    memory_db.commit()

    assert repo.get_by_cik(111)["ticker"] == "ABC"
    assert repo.get_by_cik(222)["ticker"] == "ABCD"
    assert repo.count() == 2
