"""Historical Small-Cap Universe Builder.

Reconstructs the point-in-time universe of US publicly traded small-cap companies
as of a historical screen date (e.g. 2016-12-31).

Enforces:
1. Strict Point-in-Time Discipline: Price and shares must be confirmed on or before `screen_date`.
2. Avoiding Lookahead: No data filed after `screen_date` can be used.
3. Avoiding Survivorship Bias: Companies active in 2016 are tracked by CIK regardless of subsequent
   mergers, acquisitions, ticker changes, or bankruptcies.
4. Clean Classification: Every excluded company records its explicit exclusion reason.
5. Reproducibility: Generates an immutable `universe_run_id` and persists run configuration and company-level audit records to SQLite.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sqlite3
import pandas as pd
import numpy as np

from config.settings import (
    DATABASE_PATH,
    DEFAULT_MAX_MARKET_CAP,
    DEFAULT_MIN_MARKET_CAP,
    DEFAULT_SCREEN_DATE,
    EXPORTS_DIR,
    PRICE_WORKERS,
    setup_logger,
)
from database.connection import get_connection
from database.repositories.companies import CompanyRepository
from data_sources.market_data.base import PriceProvider
from data_sources.market_data.delisted_registry import get_delisted_record_by_cik
from data_sources.market_data.resolver import HistoricalPriceResolver
from data_sources.market_data.yahoo import YahooPriceProvider
from data_sources.sec.client import SECClient
from data_sources.sec.companyfacts import fetch_company_facts
from .filters import classify_company, is_financial_sector, is_valid_exchange
from .market_cap import calculate_historical_market_cap
from .security_type import classify_security_type
from .survivorship_audit import audit_price_coverage, audit_shares_filing_lag, classify_historical_status

logger = setup_logger("historical_universe", "screening.log")


def build_historical_smallcap_universe(
    screen_date: str = DEFAULT_SCREEN_DATE,
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    max_market_cap: float = DEFAULT_MAX_MARKET_CAP,
    exclude_financials: bool = True,
    require_major_exchange: bool = True,
    candidate_ciks: Optional[List[int]] = None,
    limit: Optional[int] = None,
    price_provider: Optional[PriceProvider] = None,
    sec_client: Optional[SECClient] = None,
    workers: int = PRICE_WORKERS,
    db_path: Optional[Path] = None,
    export_csv: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """Construct, audit, and persist the historical small-cap universe."""
    database_file = db_path or DATABASE_PATH
    conn = get_connection(database_file)
    company_repo = CompanyRepository(conn)
    provider = price_provider or HistoricalPriceResolver(db_path=database_file)
    client = sec_client or SECClient()

    # Generate immutable run ID
    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    date_compact = screen_date.replace("-", "")
    run_id = f"universe_{date_compact}_{timestamp_str}"

    logger.info("=" * 80)
    logger.info(f"RECONSTRUCTING HISTORICAL UNIVERSE (Run ID: {run_id})")
    logger.info(f"Screen Date: {screen_date} | Range: ${min_market_cap/1e6:.1f}M - ${max_market_cap/1e6:.1f}M")
    logger.info(f"Exclude Financials: {exclude_financials} | Major Exchange Only: {require_major_exchange}")
    logger.info("=" * 80)

    # 1. Fetch Candidates from Database
    if candidate_ciks:
        candidates = [company_repo.get_by_cik(c) for c in candidate_ciks]
        candidates = [c for c in candidates if c is not None]
    else:
        candidates = company_repo.list_all(limit=limit)

    conn.close()

    total_candidates = len(candidates)
    logger.info(f"Loaded {total_candidates} candidate companies for evaluation.")

    eligible_rows: List[Dict[str, Any]] = []
    excluded_rows: List[Dict[str, Any]] = []
    all_evaluated_rows: List[Dict[str, Any]] = []

    valid_price_count = 0
    valid_shares_count = 0
    valid_market_cap_count = 0

    for idx, comp in enumerate(candidates, start=1):
        cik = int(comp["cik"])
        ticker = comp.get("ticker")
        company_name = comp.get("company_name", "")
        exchange = comp.get("exchange")
        sic = comp.get("sic")

        # Check historical delisted registry to recover historical ticker & exchange
        delist_rec = get_delisted_record_by_cik(cik)
        if delist_rec:
            ticker = ticker or delist_rec.get("ticker")
            exchange = exchange or delist_rec.get("exchange")
            if not company_name:
                company_name = delist_rec.get("company_name", "")

        # Classify historical listing lifecycle status
        hist_status = classify_historical_status(comp, screen_date=screen_date)
        if delist_rec and delist_rec.get("status"):
            hist_status = delist_rec.get("status")

        # Security type check: COMMON_EQUITY vs Preferred / Debt / Fund / REIT
        sec_type = classify_security_type(ticker=ticker, company_name=company_name, sic=sic)
        if sec_type != "COMMON_EQUITY":
            item = {
                "cik": cik,
                "ticker": ticker,
                "company_name": company_name,
                "exchange": exchange,
                "sic": sic,
                "status": "not_common_equity",
                "historical_status": hist_status,
                "reason": f"Not eligible common equity (Security Type: {sec_type})",
                "price_2016": None,
                "shares_2016": None,
                "market_cap": None,
            }
            excluded_rows.append(item)
            all_evaluated_rows.append(item)
            continue

        # Early check: exchange filter if configured
        if require_major_exchange and not is_valid_exchange(exchange):
            item = {
                "cik": cik,
                "ticker": ticker,
                "company_name": company_name,
                "exchange": exchange,
                "sic": sic,
                "status": "not_listed",
                "historical_status": hist_status,
                "reason": f"Not listed on major US exchange (Exchange: {exchange or 'Unknown'})",
                "price_2016": None,
                "shares_2016": None,
                "market_cap": None,
            }
            excluded_rows.append(item)
            all_evaluated_rows.append(item)
            continue

        # Early check: financial sector filter if SIC is known
        if exclude_financials and is_financial_sector(sic):
            item = {
                "cik": cik,
                "ticker": ticker,
                "company_name": company_name,
                "exchange": exchange,
                "sic": sic,
                "status": "financial_sector",
                "historical_status": hist_status,
                "reason": f"Financial sector (SIC {sic})",
                "price_2016": None,
                "shares_2016": None,
                "market_cap": None,
            }
            excluded_rows.append(item)
            all_evaluated_rows.append(item)
            continue

        # 2. Fetch/load SEC Company Facts
        facts_data = fetch_company_facts(cik, client=client, refresh=False)

        # Calculate historical market cap
        mcap_res = calculate_historical_market_cap(
            cik=cik,
            ticker=ticker,
            screen_date=screen_date,
            price_provider=provider,
            facts_json=facts_data,
        )

        if mcap_res["price"] is not None:
            valid_price_count += 1
        if mcap_res["shares"] is not None:
            valid_shares_count += 1
        if mcap_res["is_valid"]:
            valid_market_cap_count += 1

        # Classify eligibility
        status, reason = classify_company(
            market_cap_result=mcap_res,
            sic=sic,
            exchange=exchange,
            exclude_financials=exclude_financials,
            min_market_cap=min_market_cap,
            max_market_cap=max_market_cap,
            require_major_exchange=require_major_exchange,
        )

        # Compute data quality flags for historical shares and prices
        dq_flags = []
        if mcap_res.get("shares_filing_date"):
            try:
                s_dt = pd.to_datetime(mcap_res["shares_filing_date"])
                lag_days = (pd.to_datetime(screen_date) - s_dt).days
                if lag_days > 90:
                    dq_flags.append(f"shares_lag_{lag_days}d")
            except Exception:
                pass
        if mcap_res.get("shares_source") and "WeightedAverage" in str(mcap_res.get("shares_source")):
            dq_flags.append("weighted_avg_shares")
        dq_flag_str = ";".join(dq_flags) if dq_flags else "CLEAN"

        record_item = {
            "cik": cik,
            "ticker": ticker,
            "company_name": company_name,
            "exchange": exchange,
            "sic": sic,
            "screen_date": screen_date,
            "status": status,
            "historical_status": hist_status,
            "reason": reason or status,
            "price_2016": mcap_res["price"],
            "shares_2016": mcap_res["shares"],
            "shares_filing_date": mcap_res["shares_filing_date"],
            "shares_source": mcap_res.get("shares_source"),
            "market_cap_2016": mcap_res["market_cap"],
            "data_quality_flags": dq_flag_str,
            "exclusion_reason": reason or status if status != "eligible" else None,
        }
        all_evaluated_rows.append(record_item)

        if status == "eligible":
            eligible_rows.append(record_item)
        else:
            excluded_rows.append(record_item)

        if idx % 100 == 0 or idx == total_candidates:
            logger.info(f"Evaluated [{idx}/{total_candidates}]: {len(eligible_rows)} eligible, {len(excluded_rows)} excluded.")

    # Convert to DataFrames
    eligible_df = pd.DataFrame(eligible_rows)
    if not eligible_df.empty:
        eligible_df = eligible_df.sort_values("market_cap_2016").reset_index(drop=True)

    excluded_df = pd.DataFrame(excluded_rows)
    if not excluded_df.empty:
        excluded_df = excluded_df.sort_values("cik").reset_index(drop=True)

    # 3. Perform Price Coverage Audit & Identify Price Gaps
    coverage_df, price_gaps_df = audit_price_coverage(all_evaluated_rows)

    # 4. Shares Filing Lag Audit
    lag_stats = audit_shares_filing_lag(eligible_df, screen_date=screen_date)

    # 5. Compute Detailed Stats & Distributions
    stats: Dict[str, Any] = {
        "run_id": run_id,
        "screen_date": screen_date,
        "min_market_cap": min_market_cap,
        "max_market_cap": max_market_cap,
        "companies_considered": total_candidates,
        "valid_historical_price": valid_price_count,
        "valid_historical_shares": valid_shares_count,
        "valid_market_cap": valid_market_cap_count,
        "final_universe_count": len(eligible_df),
        "excluded_count": len(excluded_df),
        "lag_stats": lag_stats,
    }

    if not eligible_df.empty:
        caps = eligible_df["market_cap_2016"]
        stats["percentiles"] = {
            "10th": float(np.percentile(caps, 10)),
            "25th": float(np.percentile(caps, 25)),
            "median": float(np.percentile(caps, 50)),
            "75th": float(np.percentile(caps, 75)),
            "90th": float(np.percentile(caps, 90)),
        }
        # Distributions
        stats["exchange_distribution"] = eligible_df["exchange"].value_counts().to_dict()
        if "sic" in eligible_df.columns:
            stats["sic_distribution"] = eligible_df["sic"].dropna().astype(int).value_counts().head(10).to_dict()
    else:
        stats["percentiles"] = {}
        stats["exchange_distribution"] = {}
        stats["sic_distribution"] = {}

    # 6. Save Run to SQLite for 100% Reproducibility
    conn = get_connection(database_file)
    try:
        conn.execute(
            """
            INSERT INTO universe_runs (
                run_id, screen_date, min_market_cap, max_market_cap,
                exclude_financials, allowed_exchanges, total_candidates,
                eligible_count, excluded_count, stats_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                run_id,
                screen_date,
                min_market_cap,
                max_market_cap,
                1 if exclude_financials else 0,
                "NYSE,NASDAQ,AMEX",
                total_candidates,
                len(eligible_df),
                len(excluded_df),
                json.dumps(stats),
            ),
        )

        company_records = []
        for r in all_evaluated_rows:
            company_records.append((
                run_id,
                r["cik"],
                r.get("ticker"),
                r.get("company_name"),
                r.get("exchange"),
                int(r["sic"]) if r.get("sic") is not None and not pd.isna(r["sic"]) else None,
                r.get("status"),
                r.get("reason"),
                r.get("price_2016"),
                r.get("shares_2016"),
                r.get("shares_filing_date"),
                r.get("shares_source"),
                r.get("market_cap_2016"),
                r.get("historical_status"),
                r.get("data_quality_flags"),
            ))

        conn.executemany(
            """
            INSERT INTO universe_run_companies (
                run_id, cik, ticker, company_name, exchange, sic,
                status, reason, price_2016, shares_2016, shares_filing_date,
                shares_source, market_cap_2016, historical_status, data_quality_flags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            company_records,
        )
        conn.commit()
    finally:
        conn.close()

    # 7. Export CSVs
    if export_csv:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        inc_path = EXPORTS_DIR / f"historical_universe_{date_compact}.csv"
        exc_path = EXPORTS_DIR / f"historical_universe_{date_compact}_excluded.csv"

        inc_cols = [
            "cik", "ticker", "company_name", "exchange", "sic", "screen_date",
            "price_2016", "shares_2016", "shares_filing_date", "shares_source",
            "market_cap_2016", "data_quality_flags"
        ]
        eligible_export = eligible_df[[c for c in inc_cols if c in eligible_df.columns]]
        eligible_export.to_csv(inc_path, index=False)

        exc_cols = ["cik", "ticker", "company_name", "reason", "status", "historical_status", "market_cap_2016"]
        excluded_export = excluded_df[[c for c in exc_cols if c in excluded_df.columns]].rename(columns={"market_cap_2016": "market_cap"})
        excluded_export.to_csv(exc_path, index=False)

        logger.info(f"Exported {len(eligible_df)} eligible companies to {inc_path}")
        logger.info(f"Exported {len(excluded_df)} excluded companies to {exc_path}")

    return eligible_df, excluded_df, stats
