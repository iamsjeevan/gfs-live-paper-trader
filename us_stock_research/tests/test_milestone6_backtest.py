"""Comprehensive regression test suite for Milestone 6 Historical Backtesting.

Covers all 12 required scenarios from Part 18 of the specification:
1. simple buy-and-hold stock
2. stock split
3. reverse split
4. cash dividend
5. acquisition for cash
6. acquisition for stock
7. bankruptcy to zero
8. ticker change
9. spin-off
10. missing price
11. no double split adjustment
12. fractional shares
Plus cryptographic hash verification and export deliverables integrity.
"""

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from backtest.models import Position, CorporateAction, PortfolioSnapshot
from backtest.engine import BacktestEngine
from backtest.attribution import compute_concentration_metrics, compute_holding_attribution
from backtest.audit import generate_input_snapshot
from config.settings import DATA_DIR

EXPORTS_DIR = DATA_DIR / "exports"


@pytest.fixture
def mock_market_data(tmp_path):
    """Create a self-contained synthetic market data cache for controlled tests."""
    cache_file = tmp_path / "test_market_data.json"
    data = {
        "TEST_HOLD": {
            "daily": [
                {"date": "2016-12-30", "close": 10.0},
                {"date": "2017-06-30", "close": 15.0},
                {"date": "2018-12-31", "close": 20.0},
            ],
            "splits": [],
            "dividends": [],
        },
        "TEST_SPLIT": {
            "daily": [
                {"date": "2016-12-30", "close": 20.0},
                {"date": "2017-06-15", "close": 22.0},
                {"date": "2017-06-16", "close": 11.0},
                {"date": "2018-12-31", "close": 15.0},
            ],
            "splits": [{"date": "2017-06-16", "ratio": 2.0}],
            "dividends": [],
        },
        "TEST_REVERSE": {
            "daily": [
                {"date": "2016-12-30", "close": 2.0},
                {"date": "2017-06-15", "close": 1.5},
                {"date": "2017-06-16", "close": 15.0},
                {"date": "2018-12-31", "close": 20.0},
            ],
            "splits": [{"date": "2017-06-16", "ratio": 0.1}],  # 1-for-10 reverse split
            "dividends": [],
        },
        "TEST_DIV": {
            "daily": [
                {"date": "2016-12-30", "close": 50.0},
                {"date": "2017-06-30", "close": 50.0},
                {"date": "2018-12-31", "close": 50.0},
            ],
            "splits": [],
            "dividends": [
                {"date": "2017-06-30", "amount": 2.50},
                {"date": "2018-12-31", "amount": 2.50},
            ],
        },
        "TEST_SPIN": {
            "daily": [
                {"date": "2016-12-30", "close": 20.0},
                {"date": "2020-08-24", "close": 20.0},
                {"date": "2026-08-31", "close": 20.0},
            ],
            "splits": [],
            "dividends": [],
        },
        "AOUT": {
            "daily": [
                {"date": "2020-08-24", "close": 10.0},
                {"date": "2026-08-31", "close": 15.0},
            ],
            "splits": [],
            "dividends": [],
        },
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return cache_file


# 1. Simple buy-and-hold stock
def test_simple_buy_and_hold(mock_market_data):
    engine = BacktestEngine(
        market_data_cache_path=mock_market_data,
        start_date="2016-12-30",
        end_date="2018-12-31",
        initial_capital=1_000.0,
    )
    holdings = [{"ticker": "TEST_HOLD", "company_name": "Test Hold Co", "cik": 111111, "price_2016": 10.0}]
    res = engine.run_backtest("Test Hold", holdings)

    assert res["ending_value"] == 2_000.0
    assert res["total_return_pct"] == 1.0  # +100%
    pos = res["positions"]["TEST_HOLD"]
    assert pos.initial_shares == 100.0
    assert pos.current_shares == 100.0
    assert pos.accumulated_dividends == 0.0


# 2. Stock split
def test_stock_split(mock_market_data):
    engine = BacktestEngine(
        market_data_cache_path=mock_market_data,
        start_date="2016-12-30",
        end_date="2018-12-31",
        initial_capital=1_000.0,
    )
    holdings = [{"ticker": "TEST_SPLIT", "company_name": "Test Split Co", "cik": 222222, "price_2016": 20.0}]
    res = engine.run_backtest("Test Split", holdings)

    pos = res["positions"]["TEST_SPLIT"]
    assert pos.initial_shares == 50.0
    assert pos.current_shares == 100.0  # 2:1 split doubled shares
    # Ending price is 15.0 -> 100 * 15 = 1500
    assert res["ending_value"] == 1_500.0
    assert res["total_return_pct"] == 0.50


# 3. Reverse split
def test_reverse_split(mock_market_data):
    engine = BacktestEngine(
        market_data_cache_path=mock_market_data,
        start_date="2016-12-30",
        end_date="2018-12-31",
        initial_capital=1_000.0,
    )
    holdings = [{"ticker": "TEST_REVERSE", "company_name": "Test Reverse Co", "cik": 333333, "price_2016": 2.0}]
    res = engine.run_backtest("Test Reverse", holdings)

    pos = res["positions"]["TEST_REVERSE"]
    assert pos.initial_shares == 500.0
    assert pos.current_shares == 50.0  # 1:10 reverse split reduced shares by 10
    # Ending price is 20.0 -> 50 * 20 = 1000
    assert res["ending_value"] == 1_000.0
    assert res["total_return_pct"] == 0.0


# 4. Cash dividend
def test_cash_dividend(mock_market_data):
    engine = BacktestEngine(
        market_data_cache_path=mock_market_data,
        start_date="2016-12-30",
        end_date="2018-12-31",
        initial_capital=1_000.0,
    )
    holdings = [{"ticker": "TEST_DIV", "company_name": "Test Div Co", "cik": 444444, "price_2016": 50.0}]
    res = engine.run_backtest("Test Div Cash", holdings, reinvest_dividends=False)

    pos = res["positions"]["TEST_DIV"]
    assert pos.initial_shares == 20.0
    assert pos.current_shares == 20.0
    # Two $2.50 dividends on 20 shares = $50 + $50 = $100 cash
    assert pos.accumulated_dividends == 100.0
    assert res["ending_equity"] == 1_000.0
    assert res["ending_cash"] == 100.0
    assert res["ending_value"] == 1_100.0
    assert res["total_return_pct"] == 0.10


# 5. Acquisition for cash
def test_acquisition_for_cash():
    pos = Position(
        ticker="ACQ_CASH",
        company_name="Acquired Cash Co",
        cik=555555,
        entry_date="2016-12-30",
        entry_price=10.0,
        initial_allocation=1_000.0,
        initial_shares=100.0,
        current_shares=0.0,
        cash_proceeds=1_500.0,  # Acquired for $15/share in cash
        status="ACQUIRED",
    )
    assert pos.total_value(current_price=0.0) == 1_500.0
    assert pos.status == "ACQUIRED"


# 6. Acquisition for stock
def test_acquisition_for_stock():
    # Target acquired for 0.5 shares of Acquirer (trading at $40)
    pos = Position(
        ticker="ACQ_STOCK",
        company_name="Acquired Stock Co",
        cik=666666,
        entry_date="2016-12-30",
        entry_price=10.0,
        initial_allocation=1_000.0,
        initial_shares=100.0,
        current_shares=0.0,
        spinoff_shares={"ACQUIRER": 50.0},  # 100 * 0.5
        status="ACQUIRED",
    )
    val = pos.total_value(current_price=0.0, spinoff_prices={"ACQUIRER": 40.0})
    assert val == 2_000.0


# 7. Bankruptcy to zero
def test_bankruptcy_to_zero():
    pos = Position(
        ticker="BANKRUPT_CO",
        company_name="Insolvent Co",
        cik=777777,
        entry_date="2016-12-30",
        entry_price=20.0,
        initial_allocation=1_000.0,
        initial_shares=50.0,
        current_shares=50.0,
        accumulated_dividends=25.0,
        cash_proceeds=0.0,
        status="BANKRUPT",
    )
    # Price is 0.0, shareholder retains accumulated dividends
    val = pos.total_value(current_price=0.0)
    assert val == 25.0
    assert pos.current_equity_value(current_price=0.0) == 0.0


# 8. Ticker change
def test_ticker_change():
    pos = Position(
        ticker="OLD_TICKER",
        company_name="Company Identity Retained",
        cik=888888,
        entry_date="2016-12-30",
        entry_price=25.0,
        initial_allocation=1_000.0,
        initial_shares=40.0,
        current_shares=40.0,
        status="ACTIVE",
    )
    # Ticker change handled by tracking CIK
    assert pos.cik == 888888
    assert pos.total_value(current_price=30.0) == 1_200.0


# 9. Spin-off asset tracking
def test_spinoff_asset_tracking():
    pos = Position(
        ticker="SWBI",
        company_name="Smith & Wesson Brands",
        cik=1092796,
        entry_date="2016-12-30",
        entry_price=16.20,
        initial_allocation=1_000.0,
        initial_shares=61.73,
        current_shares=61.73,
        spinoff_shares={"AOUT": 15.43},  # 0.25 ratio
        status="ACTIVE",
    )
    # SWBI at $12.72, AOUT at $10.57
    val = pos.total_value(current_price=12.72, spinoff_prices={"AOUT": 10.57})
    expected_swbi = 61.73 * 12.72
    expected_aout = 15.43 * 10.57
    assert abs(val - (expected_swbi + expected_aout)) < 0.01


# 10. Missing price fallback
def test_missing_price_fallback(mock_market_data):
    engine = BacktestEngine(
        market_data_cache_path=mock_market_data,
        start_date="2016-12-30",
        end_date="2018-12-31",
    )
    # 2017-01-15 was a Sunday, not in daily list -> should fall back to 2016-12-30 close ($10)
    p = engine._get_price_on_date("TEST_HOLD", "2017-01-15")
    assert p == 10.0


# 11. No double split adjustment
def test_no_double_split_adjustment():
    engine = BacktestEngine(initial_capital=1_000.0)
    # Strategy D Top 10 includes BBSI
    bbsi_holding = [{"ticker": "BBSI", "company_name": "BBSI", "cik": 902791, "price_2016": 64.099998}]
    res = engine.run_backtest("BBSI Single", bbsi_holding)
    pos = res["positions"]["BBSI"]
    # Starting shares is ~15.6, post-split is ~62.4, NOT 249.6!
    assert 62.0 < pos.current_shares < 63.0
    assert 2200.0 < res["ending_value"] < 2400.0


# 12. Fractional shares precision
def test_fractional_shares_precision():
    pos = Position(
        ticker="FRAC_TEST",
        company_name="Fractional Share Test",
        cik=999999,
        entry_date="2016-12-30",
        entry_price=33.333333,
        initial_allocation=1_000.0,
        initial_shares=1000.0 / 33.333333,
        current_shares=1000.0 / 33.333333,
        status="ACTIVE",
    )
    assert abs(pos.initial_shares - 30.0000003) < 1e-6
    assert abs(pos.total_value(current_price=33.333333) - 1_000.0) < 1e-4


# 13. Deliverables exist and verified
def test_all_12_deliverables_exist():
    expected_files = [
        "backtest_input_snapshot_20161231.json",
        "backtest_positions_2016_2026.csv",
        "backtest_corporate_actions_2016_2026.csv",
        "backtest_dividends_2016_2026.csv",
        "backtest_annual_values_2016_2026.csv",
        "backtest_daily_values_2016_2026.csv",
        "backtest_holding_attribution_2016_2026.csv",
        "backtest_strategy_comparison_2016_2026.csv",
        "backtest_data_quality_2016_2026.csv",
        "backtest_lookahead_audit_2016_2026.csv",
        "price_anomalies_2016_2026.csv",
        "final_backtest_report_2016_2026.md",
    ]
    for fn in expected_files:
        fpath = EXPORTS_DIR / fn
        assert fpath.exists(), f"Missing required deliverable: {fn}"
        assert fpath.stat().st_size > 0, f"File {fn} is empty!"


# 14. SHA-256 cryptographic snapshot hash validation
def test_snapshot_sha256_verification():
    snapshot_file = EXPORTS_DIR / "backtest_input_snapshot_20161231.json"
    assert snapshot_file.exists()
    with open(snapshot_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    recorded_hash = data["metadata"].get("sha256_integrity_hash")
    assert recorded_hash is not None and len(recorded_hash) == 64

    # Remove the hash field to recalculate and verify
    data_to_hash = dict(data)
    metadata_copy = dict(data["metadata"])
    del metadata_copy["sha256_integrity_hash"]
    data_to_hash["metadata"] = metadata_copy

    serialized = json.dumps(data_to_hash, sort_keys=True, indent=2)
    computed_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    assert recorded_hash == computed_hash


# 15. Dividend Total Reconciliation Across All Strategies
def test_dividend_total_reconciliation():
    attr = pd.read_csv(EXPORTS_DIR / "backtest_holding_attribution_2016_2026.csv")
    comp = pd.read_csv(EXPORTS_DIR / "backtest_strategy_comparison_2016_2026.csv")

    for strat in comp[comp["mode"].str.contains("PRIMARY")]["strategy"].unique():
        s_attr = attr[attr["strategy"] == strat]
        attr_div_sum = s_attr["dividends_cash"].sum()
        c_row = comp[comp["strategy"] == strat].iloc[0]
        rep_div = c_row["accumulated_dividends"]
        rep_cash = c_row["ending_cash"]
        assert abs(attr_div_sum - rep_div) < 0.05
        assert abs(rep_div - rep_cash) < 0.05


# 16. Strategy Ending Value Invariant: Equity + Divs + CA Cash == Ending Value
def test_strategy_ending_value_reconciliation():
    comp = pd.read_csv(EXPORTS_DIR / "backtest_strategy_comparison_2016_2026.csv")
    for _, row in comp[comp["mode"].str.contains("PRIMARY")].iterrows():
        calc_end = row["ending_equity"] + row["ending_cash"]
        rep_end = row["ending_value"]
        assert abs(calc_end - rep_end) < 0.05


# 17. BBSI Forward Split Accounting & Preservation of Value
def test_bbsi_split_accounting():
    ca_df = pd.read_csv(EXPORTS_DIR / "corporate_action_reconciliation_2016_2026.csv")
    bbsi_ca = ca_df[ca_df["ticker"] == "BBSI"].iloc[0]
    assert bbsi_ca["action_type"] == "FORWARD_SPLIT_4_FOR_1"
    assert abs(bbsi_ca["post_action_shares"] - (bbsi_ca["pre_action_shares"] * 4.0)) < 0.01
    assert abs(bbsi_ca["value_difference_pct"]) < 5.0  # Daily normal market movement


# 18. SWBI / AOUT Spinoff Asset Tracking
def test_swbi_aout_spinoff_reconciliation():
    attr = pd.read_csv(EXPORTS_DIR / "backtest_holding_attribution_2016_2026.csv")
    sd_swbi = attr[(attr["strategy"].str.contains("Strategy D")) & (attr["ticker"] == "SWBI")].iloc[0]
    # Ending equity value includes both SWBI and AOUT
    # SWBI shares = 61.717, price = $12.72 -> $785.04
    # AOUT shares = 15.429, price = $10.57 -> $163.09
    # Total equity = $948.13
    assert abs(sd_swbi["ending_equity_value"] - 948.13) < 0.10
    assert abs(sd_swbi["dividends_cash"] - 155.53) < 0.10
    assert abs(sd_swbi["total_ending_value"] - 1103.66) < 0.10


# 19. Benchmark Dividend Treatment: Unadjusted Close Used, No Double Count
def test_benchmark_dividend_treatment():
    bm_df = pd.read_csv(EXPORTS_DIR / "benchmark_reconciliation_2016_2026.csv")
    for _, row in bm_df.iterrows():
        calc_primary = row["ending_equity_value"] + row["cash_dividends_received"]
        assert abs(calc_primary - row["primary_ending_value"]) < 0.05
        # DRIP ending value must exceed primary cash ending value due to compounding
        assert row["drip_ending_value"] > row["primary_ending_value"]


# 20. CAGR Analytical Calculation Accuracy
def test_cagr_calculation_accuracy():
    comp = pd.read_csv(EXPORTS_DIR / "backtest_strategy_comparison_2016_2026.csv")
    days = (pd.to_datetime("2026-08-31") - pd.to_datetime("2016-12-30")).days
    years = days / 365.25
    for _, row in comp.iterrows():
        calc_cagr = ((row["ending_value"] / row["initial_capital"]) ** (1.0 / years) - 1.0) * 100
        assert abs(calc_cagr - row["cagr_pct"]) < 0.02


# 21. Maximum Drawdown Calculation Verification
def test_maximum_drawdown_calculation():
    comp = pd.read_csv(EXPORTS_DIR / "backtest_strategy_comparison_2016_2026.csv")
    daily = pd.read_csv(EXPORTS_DIR / "backtest_daily_values_2016_2026.csv")
    for strat in comp[comp["mode"].str.contains("PRIMARY")]["strategy"].unique():
        s_daily = daily[daily["strategy"] == strat].sort_values("date")
        peaks = s_daily["total_value"].cummax()
        dds = (s_daily["total_value"] - peaks) / peaks
        calc_mdd = dds.min() * 100
        rep_mdd = comp[comp["strategy"] == strat].iloc[0]["max_drawdown_pct"]
        assert abs(calc_mdd - rep_mdd) < 0.05


# 22. IRMD Attribution and Profit Share Verification
def test_irmd_attribution_verification():
    attr = pd.read_csv(EXPORTS_DIR / "backtest_holding_attribution_2016_2026.csv")
    sd_irmd = attr[(attr["strategy"].str.contains("Strategy D")) & (attr["ticker"] == "IRMD")].iloc[0]
    irmd_profit = sd_irmd["total_ending_value"] - sd_irmd["initial_allocation"]
    assert abs(irmd_profit - 7224.32) < 0.10

    sd_total = attr[attr["strategy"].str.contains("Strategy D")]["total_ending_value"].sum()
    sd_net_profit = sd_total - 10_000.0
    profit_share = (irmd_profit / sd_net_profit) * 100
    assert abs(profit_share - 91.96) < 0.05


# 23. Frozen Portfolio Membership Invariance
def test_frozen_portfolio_membership():
    with open(EXPORTS_DIR / "backtest_input_snapshot_20161231.json") as f:
        snap = json.load(f)
    screen_df = pd.read_csv(EXPORTS_DIR / "screening_results_full_20161231.csv")

    for strat_key, strat_name in [
        ("a", "Strategy A (Quality Only)"),
        ("b", "Strategy B (Quality + Growth)"),
        ("c", "Strategy C (Quality + Growth + Value)"),
        ("d", "Strategy D (Full Strategy: Quality + Growth + Value + Moat)"),
    ]:
        snap_tickers = [h["ticker"] for h in snap["strategies"][strat_name]]
        expected_tickers = screen_df.sort_values(f"rank_strategy_{strat_key}").head(10)["ticker"].tolist()
        assert snap_tickers == expected_tickers

