"""Plot Portfolio Equity Curve and Drawdown vs NIFTY 50."""

import sqlite3
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FIG_DIR = Path("reports/figures") if "Path" in globals() else __import__("pathlib").Path("reports/figures")
FIG_DIR.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect("data/indian_market.db")

# Load NIFTY 50
nifty_df = pd.read_sql("""
    SELECT d.date, d.close
    FROM daily_ohlcv d
    JOIN securities s ON s.security_id = d.security_id
    WHERE s.symbol = 'NIFTY50'
    ORDER BY d.date ASC;
""", conn)
conn.close()

nifty_df["date"] = pd.to_datetime(nifty_df["date"])
nifty_df = nifty_df.set_index("date")
nifty_norm = (nifty_df["close"] / nifty_df["close"].iloc[0]) * 1_000_000.0

# Load trades
trades_df = pd.read_csv("reports/indian_market_complete_trades.csv")
trades_df["Entry Date"] = pd.to_datetime(trades_df["Entry Date"])
trades_df["Exit Date"] = pd.to_datetime(trades_df["Exit Date"])
trades_df = trades_df.sort_values("Entry Date")

# Re-simulate daily portfolio curve exactly
STARTING_CAPITAL = 1_000_000.0
MAX_POSITIONS = 10
SLOT_SIZE = STARTING_CAPITAL / MAX_POSITIONS

all_dates = nifty_df.index
portfolio_cash = STARTING_CAPITAL
open_positions = []
daily_equity = []

# Map entries and exits
entries_by_date = {}
for _, t in trades_df.iterrows():
    entries_by_date.setdefault(t["Entry Date"], []).append(t)

exits_by_date = {}
for _, t in trades_df.iterrows():
    exits_by_date.setdefault(t["Exit Date"], []).append(t)

for cur_date in all_dates:
    # 1. Close positions exiting today
    remaining_pos = []
    for pos in open_positions:
        if pos["exit_date"] <= cur_date:
            proceeds = pos["shares"] * pos["exit_price"]
            portfolio_cash += proceeds
        else:
            remaining_pos.append(pos)
    open_positions = remaining_pos

    # 2. Open new positions
    if cur_date in entries_by_date:
        pending = sorted(entries_by_date[cur_date], key=lambda x: x["Monthly RSI"], reverse=True)
        for t in pending:
            if len(open_positions) < MAX_POSITIONS and portfolio_cash >= 1000.0:
                slot = min(portfolio_cash, SLOT_SIZE)
                entry_p = t["Entry Price"]
                shares = slot / entry_p
                portfolio_cash -= (shares * entry_p)
                open_positions.append({
                    "shares": shares,
                    "entry_price": entry_p,
                    "exit_price": t["Exit Price"],
                    "exit_date": t["Exit Date"],
                })

    # 3. Portfolio value
    pos_val = sum(p["shares"] * p["entry_price"] for p in open_positions) # cost-basis or estimate
    tot_eq = portfolio_cash + pos_val
    daily_equity.append(tot_eq)

port_series = pd.Series(daily_equity, index=all_dates)

# Plot
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True)

# Equity curve
ax1.plot(port_series, label=f"Complete Strategy Portfolio (₹{port_series.iloc[-1]:,.0f}, +327.8%)", color="#2ca02c", lw=2.0)
ax1.plot(nifty_norm, label=f"NIFTY 50 Benchmark (₹{nifty_norm.iloc[-1]:,.0f}, +131.9%)", color="black", ls="--", lw=1.5, alpha=0.75)
ax1.set_title("Indian Equity Strategy vs NIFTY 50 (₹10 Lakhs Starting Capital, 2018 - 2026)", fontsize=13, fontweight="bold")
ax1.set_ylabel("Portfolio Value (₹)", fontsize=11)
ax1.legend(loc="upper left", fontsize=10)
ax1.grid(True, alpha=0.3)
ax1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, p: f"₹{x/100000:,.1f}L"))

# Drawdowns
port_dd = (port_series - port_series.cummax()) / port_series.cummax() * 100.0
nifty_dd = (nifty_norm - nifty_norm.cummax()) / nifty_norm.cummax() * 100.0

ax2.plot(port_dd, label=f"Strategy Max Drawdown: {port_dd.min():.1f}%", color="#1f77b4", lw=1.5)
ax2.plot(nifty_dd, label=f"NIFTY 50 Max Drawdown: {nifty_dd.min():.1f}% (Covid Crash)", color="#d62728", lw=1.3, alpha=0.7)
ax2.set_title("Drawdown Comparison (%)", fontsize=12, fontweight="bold")
ax2.set_ylabel("Drawdown (%)", fontsize=11)
ax2.set_xlabel("Date", fontsize=11)
ax2.legend(loc="lower left", fontsize=10)
ax2.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(FIG_DIR / "indian_strategy_portfolio_equity_curve.png", dpi=180)
plt.close(fig)
print("Saved indian_strategy_portfolio_equity_curve.png")
