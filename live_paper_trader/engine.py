"""
live_paper_trader.engine
========================
Autonomous Paper Trading Engine for Indian Equities.
Simultaneously tracks and forward-tests 4 Portfolio Architectures:
1. Tiered 7-Slot • 1.0x Pure Cash (No Margin Debt, Pure Defense)
2. Tiered 7-Slot • 1.5x MTF Champion (The Verified Multi-Decade Sweet Spot)
3. Tiered 7-Slot • 2.0x MTF Alpha (High Growth MTF Purchasing Power)
4. Tiered 10-Slot • 1.5x MTF Control (Original 10-Slot Baseline Control)

Features:
- Hourly Intraday GTT -12% Circuit Guard Monitoring
- End-of-Day (4:00 PM IST) Screening, Rebalancing & Stop Evaluation
- Unified Vercel Static HTML Dashboard with Real-Time Portfolio Tab Switcher
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Set

import pandas as pd
import numpy as np
import yfinance as yf

from live_paper_trader.config import (
    PORTFOLIOS,
    REPORTS_DIR,
    STATE_FILE,
    TRADES_FILE,
    EQUITY_FILE,
    SCAN_RESULTS_FILE,
    DASHBOARD_FILE,
    UNIVERSE_FILE,
    INITIAL_CAPITAL,
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
from live_paper_trader.notifier import PaperTradingNotifier

logger = logging.getLogger("live_paper_trader.engine")


class PaperTradingEngine:
    def __init__(self):
        self.portfolios = PORTFOLIOS
        self.states: Dict[str, Dict[str, Any]] = {}
        self.trades: Dict[str, List[Dict[str, Any]]] = {}
        self.equity_histories: Dict[str, List[Dict[str, Any]]] = {}
        self.notifier = PaperTradingNotifier()

        for p_id, p_cfg in self.portfolios.items():
            self.states[p_id] = self.load_portfolio_state(p_id, p_cfg)
            self.trades[p_id] = self.load_portfolio_trades(p_id)
            self.equity_histories[p_id] = self.load_portfolio_equity(p_id, p_cfg)

        # Legacy backward-compatibility aliases pointing to Champion portfolio
        self.state = self.states["tiered_7_1_5x"]
        self.trade_list = self.trades["tiered_7_1_5x"]

    # =========================================================================
    # PERSISTENCE HELPERS
    # =========================================================================
    def get_state_path(self, p_id: str) -> Path:
        return REPORTS_DIR / f"state_{p_id}.json"

    def get_trades_path(self, p_id: str) -> Path:
        return REPORTS_DIR / f"trades_{p_id}.json"

    def get_equity_path(self, p_id: str) -> Path:
        return REPORTS_DIR / f"equity_{p_id}.json"

    def load_portfolio_state(self, p_id: str, p_cfg: Dict[str, Any]) -> Dict[str, Any]:
        path = self.get_state_path(p_id)
        if path.exists():
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read {path}, initializing fresh: {e}")

        # Check legacy state file for migration
        if p_id == "tiered_7_1_5x" and STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                    self.save_json(path, data)
                    return data
            except Exception:
                pass

        init_capital = p_cfg.get("initial_capital", INITIAL_CAPITAL)
        state = {
            "portfolio_id": p_id,
            "portfolio_name": p_cfg["name"],
            "leverage": p_cfg["leverage"],
            "slots": p_cfg["slots"],
            "initial_capital": init_capital,
            "cash": init_capital,
            "borrowed_debt": 0.0,
            "gold_units": 0,
            "positions": {},
            "total_interest_paid": 0.0,
            "current_regime": "BULL",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "last_mode": "INIT",
            "gold_price": 117.30
        }
        self.save_json(path, state)
        return state

    def load_portfolio_trades(self, p_id: str) -> List[Dict[str, Any]]:
        path = self.get_trades_path(p_id)
        if path.exists():
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def load_portfolio_equity(self, p_id: str, p_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        path = self.get_equity_path(p_id)
        if path.exists():
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        today_str = datetime.now().strftime("%Y-%m-%d")
        init_capital = p_cfg.get("initial_capital", INITIAL_CAPITAL)
        return [{
            "date": today_str,
            "equity": init_capital,
            "cash": init_capital,
            "stock_value": 0.0,
            "gold_value": 0.0,
            "debt": 0.0
        }]

    def save_json(self, path: Path, data: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def calculate_portfolio_equity(self, p_id: str) -> float:
        st = self.states[p_id]
        stock_val = sum(p["units"] * p.get("current_px", p["entry_px"]) for p in st["positions"].values())
        gold_val = st["gold_units"] * st.get("gold_price", 117.30)
        return st["cash"] + stock_val + gold_val - st["borrowed_debt"]

    def calculate_total_equity(self) -> float:
        """Alias for Champion portfolio equity."""
        return self.calculate_portfolio_equity("tiered_7_1_5x")

    # =========================================================================
    # 1. INTRADAY CYCLE (Hourly Check during Market Hours 9:15 AM - 3:30 PM IST)
    # =========================================================================
    def run_intraday_cycle(self):
        """
        Monitors open positions across all 4 portfolios for -12% Emergency Intraday GTT Guard.
        """
        logger.info("⚡ Running Hourly Intraday Market-Hours GTT Circuit Guard Check (6 Portfolios)...")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

        # Collect unique open symbols across all portfolios
        all_symbols: Set[str] = set()
        for p_id, st in self.states.items():
            for sym in st["positions"].keys():
                all_symbols.add(sym)

        if not all_symbols:
            logger.info("No active open positions across all 4 portfolios. Intraday check complete in 0.1s.")
            for p_id, st in self.states.items():
                st["last_updated"] = now_str
                st["last_mode"] = "INTRADAY (Idle)"
                self.save_json(self.get_state_path(p_id), st)
            self.generate_dashboard_html()
            return

        # Fetch quotes once for all symbols
        quotes = get_intraday_quotes(list(all_symbols))

        for p_id, st in self.states.items():
            positions = st["positions"]
            to_exit = []

            for sym, p in positions.items():
                q = quotes.get(sym)
                if not q:
                    continue

                curr_px = q["current"]
                p["current_px"] = round(curr_px, 2)
                p["unrealized_pnl"] = round((curr_px - p["entry_px"]) * p["units"], 2)
                p["unrealized_pct"] = round((curr_px / p["entry_px"] - 1.0) * 100.0, 2)

                # Check -12% Intraday GTT trigger
                low_px = q["low"]
                gtt_trigger_px = p["entry_px"] * (1.0 + GTT_CIRCUIT_STOP_PCT)

                if low_px <= gtt_trigger_px:
                    fill_px = round(gtt_trigger_px, 2)
                    logger.warning(
                        f"🚨 [{st['portfolio_name']}] GTT CIRCUIT GUARD TRIGGERED on {sym}! "
                        f"Low: ₹{low_px:.2f} <= ₹{gtt_trigger_px:.2f}. Market Exit Executed."
                    )
                    gross = fill_px * p["units"]
                    fee = gross * TRANSACTION_FEE_BPS
                    net = gross - fee
                    pnl = net - p["cost"]
                    ret_pct = (fill_px / p["entry_px"] - 1.0) * 100.0

                    if st["borrowed_debt"] > 0:
                        paydown = min(st["borrowed_debt"], net)
                        st["borrowed_debt"] -= paydown
                        st["cash"] += (net - paydown)
                    else:
                        st["cash"] += net

                    trade_rec = {
                        "id": len(self.trades[p_id]) + 1,
                        "symbol": sym,
                        "entry_date": p["entry_date"],
                        "entry_px": p["entry_px"],
                        "exit_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "exit_px": fill_px,
                        "units": p["units"],
                        "cost": p["cost"],
                        "net_proceeds": round(net, 2),
                        "pnl": round(pnl, 2),
                        "ret_pct": round(ret_pct, 2),
                        "exit_type": "Emergency GTT Circuit Guard (-12%)",
                        "tier": p.get("tier", "Tier 2")
                    }
                    self.trades[p_id].append(trade_rec)
                    to_exit.append(sym)
                    self.notifier.send_trade_alert(
                        market="INDIA",
                        action="SELL",
                        symbol=sym,
                        price=fill_px,
                        shares=p["units"],
                        value=net,
                        ret_pct=ret_pct,
                        pnl=pnl,
                        reason="Emergency GTT Circuit Guard (-12%)"
                    )

            for sym in to_exit:
                del positions[sym]

            st["last_updated"] = now_str
            st["last_mode"] = "INTRADAY (Checked)"
            self.save_json(self.get_state_path(p_id), st)
            self.save_json(self.get_trades_path(p_id), self.trades[p_id])

        self.generate_dashboard_html()
        logger.info("Hourly Intraday GTT Guard check finished successfully.")

    # =========================================================================
    # 2. END-OF-DAY CYCLE (4:00 PM IST Screening, Stop Check & Rebalance)
    # =========================================================================
    def run_eod_cycle(self):
        """
        Runs the daily close routine across all 4 portfolios:
        - Accrues MTF margin interest
        - Evaluates routine -8% daily close stops & 21 EMA trailing stops
        - Executes macro regime checks and GOLDBEES parking/liquidation
        - Screens 700+ liquid Indian universe for Stage 2 breakouts
        - Sizes and enters new setups per portfolio configuration
        """
        logger.info("🌙 Running End-of-Day (EOD) Screening & Rebalance Cycle (6 Portfolios)...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

        # 1. Broad Market Regime
        regime_info = get_market_regime()
        market_regime = regime_info["regime"]
        logger.info(f"Broad Market Regime: {market_regime} (Nifty: ₹{regime_info['close']:,.1f}, 200 EMA: ₹{regime_info['ema200']:,.1f})")

        # 2. Gold Price for Cash Parking
        gold_quote = get_proxy_price(CASH_PROXY)
        gold_close = gold_quote["close"]

        # Collect open symbols across all portfolios for daily close updates
        all_symbols: Set[str] = set()
        for p_id, st in self.states.items():
            for sym in st["positions"].keys():
                all_symbols.add(sym)

        quotes = get_intraday_quotes(list(all_symbols)) if all_symbols else {}

        # 3. Process Exits & Regime Hedging per Portfolio
        for p_id, st in self.states.items():
            st["current_regime"] = market_regime
            st["gold_price"] = gold_close
            positions = st["positions"]

            # Accrue daily MTF debt interest
            if st["borrowed_debt"] > 0:
                daily_int = st["borrowed_debt"] * DAILY_INTEREST_RATE
                st["cash"] -= daily_int
                st["total_interest_paid"] += daily_int

            to_exit = []
            for sym, p in positions.items():
                q = quotes.get(sym)
                curr_px = q["close"] if q else p.get("current_px", p["entry_px"])
                p["current_px"] = round(curr_px, 2)
                p["unrealized_pnl"] = round((curr_px - p["entry_px"]) * p["units"], 2)
                p["unrealized_pct"] = round((curr_px / p["entry_px"] - 1.0) * 100.0, 2)

                # Stop conditions
                hit_stop_8 = curr_px <= p["stop_8_px"]
                hit_ema21 = False
                trail_ema = p.get("trail_ema21", 0.0)
                if trail_ema > 0 and curr_px < trail_ema * (1.0 - EMA_BUFFER_PCT):
                    hit_ema21 = True
                regime_forced_exit = (market_regime == "BEAR")

                if hit_stop_8 or hit_ema21 or regime_forced_exit:
                    fill_px = curr_px
                    exit_type = ""
                    if hit_stop_8:
                        fill_px = min(curr_px, p["entry_px"] * 0.90) # model slippage
                        exit_type = "Daily Close Stop (-8%)"
                    elif hit_ema21:
                        exit_type = "21 EMA Trailing Profit Stop"
                    elif regime_forced_exit:
                        exit_type = "Regime BEAR Liquidation (Nifty < 200 EMA)"

                    gross = fill_px * p["units"]
                    fee = gross * TRANSACTION_FEE_BPS
                    net = gross - fee
                    pnl = net - p["cost"]
                    ret_pct = (fill_px / p["entry_px"] - 1.0) * 100.0

                    if st["borrowed_debt"] > 0:
                        paydown = min(st["borrowed_debt"], net)
                        st["borrowed_debt"] -= paydown
                        st["cash"] += (net - paydown)
                    else:
                        st["cash"] += net

                    trade_rec = {
                        "id": len(self.trades[p_id]) + 1,
                        "symbol": sym,
                        "entry_date": p["entry_date"],
                        "entry_px": p["entry_px"],
                        "exit_date": today_str,
                        "exit_px": round(fill_px, 2),
                        "units": p["units"],
                        "cost": p["cost"],
                        "net_proceeds": round(net, 2),
                        "pnl": round(pnl, 2),
                        "ret_pct": round(ret_pct, 2),
                        "exit_type": exit_type,
                        "tier": p.get("tier", "Tier 2")
                    }
                    self.trades[p_id].append(trade_rec)
                    to_exit.append(sym)
                    self.notifier.send_trade_alert(
                        market="INDIA",
                        action="SELL",
                        symbol=sym,
                        price=fill_px,
                        shares=p["units"],
                        value=net,
                        ret_pct=ret_pct,
                        pnl=pnl,
                        reason="Emergency GTT Circuit Guard (-12%)"
                    )
                    logger.info(f"[{st['portfolio_name']}] Exited {sym} @ ₹{fill_px:.2f} ({exit_type}) | Net: ₹{pnl:+,.2f} ({ret_pct:+.2f}%)")

            for sym in to_exit:
                del positions[sym]

            # GOLDBEES Management
            if market_regime == "BEAR":
                # Park idle cash into Gold
                if st["cash"] > 2_000:
                    gold_units = int(st["cash"] / (gold_close * (1.0 + TRANSACTION_FEE_BPS)))
                    if gold_units > 0:
                        cost = gold_units * gold_close * (1.0 + TRANSACTION_FEE_BPS)
                        st["gold_units"] += gold_units
                        st["cash"] -= cost
                        logger.info(f"[{st['portfolio_name']}] Parked cash into {gold_units} units of GOLDBEES @ ₹{gold_close:.2f}")
            else:
                # BULL/NEUTRAL: Liquidate Gold to cash for equity breakout buying
                if st["gold_units"] > 0:
                    gross_gold = st["gold_units"] * gold_close
                    net_gold = gross_gold * (1.0 - TRANSACTION_FEE_BPS)
                    st["cash"] += net_gold
                    logger.info(f"[{st['portfolio_name']}] Liquidated {st['gold_units']} GOLDBEES units for ₹{net_gold:,.2f} to deploy into Equities")
                    st["gold_units"] = 0

        # 4. Scan Universe for Fresh Breakouts if Regime is BULL or NEUTRAL
        candidates = []
        if market_regime != "BEAR":
            universe = self.load_universe()
            candidates = scan_universe_for_setups(universe, regime_info["ret63"])
            self.save_json(SCAN_RESULTS_FILE, {
                "scan_time": now_str,
                "regime": market_regime,
                "candidates_count": len(candidates),
                "candidates": candidates
            })

            # Enter fresh positions per portfolio
            for p_id, st in self.states.items():
                p_cfg = self.portfolios[p_id]
                max_slots = p_cfg["slots"]
                tier_weights = p_cfg["weights"]
                leverage = p_cfg["leverage"]

                positions = st["positions"]
                open_slots = max(0, max_slots - len(positions))
                port_equity = self.calculate_portfolio_equity(p_id)

                available_cands = [c for c in candidates if c["symbol"] not in positions][:open_slots]

                for rank_offset, cand in enumerate(available_cands):
                    slot_idx = len(positions)
                    target_w = tier_weights[min(len(tier_weights) - 1, slot_idx)]
                    alloc_capital = port_equity * target_w * leverage
                    fill_px = cand["close"] * (1.0 + SLIPPAGE_BPS)

                    if fill_px > 0 and alloc_capital > 2_000:
                        units = int(alloc_capital / fill_px)
                        if units > 0:
                            actual_cost = units * fill_px
                            if leverage > 1.0 and st["cash"] < actual_cost:
                                debt_needed = actual_cost - max(0.0, st["cash"])
                                st["borrowed_debt"] += debt_needed
                                st["cash"] -= (actual_cost - debt_needed)
                            else:
                                st["cash"] -= actual_cost

                            tier_str = "Tier 1 (High Conviction)" if slot_idx < 2 else ("Tier 2 (Core Conviction)" if slot_idx < 4 else "Tier 3 (Satellite)")

                            positions[cand["symbol"]] = {
                                "symbol": cand["symbol"],
                                "entry_date": today_str,
                                "entry_px": round(fill_px, 2),
                                "current_px": round(cand["close"], 2),
                                "units": units,
                                "cost": round(actual_cost, 2),
                                "stop_8_px": round(fill_px * (1.0 + CLOSE_STOP_PCT), 2),
                                "gtt_12_px": round(fill_px * (1.0 + GTT_CIRCUIT_STOP_PCT), 2),
                                "trail_ema21": round(cand["e20"], 2),
                                "tier": tier_str,
                                "weight_pct": round(target_w * 100.0, 1),
                                "unrealized_pnl": 0.0,
                                "unrealized_pct": 0.0
                            }
                            logger.info(f"[{st['portfolio_name']}] ENTERED {cand['symbol']} @ ₹{fill_px:.2f} ({units} shares, ₹{actual_cost:,.2f}) [{tier_str}]")
                            self.notifier.send_trade_alert(
                                market="INDIA",
                                action="BUY",
                                symbol=cand["symbol"],
                                price=fill_px,
                                shares=units,
                                value=actual_cost,
                                reason=f"{st['portfolio_name']} • {tier_str}"
                            )

        # 5. Record Equity History and Save All States
        for p_id, st in self.states.items():
            curr_nav = self.calculate_portfolio_equity(p_id)
            stock_val = sum(p["units"] * p.get("current_px", p["entry_px"]) for p in st["positions"].values())
            gold_val = st["gold_units"] * gold_close

            # Update or append daily equity history
            eq_hist = self.equity_histories[p_id]
            if eq_hist and eq_hist[-1]["date"] == today_str:
                eq_hist[-1].update({
                    "equity": round(curr_nav, 2),
                    "cash": round(st["cash"], 2),
                    "stock_value": round(stock_val, 2),
                    "gold_value": round(gold_val, 2),
                    "debt": round(st["borrowed_debt"], 2)
                })
            else:
                eq_hist.append({
                    "date": today_str,
                    "equity": round(curr_nav, 2),
                    "cash": round(st["cash"], 2),
                    "stock_value": round(stock_val, 2),
                    "gold_value": round(gold_val, 2),
                    "debt": round(st["borrowed_debt"], 2)
                })

            st["last_updated"] = now_str
            st["last_mode"] = "EOD (Rebalanced)"
            self.save_json(self.get_state_path(p_id), st)
            self.save_json(self.get_trades_path(p_id), self.trades[p_id])
            self.save_json(self.get_equity_path(p_id), eq_hist)

        # Legacy backward-compatibility files pointing to Champion portfolio
        self.save_json(STATE_FILE, self.states["tiered_7_1_5x"])
        self.save_json(TRADES_FILE, self.trades["tiered_7_1_5x"])
        self.save_json(EQUITY_FILE, self.equity_histories["tiered_7_1_5x"])

        self.generate_dashboard_html()

        # Send daily EOD scorecard email across all 4 portfolios
        summary_payload = {}
        for p_id, p_cfg in self.portfolios.items():
            st = self.states[p_id]
            nav = self.calculate_portfolio_equity(p_id)
            init_cap = p_cfg.get("initial_capital", INITIAL_CAPITAL)
            pnl = nav - init_cap
            summary_payload[p_id] = {
                "name": p_cfg["name"],
                "color": p_cfg["color"],
                "slots": p_cfg["slots"],
                "nav": nav,
                "pnl": pnl,
                "ret_pct": (nav / init_cap - 1.0) * 100.0,
                "positions_count": len(st.get("positions", {})),
                "cash": st.get("cash", 0.0),
                "debt": st.get("borrowed_debt", 0.0),
                "gold_units": st.get("gold_units", 0),
                "gold_val": st.get("gold_units", 0) * st.get("gold_price", 117.30)
            }
        self.notifier.send_eod_multi_portfolio_summary(summary_payload, regime_info)

        logger.info("EOD screening & rebalance complete across all 4 portfolios.")

    def load_universe(self) -> List[str]:
        if UNIVERSE_FILE.exists():
            try:
                with open(UNIVERSE_FILE, "r") as f:
                    data = json.load(f)
                    return data.get("symbols", [])
            except Exception as e:
                logger.error(f"Failed to read universe file: {e}")
        return ["TBZ", "WELCORP", "CENTUM", "CUPID", "STLTECH", "BLISSGVS", "BOMDYEING", "SURAJEST", "KDDL"]

    # =========================================================================
    # 3. DIRECT VERCEL MULTI-PORTFOLIO DASHBOARD GENERATOR (index.html)
    # =========================================================================
    def generate_dashboard_html(self):
        """Builds modern, responsive multi-portfolio index.html for direct Vercel static deployment."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

        # Bundle full data for all 4 portfolios into a clean JSON structure
        bundle = {}
        for p_id, p_cfg in self.portfolios.items():
            st = self.states[p_id]
            nav = self.calculate_portfolio_equity(p_id)
            init_cap = p_cfg.get("initial_capital", INITIAL_CAPITAL)
            pnl = nav - init_cap
            ret_pct = ((nav / init_cap) - 1.0) * 100.0

            trades_rev = list(reversed(self.trades[p_id]))
            wins = [t for t in self.trades[p_id] if t["pnl"] > 0]
            wr = (len(wins) / len(self.trades[p_id]) * 100.0) if self.trades[p_id] else 0.0

            gold_units = st.get("gold_units", 0)
            gold_px = st.get("gold_price", 117.30)
            gold_val = gold_units * gold_px

            positions = list(st["positions"].values())

            bundle[p_id] = {
                "id": p_id,
                "name": p_cfg["name"],
                "short_name": p_cfg["short_name"],
                "badge": p_cfg["badge"],
                "description": p_cfg["description"],
                "color": p_cfg["color"],
                "slots": p_cfg["slots"],
                "leverage": p_cfg["leverage"],
                "initial_capital": init_cap,
                "nav": round(nav, 2),
                "pnl": round(pnl, 2),
                "ret_pct": round(ret_pct, 2),
                "cash": round(st.get("cash", 0.0), 2),
                "debt": round(st.get("borrowed_debt", 0.0), 2),
                "interest_paid": round(st.get("total_interest_paid", 0.0), 2),
                "gold_units": gold_units,
                "gold_price": round(gold_px, 2),
                "gold_val": round(gold_val, 2),
                "regime": st.get("current_regime", "BULL"),
                "positions_count": len(positions),
                "trades_count": len(self.trades[p_id]),
                "win_rate": round(wr, 1),
                "equity_history": self.equity_histories[p_id],
                "positions": positions,
                "trades": trades_rev[:30]
            }

        bundle_json = json.dumps(bundle)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Live Swing Momentum Forward Test • 6 Portfolios</title>
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
      --gold: #f59e0b;
      --purple: #a855f7;
      --orange: #f97316;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    body {{ background: var(--bg); color: var(--text-main); padding: 24px; line-height: 1.5; }}
    .container {{ max-width: 1440px; margin: 0 auto; }}
    
    .header {{ display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--card-border); margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }}
    .title-box h1 {{ font-size: 26px; font-weight: 800; display: flex; align-items: center; gap: 10px; }}
    .badge {{ background: var(--green-bg); color: var(--green); border: 1px solid var(--green); padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
    .subtext {{ color: var(--text-muted); font-size: 13px; margin-top: 4px; }}

    /* Portfolio Tabs */
    .portfolio-tabs {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-bottom: 24px; }}
    .tab-card {{ background: var(--card-bg); border: 2px solid var(--card-border); border-radius: 12px; padding: 16px; cursor: pointer; transition: all 0.2s ease; position: relative; }}
    .tab-card:hover {{ border-color: #3b82f6; transform: translateY(-2px); }}
    .tab-card.active {{ border-color: var(--accent); background: #162035; box-shadow: 0 4px 20px rgba(56, 189, 248, 0.15); }}
    .tab-badge {{ font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; display: inline-block; margin-bottom: 6px; }}
    .tab-name {{ font-size: 14px; font-weight: 700; color: #fff; }}
    .tab-nav {{ font-size: 22px; font-weight: 800; margin-top: 6px; }}
    .tab-ret {{ font-size: 12px; font-weight: 600; margin-top: 2px; }}

    /* KPIs */
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

    .chart-box {{ height: 340px; padding: 20px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="title-box">
        <h1>Autonomous Forward Testing Engine <span class="badge">6 PORTFOLIOS LIVE</span></h1>
        <div class="subtext">Stage 2 Momentum + Dual-Stop Architecture • 7-Slot vs 10-Slot Matrix (1.0x Cash, 1.5x MTF, 2.0x MTF)</div>
      </div>
      <div style="text-align: right;">
        <div style="font-size: 13px; font-weight: 600; color: var(--accent);">Last Update: {now_str}</div>
        <div style="font-size: 11px; color: var(--text-muted);">Auto-deployed via Vercel & GitHub Actions</div>
      </div>
    </div>

    <!-- 4 Portfolio Selector Cards -->
    <div class="portfolio-tabs" id="tabsContainer"></div>

    <!-- Active Portfolio Header Banner -->
    <div style="background: #111a2e; border: 1px solid #1e293b; border-radius: 10px; padding: 14px 20px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center;">
      <div>
        <span id="activeBadge" class="tab-badge" style="background: rgba(56, 189, 248, 0.2); color: #38bdf8;">👑 1.5x MTF Champion</span>
        <strong id="activeTitle" style="font-size: 16px; margin-left: 8px;">Tiered 7-Slot (1.5x MTF Champion)</strong>
        <div id="activeDesc" style="font-size: 12px; color: var(--text-muted); margin-top: 2px;">Optimal Kelly Growth • Sharpe 1.14 • ₹2.88 Cr 17.7Y Backtest</div>
      </div>
      <div style="font-size: 12px; color: var(--text-muted);">
        Slot Capacity: <strong id="activeSlots" style="color: #fff;">7 Stocks</strong> | Leverage: <strong id="activeLev" style="color: #fff;">1.5x MTF</strong>
      </div>
    </div>

    <!-- Dynamic KPIs -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-lbl">Current Portfolio Equity</div>
        <div class="kpi-val accent" id="kpiNav">₹ 100,000.00</div>
        <div class="kpi-sub">Started at ₹ 100,000</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-lbl">Total Net Return</div>
        <div class="kpi-val green" id="kpiPnl">+₹ 0.00 (+0.00%)</div>
        <div class="kpi-sub">After all fees & margin interest</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-lbl">Market Regime Filter</div>
        <div class="kpi-val" id="kpiRegime">BEAR</div>
        <div class="kpi-sub" id="kpiRegimeSub">Nifty 50 < 200 EMA (Capital in Gold)</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-lbl">Active Positions & WR</div>
        <div class="kpi-val accent" id="kpiPosCount">0 / 7 <span style="font-size: 14px; font-weight: normal; color: var(--text-muted);">| 0.0% WR</span></div>
        <div class="kpi-sub" id="kpiTradesCount">0 Closed Trades</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-lbl">Cash & Allocation</div>
        <div class="kpi-val" id="kpiCash" style="font-size: 18px; margin-top: 8px;">₹ 295</div>
        <div class="kpi-sub" id="kpiDebt">Debt: ₹ 0 | Margin Paid: ₹ 0.00</div>
      </div>
    </div>

    <!-- Comparative Equity Curve -->
    <div class="section-title">
      Comparative Forward-Test Equity Curves
      <span style="font-size: 12px; font-weight: normal; color: var(--text-muted);">All 6 Portfolios Tracked Side-by-Side</span>
    </div>
    <div class="card chart-box">
      <canvas id="equityChart"></canvas>
    </div>

    <!-- Active Open Positions -->
    <div class="section-title">
      Active Open Positions (<span id="tablePosCount">0</span>)
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
        <tbody id="openPositionsBody"></tbody>
      </table>
    </div>

    <!-- Closed Trades -->
    <div class="section-title">
      Closed Trade History (<span id="tableTradesCount">0</span>)
    </div>
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
        <tbody id="closedTradesBody"></tbody>
      </table>
    </div>
  </div>

  <script>
    const P_DATA = {bundle_json};
    let activePId = "tiered_7_1_5x";
    let chartInstance = null;

    function renderTabs() {{
      const container = document.getElementById("tabsContainer");
      container.innerHTML = "";
      for (const [id, p] of Object.entries(P_DATA)) {{
        const isAct = (id === activePId);
        const card = document.createElement("div");
        card.className = "tab-card " + (isAct ? "active" : "");
        card.onclick = () => switchPortfolio(id);
        const pnlCls = p.pnl >= 0 ? "green" : "red";
        card.innerHTML = `
          <div class="tab-badge" style="background: ${{p.color}}22; color: ${{p.color}}; border: 1px solid ${{p.color}}44;">${{p.badge}}</div>
          <div class="tab-name">${{p.short_name}}</div>
          <div class="tab-nav" style="color: ${{p.color}};">₹ ${{p.nav.toLocaleString('en-IN', {{minimumFractionDigits: 2}})}}</div>
          <div class="tab-ret ${{pnlCls}}">${{p.pnl >= 0 ? '+' : ''}}₹ ${{p.pnl.toLocaleString('en-IN')}} (${{p.ret_pct >= 0 ? '+' : ''}}${{p.ret_pct.toFixed(2)}}%)</div>
        `;
        container.appendChild(card);
      }}
    }}

    function switchPortfolio(id) {{
      activePId = id;
      renderTabs();
      updateView();
    }}

    function updateView() {{
      const p = P_DATA[activePId];
      if (!p) return;

      document.getElementById("activeBadge").innerText = p.badge;
      document.getElementById("activeBadge").style.color = p.color;
      document.getElementById("activeBadge").style.background = p.color + "22";
      document.getElementById("activeTitle").innerText = p.name;
      document.getElementById("activeDesc").innerText = p.description;
      document.getElementById("activeSlots").innerText = p.slots + " Stocks";
      document.getElementById("activeLev").innerText = p.leverage + "x MTF";

      document.getElementById("kpiNav").innerText = "₹ " + p.nav.toLocaleString('en-IN', {{minimumFractionDigits: 2}});
      const pnlSign = p.pnl >= 0 ? "+" : "";
      document.getElementById("kpiPnl").innerText = `${{pnlSign}}₹ ${{p.pnl.toLocaleString('en-IN', {{minimumFractionDigits: 2}})}} (${{pnlSign}}${{p.ret_pct.toFixed(2)}}%)`;
      document.getElementById("kpiPnl").className = "kpi-val " + (p.pnl >= 0 ? "green" : "red");

      const regEl = document.getElementById("kpiRegime");
      regEl.innerText = p.regime;
      regEl.className = "kpi-val " + (p.regime === "BULL" ? "green" : "red");
      document.getElementById("kpiRegimeSub").innerText = p.regime === "BULL" ? "Nifty 50 > 200 EMA (Equity Active)" : "Nifty 50 < 200 EMA (Capital in Gold)";

      document.getElementById("kpiPosCount").innerHTML = `${{p.positions_count}} / ${{p.slots}} <span style="font-size: 14px; font-weight: normal; color: var(--text-muted);">| ${{p.win_rate.toFixed(1)}}% WR</span>`;
      document.getElementById("kpiTradesCount").innerText = p.trades_count + " Closed Trades";

      let cashBadge = p.gold_units > 0 
        ? `<span style="font-size: 12px; color: var(--gold);">(+ ₹ ${{p.gold_val.toLocaleString('en-IN')}} Gold)</span>`
        : `<span style="font-size: 12px; color: var(--red);">(-₹${{p.debt.toLocaleString('en-IN')}} MTF)</span>`;
      document.getElementById("kpiCash").innerHTML = `₹ ${{p.cash.toLocaleString('en-IN')}} ` + cashBadge;
      document.getElementById("kpiDebt").innerText = `Debt: ₹ ${{p.debt.toLocaleString('en-IN')}} | Margin Paid: ₹ ${{p.interest_paid.toFixed(2)}}`;

      // Open Positions Table
      const posTbody = document.getElementById("openPositionsBody");
      let posRows = "";
      if (p.gold_units > 0) {{
        posRows += `
          <tr style="background: rgba(245, 158, 11, 0.05);">
            <td class="symbol-cell"><span style="color: var(--gold); font-size: 16px;">🛡️</span> GOLDBEES.NS <span class="badge" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid #f59e0b; font-size: 10px;">DEFENSIVE HEDGE</span></td>
            <td><span class="tier-badge" style="color: #fbbf24; background: rgba(245, 158, 11, 0.1);">100% Capital Hedge</span></td>
            <td>${{new Date().toISOString().split('T')[0]}}</td>
            <td>₹ ${{p.gold_price.toFixed(2)}}</td>
            <td><strong>₹ ${{p.gold_price.toFixed(2)}}</strong></td>
            <td>${{p.gold_units.toLocaleString('en-IN')}}</td>
            <td>₹ ${{p.gold_val.toLocaleString('en-IN', {{minimumFractionDigits: 2}})}}</td>
            <td style="color: var(--text-muted); font-size: 11px;">Macro Regime Exit</td>
            <td style="color: var(--text-muted); font-size: 11px;">N/A (Liquid ETF)</td>
            <td class="green" style="font-weight: 700;">₹ 0.00 (+0.00%)</td>
          </tr>
        `;
      }}
      for (const pos of p.positions) {{
        const unPnlCls = pos.unrealized_pnl >= 0 ? "green" : "red";
        posRows += `
          <tr>
            <td class="symbol-cell">${{pos.symbol}}</td>
            <td><span class="tier-badge ${{pos.tier.includes('Tier 1') ? 'tier-t1' : ''}}">${{pos.tier.split(' ')[0]}} (${{pos.weight_pct}}%)</span></td>
            <td>${{pos.entry_date}}</td>
            <td>₹ ${{pos.entry_px.toFixed(2)}}</td>
            <td><strong>₹ ${{pos.current_px.toFixed(2)}}</strong></td>
            <td>${{pos.units}}</td>
            <td>₹ ${{pos.cost.toLocaleString('en-IN', {{minimumFractionDigits: 2}})}}</td>
            <td style="color: var(--red);">₹ ${{pos.stop_8_px.toFixed(2)}}</td>
            <td style="color: var(--orange); font-weight: 700;">₹ ${{pos.gtt_12_px.toFixed(2)}}</td>
            <td class="${{unPnlCls}}" style="font-weight: 700;">
              ${{pos.unrealized_pnl >= 0 ? '+' : ''}}₹ ${{pos.unrealized_pnl.toLocaleString('en-IN', {{minimumFractionDigits: 2}})}} (${{pos.unrealized_pct >= 0 ? '+' : ''}}${{pos.unrealized_pct.toFixed(2)}}%)
            </td>
          </tr>
        `;
      }}
      posTbody.innerHTML = posRows || '<tr><td colspan="10" style="text-align:center; padding: 24px; color: var(--text-muted);">No open equity positions. Scanner active at 4:00 PM EOD.</td></tr>';
      document.getElementById("tablePosCount").innerText = p.positions.length + (p.gold_units > 0 ? 1 : 0);

      // Closed Trades Table
      const tradesTbody = document.getElementById("closedTradesBody");
      let tradeRows = "";
      for (const t of p.trades) {{
        const pnlCls = t.pnl >= 0 ? "green" : "red";
        tradeRows += `
          <tr>
            <td class="symbol-cell">${{t.symbol}}</td>
            <td>${{t.entry_date}}</td>
            <td>₹ ${{t.entry_px.toFixed(2)}}</td>
            <td>${{t.exit_date}}</td>
            <td>₹ ${{t.exit_px.toFixed(2)}}</td>
            <td>${{t.units}}</td>
            <td class="${{pnlCls}}" style="font-weight: 700;">${{t.pnl >= 0 ? '+' : ''}}₹ ${{t.pnl.toLocaleString('en-IN', {{minimumFractionDigits: 2}})}}</td>
            <td class="${{pnlCls}}" style="font-weight: 700;">${{t.ret_pct >= 0 ? '+' : ''}}${{t.ret_pct.toFixed(2)}}%</td>
            <td><strong>${{t.exit_type}}</strong></td>
          </tr>
        `;
      }}
      tradesTbody.innerHTML = tradeRows || '<tr><td colspan="9" style="text-align:center; padding: 20px; color: var(--text-muted);">No closed trades yet in forward test sequence.</td></tr>';
      document.getElementById("tableTradesCount").innerText = p.trades_count;

      updateChart();
    }}

    function updateChart() {{
      const ctx = document.getElementById('equityChart').getContext('2d');
      const allDates = Array.from(new Set(Object.values(P_DATA).flatMap(p => p.equity_history.map(x => x.date)))).sort();

      const datasets = Object.values(P_DATA).map(p => {{
        const map = new Map(p.equity_history.map(x => [x.date, x.equity]));
        const data = allDates.map(d => map.get(d) || null);
        const isAct = (p.id === activePId);
        return {{
          label: p.name,
          data: data,
          borderColor: p.color,
          backgroundColor: p.color + (isAct ? "15" : "00"),
          borderWidth: isAct ? 3 : 1.5,
          pointRadius: 2,
          fill: isAct,
          tension: 0.1
        }};
      }});

      if (chartInstance) {{
        chartInstance.destroy();
      }}

      chartInstance = new Chart(ctx, {{
        type: 'line',
        data: {{
          labels: allDates,
          datasets: datasets
        }},
        options: {{
          responsive: true,
          maintainAspectRatio: false,
          interaction: {{ mode: 'index', intersect: false }},
          plugins: {{
            legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }}
          }},
          scales: {{
            x: {{ grid: {{ color: '#1e293b' }}, ticks: {{ color: '#64748b' }} }},
            y: {{ grid: {{ color: '#1e293b' }}, ticks: {{ color: '#94a3b8' }} }}
          }}
        }}
      }});
    }}

    // Initialize
    renderTabs();
    updateView();
  </script>
</body>
</html>
"""
        with open(DASHBOARD_FILE, "w") as f:
            f.write(html)
        logger.info(f"Updated unified 6-portfolio Vercel dashboard: {DASHBOARD_FILE}")
