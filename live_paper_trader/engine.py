"""
live_paper_trader.engine
========================
Autonomous Paper Trading Engine supporting 4 parallel portfolios:
1. `india_broad`: All Indian stocks > ₹100 Cr market cap (~1,234 stocks)
2. `india_liquid`: Top 500 liquid Indian stocks (Nifty 500)
3. `usa_broad`: All INDmoney / Tickertape tradeable US stocks (~2,500 stocks)
4. `usa_liquid`: Top 500 liquid US stocks (S&P 500)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import yfinance as yf
import pandas as pd

from live_paper_trader.config import (
    INDIA_INITIAL_CAPITAL,
    INDIA_SLOTS,
    INDIA_CASH_PROXY,
    INDIA_INDEX_TICKER,
    INDIA_STOCK_FEE_BPS,
    INDIA_GOLD_FEE_BPS,
    INDIA_DEAD_MONEY_DAYS,
    INDIA_MONTHLY_EMA_SPAN,
    USA_INITIAL_CAPITAL,
    USA_SLOTS,
    USA_CASH_PROXY,
    USA_INDEX_TICKER,
    USA_STOCK_FEE_BPS,
    USA_ETF_FEE_BPS,
    USA_DEAD_MONEY_DAYS,
    USA_DEAD_MONEY_THRESH_PCT,
    USA_MONTHLY_EMA_SPAN,
    REGIME_EXPOSURE,
    STATE_INDIA_BROAD,
    STATE_INDIA_LIQUID,
    STATE_USA_BROAD,
    STATE_USA_LIQUID,
    UNIVERSE_INDIA_BROAD,
    UNIVERSE_INDIA_LIQUID,
    UNIVERSE_USA_BROAD,
    UNIVERSE_USA_LIQUID
)
from live_paper_trader.signals import (
    get_market_regime,
    get_proxy_price,
    scan_gfs_universe,
    check_stock_monthly_ema_status
)
from live_paper_trader.indicators import is_month_end_trading_day
from live_paper_trader.notifier import PaperTradingNotifier

logger = logging.getLogger("live_paper_trader.engine")

class PaperTradingEngine:
    def __init__(self, portfolio_id: str = "india_broad"):
        self.portfolio_id = portfolio_id.lower()
        self.notifier = PaperTradingNotifier()

        if "india" in self.portfolio_id:
            self.market = "india"
            self.currency = "INR"
            self.symbol_prefix = "₹"
            self.initial_capital = INDIA_INITIAL_CAPITAL
            self.slots = INDIA_SLOTS
            self.proxy_symbol = INDIA_CASH_PROXY
            self.index_symbol = INDIA_INDEX_TICKER
            self.stock_fee = INDIA_STOCK_FEE_BPS / 10000.0
            self.proxy_fee = INDIA_GOLD_FEE_BPS / 10000.0
            self.dead_money_days = INDIA_DEAD_MONEY_DAYS
            self.dead_money_thresh = 3.0
            self.monthly_ema_span = INDIA_MONTHLY_EMA_SPAN

            if "liquid" in self.portfolio_id:
                self.universe_file = UNIVERSE_INDIA_LIQUID
                self.state_file = STATE_INDIA_LIQUID
                self.label = "INDIA (Liquid 500)"
            else:
                self.universe_file = UNIVERSE_INDIA_BROAD
                self.state_file = STATE_INDIA_BROAD
                self.label = "INDIA (All Stocks > ₹100Cr)"
        else:
            self.market = "usa"
            self.currency = "USD"
            self.symbol_prefix = "$"
            self.initial_capital = USA_INITIAL_CAPITAL
            self.slots = USA_SLOTS
            self.proxy_symbol = USA_CASH_PROXY
            self.index_symbol = USA_INDEX_TICKER
            self.stock_fee = USA_STOCK_FEE_BPS / 10000.0
            self.proxy_fee = USA_ETF_FEE_BPS / 10000.0
            self.dead_money_days = USA_DEAD_MONEY_DAYS
            self.dead_money_thresh = USA_DEAD_MONEY_THRESH_PCT
            self.monthly_ema_span = USA_MONTHLY_EMA_SPAN

            if "liquid" in self.portfolio_id:
                self.universe_file = UNIVERSE_USA_LIQUID
                self.state_file = STATE_USA_LIQUID
                self.label = "USA (Liquid S&P 500)"
            else:
                self.universe_file = UNIVERSE_USA_BROAD
                self.state_file = STATE_USA_BROAD
                self.label = "USA (INDmoney / Tickertape Broad)"

        self.state = self._load_or_initialize_state()

    def _load_or_initialize_state(self) -> Dict[str, Any]:
        """Loads state from JSON or initializes fresh portfolio parked in cash/proxy ETF."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    state = json.load(f)
                logger.info(f"Loaded existing portfolio state for {self.label} from {self.state_file}")
                return state
            except Exception as e:
                logger.error(f"Error reading state file {self.state_file}: {e}. Reinitializing.")

        p_data = get_proxy_price(self.proxy_symbol)
        p_price = p_data.get("close", 100.0)
        p_entry = p_price * (1.0 + self.proxy_fee)
        proxy_units = self.initial_capital / p_entry
        today_str = datetime.now().strftime("%Y-%m-%d")

        state = {
            "portfolio_id": self.portfolio_id,
            "label": self.label,
            "market": self.market.upper(),
            "currency": self.currency,
            "created_date": today_str,
            "last_updated": today_str,
            "initial_capital": self.initial_capital,
            "cash": 0.0,
            "proxy_symbol": self.proxy_symbol,
            "proxy_units": proxy_units,
            "proxy_last_price": p_price,
            "proxy_val": proxy_units * p_price,
            "stock_invested": 0.0,
            "total_equity": self.initial_capital,
            "positions": {},
            "closed_trades": [],
            "daily_equity_history": [
                {
                    "date": today_str,
                    "total_equity": self.initial_capital,
                    "cash": 0.0,
                    "proxy_val": self.initial_capital,
                    "stock_val": 0.0,
                    "positions_count": 0
                }
            ]
        }
        self._save_state(state)
        logger.info(f"Initialized fresh paper portfolio for {self.label} with {self.symbol_prefix}{self.initial_capital:,.2f} in {self.proxy_symbol}")
        return state

    def _save_state(self, state: Optional[Dict[str, Any]] = None):
        """Persists state to disk."""
        if state is None:
            state = self.state
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)
        logger.info(f"Saved state for {self.label} to {self.state_file}")

    def run_daily_cycle(self, force_monthly_report: bool = False):
        """Executes daily paper trading cycle."""
        today_ts = pd.Timestamp.now()
        today_str = today_ts.strftime("%Y-%m-%d")
        print(f"\n=======================================================")
        print(f"🚀 EXECUTING GFS PAPER TRADING CYCLE: {self.label} ({today_str})")
        print(f"=======================================================")

        # 1. Fetch Proxy Price
        p_data = get_proxy_price(self.proxy_symbol)
        p_op = p_data.get("open", self.state.get("proxy_last_price", 100.0))
        p_cp = p_data.get("close", p_op)
        self.state["proxy_last_price"] = p_cp

        # 2. Mark to Market Open Positions & Check Exits
        is_month_end = is_month_end_trading_day(today_ts)
        positions = self.state.get("positions", {})
        to_close = []

        print(f"Checking {len(positions)} active open position(s)...")
        for sym, pos in list(positions.items()):
            try:
                stock_t = yf.Ticker(sym)
                df_hist = stock_t.history(period="5d", interval="1d")
                if df_hist.empty:
                    continue
                last_row = df_hist.iloc[-1]
                op = float(last_row["Open"])
                cp = float(last_row["Close"])
                pos["last_price"] = cp
                pos["holding_days"] += 1
                
                sim_entry = pos["sim_entry_price"]
                unrealized_pnl = pos["shares"] * (cp - sim_entry)
                unrealized_ret = (cp - sim_entry) / sim_entry * 100.0
                pos["unrealized_pnl"] = unrealized_pnl
                pos["unrealized_return_pct"] = unrealized_ret

                should_exit = False
                exit_reason = ""

                # Month-End Check
                if is_month_end or pos.get("pending_exit"):
                    m_stat = check_stock_monthly_ema_status(sym, monthly_ema_span=self.monthly_ema_span)
                    if m_stat.get("should_exit"):
                        should_exit = True
                        exit_reason = f"MONTHLY_EMA{self.monthly_ema_span}_BREAK"

                # US Dead-Money Eviction Rule
                if self.dead_money_days > 0 and pos["holding_days"] >= self.dead_money_days and unrealized_ret < self.dead_money_thresh:
                    should_exit = True
                    exit_reason = f"DEAD_MONEY_EVICTION_({self.dead_money_days}D_<_{self.dead_money_thresh}%)"

                if should_exit:
                    to_close.append((sym, op, cp, exit_reason))
            except Exception as e:
                logger.error(f"Error updating position {sym}: {e}")

        # Execute Exits
        for sym, op, cp, reason in to_close:
            pos = positions[sym]
            exit_price = cp * (1.0 - self.stock_fee)
            trade_pnl = pos["shares"] * (exit_price - pos["sim_entry_price"])
            trade_ret = (exit_price - pos["sim_entry_price"]) / pos["sim_entry_price"] * 100.0
            proceeds = pos["shares"] * exit_price

            # Reinvest proceeds into Proxy ETF
            proxy_buy_price = p_cp * (1.0 + self.proxy_fee)
            add_proxy_units = proceeds / proxy_buy_price
            self.state["proxy_units"] += add_proxy_units

            closed_record = {
                "symbol": sym,
                "entry_date": pos["entry_date"],
                "exit_date": today_str,
                "entry_price": pos["sim_entry_price"],
                "exit_price": exit_price,
                "shares": pos["shares"],
                "pnl": trade_pnl,
                "return_pct": trade_ret,
                "holding_days": pos["holding_days"],
                "exit_reason": reason
            }
            self.state["closed_trades"].append(closed_record)
            del positions[sym]

            print(f"  ❌ CLOSED POSITION: {sym} | PnL: {self.symbol_prefix}{trade_pnl:+,.2f} ({trade_ret:+.2f}%) | Reason: {reason}")
            
            self.notifier.send_trade_alert(
                market=f"{self.market.upper()}_{self.portfolio_id.split('_')[1].upper()}",
                action="EVICT" if "DEAD_MONEY" in reason else "SELL",
                symbol=sym,
                price=exit_price,
                shares=pos["shares"],
                value=proceeds,
                ret_pct=trade_ret,
                pnl=trade_pnl,
                reason=reason,
                holding_days=pos["holding_days"]
            )

        # 3. Portfolio Mark-to-Market
        stock_invested = sum(p["shares"] * p["last_price"] for p in positions.values())
        proxy_val = self.state["proxy_units"] * p_cp
        total_equity = self.state["cash"] + proxy_val + stock_invested

        # 4. Check Market Regime and New Entries
        regime_info = get_market_regime(self.index_symbol)
        regime = regime_info.get("regime", "NEUTRAL")
        regime_factor = REGIME_EXPOSURE.get(regime, 1.0)
        max_allowed_positions = max(1, int(round(self.slots * regime_factor)))
        max_allowed_stock_equity = total_equity * regime_factor

        avail_slots = max_allowed_positions - len(positions)
        print(f"Regime: {regime} (Exposure: {regime_factor*100:.0f}%, Max Slots: {max_allowed_positions}, Open: {len(positions)}, Avail: {avail_slots})")

        avail_liquid_funds = self.state["proxy_units"] * p_cp * (1.0 - self.proxy_fee)

        if avail_slots > 0 and stock_invested < max_allowed_stock_equity and avail_liquid_funds > (total_equity * 0.05):
            with open(self.universe_file, "r") as uf:
                universe = json.load(uf)

            universe_cands = [s for s in universe if s not in positions and f"{s}.NS" not in positions]
            
            # Scan top 150 tickers in this universe
            signals = scan_gfs_universe(universe_cands, market=self.market, max_scan=150)

            # Filter out overextended stocks (> 50% above monthly EMA)
            filtered_signals = []
            for s in signals:
                m_close = s.get("monthly_close", 0.0)
                m_ema = s.get("monthly_ema", 0.0)
                if m_ema > 0:
                    dist_pct = (m_close - m_ema) / m_ema * 100.0
                    if dist_pct > 50.0:
                        print(f"  ⏭️ Disqualified overextended candidate: {s['symbol']} (+{dist_pct:.1f}% above Monthly EMA)")
                        continue
                filtered_signals.append(s)

            alloc_per_slot = total_equity / self.slots
            for cand in filtered_signals[:avail_slots]:
                s_sym = cand["symbol"]
                curr_price = cand["close"]
                sim_entry_p = curr_price * (1.0 + self.stock_fee)
                
                req_alloc = min(avail_liquid_funds, alloc_per_slot)
                if req_alloc < (total_equity * 0.05):
                    break

                proxy_sell_price = p_cp * (1.0 - self.proxy_fee)
                units_to_sell = req_alloc / proxy_sell_price
                if units_to_sell > self.state["proxy_units"]:
                    units_to_sell = self.state["proxy_units"]
                    req_alloc = units_to_sell * proxy_sell_price

                self.state["proxy_units"] -= units_to_sell
                avail_liquid_funds -= req_alloc

                shares = req_alloc / sim_entry_p
                stock_invested += req_alloc

                positions[s_sym] = {
                    "symbol": s_sym,
                    "entry_date": today_str,
                    "sim_entry_price": sim_entry_p,
                    "shares": shares,
                    "last_price": curr_price,
                    "holding_days": 0,
                    "unrealized_pnl": 0.0,
                    "unrealized_return_pct": 0.0,
                    "pending_exit": False
                }

                print(f"  🟢 NEW GFS ENTRY: {s_sym} | Alloc: {self.symbol_prefix}{req_alloc:,.2f} | Shares: {shares:.2f} @ {curr_price:,.2f}")
                
                self.notifier.send_trade_alert(
                    market=f"{self.market.upper()}_{self.portfolio_id.split('_')[1].upper()}",
                    action="BUY",
                    symbol=s_sym,
                    price=curr_price,
                    shares=shares,
                    value=req_alloc
                )

        # 5. Final Daily Valuation
        stock_invested = sum(p["shares"] * p["last_price"] for p in positions.values())
        proxy_val = self.state["proxy_units"] * p_cp
        total_equity = self.state["cash"] + proxy_val + stock_invested

        self.state["positions"] = positions
        self.state["stock_invested"] = stock_invested
        self.state["proxy_val"] = proxy_val
        self.state["total_equity"] = total_equity
        self.state["last_updated"] = today_str

        self.state["daily_equity_history"].append({
            "date": today_str,
            "total_equity": total_equity,
            "cash": self.state["cash"],
            "proxy_val": proxy_val,
            "stock_val": stock_invested,
            "positions_count": len(positions)
        })

        self._save_state()

        pnl = total_equity - self.initial_capital
        pnl_pct = (pnl / self.initial_capital) * 100.0
        print(f"\n📊 {self.label} SUMMARY: Equity = {self.symbol_prefix}{total_equity:,.2f} | Total PnL = {pnl_pct:+.2f}% ({self.symbol_prefix}{pnl:+,.2f}) | Positions = {len(positions)}/{self.slots}")
        print(f"=======================================================\n")

        # 6. Monthly Report Dispatch
        if is_month_end or force_monthly_report:
            print(f"Sending Monthly Performance Report email for {self.label}...")
            self.notifier.send_monthly_report(self.label, self.state)
