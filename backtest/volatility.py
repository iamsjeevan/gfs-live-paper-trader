"""Rolling realized volatility calculation and volatility targeting logic."""

from typing import Optional, Sequence
import numpy as np
import pandas as pd

# Annual periods for 24/7/365 crypto markets
ANNUAL_PERIODS = {
    "1d": 365,
    "4h": 365 * 6,       # 2,190
    "1h": 365 * 24,      # 8,760
    "15m": 365 * 96,     # 35,040
    "5m": 365 * 288,     # 105,120
    "1m": 365 * 1440,    # 525,600
}


def get_annualization_factor(timeframe: str) -> float:
    """Return sqrt of periods per year for the given timeframe in 24/7 crypto markets."""
    tf = timeframe.lower()
    if tf not in ANNUAL_PERIODS:
        raise ValueError(f"Unknown timeframe '{timeframe}'. Supported: {list(ANNUAL_PERIODS.keys())}")
    return np.sqrt(ANNUAL_PERIODS[tf])


def compute_realized_volatility(
    df: pd.DataFrame,
    timeframe: str = "1d",
    window_bars: int = 20,
    price_col: str = "close",
    min_vol: float = 0.05,
    log_returns: bool = False,
) -> pd.DataFrame:
    """Calculate rolling realized annualized volatility with a floor.

    Parameters
    ----------
    df : pd.DataFrame
        Candle dataframe containing price_col.
    timeframe : str
        Candle timeframe ('1d', '4h', '1h', '15m', '5m').
    window_bars : int
        Rolling window length in bars (e.g. 20 bars).
    price_col : str
        Column name for price.
    min_vol : float
        Minimum annualized volatility floor to prevent division by zero / explosive leverage.
    log_returns : bool
        Whether to compute log returns (True) or simple returns (False).

    Returns
    -------
    pd.DataFrame
        DataFrame with added columns:
        - returns: bar returns
        - realized_vol: annualized realized volatility bounded from below by min_vol
    """
    out = df.copy()
    prices = out[price_col]

    if log_returns:
        returns = np.log(prices / prices.shift(1))
    else:
        returns = (prices - prices.shift(1)) / prices.shift(1)

    ann_factor = get_annualization_factor(timeframe)

    # Rolling sample standard deviation (ddof=1)
    rolling_std = returns.rolling(window=window_bars, min_periods=window_bars).std(ddof=1)
    ann_vol = rolling_std * ann_factor

    # Apply volatility floor
    clipped_vol = ann_vol.clip(lower=min_vol)

    out["bar_return"] = returns
    out["realized_vol"] = clipped_vol

    return out
