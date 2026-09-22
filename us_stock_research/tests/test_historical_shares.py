"""Unit tests for historical shares outstanding extraction."""

import pytest
from universe.market_cap import extract_historical_shares_from_facts


def test_extract_historical_shares_point_in_time():
    """Verify that only shares filed on or before screen_date are returned, choosing the most recent."""
    facts = {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"filed": "2015-11-05", "end": "2015-09-30", "val": 8_000_000},
                            {"filed": "2016-03-15", "end": "2015-12-31", "val": 8_500_000},
                            {"filed": "2016-11-04", "end": "2016-09-30", "val": 9_000_000},  # Latest on/before 2016-12-31
                            {"filed": "2017-02-28", "end": "2016-12-31", "val": 9_500_000},  # Filed in 2017!
                            {"filed": "2018-03-01", "end": "2017-12-31", "val": 10_000_000},
                        ]
                    }
                }
            }
        }
    }

    # As of 2016-12-31: must return 9,000,000 filed on 2016-11-04
    res_2016 = extract_historical_shares_from_facts(facts, screen_date="2016-12-31")
    assert res_2016 is not None
    shares, filed, report, concept = res_2016
    assert shares == 9_000_000.0
    assert filed == "2016-11-04"
    assert filed <= "2016-12-31"

    # As of 2017-12-31: must return 9,500,000 filed on 2017-02-28
    res_2017 = extract_historical_shares_from_facts(facts, screen_date="2017-12-31")
    assert res_2017 is not None
    shares_17, filed_17, report_17, _ = res_2017
    assert shares_17 == 9_500_000.0
    assert filed_17 == "2017-02-28"

    # As of 2014-12-31 (before any facts): must return None
    res_2014 = extract_historical_shares_from_facts(facts, screen_date="2014-12-31")
    assert res_2014 is None


def test_extract_historical_shares_empty_or_malformed():
    """Verify safe handling of empty or missing facts."""
    assert extract_historical_shares_from_facts({}, "2016-12-31") is None
    assert extract_historical_shares_from_facts({"facts": {}}, "2016-12-31") is None
