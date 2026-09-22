"""Migrate and compute point-in-time fundamentals into data/indian_market.db."""

import sqlite3
import pandas as pd
import numpy as np
import time

def setup_fundamentals():
    t0 = time.time()
    conn = sqlite3.connect("data/indian_market.db")
    cur = conn.cursor()

    # Create tables
    cur.execute("""
    CREATE TABLE IF NOT EXISTS fundamental_annual (
        security_id INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        fiscal_year INTEGER NOT NULL,
        period_end_date TEXT NOT NULL,
        availability_date TEXT NOT NULL,
        total_revenue REAL,
        net_profit REAL,
        pbt REAL,
        finance_costs REAL,
        eps REAL,
        total_assets REAL,
        total_equity REAL,
        total_debt REAL,
        PRIMARY KEY (security_id, fiscal_year),
        FOREIGN KEY (security_id) REFERENCES securities(security_id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fundamental_ratios (
        security_id INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        fiscal_year INTEGER NOT NULL,
        period_end_date TEXT NOT NULL,
        availability_date TEXT NOT NULL,
        roe REAL,
        roce REAL,
        debt_equity REAL,
        current_ratio REAL,
        net_margin REAL,
        interest_coverage REAL,
        profit_cagr_3y REAL,
        sales_cagr_3y REAL,
        PRIMARY KEY (security_id, fiscal_year),
        FOREIGN KEY (security_id) REFERENCES securities(security_id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fundamental_data_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        fiscal_years_count INTEGER,
        status TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()

    print("Created fundamental tables in data/indian_market.db.")

    # Attach old database
    cur.execute("ATTACH DATABASE 'data/nse_stocks_all_years.db' AS old_db;")

    print("Reading old fundamentals...")
    pl_df = pd.read_sql("""
        SELECT s.security_id, pl.symbol, pl.year as fiscal_year, pl.total_revenue, pl.net_profit,
               pl.profit_before_tax as pbt, pl.finance_costs, pl.eps_basic as eps
        FROM old_db.financial_income_statement pl
        JOIN securities s ON s.symbol = pl.symbol;
    """, conn)

    bs_df = pd.read_sql("""
        SELECT s.security_id, bs.symbol, bs.year as fiscal_year, bs.total_shareholders_funds as total_equity,
               bs.total_debt, bs.total_assets
        FROM old_db.financial_balance_sheet bs
        JOIN securities s ON s.symbol = bs.symbol;
    """, conn)

    r_df = pd.read_sql("""
        SELECT s.security_id, r.symbol, r.year as fiscal_year, r.roe, r.roce, r.debt_equity,
               r.current_ratio, r.net_margin
        FROM old_db.financial_ratios r
        JOIN securities s ON s.symbol = r.symbol;
    """, conn)

    cur.execute("DETACH DATABASE old_db;")

    print(f"Loaded {len(pl_df):,} P&L rows, {len(bs_df):,} BS rows, {len(r_df):,} Ratio rows.")

    # Merge into annual fundamentals
    annual = pl_df.merge(bs_df, on=["security_id", "symbol", "fiscal_year"], how="outer")
    annual = annual.merge(r_df, on=["security_id", "symbol", "fiscal_year"], how="outer")
    annual = annual.sort_values(["security_id", "fiscal_year"]).reset_index(drop=True)

    # Point-in-time date calculation:
    # Fiscal year Y ends on Y-03-31.
    # Audited results publicly available by Y-05-31 under SEBI LODR 60-day rule.
    annual["period_end_date"] = annual["fiscal_year"].apply(lambda y: f"{int(y):04d}-03-31" if pd.notna(y) else None)
    annual["availability_date"] = annual["fiscal_year"].apply(lambda y: f"{int(y):04d}-05-31" if pd.notna(y) else None)

    # Calculate Interest Coverage: EBIT / Finance Costs
    pbt = annual["pbt"].fillna(0.0)
    fc = annual["finance_costs"].fillna(0.0)
    ebit = pbt + fc.clip(lower=0.0)
    annual["interest_coverage"] = np.where(
        fc > 0,
        ebit / fc,
        np.where(ebit > 0, 999.0, 0.0)
    )

    # Vectorized 3-Year Profit CAGR and 3-Year Sales CAGR
    print("Computing 3-year Profit & Sales CAGRs per security...")
    annual = annual.sort_values(["security_id", "fiscal_year"]).reset_index(drop=True)
    
    # Check shift matching 3 years back
    annual["fiscal_year_prev3"] = annual.groupby("security_id")["fiscal_year"].shift(3)
    annual["net_profit_prev3"] = annual.groupby("security_id")["net_profit"].shift(3)
    annual["revenue_prev3"] = annual.groupby("security_id")["total_revenue"].shift(3)

    is_3y_match = (annual["fiscal_year"] - annual["fiscal_year_prev3"] == 3)
    
    # Profit CAGR
    profit_cagr = np.where(
        is_3y_match & (annual["net_profit"] > 0) & (annual["net_profit_prev3"] > 0),
        ((annual["net_profit"] / annual["net_profit_prev3"]) ** (1.0 / 3.0) - 1.0) * 100.0,
        np.where(is_3y_match & (annual["net_profit"] > 0) & (annual["net_profit_prev3"] <= 0), 100.0,
                 np.where(is_3y_match & (annual["net_profit"] <= 0), -100.0, np.nan))
    )
    annual["profit_cagr_3y"] = profit_cagr

    # Sales CAGR
    sales_cagr = np.where(
        is_3y_match & (annual["total_revenue"] > 0) & (annual["revenue_prev3"] > 0),
        ((annual["total_revenue"] / annual["revenue_prev3"]) ** (1.0 / 3.0) - 1.0) * 100.0,
        np.nan
    )
    annual["sales_cagr_3y"] = sales_cagr

    # Insert into SQLite tables
    cur.execute("DELETE FROM fundamental_annual;")
    cur.execute("DELETE FROM fundamental_ratios;")

    # Save fundamental_annual
    fa_cols = ["security_id", "symbol", "fiscal_year", "period_end_date", "availability_date",
               "total_revenue", "net_profit", "pbt", "finance_costs", "eps", "total_assets",
               "total_equity", "total_debt"]
    annual[fa_cols].to_sql("fundamental_annual", conn, if_exists="append", index=False)

    # Save fundamental_ratios
    fr_cols = ["security_id", "symbol", "fiscal_year", "period_end_date", "availability_date",
               "roe", "roce", "debt_equity", "current_ratio", "net_margin", "interest_coverage",
               "profit_cagr_3y", "sales_cagr_3y"]
    annual[fr_cols].to_sql("fundamental_ratios", conn, if_exists="append", index=False)

    # Create indexes for ultra-fast point-in-time queries
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fa_sec_avail ON fundamental_annual(security_id, availability_date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_fr_sec_avail ON fundamental_ratios(security_id, availability_date);")

    cur.execute("""
        INSERT INTO fundamental_data_log (symbol, fiscal_years_count, status)
        SELECT symbol, COUNT(*), 'POPULATED' FROM fundamental_annual GROUP BY symbol;
    """)

    conn.commit()
    conn.close()

    print(f"Successfully populated fundamental_annual ({len(annual):,} rows) and fundamental_ratios in {time.time() - t0:.2f}s.")

if __name__ == "__main__":
    setup_fundamentals()
