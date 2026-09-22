"""Pipeline to screen, score, and rank the 2016 US small-cap universe.

Applies strict point-in-time fundamental quality filters, computes multi-year growth,
valuation multiples, and quantitative moat proxies, and evaluates four strategy variants:
  - Strategy A: Quality Only
  - Strategy B: Quality + Growth
  - Strategy C: Quality + Growth + Value
  - Strategy D: Full Strategy (Quality + Growth + Value + Moat)

Usage:
    python -m pipelines.screen_universe --date 2016-12-31
    python -m pipelines.screen_universe --date 2016-12-31 --top-n 10
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import pandas as pd

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
from database.repositories.screens import ScreenRepository
from fundamentals.engine import PointInTimeFundamentalsEngine
from screening.filters import QualityFilterConfig, evaluate_quality_filters
from screening.scoring import score_universe_candidates

logger = setup_logger("screen_pipeline", "screening.log")


def run_screening_pipeline(
    screen_date: str = DEFAULT_SCREEN_DATE,
    universe_csv: Optional[str] = None,
    min_market_cap: float = DEFAULT_MIN_MARKET_CAP,
    max_market_cap: float = DEFAULT_MAX_MARKET_CAP,
    top_n: int = 10,
    export_csv: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Execute the complete fundamental screening and multi-factor ranking pipeline."""
    # 1. Load historical universe
    csv_path = Path(universe_csv) if universe_csv else EXPORTS_DIR / f"historical_universe_{screen_date.replace('-', '')}.csv"
    if not csv_path.exists():
        fallback_path = EXPORTS_DIR / "historical_universe_20161231.csv"
        if fallback_path.exists():
            csv_path = fallback_path
        else:
            raise FileNotFoundError(f"Historical universe CSV not found at {csv_path}")

    logger.info(f"Loading historical universe from {csv_path}")
    universe_df = pd.read_csv(csv_path)

    # 2. Compute Point-in-Time Fundamentals
    logger.info(f"Computing point-in-time fundamentals as of {screen_date}...")
    engine = PointInTimeFundamentalsEngine(screen_date=screen_date)
    filter_config = QualityFilterConfig()

    all_candidates: List[Dict[str, Any]] = []
    passers: List[Dict[str, Any]] = []
    failures_log: List[Dict[str, Any]] = []

    for _, row in universe_df.iterrows():
        cik = int(row["cik"])
        ticker = str(row.get("ticker", ""))
        mcap = float(row["market_cap_2016"]) if pd.notnull(row.get("market_cap_2016")) else None
        price = float(row["price_2016"]) if pd.notnull(row.get("price_2016")) else None

        f = engine.compute_company_fundamentals(
            cik=cik,
            ticker=ticker,
            market_cap_2016=mcap,
        )
        # Enrich metadata
        f["company_name"] = row.get("company_name", "")
        f["exchange"] = row.get("exchange", "")
        f["sic"] = row.get("sic", "")
        f["price"] = price
        f["market_cap"] = mcap

        passes, fail_reasons = evaluate_quality_filters(f, filter_config)
        f["passes_filters"] = passes
        f["failure_reasons"] = "; ".join(fail_reasons) if fail_reasons else ""

        all_candidates.append(f)
        if passes:
            passers.append(f)
        else:
            failures_log.append(f)

    logger.info(f"Universe evaluation complete: {len(passers)} passed strict quality filters, {len(failures_log)} failed.")

    # 3. Score across all 4 strategy variants
    scoring_candidates = passers if len(passers) >= 10 else [c for c in all_candidates if c.get("data_completeness_score", 0) >= 0.40]
    strategy_results = score_universe_candidates(scoring_candidates)

    # 4. Save to Database
    conn = get_connection()
    repo = ScreenRepository(conn)
    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    for strat_name, res_df in strategy_results.items():
        clean_strat = strat_name.split("(")[0].strip().replace(" ", "_").lower()
        run_id = f"screen_{screen_date.replace('-', '')}_{clean_strat}_{timestamp_str}"

        repo.save_screen_run(
            run_id=run_id,
            screen_date=screen_date,
            strategy_name=strat_name,
            min_market_cap=min_market_cap,
            max_market_cap=max_market_cap,
            weights={"strategy": strat_name},
            hard_filters=filter_config.to_dict(),
        )

        db_records = []
        for _, r in res_df.iterrows():
            rec = {
                "cik": int(r["cik"]),
                "ticker": r["ticker"],
                "company_name": r.get("company_name"),
                "score": float(r.get("composite_score", 0.0)),
                "rank": int(r.get("rank", 0)),
                "market_cap": float(r["market_cap"]) if pd.notnull(r.get("market_cap")) else None,
                "price": float(r["price"]) if pd.notnull(r.get("price")) else None,
                "roe": float(r["roe"]) if pd.notnull(r.get("roe")) else None,
                "roic": float(r["roic"]) if pd.notnull(r.get("roic")) else None,
                "revenue_growth": float(r["revenue_growth"]) if pd.notnull(r.get("revenue_growth")) else None,
                "earnings_growth": float(r["net_income_growth"]) if pd.notnull(r.get("net_income_growth")) else None,
                "fcf_growth": float(r["fcf_growth"]) if pd.notnull(r.get("fcf_growth")) else None,
                "debt_equity": float(r["debt_equity"]) if pd.notnull(r.get("debt_equity")) else None,
                "operating_margin": float(r["operating_margin"]) if pd.notnull(r.get("operating_margin")) else None,
                "fcf_margin": float(r["fcf_margin"]) if pd.notnull(r.get("fcf_margin")) else None,
                "moat_score": float(r["quantitative_moat_score"]) if pd.notnull(r.get("quantitative_moat_score")) else None,
                "data_quality_flags": str(r.get("data_quality_flags", "CLEAN")),
            }
            db_records.append(rec)

        repo.save_screen_results_batch(run_id, db_records)
        conn.commit()

    conn.close()

    # Export quality_passed.csv
    passed_file = EXPORTS_DIR / "quality_passed.csv"
    pd.DataFrame(passers).to_csv(passed_file, index=False)
    logger.info(f"Saved {len(passers)} passing companies to {passed_file}")

    # 5. Export comprehensive screening CSV
    if export_csv:
        export_file = EXPORTS_DIR / f"screening_results_{screen_date.replace('-', '')}.csv"
        # Compile multi-strategy comparison table
        d_df = strategy_results.get("Strategy D (Full Strategy: Quality + Growth + Value + Moat)", pd.DataFrame())
        a_df = strategy_results.get("Strategy A (Quality Only)", pd.DataFrame())
        b_df = strategy_results.get("Strategy B (Quality + Growth)", pd.DataFrame())
        c_df = strategy_results.get("Strategy C (Quality + Growth + Value)", pd.DataFrame())

        export_records = []
        for _, r in d_df.iterrows():
            cik = r["cik"]
            rank_a = a_df[a_df["cik"] == cik]["rank"].iloc[0] if not a_df.empty and (a_df["cik"] == cik).any() else None
            rank_b = b_df[b_df["cik"] == cik]["rank"].iloc[0] if not b_df.empty and (b_df["cik"] == cik).any() else None
            rank_c = c_df[c_df["cik"] == cik]["rank"].iloc[0] if not c_df.empty and (c_df["cik"] == cik).any() else None
            rank_d = r["rank"]

            export_records.append({
                "cik": cik,
                "ticker": r["ticker"],
                "company_name": r.get("company_name"),
                "screen_date": screen_date,
                "rank_strategy_a": rank_a,
                "rank_strategy_b": rank_b,
                "rank_strategy_c": rank_c,
                "rank_strategy_d": rank_d,
                "score_strategy_d": r["composite_score"],
                "market_cap_2016": r.get("market_cap"),
                "price_2016": r.get("price"),
                "roe": r.get("roe"),
                "roic": r.get("roic"),
                "roic_gross": r.get("roic_gross"),
                "debt_equity": r.get("debt_equity"),
                "operating_margin": r.get("operating_margin"),
                "fcf_margin": r.get("fcf_margin"),
                "revenue_growth": r.get("revenue_growth"),
                "revenue_cagr": r.get("revenue_cagr"),
                "net_income_cagr": r.get("net_income_cagr"),
                "fcf_cagr": r.get("fcf_cagr"),
                "growth_consistency": r.get("growth_consistency"),
                "growth_quality_flag": r.get("growth_quality_flag"),
                "pe": r.get("pe"),
                "ev_ebitda": r.get("ev_ebitda"),
                "price_fcf": r.get("price_fcf"),
                "quantitative_moat_score": r.get("quantitative_moat_score"),
                "moat_gm_stability": r.get("moat_gm_stability"),
                "moat_op_persistence": r.get("moat_op_persistence"),
                "moat_roic_spread": r.get("moat_roic_spread"),
                "moat_fcf_durability": r.get("moat_fcf_durability"),
                "moat_capex_intensity": r.get("moat_capex_intensity"),
                "filing_date": r.get("filing_date"),
                "period_end": r.get("period_end"),
                "passes_filters": r.get("passes_filters"),
                "failure_reasons": r.get("failure_reasons"),
            })

        exp_df = pd.DataFrame(export_records)
        exp_df.to_csv(export_file, index=False)
        logger.info(f"Screening export saved to {export_file} ({len(exp_df)} records)")


    return strategy_results


def main():
    parser = argparse.ArgumentParser(description="Point-in-Time Fundamental Screening and Multi-Factor Ranking")
    parser.add_argument("--date", type=str, default=DEFAULT_SCREEN_DATE, help="Screen date (YYYY-MM-DD)")
    parser.add_argument("--min-cap", type=float, default=DEFAULT_MIN_MARKET_CAP, help="Minimum market cap in USD")
    parser.add_argument("--max-cap", type=float, default=DEFAULT_MAX_MARKET_CAP, help="Maximum market cap in USD")
    parser.add_argument("--top-n", type=int, default=10, help="Top N candidates to display")
    args = parser.parse_args()

    results = run_screening_pipeline(
        screen_date=args.date,
        min_market_cap=args.min_cap,
        max_market_cap=args.max_cap,
        top_n=args.top_n,
        export_csv=True,
    )

    print("\n" + "=" * 90)
    print(f"HISTORICAL POINT-IN-TIME SCREENING & SCORING ({args.date})")
    print("=" * 90)

    for strat_name, df in results.items():
        print(f"\n>>> {strat_name} (Top {args.top_n}) <<<")
        cols = [
            "rank", "ticker", "company_name", "composite_score",
            "roe", "roic", "revenue_cagr", "growth_quality_flag", "pe", "debt_equity", "quantitative_moat_score"
        ]
        avail = [c for c in cols if c in df.columns]
        display_df = df[avail].head(args.top_n).copy()
        # Format percentages and decimals
        if "composite_score" in display_df:
            display_df["composite_score"] = display_df["composite_score"].apply(lambda x: f"{x:.1f}" if pd.notnull(x) else "")
        if "roe" in display_df:
            display_df["roe"] = display_df["roe"].apply(lambda x: f"{x*100:.1f}%" if pd.notnull(x) else "N/A")
        if "roic" in display_df:
            display_df["roic"] = display_df["roic"].apply(lambda x: f"{x*100:.1f}%" if pd.notnull(x) else "N/A")
        if "revenue_cagr" in display_df:
            display_df["revenue_cagr"] = display_df["revenue_cagr"].apply(lambda x: f"{x*100:.1f}%" if pd.notnull(x) else "N/A")
        if "pe" in display_df:
            display_df["pe"] = display_df["pe"].apply(lambda x: f"{x:.1f}x" if pd.notnull(x) else "N/A")
        if "debt_equity" in display_df:
            display_df["debt_equity"] = display_df["debt_equity"].apply(lambda x: f"{x:.2f}" if pd.notnull(x) else "0.00")
        if "quantitative_moat_score" in display_df:
            display_df["quantitative_moat_score"] = display_df["quantitative_moat_score"].apply(lambda x: f"{x:.2f}" if pd.notnull(x) else "")

        print(display_df.to_string(index=False))


if __name__ == "__main__":
    main()
