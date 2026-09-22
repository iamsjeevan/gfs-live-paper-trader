"""
live_paper_trader.runner
========================
Main CLI orchestrator running the 4 parallel paper trading portfolios:
1. `india_broad`: All Indian stocks > ₹100 Cr Market Cap
2. `india_liquid`: Nifty 500 Liquid subset
3. `usa_broad`: INDmoney / Tickertape tradeable US equities
4. `usa_liquid`: S&P 500 Mega-liquid US equities
"""

import argparse
import sys
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from live_paper_trader.engine import PaperTradingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("live_paper_trader.runner")

ALL_PORTFOLIOS = ["india_broad", "india_liquid", "usa_broad", "usa_liquid"]

def main():
    parser = argparse.ArgumentParser(description="GFS 1-Year Live Dual-Universe Paper Trading Runner")
    parser.add_argument(
        "--portfolio",
        choices=["all", "india_broad", "india_liquid", "usa_broad", "usa_liquid"],
        default="all",
        help="Specific portfolio to run (default: all)"
    )
    parser.add_argument(
        "--market",
        choices=["all", "india", "usa"],
        default=None,
        help="Convenience filter by market (runs both broad & liquid for that market)"
    )
    parser.add_argument(
        "--force-monthly-report",
        action="store_true",
        help="Force generation and dispatch of monthly performance email report"
    )
    parser.add_argument(
        "--init-only",
        action="store_true",
        help="Only initialize paper trading state files without running daily scan"
    )

    args = parser.parse_args()

    if args.market == "india":
        targets = ["india_broad", "india_liquid"]
    elif args.market == "usa":
        targets = ["usa_broad", "usa_liquid"]
    elif args.portfolio == "all":
        targets = ALL_PORTFOLIOS
    else:
        targets = [args.portfolio]

    print("\n" + "="*80)
    print(f"🚀 RUNNING GFS 1-YEAR FORWARD TEST SUITE FOR: {', '.join(targets)}")
    print("="*80)

    for p_id in targets:
        try:
            logger.info(f"Starting Paper Trading Engine for [{p_id}]...")
            engine = PaperTradingEngine(portfolio_id=p_id)
            
            if args.init_only:
                logger.info(f"State initialized for [{p_id}].")
                continue

            engine.run_daily_cycle(force_monthly_report=args.force_monthly_report)
        except Exception as e:
            logger.error(f"Error executing cycle for [{p_id}]: {e}", exc_info=True)

if __name__ == "__main__":
    main()
