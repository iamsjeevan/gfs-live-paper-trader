# Indian Equity Momentum Paper/Shadow Trading System
**Production-Grade 3–6 Month Live Simulation Engine**

An automated, institutional-grade live paper trading system implementing the validated **Indian Equity Momentum Breakout Strategy (Model C — Relative Volume Weighting)**.

> **CRITICAL ARCHITECTURAL SAFETY GUARANTEE:**  
> This system is strictly configured for **PAPER / SHADOW TRADING ONLY**. Real broker order placement functions (`place_order`, `modify_order`, etc.) are **architecturally disabled**. It simulates fills, slippage, and portfolio equity in real time using live market data without risking real capital.

---

## 1. Frozen Strategy Rules

The strategy parameters are strictly **frozen** for the 3–6 month live validation experiment:

1. **Monthly Candidate Filter:**
   - Completed prior month $RSI(14) > 70$
   - Completed prior month $Close > EMA(9)$
2. **Daily Setup & Breakout:**
   - Daily $Close > EMA(21)$
   - $Resistance = \max(\text{High}_{t-20:t-1})$ (excluding current day)
   - $Breakout = \text{Daily Close} > Resistance$ (no entry on breakout candle)
3. **Retest Zone:**
   - Price returns within $\pm 0.5\%$ of broken resistance ($[0.995 \times R, 1.005 \times R]$)
   - Expiration: Must confirm within 20 trading days after breakout
   - Invalidation: Daily Close drops below $0.97 \times R$
4. **Bullish Confirmation Candle:**
   - Low $\le 1.005 \times R$ and High $\ge 0.995 \times R$
   - $Close > R$
   - $Close > Open$ (Bullish green bar)
   - $Close > Daily\ EMA(21)$
5. **Entry Simulation:**
   - Entry on Next Trading Day Market Open ($T+1$ Open at 09:15 IST)
   - Simulated fill with configurable slippage (Default: 25 bps per side):
     $$\text{Fill Price} = \text{Market Open} \times 1.0025$$
6. **Position Management:**
   - **Initial Stop:** $\text{Entry} \times 0.97$ (-3.0%). Realized with realistic gap-down execution if open gaps below stop.
   - **+5% Activation:** When $\text{High} \ge \text{Entry} \times 1.05$, activate EMA21 trailing regime and ignore the -3% stop.
   - **Trailing Exit:** When completed daily candle $\text{Close} < \text{Daily } EMA(21)$, exit on next trading day Open with slippage.
7. **Portfolio & Allocation (Model C):**
   - Default Starting Capital: ₹10,00,000
   - Capacity: Max 15 simultaneous open positions
   - Concentration Cap: Max 10% allocation per position (₹1,00,000 max initial allocation)
   - Minimum Liquidity: 20-day Average Daily Turnover $\ge$ ₹50 Lakhs/day
   - Long-only, no leverage, no shorting. Unused cash remains uninvested.

---

## 2. Directory Structure

```
.
├── app/
│   ├── config.py         # Strategy parameters, capital tiers, slippage settings
│   ├── db.py             # SQLite schema initialization and connection manager
│   ├── data.py           # Market data ingestion (NSE Bhavcopy / Yahoo Finance)
│   ├── indicators.py     # RSI, EMA, 20D Resistance, Relative Volume
│   ├── strategy.py       # Causal breakout, retest, confirmation state machine
│   ├── ranking.py        # Model C relative volume ranking and allocation
│   ├── execution.py      # Simulated fills, gap-down stops, circuit detection
│   ├── portfolio.py      # Mark-to-market engine, snapshots, multi-capital tracker
│   ├── alerts.py         # Telegram, Discord, and console notification dispatcher
│   ├── reports.py        # Automated daily, weekly, monthly, checkpoint reports
│   ├── dashboard.py      # Embedded web server and reactive dashboard
│   └── main.py           # CLI runner, scheduler loop, Section 37 banner
├── database/
│   └── paper_trading.db  # Persistent SQLite database
├── reports/
│   ├── daily/            # Markdown daily snapshots (YYYY-MM-DD.md)
│   ├── weekly/           # Markdown weekly performance summaries
│   ├── monthly/          # Markdown monthly audits
│   └── final/            # Final validation report
├── logs/
│   └── paper_trading.log
├── tests/
│   ├── test_paper_engine.py      # Indicator and strategy unit tests
│   └── test_historical_replay.py # Historical replay parity tests
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## 3. Quickstart & Local Setup

### Step 1: Install Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure Environment
```bash
cp .env.example .env
# Edit .env to set custom starting capital, telegram alerts, or dashboard port
```

### Step 3: Run Tests
```bash
# Run unit tests
python -m unittest tests/test_paper_engine.py

# Run historical replay parity test
python -m unittest tests/test_historical_replay.py
```

### Step 4: Initialize Database & Sync Data
```bash
# Initialize SQLite database
python -m app.main --init-db

# Sync data from historical database (if available)
python -m app.main --sync-data
```

### Step 5: Start Live Continuous Engine & Web Dashboard
```bash
python -m app.main --run-continuous
```
Access the responsive web dashboard at: **http://localhost:8080**

---

## 4. Daily Execution Cycle (Cron Schedule)

In live paper trading, Indian equity markets close at 15:30 IST. Daily candles are typically finalized between 15:45 and 16:00 IST.

Set up a daily cron job to run the EOD cycle automatically:
```bash
# Run every Monday through Friday at 16:00 IST (10:30 UTC)
30 10 * * 1-5 cd /path/to/project && /path/to/.venv/bin/python -m app.main --run-daily >> logs/cron.log 2>&1
```

---

## 5. Market Data Source & Cost Analysis

| Data Provider | Data Type | Cost | Latency / Frequency | Reliability |
| :--- | :--- | :--- | :--- | :--- |
| **NSE Bhavcopy (Public Archive)** | Daily EOD OHLCV | **FREE ($0)** | Finalized daily at 16:30 IST | 100% Official Official Exchange Data |
| **Yahoo Finance (`yfinance`)** | Daily OHLCV (`.NS`) | **FREE ($0)** | Real-time & EOD daily bars | High (Standard for systematic paper trading) |
| **Local SQLite Database** | Historical OHLCV | **FREE ($0)** | 2018–2026 pre-loaded | 100% Deterministic |
| **Broker API (Zerodha / Dhan)** | Historical Data API | ₹2,000 / month | Millisecond tick / 1-minute / EOD | High (Optional for real execution later) |

**Recommendation:** For the 3–6 month paper trading experiment, **FREE public sources (NSE Bhavcopy / Yahoo Finance) are 100% sufficient**. Do not pay for expensive institutional feeds.

---

## 6. Cloud Deployment & Cheapest Hosting Options

To run the system 24/7 for 3–6 months uninterrupted, deploy on a lightweight Linux VPS:

### Option A: Oracle Cloud Always Free Tier (**$0 / month — Recommended**)
- **Specs:** Ampere A1 ARM Compute (Up to 4 OCPUs, 24 GB RAM free forever) or 1 AMD micro-instance.
- **Cost:** **₹0 / $0**.
- **Deployment:**
  ```bash
  sudo apt update && sudo apt install -y git python3-pip docker.io docker-compose
  git clone <repo_url> && cd value_investing_backtest
  docker-compose up -d
  ```

### Option B: Hetzner Cloud (**~€3.50 / month**)
- **Specs:** CX22 (2 vCPU, 4 GB RAM, 40 GB NVMe SSD).
- **Cost:** ~₹320 / month. Unbeatable performance-to-price ratio in Europe/India routing.

### Option C: AWS EC2 `t4g.nano` (**~$3.20 / month**)
- **Specs:** 2 vCPUs, 0.5 GB RAM (with 2GB swap enabled).
- **Region:** `ap-south-1` (Mumbai) for minimal Indian market API latency.

---

## 7. Reports & Performance Interpretation

- **Daily Reports:** Automatically stored in `reports/daily/YYYY-MM-DD.md` after every trading session.
- **Weekly Summaries:** `reports/weekly/YYYY-WW.md` every Friday evening.
- **Monthly Audits:** `reports/monthly/YYYY-MM.md` at month end.
- **Checkpoints:** Triggered at 30, 60, 90, 120, 150 trading days to audit drift against backtest expectations.

> **Performance Interpretation Standard:**  
> Always distinguish **REAL MONEY** from **SIMULATED MONEY**. State: *"Virtual portfolio equity changed by +X%"*. Never extrapolate 3-month performance into an annualized guarantee.
