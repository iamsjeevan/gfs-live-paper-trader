"""Main Orchestrator and CLI for Indian Equity Paper Trading Engine.

Commands:
- --init-db: Initialize SQLite paper trading database
- --sync-data: Seed/sync market data from historical database
- --run-daily --date YYYY-MM-DD: Run simulation cycle for a specific trading day
- --run-continuous: Run continuous scheduler loop + embedded web dashboard
- --status: Print current portfolio performance metrics and heartbeat
- --generate-reports: Generate all markdown reports
"""

import sys
import time
import argparse
import datetime
import logging
from pathlib import Path
from typing import Optional, Dict

from app.config import CONFIG, DEFAULT_DB_PATH, LOG_FILE, REAL_ORDERS_ENABLED
from app.db import init_paper_trading_db, get_db_connection
from app.data import MarketDataManager
from app.strategy import TechnicalStrategyEngine
from app.ranking import ModelCRankingEngine
from app.execution import PaperExecutionEngine
from app.portfolio import PortfolioManager
from app.reports import ReportGenerator
from app.alerts import AlertDispatcher
from app.dashboard import DashboardServer

# Configure Logging
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("paper_trading.main")

def print_startup_banner(last_update_str: str = "N/A"):
    """Print Section 37 compliant startup banner."""
    banner = f"""
=========================================
INDIAN EQUITY PAPER TRADING ENGINE
==================================

Mode:
PAPER / SHADOW ONLY

Starting Capital:
₹10,00,000

Strategy:
Monthly RSI > 70
Monthly Close > EMA9
Daily EMA21
20D Breakout
0.5% Retest
Bullish Confirmation
Relative Volume Ranking

Portfolio:
15 Positions
10% Maximum Position
₹50L Minimum 20D ADT

Real Orders:
DISABLED

Last Data Update:
{last_update_str}

System Status:
RUNNING

=========================================
"""
    print(banner.strip())
    sys.stdout.flush()

class PaperTradingEngine:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.data_mgr = MarketDataManager(self.db_path)
        self.strategy_engine = TechnicalStrategyEngine(self.db_path)
        self.ranking_engine = ModelCRankingEngine(self.db_path)
        self.execution_engine = PaperExecutionEngine(self.db_path)
        self.portfolio_mgr = PortfolioManager(self.db_path)
        self.report_gen = ReportGenerator(self.db_path)
        self.alerts = AlertDispatcher()

    def run_daily_cycle(self, trading_date: str) -> dict:
        """Execute a full single-session EOD cycle on date `trading_date`."""
        logger.info(f"--- Starting Paper Trading Cycle for {trading_date} ---")

        # 1. Manage Active Positions (Exits, Stop-loss, Trailing activations)
        closed_trades, open_positions = self.execution_engine.process_position_management_and_exits(
            trading_date, CONFIG.STARTING_CAPITAL
        )
        for ct in closed_trades:
            self.alerts.alert_exit(ct["symbol"], ct["exit_price"], ct["return_pct"], ct["reason"])

        # 2. Evaluate Strategy Setups on Day T completed candle
        confirmed_signals = self.strategy_engine.evaluate_signals_for_date(trading_date)

        # 3. Fetch current portfolio equity and deployable cash
        p_state = self.portfolio_mgr.get_portfolio_state(CONFIG.STARTING_CAPITAL)
        curr_equity = p_state["total_equity"]
        avail_cash = p_state["cash"]
        active_slots = len(open_positions)

        # 4. Model C Relative Volume Ranking & Allocation
        accepted_orders, rejected_signals = self.ranking_engine.rank_and_allocate_signals(
            confirmed_signals, curr_equity, avail_cash, active_slots, CONFIG.STARTING_CAPITAL
        )

        for s in accepted_orders:
            self.alerts.alert_new_signal(s["symbol"], s.get("relative_volume", 1.0), s.get("allocation", 0.0))

        # 5. Simulate Next-Day Entries at Open (Simulated if today has open prices)
        filled_entries = self.execution_engine.simulate_entries(
            trading_date, accepted_orders, CONFIG.STARTING_CAPITAL
        )
        for fe in filled_entries:
            self.alerts.alert_entry(fe["symbol"], fe["simulated_open"], fe["shares"], fe["initial_stop"])

        # 6. Take Mark-to-Market Portfolio Snapshot for all capital tiers
        snapshot = None
        for tier in CONFIG.CAPITAL_TIERS:
            # Scale allocations proportionally for multi-capital simulation
            snap = self.portfolio_mgr.record_daily_snapshot(trading_date, tier)
            if tier == CONFIG.STARTING_CAPITAL:
                snapshot = snap

        # 7. Generate Daily Report
        self.report_gen.generate_daily_report(trading_date, CONFIG.STARTING_CAPITAL)

        logger.info(
            f"Cycle for {trading_date} completed. Equity: ₹{snapshot['total_equity']:,.2f} | "
            f"Daily: {snapshot['daily_return_pct']:+.2f}% | Open: {snapshot['open_positions_count']}/15"
        )
        return snapshot

def main():
    parser = argparse.ArgumentParser(description="Indian Equity Paper Trading Engine")
    parser.add_argument("--init-db", action="store_true", help="Initialize paper trading SQLite schema")
    parser.add_argument("--sync-data", action="store_true", help="Sync market data from historical database")
    parser.add_argument("--run-daily", action="store_true", help="Run a single daily paper trading cycle")
    parser.add_argument("--date", type=str, default=None, help="Trading date in YYYY-MM-DD format")
    parser.add_argument("--run-continuous", action="store_true", help="Run continuous scheduler loop + dashboard")
    parser.add_argument("--status", action="store_true", help="Print current status and metrics")
    parser.add_argument("--generate-reports", action="store_true", help="Generate all markdown reports")
    args = parser.parse_args()

    engine = PaperTradingEngine()

    if args.init_db:
        init_paper_trading_db()
        print("Paper trading database initialized at", DEFAULT_DB_PATH)
        return

    if args.sync_data:
        init_paper_trading_db()
        n = engine.data_mgr.sync_from_historical_db()
        print(f"Synchronized {n:,} price records into paper trading database.")
        return

    if args.status:
        metrics = engine.portfolio_mgr.compute_comprehensive_metrics(CONFIG.STARTING_CAPITAL)
        print_startup_banner(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print("\nPERFORMANCE METRICS SUMMARY:")
        for k, v in metrics.items():
            if isinstance(v, float):
                print(f"  {k:30s}: {v:,.2f}")
            else:
                print(f"  {k:30s}: {v}")
        return

    if args.generate_reports:
        now_dt = datetime.datetime.now()
        engine.report_gen.generate_final_report(CONFIG.STARTING_CAPITAL)
        print("Generated final report at reports/final/FINAL_PAPER_TRADING_REPORT.md")
        return

    if args.run_daily:
        run_date = args.date or datetime.date.today().strftime("%Y-%m-%d")
        snap = engine.run_daily_cycle(run_date)
        print(f"Completed run for {run_date}. Total Equity: ₹{snap['total_equity']:,.2f}")
        return

    if args.run_continuous:
        init_paper_trading_db()
        last_update = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print_startup_banner(last_update)

        # Start Dashboard in background
        dashboard = DashboardServer(host=CONFIG.DASHBOARD_HOST, port=CONFIG.DASHBOARD_PORT)
        dashboard.start_background()
        print(f"\nWeb Dashboard available at: http://localhost:{CONFIG.DASHBOARD_PORT}")
        print("Running live continuous paper trading loop... (Press Ctrl+C to terminate safely)")

        try:
            while True:
                time.sleep(3600)  # Hourly heartbeat check
        except KeyboardInterrupt:
            print("\nStopping paper trading system safely...")
            dashboard.stop()
            print("System stopped.")
        return

    # Default fallback: show banner and help
    print_startup_banner(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    parser.print_help()

if __name__ == "__main__":
    main()
