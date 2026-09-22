"""Base interface for market data and price providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import pandas as pd


class PriceProvider(ABC):
    """Abstract interface for downloading and querying historical market prices."""

    @abstractmethod
    def get_history(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Fetch historical daily OHLCV price DataFrame.

        Returns DataFrame with columns:
        ['date', 'open', 'high', 'low', 'close', 'adjusted_close', 'volume']
        indexed by date or with 'date' as a string column.
        """
        pass

    @abstractmethod
    def get_price(
        self,
        ticker: str,
        date: str,
        adjusted: bool = False,
    ) -> Optional[float]:
        """Fetch the closing price on or immediately before `date` (e.g. for weekends/holidays)."""
        pass

    @abstractmethod
    def get_corporate_actions(
        self,
        ticker: str,
    ) -> pd.DataFrame:
        """Fetch historical splits, dividends, and corporate actions."""
        pass
