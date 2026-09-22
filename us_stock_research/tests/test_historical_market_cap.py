"""Unit tests for historical market capitalization calculation and lookahead protection."""

import pytest
from unittest.mock import MagicMock

from universe.market_cap import calculate_historical_market_cap
from data_sources.market_data.base import PriceProvider


class MockPriceProvider(PriceProvider):
    def __init__(self, prices_dict):
        self.prices = prices_dict

    def get_history(self, ticker, start_date, end_date):
        import pandas as pd
        return pd.DataFrame()

    def get_price(self, ticker, date, adjusted=False, lookback_days=10):
        return self.prices.get(ticker)

    def get_corporate_actions(self, ticker):
        import pandas as pd
        return pd.DataFrame()


def test_market_cap_calculation_success():
    """Verify that market cap = unadjusted price * historical shares."""
    facts_json = {
        "cik": 12345,
        "entityName": "Small Cap Inc",
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"filed": "2016-11-05", "end": "2016-09-30", "val": 10_000_000},
                        ]
                    }
                }
            }
        },
    }
    price_provider = MockPriceProvider({"SCAP": 25.0})

    res = calculate_historical_market_cap(
        cik=12345,
        ticker="SCAP",
        screen_date="2016-12-31",
        price_provider=price_provider,
        facts_json=facts_json,
    )

    assert res["is_valid"] is True
    assert res["shares"] == 10_000_000.0
    assert res["price"] == 25.0
    assert res["market_cap"] == 250_000_000.0  # $250M
    assert res["exclusion_reason"] is None


def test_market_cap_strictly_rejects_2017_shares_lookahead():
    """CRITICAL TEST: Verify that a share fact filed in 2017 cannot be used for a 2016-12-31 screen."""
    facts_json = {
        "cik": 99999,
        "entityName": "Post 2016 Filer Inc",
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            # Only shares filed in 2017!
                            {"filed": "2017-02-15", "end": "2016-12-31", "val": 50_000_000},
                        ]
                    }
                }
            }
        },
    }
    price_provider = MockPriceProvider({"POST": 10.0})

    res = calculate_historical_market_cap(
        cik=99999,
        ticker="POST",
        screen_date="2016-12-31",
        price_provider=price_provider,
        facts_json=facts_json,
    )

    # Must be marked invalid due to missing historical shares available on or before 2016-12-31!
    assert res["is_valid"] is False
    assert res["market_cap"] is None
    assert res["exclusion_reason"] == "missing_shares"


def test_market_cap_missing_price():
    """Verify that if historical price is unavailable, company is flagged rather than silently approximated."""
    facts_json = {
        "cik": 11111,
        "entityName": "No Price Corp",
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"filed": "2016-11-01", "end": "2016-09-30", "val": 5_000_000},
                        ]
                    }
                }
            }
        },
    }
    # Price provider returns None (e.g. delisted or no price)
    price_provider = MockPriceProvider({})

    res = calculate_historical_market_cap(
        cik=11111,
        ticker="NOPRICE",
        screen_date="2016-12-31",
        price_provider=price_provider,
        facts_json=facts_json,
    )

    assert res["is_valid"] is False
    assert res["exclusion_reason"] == "missing_price"
