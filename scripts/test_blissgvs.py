"""Test and reconstruct the strategy on BLISSGVS."""

import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect("data/indian_market.db")

# 1. Fetch BLISSGVS monthly candles
monthly_df = pd.read_sql("""
    SELECT m.*, s.symbol, s.company_name
    FROM monthly_ohlcv m
    JOIN securities s ON s.security_id = m.security_id
    WHERE s.symbol = 'BLISSGVS'
    ORDER BY m.year_month ASC;
""", conn)

print("BLISSGVS monthly candles count:", len(monthly_df))

# Calculate Monthly RSI(14)
closes = monthly_df["close"]
delta = closes.diff()
gain = delta.clip(lower=0.0)
loss = -delta.clip(upper=0.0)
# Wilder / standard EMA smoothing for RSI
avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
rs = avg_gain / avg_loss.replace(0.0, 1e-9)
monthly_df["rsi14"] = 100.0 - (100.0 / (1.0 + rs))

# Calculate Monthly EMA(9)
monthly_df["ema9"] = closes.ewm(span=9, adjust=False).mean()

# Qualification condition: RSI14 > 70 AND Close > EMA9
monthly_df["is_candidate"] = (monthly_df["rsi14"] > 70.0) & (monthly_df["close"] > monthly_df["ema9"])

candidates = monthly_df[monthly_df["is_candidate"]]
print("\nBLISSGVS Qualified Months (RSI > 70 and Close > EMA9):")
for _, r in candidates.iterrows():
    print(f"  Month: {r['year_month']} | Close: {r['close']:6.2f} | EMA9: {r['ema9']:6.2f} | RSI: {r['rsi14']:5.2f} | End Date: {r['end_date']}")

# 2. Fetch BLISSGVS daily candles
daily_df = pd.read_sql("""
    SELECT d.*
    FROM daily_ohlcv d
    JOIN securities s ON s.security_id = d.security_id
    WHERE s.symbol = 'BLISSGVS'
    ORDER BY d.date ASC;
""", conn)
conn.close()

daily_df["date"] = pd.to_datetime(daily_df["date"])
daily_df = daily_df.sort_values("date").reset_index(drop=True)

# Daily indicators:
# Daily EMA(21)
daily_df["ema21"] = daily_df["close"].ewm(span=21, adjust=False).mean()
# 20-day resistance = highest HIGH of previous 20 completed days (shift(1).rolling(20).max())
daily_df["resistance_20"] = daily_df["high"].shift(1).rolling(20).max()
# 20-day average volume
daily_df["vol_sma20"] = daily_df["volume"].shift(1).rolling(20).mean()

print("\nBLISSGVS daily candles loaded:", len(daily_df))
