"""Audit data/nse_stocks_all_years.db for Indian equities."""

import sqlite3
import pandas as pd

conn = sqlite3.connect("data/nse_stocks_all_years.db")

# 1. Total distinct symbols in daily_prices
symbols_df = pd.read_sql("SELECT DISTINCT symbol FROM daily_prices;", conn)
symbols = symbols_df["symbol"].tolist()
print(f"Total distinct symbols in daily_prices: {len(symbols):,}")

# 2. Check major symbols
test_syms = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "TATAMOTORS", "ITC", "SBIN", "BHARTIARTL", "NIFTY50"]
print("\nMajor symbols audit:")
for sym in test_syms:
    df = pd.read_sql("SELECT MIN(date) as min_d, MAX(date) as max_d, COUNT(*) as cnt, COUNT(open) as o_cnt, COUNT(close) as c_cnt FROM daily_prices WHERE symbol=?", conn, params=[sym])
    min_d = df.iloc[0]["min_d"]
    max_d = df.iloc[0]["max_d"]
    cnt = df.iloc[0]["cnt"]
    o_cnt = df.iloc[0]["o_cnt"]
    c_cnt = df.iloc[0]["c_cnt"]
    print(f"Symbol: {sym:12s} | Dates: {min_d} to {max_d} | Rows: {cnt:,} | Open: {o_cnt:,} | Close: {c_cnt:,}")

# 3. Check Date Distribution across all symbols
date_stats = pd.read_sql("SELECT date, COUNT(DISTINCT symbol) as sym_count FROM daily_prices WHERE close IS NOT NULL GROUP BY date ORDER BY date;", conn)
print(f"\nTotal trading days in database: {len(date_stats):,}")
print(f"Earliest date: {date_stats.iloc[0]['date']} (with {date_stats.iloc[0]['sym_count']} symbols)")
print(f"Latest date:   {date_stats.iloc[-1]['date']} (with {date_stats.iloc[-1]['sym_count']} symbols)")

# Check symbol coverage across time
mid_2018 = date_stats[date_stats["date"].str.startswith("2018")]["sym_count"].median()
mid_2020 = date_stats[date_stats["date"].str.startswith("2020")]["sym_count"].median()
mid_2022 = date_stats[date_stats["date"].str.startswith("2022")]["sym_count"].median()
mid_2024 = date_stats[date_stats["date"].str.startswith("2024")]["sym_count"].median()
mid_2026 = date_stats[date_stats["date"].str.startswith("2026")]["sym_count"].median()

print(f"\nMedian active symbols per day by year:")
print(f"  2018: {mid_2018:.0f} symbols")
print(f"  2020: {mid_2020:.0f} symbols")
print(f"  2022: {mid_2022:.0f} symbols")
print(f"  2024: {mid_2024:.0f} symbols")
print(f"  2026: {mid_2026:.0f} symbols")

# 4. Check data quality: OHLC relationships
ohlc_check = pd.read_sql("""
    SELECT 
        COUNT(*) as total_rows,
        SUM(CASE WHEN open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL THEN 1 ELSE 0 END) as null_ohlc,
        SUM(CASE WHEN high < low THEN 1 ELSE 0 END) as high_lt_low,
        SUM(CASE WHEN high < open OR high < close THEN 1 ELSE 0 END) as high_lt_open_close,
        SUM(CASE WHEN low > open OR low > close THEN 1 ELSE 0 END) as low_gt_open_close,
        SUM(CASE WHEN close <= 0 THEN 1 ELSE 0 END) as non_positive_close,
        SUM(CASE WHEN volume < 0 THEN 1 ELSE 0 END) as negative_vol
    FROM daily_prices;
""", conn)
print("\nOHLC Quality Audit on 2.64M rows:")
for col in ohlc_check.columns:
    print(f"  {col:25s}: {ohlc_check.iloc[0][col]:,}")

# 5. Check technical_valuation_data and fundamentals
tech_df = pd.read_sql("SELECT COUNT(*) as c FROM technical_valuation_data;", conn)
print(f"\nTechnical valuation table: {tech_df.iloc[0]['c']:,} rows")
fin_pl = pd.read_sql("SELECT COUNT(*) as c, COUNT(DISTINCT symbol) as s FROM financial_profit_loss;", conn)
print(f"Financial P&L table:        {fin_pl.iloc[0]['c']:,} rows across {fin_pl.iloc[0]['s']:,} symbols")
fin_bs = pd.read_sql("SELECT COUNT(*) as c, COUNT(DISTINCT symbol) as s FROM financial_balance_sheet;", conn)
print(f"Financial Balance Sheet:    {fin_bs.iloc[0]['c']:,} rows across {fin_bs.iloc[0]['s']:,} symbols")
fin_r = pd.read_sql("SELECT COUNT(*) as c, COUNT(DISTINCT symbol) as s FROM financial_ratios;", conn)
print(f"Financial Ratios table:     {fin_r.iloc[0]['c']:,} rows across {fin_r.iloc[0]['s']:,} symbols")

conn.close()
