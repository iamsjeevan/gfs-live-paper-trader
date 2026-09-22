"""SEC Company Facts (XBRL) downloader.

Fetches standardized financial facts across all historical 10-Ks and 10-Qs from:
`https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json`
"""

from pathlib import Path
from typing import Any, Dict, Optional

from config.settings import SEC_COMPANYFACTS_DIR, setup_logger
from .client import SECClient

logger = setup_logger("sec_companyfacts", "sec_download.log")

COMPANYFACTS_BASE_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def get_companyfacts_cache_path(cik: int, base_dir: Optional[Path] = None) -> Path:
    """Return raw cache file path for a company's XBRL facts JSON."""
    target_dir = Path(base_dir) if base_dir else SEC_COMPANYFACTS_DIR
    return target_dir / f"CIK{cik:010d}.json"


def fetch_company_facts(
    cik: int,
    client: Optional[SECClient] = None,
    refresh: bool = False,
    cache_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch raw XBRL company facts from SEC EDGAR API.

    Returns:
        Dict containing facts if found, or None if 404 (e.g. non-reporting entity).
    """
    sec_client = client or SECClient()
    url = COMPANYFACTS_BASE_URL.format(cik=cik)
    cache_path = get_companyfacts_cache_path(cik, cache_dir)
    return sec_client.get(url, cache_path=cache_path, refresh=refresh)
