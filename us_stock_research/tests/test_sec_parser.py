"""Unit tests for the SEC Company Facts parser."""

import pytest
from data_sources.sec.parser import parse_company_facts


@pytest.fixture
def sample_company_facts():
    """Synthetic SEC CompanyFacts JSON mirroring real SEC EDGAR structure."""
    return {
        "cik": 99999,
        "entityName": "Small Cap Star Inc.",
        "facts": {
            "dei": {
                "CommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "end": "2015-12-31",
                                "val": 10000000,
                                "fy": 2015,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2016-03-10",
                                "accn": "000099999-16-0001",
                            }
                        ]
                    }
                }
            },
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "end": "2015-12-31",
                                "val": 200000000,
                                "fy": 2015,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2016-03-10",
                                "accn": "000099999-16-0001",
                            }
                        ]
                    }
                },
                "GrossProfit": {
                    "units": {
                        "USD": [
                            {
                                "end": "2015-12-31",
                                "val": 80000000,
                                "fy": 2015,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2016-03-10",
                                "accn": "000099999-16-0001",
                            }
                        ]
                    }
                },
                "OperatingIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "end": "2015-12-31",
                                "val": 30000000,
                                "fy": 2015,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2016-03-10",
                                "accn": "000099999-16-0001",
                            }
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "end": "2015-12-31",
                                "val": 20000000,
                                "fy": 2015,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2016-03-10",
                                "accn": "000099999-16-0001",
                            }
                        ]
                    }
                },
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            {
                                "end": "2015-12-31",
                                "val": 100000000,
                                "fy": 2015,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2016-03-10",
                                "accn": "000099999-16-0001",
                            }
                        ]
                    }
                },
                "LongTermDebtNoncurrent": {
                    "units": {
                        "USD": [
                            {
                                "end": "2015-12-31",
                                "val": 20000000,
                                "fy": 2015,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2016-03-10",
                                "accn": "000099999-16-0001",
                            }
                        ]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [
                            {
                                "end": "2015-12-31",
                                "val": 35000000,
                                "fy": 2015,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2016-03-10",
                                "accn": "000099999-16-0001",
                            }
                        ]
                    }
                },
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {
                        "USD": [
                            {
                                "end": "2015-12-31",
                                "val": 5000000,
                                "fy": 2015,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2016-03-10",
                                "accn": "000099999-16-0001",
                            }
                        ]
                    }
                },
            },
        },
    }


def test_parse_company_facts(sample_company_facts):
    records = parse_company_facts(sample_company_facts, ticker="STAR", annual_only=True)
    assert len(records) == 1

    rec = records[0]
    assert rec["cik"] == 99999
    assert rec["ticker"] == "STAR"
    assert rec["filing_date"] == "2016-03-10"
    assert rec["report_date"] == "2015-12-31"
    assert rec["fiscal_year"] == 2015

    # Values
    assert rec["revenue"] == 200000000.0
    assert rec["net_income"] == 20000000.0
    assert rec["operating_income"] == 30000000.0
    assert rec["gross_profit"] == 80000000.0
    assert rec["equity"] == 100000000.0
    assert rec["debt"] == 20000000.0

    # FCF = OCF (35M) - Capex (5M) = 30M
    assert rec["operating_cash_flow"] == 35000000.0
    assert rec["capex"] == 5000000.0
    assert rec["free_cash_flow"] == 30000000.0

    # Shares
    assert rec["shares_outstanding"] == 10000000.0

    # Margins & Ratios
    assert rec["gross_margin"] == pytest.approx(0.40)      # 80M / 200M
    assert rec["operating_margin"] == pytest.approx(0.15)  # 30M / 200M
    assert rec["net_margin"] == pytest.approx(0.10)        # 20M / 200M
    assert rec["fcf_margin"] == pytest.approx(0.15)        # 30M / 200M
    assert rec["roe"] == pytest.approx(0.20)               # 20M / 100M
    assert rec["debt_equity"] == pytest.approx(0.20)       # 20M / 100M
