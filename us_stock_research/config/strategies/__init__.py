"""Strategies registry package."""

from .quality import STRATEGY as QUALITY_STRATEGY
from .quality_growth import STRATEGY as QUALITY_GROWTH_STRATEGY
from .quality_value_moat import STRATEGY as QUALITY_VALUE_MOAT_STRATEGY

STRATEGIES = {
    "quality": QUALITY_STRATEGY,
    "quality_growth": QUALITY_GROWTH_STRATEGY,
    "quality_value_moat": QUALITY_VALUE_MOAT_STRATEGY,
}

__all__ = [
    "QUALITY_STRATEGY",
    "QUALITY_GROWTH_STRATEGY",
    "QUALITY_VALUE_MOAT_STRATEGY",
    "STRATEGIES",
]
