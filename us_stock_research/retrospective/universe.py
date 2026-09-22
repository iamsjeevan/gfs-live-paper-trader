"""Universe reconstruction and future-winner group definitions for Milestone 7."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import yfinance as yf

from config.settings import DATA_DIR, setup_logger

logger = setup_logger("retrospective_universe", "screening.log")

PRICE_CACHE_PATH = DATA_DIR / "raw" / "retrospective_universe_prices.json"
FULL_UNIVERSE_PATH = DATA_DIR / "exports" / "full_historical_universe_20161231.csv"


def fetch_universe_10yr_returns(
    eligible_df: pd.DataFrame,
    start_date: str = "2016-12-30",
    end_date: str = "2026-08-31",
    cache_path: Optional[Path] = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Retrieve 2016-12-30 and 2026-08-31 prices and compute 10-year total returns.

    Caches downloaded price series locally for deterministic reproducibility.
    """
    cache_file = cache_path or PRICE_CACHE_PATH
    cached_prices: Dict[str, Dict[str, float]] = {}

    if cache_file.exists() and not force_refresh:
        logger.info(f"Loading cached retrospective prices from {cache_file}...")
        with open(cache_file, "r", encoding="utf-8") as f:
            cached_prices = json.load(f)
    else:
        logger.info(f"Downloading retrospective prices for {len(eligible_df)} eligible tickers...")
        tickers = eligible_df["ticker"].dropna().unique().tolist()

        chunk_size = 100
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]
            try:
                # auto_adjust=False provides both Close and Adj Close
                data_end = yf.download(
                    chunk,
                    start="2026-08-25",
                    end="2026-09-02",
                    auto_adjust=False,
                    progress=False,
                )
                data_start = yf.download(
                    chunk,
                    start="2016-12-28",
                    end="2017-01-05",
                    auto_adjust=False,
                    progress=False,
                )

                for t in chunk:
                    p_start = None
                    p_end = None
                    p_start_raw = None
                    p_end_raw = None

                    if "Adj Close" in data_start and t in data_start["Adj Close"]:
                        s_s = data_start["Adj Close"][t].dropna()
                        if not s_s.empty:
                            p_start = float(s_s.iloc[0])
                    if "Close" in data_start and t in data_start["Close"]:
                        s_sr = data_start["Close"][t].dropna()
                        if not s_sr.empty:
                            p_start_raw = float(s_sr.iloc[0])

                    if "Adj Close" in data_end and t in data_end["Adj Close"]:
                        s_e = data_end["Adj Close"][t].dropna()
                        if not s_e.empty:
                            p_end = float(s_e.iloc[-1])
                    if "Close" in data_end and t in data_end["Close"]:
                        s_er = data_end["Close"][t].dropna()
                        if not s_er.empty:
                            p_end_raw = float(s_er.iloc[-1])

                    if p_start and p_end:
                        cached_prices[t] = {
                            "adj_close_2016": p_start,
                            "adj_close_2026": p_end,
                            "raw_close_2016": p_start_raw,
                            "raw_close_2026": p_end_raw,
                        }
            except Exception as e:
                logger.error(f"Error downloading chunk {i}: {e}")

        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cached_prices, f, indent=2)
        logger.info(f"Saved {len(cached_prices)} price pairs to {cache_file}.")

    # Calculate holding-level returns
    days = (pd.to_datetime(end_date) - pd.to_datetime(start_date)).days
    years = days / 365.25

    records = []
    for _, row in eligible_df.iterrows():
        t = row["ticker"]
        cik = int(row["cik"])
        name = row.get("company_name", t)
        mcap = float(row.get("market_cap_2016", 0.0))
        p_raw = float(row.get("price_2016", 0.0))

        if t in cached_prices:
            p_data = cached_prices[t]
            p_start_adj = p_data["adj_close_2016"]
            p_end_adj = p_data["adj_close_2026"]
            p_end_raw = p_data.get("raw_close_2026", p_end_adj)

            if p_start_adj > 0 and p_end_adj > 0:
                tot_ret = (p_end_adj / p_start_adj) - 1.0
                cagr = ((p_end_adj / p_start_adj) ** (1.0 / years)) - 1.0
                price_ret = (p_end_raw / p_raw) - 1.0 if p_raw > 0 else tot_ret

                records.append({
                    "cik": cik,
                    "ticker": t,
                    "company_name": name,
                    "market_cap_2016": mcap,
                    "price_2016_raw": p_raw,
                    "price_2016_adj": p_start_adj,
                    "price_2026_raw": p_end_raw,
                    "price_2026_adj": p_end_adj,
                    "total_return": tot_ret,
                    "cagr": cagr,
                    "price_return": price_ret,
                    "has_valid_return": True,
                })
            else:
                records.append({
                    "cik": cik,
                    "ticker": t,
                    "company_name": name,
                    "market_cap_2016": mcap,
                    "has_valid_return": False,
                    "exclusion_reason": "INVALID_PRICE_VALUE",
                })
        else:
            records.append({
                "cik": cik,
                "ticker": t,
                "company_name": name,
                "market_cap_2016": mcap,
                "has_valid_return": False,
                "exclusion_reason": "MISSING_2026_PRICE",
            })

    return pd.DataFrame(records)


def define_winner_groups(universe_returns_df: pd.DataFrame) -> pd.DataFrame:
    """Label universe companies into objective winner and control groups."""
    df = universe_returns_df.copy()
    valid_df = df[df["has_valid_return"] == True].sort_values("cagr", ascending=False).reset_index(drop=True)

    valid_df["return_rank"] = valid_df.index + 1
    total_valid = len(valid_df)

    # Group definitions
    valid_df["is_w1_top25"] = valid_df["return_rank"] <= 25
    valid_df["is_w1_top50"] = valid_df["return_rank"] <= 50
    valid_df["is_w2_cagr20"] = valid_df["cagr"] >= 0.20
    valid_df["is_w2_cagr15"] = valid_df["cagr"] >= 0.15
    valid_df["is_non_winner"] = valid_df["cagr"] < 0.10

    # Categorical primary label
    conditions = [
        valid_df["is_w1_top25"],
        valid_df["is_w1_top50"] & (~valid_df["is_w1_top25"]),
        valid_df["is_w2_cagr20"] & (~valid_df["is_w1_top50"]),
        valid_df["is_w2_cagr15"] & (~valid_df["is_w2_cagr20"]),
        valid_df["is_non_winner"],
    ]
    choices = [
        "EXTREME_WINNER_TOP25",
        "EXTREME_WINNER_TOP26_50",
        "HIGH_COMPOUNDER_20PLUS",
        "MODERATE_COMPOUNDER_15_20",
        "NON_WINNER_UNDER10",
    ]
    valid_df["winner_tier"] = np.select(conditions, choices, default="AVERAGE_PERFORMER_10_15")

    invalid_df = df[df["has_valid_return"] != True].copy()
    if not invalid_df.empty:
        invalid_df["return_rank"] = np.nan
        invalid_df["is_w1_top25"] = False
        invalid_df["is_w1_top50"] = False
        invalid_df["is_w2_cagr20"] = False
        invalid_df["is_w2_cagr15"] = False
        invalid_df["is_non_winner"] = False
        invalid_df["winner_tier"] = "EXCLUDED_MISSING_PRICE"
        return pd.concat([valid_df, invalid_df], ignore_index=True)

    return valid_df
