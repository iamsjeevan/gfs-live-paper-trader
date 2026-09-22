"""SEC Submissions and filing metadata downloader and parser.

Fetches company metadata and historical filing history from:
`https://data.sec.gov/submissions/CIK{cik:010d}.json`
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import SEC_SUBMISSIONS_DIR, setup_logger
from .client import SECClient

logger = setup_logger("sec_filings", "sec_download.log")

SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def get_submissions_cache_path(cik: int, base_dir: Optional[Path] = None) -> Path:
    """Return the raw cache path for a company's submissions JSON."""
    target_dir = Path(base_dir) if base_dir else SEC_SUBMISSIONS_DIR
    return target_dir / f"CIK{cik:010d}.json"


def fetch_company_submissions(
    cik: int,
    client: Optional[SECClient] = None,
    refresh: bool = False,
    cache_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch raw submission metadata from SEC for a given CIK."""
    sec_client = client or SECClient()
    url = SUBMISSIONS_BASE_URL.format(cik=cik)
    cache_path = get_submissions_cache_path(cik, cache_dir)
    return sec_client.get(url, cache_path=cache_path, refresh=refresh)


def parse_submissions_data(
    data: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Parse raw submissions JSON into company updates and filings list.

    Returns:
        (company_update_dict, filings_list)
    """
    cik = int(data.get("cik", 0))

    # Company updates
    sic_val = None
    if data.get("sic"):
        try:
            sic_val = int(data["sic"])
        except ValueError:
            sic_val = None

    exchanges = data.get("exchanges", [])
    primary_exchange = exchanges[0] if exchanges else None

    # Track historical former names
    former_names = data.get("formerNames", [])
    tickers = data.get("tickers", [])
    primary_ticker = tickers[0] if tickers else None

    company_update = {
        "cik": cik,
        "ticker": primary_ticker,
        "company_name": data.get("name", "").strip(),
        "exchange": primary_exchange,
        "sic": sic_val,
        "sic_description": data.get("sicDescription"),
        "metadata_json": json.dumps({
            "former_names": former_names,
            "all_tickers": tickers,
            "fiscal_year_end": data.get("fiscalYearEnd"),
            "state_of_incorporation": data.get("stateOfIncorporation"),
        }),
    }

    # Filings list
    filings: List[Dict[str, Any]] = []
    recent = data.get("filings", {}).get("recent", {})
    if recent and "accessionNumber" in recent:
        acc_nums = recent.get("accessionNumber", [])
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        fy_list = recent.get("fiscalYear", [])
        fp_list = recent.get("fiscalPeriod", [])
        primary_docs = recent.get("primaryDocument", [])

        num_records = len(acc_nums)
        for i in range(num_records):
            try:
                acc_num = acc_nums[i]
                form_type = forms[i] if i < len(forms) else ""
                f_date = filing_dates[i] if i < len(filing_dates) else ""
                r_date = report_dates[i] if i < len(report_dates) else None
                fy_val = None
                if i < len(fy_list) and fy_list[i]:
                    try:
                        fy_val = int(fy_list[i])
                    except ValueError:
                        fy_val = None
                fp_val = fp_list[i] if i < len(fp_list) else None
                prim_doc = primary_docs[i] if i < len(primary_docs) else None

                filings.append({
                    "accession_number": acc_num,
                    "cik": cik,
                    "form": form_type,
                    "filing_date": f_date,
                    "report_date": r_date,
                    "fiscal_year": fy_val,
                    "fiscal_period": fp_val,
                    "primary_document": prim_doc,
                })
            except IndexError:
                continue

    return company_update, filings
