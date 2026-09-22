"""Pipeline script to discover SEC universe, download XBRL company facts, and persist to SQLite.

Usage:
    python -m pipelines.download_sec --sync-universe
    python -m pipelines.download_sec --download-facts --limit 50
    python -m pipelines.download_sec --all --limit 20
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from config.settings import DATABASE_PATH, SEC_WORKERS, setup_logger
from database.connection import get_connection
from database.repositories.companies import CompanyRepository
from database.repositories.filings import FilingRepository
from database.repositories.fundamentals import FundamentalRepository
from database.schema import init_db
from data_sources.sec.company_universe import sync_sec_universe_to_db
from data_sources.sec.companyfacts import fetch_company_facts
from data_sources.sec.downloader import download_all_sec_data
from data_sources.sec.parser import parse_company_facts

logger = setup_logger("pipeline_sec", "sec_download.log")


def run_pipeline(
    sync_universe: bool = True,
    download_submissions: bool = False,
    download_facts: bool = False,
    parse_to_db: bool = False,
    limit: int = None,
    workers: int = SEC_WORKERS,
    refresh: bool = False,
    resume: bool = True,
    db_path: Path = DATABASE_PATH,
):
    """Execute the SEC data pipeline."""
    logger.info("=" * 80)
    logger.info("STARTING SEC DATA PIPELINE")
    logger.info(f"Database: {db_path}")
    logger.info("=" * 80)

    # 1. Initialize schema
    init_db(db_path)
    conn = get_connection(db_path)

    # 2. Sync Company Universe
    if sync_universe:
        logger.info("Step 1: Synchronizing SEC company universe...")
        count = sync_sec_universe_to_db(conn, refresh=refresh)
        print(f"✓ Synchronized {count} SEC companies to database.")

    # 3. Download Company Submissions (SIC, Former Names, Filing History)
    if download_submissions:
        logger.info("Step 2a: Downloading SEC company submissions...")
        company_repo = CompanyRepository(conn)
        filing_repo = FilingRepository(conn)
        companies = company_repo.list_all(limit=limit)
        ciks = [c["cik"] for c in companies]

        print(f"Targeting {len(ciks)} companies for submissions download (workers={workers})...")
        summary = download_all_sec_data(
            ciks=ciks,
            task_type="sec_submissions",
            workers=workers,
            resume=resume,
            refresh=refresh,
            db_path=db_path,
        )
        print(f"✓ Submissions Download Summary: {summary}")

        # Update SIC and company metadata from cached submissions
        for comp in companies:
            cik = comp["cik"]
            from data_sources.sec.filings import fetch_company_submissions, parse_submissions_data
            sub_data = fetch_company_submissions(cik, refresh=False)
            if sub_data:
                comp_update, filings = parse_submissions_data(sub_data)
                company_repo.upsert_company(comp_update)
                if filings:
                    filing_repo.upsert_filings_batch(filings)
        conn.commit()

    # 4. Download Company Facts (XBRL)
    if download_facts:
        logger.info("Step 2b: Downloading SEC XBRL company facts...")
        company_repo = CompanyRepository(conn)
        companies = company_repo.list_all(limit=limit)
        ciks = [c["cik"] for c in companies]

        print(f"Targeting {len(ciks)} companies for facts download (workers={workers})...")
        summary = download_all_sec_data(
            ciks=ciks,
            task_type="sec_companyfacts",
            workers=workers,
            resume=resume,
            refresh=refresh,
            db_path=db_path,
        )
        print(f"✓ Facts Download Summary: {summary}")

    # 4. Parse Downloaded Facts into SQLite fundamentals table
    if parse_to_db:
        logger.info("Step 3: Parsing cached XBRL facts into fundamentals table...")
        company_repo = CompanyRepository(conn)
        fund_repo = FundamentalRepository(conn)
        companies = company_repo.list_all(limit=limit)

        total_records_inserted = 0
        parsed_companies = 0

        for comp in companies:
            cik = comp["cik"]
            ticker = comp.get("ticker")
            # Read from raw cache
            facts_data = fetch_company_facts(cik, refresh=False)
            if facts_data:
                records = parse_company_facts(facts_data, ticker=ticker, annual_only=True)
                if records:
                    inserted = fund_repo.upsert_fundamentals_batch(records)
                    total_records_inserted += inserted
                    parsed_companies += 1

        conn.commit()
        print(f"✓ Parsed {total_records_inserted} annual fundamental records for {parsed_companies} companies.")

    conn.close()
    logger.info("SEC DATA PIPELINE COMPLETE.")


def main():
    parser = argparse.ArgumentParser(description="SEC EDGAR Data Pipeline")
    parser.add_argument("--sync-universe", action="store_true", help="Download and sync SEC company universe")
    parser.add_argument("--download-submissions", action="store_true", help="Download SEC submissions metadata (SIC, tickers)")
    parser.add_argument("--download-facts", action="store_true", help="Download SEC XBRL company facts")
    parser.add_argument("--parse-facts", action="store_true", help="Parse downloaded facts into database")
    parser.add_argument("--all", action="store_true", help="Run full pipeline: sync, download, and parse")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of companies to process")
    parser.add_argument("--workers", type=int, default=SEC_WORKERS, help="Number of concurrent download threads")
    parser.add_argument("--refresh", action="store_true", help="Force refresh and bypass cache")
    parser.add_argument("--no-resume", action="store_true", help="Do not skip previously completed downloads")

    args = parser.parse_args()

    # If no specific flags passed, default to --sync-universe
    if not any([args.sync_universe, args.download_submissions, args.download_facts, args.parse_facts, args.all]):
        args.sync_universe = True

    if args.all:
        args.sync_universe = True
        args.download_submissions = True
        args.download_facts = True
        args.parse_facts = True

    run_pipeline(
        sync_universe=args.sync_universe,
        download_submissions=args.download_submissions or args.all,
        download_facts=args.download_facts or args.all,
        parse_to_db=args.parse_facts or args.all,
        limit=args.limit,
        workers=args.workers,
        refresh=args.refresh,
        resume=not args.no_resume,
    )


if __name__ == "__main__":
    main()
