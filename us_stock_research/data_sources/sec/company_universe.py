"""SEC Company Universe discovery and normalization.

Fetches the complete directory of SEC reporting companies from EDGAR,
extracts CIKs, tickers, company names, and trading exchanges, and persists
them into the local SQLite database.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import sqlite3

from config.settings import CACHE_DIR, setup_logger
from database.repositories.companies import CompanyRepository
from .client import SECClient

logger = setup_logger("company_universe", "sec_download.log")

SEC_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def fetch_sec_company_universe(
    client: Optional[SECClient] = None,
    refresh: bool = False,
    cache_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Fetch all publicly registered companies from SEC EDGAR.

    Args:
        client: Optional SECClient instance.
        refresh: If True, bypass cached file and download fresh.
        cache_dir: Directory to store cached JSON.

    Returns:
        List of normalized company dicts with keys:
        ['cik', 'ticker', 'company_name', 'exchange']
    """
    sec_client = client or SECClient()
    cdir = Path(cache_dir) if cache_dir else CACHE_DIR
    cache_path = cdir / "sec_company_tickers_exchange.json"

    logger.info("Fetching SEC company ticker directory...")
    data = sec_client.get(SEC_TICKERS_EXCHANGE_URL, cache_path=cache_path, refresh=refresh)

    companies: List[Dict[str, Any]] = []

    if data and "data" in data and "fields" in data:
        fields = data["fields"]
        cik_idx = fields.index("cik") if "cik" in fields else 0
        name_idx = fields.index("name") if "name" in fields else 1
        ticker_idx = fields.index("ticker") if "ticker" in fields else 2
        exchange_idx = fields.index("exchange") if "exchange" in fields else 3

        for row in data["data"]:
            try:
                cik_val = int(row[cik_idx])
                name_val = str(row[name_idx]).strip()
                ticker_val = str(row[ticker_idx]).strip().upper() if row[ticker_idx] else None
                exchange_val = str(row[exchange_idx]).strip() if row[exchange_idx] else None

                companies.append({
                    "cik": cik_val,
                    "ticker": ticker_val,
                    "company_name": name_val,
                    "exchange": exchange_val,
                    "is_active": 1,
                })
            except (ValueError, IndexError) as err:
                logger.debug(f"Skipping malformed row {row}: {err}")
                continue

    elif not companies:
        # Fallback to standard company_tickers.json
        fallback_cache = cdir / "sec_company_tickers.json"
        logger.info("Falling back to company_tickers.json...")
        fb_data = sec_client.get(SEC_TICKERS_URL, cache_path=fallback_cache, refresh=refresh)
        if fb_data:
            for item in fb_data.values():
                try:
                    companies.append({
                        "cik": int(item["cik_str"]),
                        "ticker": str(item.get("ticker", "")).strip().upper() or None,
                        "company_name": str(item.get("title", "")).strip(),
                        "exchange": None,
                        "is_active": 1,
                    })
                except (KeyError, ValueError):
                    continue

    logger.info(f"Loaded {len(companies)} companies from SEC universe.")
    return companies


def sync_sec_universe_to_db(
    conn: sqlite3.Connection,
    companies: Optional[List[Dict[str, Any]]] = None,
    client: Optional[SECClient] = None,
    refresh: bool = False,
) -> int:
    """Download SEC company universe and synchronize into the SQLite companies table.

    Returns:
        Number of companies inserted/updated.
    """
    if companies is None:
        companies = fetch_sec_company_universe(client=client, refresh=refresh)

    repo = CompanyRepository(conn)
    count = repo.upsert_companies_batch(companies)
    conn.commit()
    logger.info(f"Synchronized {count} companies to database.")
    return count
