"""Global configuration settings for the US Stock Research framework.

All directory paths, SEC API parameters, default screen parameters,
and logging configurations are defined here.
"""

import os
import logging
from pathlib import Path

# -----------------------------------------------------------------------------
# Base Directories
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
SEC_RAW_DIR = RAW_DATA_DIR / "sec"
SEC_SUBMISSIONS_DIR = SEC_RAW_DIR / "submissions"
SEC_COMPANYFACTS_DIR = SEC_RAW_DIR / "companyfacts"
CACHE_DIR = DATA_DIR / "cache"
EXPORTS_DIR = DATA_DIR / "exports"
LOGS_DIR = BASE_DIR / "logs"
DATABASE_DIR = BASE_DIR / "database"

# Ensure all directories exist
for directory in [
    DATA_DIR,
    RAW_DATA_DIR,
    SEC_RAW_DIR,
    SEC_SUBMISSIONS_DIR,
    SEC_COMPANYFACTS_DIR,
    CACHE_DIR,
    EXPORTS_DIR,
    LOGS_DIR,
    DATABASE_DIR,
]:
    directory.mkdir(parents=True, exist_ok=True)

# Database file path
DATABASE_PATH = BASE_DIR / "research.db"

# -----------------------------------------------------------------------------
# SEC EDGAR API Settings
# -----------------------------------------------------------------------------
# SEC strictly requires User-Agent in format: "Sample Company Name AdminContact@<domain>.com"
SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "USStockResearchBot academic_research@valueinvesting.org"
)

# SEC allows up to 10 requests per second across all connections.
# We set 8 req/sec max to maintain fair-access headroom.
SEC_RATE_LIMIT_PER_SEC = 8.0
SEC_WORKERS = int(os.environ.get("SEC_WORKERS", 5))
SEC_MAX_RETRIES = 5
SEC_TIMEOUT = 25.0
SEC_BACKOFF_FACTOR = 1.5

# -----------------------------------------------------------------------------
# Market Data (Yahoo Finance / Price Providers)
# -----------------------------------------------------------------------------
PRICE_WORKERS = int(os.environ.get("PRICE_WORKERS", 10))
PRICE_MAX_RETRIES = 3
PRICE_TIMEOUT = 15.0

# -----------------------------------------------------------------------------
# Default Screen & Backtest Parameters
# -----------------------------------------------------------------------------
# Default Small-Cap Market Cap Bounds ($50M - $1B)
DEFAULT_MIN_MARKET_CAP = 50_000_000.0
DEFAULT_MAX_MARKET_CAP = 1_000_000_000.0

DEFAULT_SCREEN_DATE = "2016-12-31"
DEFAULT_BACKTEST_START_DATE = "2016-12-30"
DEFAULT_BACKTEST_END_DATE = "2026-09-08"

DEFAULT_TOP_N = 10
DEFAULT_INVESTMENT_PER_STOCK = 1_000.0
DEFAULT_TOTAL_INVESTMENT = 10_000.0


def setup_logger(name: str, log_filename: str = "app.log", level: int = logging.INFO) -> logging.Logger:
    """Create and configure a logger with both console and rotating/file handlers."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler
    log_file_path = LOGS_DIR / log_filename
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
