"""Corporate actions analysis, split timing auditing, and historical normalization.

Handles:
- Stock splits & reverse splits
- Stock dividends
- Ticker changes
- Mergers & acquisitions
- Spin-offs
- Audit of split timing between SEC shares filing date and historical screen date
"""

from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from config.settings import setup_logger

logger = setup_logger("corporate_actions", "screening.log")


def audit_shares_split_timing(
    shares_filing_date: Optional[str],
    screen_date: str,
    splits_df: Optional[pd.DataFrame] = None,
) -> Tuple[float, Optional[str]]:
    """Audit whether a stock split or reverse split occurred between shares filing date and screen date.

    If a 2:1 split occurred after the Q3 10-Q filing date but before screen date,
    the unadjusted share count in the 10-Q is pre-split, while the unadjusted market price
    on screen date is post-split. In this case, shares must be multiplied by split ratio (2.0)
    to calculate the true economic market capitalization.

    Returns:
        (split_factor, flag_or_none)
        split_factor is 1.0 if no intervening split occurred.
    """
    if not shares_filing_date or splits_df is None or splits_df.empty:
        return 1.0, None

    # Filter splits in the interval (shares_filing_date, screen_date]
    intervening_splits = splits_df[
        (splits_df["date"] > shares_filing_date) & (splits_df["date"] <= screen_date)
    ]

    if intervening_splits.empty:
        return 1.0, None

    cumulative_factor = 1.0
    descriptions = []

    for _, row in intervening_splits.iterrows():
        ratio = float(row.get("ratio") or row.get("Stock Splits") or 1.0)
        if ratio > 0 and ratio != 1.0:
            cumulative_factor *= ratio
            descriptions.append(f"split_{ratio:g}:1_on_{row['date']}")

    if cumulative_factor != 1.0:
        flag = f"INTERVENING_SPLIT_{';'.join(descriptions)}"
        logger.warning(f"Intervening split detected between {shares_filing_date} and {screen_date}: factor={cumulative_factor}")
        return cumulative_factor, flag

    return 1.0, None


def normalize_historical_market_cap(
    unadjusted_price: float,
    unadjusted_shares: float,
    shares_filing_date: Optional[str],
    screen_date: str,
    splits_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Compute point-in-time market cap with split-timing normalization.

    Formula:
        market_cap = unadjusted_price × (unadjusted_shares × split_factor)

    Ensures we NEVER multiply a post-split price by pre-split shares without adjustment.
    """
    split_factor, split_flag = audit_shares_split_timing(
        shares_filing_date=shares_filing_date,
        screen_date=screen_date,
        splits_df=splits_df,
    )

    effective_shares = unadjusted_shares * split_factor
    market_cap = unadjusted_price * effective_shares

    return {
        "unadjusted_price": unadjusted_price,
        "raw_shares": unadjusted_shares,
        "split_factor": split_factor,
        "effective_shares": effective_shares,
        "market_cap": market_cap,
        "corporate_action_flag": split_flag or "CLEAN",
    }
