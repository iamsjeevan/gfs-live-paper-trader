"""
live_paper_trader.signals
=========================
Fast, robust market data fetcher & scanner for Indian equities.
Implements:
1. Macro Regime Gate (Index vs 200 EMA & 50 EMA)
2. Live Intraday Price & Low Checker (for -12% GTT Circuit Guard)
3. Stage 2 + 52-Week High Breakout Scanner
"""

import logging
import time
from typing import Dict, Any, List
import pandas as pd
import numpy as np
import yfinance as yf

from live_paper_trader.config import (
    REGIME_INDEX,
    CASH_PROXY
)

logger = logging.getLogger("live_paper_trader.signals")

def get_market_regime() -> Dict[str, Any]:
    """
    Checks the broad Indian market regime using Nifty / Smallcap index.
    BULL (Green)    : Close > 200 EMA and Close > 50 EMA (100% capacity)
    NEUTRAL (Yellow): Close > 200 EMA but <= 50 EMA (50% capacity)
    BEAR (Red)      : Close <= 200 EMA (0% equity, 100% Gold BeES)
    """
    try:
        t = yf.Ticker(REGIME_INDEX)
        df = t.history(period="1y", interval="1d")
        if df.empty or len(df) < 200:
            logger.warning(f"Insufficient history for {REGIME_INDEX}, defaulting to BULL")
            return {"regime": "BULL", "close": 0.0, "ema200": 0.0, "ema50": 0.0, "ret63": 0.0}

        close = df["Close"]
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        last_close = close.iloc[-1]

        # 63-day benchmark return
        ret63 = (last_close / close.iloc[-63] - 1) if len(close) >= 63 else 0.0

        if last_close > ema200 and last_close > ema50:
            regime = "BULL"
        elif last_close > ema200:
            regime = "NEUTRAL"
        else:
            regime = "BEAR"

        logger.info(f"Market Regime for {REGIME_INDEX}: {regime} (Close: {last_close:,.1f}, 200 EMA: {ema200:,.1f})")
        return {
            "regime": regime,
            "close": float(last_close),
            "ema200": float(ema200),
            "ema50": float(ema50),
            "ret63": float(ret63)
        }
    except Exception as e:
        logger.error(f"Error fetching market regime: {e}")
        return {"regime": "BULL", "close": 0.0, "ema200": 0.0, "ema50": 0.0, "ret63": 0.0}

def get_proxy_price(symbol: str = CASH_PROXY) -> Dict[str, float]:
    """Fetches latest Open and Close for Gold BeES / cash parking."""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="5d", interval="1d")
        if df.empty:
            return {"open": 60.0, "close": 60.0}
        last = df.iloc[-1]
        return {
            "open": float(last["Open"]),
            "close": float(last["Close"])
        }
    except Exception as e:
        logger.error(f"Error fetching proxy price for {symbol}: {e}")
        return {"open": 60.0, "close": 60.0}

def get_intraday_quotes(symbols: List[str]) -> Dict[str, Dict[str, float]]:
    """
    Fetches latest intraday prices (Open, High, Low, Close) for currently held positions.
    Used for monitoring the -12% Emergency Intraday GTT Circuit Guard.
    """
    if not symbols:
        return {}
    
    tickers = [s if s.endswith(".NS") else f"{s}.NS" for s in symbols]
    quotes = {}
    try:
        data = yf.download(tickers, period="2d", interval="1d", progress=False)
        for s in symbols:
            t_key = s if s.endswith(".NS") else f"{s}.NS"
            try:
                if len(tickers) == 1:
                    row = data.iloc[-1]
                    quotes[s] = {
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "current": float(row["Close"])
                    }
                else:
                    o = float(data["Open"][t_key].dropna().iloc[-1])
                    h = float(data["High"][t_key].dropna().iloc[-1])
                    l = float(data["Low"][t_key].dropna().iloc[-1])
                    c = float(data["Close"][t_key].dropna().iloc[-1])
                    quotes[s] = {
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": c,
                        "current": c
                    }
            except Exception as e:
                logger.warning(f"Could not parse quote for {s}: {e}")
    except Exception as e:
        logger.error(f"Batch quote fetch failed: {e}")
        
    return quotes

def scan_universe_for_setups(universe_symbols: List[str], benchmark_ret63: float) -> List[Dict[str, Any]]:
    """
    Scans liquid Indian equities for the 5-Engine Entry Checklist:
    1. Stage 2 Trend: Close > EMA20 > EMA50 > EMA200
    2. Near 52-Week High: Close >= 0.96 * 52W High
    3. 63-day Relative Strength Alpha vs Benchmark > 0
    4. Breakout Volume: Volume >= 1.5x 20-day median volume
    5. Clean liquidity floor: Price >= ₹50
    """
    tickers = [s if s.endswith(".NS") else f"{s}.NS" for s in universe_symbols]
    logger.info(f"Scanning {len(tickers)} Indian stocks for Stage 2 & 52W High breakouts...")

    candidates = []
    # Batch download historical daily candles (period: 1y)
    try:
        # Download in chunks of 100 for safety against timeouts
        chunk_size = 100
        for k in range(0, len(tickers), chunk_size):
            chunk = tickers[k:k + chunk_size]
            data = yf.download(chunk, period="1y", interval="1d", group_by="ticker", progress=False)
            
            for sym_raw in chunk:
                clean_sym = sym_raw.replace(".NS", "")
                try:
                    df = data[sym_raw] if len(chunk) > 1 else data
                    df = df.dropna(subset=["Close", "Volume"])
                    if len(df) < 180:
                        continue

                    close = df["Close"]
                    vol = df["Volume"]
                    last_c = float(close.iloc[-1])
                    
                    if last_c < 50.0:
                        continue

                    # Moving averages
                    e20 = close.ewm(span=20, adjust=False).mean()
                    e50 = close.ewm(span=50, adjust=False).mean()
                    e200 = close.ewm(span=200, adjust=False).mean()
                    
                    c_val = last_c
                    e20_val = float(e20.iloc[-1])
                    e50_val = float(e50.iloc[-1])
                    e200_val = float(e200.iloc[-1])

                    # 1. Stage 2 Check
                    if not (c_val > e20_val and e20_val > e50_val and e50_val > e200_val):
                        continue

                    # 2. Near 52-Week High Check (within 4%)
                    h52 = float(close.rolling(252, min_periods=150).max().iloc[-1])
                    dist_52 = (c_val / h52 - 1.0)
                    if dist_52 < -0.04:
                        continue

                    # 3. 63-Day RS Alpha Check
                    ret63 = (c_val / close.iloc[-63] - 1.0) if len(close) >= 63 else 0.0
                    rs_alpha = ret63 - benchmark_ret63
                    if rs_alpha <= 0.0:
                        continue

                    # 4. Volume Surge Check (>= 1.5x 20-day median)
                    vol_med20 = float(vol.rolling(20, min_periods=10).median().iloc[-1])
                    last_vol = float(vol.iloc[-1])
                    vol_ratio = (last_vol / vol_med20) if vol_med20 > 0 else 1.0
                    if vol_ratio < 1.3: # Allow 1.3x floor for robust live screening
                        continue

                    # Passed all 4 filters!
                    candidates.append({
                        "symbol": clean_sym,
                        "ticker": sym_raw,
                        "close": c_val,
                        "e20": e20_val,
                        "e50": e50_val,
                        "e200": e200_val,
                        "h52": h52,
                        "dist_52_pct": round(dist_52 * 100, 2),
                        "rs_alpha_pct": round(rs_alpha * 100, 2),
                        "vol_ratio": round(vol_ratio, 2),
                        "composite_score": round(rs_alpha * 100, 2)
                    })
                except Exception as e:
                    continue

        # Sort by composite RS Alpha descending
        candidates.sort(key=lambda x: x["composite_score"], reverse=True)
        logger.info(f"Scan complete: Found {len(candidates)} qualified Stage 2 Breakout candidates.")
        return candidates
    except Exception as e:
        logger.error(f"Error during universe scan: {e}")
        return []
