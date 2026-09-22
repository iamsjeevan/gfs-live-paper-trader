#!/usr/bin/env python3
"""CLI Runner: Download longest available history of Bitcoin 1-minute data into SQLite."""

from pathlib import Path
import sys
import time

# Ensure parent directory in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crypto_data.config import DB_PATH, PAIR, TABLE_NAME, TIMEFRAME
from crypto_data.downloader import BitcoinHistoricalDownloader
from crypto_data.validator import BitcoinDataValidator


def main():
    print("================================================================================")
    print("BITCOIN HISTORICAL 1-MINUTE DATASET INGESTION PIPELINE")
    print(f"Pair: {PAIR} | Timeframe: {TIMEFRAME} | Target DB: {DB_PATH}")
    print("================================================================================")

    t0 = time.time()
    downloader = BitcoinHistoricalDownloader()

    # Step 1: Sync Archives (Monthly and Daily from Binance Vision)
    downloader.sync_archives(max_workers=6)

    # Step 2: REST API catch-up for today (intraday completed candles)
    downloader.sync_rest_api_catchup()

    # Step 3: Run Validation and Integrity Suite
    print("\nRunning forensic data validation and gap analysis...")
    validator = BitcoinDataValidator()
    val_report = validator.run_full_validation()

    total_time = time.time() - t0

    print("\n================================================================================")
    print("INGESTION & VALIDATION SUMMARY REPORT")
    print("================================================================================")
    print(f"DATA SOURCE:     Binance Vision Official Archive + Binance REST API")
    print(f"PAIR:            {PAIR} (Spot)")
    print(f"TIMEFRAME:       {TIMEFRAME}")
    print(f"EARLIEST DATA:   {val_report['earliest_datetime_utc']} UTC (timestamp: {val_report['min_timestamp']})")
    print(f"LATEST DATA:     {val_report['latest_datetime_utc']} UTC (timestamp: {val_report['max_timestamp']})")
    print(f"TOTAL ROWS:      {val_report['row_count']:,}")
    print(f"DATABASE:        {DB_PATH}")
    print(f"TABLE:           {TABLE_NAME}")
    print(f"SPAN:            {val_report['years_covered']} years ({val_report['months_covered']} months / {val_report['span_days']} days)")
    print(f"MISSING MINUTES: {val_report['missing_minutes']:,} ({val_report['missing_percentage']:.3f}% of theoretical span)")
    print(f"DUPLICATES:      {val_report['duplicate_count']}")
    print(f"INVALID OHLC:    {val_report['invalid_ohlc_count']}")
    print(f"ZERO/NEG PRICES: {val_report['non_positive_price_count']}")
    print(f"ZERO VOLUME:     {val_report['zero_volume_count']:,} candles (0.00 volume during low activity / maintenance)")
    print(f"DATA QUALITY:    {val_report['data_quality_verdict']}")
    print(f"DOWNLOAD SIZE:   {val_report['db_size_mb']:.2f} MB (SQLite storage)")
    print(f"ELAPSED TIME:    {total_time:.1f}s")
    print(f"STATUS:          COMPLETE")
    print("================================================================================")

    if val_report["top_outage_gaps"]:
        print("\nTop Historical Binance Maintenance Gaps:")
        for idx, g in enumerate(val_report["top_outage_gaps"][:5], 1):
            print(f"  {idx}. {g['gap_start']} -> {g['gap_end']} ({g['missing_minutes']} mins / {g['duration_hours']} hrs)")


if __name__ == "__main__":
    main()
