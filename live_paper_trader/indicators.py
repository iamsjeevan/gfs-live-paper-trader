"""
live_paper_trader.indicators
============================
Multi-timeframe technical indicator calculations for the GFS strategy:
- Daily, Weekly, and Monthly RSI(14) with Wilder's exponential smoothing
- Daily, Weekly, and Monthly EMAs (9, 13, 21, 50, 200)
- Month-end calendar detection
"""

import pandas as pd
import numpy as np
from typing import Dict, Any

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Computes Wilder's Smoothed RSI."""
    if len(series) < period + 1:
        return pd.Series(50.0, index=series.index)
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)

def compute_ema(series: pd.Series, span: int) -> pd.Series:
    """Computes Exponential Moving Average."""
    return series.ewm(span=span, adjust=False).mean()

def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resamples daily OHLCV DataFrame into weekly candles."""
    df_w = df.resample("W-FRI").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()
    return df_w

def resample_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """Resamples daily OHLCV DataFrame into monthly candles."""
    df_m = df.resample("ME").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()
    return df_m

def is_month_end_trading_day(current_date: pd.Timestamp, future_trading_days: list = None) -> bool:
    """
    Determines if current_date is the last trading day of the calendar month.
    """
    next_day = current_date + pd.Timedelta(days=1)
    # If the next day is a new month, today is definitely the month end
    if next_day.month != current_date.month:
        return True
    # If next day is weekend or holiday and rolls into next month
    days_to_end = (pd.Period(current_date, freq='M').end_time.date() - current_date.date()).days
    if current_date.dayofweek == 4 and days_to_end <= 2: # Friday within 2 days of month end
        return True
    return False
