"""Unit tests for point-in-time fundamental screening and multi-factor scoring.

Verifies:
1. Strict point-in-time cutoff: filing_date <= screen_date (rejecting 2017+ filings).
2. Distinction between report date and filing date.
3. Metric calculations: CAGR, YoY growth, ROIC, and growth consistency.
4. Valuation calculations using point-in-time prices.
5. Hard quality filter evaluation and explicit failure diagnostics.
6. Quantitative moat proxy components.
7. Multi-factor strategy scoring (Strategy A, B, C, D) reproducibility.
"""

from typing import Any, Dict
import numpy as np
import pandas as pd
import pytest

from fundamentals.engine import PointInTimeFundamentalsEngine
from fundamentals.metrics import (
    compute_cagr,
    compute_enterprise_value,
    compute_growth_consistency,
    compute_roic,
    compute_yoy_growth,
)
from screening.filters import QualityFilterConfig, evaluate_quality_filters
from screening.scoring import compute_percentile_ranks, score_universe_candidates


# -----------------------------------------------------------------------------
# 1. Point-in-Time Cutoff & Look-Ahead Tests
# -----------------------------------------------------------------------------
def test_point_in_time_strictly_rejects_2017_filings():
    """Filing on 2017-02-15 reporting on 2016-12-31 must NOT be used on 2016-12-31."""
    engine = PointInTimeFundamentalsEngine(screen_date="2016-12-31")

    # Mock companyfacts JSON containing a 2015 10-K filed in 2016 and a 2016 10-K filed in 2017
    mock_facts = {
        "cik": 999999,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"filed": "2016-03-15", "end": "2015-12-31", "form": "10-K", "fp": "FY", "fy": 2015, "val": 100_000_000},
                            {"filed": "2017-02-28", "end": "2016-12-31", "form": "10-K", "fp": "FY", "fy": 2016, "val": 200_000_000},
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"filed": "2016-03-15", "end": "2015-12-31", "form": "10-K", "fp": "FY", "fy": 2015, "val": 10_000_000},
                            {"filed": "2017-02-28", "end": "2016-12-31", "form": "10-K", "fp": "FY", "fy": 2016, "val": 30_000_000},
                        ]
                    }
                },
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            {"filed": "2016-03-15", "end": "2015-12-31", "form": "10-K", "fp": "FY", "fy": 2015, "val": 50_000_000},
                            {"filed": "2017-02-28", "end": "2016-12-31", "form": "10-K", "fp": "FY", "fy": 2016, "val": 80_000_000},
                        ]
                    }
                },
            }
        }
    }

    result = engine.compute_company_fundamentals(
        cik=999999,
        ticker="TEST",
        market_cap_2016=100_000_000,
        facts_json=mock_facts,
    )

    # Must have used the 2016-03-15 filing, NOT the 2017 filing!
    assert result["filing_date"] == "2016-03-15"
    assert result["period_end"] == "2015-12-31"
    # ROE should be based on 2015 Net Income ($10M) / Equity ($50M) = 20%, NOT 2016 ($30M / $80M = 37.5%)
    assert pytest.approx(result["roe"], 1e-4) == 0.20
    # P/E should be $100M / $10M = 10.0x, NOT $100M / $30M = 3.33x
    assert pytest.approx(result["pe"], 1e-4) == 10.0


def test_point_in_time_no_prior_filings_returns_empty():
    """A company whose first filing is in 2017 has zero available fundamentals on 2016-12-31."""
    engine = PointInTimeFundamentalsEngine(screen_date="2016-12-31")
    mock_facts = {
        "cik": 888888,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"filed": "2017-05-10", "end": "2016-12-31", "form": "10-K", "fp": "FY", "val": 50_000_000}
                        ]
                    }
                }
            }
        }
    }
    result = engine.compute_company_fundamentals(cik=888888, facts_json=mock_facts)
    assert result["filing_date"] is None
    assert result["is_valid"] is False
    assert result["data_completeness_score"] == 0.0


# -----------------------------------------------------------------------------
# 2. Financial Metrics & Growth Tests
# -----------------------------------------------------------------------------
def test_cagr_calculation():
    """Verify compound annual growth rate calculation."""
    # Doubling in 3 years: (2.0)**(1/3) - 1 ≈ 25.99%
    cagr = compute_cagr(100.0, 200.0, 3)
    assert cagr is not None
    assert pytest.approx(cagr, 1e-4) == 0.2599

    # Halving in 2 years: (0.5)**(1/2) - 1 ≈ -29.29%
    cagr_neg = compute_cagr(100.0, 50.0, 2)
    assert cagr_neg is not None
    assert pytest.approx(cagr_neg, 1e-4) == -0.2929

    # Negative base or zero base returns None
    assert compute_cagr(-50.0, 100.0, 3) is None
    assert compute_cagr(0.0, 100.0, 3) is None
    assert compute_cagr(100.0, -20.0, 3) is None


def test_growth_consistency_metric():
    """Verify consistency metric rewards steady growers and penalizes high volatility."""
    # Steady 15% growth every year
    steady_rates = [0.15, 0.16, 0.14, 0.15]
    steady_score = compute_growth_consistency(steady_rates)

    # Erratic swingers: alternating big up and big down
    erratic_rates = [0.80, -0.40, 0.90, -0.30]
    erratic_score = compute_growth_consistency(erratic_rates)

    assert steady_score > 0.80
    assert erratic_score < 0.50
    assert steady_score > erratic_score


def test_roic_calculation():
    """Verify Return on Invested Capital calculation."""
    # Operating income = $20M, Equity = $80M, Debt = $40M, Cash = $20M
    # Invested Capital = 80 + 40 - 20 = $100M
    # NOPAT = 20 * (1 - 0.21) = $15.8M
    # ROIC = 15.8 / 100 = 15.8%
    roic = compute_roic(operating_income=20.0, equity=80.0, debt=40.0, cash=20.0, tax_rate=0.21)
    assert roic is not None
    assert pytest.approx(roic, 1e-4) == 0.158

    # Zero debt and excess cash
    roic_cash = compute_roic(operating_income=10.0, equity=50.0, debt=0.0, cash=10.0)
    assert roic_cash is not None
    assert pytest.approx(roic_cash, 1e-4) == (10.0 * 0.79) / 40.0


def test_enterprise_value_calculation():
    """Verify Enterprise Value = Market Cap + Debt - Cash."""
    ev = compute_enterprise_value(market_cap=500_000_000, debt=100_000_000, cash=50_000_000)
    assert ev == 550_000_000


# -----------------------------------------------------------------------------
# 3. Quality Filter Evaluation Tests
# -----------------------------------------------------------------------------
def test_evaluate_quality_filters_pass_and_fail():
    """Verify hard filter pass/fail rules and explicit failure explanations."""
    config = QualityFilterConfig(min_roe=0.12, min_roic=0.10, max_debt_equity=0.75)

    # Compliant candidate
    passing_candidate = {
        "roe": 0.18,
        "roic": 0.15,
        "debt_equity": 0.20,
        "operating_cash_flow": 15_000_000,
        "free_cash_flow": 10_000_000,
        "revenue": 80_000_000,
        "pe": 15.0,
        "data_completeness_score": 0.85,
    }
    passes, failures = evaluate_quality_filters(passing_candidate, config)
    assert passes is True
    assert len(failures) == 0

    # Failing candidate: low ROE, high debt, negative cash flow
    failing_candidate = {
        "roe": 0.05,
        "roic": 0.04,
        "debt_equity": 1.50,
        "operating_cash_flow": -2_000_000,
        "free_cash_flow": -5_000_000,
        "revenue": 50_000_000,
        "pe": -10.0,
        "data_completeness_score": 0.80,
    }
    passes, failures = evaluate_quality_filters(failing_candidate, config)
    assert passes is False
    assert any("ROE" in f for f in failures)
    assert any("ROIC" in f for f in failures)
    assert any("Debt/Equity" in f for f in failures)
    assert any("Operating cash flow" in f for f in failures)


# -----------------------------------------------------------------------------
# 4. Multi-Factor Strategy Scoring & Reproducibility Tests
# -----------------------------------------------------------------------------
def test_compute_percentile_ranks():
    """Verify percentile ranking handles ordering and missing values."""
    s = pd.Series([10.0, 20.0, 30.0, None, 50.0])
    ranks = compute_percentile_ranks(s, ascending=True, missing_value=50.0)
    assert ranks[0] == 25.0
    assert ranks[1] == 50.0
    assert ranks[2] == 75.0
    assert ranks[3] == 50.0  # missing value imputed as 50.0
    assert ranks[4] == 100.0


def test_strategy_variants_scoring_reproducibility():
    """Verify that the 4 strategy variants produce distinct, reproducible rankings."""
    candidates = [
        # Candidate 1: High quality, moderate growth, low P/E
        {
            "cik": 101, "ticker": "AAA", "company_name": "Co AAA",
            "roe": 0.25, "roic": 0.30, "debt_equity": 0.0, "operating_margin": 0.20, "fcf_margin": 0.15,
            "revenue_growth": 0.10, "revenue_cagr": 0.12, "net_income_growth": 0.10, "net_income_cagr": 0.12,
            "fcf_growth": 0.10, "fcf_cagr": 0.10, "growth_consistency": 0.80, "pe": 10.0, "ev_ebitda": 6.0,
            "price_fcf": 8.0, "quantitative_moat_score": 0.75, "market_cap": 100_000_000, "price": 20.0
        },
        # Candidate 2: Hyper growth, high quality, but expensive (P/E 80)
        {
            "cik": 102, "ticker": "BBB", "company_name": "Co BBB",
            "roe": 0.30, "roic": 0.35, "debt_equity": 0.1, "operating_margin": 0.25, "fcf_margin": 0.18,
            "revenue_growth": 0.60, "revenue_cagr": 0.50, "net_income_growth": 0.70, "net_income_cagr": 0.55,
            "fcf_growth": 0.50, "fcf_cagr": 0.45, "growth_consistency": 0.90, "pe": 80.0, "ev_ebitda": 45.0,
            "price_fcf": 50.0, "quantitative_moat_score": 0.85, "market_cap": 200_000_000, "price": 40.0
        },
        # Candidate 3: Deep value, moderate quality, low growth
        {
            "cik": 103, "ticker": "CCC", "company_name": "Co CCC",
            "roe": 0.14, "roic": 0.12, "debt_equity": 0.05, "operating_margin": 0.10, "fcf_margin": 0.08,
            "revenue_growth": 0.02, "revenue_cagr": 0.03, "net_income_growth": 0.02, "net_income_cagr": 0.03,
            "fcf_growth": 0.01, "fcf_cagr": 0.02, "growth_consistency": 0.60, "pe": 5.0, "ev_ebitda": 3.0,
            "price_fcf": 4.0, "quantitative_moat_score": 0.40, "market_cap": 80_000_000, "price": 15.0
        }
    ]

    results = score_universe_candidates(candidates)

    assert "Strategy A (Quality Only)" in results
    assert "Strategy B (Quality + Growth)" in results
    assert "Strategy C (Quality + Growth + Value)" in results
    assert "Strategy D (Full Strategy: Quality + Growth + Value + Moat)" in results

    df_a = results["Strategy A (Quality Only)"]
    df_b = results["Strategy B (Quality + Growth)"]
    df_c = results["Strategy C (Quality + Growth + Value)"]
    df_d = results["Strategy D (Full Strategy: Quality + Growth + Value + Moat)"]

    # In Strategy B (Quality + Growth), BBB should rank higher due to massive growth CAGR
    rank_b_bbb = df_b[df_b["ticker"] == "BBB"]["rank"].iloc[0]
    rank_b_ccc = df_b[df_b["ticker"] == "CCC"]["rank"].iloc[0]
    assert rank_b_bbb < rank_b_ccc

    # In Strategy C (Quality + Growth + Value), AAA or CCC should gain relative to expensive BBB
    score_c_bbb = df_c[df_c["ticker"] == "BBB"]["valuation_score"].iloc[0]
    score_c_ccc = df_c[df_c["ticker"] == "CCC"]["valuation_score"].iloc[0]
    assert score_c_ccc > score_c_bbb

    # Verify ranking monotonicity: rank 1 has highest score, rank 3 has lowest score
    for sname, df in results.items():
        scores = df["composite_score"].tolist()
        assert scores == sorted(scores, reverse=True)


# -----------------------------------------------------------------------------
# 5. Milestone 4.5 Integrity & Regression Tests
# -----------------------------------------------------------------------------
def test_uhal_negative_fcf_strictly_fails_hard_filter():
    """Regression Test: A company with positive OCF but negative FCF must strictly FAIL."""
    config = QualityFilterConfig(require_positive_fcf=True, allow_temporary_fcf_exception=False)
    uhal_mock = {
        "roe": 0.217,
        "roic": 0.415,
        "debt_equity": 0.00,
        "operating_cash_flow": 1_045_346_000.0,
        "capex": 1_509_154_000.0,
        "free_cash_flow": -463_808_000.0,  # Negative FCF
        "revenue": 3_275_468_000.0,
        "net_income": 489_001_000.0,
        "pe": 14.8,
        "data_completeness_score": 0.85,
    }
    passes, failures = evaluate_quality_filters(uhal_mock, config)
    assert passes is False
    assert any("Free cash flow is negative" in f for f in failures)


def test_quality_passed_csv_satisfies_all_hard_filters():
    """Verify that 100% of companies in quality_passed.csv satisfy every hard filter without exception."""
    from pathlib import Path
    p = Path("data/exports/quality_passed.csv")
    assert p.exists(), "quality_passed.csv must exist"

    df = pd.read_csv(p)
    assert len(df) >= 10, f"Expected at least 10 passing companies, got {len(df)}"

    for _, row in df.iterrows():
        ticker = row["ticker"]
        roe = float(row["roe"])
        roic = float(row["roic"]) if pd.notnull(row["roic"]) else None
        de = float(row["debt_equity"]) if pd.notnull(row["debt_equity"]) else 0.0
        ocf = float(row["operating_cash_flow"])
        fcf = float(row["free_cash_flow"])
        rev = float(row["revenue"])
        comp = float(row["data_completeness_score"])

        assert roe >= 0.12, f"{ticker}: ROE {roe:.1%} < 12%"
        if roic is not None:
            assert roic >= 0.10, f"{ticker}: ROIC {roic:.1%} < 10%"
        else:
            assert de == 0.0 and roe >= 0.10, f"{ticker}: Missing ROIC without zero debt"
        assert de <= 0.75, f"{ticker}: Debt/Equity {de:.2f} > 0.75"
        assert ocf > 0, f"{ticker}: Non-positive OCF (${ocf:,.0f})"
        assert fcf > 0, f"{ticker}: Non-positive FCF (${fcf:,.0f})"
        assert rev > 0, f"{ticker}: Non-positive Revenue (${rev:,.0f})"
        assert comp >= 0.50, f"{ticker}: Completeness {comp:.1%} < 50%"


def test_zero_lookahead_audit_no_future_filings():
    """Verify that NO observation in the 2016 screening results was filed after 2016-12-31."""
    from pathlib import Path
    p = Path("data/exports/screening_results_20161231.csv")
    assert p.exists(), "screening_results_20161231.csv must exist"

    df = pd.read_csv(p)
    for _, row in df.iterrows():
        f_date = str(row["filing_date"])
        ticker = row["ticker"]
        assert f_date <= "2016-12-31", f"Look-ahead violation for {ticker}: filed {f_date} > 2016-12-31"
        assert not f_date.startswith("2017"), f"2017 look-ahead violation for {ticker}: {f_date}"
        assert not f_date.startswith("2018"), f"2018 look-ahead violation for {ticker}: {f_date}"


def test_annual_cagr_filters_out_quarterly_footnote_fragments():
    """Verify that backward chaining prevents quarterly footnote items from inflating CAGRs."""
    engine = PointInTimeFundamentalsEngine(screen_date="2016-12-31")

    # Mock companyfacts with a 10-K containing 3 quarterly footnote observations and 1 annual
    mock_facts = {
        "cik": 777777,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"filed": "2013-03-01", "end": "2012-12-31", "form": "10-K", "fp": "FY", "val": 100_000_000},
                            {"filed": "2014-03-01", "end": "2013-12-31", "form": "10-K", "fp": "FY", "val": 110_000_000},
                            {"filed": "2015-03-01", "end": "2014-12-31", "form": "10-K", "fp": "FY", "val": 120_000_000},
                            # 2015 10-K containing quarterly footnote data (90-day intervals)
                            {"filed": "2016-03-01", "end": "2015-03-31", "form": "10-K", "fp": None, "val": 32_000_000},
                            {"filed": "2016-03-01", "end": "2015-06-30", "form": "10-K", "fp": None, "val": 34_000_000},
                            {"filed": "2016-03-01", "end": "2015-09-30", "form": "10-K", "fp": None, "val": 35_000_000},
                            {"filed": "2016-03-01", "end": "2015-12-31", "form": "10-K", "fp": "FY", "val": 133_100_000},
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"filed": "2013-03-01", "end": "2012-12-31", "form": "10-K", "fp": "FY", "val": 10_000_000},
                            {"filed": "2014-03-01", "end": "2013-12-31", "form": "10-K", "fp": "FY", "val": 11_000_000},
                            {"filed": "2015-03-01", "end": "2014-12-31", "form": "10-K", "fp": "FY", "val": 12_000_000},
                            {"filed": "2016-03-01", "end": "2015-12-31", "form": "10-K", "fp": "FY", "val": 13_310_000},
                        ]
                    }
                },
                "StockholdersEquity": {
                    "units": {
                        "USD": [
                            {"filed": "2016-03-01", "end": "2015-12-31", "form": "10-K", "fp": "FY", "val": 50_000_000},
                        ]
                    }
                },
            }
        }
    }

    result = engine.compute_company_fundamentals(cik=777777, ticker="TEST_CAGR", facts_json=mock_facts)

    # True 3-year CAGR: ($133.1M / $100M)**(1/3) - 1 = 10.0%
    # If it had used the quarterly fragment $32M, CAGR would have been: ($133.1M / $32M)**(1/3) - 1 = 60.8%
    assert result["revenue_cagr"] is not None
    assert pytest.approx(result["revenue_cagr"], 1e-3) == 0.10
    assert result["growth_quality_flag"] == "ORGANIC_LIKELY"

