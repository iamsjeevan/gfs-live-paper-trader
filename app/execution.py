"""Execution Engine for Simulated Live Paper Trading.

Simulates:
1. Next-day Market Open long entries with realistic configurable slippage (default 25 bps).
2. -3.0% Initial Stop-loss with gap-down execution realism (if open < stop, fills at open).
3. Lower circuit block detection (EXIT_BLOCKED_LOWER_CIRCUIT).
4. +5.0% Trailing Activation regime tracking.
5. Completed daily Close < Daily EMA21 trailing exits executed at next-day open with slippage.
"""

import sqlite3
import logging
from typing import Dict, List, Optional, Tuple
import pandas as pd

from app.config import CONFIG, DEFAULT_DB_PATH
from app.db import get_db_connection

logger = logging.getLogger("paper_trading.execution")

class PaperExecutionEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH

    def simulate_entries(self, execution_date: str, accepted_orders: List[Dict], capital_tier: float = 1_000_000.0) -> List[Dict]:
        """Execute simulated entries at Day T+1 Market Open with slippage."""
        if not accepted_orders:
            return []

        conn = get_db_connection(self.db_path)
        cur = conn.cursor()

        slippage_mult = 1.0 + (CONFIG.SLIPPAGE_BPS_ENTRY / 10000.0)
        filled_positions = []

        symbols = [o["symbol"] for o in accepted_orders]
        placeholders = ",".join(["?"] * len(symbols))

        today_bars = pd.read_sql(
            f"SELECT symbol, date, open, high, low, close, volume FROM daily_prices WHERE date = ? AND symbol IN ({placeholders});",
            conn,
            params=[execution_date] + symbols
        )
        bars_by_sym = {row["symbol"]: row for _, row in today_bars.iterrows()}

        with conn:
            for order in accepted_orders:
                sym = order["symbol"]
                bar = bars_by_sym.get(sym)
                if bar is None:
                    logger.warning(f"No market open price available for {sym} on {execution_date}. Order deferred.")
                    continue

                raw_open = float(bar["open"])
                simulated_open = raw_open * slippage_mult
                allocated_rs = float(order.get("allocation", 0.0))
                
                if allocated_rs < 100.0:
                    continue

                shares = allocated_rs / simulated_open
                initial_stop = simulated_open * (1.0 - CONFIG.INITIAL_STOP_LOSS_PCT)
                plus_5_thresh = simulated_open * (1.0 + CONFIG.TRAILING_ACTIVATION_PCT)

                # Record in orders table
                cur.execute("""
                INSERT INTO orders (
                    signal_id, symbol, order_date, order_type, side, status,
                    raw_price, simulated_price, shares, order_value, slippage_bps, capital_tier
                ) VALUES (?, ?, ?, 'SIMULATED_LIMIT_OPEN', 'BUY', 'FILLED', ?, ?, ?, ?, ?, ?);
                """, (
                    order.get("signal_id"), sym, execution_date, raw_open, simulated_open,
                    shares, allocated_rs, CONFIG.SLIPPAGE_BPS_ENTRY, capital_tier
                ))

                # Insert into positions table
                cur.execute("""
                INSERT INTO positions (
                    capital_tier, symbol, entry_date, entry_price, simulated_entry_price,
                    shares, allocated_capital, initial_stop, plus_5_threshold,
                    plus_5_reached, highest_price, status, current_price, holding_days
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'OPEN', ?, 1);
                """, (
                    capital_tier, sym, execution_date, raw_open, simulated_open,
                    shares, allocated_rs, initial_stop, plus_5_thresh,
                    raw_open, raw_open
                ))
                pos_id = cur.lastrowid

                filled_positions.append({
                    "position_id": pos_id,
                    "symbol": sym,
                    "entry_date": execution_date,
                    "raw_open": raw_open,
                    "simulated_open": simulated_open,
                    "shares": shares,
                    "allocated_capital": allocated_rs,
                    "initial_stop": initial_stop,
                    "plus_5_threshold": plus_5_thresh
                })

        conn.close()
        logger.info(f"Simulated {len(filled_positions)} new entries on {execution_date}.")
        return filled_positions

    def process_position_management_and_exits(
        self,
        current_date: str,
        capital_tier: float = 1_000_000.0
    ) -> Tuple[List[Dict], List[Dict]]:
        """Manage active open positions: check +5% activation, initial stop hits (with gap checks), and EMA21 exits.
        
        Returns:
            (closed_trades, updated_open_positions)
        """
        conn = get_db_connection(self.db_path)
        cur = conn.cursor()

        open_positions = cur.execute(
            "SELECT * FROM positions WHERE capital_tier = ? AND status IN ('OPEN', 'EXIT_PENDING', 'EXIT_BLOCKED_LOWER_CIRCUIT');",
            (capital_tier,)
        ).fetchall()

        if not open_positions:
            conn.close()
            return [], []

        symbols = [p["symbol"] for p in open_positions]
        placeholders = ",".join(["?"] * len(symbols))

        today_bars = pd.read_sql(
            f"SELECT symbol, date, open, high, low, close, volume, ema21 FROM daily_prices WHERE date = ? AND symbol IN ({placeholders});",
            conn,
            params=[current_date] + symbols
        )
        bars_by_sym = {row["symbol"]: row for _, row in today_bars.iterrows()}

        closed_trades = []
        updated_open_positions = []
        cost_mult_exit = 1.0 - (CONFIG.SLIPPAGE_BPS_EXIT / 10000.0)

        with conn:
            for pos in open_positions:
                pos_id = pos["position_id"]
                sym = pos["symbol"]
                bar = bars_by_sym.get(sym)

                if bar is None:
                    # Missing bar on current date
                    updated_open_positions.append(dict(pos))
                    continue

                o_p = float(bar["open"])
                h_p = float(bar["high"])
                l_p = float(bar["low"])
                c_p = float(bar["close"])
                ema_val = float(bar["ema21"]) if pd.notna(bar["ema21"]) else 0.0

                entry_p = float(pos["simulated_entry_price"])
                shares = float(pos["shares"])
                alloc_cap = float(pos["allocated_capital"])
                initial_stop = float(pos["initial_stop"])
                plus_5_thresh = float(pos["plus_5_threshold"])
                plus_5_reached = bool(pos["plus_5_reached"])
                holding_days = int(pos["holding_days"]) + 1
                highest_price = max(float(pos["highest_price"] or entry_p), h_p)

                # Check if position had an exit pending from previous session (EMA21 exit)
                if pos["status"] == "EXIT_PENDING":
                    # Check for lower circuit freeze: Open == Low == High == Close and negative return
                    is_lower_circuit = (h_p == l_p == c_p) and (c_p < entry_p * 0.95)
                    if is_lower_circuit:
                        cur.execute(
                            "UPDATE positions SET status = 'EXIT_BLOCKED_LOWER_CIRCUIT', current_price = ? WHERE position_id = ?;",
                            (c_p, pos_id)
                        )
                        logger.warning(f"{sym} exit blocked due to lower circuit lock on {current_date}.")
                        continue

                    raw_exit_p = o_p
                    sim_exit_p = raw_exit_p * cost_mult_exit
                    ret_pct = (sim_exit_p - entry_p) / entry_p * 100.0
                    pnl_rs = shares * (sim_exit_p - entry_p)
                    exit_cost = shares * raw_exit_p * (CONFIG.SLIPPAGE_BPS_EXIT / 10000.0)
                    entry_cost = alloc_cap * (CONFIG.SLIPPAGE_BPS_ENTRY / 10000.0)
                    total_friction = entry_cost + exit_cost

                    # Close trade
                    cur.execute("""
                    INSERT INTO closed_trades (
                        capital_tier, symbol, entry_date, exit_date, entry_price, exit_price,
                        shares, return_pct, pnl_rs, holding_days, exit_reason,
                        entry_friction_rs, exit_friction_rs, total_friction_rs, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'EMA21_TRAILING_EXIT', ?, ?, ?, 'Next-open exit after daily close below EMA21');
                    """, (
                        capital_tier, sym, pos["entry_date"], current_date, entry_p, sim_exit_p,
                        shares, ret_pct, pnl_rs, holding_days, entry_cost, exit_cost, total_friction
                    ))
                    cur.execute("UPDATE positions SET status = 'CLOSED' WHERE position_id = ?;", (pos_id,))

                    closed_trades.append({
                        "symbol": sym,
                        "exit_date": current_date,
                        "exit_price": sim_exit_p,
                        "return_pct": ret_pct,
                        "pnl_rs": pnl_rs,
                        "reason": "EMA21_TRAILING_EXIT"
                    })
                    continue

                # 1. Stop-Loss Verification (Only active if +5% trailing NOT activated)
                if not plus_5_reached:
                    if l_p <= initial_stop:
                        # Check gap-down open
                        raw_exit_p = min(o_p, initial_stop)
                        sim_exit_p = raw_exit_p * cost_mult_exit
                        ret_pct = (sim_exit_p - entry_p) / entry_p * 100.0
                        pnl_rs = shares * (sim_exit_p - entry_p)
                        exit_cost = shares * raw_exit_p * (CONFIG.SLIPPAGE_BPS_EXIT / 10000.0)
                        entry_cost = alloc_cap * (CONFIG.SLIPPAGE_BPS_ENTRY / 10000.0)
                        total_friction = entry_cost + exit_cost

                        exit_reason = "STOP_GAP_DOWN" if o_p < initial_stop else "INITIAL_STOP_LOSS"

                        cur.execute("""
                        INSERT INTO closed_trades (
                            capital_tier, symbol, entry_date, exit_date, entry_price, exit_price,
                            shares, return_pct, pnl_rs, holding_days, exit_reason,
                            entry_friction_rs, exit_friction_rs, total_friction_rs, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (
                            capital_tier, sym, pos["entry_date"], current_date, entry_p, sim_exit_p,
                            shares, ret_pct, pnl_rs, holding_days, exit_reason,
                            entry_cost, exit_cost, total_friction,
                            f"Stop triggered. Low: {l_p:.2f}, Stop: {initial_stop:.2f}"
                        ))
                        cur.execute("UPDATE positions SET status = 'CLOSED' WHERE position_id = ?;", (pos_id,))

                        closed_trades.append({
                            "symbol": sym,
                            "exit_date": current_date,
                            "exit_price": sim_exit_p,
                            "return_pct": ret_pct,
                            "pnl_rs": pnl_rs,
                            "reason": exit_reason
                        })
                        continue

                    # Check +5% Activation threshold
                    if h_p >= plus_5_thresh:
                        plus_5_reached = True
                        cur.execute("""
                        UPDATE positions SET plus_5_reached = 1, plus_5_date = ?, highest_price = ?
                        WHERE position_id = ?;
                        """, (current_date, highest_price, pos_id))
                        logger.info(f"+5% Trailing activated for {sym} on {current_date} (High: {h_p:.2f} >= {plus_5_thresh:.2f}).")

                # 2. Trailing Regime: Check for Daily Close < EMA21
                if plus_5_reached:
                    if c_p < ema_val:
                        cur.execute(
                            "UPDATE positions SET status = 'EXIT_PENDING', highest_price = ?, current_price = ? WHERE position_id = ?;",
                            (highest_price, c_p, pos_id)
                        )
                        logger.info(f"{sym} Daily Close {c_p:.2f} < EMA21 {ema_val:.2f}. Exit scheduled for next Open.")
                        continue

                # Position remains open: update mark-to-market metrics
                unrealized_pnl = shares * (c_p - entry_p)
                unrealized_ret = (c_p - entry_p) / entry_p * 100.0
                cur.execute("""
                UPDATE positions SET
                    highest_price = ?,
                    current_price = ?,
                    unrealized_pnl = ?,
                    unrealized_return_pct = ?,
                    holding_days = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE position_id = ?;
                """, (highest_price, c_p, unrealized_pnl, unrealized_ret, holding_days, pos_id))

                pos_dict = dict(pos)
                pos_dict["current_price"] = c_p
                pos_dict["unrealized_pnl"] = unrealized_pnl
                pos_dict["unrealized_return_pct"] = unrealized_ret
                pos_dict["highest_price"] = highest_price
                updated_open_positions.append(pos_dict)

        conn.commit()
        conn.close()
        return closed_trades, updated_open_positions
