"""Historical listing builder and synchronization engine.

Builds and persists the `historical_listings` table as the permanent bridge
between SEC CIK entities and market-data trading identities.

Ensures:
- Every entity has a classified `security_type` ('COMMON_EQUITY', 'PREFERRED', 'DEBT', 'ETF/FUND', 'REIT', 'ADR', 'OTHER')
- Time-varying listings (start/end dates) are preserved
- Multiple tickers or historical ticker changes for a single CIK are linked
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3

from config.settings import DATABASE_PATH, setup_logger
from database.connection import get_connection
from database.repositories.historical_listings import HistoricalListingRepository
from .security_type import classify_security_type

logger = setup_logger("historical_listings", "screening.log")


def sync_historical_listings(
    db_path: Optional[Path] = None,
    screen_date: str = "2016-12-31",
    limit: Optional[int] = None,
) -> int:
    """Populate and synchronize historical_listings table from companies and filings.

    Returns:
        Number of listings inserted/synchronized.
    """
    database_file = db_path or DATABASE_PATH
    conn = get_connection(database_file)
    repo = HistoricalListingRepository(conn)

    # 1. Fetch companies
    sql = """
    SELECT cik, ticker, company_name, exchange, sic, first_seen, last_seen, is_active, metadata_json
    FROM companies
    WHERE first_seen <= ?
    ORDER BY cik ASC;
    """
    candidates = [dict(r) for r in conn.execute(sql, (screen_date,)).fetchall()]

    if limit is not None:
        candidates = candidates[:limit]

    # Pre-fetch forms filed per CIK to detect ADRs / funds
    cur = conn.cursor()
    filing_forms_map = {}
    forms_rows = cur.execute("SELECT cik, DISTINCT form FROM filings;").fetchall() if False else []
    # Query distinct forms per CIK
    for row in cur.execute("SELECT cik, form FROM filings GROUP BY cik, form;").fetchall():
        cik, f = row[0], row[1]
        filing_forms_map.setdefault(cik, []).append(f)

    listings_to_insert = []

    for comp in candidates:
        cik = comp["cik"]
        ticker = comp.get("ticker")
        name = comp.get("company_name", "")
        exchange = comp.get("exchange")
        sic = comp.get("sic")
        forms = filing_forms_map.get(cik, ["10-K"])

        # Determine security type
        sec_type = classify_security_type(
            ticker=ticker,
            company_name=name,
            sic=sic,
            forms=forms,
        )

        # Parse any additional former tickers from metadata_json
        all_tickers = [ticker] if ticker else []
        meta_str = comp.get("metadata_json")
        if meta_str:
            try:
                meta = json.loads(meta_str)
                extra = meta.get("all_tickers", [])
                for et in extra:
                    if et and et not in all_tickers:
                        all_tickers.append(et)
            except Exception:
                pass

        if not all_tickers:
            # Delisted company with no ticker recorded in modern directory
            listings_to_insert.append({
                "cik": cik,
                "ticker": None,
                "company_name": name,
                "exchange": exchange,
                "security_type": sec_type,
                "listing_start_date": comp.get("first_seen"),
                "listing_end_date": comp.get("last_seen"),
                "source": "sec_edgar_index",
                "confidence": 0.8,
            })
        else:
            for idx, t in enumerate(all_tickers):
                listings_to_insert.append({
                    "cik": cik,
                    "ticker": t,
                    "company_name": name,
                    "exchange": exchange,
                    "security_type": sec_type,
                    "listing_start_date": comp.get("first_seen"),
                    "listing_end_date": comp.get("last_seen") if comp.get("is_active") == 0 else None,
                    "source": "sec_submissions" if idx > 0 else "sec_directory",
                    "confidence": 1.0 if idx == 0 else 0.9,
                })

    # Clear previous sync for screen run or upsert
    conn.execute("DELETE FROM historical_listings;")
    conn.commit()

    inserted = repo.upsert_listings_batch(listings_to_insert)
    conn.commit()
    conn.close()

    logger.info(f"Synchronized {inserted} records into historical_listings table.")
    return inserted
