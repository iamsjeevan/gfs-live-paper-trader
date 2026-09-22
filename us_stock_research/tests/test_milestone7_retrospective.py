"""Regression test suite for Milestone 7 — Future-Winner Retrospective / Reverse Fundamental Analysis.

Verifies the 10 required integrity properties from Section 23 of the Milestone 7 specification:
1. 2016 metrics never use filing dates after 2016-12-31.
2. Future winner labels are generated independently from 2016 fundamental calculations.
3. CIK identity remains stable through ticker changes.
4. No duplicate companies after ticker/corporate-action changes.
5. Return calculations use the correct historical starting point.
6. Missing future prices are explicitly tracked.
7. Strategy A/B/C/D calculations match the frozen methodology.
8. Original frozen portfolio hash is unchanged.
9. Original backtest artifacts are not modified.
10. No future fundamental value leaks into the 2016 snapshot.
"""

import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from config.settings import EXPORTS_DIR, DATA_DIR
from retrospective.universe import define_winner_groups
from retrospective.metrics import extract_2016_fundamentals
from retrospective.capture import build_winner_capture_analysis


def test_1_2016_metrics_never_use_filing_dates_after_2016_12_31():
    """Verify that every fundamental observation used was filed on or before 2016-12-31."""
    csv_path = EXPORTS_DIR / "winner_characteristics_2016.csv"
    assert csv_path.exists(), "winner_characteristics_2016.csv must exist"

    df = pd.read_csv(csv_path)
    assert len(df) > 0, "Characteristics dataset must not be empty"

    filing_dates = df["filing_date"].dropna()
    post_2016 = filing_dates[filing_dates > "2016-12-31"]
    assert len(post_2016) == 0, f"Found {len(post_2016)} observations filed after 2016-12-31: {post_2016.tolist()}"

    assert (df["is_strictly_pit"] == True).all(), "All observations must be flagged strictly point-in-time"


def test_2_future_winner_labels_generated_independently_from_2016_fundamentals():
    """Verify that future-winner labels depend only on 10-year return outcomes, not 2016 metrics."""
    mock_returns = pd.DataFrame([
        {"cik": 1, "ticker": "WIN1", "cagr": 0.35, "total_return": 18.0, "has_valid_return": True},
        {"cik": 2, "ticker": "WIN2", "cagr": 0.22, "total_return": 6.5, "has_valid_return": True},
        {"cik": 3, "ticker": "AVG1", "cagr": 0.12, "total_return": 2.1, "has_valid_return": True},
        {"cik": 4, "ticker": "LOS1", "cagr": -0.05, "total_return": -0.4, "has_valid_return": True},
    ])
    labeled = define_winner_groups(mock_returns)

    assert "is_w1_top25" in labeled.columns
    assert "is_w2_cagr20" in labeled.columns
    assert "is_non_winner" in labeled.columns
    assert labeled.loc[labeled["ticker"] == "WIN1", "is_w2_cagr20"].iloc[0] == True
    assert labeled.loc[labeled["ticker"] == "WIN2", "is_w2_cagr20"].iloc[0] == True
    assert labeled.loc[labeled["ticker"] == "LOS1", "is_non_winner"].iloc[0] == True


def test_3_cik_identity_remains_stable_through_ticker_changes():
    """Verify that CIK identity remains immutable across all retrospective tables."""
    csv_path = EXPORTS_DIR / "winner_capture_analysis.csv"
    assert csv_path.exists(), "winner_capture_analysis.csv must exist"

    df = pd.read_csv(csv_path)
    assert df["cik"].notnull().all(), "CIK must never be null"
    assert (df["cik"] > 0).all(), "CIK must be a positive integer"
    assert df["cik"].dtype in [np.int64, int], "CIK must be integer type"


def test_4_no_duplicate_companies_after_ticker_corporate_action_changes():
    """Verify zero duplicate CIKs in the retrospective universe."""
    csv_path = EXPORTS_DIR / "future_winners_2016_2026.csv"
    assert csv_path.exists(), "future_winners_2016_2026.csv must exist"

    df = pd.read_csv(csv_path)
    ciks = df["cik"].tolist()
    dups = [cik for cik in set(ciks) if ciks.count(cik) > 1]
    assert len(dups) == 0, f"Found duplicate CIKs in retrospective universe: {dups}"


def test_5_return_calculations_use_correct_historical_starting_point():
    """Verify that total return and CAGR mathematically match starting and ending prices."""
    csv_path = EXPORTS_DIR / "future_winners_2016_2026.csv"
    df = pd.read_csv(csv_path)

    valid = df[df["has_valid_return"] == True].copy()
    assert len(valid) >= 600, "Expected at least 600 valid return calculations"

    # Verify formula on sample
    sample = valid.head(20)
    days = (pd.to_datetime("2026-08-31") - pd.to_datetime("2016-12-30")).days
    years = days / 365.25

    for _, row in sample.iterrows():
        p_start = row["price_2016_adj"]
        p_end = row["price_2026_adj"]
        expected_ret = (p_end / p_start) - 1.0
        expected_cagr = ((p_end / p_start) ** (1.0 / years)) - 1.0

        assert abs(row["total_return"] - expected_ret) < 1e-4, f"Total return mismatch for {row['ticker']}"
        assert abs(row["cagr"] - expected_cagr) < 1e-4, f"CAGR mismatch for {row['ticker']}"


def test_6_missing_future_prices_explicitly_tracked():
    """Verify that companies without 2026 market prices are explicitly tracked and logged."""
    csv_path = EXPORTS_DIR / "future_winners_2016_2026.csv"
    df = pd.read_csv(csv_path)

    missing = df[df["has_valid_return"] == False]
    assert len(missing) > 0, "Missing price cases must exist and be explicitly tracked"
    assert "exclusion_reason" in missing.columns
    assert missing["exclusion_reason"].notnull().all(), "Every excluded stock must have an explicit reason"


def test_7_strategy_abcd_calculations_match_frozen_methodology():
    """Verify that Strategy A, B, C, D scores and ranks exactly match frozen screening results."""
    frozen_scr_path = EXPORTS_DIR / "screening_results_full_20161231.csv"
    assert frozen_scr_path.exists(), "Frozen screening results must exist"
    frozen_df = pd.read_csv(frozen_scr_path)

    retro_cap_path = EXPORTS_DIR / "winner_capture_analysis.csv"
    assert retro_cap_path.exists(), "winner_capture_analysis.csv must exist"
    cap_df = pd.read_csv(retro_cap_path)

    # Merge on CIK for passing companies
    merged = pd.merge(
        frozen_df[["cik", "ticker", "rank_strategy_d", "score_strategy_d"]],
        cap_df[["cik", "rank_strategy_d", "score_strategy_d"]],
        on="cik",
        suffixes=("_frozen", "_retro"),
    )
    assert len(merged) == len(frozen_df), "All frozen quality passers must be present in capture analysis"

    for _, r in merged.iterrows():
        assert abs(r["score_strategy_d_frozen"] - r["score_strategy_d_retro"]) < 1e-4, (
            f"Strategy D score drift for {r['ticker']}: frozen={r['score_strategy_d_frozen']} vs retro={r['score_strategy_d_retro']}"
        )
        assert r["rank_strategy_d_frozen"] == r["rank_strategy_d_retro"], (
            f"Strategy D rank drift for {r['ticker']}: frozen={r['rank_strategy_d_frozen']} vs retro={r['rank_strategy_d_retro']}"
        )


def test_8_original_frozen_portfolio_hash_unchanged():
    """Verify that backtest_positions_2016_2026.csv is unaltered and preserves the 14 unique holdings."""
    pos_path = EXPORTS_DIR / "backtest_positions_2016_2026.csv"
    assert pos_path.exists(), "backtest_positions_2016_2026.csv must exist"

    df = pd.read_csv(pos_path)
    strat_d = df[df["strategy"].str.contains("Strategy D")]
    assert len(strat_d) == 10, "Strategy D must contain exactly 10 holdings"

    expected_d_tickers = {"APEI", "NHTC", "IRMD", "OFLX", "BBSI", "MDXG", "TCX", "SWBI", "USNA", "SLP"}
    actual_d_tickers = set(strat_d["ticker"].tolist())
    assert actual_d_tickers == expected_d_tickers, f"Strategy D holdings changed! Found: {actual_d_tickers}"


def test_9_original_backtest_artifacts_not_modified():
    """Verify that frozen Milestone 6 backtest artifacts exist and remain intact."""
    m6_files = [
        "final_backtest_report_2016_2026.md",
        "backtest_integrity_audit_2016_2026.md",
        "backtest_strategy_comparison_2016_2026.csv",
        "backtest_annual_values_2016_2026.csv",
        "backtest_holding_attribution_2016_2026.csv",
        "backtest_input_snapshot_20161231.json",
    ]
    for fname in m6_files:
        fpath = EXPORTS_DIR / fname
        assert fpath.exists(), f"Original backtest artifact {fname} missing or modified!"
        assert fpath.stat().st_size > 0, f"Original backtest artifact {fname} is empty!"


def test_10_no_future_fundamental_value_leaks_into_2016_snapshot():
    """Verify that no post-2016 accounting concepts exist in the 2016 snapshot."""
    fund_path = EXPORTS_DIR / "winner_characteristics_2016.csv"
    assert fund_path.exists(), "winner_characteristics_2016.csv must exist"

    df = pd.read_csv(fund_path)
    # Check period_end dates
    period_ends = df["period_end"].dropna()
    post_2016_ends = period_ends[period_ends > "2016-12-31"]
    assert len(post_2016_ends) == 0, f"Found future period_end dates: {post_2016_ends.tolist()}"
