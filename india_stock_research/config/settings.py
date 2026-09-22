"""Configuration settings for Indian Equity Research and Retrospective Pipeline."""

import logging
from pathlib import Path
import sys

# Directory Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
EXPORTS_DIR = DATA_DIR / "exports"

# Source Database & Bhavcopy Paths
MAIN_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nse_stocks_all_years.db"
EQUITY_MASTER_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "equity_master.csv"
BHAVCOPY_2016_PATH = RAW_DATA_DIR / "cm30DEC2016bhav.csv"
PRICE_CACHE_PATH = RAW_DATA_DIR / "india_retrospective_prices.json"

# Research Timestamps & Dates
DEFAULT_SCREEN_DATE = "2016-12-31"
START_PRICE_DATE = "2016-12-30"
END_PRICE_DATE = "2026-08-31"

# Primary Small-Cap Market Cap Thresholds (in INR Crores)
# Definition D (Primary): ₹500 Cr to ₹5,000 Cr (~$75M to $750M at 2016 exchange rates)
DEFAULT_MIN_MARKET_CAP_CR = 500.0
DEFAULT_MAX_MARKET_CAP_CR = 5000.0

# Alternative Definitions for Multi-Tiered Sensitivity Audit:
DEFINITION_A_PCT = 20.0       # Bottom 20%
DEFINITION_B_PCT = 25.0       # Bottom 25%
DEFINITION_C_MIN_CR = 1000.0  # ₹1,000 Cr
DEFINITION_C_MAX_CR = 10000.0 # ₹10,000 Cr

# Benchmarks
BENCHMARKS = {
    "NIFTY_50": "^NSEI",
    "BSE_SENSEX": "^BSESN",
    "NIFTY_500": "^CRSLDX",
    "NIFTY_SMALLCAP_250": "NIFTYSMLCAP250.NS"
}


def setup_logger(name: str = "india_research", log_filename: str = "india_screening.log") -> logging.Logger:
    """Set up and configure a structured file and stream logger."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        log_format = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(log_format)
        logger.addHandler(stream_handler)

        log_dir = BASE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / log_filename, encoding="utf-8")
        file_handler.setFormatter(log_format)
        logger.addHandler(file_handler)

    return logger
