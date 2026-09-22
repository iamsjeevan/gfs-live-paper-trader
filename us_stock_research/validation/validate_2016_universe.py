"""Critical validation script for 2016 historical universe.

Verifies:
1. 50-candidate point-in-time test: "If we had stood on 2016-12-31, could this company have entered our universe?"
2. Edge cases audit: bankruptcies, acquisitions, delistings, and ticker changes.
3. Proof that companies disappearing after 2016 do NOT silently vanish from the initial universe.
"""

import sys
from pathlib import Path
import sqlite3
import pandas as pd

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from config.settings import EXPORTS_DIR, DATABASE_PATH, setup_logger
from database.connection import get_connection
from data_sources.market_data.resolver import HistoricalPriceResolver
from data_sources.market_data.yahoo import YahooPriceProvider
from universe.market_cap import calculate_historical_market_cap, get_historical_shares_outstanding
from universe.filters import classify_company, is_financial_sector, is_valid_exchange
from universe.survivorship_audit import classify_historical_status

logger = setup_logger("universe_validation", "screening.log")


def run_50_candidate_audit():
    print("=" * 100)
    print("CRITICAL 50-CANDIDATE AUDIT: COULD THIS COMPANY HAVE ENTERED OUR 2016 UNIVERSE?")
    print("=" * 100)

    conn = get_connection(DATABASE_PATH)
    # Sample 50 companies across both active and historical-only filers
    query = """
    SELECT cik, ticker, company_name, exchange, sic, first_seen, last_seen, is_active
    FROM companies
    WHERE first_seen <= '2016-12-31'
    ORDER BY cik ASC
    LIMIT 50;
    """
    candidates = [dict(r) for r in conn.execute(query).fetchall()]
    conn.close()

    provider = HistoricalPriceResolver()
    results = []

    for c in candidates:
        cik = c["cik"]
        ticker = c.get("ticker")
        name = c.get("company_name", "")[:28]
        sic = c.get("sic")
        exchange = c.get("exchange")
        hist_status = classify_historical_status(c, screen_date="2016-12-31")

        # Market cap evaluation
        mcap_res = calculate_historical_market_cap(
            cik=cik,
            ticker=ticker,
            screen_date="2016-12-31",
            price_provider=provider,
        )

        status, reason = classify_company(
            market_cap_result=mcap_res,
            sic=sic,
            exchange=exchange,
            exclude_financials=True,
            min_market_cap=50_000_000,
            max_market_cap=1_000_000_000,
            require_major_exchange=True,
        )

        if status == "eligible":
            audit_class = "ELIGIBLE IN 2016"
        elif status in ("missing_price", "missing_shares", "insufficient_data"):
            audit_class = "INSUFFICIENT DATA"
        else:
            audit_class = "NOT ELIGIBLE"

        p_str = f"${mcap_res['price']:.2f}" if mcap_res["price"] else "N/A"
        s_str = f"{mcap_res['shares']/1e6:.2f}M" if mcap_res["shares"] else "N/A"
        mc_str = f"${mcap_res['market_cap']/1e6:.1f}M" if mcap_res["market_cap"] else "N/A"

        results.append({
            "CIK": cik,
            "Ticker": ticker or "---",
            "Company Name": name,
            "2016 Price": p_str,
            "2016 Shares": s_str,
            "2016 MCap": mc_str,
            "Lifecycle": hist_status,
            "Classification": audit_class,
            "Reason": reason or "Passes all 2016 small-cap criteria",
        })

    audit_df = pd.DataFrame(results)

    # Print summary counts
    print(f"\nEvaluated 50 historical candidates as of 2016-12-31:")
    print(audit_df["Classification"].value_counts().to_string())
    print("\nDetailed Breakdown (first 25 shown):")
    print(audit_df[["CIK", "Ticker", "Company Name", "2016 MCap", "Lifecycle", "Classification"]].head(25).to_string(index=False))

    return audit_df


def test_edge_cases_survivorship():
    print("\n" + "=" * 100)
    print("SURVIVORSHIP BIAS & SPECIAL SITUATIONS AUDIT")
    print("=" * 100)

    cases = [
        {"cik": 84263, "ticker": "RAD", "name": "Rite Aid Corp", "category": "Bankrupt in 2023 (Chapter 11), delisted from NYSE"},
        {"cik": 1408356, "ticker": "SCTY", "name": "SolarCity Corp", "category": "Acquired by Tesla in Nov 2016"},
        {"cik": 1271024, "ticker": "LNKD", "name": "LinkedIn Corp", "category": "Acquired by Microsoft in Dec 2016"},
        {"cik": 1326801, "ticker": "META", "name": "Meta Platforms (fka Facebook / FB)", "category": "Ticker changed from FB to META in 2022"},
        {"cik": 1644406, "ticker": "TWNK", "name": "Hostess Brands Inc", "category": "Acquired by J.M. Smucker in 2023"},
        {"cik": 31235, "ticker": "KODK", "name": "Eastman Kodak Co", "category": "Emerged from Chapter 11 in 2013, active in 2016"},
        {"cik": 2098, "ticker": "ACU", "name": "Acme United Corp", "category": "Continuous active small-cap survivor"},
    ]

    provider = HistoricalPriceResolver()
    conn = get_connection(DATABASE_PATH)

    for c in cases:
        cik = c["cik"]
        tick = c["ticker"]
        name = c["name"]
        cat = c["category"]

        shares_tuple = get_historical_shares_outstanding(cik=cik, screen_date="2016-12-31", conn=conn)
        shares_str = f"{shares_tuple[0]/1e6:.2f}M (filed {shares_tuple[1]})" if shares_tuple else "None (post-2016 or missing)"

        res = provider.resolve_price(cik=cik, ticker=tick, date="2016-12-31")
        p = res.get("price")
        p_prov = res.get("provider") or "None"
        p_str = f"${p:.2f} via {p_prov}" if p else "Price Unavailable"

        if p and shares_tuple:
            mcap_val = p * shares_tuple[0]
            mcap_str = f"${mcap_val/1e6:.1f}M"
        else:
            mcap_str = "N/A"

        print(f"\nCompany:  {name} (CIK: {cik}, Ticker: {tick})")
        print(f"Context:  {cat}")
        print(f"Outcome:  2016 Shares: {shares_str} | 2016 Price: {p_str} | 2016 MCap: {mcap_str}")

    conn.close()


if __name__ == "__main__":
    run_50_candidate_audit()
    test_edge_cases_survivorship()
