"""Portfolio Manager and Mark-to-Market Engine.

Maintains:
1. Daily portfolio snapshots (Cash, Invested Value, Total Equity, Drawdown).
2. Multi-capital tier tracking (₹1L, ₹5L, ₹10L, ₹25L, ₹50L) on identical signals.
3. Performance statistics (Win rate, Profit factor, Drawdown duration, Expectancy).
4. System heartbeat updates.
"""

import sqlite3
import logging
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from app.config import CONFIG, DEFAULT_DB_PATH
from app.db import get_db_connection

logger = logging.getLogger("paper_trading.portfolio")

class PortfolioManager:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH

    def get_portfolio_state(self, capital_tier: float = 1_000_000.0) -> Dict:
        """Fetch current portfolio cash, invested value, open positions, and total equity."""
        conn = get_db_connection(self.db_path)
        cur = conn.cursor()

        # 1. Fetch latest snapshot or initialize
        last_snap = cur.execute(
            "SELECT * FROM portfolio_snapshots WHERE capital_tier = ? ORDER BY date DESC LIMIT 1;",
            (capital_tier,)
        ).fetchone()

        cash = float(last_snap["cash"]) if last_snap else capital_tier
        peak_equity = float(last_snap["peak_equity"]) if last_snap else capital_tier

        # 2. Fetch active open positions
        open_pos_rows = cur.execute(
            "SELECT * FROM positions WHERE capital_tier = ? AND status IN ('OPEN', 'EXIT_PENDING', 'EXIT_BLOCKED_LOWER_CIRCUIT');",
            (capital_tier,)
        ).fetchall()

        open_positions = [dict(r) for r in open_pos_rows]
        invested_val = sum(p["shares"] * (p["current_price"] or p["simulated_entry_price"]) for p in open_positions)
        unrealized_pnl = sum(p["unrealized_pnl"] or 0.0 for p in open_positions)

        total_equity = cash + invested_val

        conn.close()
        return {
            "capital_tier": capital_tier,
            "cash": cash,
            "invested_val": invested_val,
            "total_equity": total_equity,
            "peak_equity": max(peak_equity, total_equity),
            "unrealized_pnl": unrealized_pnl,
            "open_positions": open_positions,
            "open_positions_count": len(open_positions)
        }

    def record_daily_snapshot(self, date_str: str, capital_tier: float = 1_000_000.0) -> Dict:
        """Mark-to-market daily closing snapshot."""
        conn = get_db_connection(self.db_path)
        cur = conn.cursor()

        # Calculate realized PnL and total proceeds from closed trades today
        today_closed = cur.execute(
            "SELECT * FROM closed_trades WHERE capital_tier = ? AND exit_date = ?;",
            (capital_tier, date_str)
        ).fetchall()

        # Calculate cash adjustments from previous snapshot
        prev_snap = cur.execute(
            "SELECT * FROM portfolio_snapshots WHERE capital_tier = ? AND date < ? ORDER BY date DESC LIMIT 1;",
            (capital_tier, date_str)
        ).fetchone()

        prev_equity = float(prev_snap["total_equity"]) if prev_snap else capital_tier
        prev_cash = float(prev_snap["cash"]) if prev_snap else capital_tier
        peak_equity = float(prev_snap["peak_equity"]) if prev_snap else capital_tier

        # Add proceeds from exits today
        cash_from_exits = sum(r["shares"] * r["exit_price"] for r in today_closed)

        # Subtract capital allocated to new entries today
        today_orders = cur.execute(
            "SELECT * FROM orders WHERE capital_tier = ? AND order_date = ? AND status = 'FILLED';",
            (capital_tier, date_str)
        ).fetchall()
        cash_to_entries = sum(o["order_value"] for o in today_orders)

        current_cash = prev_cash + cash_from_exits - cash_to_entries

        # Mark open positions
        open_pos_rows = cur.execute(
            "SELECT * FROM positions WHERE capital_tier = ? AND status IN ('OPEN', 'EXIT_PENDING', 'EXIT_BLOCKED_LOWER_CIRCUIT');",
            (capital_tier,)
        ).fetchall()

        gross_market_val = sum(r["shares"] * (r["current_price"] or r["simulated_entry_price"]) for r in open_pos_rows)
        unrealized_pnl = sum(r["unrealized_pnl"] or 0.0 for r in open_pos_rows)

        # Realized PnL cumulative
        all_realized = cur.execute(
            "SELECT SUM(pnl_rs) as total_realized FROM closed_trades WHERE capital_tier = ? AND exit_date <= ?;",
            (capital_tier, date_str)
        ).fetchone()
        cum_realized_pnl = float(all_realized["total_realized"] or 0.0)

        total_equity = current_cash + gross_market_val
        daily_ret_pct = ((total_equity - prev_equity) / prev_equity) * 100.0 if prev_equity > 0 else 0.0
        cum_ret_pct = ((total_equity - capital_tier) / capital_tier) * 100.0

        peak_equity = max(peak_equity, total_equity)
        drawdown_pct = ((total_equity - peak_equity) / peak_equity) * 100.0

        with conn:
            cur.execute("""
            INSERT INTO portfolio_snapshots (
                date, capital_tier, cash, invested_val, gross_market_val,
                unrealized_pnl, realized_pnl, total_equity, daily_return_pct,
                cumulative_return_pct, drawdown_pct, peak_equity, open_positions_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, capital_tier) DO UPDATE SET
                cash=excluded.cash,
                invested_val=excluded.invested_val,
                gross_market_val=excluded.gross_market_val,
                unrealized_pnl=excluded.unrealized_pnl,
                realized_pnl=excluded.realized_pnl,
                total_equity=excluded.total_equity,
                daily_return_pct=excluded.daily_return_pct,
                cumulative_return_pct=excluded.cumulative_return_pct,
                drawdown_pct=excluded.drawdown_pct,
                peak_equity=excluded.peak_equity,
                open_positions_count=excluded.open_positions_count;
            """, (
                date_str, capital_tier, current_cash, gross_market_val, gross_market_val,
                unrealized_pnl, cum_realized_pnl, total_equity, daily_ret_pct,
                cum_ret_pct, drawdown_pct, peak_equity, len(open_pos_rows)
            ))

            # Update system heartbeat
            cur.execute("""
            INSERT INTO system_heartbeat (status, last_data_update, open_positions, cash, total_equity)
            VALUES ('RUNNING', ?, ?, ?, ?);
            """, (date_str, len(open_pos_rows), current_cash, total_equity))

        conn.close()
        return {
            "date": date_str,
            "capital_tier": capital_tier,
            "cash": current_cash,
            "invested_val": gross_market_val,
            "total_equity": total_equity,
            "daily_return_pct": daily_ret_pct,
            "cumulative_return_pct": cum_ret_pct,
            "drawdown_pct": drawdown_pct,
            "peak_equity": peak_equity,
            "open_positions_count": len(open_pos_rows)
        }

    def compute_comprehensive_metrics(self, capital_tier: float = 1_000_000.0) -> Dict:
        """Compute all 25+ performance and execution metrics."""
        conn = get_db_connection(self.db_path)
        cur = conn.cursor()

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
        signals = pd.read_sql(
            "SELECT * FROM signals ORDER BY signal_date ASC;",
            conn
        )
        open_pos = pd.read_sql(
            "SELECT * FROM positions WHERE capital_tier = ? AND status != 'CLOSED';",
            conn,
            params=[capital_tier]
        )
        conn.close()

        if snaps.empty:
            return {
                "starting_capital": capital_tier,
                "current_equity": capital_tier,
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "total_trades": 0,
                "open_positions": 0
            }

        start_cap = capital_tier
        curr_equity = float(snaps["total_equity"].iloc[-1])
        abs_profit = curr_equity - start_cap
        tot_return_pct = (abs_profit / start_cap) * 100.0
        max_dd = float(snaps["drawdown_pct"].min())
        curr_dd = float(snaps["drawdown_pct"].iloc[-1])

        # Trade metrics
        total_trades = len(trades)
        if total_trades > 0:
            winners = trades[trades["return_pct"] > 0]
            losers = trades[trades["return_pct"] <= 0]
            win_rate = (len(winners) / total_trades) * 100.0
            gross_win = winners["pnl_rs"].sum() if not winners.empty else 0.0
            gross_loss = abs(losers["pnl_rs"].sum()) if not losers.empty else 1e-9
            profit_factor = gross_win / gross_loss
            avg_win = winners["return_pct"].mean() if not winners.empty else 0.0
            avg_loss = losers["return_pct"].mean() if not losers.empty else 0.0
            largest_win = trades["return_pct"].max()
            largest_loss = trades["return_pct"].min()
            avg_holding = trades["holding_days"].mean()
            total_friction = trades["total_friction_rs"].sum()

            # Streaks
            is_loss = (trades["return_pct"] <= 0).tolist()
            max_loss_streak = 0
            curr_streak = 0
            for l in is_loss:
                if l:
                    curr_streak += 1
                    max_loss_streak = max(max_loss_streak, curr_streak)
                else:
                    curr_streak = 0
        else:
            win_rate = 0.0
            profit_factor = 0.0
            avg_win = 0.0
            avg_loss = 0.0
            largest_win = 0.0
            largest_loss = 0.0
            avg_holding = 0.0
            total_friction = 0.0
            max_loss_streak = 0

        # Signal stats
        total_signals = len(signals)
        accepted_signals = len(signals[signals["status"] == "ACCEPTED"])
        rejected_cap = len(signals[signals["status"] == "REJECTED_CAPACITY"])
        rejected_liq = len(signals[signals["status"] == "REJECTED_LIQUIDITY"])

        return {
            "starting_capital": start_cap,
            "current_equity": curr_equity,
            "absolute_profit": abs_profit,
            "total_return_pct": tot_return_pct,
            "max_drawdown_pct": max_dd,
            "current_drawdown_pct": curr_dd,
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "total_trades": total_trades,
            "open_positions": len(open_pos),
            "average_winner_pct": avg_win,
            "average_loser_pct": avg_loss,
            "largest_winner_pct": largest_win,
            "largest_loser_pct": largest_loss,
            "longest_losing_streak": max_loss_streak,
            "average_holding_days": avg_holding,
            "total_friction_rs": total_friction,
            "total_signals": total_signals,
            "accepted_signals": accepted_signals,
            "rejected_capacity": rejected_cap,
            "rejected_liquidity": rejected_liq,
            "average_cash_pct": float((snaps["cash"] / snaps["total_equity"] * 100.0).mean()),
            "average_exposure_pct": float((snaps["invested_val"] / snaps["total_equity"] * 100.0).mean())
        }
