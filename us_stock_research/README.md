# US Small-Cap Fundamental Research & Backtesting Framework

A modular, point-in-time, local Python research and backtesting engine for historical US small-cap equity strategies.

Designed to test the hypothesis:
> *Pretend it is December 31, 2016. Find very small US publicly listed companies using ONLY information that was publicly filed and available on or before that date. Apply fundamental quality and moat filters, select the top 10 companies, invest equally, and hold them until September 2026 without selling.*

---

## Key Design Principles

1. **Strict Point-in-Time Discipline (Zero Look-Ahead Bias)**:
   Financial data is evaluated strictly against SEC `filing_date`. For example, FY2016 financial results filed in February 2017 are strictly forbidden for a December 31, 2016 screen.
2. **Mitigating Survivorship Bias**:
   Companies that existed and filed in 2016 are identified by Central Index Key (CIK). Companies that subsequently merged, were acquired, restructured, or went bankrupt remain in the historical universe rather than disappearing.
3. **Resumable Data Pipelines**:
   All SEC EDGAR downloads (XBRL company facts, submissions, and market prices) track status in SQLite (`download_status` table). If a download session is interrupted, it resumes from unfinished CIKs.
4. **SEC Fair-Access Compliance**:
   Built-in thread-safe rate limiter (<= 8 req/sec), custom `User-Agent` headers, exponential backoff on HTTP 429, and local raw caching in `data/raw/sec/`.
5. **Separation of Concerns**:
   Data sources, database repositories, fundamental metric calculation, universe reconstruction, screening/ranking, and portfolio backtesting are decoupled into independent layers.

---

## Directory Structure

```text
us_stock_research/
│
├── README.md
├── requirements.txt
├── config/
│   ├── __init__.py
│   ├── settings.py
│   └── strategies/
│       ├── quality.py
│       ├── quality_growth.py
│       └── quality_value_moat.py
│
├── database/
│   ├── __init__.py
│   ├── connection.py
│   ├── schema.py
│   └── repositories/
│       ├── companies.py
│       ├── filings.py
│       ├── fundamentals.py
│       ├── prices.py
│       ├── screens.py
│       ├── backtests.py
│       └── downloads.py
│
├── data_sources/
│   ├── __init__.py
│   ├── sec/
│   │   ├── client.py
│   │   ├── company_universe.py
│   │   ├── filings.py
│   │   ├── companyfacts.py
│   │   ├── parser.py
│   │   └── downloader.py
│   │
│   └── market_data/
│       ├── yahoo.py
│       └── corporate_actions.py
│
├── universe/
├── fundamentals/
├── screening/
├── backtesting/
├── validation/
├── pipelines/
│   └── download_sec.py
├── cli/
├── tests/
├── data/
│   ├── raw/sec/
│   ├── cache/
│   └── exports/
├── logs/
└── research.db
```

---

## Quickstart (Milestone 1)

### 1. Initialize SQLite Database & Sync SEC Universe
```bash
python -m pipelines.download_sec --sync-universe
```

### 2. Download XBRL Facts (with Resume & Concurrency)
```bash
python -m pipelines.download_sec --download-facts --limit 50 --workers 5
```

### 3. Parse Downloaded Facts into Normalized Database
```bash
python -m pipelines.download_sec --parse-facts --limit 50
```

### 4. Run Unit Tests
```bash
pytest tests/
```
