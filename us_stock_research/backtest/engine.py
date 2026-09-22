"""Historical Backtesting Engine.

Simulates buy-and-hold portfolio performance from 2016-12-30 close to 2026-08-31 close.
Supports:
- Daily portfolio valuation and cash tracking
- Corporate actions ledger (cash dividends, stock splits, spinoffs, acquisitions)
- Total return calculation without dividend reinvestment (default primary)
- Secondary DRIP (dividend reinvestment) comparison
- Performance metrics: CAGR, Annualized Volatility, Max Drawdown, Sharpe Ratio
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from config.settings import DATA_DIR, setup_logger
from .models import CorporateAction, PortfolioSnapshot, Position

logger = setup_logger("backtest_engine", "backtest.log")

DEFAULT_MARKET_DATA_CACHE = DATA_DIR / "raw" / "backtest_market_data.json"


class BacktestEngine:
    """Simulates multi-asset portfolio performance over a historical horizon."""

    def __init__(
        self,
        market_data_cache_path: Optional[Path] = None,
        start_date: str = "2016-12-30",
        end_date: str = "2026-08-31",
        initial_capital: float = 10_000.0,
        risk_free_rate: float = 0.02,  # 2.0% historical risk-free proxy
    ):
        self.market_data_path = market_data_cache_path or DEFAULT_MARKET_DATA_CACHE
        self.start_date = start_date
        self.end_date = end_date
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate

        self.market_data: Dict[str, Any] = {}
        self._load_market_data()

    def _load_market_data(self) -> None:
        """Load market data cache into memory."""
        if not self.market_data_path.exists():
            raise FileNotFoundError(f"Market data cache not found at {self.market_data_path}")
        with open(self.market_data_path, "r", encoding="utf-8") as f:
            self.market_data = json.load(f)
        logger.info(f"Loaded market data cache with {len(self.market_data)} symbols.")

    def run_backtest(
        self,
        strategy_name: str,
        holdings: List[Dict[str, Any]],
        reinvest_dividends: bool = False,
    ) -> Dict[str, Any]:
        """Execute backtest for a given set of frozen holdings.

        Args:
            strategy_name: Identifier for the strategy (e.g. 'Strategy D').
            holdings: List of dicts with keys: ['ticker', 'company_name', 'cik', 'price_2016'].
            reinvest_dividends: If True, executes secondary DRIP policy; if False, cash accumulates.

        Returns:
            Dict containing complete performance summary, daily series, positions, and action logs.
        """
        num_positions = len(holdings)
        if num_positions == 0:
            raise ValueError("No holdings provided for backtest.")

        allocation_per_stock = self.initial_capital / num_positions
        positions: Dict[str, Position] = {}
        corporate_actions_log: List[CorporateAction] = []
        dividends_log: List[Dict[str, Any]] = []

        # 1. Initialize Positions on start_date
        for h in holdings:
            ticker = h["ticker"].upper()
            cik = int(h.get("cik", 0))
            name = h.get("company_name", ticker)

            # Get unadjusted start price
            p_entry = float(h.get("price_2016", 0.0))
            if p_entry <= 0:
                p_entry = self._get_price_on_date(ticker, self.start_date)

            if p_entry <= 0:
                raise ValueError(f"Could not determine valid entry price for {ticker} on {self.start_date}")

            init_shares = allocation_per_stock / p_entry

            positions[ticker] = Position(
                ticker=ticker,
                company_name=name,
                cik=cik,
                entry_date=self.start_date,
                entry_price=p_entry,
                initial_allocation=allocation_per_stock,
                initial_shares=init_shares,
                current_shares=init_shares,
                accumulated_dividends=0.0,
                cash_proceeds=0.0,
                status="ACTIVE",
                last_price=p_entry,
                last_value=allocation_per_stock,
            )

        # 2. Extract and unify calendar of trading days between start_date and end_date
        all_dates = set()
        for t in positions.keys():
            if t in self.market_data:
                for row in self.market_data[t]["daily"]:
                    d = row["date"]
                    if self.start_date <= d <= self.end_date:
                        all_dates.add(d)
        if not all_dates:
            raise ValueError(f"No trading dates found between {self.start_date} and {self.end_date}")

        trading_days = sorted(list(all_dates))

        # Pre-index dividends and splits by ticker and date for O(1) daily lookup
        div_map = {}
        split_map = {}
        for t, m_data in self.market_data.items():
            div_map[t] = {item["date"]: item["amount"] for item in m_data.get("dividends", [])}
            split_map[t] = {item["date"]: item["ratio"] for item in m_data.get("splits", [])}

        daily_values: List[Dict[str, Any]] = []
        portfolio_cash = 0.0

        # 3. Simulate Day-by-Day
        for current_date in trading_days:
            daily_equity_value = 0.0
            daily_dividends_paid = 0.0

            # Price map for this date
            day_prices = {}
            for t in positions.keys():
                day_prices[t] = self._get_price_on_date(t, current_date)
            # Spinoff prices
            spinoff_prices = {}
            if "AOUT" in self.market_data:
                spinoff_prices["AOUT"] = self._get_price_on_date("AOUT", current_date)

            for ticker, pos in positions.items():
                if pos.status != "ACTIVE":
                    continue

                # --- A. Process Stock Splits on this date ---
                if current_date in split_map.get(ticker, {}) and current_date > self.start_date:
                    s_ratio = split_map[ticker][current_date]
                    # Note: For SWBI on 2020-08-25, Yahoo records a 1.301 synthetic split to reflect
                    # the AOUT spinoff. We explicitly model the spinoff by distributing AOUT shares
                    # on 2020-08-24, so we ignore this synthetic share split to avoid double-counting.
                    if ticker == "SWBI" and current_date == "2020-08-25":
                        logger.debug("Skipping Yahoo synthetic 1.301 split for SWBI; AOUT spinoff handled explicitly.")
                    elif s_ratio > 0 and s_ratio != 1.0:
                        prev_sh = pos.current_shares
                        pos.current_shares *= s_ratio
                        action = CorporateAction(
                            date=current_date,
                            ticker=ticker,
                            action_type="SPLIT" if s_ratio > 1.0 else "REVERSE_SPLIT",
                            description=f"{s_ratio:g}-for-1 stock split",
                            ratio_or_amount=s_ratio,
                            treatment=f"Shares multiplied from {prev_sh:.4f} to {pos.current_shares:.4f}",
                        )
                        corporate_actions_log.append(action)

                # --- B. Process Spinoffs (e.g. SWBI -> AOUT on 2020-08-24) ---
                if ticker == "SWBI" and current_date == "2020-08-24":
                    # Ratio: 1 share of AOUT per 4 shares of SWBI (0.25 ratio)
                    spinoff_ratio = 0.25
                    aout_shares = pos.current_shares * spinoff_ratio
                    pos.spinoff_shares["AOUT"] = aout_shares
                    action = CorporateAction(
                        date=current_date,
                        ticker=ticker,
                        action_type="SPINOFF",
                        description="Tax-free spin-off of American Outdoor Brands, Inc. (AOUT)",
                        ratio_or_amount=spinoff_ratio,
                        treatment=f"Distributed {aout_shares:.4f} shares of AOUT (1:4 ratio)",
                    )
                    corporate_actions_log.append(action)

                # --- C. Process Cash Dividends on this date ---
                if current_date in div_map.get(ticker, {}) and current_date > self.start_date:
                    d_amt = div_map[ticker][current_date]
                    # BBSI prior to 2024-06-24: Yahoo reports split-adjusted dividend ($0.075 vs $0.30 unadjusted)
                    # Since BBSI shares are pre-split (15.6 sh) before 2024-06-24, scale div by 4.0 so actual cash matches
                    if ticker == "BBSI" and current_date < "2024-06-24":
                        d_amt_effective = d_amt * 4.0
                    else:
                        d_amt_effective = d_amt

                    if d_amt_effective > 0:
                        div_cash = pos.current_shares * d_amt_effective
                        pos.accumulated_dividends += div_cash
                        daily_dividends_paid += div_cash

                        # Get today's effective trading price
                        px_today = day_prices.get(ticker, 0.0)
                        if ticker == "BBSI" and current_date < "2024-06-24":
                            px_today *= 4.0

                        if reinvest_dividends:
                            if px_today > 0:
                                add_shares = div_cash / px_today
                                pos.current_shares += add_shares
                        else:
                            portfolio_cash += div_cash

                        dividends_log.append({
                            "date": current_date,
                            "ticker": ticker,
                            "shares_held": pos.current_shares,
                            "dividend_per_share": d_amt_effective,
                            "dividend_cash": div_cash,
                            "reinvested": reinvest_dividends,
                        })

                        action = CorporateAction(
                            date=current_date,
                            ticker=ticker,
                            action_type="DIVIDEND",
                            description=f"Cash dividend of ${d_amt_effective:.4f} per share",
                            ratio_or_amount=d_amt_effective,
                            treatment=f"Received ${div_cash:.2f} cash",
                        )
                        corporate_actions_log.append(action)

                # --- D. Value Position for the day ---
                px = day_prices.get(ticker, pos.last_price)
                if ticker == "BBSI" and current_date < "2024-06-24":
                    px *= 4.0

                if px > 0:
                    pos.last_price = px

                eq_val = pos.current_equity_value(pos.last_price, spinoff_prices)
                pos.last_value = eq_val
                daily_equity_value += eq_val

            total_port_value = daily_equity_value + portfolio_cash

            daily_values.append({
                "date": current_date,
                "strategy": strategy_name,
                "total_value": total_port_value,
                "equity_value": daily_equity_value,
                "cash_balance": portfolio_cash,
                "dividends_received_cumulative": sum(p.accumulated_dividends for p in positions.values()),
                "daily_dividends_paid": daily_dividends_paid,
            })

        daily_df = pd.DataFrame(daily_values)
        daily_df["daily_return"] = daily_df["total_value"].pct_change().fillna(0.0)

        # 4. Calculate Final Metrics
        ending_val = daily_df["total_value"].iloc[-1]
        ending_cash = daily_df["cash_balance"].iloc[-1]
        ending_equity = daily_df["equity_value"].iloc[-1]
        total_dividends = daily_df["dividends_received_cumulative"].iloc[-1]

        total_return_pct = (ending_val - self.initial_capital) / self.initial_capital
        days_span = (pd.to_datetime(self.end_date) - pd.to_datetime(self.start_date)).days
        years_span = days_span / 365.25
        cagr = (ending_val / self.initial_capital) ** (1.0 / years_span) - 1.0 if years_span > 0 else 0.0

        # Volatility & Sharpe
        ann_vol = float(daily_df["daily_return"].std() * np.sqrt(252))
        sharpe = (cagr - self.risk_free_rate) / ann_vol if ann_vol > 0 else 0.0

        # Maximum Drawdown
        rolling_max = daily_df["total_value"].cummax()
        drawdown_series = (daily_df["total_value"] - rolling_max) / rolling_max
        max_drawdown = float(drawdown_series.min())

        # Holding Attribution
        attribution_records = []
        for ticker, pos in positions.items():
            p_end = pos.last_price
            eq_end = pos.current_equity_value(p_end, spinoff_prices)
            tot_end = eq_end + pos.accumulated_dividends + pos.cash_proceeds
            holding_ret = (tot_end - pos.initial_allocation) / pos.initial_allocation
            holding_cagr = (tot_end / pos.initial_allocation) ** (1.0 / years_span) - 1.0 if years_span > 0 else 0.0
            contrib_to_port_ret = (tot_end - pos.initial_allocation) / self.initial_capital

            attribution_records.append({
                "strategy": strategy_name,
                "ticker": ticker,
                "company_name": pos.company_name,
                "cik": pos.cik,
                "entry_date": self.start_date,
                "entry_price": pos.entry_price,
                "initial_allocation": pos.initial_allocation,
                "initial_shares": pos.initial_shares,
                "ending_date": self.end_date,
                "ending_price": p_end,
                "ending_shares": pos.current_shares,
                "ending_equity_value": eq_end,
                "dividends_cash": pos.accumulated_dividends,
                "corporate_action_proceeds": pos.cash_proceeds,
                "total_ending_value": tot_end,
                "total_return": holding_ret,
                "cagr": holding_cagr,
                "contribution_to_portfolio_return": contrib_to_port_ret,
                "status": pos.status,
            })

        attr_df = pd.DataFrame(attribution_records).sort_values("total_ending_value", ascending=False)

        # Winners / Losers
        num_winners = (attr_df["total_return"] > 0).sum()
        num_losers = (attr_df["total_return"] <= 0).sum()

        # Concentration metrics
        top1_contrib = attr_df.iloc[0]["contribution_to_portfolio_return"]
        top3_contrib = attr_df.iloc[:3]["contribution_to_portfolio_return"].sum()
        top5_contrib = attr_df.iloc[:5]["contribution_to_portfolio_return"].sum()

        return {
            "strategy": strategy_name,
            "reinvest_dividends": reinvest_dividends,
            "initial_capital": self.initial_capital,
            "ending_value": ending_val,
            "ending_equity": ending_equity,
            "ending_cash": ending_cash,
            "total_dividends": total_dividends,
            "total_return_pct": total_return_pct,
            "cagr": cagr,
            "annualized_volatility": ann_vol,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe,
            "years": years_span,
            "num_holdings": num_positions,
            "num_winners": int(num_winners),
            "num_losers": int(num_losers),
            "best_holding": attr_df.iloc[0]["ticker"],
            "best_holding_return": attr_df.iloc[0]["total_return"],
            "worst_holding": attr_df.iloc[-1]["ticker"],
            "worst_holding_return": attr_df.iloc[-1]["total_return"],
            "top1_contribution": top1_contrib,
            "top3_contribution": top3_contrib,
            "top5_contribution": top5_contrib,
            "daily_df": daily_df,
            "attribution_df": attr_df,
            "positions": positions,
            "corporate_actions": corporate_actions_log,
            "dividends_log": dividends_log,
        }

    def _get_price_on_date(self, ticker: str, date: str) -> float:
        """Retrieve closing price for ticker on or immediately before date."""
        if ticker not in self.market_data:
            return 0.0
        daily = self.market_data[ticker].get("daily", [])
        # Find exact date or latest date <= date
        best_price = 0.0
        for r in daily:
            d = r["date"]
            if d <= date:
                best_price = float(r["close"])
            elif d > date:
                break
        return best_price
