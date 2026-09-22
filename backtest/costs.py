"""Trading costs, slippage, and financing fee calculations."""

from dataclasses import dataclass
from typing import Dict, Tuple

# Predefined cost tiers as specified in research requirements
COST_TIERS: Dict[str, Tuple[float, float, float]] = {
    # tier_name: (fee_rate, slippage_rate, borrow_rate_apr)
    "zero": (0.0, 0.0, 0.0),
    "realistic": (0.0005, 0.00025, 0.06),  # 5 bps fee, 2.5 bps slippage, 6% APR borrow
    "stress": (0.0015, 0.0010, 0.06),     # 15 bps fee, 10 bps slippage, 6% APR borrow
}


@dataclass(frozen=True)
class CostModel:
    """Cost configuration for trading fee, execution slippage, and margin financing."""
    fee_rate: float = 0.0005          # 5 bps per trade
    slippage_rate: float = 0.00025    # 2.5 bps per trade
    borrow_rate_apr: float = 0.06     # 6% APR on borrowed capital

    @property
    def total_trade_cost_rate(self) -> float:
        """Total execution cost rate per one-way turnover dollar."""
        return self.fee_rate + self.slippage_rate

    @classmethod
    def from_tier(cls, tier_name: str = "realistic") -> "CostModel":
        """Factory for predefined cost tiers: 'zero', 'realistic', 'stress'."""
        tier = tier_name.lower()
        if tier not in COST_TIERS:
            raise ValueError(f"Unknown cost tier '{tier_name}'. Available: {list(COST_TIERS.keys())}")
        fee, slip, borrow = COST_TIERS[tier]
        return cls(fee_rate=fee, slippage_rate=slip, borrow_rate_apr=borrow)

    def calculate_trade_cost(self, traded_dollars: float) -> Tuple[float, float, float]:
        """Compute fee, slippage, and total cost on a rebalance trade.

        Parameters
        ----------
        traded_dollars : float
            Gross dollar value traded: abs(delta_shares) * execution_price.

        Returns
        -------
        Tuple[float, float, float]
            (fee_dollars, slippage_dollars, total_cost_dollars)
        """
        fee = abs(traded_dollars) * self.fee_rate
        slippage = abs(traded_dollars) * self.slippage_rate
        return fee, slippage, fee + slippage

    def calculate_borrow_cost(
        self,
        position_value: float,
        equity: float,
        annual_periods: int,
        is_short: bool = False,
    ) -> float:
        """Compute financing cost for borrowed capital over one bar period.

        Parameters
        ----------
        position_value : float
            Current absolute dollar value of the position.
        equity : float
            Current account equity.
        annual_periods : int
            Number of periods per year for the bar timeframe (e.g. 365 for 1d, 8760 for 1h).
        is_short : bool
            Whether the position is short. In spot margin, shorting requires borrowing 100% of asset.

        Returns
        -------
        float
            Financing cost in dollars for the period.
        """
        if self.borrow_rate_apr <= 0 or annual_periods <= 0:
            return 0.0

        if is_short:
            # Spot margin borrowing: borrow entire asset value
            borrowed_capital = abs(position_value)
        else:
            # Long leverage borrowing: borrow excess over equity
            borrowed_capital = max(0.0, abs(position_value) - max(0.0, equity))

        period_rate = self.borrow_rate_apr / annual_periods
        return borrowed_capital * period_rate
