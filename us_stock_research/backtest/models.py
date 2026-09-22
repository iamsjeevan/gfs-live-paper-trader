"""Data structures and models for historical backtesting and position ledger."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class CorporateAction:
    """Record of a discrete corporate action."""
    date: str
    ticker: str
    action_type: str  # 'DIVIDEND', 'SPLIT', 'SPINOFF', 'MERGER_CASH', 'MERGER_STOCK', 'BANKRUPTCY'
    description: str
    ratio_or_amount: float
    treatment: str
    provider: str = "yahoo_market_data"
    confidence: float = 1.0


@dataclass
class Position:
    """Tracks a single security holding throughout the backtest period."""
    ticker: str
    company_name: str
    cik: int
    entry_date: str
    entry_price: float
    initial_allocation: float
    initial_shares: float
    current_shares: float
    accumulated_dividends: float = 0.0
    cash_proceeds: float = 0.0
    status: str = "ACTIVE"  # 'ACTIVE', 'ACQUIRED', 'BANKRUPT', 'DELISTED', 'SPINOFF'
    spinoff_shares: Dict[str, float] = field(default_factory=dict)
    last_price: float = 0.0
    last_value: float = 0.0

    def current_equity_value(self, current_price: float, spinoff_prices: Optional[Dict[str, float]] = None) -> float:
        """Calculate market value of security shares plus any spun-off shares."""
        val = self.current_shares * current_price
        if spinoff_prices and self.spinoff_shares:
            for s_ticker, s_shares in self.spinoff_shares.items():
                s_px = spinoff_prices.get(s_ticker, 0.0)
                val += s_shares * s_px
        return val

    def total_value(self, current_price: float, spinoff_prices: Optional[Dict[str, float]] = None) -> float:
        """Calculate total position value including accumulated cash and spinoffs."""
        return self.current_equity_value(current_price, spinoff_prices) + self.accumulated_dividends + self.cash_proceeds


@dataclass
class PortfolioSnapshot:
    """Point-in-time valuation snapshot of a portfolio."""
    date: str
    total_value: float
    equity_value: float
    cash_balance: float
    accumulated_dividends: float
    corporate_action_cash: float
    positions_detail: Dict[str, Dict[str, Any]]
