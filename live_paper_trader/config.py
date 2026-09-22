"""
live_paper_trader.config
========================
Configuration settings for the 1-Year Automated Paper Trading Engine
for both Indian and US Equity Markets across Dual Universes:
1. Broad Universe (All stocks meeting basic sanity floor: > ₹100Cr MCap in India, INDmoney/Tickertape tradeable in US)
2. Liquid Universe (High liquidity / institutional quality subset)
"""

import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports" / "paper_trading"
LOGS_DIR = REPORTS_DIR / "logs"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Universe file paths
MODULE_DIR = Path(__file__).resolve().parent
UNIVERSE_INDIA_BROAD = MODULE_DIR / "universe_india_broad.json"
UNIVERSE_INDIA_LIQUID = MODULE_DIR / "universe_india_liquid.json"
UNIVERSE_USA_BROAD = MODULE_DIR / "universe_usa_broad.json"
UNIVERSE_USA_LIQUID = MODULE_DIR / "universe_usa_liquid.json"

# State persistence files
STATE_INDIA_BROAD = REPORTS_DIR / "portfolio_state_india_broad.json"
STATE_INDIA_LIQUID = REPORTS_DIR / "portfolio_state_india_liquid.json"
STATE_USA_BROAD = REPORTS_DIR / "portfolio_state_usa_broad.json"
STATE_USA_LIQUID = REPORTS_DIR / "portfolio_state_usa_liquid.json"

# ==========================================
# 1. INDIAN MARKET CONFIGURATION
# ==========================================
INDIA_INITIAL_CAPITAL = float(os.getenv("INDIA_CAPITAL", "100000.0")) # ₹1,00,000
INDIA_SLOTS = 10
INDIA_CASH_PROXY = "GOLDBEES.NS"
INDIA_INDEX_TICKER = "^NSEI" # Nifty 50

# Frictions
INDIA_STOCK_FEE_BPS = 25.0 # 0.25% broker + STT + slippage
INDIA_GOLD_FEE_BPS = 10.0  # 0.10% ETF slippage/brokerage

# Regime Schedule 1: Exposure limits
REGIME_EXPOSURE = {
    "BULL": 1.00,    # 10 slots active
    "NEUTRAL": 0.70, # 7 slots active
    "BEAR": 0.30     # 3 slots active
}

# India GFS Parameters
INDIA_MONTHLY_RSI_PERIOD = 14
INDIA_MONTHLY_RSI_THRESH = 60.0
INDIA_MONTHLY_EMA_SPAN = 9

INDIA_WEEKLY_RSI_PERIOD = 14
INDIA_WEEKLY_RSI_THRESH = 60.0

INDIA_DAILY_RSI_PERIOD = 14
INDIA_DAILY_RSI_TRIGGER = 40.0

# Indian Exit Rule: Month-end close < Monthly EMA9 (No dead money eviction in India!)
INDIA_DEAD_MONEY_DAYS = 0

# ==========================================
# 2. US MARKET CONFIGURATION
# ==========================================
USA_INITIAL_CAPITAL = float(os.getenv("USA_CAPITAL", "10000.0")) # $10,000
USA_SLOTS = 10
USA_CASH_PROXY = "GLD"      # SPDR Gold Shares ETF (Gold Proxy)
USA_INDEX_TICKER = "SPY"    # S&P 500

# Frictions
USA_STOCK_FEE_BPS = 5.0
USA_ETF_FEE_BPS = 2.0

# US GFS Parameters
USA_MONTHLY_RSI_PERIOD = 14
USA_MONTHLY_RSI_THRESH = 60.0
USA_MONTHLY_EMA_SPAN = 13

USA_WEEKLY_RSI_PERIOD = 14
USA_WEEKLY_RSI_THRESH = 60.0

USA_DAILY_RSI_PERIOD = 14
USA_DAILY_RSI_TRIGGER = 40.0

# US Exit Rule: 60-Day Dead-Money Eviction (< +3% return) + Month-End close < EMA13
USA_DEAD_MONEY_DAYS = 60
USA_DEAD_MONEY_THRESH_PCT = 3.0

# ==========================================
# 3. EMAIL NOTIFICATION SETTINGS (SMTP)
# ==========================================
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# Telegram Fallback (optional)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
