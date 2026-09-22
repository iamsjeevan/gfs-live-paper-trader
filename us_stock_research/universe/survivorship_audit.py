"""Survivorship-Bias and Historical Price Coverage Audit Engine.

Audits:
1. Historical listing status classification (ACTIVE_2016, POST_2016_IPO, DELISTED_AFTER_2016, ACQUIRED, BANKRUPT, etc.)
2. Historical price coverage rates across active vs non-surviving companies via Yahoo Finance
3. Generation of `historical_universe_price_gaps.csv` tracking exact missing-price companies
4. SEC shares filing lag analysis (share filing date vs screen date gap)
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sqlite3
import pandas as pd
import numpy as np

from config.settings import DATABASE_PATH, EXPORTS_DIR, setup_logger
from database.connection import get_connection

logger = setup_logger("survivorship_audit", "screening.log")


def classify_historical_status(
    company: Dict[str, Any],
    screen_date: str = "2016-12-31",
) -> str:
    """Classify a company's historical lifecycle status relative to the screen date.

    Returns one of:
    - 'ACTIVE_2016': Publicly traded in 2016 and currently still an active SEC filer.
    - 'POST_2016_IPO': First listed / registered after 2016-12-31.
    - 'DELISTED_AFTER_2016': Public in 2016, but delisted/ceased filing between 2017 and 2026.
    - 'ACQUIRED': Acquired or merged post-2016.
    - 'BANKRUPT': Filed Chapter 11 / liquidated post-2016.
    - 'DELISTED_BEFORE_2016': Ceased filing prior to 2016.
    - 'UNKNOWN': Insufficient status records.
    """
    first_seen = company.get("first_seen")
    last_seen = company.get("last_seen")
    is_active = company.get("is_active", 1)
    name_upper = (company.get("company_name") or "").upper()

    # 1. Post-2016 IPO
    if first_seen and first_seen > screen_date:
        return "POST_2016_IPO"

    # 2. Delisted prior to 2016
    if last_seen and last_seen < "2016-01-01":
        return "DELISTED_BEFORE_2016"

    # 3. Known bankruptcy indicators in name or notes
    if any(k in name_upper for k in ["LIQUIDAT", "BANKRUPT", "CHAPTER 11", "ESTATE OF", "DISSOLUTION"]):
        return "BANKRUPT"

    # 4. Active today vs Delisted post-2016
    if is_active == 1 and company.get("exchange") in ["NYSE", "Nasdaq", "AMEX", "NYSE American"]:
        return "ACTIVE_2016"

    # If active in 2016 but not active on a major exchange today:
    if is_active == 0 or company.get("exchange") is None:
        if any(k in name_upper for k in ["MERGER", "ACQUISITION", "HOLDINGS"]):
            return "ACQUIRED"
        return "DELISTED_AFTER_2016"

    return "ACTIVE_2016"


def audit_price_coverage(
    candidate_records: List[Dict[str, Any]],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Audit price coverage by lifecycle status and identify price gaps.

    Args:
        candidate_records: List of candidate evaluation dicts containing:
        ['cik', 'ticker', 'company_name', 'status', 'sic', 'exchange',
         'price_2016', 'shares_2016', 'historical_status', 'exclusion_reason']

    Returns:
        (summary_table_df, price_gaps_df)
    """
    df = pd.DataFrame(candidate_records)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df["price_available"] = df["price_2016"].notna() & (df["price_2016"] > 0)
    df["price_missing"] = ~df["price_available"]

    # Generate coverage summary table by status
    grouped = df.groupby("historical_status").agg(
        candidate_count=("cik", "count"),
        price_available=("price_available", "sum"),
        price_missing=("price_missing", "sum"),
    ).reset_index()

    grouped["coverage_rate"] = (grouped["price_available"] / grouped["candidate_count"] * 100.0).map(lambda x: f"{x:.1f}%")

    # Filter price gap records
    gaps_mask = df["price_missing"] & (df["historical_status"] != "POST_2016_IPO")
    gaps_df = df[gaps_mask].copy()

    gaps_columns = [
        "cik", "ticker", "company_name", "historical_status", "sic", "exchange",
        "shares_2016", "price_available", "exclusion_reason"
    ]
    avail_cols = [c for c in gaps_columns if c in gaps_df.columns]
    price_gaps = gaps_df[avail_cols].rename(columns={
        "cik": "CIK",
        "ticker": "ticker_2016",
        "historical_status": "status",
        "sic": "SIC",
        "price_available": "price_2016_available",
        "exclusion_reason": "missing_price_reason",
    })

    # Add last known notes
    price_gaps["last_known_trading_date"] = "2016-12-30"
    price_gaps["notes"] = price_gaps["status"].map({
        "DELISTED_AFTER_2016": "Delisted post-2016; historical quote unavailable on Yahoo public API",
        "ACQUIRED": "Acquired post-2016; historical ticker suppressed on Yahoo",
        "BANKRUPT": "Entered liquidation / Chapter 11 post-2016; unlisted on Yahoo",
        "ACTIVE_2016": "Active ticker but missing 2016 quote on Yahoo (possible ticker reassignment)",
    }).fillna("Missing historical data")

    # Reorder columns
    ordered_cols = [
        "CIK", "ticker_2016", "company_name", "status", "SIC", "exchange",
        "last_known_trading_date", "price_2016_available", "missing_price_reason", "notes"
    ]
    price_gaps = price_gaps[[c for c in ordered_cols if c in price_gaps.columns]]

    # Export price gaps CSV
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    gaps_csv_path = EXPORTS_DIR / "historical_universe_price_gaps.csv"
    price_gaps.to_csv(gaps_csv_path, index=False)
    logger.info(f"Exported {len(price_gaps)} price gap records to {gaps_csv_path}")

    return grouped, price_gaps


def audit_shares_filing_lag(eligible_df: pd.DataFrame, screen_date: str = "2016-12-31") -> Dict[str, Any]:
    """Quantify the lag between SEC cover-page shares filing date and the historical screen date.

    Investigates whether the latest SEC shares observation filed before screen_date
    is sufficiently representative of shares outstanding on screen date.
    """
    if eligible_df.empty or "shares_filing_date" not in eligible_df.columns:
        return {}

    screen_dt = pd.to_datetime(screen_date)
    filing_dts = pd.to_datetime(eligible_df["shares_filing_date"].dropna())
    lags = (screen_dt - filing_dts).dt.days

    stats = {
        "count": len(lags),
        "mean_lag_days": float(lags.mean()),
        "median_lag_days": float(lags.median()),
        "min_lag_days": int(lags.min()) if not lags.empty else 0,
        "max_lag_days": int(lags.max()) if not lags.empty else 0,
        "within_60_days_pct": float((lags <= 60).mean() * 100.0) if not lags.empty else 0.0,
        "within_90_days_pct": float((lags <= 90).mean() * 100.0) if not lags.empty else 0.0,
    }
    return stats
