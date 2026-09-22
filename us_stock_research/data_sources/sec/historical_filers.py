"""Historical SEC Filer Discovery using EDGAR Full-Index Archives.

Downloads and parses quarterly master index files from SEC EDGAR for calendar year 2016:
`https://www.sec.gov/Archives/edgar/full-index/2016/QTR{1..4}/master.gz`

This discovers all companies that actively filed periodic reports (10-K, 10-Q) with the SEC
during 2016, specifically capturing companies that subsequently:
- went bankrupt
- were acquired
- merged
- were delisted
and therefore no longer appear in the SEC's current active ticker list.
"""

import gzip
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import sqlite3

from config.settings import RAW_DATA_DIR, setup_logger
from database.connection import get_connection
from database.repositories.companies import CompanyRepository
from .client import SECClient

logger = setup_logger("historical_filers", "sec_download.log")

INDEX_DIR = RAW_DATA_DIR / "sec" / "indexes"
INDEX_DIR.mkdir(parents=True, exist_ok=True)

MASTER_URL_TEMPLATE = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{qtr}/master.gz"


def fetch_historical_filers_for_year(
    year: int = 2016,
    client: Optional[SECClient] = None,
    refresh: bool = False,
) -> Dict[int, Dict[str, Any]]:
    """Download EDGAR master indexes for all 4 quarters of `year` and extract periodic filers.

    Returns:
        Dict[cik, {
            'cik': int,
            'company_name': str,
            'forms_filed': List[str],
            'first_filing_2016': str,
            'last_filing_2016': str,
        }]
    """
    sec_client = client or SECClient()
    filers: Dict[int, Dict[str, Any]] = {}

    target_forms = {"10-K", "10-Q", "10-K/A", "10-Q/A"}

    for qtr in range(1, 5):
        cache_path = INDEX_DIR / f"{year}_QTR{qtr}_master.gz"
        url = MASTER_URL_TEMPLATE.format(year=year, qtr=qtr)

        logger.info(f"Retrieving SEC master index for {year} QTR{qtr}...")

        # If cache exists and not refresh, read local file
        if cache_path.exists() and not refresh:
            with open(cache_path, "rb") as f:
                content = f.read()
        else:
            # Download via client
            sec_client.rate_limiter.wait()
            resp = sec_client.session.get(url, timeout=30.0)
            resp.raise_for_status()
            content = resp.content
            # Write cache
            with open(cache_path, "wb") as f:
                f.write(content)

        # Decompress gzip
        try:
            decompressed = gzip.decompress(content).decode("latin-1", errors="ignore")
        except Exception as exc:
            logger.error(f"Failed to decompress {cache_path}: {exc}")
            continue

        lines = decompressed.splitlines()
        for line in lines:
            parts = line.split("|")
            if len(parts) >= 5:
                cik_str = parts[0].strip()
                company_name = parts[1].strip()
                form_type = parts[2].strip()
                date_filed = parts[3].strip()

                if form_type in target_forms:
                    try:
                        cik = int(cik_str)
                    except ValueError:
                        continue

                    if cik not in filers:
                        filers[cik] = {
                            "cik": cik,
                            "company_name": company_name,
                            "forms_filed": [form_type],
                            "first_filing_2016": date_filed,
                            "last_filing_2016": date_filed,
                        }
                    else:
                        filers[cik]["forms_filed"].append(form_type)
                        if date_filed < filers[cik]["first_filing_2016"]:
                            filers[cik]["first_filing_2016"] = date_filed
                        if date_filed > filers[cik]["last_filing_2016"]:
                            filers[cik]["last_filing_2016"] = date_filed

    logger.info(f"Discovered {len(filers)} unique periodic reporting companies (10-K/10-Q) in {year}.")
    return filers


def sync_historical_filers_to_db(
    year: int = 2016,
    conn: Optional[sqlite3.Connection] = None,
    client: Optional[SECClient] = None,
    refresh: bool = False,
) -> Dict[str, int]:
    """Sync historical filers from EDGAR indexes into the SQLite database.

    Marks companies with `first_seen <= '{year}-12-31'`.

    Returns:
        Summary dict with counts of new filers added vs existing updated.
    """
    filers = fetch_historical_filers_for_year(year=year, client=client, refresh=refresh)
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    company_repo = CompanyRepository(conn)
    existing_ciks = set(r[0] for r in conn.execute("SELECT cik FROM companies").fetchall())

    new_companies: List[Dict[str, Any]] = []
    updated_count = 0

    for cik, info in filers.items():
        if cik not in existing_ciks:
            new_companies.append({
                "cik": cik,
                "ticker": None,  # Will be discovered from submissions or ticker mapping
                "company_name": info["company_name"],
                "exchange": None,
                "first_seen": f"{year}-01-01",
                "last_seen": info["last_filing_2016"],
                "is_active": 0,  # Delisted/inactive today unless confirmed otherwise
            })
        else:
            updated_count += 1
            # Ensure first_seen is recorded as historical
            conn.execute(
                "UPDATE companies SET first_seen = COALESCE(first_seen, ?) WHERE cik = ?",
                (f"{year}-01-01", cik),
            )

    inserted_count = company_repo.upsert_companies_batch(new_companies)
    conn.commit()

    if should_close:
        conn.close()

    logger.info(f"Historical filers sync for {year}: {inserted_count} historical-only companies added, {updated_count} existing updated.")
    return {
        "total_2016_filers": len(filers),
        "historical_only_added": inserted_count,
        "existing_matched": updated_count,
    }
