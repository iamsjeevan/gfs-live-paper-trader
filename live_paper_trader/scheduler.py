"""
live_paper_trader.scheduler
===========================
Continuous 24/7 background daemon for deploying on Render, VPS, or Docker.
Schedules daily runs at market close for both Indian and US markets.
"""

import time
import logging
from datetime import datetime
import pytz
from live_paper_trader.engine import PaperTradingEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("live_paper_trader.scheduler")

IST = pytz.timezone("Asia/Kolkata")
EST = pytz.timezone("US/Eastern")

def run_india_market_cycle():
    logger.info("Executing scheduled Indian Market paper trading cycle...")
    try:
        engine = PaperTradingEngine(market="india")
        engine.run_daily_cycle()
    except Exception as e:
        logger.error(f"Error in Indian market paper trading cycle: {e}", exc_info=True)

def run_usa_market_cycle():
    logger.info("Executing scheduled US Market paper trading cycle...")
    try:
        engine = PaperTradingEngine(market="usa")
        engine.run_daily_cycle()
    except Exception as e:
        logger.error(f"Error in US market paper trading cycle: {e}", exc_info=True)

def main():
    logger.info("Starting GFS 24/7 Paper Trading Scheduler Daemon...")
    last_india_run = None
    last_usa_run = None

    while True:
        now_ist = datetime.now(IST)
        now_est = datetime.now(EST)
        today_ist = now_ist.strftime("%Y-%m-%d")
        today_est = now_est.strftime("%Y-%m-%d")

        # 1. India Market Run: Weekdays between 17:00 and 17:30 IST
        if now_ist.weekday() < 5:
            if now_ist.hour == 17 and 0 <= now_ist.minute <= 30 and last_india_run != today_ist:
                run_india_market_cycle()
                last_india_run = today_ist

        # 2. USA Market Run: Weekdays between 17:30 and 18:00 EST
        if now_est.weekday() < 5:
            if now_est.hour == 17 and 30 <= now_est.minute <= 59 and last_usa_run != today_est:
                run_usa_market_cycle()
                last_usa_run = today_est

        time.sleep(60) # check every minute

if __name__ == "__main__":
    main()
