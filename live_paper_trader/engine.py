"""
live_paper_trader.engine
========================
Autonomous Paper Trading Engine for Indian Equities.
Handles:
1. Hourly Intraday GTT -12% Circuit Guard Monitoring
2. End-of-Day (4:00 PM IST) Screening, Rebalancing & Stop Evaluation
3. State Persistence (JSON) & Direct Vercel Static HTML Deployment
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd
import numpy as np
import yfinance as yf

from live_paper_trader.config import (
    STATE_FILE,
    TRADES_FILE,
    EQUITY_FILE,
    SCAN_RESULTS_FILE,
    DASHBOARD_FILE,
    UNIVERSE_FILE,
    INITIAL_CAPITAL,
    LEVERAGE,
    MAX_POSITIONS,
    TIER_WEIGHTS,
    GTT_CIRCUIT_STOP_PCT,
    CLOSE_STOP_PCT,
    EMA_TRAIL_SPAN,
    EMA_BUFFER_PCT,
    DAILY_INTEREST_RATE,
    TRANSACTION_FEE_BPS,
    SLIPPAGE_BPS,
    CASH_PROXY
)
from live_paper_trader.signals import (
    get_market_regime,
    get_proxy_price,
    get_intraday_quotes,
    scan_universe_for_setups
)

logger = logging.getLogger("live_paper_trader.engine")

class PaperTradingEngine:
    def __init__(self):
        self.state = self.load_state()
        self.trades = self.load_trades()
        self.equity_history = self.load_equity_history()

    def load_state(self) -> Dict[str, Any]:
        """Loads persistent portfolio state from disk or initializes fresh."""
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read {STATE_FILE}, initializing fresh: {e}")

        initial_state = {
            "initial_capital": INITIAL_CAPITAL,
            "cash": INITIAL_CAPITAL,
            "borrowed_debt": 0.0,
            "gold_units": 0.0,
            "positions": {}, # symbol -> position details
            "total_interest_paid": 0.0,
            "current_regime": "BULL",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "last_mode": "INIT"
        }
        self.save_json(STATE_FILE, initial_state)
        return initial_state

    def load_trades(self) -> List[Dict[str, Any]]:
        if TRADES_FILE.exists():
            try:
                with open(TRADES_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def load_equity_history(self) -> List[Dict[str, Any]]:
        if EQUITY_FILE.exists():
            try:
                with open(EQUITY_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        today_str = datetime.now().strftime("%Y-%m-%d")
        return [{
            "date": today_str,
            "equity": INITIAL_CAPITAL,
            "cash": INITIAL_CAPITAL,
            "stock_value": 0.0,
            "gold_value": 0.0,
            "debt": 0.0
        }]

    def save_json(self, path: Path, data: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def calculate_total_equity(self) -> float:
        """Computes current portfolio Net Asset Value (NAV)."""
        stock_val = sum(p["units"] * p.get("current_px", p["entry_px"]) for p in self.state["positions"].values())
        gold_val = self.state["gold_units"] * self.state.get("gold_price", 60.0)
        return self.state["cash"] + stock_val + gold_val - self.state["borrowed_debt"]

    # =========================================================================
    # 1. INTRADAY CYCLE (Runs hourly during 9:15 AM - 3:30 PM IST)
    # =========================================================================
    def run_intraday_cycle(self):
        """
        Monitors open positions for the -12% Emergency Intraday GTT Circuit Guard.
        If a stock's intraday low breaches -12% from entry, triggers an immediate market exit!
        """
        logger.info("⚡ Running Intraday Market-Hours GTT Guard Monitoring Cycle...")
        positions = self.state["positions"]

        if not positions:
            logger.info("No active open positions. Intraday check complete in 0.1s.")
            self.state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
            self.state["last_mode"] = "INTRADAY (Idle)"
            self.save_json(STATE_FILE, self.state)
            self.generate_dashboard_html()
            return

        symbols = list(positions.keys())
        quotes = get_intraday_quotes(symbols)

        to_exit = []
        for sym, p in positions.items():
            q = quotes.get(sym)
            if not q:
                continue

            low_px = q["low"]
            curr_px = q["current"]
            p["current_px"] = curr_px
            p["unrealized_pnl"] = round((curr_px - p["entry_px"]) * p["units"], 2)
            p["unrealized_pct"] = round((curr_px / p["entry_px"] - 1.0) * 100, 2)

            # Check -12% Intraday GTT Circuit Guard
            gtt_stop_px = p["gtt_12_px"]
            if low_px <= gtt_stop_px:
                logger.warning(f"🚨 EMERGENCY GTT TRIGGERED: {sym} dropped to ₹{low_px:.2f} (<= ₹{gtt_stop_px:.2f})!")
                fill_px = gtt_stop_px * (1.0 - 0.005) # minor slippage
                net_proceeds = p["units"] * fill_px * (1.0 - TRANSACTION_FEE_BPS)
                pnl = net_proceeds - p["cost"]
                ret_pct = (fill_px / p["entry_px"] - 1.0) * 100

                # Pay down margin debt first
                if self.state["borrowed_debt"] > 0:
                    paydown = min(self.state["borrowed_debt"], net_proceeds)
                    self.state["borrowed_debt"] -= paydown
                    self.state["cash"] += (net_proceeds - paydown)
                else:
                    self.state["cash"] += net_proceeds

                self.trades.append({
                    "symbol": sym,
                    "entry_date": p["entry_date"],
                    "entry_px": p["entry_px"],
                    "exit_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "exit_px": round(fill_px, 2),
                    "units": p["units"],
                    "cost": p["cost"],
                    "net_proceeds": round(net_proceeds, 2),
                    "pnl": round(pnl, 2),
                    "ret_pct": round(ret_pct, 2),
                    "exit_type": "Intraday GTT Circuit Guard (-12%)",
                    "exit_explanation": f"Intraday low plunged to ₹{low_px:.2f}. Emergency GTT stop executed at ₹{fill_px:.2f} before lower-circuit lock."
                })
                to_exit.append(sym)

        for sym in to_exit:
            del positions[sym]

        self.state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        self.state["last_mode"] = f"INTRADAY ({len(positions)} active)"
        self.save_json(STATE_FILE, self.state)
        self.save_json(TRADES_FILE, self.trades)
        self.generate_dashboard_html()
        logger.info(f"Intraday check complete. {len(to_exit)} positions exited via GTT.")

    # =========================================================================
    # 2. END-OF-DAY CYCLE (Runs at 4:00 PM IST on weekdays)
    # =========================================================================
    def run_eod_cycle(self):
        """
        Executes daily market-close rebalancing:
        1. Evaluates broad market regime (Nifty/Smallcap 200 EMA)
        2. Evaluates daily exits (-8% close stop & 21 EMA trailing stop)
        3. Screens liquid universe for Stage 2 & 52W High breakouts
        4. Allocates to new candidates using Tiered Conviction Sizing
        5. Deducts daily margin interest and updates equity curve
        """
        logger.info("🌙 Running End-of-Day (EOD) Market-Close Rebalancing Cycle...")
        today_str = datetime.now().strftime("%Y-%m-%d")

        # 1. Market Regime Check
        regime_info = get_market_regime()
        regime = regime_info["regime"]
        self.state["current_regime"] = regime
        benchmark_ret63 = regime_info.get("ret63", 0.0)

        # If Regime is BEAR (Red): Liquidate all equities and park in Gold BeES
        if regime == "BEAR":
            logger.warning("Market Regime is BEAR (Close < 200 EMA). Liquidating equities to Gold BeES.")
            self.liquidate_all_positions(reason="Regime Red Bear Market Exit (Index < 200 EMA)")
            self.park_cash_in_gold()
            self.finalize_eod_cycle(today_str)
            return

        # If parked in Gold BeES during a previous bear regime and now GREEN:
        if self.state["gold_units"] > 0 and regime in ["BULL", "NEUTRAL"]:
            gold_p = get_proxy_price(CASH_PROXY)
            gold_val = self.state["gold_units"] * gold_p["open"] * (1.0 - TRANSACTION_FEE_BPS)
            self.state["cash"] += gold_val
            self.state["gold_units"] = 0.0
            logger.info(f"Liquidated Gold BeES back into cash: +₹{gold_val:,.2f}")

        # 2. Evaluate Exits for Open Positions
        positions = self.state["positions"]
        symbols = list(positions.keys())
        if symbols:
            quotes = get_intraday_quotes(symbols)
            to_exit = []

            for sym, p in positions.items():
                q = quotes.get(sym)
                if not q:
                    continue

                close_px = q["close"]
                p["current_px"] = close_px
                p["unrealized_pnl"] = round((close_px - p["entry_px"]) * p["units"], 2)
                p["unrealized_pct"] = round((close_px / p["entry_px"] - 1.0) * 100, 2)

                # Fetch updated 21 EMA from yfinance for trailing stop
                try:
                    df = yf.Ticker(f"{sym}.NS").history(period="3mo", interval="1d")
                    e21_val = float(df["Close"].ewm(span=EMA_TRAIL_SPAN, adjust=False).mean().iloc[-1])
                    p["current_e21"] = round(e21_val, 2)
                except Exception:
                    e21_val = p["entry_px"]

                hit_stop_8 = (close_px <= p["stop_8_px"])
                # 21 EMA Trail with 1.5% buffer rule (prevents TBZ-style premature shakeouts)
                hit_e21_trail = (close_px < e21_val * (1.0 - EMA_BUFFER_PCT))

                if hit_stop_8 or hit_e21_trail:
                    fill_px = close_px
                    exit_type = "Daily Close Stop (-8%)" if hit_stop_8 else "21 EMA Trailing Stop"
                    expl = f"Closed at ₹{close_px:.2f} below -8% boundary." if hit_stop_8 else f"Daily close ₹{close_px:.2f} breached 21 EMA (₹{e21_val:.2f}) with 1.5% buffer."

                    net_proceeds = p["units"] * fill_px * (1.0 - TRANSACTION_FEE_BPS)
                    pnl = net_proceeds - p["cost"]
                    ret_pct = (fill_px / p["entry_px"] - 1.0) * 100

                    if self.state["borrowed_debt"] > 0:
                        paydown = min(self.state["borrowed_debt"], net_proceeds)
                        self.state["borrowed_debt"] -= paydown
                        self.state["cash"] += (net_proceeds - paydown)
                    else:
                        self.state["cash"] += net_proceeds

                    self.trades.append({
                        "symbol": sym,
                        "entry_date": p["entry_date"],
                        "entry_px": p["entry_px"],
                        "exit_date": today_str,
                        "exit_px": round(fill_px, 2),
                        "units": p["units"],
                        "cost": p["cost"],
                        "net_proceeds": round(net_proceeds, 2),
                        "pnl": round(pnl, 2),
                        "ret_pct": round(ret_pct, 2),
                        "exit_type": exit_type,
                        "exit_explanation": expl
                    })
                    to_exit.append(sym)

            for sym in to_exit:
                del positions[sym]

        # 3. Screen Universe & Allocate New Entries
        cap = 5 if regime == "NEUTRAL" else MAX_POSITIONS
        open_slots = cap - len(positions)
        port_equity = self.calculate_total_equity()

        if open_slots > 0:
            universe_symbols = self.load_universe()
            candidates = scan_universe_for_setups(universe_symbols, benchmark_ret63)
            self.save_json(SCAN_RESULTS_FILE, candidates)

            # Filter out already held positions
            available_cands = [c for c in candidates if c["symbol"] not in positions][:open_slots]

            for rank_offset, cand in enumerate(available_cands):
                slot_idx = len(positions)
                target_w = TIER_WEIGHTS[min(9, slot_idx)]
                alloc_capital = port_equity * target_w * LEVERAGE
                fill_px = cand["close"] * (1.0 + SLIPPAGE_BPS)

                if fill_px > 0 and alloc_capital > 2_000:
                    units = int(alloc_capital / fill_px)
                    if units > 0:
                        actual_cost = units * fill_px
                        if LEVERAGE > 1.0 and self.state["cash"] < actual_cost:
                            debt_needed = actual_cost - max(0.0, self.state["cash"])
                            self.state["borrowed_debt"] += debt_needed
                            self.state["cash"] -= (actual_cost - debt_needed)
                        else:
                            self.state["cash"] -= actual_cost

                        tier_str = "Tier 1 (High Conviction)" if slot_idx < 2 else ("Tier 2 (Core Conviction)" if slot_idx < 5 else "Tier 3 (Satellite)")

                        positions[cand["symbol"]] = {
                            "symbol": cand["symbol"],
                            "entry_date": today_str,
                            "entry_px": round(fill_px, 2),
                            "current_px": round(cand["close"], 2),
                            "units": units,
                            "cost": round(actual_cost, 2),
                            "stop_8_px": round(fill_px * (1.0 + CLOSE_STOP_PCT), 2),
                            "gtt_12_px": round(fill_px * (1.0 + GTT_CIRCUIT_STOP_PCT), 2),
                            "current_e21": round(cand["e20"], 2), # proxy
                            "tier": tier_str,
                            "weight_pct": round(target_w * 100, 1),
                            "dist_52_pct": cand["dist_52_pct"],
                            "rs_alpha_pct": cand["rs_alpha_pct"],
                            "vol_ratio": cand["vol_ratio"]
                        }
                        logger.info(f"✅ BOUGHT {units} shs of {cand['symbol']} @ ₹{fill_px:.2f} ({tier_str}, Cost: ₹{actual_cost:,.2f})")

        self.finalize_eod_cycle(today_str)

    def finalize_eod_cycle(self, today_str: str):
        # Deduct daily margin interest
        if self.state["borrowed_debt"] > 0:
            daily_interest = self.state["borrowed_debt"] * DAILY_INTEREST_RATE
            self.state["cash"] -= daily_interest
            self.state["total_interest_paid"] += daily_interest

        total_nav = self.calculate_total_equity()
        stock_val = sum(p["units"] * p.get("current_px", p["entry_px"]) for p in self.state["positions"].values())

        # Update equity history
        if not self.equity_history or self.equity_history[-1]["date"] != today_str:
            self.equity_history.append({
                "date": today_str,
                "equity": round(total_nav, 2),
                "cash": round(self.state["cash"], 2),
                "stock_value": round(stock_val, 2),
                "debt": round(self.state["borrowed_debt"], 2)
            })
        else:
            self.equity_history[-1] = {
                "date": today_str,
                "equity": round(total_nav, 2),
                "cash": round(self.state["cash"], 2),
                "stock_value": round(stock_val, 2),
                "debt": round(self.state["borrowed_debt"], 2)
            }

        self.state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        self.state["last_mode"] = "EOD (Rebalanced)"
        self.save_json(STATE_FILE, self.state)
        self.save_json(TRADES_FILE, self.trades)
        self.save_json(EQUITY_FILE, self.equity_history)
        self.generate_dashboard_html()
        logger.info(f"EOD Cycle complete. NAV: ₹{total_nav:,.2f} | Open Positions: {len(self.state['positions'])}")

    def liquidate_all_positions(self, reason: str):
        today_str = datetime.now().strftime("%Y-%m-%d")
        for sym, p in list(self.state["positions"].items()):
            fill_px = p.get("current_px", p["entry_px"])
            net_proceeds = p["units"] * fill_px * (1.0 - TRANSACTION_FEE_BPS)
            pnl = net_proceeds - p["cost"]
            ret_pct = (fill_px / p["entry_px"] - 1.0) * 100

            if self.state["borrowed_debt"] > 0:
                paydown = min(self.state["borrowed_debt"], net_proceeds)
                self.state["borrowed_debt"] -= paydown
                self.state["cash"] += (net_proceeds - paydown)
            else:
                self.state["cash"] += net_proceeds

            self.trades.append({
                "symbol": sym,
                "entry_date": p["entry_date"],
                "entry_px": p["entry_px"],
                "exit_date": today_str,
                "exit_px": round(fill_px, 2),
                "units": p["units"],
                "cost": p["cost"],
                "net_proceeds": round(net_proceeds, 2),
                "pnl": round(pnl, 2),
                "ret_pct": round(ret_pct, 2),
                "exit_type": "Emergency Liquidation",
                "exit_explanation": reason
            })
        self.state["positions"] = {}

    def park_cash_in_gold(self):
        gold_p = get_proxy_price(CASH_PROXY)
        px = gold_p["close"]
        if px > 0 and self.state["cash"] > 5_000:
            units = int((self.state["cash"] * (1.0 - TRANSACTION_FEE_BPS)) / px)
            if units > 0:
                self.state["gold_units"] = units
                self.state["gold_price"] = px
                self.state["cash"] -= (units * px)
                logger.info(f"Parked cash in {units} units of {CASH_PROXY} @ ₹{px:.2f}")

    def load_universe(self) -> List[str]:
        if UNIVERSE_FILE.exists():
            try:
                with open(UNIVERSE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return ["HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "TBZ", "WELCORP", "STLTECH", "CUPID"]

    # =========================================================================
    # 3. DIRECT VERCEL DASHBOARD GENERATOR (index.html)
    # =========================================================================
    def generate_dashboard_html(self):
        """Builds modern, responsive index.html for direct Vercel static deployment."""
        nav = self.calculate_total_equity()
        ret_pct = ((nav / INITIAL_CAPITAL) - 1.0) * 100
        pnl = nav - INITIAL_CAPITAL

        positions = list(self.state["positions"].values())
        trades_rev = list(reversed(self.trades))
        wins = [t for t in self.trades if t["pnl"] > 0]
        wr = (len(wins) / len(self.trades) * 100) if self.trades else 0.0

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Live Swing Momentum Forward Test • NSE Smallcaps</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {{
      --bg: #090d16;
      --card-bg: #121826;
      --card-border: #1f293d;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --green: #10b981;
      --green-bg: rgba(16, 185, 129, 0.12);
      --red: #ef4444;
      --red-bg: rgba(239, 68, 68, 0.12);
      --accent: #38bdf8;
      --orange: #f97316;
      --gold: #f59e0b;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    body {{ background: var(--bg); color: var(--text-main); padding: 24px; line-height: 1.5; }}
    .container {{ max-width: 1400px; margin: 0 auto; }}
    
    .header {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--card-border); margin-bottom: 24px; }}
    .title-box h1 {{ font-size: 26px; font-weight: 800; display: flex; align-items: center; gap: 10px; }}
    .badge {{ background: var(--green-bg); color: var(--green); border: 1px solid var(--green); padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .subtext {{ color: var(--text-muted); font-size: 13px; margin-top: 4px; }}

    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
    .kpi-card {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; padding: 18px; }}
    .kpi-lbl {{ font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; }}
    .kpi-val {{ font-size: 24px; font-weight: 800; margin-top: 4px; }}
    .kpi-sub {{ font-size: 12px; color: var(--text-muted); margin-top: 2px; }}
    .green {{ color: var(--green); }}
    .red {{ color: var(--red); }}
    .accent {{ color: var(--accent); }}

    .section-title {{ font-size: 18px; font-weight: 700; margin: 28px 0 14px 0; display: flex; justify-content: space-between; align-items: center; }}
    .card {{ background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 12px; overflow: hidden; margin-bottom: 24px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ background: #0c1220; color: var(--text-muted); font-weight: 600; text-align: left; padding: 12px 16px; border-bottom: 1px solid var(--card-border); text-transform: uppercase; font-size: 11px; }}
    td {{ padding: 12px 16px; border-bottom: 1px solid #162032; }}
    tr:last-child td {{ border-bottom: none; }}
    .symbol-cell {{ font-weight: 700; color: #fff; display: flex; align-items: center; gap: 8px; }}
    .tier-badge {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; background: #1e293b; color: #94a3b8; font-weight: 600; }}
    .tier-t1 {{ background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }}

    .chart-box {{ height: 320px; padding: 20px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="title-box">
        <h1>Autonomous Forward Testing Engine <span class="badge">LIVE SYSTEM</span></h1>
        <div class="subtext">Stage 2 Momentum + Dual-Stop Architecture (1.5x Leverage • NSE Smallcaps) | Mode: <strong>{self.state.get('last_mode')}</strong></div>
      </div>
      <div style="text-align: right;">
        <div style="font-size: 13px; font-weight: 600; color: var(--accent);">Last Update: {self.state.get('last_updated')}</div>
        <div style="font-size: 11px; color: var(--text-muted);">Auto-deployed via Vercel & GitHub Actions</div>
      </div>
    </div>

    <!-- KPIs -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-lbl">Current Portfolio Equity</div>
        <div class="kpi-val accent">₹ {nav:,.2f}</div>
        <div class="kpi-sub">Started at ₹ {INITIAL_CAPITAL:,.0f}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-lbl">Total Net Return</div>
        <div class="kpi-val {'green' if pnl >= 0 else 'red'}">{'+' if pnl >= 0 else ''}₹ {pnl:,.2f} ({ret_pct:+.2f}%)</div>
        <div class="kpi-sub">After all fees & margin interest</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-lbl">Market Regime Filter</div>
        <div class="kpi-val {'green' if self.state.get('current_regime') == 'BULL' else 'red'}">{self.state.get('current_regime')}</div>
        <div class="kpi-sub">Benchmark > 200 EMA</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-lbl">Active Positions & WR</div>
        <div class="kpi-val accent">{len(positions)} / {MAX_POSITIONS} <span style="font-size: 14px; font-weight: normal; color: var(--text-muted);">| {wr:.1f}% WR</span></div>
        <div class="kpi-sub">{len(self.trades)} Closed Trades</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-lbl">Cash & Borrowed Debt</div>
        <div class="kpi-val" style="font-size: 18px; margin-top: 8px;">₹ {self.state.get('cash', 0.0):,.0f} <span style="font-size: 12px; color: var(--red);">(-₹{self.state.get('borrowed_debt', 0.0):,.0f} MTF)</span></div>
        <div class="kpi-sub">Interest Paid: ₹ {self.state.get('total_interest_paid', 0.0):,.2f}</div>
      </div>
    </div>

    <!-- Equity Curve -->
    <div class="section-title">Forward-Test Equity Curve</div>
    <div class="card chart-box">
      <canvas id="equityChart"></canvas>
    </div>

    <!-- Open Positions -->
    <div class="section-title">
      Active Open Positions ({len(positions)})
      <span style="font-size: 12px; font-weight: normal; color: var(--text-muted);">Guarded by -12% Intraday GTT & 21 EMA Trailing Stop</span>
    </div>
    <div class="card">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Tier / Sizing</th>
            <th>Entry Date</th>
            <th>Buy Price</th>
            <th>Current Price</th>
            <th>Shares</th>
            <th>Position Cost</th>
            <th>-8% Close Stop</th>
            <th>-12% GTT Guard</th>
            <th>Unrealized P&L</th>
          </tr>
        </thead>
        <tbody>
          {"".join(f'''
          <tr>
            <td class="symbol-cell">{p["symbol"]}</td>
            <td><span class="tier-badge {"tier-t1" if "Tier 1" in p.get("tier","") else ""}">{p.get("tier","Tier 3").split()[0]} ({p.get("weight_pct", 6.2)}%)</span></td>
            <td>{p.get("entry_date")}</td>
            <td>₹ {p["entry_px"]:.2f}</td>
            <td><strong>₹ {p.get("current_px", p["entry_px"]):.2f}</strong></td>
            <td>{p["units"]}</td>
            <td>₹ {p["cost"]:,.2f}</td>
            <td style="color: var(--red);">₹ {p.get("stop_8_px", p["entry_px"]*0.92):.2f}</td>
            <td style="color: var(--orange); font-weight: 700;">₹ {p.get("gtt_12_px", p["entry_px"]*0.88):.2f}</td>
            <td class="{'green' if p.get('unrealized_pnl', 0) >= 0 else 'red'}" style="font-weight: 700;">
              {'+' if p.get('unrealized_pnl', 0) >= 0 else ''}₹ {p.get('unrealized_pnl', 0):,.2f} ({p.get('unrealized_pct', 0):+.2f}%)
            </td>
          </tr>
          ''' for p in positions) if positions else '<tr><td colspan="10" style="text-align:center; padding: 24px; color: var(--text-muted);">No open positions currently active. Scanner active at EOD.</td></tr>'}
        </tbody>
      </table>
    </div>

    <!-- Closed Trades -->
    <div class="section-title">Closed Trade History ({len(self.trades)})</div>
    <div class="card">
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Entry Date</th>
            <th>Buy Price</th>
            <th>Exit Date</th>
            <th>Sell Price</th>
            <th>Shares</th>
            <th>Net P&L</th>
            <th>Return</th>
            <th>Exit Mechanism</th>
          </tr>
        </thead>
        <tbody>
          {"".join(f'''
          <tr>
            <td class="symbol-cell">{t["symbol"]}</td>
            <td>{t["entry_date"]}</td>
            <td>₹ {t["entry_px"]:.2f}</td>
            <td>{t["exit_date"]}</td>
            <td>₹ {t["exit_px"]:.2f}</td>
            <td>{t["units"]}</td>
            <td class="{'green' if t['pnl'] >= 0 else 'red'}" style="font-weight: 700;">{'+' if t['pnl'] >= 0 else ''}₹ {t['pnl']:,.2f}</td>
            <td class="{'green' if t['ret_pct'] >= 0 else 'red'}" style="font-weight: 700;">{t['ret_pct']:+.2f}%</td>
            <td><strong style="color: {'var(--orange)' if 'GTT' in t['exit_type'] else ('var(--red)' if 'Stop' in t['exit_type'] else 'var(--green)')};">{t['exit_type']}</strong></td>
          </tr>
          ''' for t in trades_rev[:20]) if self.trades else '<tr><td colspan="9" style="text-align:center; padding: 20px; color: var(--text-muted);">No closed trades yet in forward-test sequence.</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>

  <script>
    const eqData = {json.dumps(self.equity_history)};
    const ctx = document.getElementById('equityChart').getContext('2d');
    new Chart(ctx, {{
      type: 'line',
      data: {{
        labels: eqData.map(x => x.date),
        datasets: [{{
          label: 'Portfolio Equity (₹)',
          data: eqData.map(x => x.equity),
          borderColor: '#38bdf8',
          backgroundColor: 'rgba(56, 189, 248, 0.08)',
          borderWidth: 2.5,
          fill: true,
          tension: 0.1
        }}]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        scales: {{
          x: {{ grid: {{ color: '#1e293b' }}, ticks: {{ color: '#64748b' }} }},
          y: {{ grid: {{ color: '#1e293b' }}, ticks: {{ color: '#94a3b8' }} }}
        }}
      }}
    }});
  </script>
</body>
</html>
"""
        with open(DASHBOARD_FILE, "w") as f:
            f.write(html)
        logger.info(f"Updated Vercel static dashboard: {DASHBOARD_FILE}")
