"""Historical 2016 Indian Equity Universe Reconstruction and Lifecycle Audit."""

from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

try:
    from india_stock_research.config.settings import (
        BHAVCOPY_2016_PATH,
        DEFAULT_MAX_MARKET_CAP_CR,
        DEFAULT_MIN_MARKET_CAP_CR,
        DEFINITION_C_MAX_CR,
        DEFINITION_C_MIN_CR,
        EQUITY_MASTER_PATH,
        MAIN_DB_PATH,
        setup_logger,
    )
except ImportError:
    from config.settings import (
        BHAVCOPY_2016_PATH,
        DEFAULT_MAX_MARKET_CAP_CR,
        DEFAULT_MIN_MARKET_CAP_CR,
        DEFINITION_C_MAX_CR,
        DEFINITION_C_MIN_CR,
        EQUITY_MASTER_PATH,
        MAIN_DB_PATH,
        setup_logger,
    )

logger = setup_logger("india_universe", "india_screening.log")


def reconstruct_2016_indian_universe(
    bhavcopy_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
    equity_master_path: Optional[Path] = None,
    min_mcap_cr: float = DEFAULT_MIN_MARKET_CAP_CR,
    max_mcap_cr: float = DEFAULT_MAX_MARKET_CAP_CR,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Reconstruct point-in-time 2016 Indian listed universe without survivorship bias.

    Starting Point: Official NSE Bhavcopy from 2016-12-30 close (cm30DEC2016bhav.csv).
    Identity: ISIN as permanent immutable company identity.
    Shares: Historical share capital from FY16 balance sheet divided by Face Value.
    Market Cap: 2016 unadjusted close * historical shares.
    """
    bhav_file = bhavcopy_path or BHAVCOPY_2016_PATH
    db_file = db_path or MAIN_DB_PATH
    em_file = equity_master_path or EQUITY_MASTER_PATH

    logger.info(f"Loading 2016 Bhavcopy from {bhav_file}...")
    bhav_df = pd.read_csv(bhav_file)
    bhav_df.columns = bhav_df.columns.str.strip()

    # Total stocks trading on 2016-12-30
    total_traded_2016 = len(bhav_df)
    eq_bhav = bhav_df[bhav_df["SERIES"] == "EQ"].copy()
    eq_count_2016 = len(eq_bhav)
    logger.info(f"Total 2016 securities traded: {total_traded_2016}, Common Equities (EQ): {eq_count_2016}")

    # Load Face Value and Modern Tickers from Equity Master
    logger.info(f"Loading Equity Master from {em_file}...")
    em_df = pd.read_csv(em_file)
    em_df.columns = em_df.columns.str.strip()
    isin_to_modern = em_df.set_index("ISIN NUMBER")["SYMBOL"].to_dict()
    isin_to_fv = em_df.set_index("ISIN NUMBER")["FACE VALUE"].to_dict()
    sym_to_fv = em_df.set_index("SYMBOL")["FACE VALUE"].to_dict()

    # Load Financial Statement Facts from SQLite Database
    logger.info(f"Loading FY2016 balance sheet facts from {db_file}...")
    conn = sqlite3.connect(db_file)
    cm_df = pd.read_sql("SELECT symbol, company_name, isin, sector, sub_sector FROM company_master", conn)
    bs_df = pd.read_sql("SELECT symbol, share_capital, total_shareholders_funds, total_debt FROM financial_balance_sheet WHERE year=2016", conn)
    pl_df = pd.read_sql("SELECT symbol, total_revenue, net_profit, profit_before_tax FROM financial_income_statement WHERE year=2016", conn)
    conn.close()

    # Map by ISIN and Symbol
    cm_isin_map = cm_df.dropna(subset=["isin"]).set_index("isin").to_dict(orient="index")
    cm_sym_map = cm_df.set_index("symbol").to_dict(orient="index")
    bs_sym_map = bs_df.set_index("symbol").to_dict(orient="index")
    pl_sym_map = pl_df.set_index("symbol").to_dict(orient="index")

    records = []
    for _, row in eq_bhav.iterrows():
        sym_2016 = str(row["SYMBOL"]).strip()
        isin = str(row["ISIN"]).strip() if pd.notnull(row.get("ISIN")) else None
        close_2016 = float(row["CLOSE"]) if pd.notnull(row.get("CLOSE")) else None

        # Resolve modern symbol
        modern_sym = isin_to_modern.get(isin, sym_2016)
        has_ticker_changed = bool(modern_sym and modern_sym != sym_2016)

        # Lookup company metadata
        cm = cm_isin_map.get(isin) or cm_sym_map.get(sym_2016, {})
        comp_name = cm.get("company_name", sym_2016)
        sector = cm.get("sector", "Unclassified")
        sub_sector = cm.get("sub_sector", "Unclassified")

        # Lookup FY16 share capital and financials
        bs = bs_sym_map.get(sym_2016) or bs_sym_map.get(modern_sym, {})
        pl = pl_sym_map.get(sym_2016) or pl_sym_map.get(modern_sym, {})

        share_capital_cr = bs.get("share_capital")
        equity_cr = bs.get("total_shareholders_funds")
        debt_cr = bs.get("total_debt")
        rev_cr = pl.get("total_revenue")
        net_profit_cr = pl.get("net_profit")

        # Face value
        face_val = isin_to_fv.get(isin) or sym_to_fv.get(sym_2016, 10.0)
        try:
            face_val = float(face_val) if face_val and face_val > 0 else 10.0
        except Exception:
            face_val = 10.0

        # Compute shares outstanding and 2016 market cap
        shares_cr = None
        market_cap_cr = None
        market_cap_inr = None

        if share_capital_cr is not None and share_capital_cr > 0 and close_2016 is not None:
            shares_cr = share_capital_cr / face_val
            market_cap_cr = shares_cr * close_2016
            market_cap_inr = market_cap_cr * 1e7

        # Determine lifecycle and eligibility
        lifecycle_status = "ACTIVE"
        if not isin_to_modern.get(isin) and modern_sym not in cm_sym_map:
            lifecycle_status = "DELISTED_OR_SUSPENDED"
        elif has_ticker_changed:
            lifecycle_status = "TICKER_CHANGED"

        has_fundamentals = bool(share_capital_cr is not None and rev_cr is not None)
        has_market_cap = bool(market_cap_cr is not None and market_cap_cr > 0)

        records.append({
            "isin": isin,
            "symbol_2016": sym_2016,
            "modern_symbol": modern_sym,
            "has_ticker_changed": has_ticker_changed,
            "company_name": comp_name,
            "sector": sector,
            "sub_sector": sub_sector,
            "price_2016_unadjusted": close_2016,
            "face_value": face_val,
            "share_capital_cr_2016": share_capital_cr,
            "shares_outstanding_cr_2016": shares_cr,
            "market_cap_cr_2016": market_cap_cr,
            "market_cap_inr_2016": market_cap_inr,
            "revenue_cr_2016": rev_cr,
            "net_profit_cr_2016": net_profit_cr,
            "equity_cr_2016": equity_cr,
            "debt_cr_2016": debt_cr,
            "lifecycle_status": lifecycle_status,
            "has_valid_2016_price": bool(close_2016 and close_2016 > 0),
            "has_valid_2016_shares": bool(shares_cr and shares_cr > 0),
            "has_valid_2016_mcap": has_market_cap,
            "has_2016_fundamentals": has_fundamentals,
        })

    full_universe_df = pd.DataFrame(records)

    # Compute Market Cap Percentiles across the full reconstructed universe
    valid_mcap_s = full_universe_df["market_cap_cr_2016"].dropna()
    pct_20 = float(np.percentile(valid_mcap_s, 20.0))
    pct_25 = float(np.percentile(valid_mcap_s, 25.0))
    pct_50 = float(np.percentile(valid_mcap_s, 50.0))
    pct_75 = float(np.percentile(valid_mcap_s, 75.0))
    pct_90 = float(np.percentile(valid_mcap_s, 90.0))

    # Apply Multiple Small-Cap Definitions:
    # Definition A: Bottom 20% by 2016 market cap (< pct_20)
    # Definition B: Bottom 25% by 2016 market cap (< pct_25)
    # Definition C: ₹1,000 Cr to ₹10,000 Cr
    # Definition D (Primary): ₹500 Cr to ₹5,000 Cr (Official SEBI small-cap equivalent tier)
    full_universe_df["is_def_a_bottom20"] = (full_universe_df["market_cap_cr_2016"] <= pct_20) & (full_universe_df["market_cap_cr_2016"] > 0)
    full_universe_df["is_def_b_bottom25"] = (full_universe_df["market_cap_cr_2016"] <= pct_25) & (full_universe_df["market_cap_cr_2016"] > 0)
    full_universe_df["is_def_c_1k_10k"] = (full_universe_df["market_cap_cr_2016"] >= DEFINITION_C_MIN_CR) & (full_universe_df["market_cap_cr_2016"] <= DEFINITION_C_MAX_CR)
    full_universe_df["is_def_d_500_5k"] = (full_universe_df["market_cap_cr_2016"] >= min_mcap_cr) & (full_universe_df["market_cap_cr_2016"] <= max_mcap_cr)

    # Primary Small-Cap Eligibility (Definition D: ₹500 Cr to ₹5,000 Cr)
    full_universe_df["is_eligible_smallcap"] = (
        full_universe_df["is_def_d_500_5k"] &
        full_universe_df["has_2016_fundamentals"] &
        full_universe_df["has_valid_2016_price"]
    )

    summary = {
        "total_traded_2016": total_traded_2016,
        "common_equities_2016": eq_count_2016,
        "companies_with_valid_2016_mcap": int(len(valid_mcap_s)),
        "companies_with_2016_fundamentals": int(full_universe_df["has_2016_fundamentals"].sum()),
        "ticker_changes_detected": int(full_universe_df["has_ticker_changed"].sum()),
        "delisted_or_suspended": int((full_universe_df["lifecycle_status"] == "DELISTED_OR_SUSPENDED").sum()),
        "mcap_percentiles_cr": {
            "p20": pct_20,
            "p25": pct_25,
            "p50_median": pct_50,
            "p75": pct_75,
            "p90": pct_90,
        },
        "definition_counts": {
            "def_a_bottom20": int(full_universe_df["is_def_a_bottom20"].sum()),
            "def_b_bottom25": int(full_universe_df["is_def_b_bottom25"].sum()),
            "def_c_1k_10k": int(full_universe_df["is_def_c_1k_10k"].sum()),
            "def_d_500_5k": int(full_universe_df["is_def_d_500_5k"].sum()),
            "eligible_primary_smallcap": int(full_universe_df["is_eligible_smallcap"].sum()),
        },
    }

    return full_universe_df, summary
