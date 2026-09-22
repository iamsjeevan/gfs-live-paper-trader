"""Pipeline to construct, audit, and validate the historical 2016 US small-cap universe.

Usage:
    python -m pipelines.build_universe --date 2016-12-31 --limit 200
    python -m pipelines.build_universe --date 2016-12-31 --min-cap 50000000 --max-cap 1000000000
"""

import argparse
import sys
from pathlib import Path
import pandas as pd

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from config.settings import (
    DEFAULT_MAX_MARKET_CAP,
    DEFAULT_MIN_MARKET_CAP,
    DEFAULT_SCREEN_DATE,
    PRICE_WORKERS,
    setup_logger,
)
from universe.historical_universe import build_historical_smallcap_universe
from universe.survivorship_audit import audit_price_coverage

logger = setup_logger("pipeline_universe", "screening.log")


def main():
    parser = argparse.ArgumentParser(description="Reconstruct and Audit Historical US Small-Cap Universe")
    parser.add_argument("--date", type=str, default=DEFAULT_SCREEN_DATE, help="Screen date (YYYY-MM-DD)")
    parser.add_argument("--min-cap", type=float, default=DEFAULT_MIN_MARKET_CAP, help="Minimum market cap in USD")
    parser.add_argument("--max-cap", type=float, default=DEFAULT_MAX_MARKET_CAP, help="Maximum market cap in USD")
    parser.add_argument("--include-financials", action="store_true", help="Include financial sector (SIC 6000-6999)")
    parser.add_argument("--all-exchanges", action="store_true", help="Include OTC and non-major exchanges")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of candidates to process")
    parser.add_argument("--workers", type=int, default=PRICE_WORKERS, help="Parallel worker threads")

    args = parser.parse_args()

    eligible_df, excluded_df, stats = build_historical_smallcap_universe(
        screen_date=args.date,
        min_market_cap=args.min_cap,
        max_market_cap=args.max_cap,
        exclude_financials=not args.include_financials,
        require_major_exchange=not args.all_exchanges,
        limit=args.limit,
        workers=args.workers,
        export_csv=True,
    )

    # -------------------------------------------------------------------------
    # 1. Main Universe Summary
    # -------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print(f"{args.date[:4]} HISTORICAL US SMALL-CAP UNIVERSE RECONSTRUCTION")
    print(f"Run ID: {stats.get('run_id')}")
    print("=" * 80)
    print(f"Screen date:             {stats['screen_date']}")
    print(f"Minimum market cap:      ${stats['min_market_cap']/1e6:.0f}M")
    print(f"Maximum market cap:      ${stats['max_market_cap']/1e6:.0f}M")
    print()
    print(f"Companies considered:    {stats['companies_considered']}")
    print(f"Valid historical price:  {stats['valid_historical_price']}")
    print(f"Valid historical shares: {stats['valid_historical_shares']}")
    print(f"Valid market cap:        {stats['valid_market_cap']}")
    print()
    print(f"Final universe:          {stats['final_universe_count']}")
    print(f"Excluded companies:      {stats['excluded_count']}")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # 2. Detailed Exclusion Breakdown
    # -------------------------------------------------------------------------
    if not excluded_df.empty and "status" in excluded_df.columns:
        print("\nExclusion Breakdown by Status:")
        breakdown = excluded_df["status"].value_counts()
        for st, cnt in breakdown.items():
            print(f"  - {st:<22}: {cnt:5d} ({cnt/len(excluded_df)*100:.1f}%)")

    # -------------------------------------------------------------------------
    # 3. Price Coverage Audit Table across Lifecycle Statuses
    # -------------------------------------------------------------------------
    all_records = []
    if not eligible_df.empty:
        all_records.extend(eligible_df.to_dict("records"))
    if not excluded_df.empty:
        all_records.extend(excluded_df.to_dict("records"))

    if all_records:
        cov_df, _ = audit_price_coverage(all_records)
        if not cov_df.empty:
            print("\nHistorical Price Coverage Audit by Lifecycle Status:")
            print(cov_df.to_string(index=False))

    # -------------------------------------------------------------------------
    # 4. Shares Filing Lag Audit (Filing Date vs Screen Date)
    # -------------------------------------------------------------------------
    lag = stats.get("lag_stats", {})
    if lag:
        print("\nHistorical Shares Filing Date Lag Analysis (relative to screen date):")
        print(f"  - Eligible companies evaluated: {lag.get('count')}")
        print(f"  - Mean filing lag:               {lag.get('mean_lag_days', 0):.1f} days")
        print(f"  - Median filing lag:             {lag.get('median_lag_days', 0):.1f} days")
        print(f"  - Min / Max lag:                 {lag.get('min_lag_days', 0)} to {lag.get('max_lag_days', 0)} days")
        print(f"  - Filed within 60 days of date:  {lag.get('within_60_days_pct', 0):.1f}%")
        print(f"  - Filed within 90 days of date:  {lag.get('within_90_days_pct', 0):.1f}%")

    # -------------------------------------------------------------------------
    # 5. Smallest 10 & Largest 10 Companies
    # -------------------------------------------------------------------------
    if not eligible_df.empty:
        print("\nSmallest 10 Companies in Final Universe:")
        s10 = eligible_df.head(10)[["ticker", "company_name", "price_2016", "shares_2016", "market_cap_2016"]].copy()
        s10["price_2016"] = s10["price_2016"].map(lambda x: f"${x:.2f}")
        s10["shares_2016"] = s10["shares_2016"].map(lambda x: f"{x/1e6:.2f}M")
        s10["market_cap_2016"] = s10["market_cap_2016"].map(lambda x: f"${x/1e6:.1f}M")
        print(s10.to_string(index=False))

        print("\nLargest 10 Companies in Final Universe:")
        l10 = eligible_df.tail(10)[["ticker", "company_name", "price_2016", "shares_2016", "market_cap_2016"]].copy()
        l10["price_2016"] = l10["price_2016"].map(lambda x: f"${x:.2f}")
        l10["shares_2016"] = l10["shares_2016"].map(lambda x: f"{x/1e6:.2f}M")
        l10["market_cap_2016"] = l10["market_cap_2016"].map(lambda x: f"${x/1e6:.1f}M")
        print(l10.to_string(index=False))

        # ---------------------------------------------------------------------
        # 6. Market Cap Distribution Percentiles
        # ---------------------------------------------------------------------
        if stats.get("percentiles"):
            p = stats["percentiles"]
            print("\nMarket Cap Distribution Percentiles:")
            print(f"  - 10th percentile: ${p['10th']/1e6:.1f}M")
            print(f"  - 25th percentile: ${p['25th']/1e6:.1f}M")
            print(f"  - Median (50th):   ${p['median']/1e6:.1f}M")
            print(f"  - 75th percentile: ${p['75th']/1e6:.1f}M")
            print(f"  - 90th percentile: ${p['90th']/1e6:.1f}M")

        # ---------------------------------------------------------------------
        # 7. Exchange & Sector Distribution
        # ---------------------------------------------------------------------
        print("\nExchange Distribution:")
        for ex, cnt in stats.get("exchange_distribution", {}).items():
            print(f"  - {ex:<18}: {cnt:4d} ({cnt/len(eligible_df)*100:.1f}%)")

        print("\nTop 10 SIC Industry Distributions:")
        for sic, cnt in stats.get("sic_distribution", {}).items():
            print(f"  - SIC {sic:<6}: {cnt:4d} ({cnt/len(eligible_df)*100:.1f}%)")


if __name__ == "__main__":
    main()
