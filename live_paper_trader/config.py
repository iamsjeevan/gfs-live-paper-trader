"""
live_paper_trader.config
========================
Institutional Configuration for the Indian Equities Forward Testing Engine:
- Stage 2 Trend + Near 52-Week High Breakout
- Dual-Layer Stop Loss (-12% Intraday GTT Circuit Guard + -8% EOD Close Stop)
- 21 EMA Trailing Exit with 1.5% Anti-Whipsaw Buffer
- Smallcap 250 / Nifty Regime Filter with Gold BeES Parking
- Tiered Conviction Sizing (18% / 11% / 6.2%) with 1.5x Leverage
"""

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports" / "paper_trading"
LOGS_DIR = REPORTS_DIR / "logs"

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# State persistence files
STATE_FILE = REPORTS_DIR / "portfolio_state.json"
TRADES_FILE = REPORTS_DIR / "trades_history.json"
EQUITY_FILE = REPORTS_DIR / "equity_curve.json"
SCAN_RESULTS_FILE = REPORTS_DIR / "latest_scan_results.json"
DASHBOARD_FILE = BASE_DIR / "index.html" # Deployed directly by Vercel

# Universe files
MODULE_DIR = Path(__file__).resolve().parent
UNIVERSE_FILE = MODULE_DIR / "universe_india_liquid.json" # Nifty 500 & liquid smallcaps

# Capital & Leverage Configuration
INITIAL_CAPITAL = float(os.getenv("INITIAL_CAPITAL", "100000.0")) # ₹ 1,00,000 per portfolio
ANNUAL_INTEREST_RATE = 0.11 # 11% p.a. MTF broker interest
DAILY_INTEREST_RATE = ANNUAL_INTEREST_RATE / 252.0

# 4 Live Forward-Testing Portfolio Configurations
PORTFOLIOS = {
    "tiered_7_1_5x": {
        "id": "tiered_7_1_5x",
        "name": "Tiered 7-Slot (1.5x MTF Champion)",
        "short_name": "1.5x Champion",
        "badge": "👑 1.5x MTF Champion",
        "slots": 7,
        "weights": [0.22, 0.22, 0.15, 0.15, 0.086, 0.086, 0.088],
        "leverage": 1.5,
        "initial_capital": INITIAL_CAPITAL,
        "color": "#38bdf8", # Sky blue
        "description": "Optimal Kelly Growth • Sharpe 1.14 • ₹2.88 Cr 17.7Y Backtest"
    },
    "tiered_7_1x": {
        "id": "tiered_7_1x",
        "name": "Tiered 7-Slot (1.0x Pure Cash)",
        "short_name": "1.0x Cash",
        "badge": "🛡️ 1.0x Pure Cash",
        "slots": 7,
        "weights": [0.22, 0.22, 0.15, 0.15, 0.086, 0.086, 0.088],
        "leverage": 1.0,
        "initial_capital": INITIAL_CAPITAL,
        "color": "#34d399", # Emerald green
        "description": "Zero Margin Debt • Pure Cash • Lowest Career Drawdown"
    },
    "tiered_7_2x": {
        "id": "tiered_7_2x",
        "name": "Tiered 7-Slot (2.0x MTF Alpha)",
        "short_name": "2.0x Alpha",
        "badge": "🚀 2.0x MTF Alpha",
        "slots": 7,
        "weights": [0.22, 0.22, 0.15, 0.15, 0.086, 0.086, 0.088],
        "leverage": 2.0,
        "initial_capital": INITIAL_CAPITAL,
        "color": "#f97316", # Orange
        "description": "Maximum Purchasing Power • ₹5.50 Cr 17.7Y Backtest"
    },
    "tiered_10_1_5x": {
        "id": "tiered_10_1_5x",
        "name": "Tiered 10-Slot (1.5x MTF Control)",
        "short_name": "1.5x 10-Slot Control",
        "badge": "📊 1.5x 10-Slot Control",
        "slots": 10,
        "weights": [0.18, 0.18, 0.11, 0.11, 0.11, 0.062, 0.062, 0.062, 0.062, 0.062],
        "leverage": 1.5,
        "initial_capital": INITIAL_CAPITAL,
        "color": "#a855f7", # Purple
        "description": "Original 10-Slot Baseline Control (18% / 11% / 6.2%)"
    }
}

# Legacy default aliases for single-model backward compatibility
MAX_POSITIONS = 7
LEVERAGE = 1.5
TIER_WEIGHTS = [0.22, 0.22, 0.15, 0.15, 0.086, 0.086, 0.088]

# Dual-Layer Stop Loss Architecture
GTT_CIRCUIT_STOP_PCT = -0.12 # -12.0% Intraday Emergency GTT Circuit Guard
CLOSE_STOP_PCT = -0.08       # -8.0% Routine Daily Close Stop (evaluated at 3:30 PM)

# Trailing Profit Exit
EMA_TRAIL_SPAN = 21          # 21 EMA trailing stop
EMA_BUFFER_PCT = 0.015       # 1.5% buffer below 21 EMA to avoid fractional false whipsaws (e.g. TBZ)

# Macro Regime Filter & Hedging
REGIME_INDEX = "^NSEI"       # Nifty 50 / Broad Indian Index
CASH_PROXY = "GOLDBEES.NS"   # Nippon India Gold ETF (park capital when regime is BEAR)

# Frictional Costs
TRANSACTION_FEE_BPS = 0.0025 # 25 bps round-trip (brokerage + STT + turnover charges)
SLIPPAGE_BPS = 0.0050        # 50 bps entry slippage modeled

# Notifications (Optional Email / Telegram)
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
