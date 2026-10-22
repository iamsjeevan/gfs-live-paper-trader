"""
live_paper_trader.runner
========================
Main CLI orchestrator for forward-testing Indian Equities:
1. Hourly Intraday GTT Circuit Guard Check (--mode intraday)
2. Daily End-of-Day Scan, Stop Evaluation & Rebalance (--mode eod)
3. Smart Automatic Mode based on IST Market Hours (--mode auto)
4. Status Inspection (--mode status)
"""

import argparse
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from live_paper_trader.engine import PaperTradingEngine
from live_paper_trader.config import (
    PORTFOLIOS,
    REPORTS_DIR,
    STATE_FILE,
    TRADES_FILE,
    EQUITY_FILE,
    SCAN_RESULTS_FILE
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("live_paper_trader.runner")

def main():
    parser = argparse.ArgumentParser(description="Autonomous Indian Equities Swing Forward-Test Runner")
    parser.add_argument(
        "--mode",
        choices=["auto", "intraday", "eod", "status", "reset"],
        default="auto",
        help="Execution mode: auto (smart IST scheduler), intraday, eod, status, or reset"
    )
    args = parser.parse_args()

    engine = PaperTradingEngine()

    if args.mode == "reset":
        logger.warning("Resetting forward-test state for all 4 portfolios to initial capital...")
        for p in REPORTS_DIR.glob("*.json"):
            try:
                p.unlink()
            except Exception:
                pass
        engine = PaperTradingEngine()
        engine.generate_dashboard_html()
        logger.info("All 4 forward-testing portfolios successfully reset.")
        return

    if args.mode == "auto":
        # Smart IST market clock
        now_utc = datetime.utcnow()
        now_ist = now_utc + timedelta(hours=5, minutes=30)
        weekday = now_ist.weekday() # 0 = Monday, 6 = Sunday
        hour = now_ist.hour
        minute = now_ist.minute
        time_minutes = hour * 60 + minute

        logger.info(f"Clock Check: IST Time = {now_ist.strftime('%Y-%m-%d %H:%M:%S (%A)')}")

        # Weekend Check: Saturday (5) & Sunday (6)
        if weekday >= 5:
            logger.info("Weekend detected. Markets are closed. Skipping execution.")
            engine.generate_dashboard_html()
            return

        # 9:15 AM IST = 555 min, 3:30 PM IST = 930 min
        if time_minutes >= 930 and time_minutes <= 1140: # 3:30 PM to 7:00 PM IST
            logger.info("Market close window detected. Running End-of-Day (EOD) screening & rebalance.")
            engine.run_eod_cycle()
        elif time_minutes >= 555 and time_minutes < 930: # 9:15 AM to 3:30 PM IST
            logger.info("Market hours active. Running hourly Intraday -12% GTT Circuit Guard check.")
            engine.run_intraday_cycle()
        else:
            logger.info("Night / Off-market hours. Skipping execution.")
            engine.generate_dashboard_html()
            return

    elif args.mode == "intraday":
        engine.run_intraday_cycle()
    elif args.mode == "eod":
        engine.run_eod_cycle()
    elif args.mode == "status":
        print("\n" + "=" * 90)
        print(f"📊 LIVE 6-PORTFOLIO FORWARD TESTING STATUS ({datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')})")
        print("=" * 90)
        print(f"{'Portfolio Architecture':<36} | {'NAV (₹)':<13} | {'Net Ret':<9} | {'Positions':<9} | {'Trades':<7} | {'Regime':<6}")
        print("-" * 90)
        for p_id, p_cfg in engine.portfolios.items():
            st = engine.states[p_id]
            nav = engine.calculate_portfolio_equity(p_id)
            init_cap = p_cfg.get("initial_capital", 100000.0)
            ret_pct = ((nav / init_cap) - 1.0) * 100.0
            pos_cnt = len(st.get("positions", {}))
            trades_cnt = len(engine.trades[p_id])
            reg = st.get("current_regime", "BULL")
            print(f"{p_cfg['name']:<36} | ₹ {nav:>10,.2f} | {ret_pct:>+6.2f}% | {pos_cnt:>2}/{p_cfg['slots']:<2} stocks | {trades_cnt:>5}   | {reg}")
        print("=" * 90 + "\n")
        engine.generate_dashboard_html()

if __name__ == "__main__":
    main()
