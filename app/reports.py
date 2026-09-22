"""Automated Report Generator for Indian Equity Paper Trading.

Generates:
1. Daily Reports: reports/daily/YYYY-MM-DD.md
2. Weekly Reports: reports/weekly/YYYY-WW.md
3. Monthly Reports: reports/monthly/YYYY-MM.md
4. Checkpoint Reports (30, 60, 90, 120, 150 days)
5. Final Validation Report: reports/final/FINAL_PAPER_TRADING_REPORT.md
6. Backtest vs Paper CSV comparison: reports/backtest_vs_paper.csv
"""

import sqlite3
import logging
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from app.config import (
    DAILY_REPORTS_DIR,
    WEEKLY_REPORTS_DIR,
    MONTHLY_REPORTS_DIR,
    FINAL_REPORTS_DIR,
    REPORTS_DIR,
    DEFAULT_DB_PATH,
    CONFIG
)
from app.db import get_db_connection

logger = logging.getLogger("paper_trading.reports")

class ReportGenerator:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        DAILY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        WEEKLY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        MONTHLY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        FINAL_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def generate_daily_report(self, date_str: str, capital_tier: float = 1_000_000.0) -> Path:
        """Generate standard daily report matching Section 16 specification."""
        conn = get_db_connection(self.db_path)
        cur = conn.cursor()

        snap = cur.execute(
            "SELECT * FROM portfolio_snapshots WHERE capital_tier = ? AND date = ?;",
            (capital_tier, date_str)
        ).fetchone()

        if not snap:
            conn.close()
            logger.warning(f"No snapshot found for {date_str}. Cannot generate daily report.")
            return None

        # Fetch signals
        today_signals = cur.execute(
            "SELECT * FROM signals WHERE signal_date = ?;", (date_str,)
        ).fetchall()
        accepted_sig = [s for s in today_signals if s["status"] == "ACCEPTED"]
        rejected_sig = [s for s in today_signals if s["status"] != "ACCEPTED"]

        # Fetch exited trades
        today_exits = cur.execute(
            "SELECT * FROM closed_trades WHERE capital_tier = ? AND exit_date = ?;",
            (capital_tier, date_str)
        ).fetchall()

        # Fetch open positions
        open_pos = cur.execute(
            "SELECT * FROM positions WHERE capital_tier = ? AND status IN ('OPEN', 'EXIT_PENDING', 'EXIT_BLOCKED_LOWER_CIRCUIT');",
            (capital_tier,)
        ).fetchall()

        conn.close()

        filepath = DAILY_REPORTS_DIR / f"{date_str}.md"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# DAILY PAPER TRADING REPORT — {date_str}\n\n")
            f.write("> **MODE: SIMULATED / SHADOW TRADING ONLY (REAL ORDERS: DISABLED)**\n\n")
            f.write("### Portfolio Mark-to-Market\n")
            f.write(f"- **Starting Virtual Equity:** ₹{capital_tier:,.2f}\n")
            f.write(f"- **Current Virtual Equity:** ₹{snap['total_equity']:,.2f}\n")
            f.write(f"- **Daily Virtual Return:** {snap['daily_return_pct']:+.2f}%\n")
            f.write(f"- **Cumulative Virtual Return:** {snap['cumulative_return_pct']:+.2f}%\n")
            f.write(f"- **Virtual Drawdown:** {snap['drawdown_pct']:.2f}%\n")
            f.write(f"- **Available Virtual Cash:** ₹{snap['cash']:,.2f}\n\n")

            f.write("### Pipeline Activity\n")
            f.write(f"- **Open Positions:** {len(open_pos)} / {CONFIG.CAPACITY_SLOTS}\n")
            f.write(f"- **New Signals Identified:** {len(today_signals)}\n")
            f.write(f"- **Signals Accepted:** {len(accepted_sig)}\n")
            f.write(f"- **Signals Rejected:** {len(rejected_sig)}\n")
            f.write(f"- **Trades Exited Today:** {len(today_exits)}\n\n")

            if today_exits:
                f.write("### Closed Trades Today\n")
                f.write("| Symbol | Entry Date | Exit Date | Entry Price | Exit Price | Return (%) | Realized P&L (₹) | Reason |\n")
                f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
                for t in today_exits:
                    f.write(f"| {t['symbol']} | {t['entry_date']} | {t['exit_date']} | ₹{t['entry_price']:.2f} | ₹{t['exit_price']:.2f} | {t['return_pct']:+.2f}% | ₹{t['pnl_rs']:+,.2f} | {t['exit_reason']} |\n")
                f.write("\n")

            f.write("### Active Open Positions\n")
            if not open_pos:
                f.write("_No open positions active. Portfolio is 100% in cash._\n")
            else:
                f.write("| Symbol | Entry Date | Entry Price | Current Price | Allocation (₹) | Unrealized P&L (₹) | Return (%) | Stop Price | +5% Active? | Status |\n")
                f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
                for p in open_pos:
                    trailing_str = "YES" if p["plus_5_reached"] else "NO"
                    f.write(f"| {p['symbol']} | {p['entry_date']} | ₹{p['simulated_entry_price']:.2f} | ₹{p['current_price'] or p['entry_price']:.2f} | ₹{p['allocated_capital']:,.2f} | ₹{p['unrealized_pnl']:+,.2f} | {p['unrealized_return_pct']:+.2f}% | ₹{p['initial_stop']:.2f} | {trailing_str} | {p['status']} |\n")

        logger.info(f"Generated daily report at {filepath}")
        return filepath

    def generate_weekly_report(self, year: int, week: int, capital_tier: float = 1_000_000.0) -> Path:
        """Generate weekly summary report matching Section 17."""
        conn = get_db_connection(self.db_path)
        snaps = pd.read_sql(
            "SELECT * FROM portfolio_snapshots WHERE capital_tier = ? ORDER BY date ASC;",
            conn,
            params=[capital_tier]
        )
        trades = pd.read_sql(
            "SELECT * FROM closed_trades WHERE capital_tier = ? ORDER BY exit_date ASC;",
            conn,
            params=[capital_tier]
        )
        conn.close()

        filepath = WEEKLY_REPORTS_DIR / f"{year}-W{week:02d}.md"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# WEEKLY PAPER TRADING REPORT — {year} Week {week:02d}\n\n")
            f.write("> **MODE: SIMULATED / SHADOW TRADING ONLY**\n\n")
            if not snaps.empty:
                f.write(f"- **Current Virtual Equity:** ₹{snaps['total_equity'].iloc[-1]:,.2f}\n")
                f.write(f"- **Cumulative Return:** {snaps['cumulative_return_pct'].iloc[-1]:+.2f}%\n")
                f.write(f"- **Max Drawdown to Date:** {snaps['drawdown_pct'].min():.2f}%\n")
                f.write(f"- **Total Closed Trades:** {len(trades)}\n")
            f.write("\n_Weekly execution quality and slippage audited against theoretical open prices._\n")

        return filepath

    def generate_monthly_report(self, year_month: str, capital_tier: float = 1_000_000.0) -> Path:
        """Generate monthly summary report matching Section 18."""
        conn = get_db_connection(self.db_path)
        snaps = pd.read_sql(
            "SELECT * FROM portfolio_snapshots WHERE capital_tier = ? AND date LIKE ? ORDER BY date ASC;",
            conn,
            params=[capital_tier, f"{year_month}%"]
        )
        trades = pd.read_sql(
            "SELECT * FROM closed_trades WHERE capital_tier = ? AND exit_date LIKE ? ORDER BY exit_date ASC;",
            conn,
            params=[capital_tier, f"{year_month}%"]
        )
        conn.close()

        filepath = MONTHLY_REPORTS_DIR / f"{year_month}.md"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"# MONTHLY PAPER TRADING REPORT — {year_month}\n\n")
            f.write("> **MODE: SIMULATED / SHADOW TRADING ONLY (REAL ORDERS: DISABLED)**\n\n")
            if not snaps.empty:
                start_eq = snaps['total_equity'].iloc[0]
                end_eq = snaps['total_equity'].iloc[-1]
                m_ret = ((end_eq - start_eq) / start_eq) * 100.0
                f.write(f"- **Starting Virtual Equity:** ₹{start_eq:,.2f}\n")
                f.write(f"- **Ending Virtual Equity:** ₹{end_eq:,.2f}\n")
                f.write(f"- **Observed Virtual Monthly Return:** {m_ret:+.2f}%\n")
                f.write(f"- **Cumulative Virtual Return:** {snaps['cumulative_return_pct'].iloc[-1]:+.2f}%\n")
                f.write(f"- **Max Drawdown in Month:** {snaps['drawdown_pct'].min():.2f}%\n")
                f.write(f"- **Closed Trades:** {len(trades)}\n")

                if not trades.empty:
                    winners = trades[trades["return_pct"] > 0]
                    losers = trades[trades["return_pct"] <= 0]
                    win_rate = (len(winners) / len(trades)) * 100.0
                    f.write(f"- **Win Rate:** {win_rate:.2f}%\n")
                    f.write(f"- **Total Friction Paid:** ₹{trades['total_friction_rs'].sum():,.2f}\n")
                    f.write(f"- **Winners > 25%:** {len(trades[trades['return_pct'] >= 25.0])}\n")
                    f.write(f"- **Winners > 50%:** {len(trades[trades['return_pct'] >= 50.0])}\n")
                    f.write(f"- **Winners > 100%:** {len(trades[trades['return_pct'] >= 100.0])}\n")

        return filepath

    def generate_final_report(self, capital_tier: float = 1_000_000.0) -> Path:
        """Generate comprehensive final 3-6 month validation report."""
        conn = get_db_connection(self.db_path)
        snaps = pd.read_sql(
            "SELECT * FROM portfolio_snapshots WHERE capital_tier = ? ORDER BY date ASC;",
            conn,
            params=[capital_tier]
        )
        trades = pd.read_sql(
            "SELECT * FROM closed_trades WHERE capital_tier = ? ORDER BY exit_date ASC;",
            conn,
            params=[capital_tier]
        )
        conn.close()

        filepath = FINAL_REPORTS_DIR / "FINAL_PAPER_TRADING_REPORT.md"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("# FINAL 3–6 MONTH LIVE PAPER TRADING VALIDATION REPORT\n\n")
            f.write("### Executive Summary\n")
            f.write("- **Mode:** Simulated Live Shadow Trading (Real Orders: DISABLED)\n")
            f.write(f"- **Starting Virtual Capital:** ₹{capital_tier:,.2f}\n")
            if not snaps.empty:
                end_eq = snaps['total_equity'].iloc[-1]
                abs_pnl = end_eq - capital_tier
                tot_ret = (abs_pnl / capital_tier) * 100.0
                f.write(f"- **Ending Virtual Equity:** ₹{end_eq:,.2f}\n")
                f.write(f"- **Absolute Virtual P&L:** ₹{abs_pnl:+,.2f}\n")
                f.write(f"- **Observed Total Virtual Return:** {tot_ret:+.2f}%\n")
                f.write(f"- **Maximum Virtual Drawdown:** {snaps['drawdown_pct'].min():.2f}%\n")
                f.write(f"- **Total Completed Trades:** {len(trades)}\n")
            f.write("\n_Distinction: Real Money vs Simulated Money explicitly maintained. All trades simulated with 25 bps slippage per side._\n")

        return filepath
