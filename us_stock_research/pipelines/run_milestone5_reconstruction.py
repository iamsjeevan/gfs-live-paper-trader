"""Milestone 5: Full 2016 Historical Universe Reconstruction, Multi-Class Share Resolution,
Point-in-Time Fundamentals Screening, and Final Strategy Candidate Portfolio Generation.

Strict Point-in-Time Rule:
- Only data filed on or before 2016-12-31 is accessible.
- No 2026 prices or post-2016 backtesting returns are computed.
"""

from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import sqlite3

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from config.settings import (
    DATABASE_PATH,
    DEFAULT_MAX_MARKET_CAP,
    DEFAULT_MIN_MARKET_CAP,
    DEFAULT_SCREEN_DATE,
    EXPORTS_DIR,
    setup_logger,
)
from database.connection import get_connection
from data_sources.market_data.delisted_registry import get_delisted_record_by_cik
from data_sources.market_data.resolver import HistoricalPriceResolver
from data_sources.sec.client import SECClient
from data_sources.sec.companyfacts import fetch_company_facts
from data_sources.sec.historical_filers import fetch_historical_filers_for_year
from fundamentals.engine import PointInTimeFundamentalsEngine
from screening.filters import QualityFilterConfig, evaluate_quality_filters
from screening.scoring import score_universe_candidates
from universe.filters import is_financial_sector, is_valid_exchange
from universe.security_type import classify_security_type
from universe.share_resolver import HistoricalShareResolver
from universe.survivorship_audit import classify_historical_status
from pipelines.generate_milestone5_reports import generate_milestone5_reports

logger = setup_logger("milestone5_pipeline", "screening.log")


def run_milestone5_pipeline(
    screen_date: str = DEFAULT_SCREEN_DATE,
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    max_market_cap: float = DEFAULT_MAX_MARKET_CAP,
    db_path: Optional[Path] = None,
    export_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute the complete Milestone 5 pipeline across the full 2016 historical universe."""
    database_file = db_path or DATABASE_PATH
    out_dir = export_dir or EXPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 80)
    logger.info("STARTING MILESTONE 5: FULL HISTORICAL UNIVERSE & STRATEGY PORTFOLIO RECONSTRUCTION")
    logger.info(f"Screen Date: {screen_date} | Market Cap: ${min_market_cap/1e6:.0f}M - ${max_market_cap/1e6:.0f}M")
    logger.info("=" * 80)

    # 1. Discover all 2016 periodic filers (7,877 companies)
    filers_2016 = fetch_historical_filers_for_year(2016)
    logger.info(f"Loaded {len(filers_2016)} periodic reporting companies from 2016 SEC EDGAR master index.")

    conn = get_connection(database_file)
    price_resolver = HistoricalPriceResolver(db_path=database_file)
    share_resolver = HistoricalShareResolver()
    client = SECClient()

    # Query all company records from SQLite
    cursor = conn.execute("SELECT * FROM companies")
    db_companies_by_cik = {row["cik"]: dict(row) for row in cursor.fetchall()}

    full_universe_records: List[Dict[str, Any]] = []
    share_audit_records: List[Dict[str, Any]] = []
    eligible_smallcaps: List[Dict[str, Any]] = []

    # Counters
    counts = {
        "total_2016_filers": len(filers_2016),
        "not_common_equity": 0,
        "not_major_exchange": 0,
        "financial_sector": 0,
        "post_2016_ipo": 0,
        "evaluated_major_common": 0,
        "valid_historical_price": 0,
        "valid_historical_shares": 0,
        "valid_market_cap": 0,
        "below_min_cap": 0,
        "above_max_cap": 0,
        "eligible_smallcaps": 0,
    }

    # Preload price map from SQLite prices table
    price_map = {}
    for r in conn.execute(
        "SELECT ticker, close, provider, date FROM prices WHERE date <= ? AND date >= ? ORDER BY date ASC",
        (screen_date, "2016-12-20"),
    ).fetchall():
        if r["ticker"] and r["close"] is not None:
            price_map[r["ticker"].upper()] = (float(r["close"]), r["provider"] or "yahoo", r["date"])

    # Load post-2016 split factors to restore true unadjusted prices from Yahoo Finance
    split_factors_file = Path("data/raw/post_2016_split_factors.json")
    split_factors_map: Dict[str, float] = {}
    if split_factors_file.exists():
        with open(split_factors_file) as sff:
            split_factors_map = json.load(sff)

    # Evaluate each filer
    for cik, filer_info in filers_2016.items():
        comp = db_companies_by_cik.get(cik, {})
        ticker = comp.get("ticker")
        company_name = comp.get("company_name") or filer_info.get("company_name", "")
        exchange = comp.get("exchange")
        sic = comp.get("sic")
        first_seen = comp.get("first_seen")

        # Delisted registry fallback
        delist_rec = get_delisted_record_by_cik(cik)
        if delist_rec:
            ticker = ticker or delist_rec.get("ticker")
            exchange = exchange or delist_rec.get("exchange")
            company_name = company_name or delist_rec.get("company_name", "")

        # Fallback to local SEC submissions for SIC if missing in companies table
        if sic is None:
            sub_p = Path(f"data/raw/sec/submissions/CIK{cik:010d}.json")
            if sub_p.exists():
                try:
                    with open(sub_p) as sf:
                        s_data = json.load(sf)
                        if s_data.get("sic"):
                            sic = int(s_data["sic"])
                except Exception:
                    pass

        hist_status = classify_historical_status(comp, screen_date=screen_date)
        if delist_rec and delist_rec.get("status"):
            hist_status = delist_rec.get("status")

        sec_type = classify_security_type(ticker=ticker, company_name=company_name, sic=sic)

        record = {
            "cik": cik,
            "ticker": ticker,
            "company_name": company_name,
            "exchange": exchange,
            "sic": sic,
            "screen_date": screen_date,
            "price_2016": None,
            "price_provider": None,
            "shares_2016": None,
            "shares_filing_date": None,
            "shares_report_date": None,
            "shares_source": None,
            "market_cap_2016": None,
            "status": "excluded",
            "reason": None,
            "historical_status": hist_status,
            "security_type": sec_type,
            "data_quality_flags": "CLEAN",
        }

        # Filter 1: Security Classification
        if sec_type != "COMMON_EQUITY":
            counts["not_common_equity"] += 1
            record["status"] = "excluded"
            record["reason"] = "INVALID_SECURITY"
            full_universe_records.append(record)
            continue

        # Filter 2: Major Exchange Requirement
        if not is_valid_exchange(exchange):
            counts["not_major_exchange"] += 1
            record["status"] = "excluded"
            record["reason"] = "NON_MAJOR_EXCHANGE"
            full_universe_records.append(record)
            continue

        # Filter 3: Financial Sector Filter (SIC 6000-6999)
        if is_financial_sector(sic):
            counts["financial_sector"] += 1
            record["status"] = "excluded"
            record["reason"] = "FINANCIAL_SECTOR"
            full_universe_records.append(record)
            continue

        # Filter 4: Post-2016 IPO Check
        if first_seen and first_seen > screen_date:
            counts["post_2016_ipo"] += 1
            record["status"] = "excluded"
            record["reason"] = "POST_2016_IPO"
            full_universe_records.append(record)
            continue

        counts["evaluated_major_common"] += 1

        # Price Resolution (strictly unadjusted closing price on or immediately prior to 2016-12-31)
        price_val = None
        price_provider_name = None
        if delist_rec and delist_rec.get("unadjusted_price"):
            price_val = float(delist_rec["unadjusted_price"])
            price_provider_name = "delisted_historical_archive"
        elif ticker and ticker.upper() in price_map:
            price_val, price_provider_name, _ = price_map[ticker.upper()]
            # If price came from Yahoo, restore true unadjusted price if subsequent split occurred
            if ticker.upper() in split_factors_map:
                s_factor = float(split_factors_map[ticker.upper()])
                if s_factor > 0 and s_factor != 1.0:
                    price_val = price_val * s_factor
                    record["data_quality_flags"] = f"POST_2016_SPLIT_RESTORED_{s_factor:g}X"

        if price_val and price_val > 0:
            counts["valid_historical_price"] += 1
            record["price_2016"] = price_val
            record["price_provider"] = price_provider_name
        else:
            record["status"] = "excluded"
            record["reason"] = "NO_HISTORICAL_PRICE"
            full_universe_records.append(record)
            continue

        # Share Count Resolution (using HistoricalShareResolver)
        share_res = share_resolver.resolve_shares(
            cik=cik,
            screen_date=screen_date,
            ticker=ticker,
            conn=conn,
        )

        share_audit_record = {
            "cik": cik,
            "ticker": ticker,
            "screen_date": screen_date,
            "shares": share_res.get("shares"),
            "shares_filing_date": share_res.get("shares_filing_date"),
            "shares_report_date": share_res.get("shares_report_date"),
            "source": share_res.get("source"),
            "is_multi_class": share_res.get("is_multi_class", False),
            "share_classes": json.dumps(share_res.get("share_classes", {})),
            "confidence": share_res.get("confidence", 0.0),
            "quality_flags": share_res.get("quality_flags", "UNKNOWN"),
        }
        share_audit_records.append(share_audit_record)

        if share_res.get("is_valid") and share_res.get("shares") and share_res["shares"] > 0:
            shares_val = float(share_res["shares"])
            counts["valid_historical_shares"] += 1
            record["shares_2016"] = shares_val
            record["shares_filing_date"] = share_res.get("shares_filing_date")
            record["shares_report_date"] = share_res.get("shares_report_date")
            record["shares_source"] = share_res.get("source")
            record["data_quality_flags"] = share_res.get("quality_flags", "CLEAN")
        else:
            record["status"] = "excluded"
            record["reason"] = "NO_HISTORICAL_SHARES"
            full_universe_records.append(record)
            continue

        # Market Capitalization Calculation
        mcap = price_val * shares_val
        record["market_cap_2016"] = mcap
        counts["valid_market_cap"] += 1

        # Small-Cap Bounds Filter ($50M to $1B)
        if mcap < min_market_cap:
            counts["below_min_cap"] += 1
            record["status"] = "excluded"
            record["reason"] = "NOT_SMALL_CAP_TOO_SMALL"
            full_universe_records.append(record)
            continue
        elif mcap > max_market_cap:
            counts["above_max_cap"] += 1
            record["status"] = "excluded"
            record["reason"] = "NOT_SMALL_CAP_TOO_LARGE"
            full_universe_records.append(record)
            continue

        # Eligible Small-Cap!
        counts["eligible_smallcaps"] += 1
        record["status"] = "eligible"
        record["reason"] = "ELIGIBLE_SMALL_CAP"
        full_universe_records.append(record)
        eligible_smallcaps.append(record)

    conn.close()

    logger.info(f"Universe Reconstruction Results:")
    for k, v in counts.items():
        logger.info(f"  {k}: {v}")

    # Convert full universe and share audit to DataFrames
    full_universe_df = pd.DataFrame(full_universe_records)
    share_audit_df = pd.DataFrame(share_audit_records)

    # 2. Compute Point-in-Time Fundamentals for all eligible small-caps
    logger.info(f"Computing point-in-time fundamentals for {len(eligible_smallcaps)} eligible small-caps...")
    engine = PointInTimeFundamentalsEngine(screen_date=screen_date)
    filter_config = QualityFilterConfig(allow_temporary_fcf_exception=False)

    evaluated_fundamentals: List[Dict[str, Any]] = []
    quality_passers: List[Dict[str, Any]] = []
    lineage_records: List[Dict[str, Any]] = []
    lookahead_records: List[Dict[str, Any]] = []

    for item in eligible_smallcaps:
        cik = item["cik"]
        ticker = item["ticker"]
        mcap = item["market_cap_2016"]
        price = item["price_2016"]

        # Compute fundamentals
        fund = engine.compute_company_fundamentals(
            cik=cik,
            ticker=ticker,
            market_cap_2016=mcap,
        )
        fund["company_name"] = item["company_name"]
        fund["exchange"] = item["exchange"]
        fund["sic"] = item["sic"]
        fund["price"] = price
        fund["market_cap"] = mcap
        fund["shares"] = item["shares_2016"]
        fund["shares_source"] = item["shares_source"]
        fund["shares_filing_date"] = item["shares_filing_date"]
        fund["historical_status"] = item["historical_status"]

        # Evaluate quality filters
        passes, fail_reasons = evaluate_quality_filters(fund, filter_config)
        fund["passes_filters"] = passes
        fund["failure_reasons"] = "; ".join(fail_reasons) if fail_reasons else ""

        evaluated_fundamentals.append(fund)
        if passes:
            quality_passers.append(fund)

            # Build Lineage Audit for passing company
            filing_dt = fund.get("filing_date") or screen_date
            accn_val = fund.get("accession_number") or "N/A"
            lineage_items = [
                ("Revenue", fund.get("revenue"), "Reported Line Item", "Revenues"),
                ("Net Income", fund.get("net_income"), "Reported Line Item", "NetIncomeLoss"),
                ("Operating Income", fund.get("operating_income"), "Reported Line Item", "OperatingIncomeLoss"),
                ("Cash & Equivalents", fund.get("cash"), "Reported Line Item", "CashAndCashEquivalentsAtCarryingValue"),
                ("Total Debt", fund.get("debt"), "Short-Term Debt + Long-Term Debt", "LongTermDebtNoncurrent"),
                ("Stockholders Equity", fund.get("equity"), "Reported Line Item", "StockholdersEquity"),
                ("Operating Cash Flow", fund.get("operating_cash_flow"), "Reported Cash Flow", "NetCashProvidedByUsedInOperatingActivities"),
                ("Capital Expenditures", fund.get("capex"), "Reported Cash Flow", "PaymentsToAcquirePropertyPlantAndEquipment"),
                ("Free Cash Flow", fund.get("free_cash_flow"), "Operating Cash Flow - Capex", "Formula"),
                ("Shares Outstanding", fund.get("shares"), "Historical Point-in-Time Shares", "Derived/ShareResolver"),
                ("Market Capitalization", fund.get("market_cap"), "2016-12-30 Price * Shares Outstanding", "Formula"),
                ("ROE", fund.get("roe"), "Net Income / Stockholders Equity", "Formula"),
                ("ROIC (Net Invested Capital)", fund.get("roic"), "NOPAT / (Equity + Debt - Cash)", "Formula"),
                ("ROIC (Gross Invested Capital)", fund.get("roic_gross"), "NOPAT / (Equity + Debt)", "Formula"),
                ("Debt / Equity", fund.get("debt_equity"), "Total Debt / Stockholders Equity", "Formula"),
                ("Operating Margin", fund.get("operating_margin"), "Operating Income / Revenue", "Formula"),
                ("FCF Margin", fund.get("fcf_margin"), "Free Cash Flow / Revenue", "Formula"),
                ("Revenue CAGR (3-Yr)", fund.get("revenue_cagr"), "(Rev_T0 / Rev_T-3)**(1/3) - 1", "Formula"),
                ("P/E Ratio", fund.get("pe"), "Market Cap / Net Income", "Formula"),
                ("EV / EBITDA", fund.get("ev_ebitda"), "Enterprise Value / (Operating Income + Capex Proxy)", "Formula"),
                ("Price / FCF", fund.get("price_fcf"), "Market Cap / Free Cash Flow", "Formula"),
                ("Quantitative Moat Score", fund.get("quantitative_moat_score"), "Weighted 5-Factor Persistence Model", "Formula"),
            ]
            for metric_name, val, formula_desc, concept_name in lineage_items:
                lineage_records.append({
                    "CIK": cik,
                    "Ticker": ticker,
                    "Metric": metric_name,
                    "Value": val,
                    "Period End": fund.get("period_end"),
                    "Filing Date": filing_dt,
                    "SEC Concept": concept_name,
                    "Accession": accn_val,
                    "Calculation Formula": formula_desc,
                    "Quality Flag": fund.get("growth_quality_flag", "CLEAN"),
                })

                # Look-ahead check
                lookahead_detected = str(filing_dt) > screen_date if filing_dt else False
                lookahead_records.append({
                    "CIK": cik,
                    "Ticker": ticker,
                    "Metric": metric_name,
                    "Source Filing Date": filing_dt,
                    "Cutoff Date": screen_date,
                    "Lookahead Detected": lookahead_detected,
                })

    logger.info(f"Quality Filter Evaluation: {len(quality_passers)} of {len(eligible_smallcaps)} passed all hard filters.")

    # 3. Score Strategies A, B, C, D across Quality Passers
    if quality_passers:
        strat_dict = score_universe_candidates(quality_passers)
        a_df = strat_dict.get("Strategy A (Quality Only)", pd.DataFrame())
        b_df = strat_dict.get("Strategy B (Quality + Growth)", pd.DataFrame())
        c_df = strat_dict.get("Strategy C (Quality + Growth + Value)", pd.DataFrame())
        d_df = strat_dict.get("Strategy D (Full Strategy: Quality + Growth + Value + Moat)", pd.DataFrame())

        export_records = []
        for _, r in d_df.iterrows():
            cik_val = r["cik"]
            rank_a = int(a_df[a_df["cik"] == cik_val]["rank"].iloc[0]) if not a_df.empty and (a_df["cik"] == cik_val).any() else None
            rank_b = int(b_df[b_df["cik"] == cik_val]["rank"].iloc[0]) if not b_df.empty and (b_df["cik"] == cik_val).any() else None
            rank_c = int(c_df[c_df["cik"] == cik_val]["rank"].iloc[0]) if not c_df.empty and (c_df["cik"] == cik_val).any() else None
            score_a = float(a_df[a_df["cik"] == cik_val]["composite_score"].iloc[0]) if not a_df.empty and (a_df["cik"] == cik_val).any() else None
            score_b = float(b_df[b_df["cik"] == cik_val]["composite_score"].iloc[0]) if not b_df.empty and (b_df["cik"] == cik_val).any() else None
            score_c = float(c_df[c_df["cik"] == cik_val]["composite_score"].iloc[0]) if not c_df.empty and (c_df["cik"] == cik_val).any() else None
            rank_d = int(r["rank"])

            export_records.append({
                "cik": cik_val,
                "ticker": r["ticker"],
                "company_name": r.get("company_name"),
                "screen_date": screen_date,
                "rank_strategy_a": rank_a,
                "rank_strategy_b": rank_b,
                "rank_strategy_c": rank_c,
                "rank_strategy_d": rank_d,
                "score_strategy_a": score_a,
                "score_strategy_b": score_b,
                "score_strategy_c": score_c,
                "score_strategy_d": float(r.get("composite_score", 0.0)),
                "market_cap_2016": float(r.get("market_cap_2016")) if pd.notnull(r.get("market_cap_2016")) else None,
                "price_2016": float(r.get("price")) if pd.notnull(r.get("price")) else None,
                "roe": float(r.get("roe")) if pd.notnull(r.get("roe")) else None,
                "roic": float(r.get("roic")) if pd.notnull(r.get("roic")) else None,
                "roic_gross": float(r.get("roic_gross")) if pd.notnull(r.get("roic_gross")) else None,
                "debt_equity": float(r.get("debt_equity")) if pd.notnull(r.get("debt_equity")) else None,
                "operating_margin": float(r.get("operating_margin")) if pd.notnull(r.get("operating_margin")) else None,
                "fcf_margin": float(r.get("fcf_margin")) if pd.notnull(r.get("fcf_margin")) else None,
                "revenue_growth": float(r.get("revenue_growth")) if pd.notnull(r.get("revenue_growth")) else None,
                "revenue_cagr": float(r.get("revenue_cagr")) if pd.notnull(r.get("revenue_cagr")) else None,
                "net_income_cagr": float(r.get("net_income_cagr")) if pd.notnull(r.get("net_income_cagr")) else None,
                "fcf_cagr": float(r.get("fcf_cagr")) if pd.notnull(r.get("fcf_cagr")) else None,
                "growth_consistency": float(r.get("growth_consistency")) if pd.notnull(r.get("growth_consistency")) else None,
                "growth_quality_flag": r.get("growth_quality_flag", "CLEAN"),
                "pe": float(r.get("pe")) if pd.notnull(r.get("pe")) else None,
                "ev_ebitda": float(r.get("ev_ebitda")) if pd.notnull(r.get("ev_ebitda")) else None,
                "price_fcf": float(r.get("price_fcf")) if pd.notnull(r.get("price_fcf")) else None,
                "quantitative_moat_score": float(r.get("quantitative_moat_score")) if pd.notnull(r.get("quantitative_moat_score")) else None,
                "moat_gm_stability": float(r.get("moat_gm_stability")) if pd.notnull(r.get("moat_gm_stability")) else None,
                "moat_op_persistence": float(r.get("moat_op_persistence")) if pd.notnull(r.get("moat_op_persistence")) else None,
                "moat_roic_spread": float(r.get("moat_roic_spread")) if pd.notnull(r.get("moat_roic_spread")) else None,
                "moat_fcf_durability": float(r.get("moat_fcf_durability")) if pd.notnull(r.get("moat_fcf_durability")) else None,
                "moat_capex_intensity": float(r.get("moat_capex_intensity")) if pd.notnull(r.get("moat_capex_intensity")) else None,
                "filing_date": r.get("filing_date"),
                "period_end": r.get("period_end"),
                "passes_filters": True,
                "failure_reasons": "",
            })
        scores_df = pd.DataFrame(export_records)
    else:
        scores_df = pd.DataFrame()

    # 4. Generate Survivorship Audit Data
    survivorship_records = []
    statuses = full_universe_df["historical_status"].value_counts()
    for st, total_in_status in statuses.items():
        sub_df = full_universe_df[full_universe_df["historical_status"] == st]
        with_px = (sub_df["price_2016"].notna() & (sub_df["price_2016"] > 0)).sum()
        with_sh = (sub_df["shares_2016"].notna() & (sub_df["shares_2016"] > 0)).sum()
        with_mc = (sub_df["market_cap_2016"].notna() & (sub_df["market_cap_2016"] > 0)).sum()
        in_smallcap = (sub_df["status"] == "eligible").sum()

        pass_fund = 0
        in_top10_d = 0
        if not scores_df.empty:
            ciks_in_scores = set(scores_df["cik"].tolist())
            pass_fund = sub_df["cik"].isin(ciks_in_scores).sum()
            top10_ciks = set(scores_df.head(10)["cik"].tolist())
            in_top10_d = sub_df["cik"].isin(top10_ciks).sum()

        survivorship_records.append({
            "Historical Status": st,
            "Total 2016 Filers": total_in_status,
            "Reconstructed Price": with_px,
            "Price Coverage %": f"{(with_px / total_in_status * 100):.1f}%",
            "Reconstructed Shares": with_sh,
            "Valid Market Cap": with_mc,
            "Inside $50M-$1B": in_smallcap,
            "Passed All Hard Filters": pass_fund,
            "Strategy D Top 10": in_top10_d,
        })
    survivorship_df = pd.DataFrame(survivorship_records)

    # 5. Export Output CSV Files
    logger.info("Exporting deliverable CSV files...")
    full_universe_df.to_csv(out_dir / "full_historical_universe_20161231.csv", index=False)
    survivorship_df.to_csv(out_dir / "survivorship_audit_20161231.csv", index=False)
    share_audit_df.to_csv(out_dir / "historical_share_count_audit_20161231.csv", index=False)

    # Price coverage by exchange & lifecycle
    price_cov_df = full_universe_df.groupby(["exchange", "historical_status"]).agg(
        total_companies=("cik", "count"),
        price_available=("price_2016", lambda s: (s.notna() & (s > 0)).sum()),
    ).reset_index()
    price_cov_df["coverage_pct"] = (price_cov_df["price_available"] / price_cov_df["total_companies"] * 100.0).map(lambda x: f"{x:.1f}%")
    price_cov_df.to_csv(out_dir / "historical_price_coverage_20161231.csv", index=False)

    quality_passed_df = pd.DataFrame(quality_passers)
    quality_passed_df.to_csv(out_dir / "quality_passed_full_20161231.csv", index=False)

    lineage_df = pd.DataFrame(lineage_records)
    lineage_df.to_csv(out_dir / "screening_data_lineage_full_20161231.csv", index=False)

    lookahead_df = pd.DataFrame(lookahead_records)
    lookahead_df.to_csv(out_dir / "lookahead_audit_20161231.csv", index=False)

    if not scores_df.empty:
        scores_df.to_csv(out_dir / "screening_results_full_20161231.csv", index=False)

    # 6. Build Versioned Screening Snapshot JSON
    snapshot_data = {
        "metadata": {
            "snapshot_id": f"screening_snapshot_{screen_date.replace('-', '')}",
            "methodology_version": "5.0.0_PRODUCTION_FULL_UNIVERSE",
            "created_at": datetime.utcnow().isoformat(),
            "screen_date": screen_date,
            "market_cap_bounds": [min_market_cap, max_market_cap],
            "price_date": "2016-12-30",
        },
        "universe_summary": counts,
        "quality_passers_count": len(quality_passers),
        "strategy_d_top10": scores_df[["cik", "ticker", "company_name", "score_strategy_d", "market_cap_2016"]].head(10).to_dict("records") if not scores_df.empty else [],
    }
    with open(out_dir / f"screening_snapshot_{screen_date.replace('-', '')}.json", "w") as f:
        json.dump(snapshot_data, f, indent=2)

    # 7. Generate Markdown Deliverable Reports
    logger.info("Generating markdown audit reports (universe quality report & final candidate portfolios)...")
    generate_milestone5_reports(
        full_universe_df=full_universe_df,
        scores_df=scores_df,
        quality_passed_df=quality_passed_df,
        survivorship_df=survivorship_df,
        counts=counts,
        out_dir=out_dir,
        screen_date=screen_date,
    )

    logger.info("Milestone 5 Reconstruction Pipeline Completed Successfully.")
    return {
        "counts": counts,
        "quality_passers_count": len(quality_passers),
        "scores_df": scores_df,
        "full_universe_df": full_universe_df,
        "survivorship_df": survivorship_df,
    }


if __name__ == "__main__":
    results = run_milestone5_pipeline()
    print("\n" + "=" * 80)
    print("MILESTONE 5 PIPELINE EXECUTION COMPLETED")
    print("=" * 80)
    print(f"Total Evaluated 2016 Filers: {results['counts']['total_2016_filers']:,}")
    print(f"Valid Historical Prices: {results['counts']['valid_historical_price']:,}")
    print(f"Valid Historical Shares: {results['counts']['valid_historical_shares']:,}")
    print(f"Valid Market Caps: {results['counts']['valid_market_cap']:,}")
    print(f"Eligible Small Caps ($50M-$1B): {results['counts']['eligible_smallcaps']:,}")
    print(f"Quality Passers (Hard Filters): {results['quality_passers_count']:,}")
    if not results['scores_df'].empty:
        print("\n=== FINAL FROZEN 2016-12-31 STRATEGY D TOP 10 ===")
        cols = ["rank_strategy_d", "ticker", "company_name", "score_strategy_d", "market_cap_2016", "pe", "roic", "roe", "revenue_cagr", "quantitative_moat_score"]
        print(results['scores_df'][cols].head(10).to_string(index=False))

