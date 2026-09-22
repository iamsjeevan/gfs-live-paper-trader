"""SQLite Schema definitions and initialization functions for the research database."""

import sqlite3
from pathlib import Path
from typing import Optional, Union

from .connection import get_connection

SCHEMA_DDL = """
-- -----------------------------------------------------------------------------
-- 1. Companies Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    cik INTEGER PRIMARY KEY,
    ticker TEXT,
    company_name TEXT NOT NULL,
    exchange TEXT,
    sic INTEGER,
    sic_description TEXT,
    first_seen TEXT,
    last_seen TEXT,
    is_active INTEGER DEFAULT 1,
    metadata_json TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);
CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(company_name);
CREATE INDEX IF NOT EXISTS idx_companies_sic ON companies(sic);

-- -----------------------------------------------------------------------------
-- 2. Filings Metadata Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS filings (
    accession_number TEXT PRIMARY KEY,
    cik INTEGER NOT NULL,
    form TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    report_date TEXT,
    fiscal_year INTEGER,
    fiscal_period TEXT,
    primary_document TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (cik) REFERENCES companies(cik)
);

CREATE INDEX IF NOT EXISTS idx_filings_cik ON filings(cik);
CREATE INDEX IF NOT EXISTS idx_filings_filing_date ON filings(filing_date);
CREATE INDEX IF NOT EXISTS idx_filings_report_date ON filings(report_date);
CREATE INDEX IF NOT EXISTS idx_filings_form ON filings(form);

-- -----------------------------------------------------------------------------
-- 3. Historical Fundamentals Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cik INTEGER NOT NULL,
    ticker TEXT,
    filing_date TEXT NOT NULL,
    report_date TEXT NOT NULL,
    fiscal_year INTEGER,
    fiscal_period TEXT,
    form TEXT,
    accession_number TEXT,
    -- Revenue & Profit
    revenue REAL,
    net_income REAL,
    operating_income REAL,
    gross_profit REAL,
    -- Balance Sheet
    assets REAL,
    current_assets REAL,
    liabilities REAL,
    current_liabilities REAL,
    equity REAL,
    debt REAL,
    cash REAL,
    -- Cash Flow
    operating_cash_flow REAL,
    capex REAL,
    free_cash_flow REAL,
    -- Per-Share
    shares_outstanding REAL,
    diluted_shares REAL,
    eps REAL,
    -- Margins & Derived Ratios
    gross_margin REAL,
    operating_margin REAL,
    net_margin REAL,
    fcf_margin REAL,
    roe REAL,
    roa REAL,
    roic REAL,
    debt_equity REAL,
    current_ratio REAL,
    -- Multi-Year Growth Metrics
    revenue_growth_1y REAL,
    revenue_growth_3y REAL,
    net_income_growth_1y REAL,
    net_income_growth_3y REAL,
    fcf_growth_1y REAL,
    fcf_growth_3y REAL,
    eps_growth_1y REAL,
    -- Valuation
    pe_ratio REAL,
    pfcf_ratio REAL,
    ps_ratio REAL,
    ev_ebitda REAL,
    -- Quantitative Moat Proxy
    moat_score REAL,
    -- Data Quality Flags (e.g. 'missing_debt,missing_fcf')
    data_quality_flags TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (cik) REFERENCES companies(cik),
    UNIQUE (cik, report_date, fiscal_period, form)
);

CREATE INDEX IF NOT EXISTS idx_fundamentals_cik ON fundamentals(cik);
CREATE INDEX IF NOT EXISTS idx_fundamentals_filing_date ON fundamentals(filing_date);
CREATE INDEX IF NOT EXISTS idx_fundamentals_report_date ON fundamentals(report_date);
CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker ON fundamentals(ticker);

-- -----------------------------------------------------------------------------
-- 4. Historical Prices Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    cik INTEGER,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    adjusted_close REAL,
    volume REAL,
    provider TEXT DEFAULT 'yahoo',
    adjustment_type TEXT DEFAULT 'UNADJUSTED_CLOSE',
    data_quality TEXT DEFAULT 'CLEAN',
    confidence REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_prices_ticker ON prices(ticker);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);

-- -----------------------------------------------------------------------------
-- 5. Corporate Actions Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS corporate_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    old_ticker TEXT,
    new_ticker TEXT,
    action_date TEXT NOT NULL,
    action_type TEXT NOT NULL,  -- 'SPLIT', 'MERGER', 'ACQUISITION', 'TICKER_CHANGE', 'SPINOFF', 'DELIST'
    ratio REAL,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_corp_actions_old_ticker ON corporate_actions(old_ticker);
CREATE INDEX IF NOT EXISTS idx_corp_actions_new_ticker ON corporate_actions(new_ticker);
CREATE INDEX IF NOT EXISTS idx_corp_actions_date ON corporate_actions(action_date);

-- -----------------------------------------------------------------------------
-- 6. Screen Runs Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS screen_runs (
    run_id TEXT PRIMARY KEY,
    screen_date TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    universe_min_market_cap REAL,
    universe_max_market_cap REAL,
    weights_json TEXT,
    hard_filters_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_screen_runs_date ON screen_runs(screen_date);

-- -----------------------------------------------------------------------------
-- 7. Screen Results Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS screen_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cik INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    company_name TEXT,
    score REAL,
    rank INTEGER,
    market_cap REAL,
    price REAL,
    roe REAL,
    roic REAL,
    revenue_growth REAL,
    earnings_growth REAL,
    fcf_growth REAL,
    debt_equity REAL,
    operating_margin REAL,
    fcf_margin REAL,
    moat_score REAL,
    data_quality_flags TEXT,
    FOREIGN KEY (run_id) REFERENCES screen_runs(run_id),
    FOREIGN KEY (cik) REFERENCES companies(cik)
);

CREATE INDEX IF NOT EXISTS idx_screen_results_run_id ON screen_results(run_id);
CREATE INDEX IF NOT EXISTS idx_screen_results_rank ON screen_results(run_id, rank);
CREATE INDEX IF NOT EXISTS idx_screen_results_cik ON screen_results(cik);

-- -----------------------------------------------------------------------------
-- 8. Backtest Runs Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    screen_run_id TEXT NOT NULL,
    strategy_name TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    investment_per_stock REAL,
    total_initial REAL,
    total_final REAL,
    multiple REAL,
    cagr REAL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (screen_run_id) REFERENCES screen_runs(run_id)
);

-- -----------------------------------------------------------------------------
-- 9. Backtest Positions Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backtest_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cik INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    company TEXT,
    initial_investment REAL,
    start_price REAL,
    end_price REAL,
    final_value REAL,
    multiple REAL,
    cagr REAL,
    final_status TEXT,  -- 'ACTIVE', 'ACQUIRED', 'DELISTED', 'BANKRUPT', 'RESTRUCTURED', 'MERGED', 'NO_DATA'
    notes TEXT,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id),
    FOREIGN KEY (cik) REFERENCES companies(cik)
);

CREATE INDEX IF NOT EXISTS idx_backtest_positions_run ON backtest_positions(run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_positions_ticker ON backtest_positions(ticker);

-- -----------------------------------------------------------------------------
-- 10. Download Status Table (Resumable Operations)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS download_status (
    task_type TEXT NOT NULL,  -- 'sec_submissions', 'sec_companyfacts', 'prices'
    entity_id TEXT NOT NULL,  -- CIK or Ticker
    status TEXT NOT NULL,     -- 'PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'NOT_FOUND'
    started_at TEXT,
    completed_at TEXT,
    attempts INTEGER DEFAULT 0,
    http_status INTEGER,
    source_url TEXT,
    error_message TEXT,
    file_path TEXT,
    PRIMARY KEY (task_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_download_status_task ON download_status(task_type, status);

-- -----------------------------------------------------------------------------
-- 11. Universe Runs & Audit Table (Reproducibility)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS universe_runs (
    run_id TEXT PRIMARY KEY,
    screen_date TEXT NOT NULL,
    min_market_cap REAL,
    max_market_cap REAL,
    exclude_financials INTEGER DEFAULT 1,
    allowed_exchanges TEXT,
    total_candidates INTEGER,
    eligible_count INTEGER,
    excluded_count INTEGER,
    stats_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS universe_run_companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    cik INTEGER NOT NULL,
    ticker TEXT,
    company_name TEXT,
    exchange TEXT,
    sic INTEGER,
    status TEXT NOT NULL,
    reason TEXT,
    price_2016 REAL,
    shares_2016 REAL,
    shares_filing_date TEXT,
    shares_source TEXT,
    market_cap_2016 REAL,
    historical_status TEXT,
    data_quality_flags TEXT,
    FOREIGN KEY (run_id) REFERENCES universe_runs(run_id),
    FOREIGN KEY (cik) REFERENCES companies(cik)
);

CREATE INDEX IF NOT EXISTS idx_universe_companies_run ON universe_run_companies(run_id);
CREATE INDEX IF NOT EXISTS idx_universe_companies_cik ON universe_run_companies(cik);
CREATE INDEX IF NOT EXISTS idx_universe_companies_status ON universe_run_companies(run_id, status);

-- -----------------------------------------------------------------------------
-- 12. Historical Listings Table (Bridge between SEC CIK and Market Identity)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS historical_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cik INTEGER NOT NULL,
    ticker TEXT,
    company_name TEXT,
    exchange TEXT,
    security_type TEXT NOT NULL,  -- 'COMMON_EQUITY', 'PREFERRED', 'DEBT', 'ETF/FUND', 'REIT', 'ADR', 'OTHER'
    listing_start_date TEXT,
    listing_end_date TEXT,
    source TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (cik) REFERENCES companies(cik)
);

CREATE INDEX IF NOT EXISTS idx_hist_listings_cik ON historical_listings(cik);
CREATE INDEX IF NOT EXISTS idx_hist_listings_ticker ON historical_listings(ticker);
CREATE INDEX IF NOT EXISTS idx_hist_listings_type ON historical_listings(security_type);
"""


def init_db(db_path: Optional[Union[str, Path]] = None) -> None:
    """Initialize the SQLite database with all required tables and indexes."""
    conn = get_connection(db_path)
    try:
        conn.executescript(SCHEMA_DDL)
        # Migrate prices table for new resolver columns if missing
        cur = conn.cursor()
        cols = [c[1] for c in cur.execute("PRAGMA table_info(prices);").fetchall()]
        for col_name, col_type, def_val in [
            ("cik", "INTEGER", "NULL"),
            ("provider", "TEXT", "'yahoo'"),
            ("adjustment_type", "TEXT", "'UNADJUSTED_CLOSE'"),
            ("data_quality", "TEXT", "'CLEAN'"),
            ("confidence", "REAL", "1.0"),
        ]:
            if col_name not in cols:
                cur.execute(f"ALTER TABLE prices ADD COLUMN {col_name} {col_type} DEFAULT {def_val};")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_prices_cik ON prices(cik);")
        conn.commit()
    finally:
        conn.close()
