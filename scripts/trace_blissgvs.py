"""Inspect BLISSGVS daily candles during qualification period."""

import sqlite3
import pandas as pd

conn = sqlite3.connect("data/indian_market.db")
df = pd.read_sql("""
    SELECT d.date, d.open, d.high, d.low, d.close, d.volume
    FROM daily_ohlcv d
    JOIN securities s ON s.security_id = d.security_id
    WHERE s.symbol = 'BLISSGVS' AND d.date >= '2026-03-01'
    ORDER BY d.date ASC;
""", conn)
conn.close()

df["date"] = pd.to_datetime(df["date"])
df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
df["resistance_20"] = df["high"].shift(1).rolling(20).max()
df["vol_sma20"] = df["volume"].shift(1).rolling(20).mean()

# Filter from April 2026 onwards
sample = df[(df["date"] >= "2026-04-01") & (df["date"] <= "2026-06-15")]
print(f"Date range: {sample.iloc[0]['date'].strftime('%Y-%m-%d')} to {sample.iloc[-1]['date'].strftime('%Y-%m-%d')}")
for _, r in sample.iterrows():
    d_str = r['date'].strftime('%Y-%m-%d')
    c = r['close']
    o = r['open']
    h = r['high']
    l = r['low']
    res = r['resistance_20']
    ema = r['ema21']
    is_breakout = (c > res) if pd.notna(res) else False
    in_retest = (l <= res * 1.005 and h >= res * 0.995) if pd.notna(res) else False
    is_green = (c > o)
    above_ema = (c > ema)
    flags = []
    if is_breakout: flags.append("BREAKOUT")
    if in_retest: flags.append("IN_RETEST")
    if in_retest and is_green and (c > res) and above_ema: flags.append("***CONFIRMED***")
    flag_str = " | ".join(flags)
    print(f"{d_str} | O:{o:6.2f} H:{h:6.2f} L:{l:6.2f} C:{c:6.2f} | Res:{res:6.2f} EMA21:{ema:6.2f} | {flag_str}")
