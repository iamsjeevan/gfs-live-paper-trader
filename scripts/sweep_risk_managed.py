"""Full 1x to 10x leverage sweep comparing Raw 200 SMA vs Risk-Managed 200 SMA."""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.test_risk_management import run_sim

print("=" * 80)
print("LEVERAGE SWEEP 1x TO 10x: LONG-ONLY")
print("=" * 80)

print("\n--- 1. RAW 200 SMA BASELINE (LONG-ONLY) ---")
for lev in range(1, 11):
    r = run_sim(leverage=float(lev), mode="long_only", band_atr_mult=0.0, filter_type="none", sl_atr_mult=0.0)
    status = "LIQUIDATED" if r["is_liq"] else f"${r['final_eq']:12,.0f}"
    print(f"Leverage {lev:2d}x | Status: {status} | CAGR: {r['cagr']*100:6.1f}% | MaxDD: {r['max_dd']*100:5.1f}% | Trades: {r['trades']}")

print("\n--- 2. RISK-MANAGED: ATR BAND 0.5x (WHIPSAW FILTER) ---")
for lev in range(1, 11):
    r = run_sim(leverage=float(lev), mode="long_only", band_atr_mult=0.5, filter_type="none", sl_atr_mult=0.0)
    status = "LIQUIDATED" if r["is_liq"] else f"${r['final_eq']:12,.0f}"
    print(f"Leverage {lev:2d}x | Status: {status} | CAGR: {r['cagr']*100:6.1f}% | MaxDD: {r['max_dd']*100:5.1f}% | Trades: {r['trades']}")

print("\n--- 3. RISK-MANAGED: ATR BAND 0.5x + STOP-LOSS 2.5x ATR ---")
for lev in range(1, 11):
    r = run_sim(leverage=float(lev), mode="long_only", band_atr_mult=0.5, filter_type="none", sl_atr_mult=2.5)
    status = "LIQUIDATED" if r["is_liq"] else f"${r['final_eq']:12,.0f}"
    print(f"Leverage {lev:2d}x | Status: {status} | CAGR: {r['cagr']*100:6.1f}% | MaxDD: {r['max_dd']*100:5.1f}% | Trades: {r['trades']}")

print("\n--- 4. RISK-MANAGED: ATR BAND 0.5x + EMA 9 CONFIRMATION + SL 2.5x ATR ---")
for lev in range(1, 11):
    r = run_sim(leverage=float(lev), mode="long_only", band_atr_mult=0.5, filter_type="ema9_entry", sl_atr_mult=2.5)
    status = "LIQUIDATED" if r["is_liq"] else f"${r['final_eq']:12,.0f}"
    print(f"Leverage {lev:2d}x | Status: {status} | CAGR: {r['cagr']*100:6.1f}% | MaxDD: {r['max_dd']*100:5.1f}% | Trades: {r['trades']}")

print("\n" + "=" * 80)
print("LEVERAGE SWEEP 1x TO 10x: LONG-SHORT")
print("=" * 80)

print("\n--- 5. RISK-MANAGED: ATR BAND 0.5x (LONG-SHORT) ---")
for lev in range(1, 11):
    r = run_sim(leverage=float(lev), mode="long_short", band_atr_mult=0.5, filter_type="none", sl_atr_mult=0.0)
    status = "LIQUIDATED" if r["is_liq"] else f"${r['final_eq']:12,.0f}"
    print(f"Leverage {lev:2d}x | Status: {status} | CAGR: {r['cagr']*100:6.1f}% | MaxDD: {r['max_dd']*100:5.1f}% | Trades: {r['trades']}")

print("\n--- 6. RISK-MANAGED: ATR BAND 0.5x + SL 2.5x ATR (LONG-SHORT) ---")
for lev in range(1, 11):
    r = run_sim(leverage=float(lev), mode="long_short", band_atr_mult=0.5, filter_type="none", sl_atr_mult=2.5)
    status = "LIQUIDATED" if r["is_liq"] else f"${r['final_eq']:12,.0f}"
    print(f"Leverage {lev:2d}x | Status: {status} | CAGR: {r['cagr']*100:6.1f}% | MaxDD: {r['max_dd']*100:5.1f}% | Trades: {r['trades']}")

print("\n--- 7. RISK-MANAGED: ATR BAND 0.5x + EMA 9 CONFIRMATION + SL 2.5x ATR (LONG-SHORT) ---")
for lev in range(1, 11):
    r = run_sim(leverage=float(lev), mode="long_short", band_atr_mult=0.5, filter_type="ema9_entry", sl_atr_mult=2.5)
    status = "LIQUIDATED" if r["is_liq"] else f"${r['final_eq']:12,.0f}"
    print(f"Leverage {lev:2d}x | Status: {status} | CAGR: {r['cagr']*100:6.1f}% | MaxDD: {r['max_dd']*100:5.1f}% | Trades: {r['trades']}")
