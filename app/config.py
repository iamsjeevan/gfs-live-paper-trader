"""Configuration module for Indian Equity Paper Trading Engine.

FROZEN STRATEGY SPECIFICATION:
- Monthly: RSI(14) > 70 AND Monthly Close > Monthly EMA(9)
- Daily: Daily Close > EMA(21)
- Resistance: Highest High of previous 20 completed trading days (excluding current)
- Breakout: Daily Close > Resistance
- Retest: Price returns within +-0.5% of broken resistance [0.995 * R, 1.005 * R]
- Confirmation: Trade into retest zone, Close > R, Close > Open, Close > EMA(21)
- Entry: Next trading day OPEN
- Initial Stop: Entry * 0.97 (-3.0%)
- Trailing Activation: High >= Entry * 1.05 (+5.0%)
- Trailing Exit: Completed Daily Close < Daily EMA(21) -> Next Open
- Allocation: Model C - Relative Volume Weighting (Max 15 positions, 10% cap)
- Safety: Real order placement is ARCHITECTURALLY DISABLED.
"""

import os
from pathlib import Path
from dataclasses import dataclass

# Root directory of the repository
BASE_DIR = Path(__file__).resolve().parent.parent

# Database Paths
DEFAULT_DB_PATH = BASE_DIR / "database" / "paper_trading.db"
HISTORICAL_DB_PATH = BASE_DIR / "data" / "indian_market.db"

# Reports & Logs
REPORTS_DIR = BASE_DIR / "reports"
DAILY_REPORTS_DIR = REPORTS_DIR / "daily"
WEEKLY_REPORTS_DIR = REPORTS_DIR / "weekly"
MONTHLY_REPORTS_DIR = REPORTS_DIR / "monthly"
FINAL_REPORTS_DIR = REPORTS_DIR / "final"
LOGS_DIR = BASE_DIR / "logs"
LOG_FILE = LOGS_DIR / "paper_trading.log"

# Real Money Safety - HARDCODED ARCHITECTURAL SAFETY GUARD
REAL_ORDERS_ENABLED = False  # NEVER SET TO TRUE. THIS SYSTEM IS PAPER-ONLY.

@dataclass(frozen=True)
class StrategyConfig:
    # Monthly Setup
    MONTHLY_RSI_PERIOD: int = 14
    MONTHLY_RSI_THRESHOLD: float = 70.0
    MONTHLY_EMA_SPAN: int = 9

    # Daily Setup
    DAILY_EMA_SPAN: int = 21
    RESISTANCE_LOOKBACK: int = 20
    RETEST_TOLERANCE: float = 0.005  # +-0.5%
    MAX_DAYS_TO_CONFIRM: int = 20    # Expire setup if no confirmation within 20 trading days
    INVALIDATION_PCT: float = 0.03   # Invalidate setup if price drops >3% below resistance

    # Trade Management
    INITIAL_STOP_LOSS_PCT: float = 0.03     # -3.0%
    TRAILING_ACTIVATION_PCT: float = 0.05   # +5.0%
    
    # Portfolio & Capacity
    STARTING_CAPITAL: float = float(os.getenv("STARTING_CAPITAL", "1000000.0"))  # ₹10,00,000
    CAPACITY_SLOTS: int = 15
    MAX_CONCENTRATION_PCT: float = 0.10     # Max 10% per position
    MIN_DAILY_TURNOVER_CR: float = 0.50     # ₹50 Lakhs / day 20D average turnover
    
    # Capital Tiers to track simultaneously
    CAPITAL_TIERS = (100_000.0, 500_000.0, 1_000_000.0, 2_500_000.0, 5_000_000.0)

    # Execution Simulation Frictions
    SLIPPAGE_BPS_ENTRY: float = float(os.getenv("SLIPPAGE_BPS_ENTRY", "25.0"))  # 0.25% per side
    SLIPPAGE_BPS_EXIT: float = float(os.getenv("SLIPPAGE_BPS_EXIT", "25.0"))    # 0.25% per side

    # Alert Configurations
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")

    # Dashboard Port
    DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "8080"))
    DASHBOARD_HOST: str = os.getenv("DASHBOARD_HOST", "0.0.0.0")

# Global Config Instance
CONFIG = StrategyConfig()
