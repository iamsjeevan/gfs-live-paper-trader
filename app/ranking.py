"""Model C Relative Volume Ranking and Capital Allocation Engine.

Implements:
1. Deterministic sorting by Relative Volume descending.
2. 20-Day Average Turnover filter (>= ₹50 Lakhs / day).
3. Capacity enforcement (Max 15 simultaneous positions).
4. Concentration cap (Max 10% allocation per position).
5. Dynamic relative-volume proportional sizing without intra-trade rebalancing.
"""

import sqlite3
import logging
from typing import List, Dict, Tuple, Optional
import numpy as np

from app.config import CONFIG, DEFAULT_DB_PATH
from app.db import get_db_connection

logger = logging.getLogger("paper_trading.ranking")

class ModelCRankingEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH

    def rank_and_allocate_signals(
        self,
        signals: List[Dict],
        current_equity: float,
        portfolio_cash: float,
        open_positions_count: int,
        capital_tier: float = 1_000_000.0
    ) -> Tuple[List[Dict], List[Dict]]:
        """Rank candidates deterministically and calculate Model C capital allocations.
        
        Returns:
            (accepted_orders, rejected_signals)
        """
        if not signals:
            return [], []

        conn = get_db_connection(self.db_path)
        cur = conn.cursor()

        available_slots = max(0, CONFIG.CAPACITY_SLOTS - open_positions_count)
        accepted_orders = []
        rejected_signals = []

        # 1. Separate by liquidity threshold
        liquid_signals = []
        for s in signals:
            t_cr = s.get("turnover_cr", 0.0)
            if t_cr < CONFIG.MIN_DAILY_TURNOVER_CR:
                s["status"] = "REJECTED_LIQUIDITY"
                s["reason"] = f"Turnover {t_cr:.2f} Cr below minimum threshold {CONFIG.MIN_DAILY_TURNOVER_CR:.2f} Cr"
                s["ranking"] = None
                s["allocation"] = 0.0
                rejected_signals.append(s)
            else:
                liquid_signals.append(s)

        # 2. Deterministic sort by Relative Volume descending (with symbol secondary sort for stability)
        liquid_signals = sorted(
            liquid_signals,
            key=lambda x: (x.get("relative_volume", 1.0), x.get("symbol", "")),
            reverse=True
        )

        # 3. Apply capacity limit
        qualifying_for_entry = liquid_signals[:available_slots]
        excess_signals = liquid_signals[available_slots:]

        for s in excess_signals:
            s["status"] = "REJECTED_CAPACITY"
            s["reason"] = f"Portfolio capacity full ({open_positions_count}/{CONFIG.CAPACITY_SLOTS} slots active)"
            s["ranking"] = None
            s["allocation"] = 0.0
            rejected_signals.append(s)

        # 4. Model C Relative Volume Proportional Weighting
        if qualifying_for_entry:
            k = len(qualifying_for_entry)
            rel_vols = np.array([max(0.01, float(s.get("relative_volume", 1.0))) for s in qualifying_for_entry])
            vol_sum = rel_vols.sum()
            batch_proportions = rel_vols / vol_sum

            # Weight = (k / Capacity) * Proportion
            raw_weights = (float(k) / CONFIG.CAPACITY_SLOTS) * batch_proportions
            capped_weights = np.minimum(raw_weights, CONFIG.MAX_CONCENTRATION_PCT)

            target_allocations = capped_weights * current_equity
            total_target = target_allocations.sum()

            deployable_cash = max(0.0, min(portfolio_cash, current_equity))
            if total_target > deployable_cash and total_target > 0:
                scale_factor = deployable_cash / total_target
                actual_allocations = target_allocations * scale_factor
            else:
                actual_allocations = target_allocations

            for rank_idx, s in enumerate(qualifying_for_entry, start=1):
                alloc_rs = float(actual_allocations[rank_idx - 1])
                s["ranking"] = rank_idx
                s["allocation"] = alloc_rs
                s["status"] = "ACCEPTED"
                s["reason"] = f"Rank {rank_idx} by RelVol {s.get('relative_volume', 1.0):.2f}x; Allocated ₹{alloc_rs:,.2f}"

                # Create simulated order draft
                accepted_orders.append(s)

        # 5. Persist all signal outcomes to database
        with conn:
            for s in accepted_orders + rejected_signals:
                cur.execute("""
                INSERT INTO signals (
                    symbol, signal_date, signal_type, monthly_rsi, monthly_ema9, monthly_close,
                    daily_ema21, resistance, breakout_price, confirmation_price, relative_volume,
                    ranking, allocation, status, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    s["symbol"], s["signal_date"], s["signal_type"], s.get("monthly_rsi"),
                    s.get("monthly_ema9"), s.get("monthly_close"), s.get("daily_ema21"),
                    s.get("resistance"), s.get("breakout_price"), s.get("confirmation_price"),
                    s.get("relative_volume"), s.get("ranking"), s.get("allocation"),
                    s["status"], s["reason"]
                ))
                s["signal_id"] = cur.lastrowid

        conn.close()
        logger.info(f"Model C allocation: {len(accepted_orders)} accepted, {len(rejected_signals)} rejected.")
        return accepted_orders, rejected_signals
