"""Mathematical indicators engine for Indian Equity Paper Trading.

Calculates:
- Monthly RSI(14)
- Monthly EMA(9)
- Daily EMA(21)
- 20-Day Resistance (Highest High of previous 20 completed days)
- 20-Day Average Daily Turnover (ADT)
- Relative Volume on Breakout: Volume / 20-day SMA Volume
"""

import numpy as np
import pandas as pd
from typing import Tuple

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calculate Relative Strength Index (RSI) using Wilder's smoothing."""
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, 1e-9)
    return 100.0 - (100.0 / (1.0 + rs))

def compute_ema(series: pd.Series, span: int) -> pd.Series:
    """Calculate Exponential Moving Average (EMA)."""
    return series.ewm(span=span, adjust=False).mean()

def compute_20d_resistance(high_series: pd.Series, lookback: int = 20) -> pd.Series:
    """Calculate 20-day resistance = Highest High of previous 20 completed days.
    
    IMPORTANT: Excludes current candle via shift(1).
    """
    return high_series.shift(1).rolling(lookback).max()

def compute_turnover_cr(volume_series: pd.Series, close_series: pd.Series) -> pd.Series:
    """Calculate Daily Turnover in Crores (₹ Cr)."""
    # 1 Crore = 10,000,000 INR
    return (volume_series * close_series) / 10_000_000.0

def compute_relative_volume(volume_series: pd.Series, lookback: int = 20) -> pd.Series:
    """Calculate Relative Volume = Current Volume / 20-day SMA Volume of previous days.
    
    Uses shift(1) so current day's volume is compared to the completed 20-day average.
    """
    sma_vol = volume_series.shift(1).rolling(lookback).mean().replace(0.0, 1e-9)
    return volume_series / sma_vol

def build_monthly_indicators(daily_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate daily bars into completed monthly bars and compute Monthly RSI(14) and EMA(9).
    
    Expected daily_df columns: ['date', 'open', 'high', 'low', 'close', 'volume']
    Returns DataFrame with columns: ['year_month', 'open', 'high', 'low', 'close', 'volume', 'rsi14', 'ema9', 'is_candidate', 'end_date']
    """
    df = daily_df.copy()
    df["date_dt"] = pd.to_datetime(df["date"])
    df["year_month"] = df["date_dt"].dt.strftime("%Y-%m")
    
    monthly_bars = []
    for ym, g in df.groupby("year_month"):
        g = g.sort_values("date_dt")
        m_open = g["open"].iloc[0]
        m_high = g["high"].max()
        m_low = g["low"].min()
        m_close = g["close"].iloc[-1]
        m_vol = g["volume"].sum()
        end_d = g["date"].iloc[-1]
        monthly_bars.append({
            "year_month": ym,
            "open": m_open,
            "high": m_high,
            "low": m_low,
            "close": m_close,
            "volume": m_vol,
            "end_date": end_d
        })
    
    m_df = pd.DataFrame(monthly_bars).sort_values("year_month").reset_index(drop=True)
    if len(m_df) < 15:
        m_df["rsi14"] = np.nan
        m_df["ema9"] = np.nan
        m_df["is_candidate"] = 0
        return m_df
    
    m_df["rsi14"] = compute_rsi(m_df["close"], 14)
    m_df["ema9"] = compute_ema(m_df["close"], 9)
    m_df["is_candidate"] = ((m_df["rsi14"] > 70.0) & (m_df["close"] > m_df["ema9"])).astype(int)
    
    return m_df
