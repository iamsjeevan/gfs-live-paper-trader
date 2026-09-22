"""Resumable parallel downloader for SEC EDGAR company facts and submissions.

Features:
- Multi-threaded execution via ThreadPoolExecutor with configurable concurrency
- Resumable: tracks status of every entity in SQLite `download_status` table
- Automatic rate-limiting and exponential backoff
- Graceful shutdown and progress reporting
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import time

from config.settings import SEC_WORKERS, setup_logger
from database.connection import get_connection
from database.repositories.downloads import DownloadStatusRepository
from .client import SECClient
from .companyfacts import COMPANYFACTS_BASE_URL, fetch_company_facts, get_companyfacts_cache_path
from .filings import SUBMISSIONS_BASE_URL, fetch_company_submissions, get_submissions_cache_path

logger = setup_logger("sec_downloader", "sec_download.log")


def download_single_company(
    cik: int,
    task_type: str,
    client: SECClient,
    db_path: Optional[Path] = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Download SEC data for a single company and update its status in SQLite.

    Args:
        cik: Company CIK.
        task_type: 'sec_companyfacts' or 'sec_submissions'.
        client: SECClient instance.
        db_path: Path to SQLite database.
        refresh: Force re-download even if previously completed.

    Returns:
        Result summary dict.
    """
    conn = get_connection(db_path)
    status_repo = DownloadStatusRepository(conn)

    source_url = (
        COMPANYFACTS_BASE_URL.format(cik=cik)
        if task_type == "sec_companyfacts"
        else SUBMISSIONS_BASE_URL.format(cik=cik)
    )

    status_repo.record_start(task_type, str(cik), source_url=source_url)
    conn.commit()

    try:
        if task_type == "sec_companyfacts":
            data = fetch_company_facts(cik, client=client, refresh=refresh)
            cache_file = str(get_companyfacts_cache_path(cik))
        else:
            data = fetch_company_submissions(cik, client=client, refresh=refresh)
            cache_file = str(get_submissions_cache_path(cik))

        if data is not None:
            status_repo.record_success(task_type, str(cik), http_status=200, file_path=cache_file)
            conn.commit()
            return {"cik": cik, "status": "COMPLETED", "http_status": 200}
        else:
            # 404 / not found on SEC
            status_repo.record_failure(task_type, str(cik), error_message="Not found on SEC", http_status=404)
            conn.commit()
            return {"cik": cik, "status": "NOT_FOUND", "http_status": 404}

    except Exception as exc:
        err_msg = str(exc)
        logger.error(f"Download failed for CIK {cik} ({task_type}): {err_msg}")
        status_repo.record_failure(task_type, str(cik), error_message=err_msg, http_status=500)
        conn.commit()
        return {"cik": cik, "status": "FAILED", "error": err_msg}
    finally:
        conn.close()


def download_all_sec_data(
    ciks: List[int],
    task_type: str = "sec_companyfacts",
    workers: int = SEC_WORKERS,
    resume: bool = True,
    refresh: bool = False,
    db_path: Optional[Path] = None,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    """Download SEC data for a list of CIKs using controlled parallelism and resume tracking.

    Args:
        ciks: List of integer CIKs.
        task_type: 'sec_companyfacts' or 'sec_submissions'.
        workers: Number of parallel worker threads.
        resume: If True, skip CIKs already marked as COMPLETED or NOT_FOUND in database.
        refresh: If True, ignore previous completion status and re-download.
        db_path: Database path.
        limit: Optional maximum number of companies to download.

    Returns:
        Dict of status counts: {'COMPLETED': int, 'FAILED': int, 'NOT_FOUND': int, 'SKIPPED': int}
    """
    conn = get_connection(db_path)
    status_repo = DownloadStatusRepository(conn)

    # Determine already completed items
    completed_set: Set[str] = set()
    if resume and not refresh:
        completed_set = status_repo.get_completed_entity_ids(task_type)
    conn.close()

    # Filter targets
    targets_to_download = []
    skipped_count = 0

    for cik in ciks:
        if str(cik) in completed_set:
            skipped_count += 1
        else:
            targets_to_download.append(cik)

    if limit is not None:
        targets_to_download = targets_to_download[:limit]

    total_targets = len(targets_to_download)
    logger.info(
        f"Starting SEC download for {task_type}: {total_targets} to download, "
        f"{skipped_count} skipped (already completed), workers={workers}"
    )

    counts = {
        "COMPLETED": 0,
        "FAILED": 0,
        "NOT_FOUND": 0,
        "SKIPPED": skipped_count,
    }

    if not targets_to_download:
        return counts

    client = SECClient()
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                download_single_company,
                cik,
                task_type,
                client,
                db_path,
                refresh,
            ): cik
            for cik in targets_to_download
        }

        for idx, future in enumerate(as_completed(futures), start=1):
            res = future.result()
            st = res.get("status", "FAILED")
            counts[st] = counts.get(st, 0) + 1

            if idx % 10 == 0 or idx == total_targets:
                elapsed = time.time() - t0
                speed = idx / elapsed if elapsed > 0 else 0
                logger.info(
                    f"Progress [{idx}/{total_targets}] ({idx/total_targets*100:.1f}%): "
                    f"{counts['COMPLETED']} completed, {counts['NOT_FOUND']} 404, "
                    f"{counts['FAILED']} failed ({speed:.1f} req/s)"
                )

    total_elapsed = time.time() - t0
    logger.info(
        f"Finished SEC download for {task_type} in {total_elapsed:.1f}s. "
        f"Summary: {counts}"
    )
    return counts
