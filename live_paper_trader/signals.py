"""
live_paper_trader.signals
=========================
Live data fetcher and GFS signal generator for Indian and US markets.
Downloads multi-timeframe candles using yfinance and generates
institutional GFS Entry & Exit signals.
"""

import logging
import json
import time
from typing import Dict, Any, List, Tuple
import pandas as pd
import numpy as np
import yfinance as yf

from live_paper_trader.config import (
    INDIA_CASH_PROXY,
    INDIA_INDEX_TICKER,
    INDIA_MONTHLY_EMA_SPAN,
    USA_CASH_PROXY,
    USA_INDEX_TICKER,
    USA_MONTHLY_EMA_SPAN
)
from live_paper_trader.indicators import (
    compute_rsi,
    compute_ema,
    resample_weekly,
    resample_monthly
)

logger = logging.getLogger("live_paper_trader.signals")

def get_market_regime(index_symbol: str) -> Dict[str, Any]:
    """
    Fetches the benchmark index (^NSEI or SPY) and determines the macro regime:
    BULL: Close > 200 SMA and Close > 50 SMA
    NEUTRAL: Close > 200 SMA but <= 50 SMA
    BEAR: Close <= 200 SMA
    """
    try:
        t = yf.Ticker(index_symbol)
        df = t.history(period="2y", interval="1d")
        if df.empty or len(df) < 200:
            logger.warning(f"Insufficient history for index {index_symbol}, defaulting to BULL")
            return {"regime": "BULL", "close": 0.0, "sma200": 0.0}

        close = df["Close"]
        sma200 = close.rolling(window=200).mean().iloc[-1]
        sma50 = close.rolling(window=50).mean().iloc[-1]
        last_close = close.iloc[-1]

        if last_close > sma200 and last_close > sma50:
            regime = "BULL"
        elif last_close > sma200:
            regime = "NEUTRAL"
        else:
            regime = "BEAR"

        logger.info(f"Market Regime for {index_symbol}: {regime} (Close: {last_close:,.1f}, 200 SMA: {sma200:,.1f})")
        return {
            "regime": regime,
            "close": float(last_close),
            "sma200": float(sma200),
            "sma50": float(sma50)
        }
    except Exception as e:
        logger.error(f"Failed to fetch market regime for {index_symbol}: {e}")
        return {"regime": "BULL", "close": 0.0, "sma200": 0.0}

def get_proxy_price(proxy_symbol: str) -> Dict[str, float]:
    """Fetches latest Open and Close for cash parking proxy (GOLDBEES or BIL)."""
    try:
        t = yf.Ticker(proxy_symbol)
        df = t.history(period="5d", interval="1d")
        if df.empty:
            raise ValueError(f"No price data returned for {proxy_symbol}")
        last_row = df.iloc[-1]
        return {
            "open": float(last_row["Open"]),
            "close": float(last_row["Close"]),
            "date": str(df.index[-1].date())
        }
    except Exception as e:
        logger.error(f"Error fetching proxy price for {proxy_symbol}: {e}")
        return {"open": 100.0, "close": 100.0, "date": ""}

def evaluate_gfs_for_stock(df: pd.DataFrame, monthly_ema_span: int = 9) -> Dict[str, Any]:
    """
    Evaluates GFS setup criteria for a single stock history DataFrame:
    1. Monthly RSI > 60 AND Monthly Close > Monthly EMA(span)
    2. Weekly RSI > 60
    3. Daily RSI crossed above 40 (prev <= 40, curr > 40)
    """
    if len(df) < 60:
        return {"valid": False, "reason": "Insufficient daily bars"}

    # Clean missing values
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    # 1. Daily RSI
    df["daily_rsi"] = compute_rsi(df["Close"], 14)
    if len(df["daily_rsi"]) < 2:
        return {"valid": False, "reason": "Insufficient RSI history"}
    curr_d_rsi = df["daily_rsi"].iloc[-1]
    prev_d_rsi = df["daily_rsi"].iloc[-2]
    daily_trigger = (prev_d_rsi <= 40.0) and (curr_d_rsi > 40.0)

    # 2. Weekly RSI
    df_w = resample_weekly(df)
    if len(df_w) < 15:
        return {"valid": False, "reason": "Insufficient weekly bars"}
    df_w["weekly_rsi"] = compute_rsi(df_w["Close"], 14)
    curr_w_rsi = df_w["weekly_rsi"].iloc[-1]
    weekly_pass = curr_w_rsi > 60.0

    # 3. Monthly Setup
    df_m = resample_monthly(df)
    if len(df_m) < 15:
        return {"valid": False, "reason": "Insufficient monthly bars"}
    df_m["monthly_rsi"] = compute_rsi(df_m["Close"], 14)
    df_m["monthly_ema"] = compute_ema(df_m["Close"], monthly_ema_span)
    curr_m_rsi = df_m["monthly_rsi"].iloc[-1]
    curr_m_close = df_m["Close"].iloc[-1]
    curr_m_ema = df_m["monthly_ema"].iloc[-1]
    monthly_pass = (curr_m_rsi > 60.0) and (curr_m_close > curr_m_ema)

    is_valid = bool(monthly_pass and weekly_pass and daily_trigger)

    return {
        "valid": is_valid,
        "symbol": "",
        "close": float(df["Close"].iloc[-1]),
        "daily_rsi": float(curr_d_rsi),
        "weekly_rsi": float(curr_w_rsi),
        "monthly_rsi": float(curr_m_rsi),
        "monthly_close": float(curr_m_close),
        "monthly_ema": float(curr_m_ema),
        "monthly_pass": bool(monthly_pass),
        "weekly_pass": bool(weekly_pass),
        "daily_trigger": bool(daily_trigger)
    }

def scan_gfs_universe(
    universe_tickers: List[str],
    market: str = "india",
    batch_size: int = 50,
    max_scan: int = 200
) -> List[Dict[str, Any]]:
    """
    Scans universe tickers in batches to find all active GFS Entry candidates.
    Returns list of candidate dicts ranked by Weekly RSI descending.
    """
    monthly_ema_span = INDIA_MONTHLY_EMA_SPAN if market.lower() == "india" else USA_MONTHLY_EMA_SPAN
    suffix = ".NS" if market.lower() == "india" else ""
    
    # Format symbols
    formatted_symbols = []
    for s in universe_tickers[:max_scan]:
        clean_s = s.strip().upper()
        if market.lower() == "india" and not clean_s.endswith(".NS"):
            clean_s += ".NS"
        formatted_symbols.append(clean_s)

    candidates = []
    print(f"Scanning {len(formatted_symbols)} tickers for {market.upper()} GFS signals...")

    # Download in batches
    for i in range(0, len(formatted_symbols), batch_size):
        batch = formatted_symbols[i:i + batch_size]
        try:
            data = yf.download(batch, period="2y", interval="1d", group_by="ticker", progress=False)
            if data.empty:
                continue

            for sym in batch:
                try:
                    sym_df = data[sym] if len(batch) > 1 else data
                    if sym_df is None or sym_df.empty or len(sym_df.dropna()) < 60:
                        continue
                    
                    res = evaluate_gfs_for_stock(sym_df, monthly_ema_span=monthly_ema_span)
                    if res.get("valid"):
                        res["symbol"] = sym
                        candidates.append(res)
                        print(f"  🔥 GFS SIGNAL FOUND: {sym} (Weekly RSI: {res['weekly_rsi']:.1f}, Daily RSI: {res['daily_rsi']:.1f})")
                except Exception as ex:
                    continue
        except Exception as e:
            logger.warning(f"Batch {i} download error: {e}")
            time.sleep(1)

    # Sort descending by Weekly RSI
    candidates.sort(key=lambda x: x["weekly_rsi"], reverse=True)
    print(f"Found {len(candidates)} valid GFS candidate(s) in {market.upper()}.")
    return candidates

def check_stock_monthly_ema_status(symbol: str, monthly_ema_span: int = 9) -> Dict[str, Any]:
    """
    Checks if a stock has closed below its Monthly EMA on the latest monthly candle.
    Used for month-end exit checking.
    """
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="2y", interval="1d")
        if df.empty or len(df) < 60:
            return {"should_exit": False, "m_close": 0.0, "m_ema": 0.0}
        
        df_m = resample_monthly(df)
        df_m["monthly_ema"] = compute_ema(df_m["Close"], monthly_ema_span)
        last_m = df_m.iloc[-1]
        should_exit = bool(last_m["Close"] < last_m["monthly_ema"])
        return {
            "should_exit": should_exit,
            "m_close": float(last_m["Close"]),
            "m_ema": float(last_m["monthly_ema"])
        }
    except Exception as e:
        logger.error(f"Error checking monthly EMA for {symbol}: {e}")
        return {"should_exit": False, "m_close": 0.0, "m_ema": 0.0}
