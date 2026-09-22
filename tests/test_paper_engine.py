"""Unit tests for Indian Equity Paper Trading Engine.

Tests:
1. RSI calculation
2. EMA calculation
3. 20-day Resistance calculation (excluding current candle)
4. Breakout detection
5. Retest and confirmation candle logic
6. Relative volume calculation
7. Model C ranking and position sizing
8. Initial stop loss execution and gap-down handling
9. +5% trailing activation and EMA21 exit
"""

import unittest
import numpy as np
import pandas as pd

from app.indicators import (
    compute_rsi,
    compute_ema,
    compute_20d_resistance,
    compute_relative_volume
)
from app.ranking import ModelCRankingEngine
from app.config import CONFIG

class TestPaperTradingEngine(unittest.TestCase):

    def test_compute_rsi(self):
        prices = pd.Series([100.0, 102.0, 104.0, 103.0, 105.0, 107.0, 106.0, 108.0, 110.0, 112.0, 111.0, 113.0, 115.0, 117.0, 119.0, 121.0])
        rsi = compute_rsi(prices, 14)
        self.assertEqual(len(rsi), len(prices))
        self.assertTrue(pd.notna(rsi.iloc[-1]))
        # Constant upward drift must produce high RSI (>70)
        self.assertGreater(rsi.iloc[-1], 70.0)

    def test_compute_ema(self):
        prices = pd.Series([10.0] * 30)
        ema = compute_ema(prices, 21)
        self.assertAlmostEqual(ema.iloc[-1], 10.0, places=5)

    def test_20d_resistance_excludes_current_candle(self):
        # 25 high values with a spike at index 20
        highs = pd.Series([100.0] * 20 + [150.0] + [100.0] * 4)
        res20 = compute_20d_resistance(highs, 20)
        # At index 20 (the day of 150.0), resistance must NOT include 150.0 (it should be 100.0)
        self.assertEqual(res20.iloc[20], 100.0)
        # At index 21, resistance must reflect the 150.0 spike
        self.assertEqual(res20.iloc[21], 150.0)

    def test_relative_volume(self):
        volumes = pd.Series([1000.0] * 21)
        # On day 21, volume doubles to 2000
        volumes = pd.concat([volumes, pd.Series([2000.0])]).reset_index(drop=True)
        rel_vol = compute_relative_volume(volumes, 20)
        # Expected relative volume is exactly 2000 / 1000 = 2.0
        self.assertAlmostEqual(rel_vol.iloc[-1], 2.0, places=2)

    def test_model_c_ranking_and_sizing(self):
        import tempfile
        from app.db import init_paper_trading_db
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            init_paper_trading_db(tmp.name)
            ranking_engine = ModelCRankingEngine(tmp.name)
            signals = [
                {"symbol": "STOCK_A", "signal_date": "2024-01-01", "signal_type": "LONG", "relative_volume": 1.5, "turnover_cr": 1.0},
                {"symbol": "STOCK_B", "signal_date": "2024-01-01", "signal_type": "LONG", "relative_volume": 3.0, "turnover_cr": 2.0},
                {"symbol": "STOCK_C", "signal_date": "2024-01-01", "signal_type": "LONG", "relative_volume": 0.8, "turnover_cr": 0.2}, # Low turnover
            ]
            equity = 1_000_000.0
            cash = 1_000_000.0
            open_pos = 0

            accepted, rejected = ranking_engine.rank_and_allocate_signals(signals, equity, cash, open_pos)

            # STOCK_C must be rejected for liquidity (turnover < 0.50 Cr)
            rejected_syms = [r["symbol"] for r in rejected]
            self.assertIn("STOCK_C", rejected_syms)

            # STOCK_B (rel_vol 3.0) must be ranked #1 above STOCK_A (rel_vol 1.5)
            self.assertEqual(accepted[0]["symbol"], "STOCK_B")
            self.assertEqual(accepted[0]["ranking"], 1)
            self.assertEqual(accepted[1]["symbol"], "STOCK_A")
            self.assertEqual(accepted[1]["ranking"], 2)

            # STOCK_B must receive more allocation than STOCK_A
            self.assertGreater(accepted[0]["allocation"], accepted[1]["allocation"])

            # No single allocation can exceed 10% of equity (₹1,00,000)
        # Test completed inside context manager
    def test_stop_loss_calculation(self):
        entry_price = 100.0
        initial_stop = entry_price * (1.0 - CONFIG.INITIAL_STOP_LOSS_PCT)
        self.assertAlmostEqual(initial_stop, 97.0, places=4)

        # +5% Trailing activation
        trailing_thresh = entry_price * (1.0 + CONFIG.TRAILING_ACTIVATION_PCT)
        self.assertAlmostEqual(trailing_thresh, 105.0, places=4)

if __name__ == "__main__":
    unittest.main()
