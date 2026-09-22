"""Signal calculation for Bitcoin 4-lookback momentum strategy."""

from typing import List, Sequence, Tuple, Union
import numpy as np
import pandas as pd


# Default baseline lookbacks (in calendar days)
DEFAULT_LOOKBACKS_DAYS = (5, 10, 21, 42)

# Bars per day for each supported timeframe
BARS_PER_DAY = {
    "1d": 1,
    "4h": 6,
    "1h": 24,
    "15m": 96,
    "5m": 288,
    "1m": 1440,
}


def get_lookbacks(timeframe: str, mode: str = "time_scaled", base_days: Sequence[int] = DEFAULT_LOOKBACKS_DAYS) -> List[int]:
    """Return lookbacks in terms of candle count for a given timeframe and mode.

    Parameters
    ----------
    timeframe : str
        Candle timeframe ('1d', '4h', '1h', '15m', '5m').
    mode : str
        'time_scaled' -> lookback scaled to match equivalent calendar duration (e.g. 5d * 24 = 120 bars on 1h).
        'raw' -> raw candle count (e.g. 5, 10, 21, 42 candles on the given timeframe).
    base_days : Sequence[int]
        Base lookbacks in days (default: 5, 10, 21, 42).

    Returns
    -------
    List[int]
        Number of bars for each lookback window.
    """
    tf = timeframe.lower()
    if tf not in BARS_PER_DAY:
        raise ValueError(f"Unknown timeframe '{timeframe}'. Supported: {list(BARS_PER_DAY.keys())}")

    if mode == "raw":
        return list(base_days)
    elif mode == "time_scaled":
        factor = BARS_PER_DAY[tf]
        return [int(d * factor) for d in base_days]
    else:
        raise ValueError(f"Unknown lookback mode '{mode}'. Must be 'time_scaled' or 'raw'.")


def compute_momentum_signals(
    df: pd.DataFrame,
    lookbacks: Sequence[int] = (5, 10, 21, 42),
    close_col: str = "close",
) -> pd.DataFrame:
    """Calculate point-in-time momentum signals and composite momentum score.

    For each lookback L:
        signal_L = sign(close_t - close_{t - L}) in {-1, +1} (or 0 if exact tie)
    
    Composite score:
        score = sum(signal_L) in {-4, -2, 0, +2, +4}

    Parameters
    ----------
    df : pd.DataFrame
        Dataframe containing at least the close price column, sorted ascending by time.
    lookbacks : Sequence[int]
        List of lookback bar counts.
    close_col : str
        Column name for close prices.

    Returns
    -------
    pd.DataFrame
        A new DataFrame with added columns:
        - signal_{L}: directional signal for each lookback
        - momentum_score: composite score
    """
    out = df.copy()
    close_series = out[close_col]

    score_series = pd.Series(0.0, index=out.index)

    for lb in lookbacks:
        diff = close_series - close_series.shift(lb)
        # Sign: +1 if diff > 0, -1 if diff < 0, 0 if diff == 0
        sig = np.where(diff > 0, 1.0, np.where(diff < 0, -1.0, 0.0))
        sig = pd.Series(sig, index=out.index)
        sig[diff.isna()] = np.nan
        col_name = f"signal_{lb}"
        out[col_name] = sig
        score_series = score_series + sig.fillna(0.0)

    # Set composite score to NaN if the longest lookback hasn't accumulated enough data
    max_lb = max(lookbacks) if len(lookbacks) > 0 else 0
    score_series.iloc[:max_lb] = np.nan
    out["momentum_score"] = score_series

    return out
