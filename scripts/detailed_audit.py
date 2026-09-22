"""Detailed audit of Indian stock coverage and gaps."""

import sqlite3
import pandas as pd

# Load existing DB
conn = sqlite3.connect("data/nse_stocks_all_years.db")
db_symbols = set(pd.read_sql("SELECT DISTINCT symbol FROM daily_prices;", conn)["symbol"])
cm_symbols = set(pd.read_sql("SELECT DISTINCT symbol FROM company_master;", conn)["symbol"])

# Load tickers.csv (Nifty 500)
nifty500_df = pd.read_csv("data/tickers.csv")
nifty500_symbols = set(nifty500_df["Symbol"].dropna().str.strip())

# Load equity_master.csv (Full NSE universe)
em_df = pd.read_csv("data/equity_master.csv")
em_symbols = set(em_df["SYMBOL"].dropna().str.strip())

print("=== UNIVERSE COVERAGE AUDIT ===")
print(f"Total symbols in equity_master.csv (Full NSE universe): {len(em_symbols):,}")
print(f"Total symbols in tickers.csv (Nifty 500 universe):      {len(nifty500_symbols):,}")
print(f"Total symbols in company_master (nse_stocks_all_years): {len(cm_symbols):,}")
print(f"Total symbols in daily_prices  (nse_stocks_all_years): {len(db_symbols):,}")

# Overlaps
nifty_in_db = nifty500_symbols.intersection(db_symbols)
nifty_missing = nifty500_symbols - db_symbols
print(f"\nNifty 500 in daily_prices: {len(nifty_in_db):,} / {len(nifty500_symbols):,} ({len(nifty_in_db)/len(nifty500_symbols)*100:.1f}%)")
print(f"Nifty 500 MISSING from daily_prices: {len(nifty_missing)}")
if nifty_missing:
    print("Sample missing Nifty 500 symbols:", sorted(list(nifty_missing))[:15])

em_in_db = em_symbols.intersection(db_symbols)
em_missing = em_symbols - db_symbols
print(f"\nFull NSE universe in daily_prices: {len(em_in_db):,} / {len(em_symbols):,} ({len(em_in_db)/len(em_symbols)*100:.1f}%)")
print(f"Full NSE universe missing: {len(em_missing):,}")

# Check Date Coverage
dates_df = pd.read_sql("SELECT MIN(date) as min_date, MAX(date) as max_date, COUNT(DISTINCT date) as days FROM daily_prices WHERE close IS NOT NULL;", conn)
print(f"\nDate Range in daily_prices: {dates_df.iloc[0]['min_date']} to {dates_df.iloc[0]['max_date']} ({dates_df.iloc[0]['days']} trading days)")

# Check symbol-level completeness across trading days
sym_days = pd.read_sql("SELECT symbol, COUNT(*) as cnt FROM daily_prices WHERE close IS NOT NULL GROUP BY symbol;", conn)
print(f"\nSymbol trading days statistics (out of max {dates_df.iloc[0]['days']}):")
print(f"  Mean days per symbol:   {sym_days['cnt'].mean():.1f}")
print(f"  Median days per symbol: {sym_days['cnt'].median():.1f}")
print(f"  Min days per symbol:    {sym_days['cnt'].min()}")
print(f"  Max days per symbol:    {sym_days['cnt'].max()}")
complete_syms = (sym_days["cnt"] >= 2100).sum()
print(f"  Symbols with >= 2,100 days (full 2018-2026 history): {complete_syms:,} ({complete_syms/len(sym_days)*100:.1f}%)")

# Check missing dates from 2026-08-25 to 2026-09-17
print("\nMissing Date Range:")
print("  Latest date in DB: 2026-08-24")
print("  Target current date: 2026-09-17")
print("  Missing recent period: 2026-08-25 through 2026-09-17 (~17 trading days)")

conn.close()
