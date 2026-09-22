"""Historical 10-Year Indian Price & Return Retrieval with Corporate Action Adjustments."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
import yfinance as yf

try:
    from india_stock_research.config.settings import DATA_DIR, PRICE_CACHE_PATH, setup_logger
except ImportError:
    from config.settings import DATA_DIR, PRICE_CACHE_PATH, setup_logger

logger = setup_logger("india_prices", "india_screening.log")


def fetch_indian_10yr_returns(
    universe_df: pd.DataFrame,
    start_date: str = "2016-12-30",
    end_date: str = "2026-08-31",
    cache_path: Optional[Path] = None,
    force_refresh: bool = False,
    chunk_size: int = 50,
) -> pd.DataFrame:
    """Retrieve 2016-12-30 and 2026-08-31 closing prices and compute 10-year TSR.

    Uses modern mapped symbols with .NS extension to ensure continuous price lineage.
    Caches downloaded prices locally for deterministic reproducibility.
    """
    cache_file = cache_path or PRICE_CACHE_PATH
    cached_prices: Dict[str, Dict[str, float]] = {}

    if cache_file.exists() and not force_refresh:
        logger.info(f"Loading cached Indian prices from {cache_file}...")
        with open(cache_file, "r", encoding="utf-8") as f:
            cached_prices = json.load(f)
    else:
        logger.info(f"Downloading 10-year Indian price data for {len(universe_df)} stocks...")
        tickers = []
        sym_map = {}
        for _, row in universe_df.iterrows():
            sym = str(row.get("modern_symbol") or row.get("symbol_2016")).strip()
            if sym:
                ns_t = f"{sym}.NS"
                tickers.append(ns_t)
                sym_map[ns_t] = sym

        unique_tickers = list(dict.fromkeys(tickers))
        logger.info(f"Unique Yahoo Finance tickers to query: {len(unique_tickers)}")

        for i in range(0, len(unique_tickers), chunk_size):
            chunk = unique_tickers[i : i + chunk_size]
            logger.info(f"Downloading chunk {i//chunk_size + 1}/{(len(unique_tickers)+chunk_size-1)//chunk_size} ({len(chunk)} tickers)...")
            try:
                # 2016 window
                df_start = yf.download(chunk, start="2016-12-25", end="2017-01-05", auto_adjust=False, progress=False)
                # 2026 window
                df_end = yf.download(chunk, start="2026-08-25", end="2026-09-05", auto_adjust=False, progress=False)

                for t in chunk:
                    orig_sym = sym_map.get(t, t.replace(".NS", ""))
                    p_start_adj = None
                    p_end_adj = None
                    p_start_raw = None
                    p_end_raw = None

                    if "Adj Close" in df_start and t in df_start["Adj Close"]:
                        s_s = df_start["Adj Close"][t].dropna()
                        if not s_s.empty:
                            p_start_adj = float(s_s.iloc[0])
                    if "Close" in df_start and t in df_start["Close"]:
                        s_sr = df_start["Close"][t].dropna()
                        if not s_sr.empty:
                            p_start_raw = float(s_sr.iloc[0])

                    if "Adj Close" in df_end and t in df_end["Adj Close"]:
                        s_e = df_end["Adj Close"][t].dropna()
                        if not s_e.empty:
                            p_end_adj = float(s_e.iloc[-1])
                    if "Close" in df_end and t in df_end["Close"]:
                        s_er = df_end["Close"][t].dropna()
                        if not s_er.empty:
                            p_end_raw = float(s_er.iloc[-1])

                    if p_start_adj and p_end_adj and p_start_adj > 0 and p_end_adj > 0:
                        cached_prices[orig_sym] = {
                            "ticker_yf": t,
                            "adj_close_2016": p_start_adj,
                            "adj_close_2026": p_end_adj,
                            "raw_close_2016": p_start_raw,
                            "raw_close_2026": p_end_raw,
                        }
            except Exception as e:
                logger.error(f"Error downloading chunk starting at {i}: {e}")

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cached_prices, f, indent=2)
        logger.info(f"Saved {len(cached_prices)} price pairs to {cache_file}.")

    # Calculate 10-year holding period returns
    days = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days
    years = days / 365.25

    records = []
    for _, row in universe_df.iterrows():
        sym_2016 = row["symbol_2016"]
        modern_sym = row.get("modern_symbol", sym_2016)
        isin = row.get("isin")
        name = row.get("company_name", sym_2016)
        mcap_cr = row.get("market_cap_cr_2016")
        p_raw_2016 = row.get("price_2016_unadjusted")

        p_info = cached_prices.get(modern_sym) or cached_prices.get(sym_2016)

        if p_info:
            p_start_adj = p_info["adj_close_2016"]
            p_end_adj = p_info["adj_close_2026"]
            p_end_raw = p_info.get("raw_close_2026", p_end_adj)

            tot_ret = (p_end_adj / p_start_adj) - 1.0
            cagr = ((p_end_adj / p_start_adj) ** (1.0 / years)) - 1.0
            price_ret = (p_end_raw / p_raw_2016) - 1.0 if (p_raw_2016 and p_raw_2016 > 0) else tot_ret

            records.append({
                "isin": isin,
                "symbol_2016": sym_2016,
                "modern_symbol": modern_sym,
                "company_name": name,
                "sector": row.get("sector", "Unclassified"),
                "sub_sector": row.get("sub_sector", "Unclassified"),
                "market_cap_cr_2016": mcap_cr,
                "price_2016_unadjusted": p_raw_2016,
                "price_2016_adj": p_start_adj,
                "price_2026_raw": p_end_raw,
                "price_2026_adj": p_end_adj,
                "total_return": tot_ret,
                "cagr": cagr,
                "price_return": price_ret,
                "has_valid_return": True,
                "lifecycle_status": row.get("lifecycle_status", "ACTIVE"),
                "is_eligible_smallcap": row.get("is_eligible_smallcap", False),
                "is_def_d_500_5k": row.get("is_def_d_500_5k", False),
            })
        else:
            records.append({
                "isin": isin,
                "symbol_2016": sym_2016,
                "modern_symbol": modern_sym,
                "company_name": name,
                "sector": row.get("sector", "Unclassified"),
                "sub_sector": row.get("sub_sector", "Unclassified"),
                "market_cap_cr_2016": mcap_cr,
                "price_2016_unadjusted": p_raw_2016,
                "has_valid_return": False,
                "exclusion_reason": "DELISTED_OR_MISSING_2026_PRICE",
                "lifecycle_status": "DELISTED_OR_SUSPENDED",
                "is_eligible_smallcap": False,
                "is_def_d_500_5k": row.get("is_def_d_500_5k", False),
            })

    return pd.DataFrame(records)
