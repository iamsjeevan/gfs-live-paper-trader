"""Screening and Ranking Engine for 2016 Indian Equity Universe.

Implements both:
- Version 1: US-equivalent threshold model (ROE >= 12%, ROCE >= 10%, D/E <= 1.5, FCF > 0).
- Version 2: India-adapted percentile threshold model (ROCE >= 15%, D/E <= 1.0, OCF > 0).

Produces Strategy A (Quality), Strategy B (Quality + Growth), Strategy C (Quality + Growth + Value),
and Strategy D (Quality + Growth + Value + Moat/Margins) top 10 portfolios.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

try:
    from india_stock_research.config.settings import setup_logger
except ImportError:
    from config.settings import setup_logger

logger = setup_logger("india_screening", "india_screening.log")


class IndiaScreeningEngine:
    """Evaluates hard quality filters and produces factor rankings across Strategy A, B, C, D."""

    def __init__(self):
        pass

    def apply_quality_filters_v1(self, fund_df: pd.DataFrame) -> pd.DataFrame:
        """Apply Version 1 (US-equivalent) hard quality filters.

        - Non-financial sector
        - ROE >= 12.0%
        - ROCE >= 10.0%
        - Debt / Equity <= 1.50
        - Free Cash Flow > 0
        - Total Revenue > 0
        """
        mask = (
            (~fund_df["is_financial"]) &
            (fund_df["roe_2016"] >= 12.0) &
            (fund_df["roce_2016"] >= 10.0) &
            (fund_df["debt_equity_2016"] <= 1.50) &
            (fund_df["free_cash_flow_cr_2016"] > 0) &
            (fund_df["revenue_cr_2016"] > 0)
        )
        passed_df = fund_df[mask].copy()
        logger.info(f"Version 1 Hard Quality Filters: {len(passed_df)} / {len(fund_df)} passed.")
        return passed_df

    def apply_quality_filters_v2(self, fund_df: pd.DataFrame) -> pd.DataFrame:
        """Apply Version 2 (India-adapted) percentile thresholds.

        - Non-financial sector
        - ROCE >= 15.0% (India capital intensity adaptation)
        - Debt / Equity <= 1.00 (stricter leverage cap in INR high-rate environment)
        - Operating Cash Flow > 0
        - Total Revenue > 0
        """
        mask = (
            (~fund_df["is_financial"]) &
            (fund_df["roce_2016"] >= 15.0) &
            (fund_df["debt_equity_2016"] <= 1.00) &
            (fund_df["operating_cash_flow_cr_2016"] > 0) &
            (fund_df["revenue_cr_2016"] > 0)
        )
        passed_df = fund_df[mask].copy()
        logger.info(f"Version 2 Hard Quality Filters: {len(passed_df)} / {len(fund_df)} passed.")
        return passed_df

    def score_and_rank_candidates(
        self,
        passed_df: pd.DataFrame,
        version_label: str = "V1",
    ) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
        """Compute Strategy A, B, C, D factor scores and select Top 10 portfolios.

        Factor weights:
        - Strategy A (Quality): Quality (100%)
        - Strategy B (Quality + Growth): Quality (50%) + Growth (50%)
        - Strategy C (Quality + Growth + Value): Quality (40%) + Growth (30%) + Value (30%)
        - Strategy D (Full Strategy + Moat): Quality (30%) + Growth (25%) + Value (25%) + Moat (20%)
        """
        df = passed_df.copy()
        if df.empty:
            return df, {}

        # 1. Quality Composite Score (ROE, ROCE, low Debt/Equity, Operating Margin)
        r_roe = df["roe_2016"].rank(pct=True)
        r_roce = df["roce_2016"].rank(pct=True)
        r_de = (-df["debt_equity_2016"]).rank(pct=True)
        r_opm = df["operating_margin_2016"].rank(pct=True)
        df["score_quality"] = (r_roe * 0.35 + r_roce * 0.35 + r_de * 0.15 + r_opm * 0.15) * 100.0

        # 2. Growth Composite Score (Revenue 3Y CAGR, Net Profit 3Y CAGR)
        med_rev_g = df["revenue_cagr_3y"].median() or 0.05
        med_prof_g = df["net_profit_cagr_3y"].median() or 0.05
        r_rev_g = df["revenue_cagr_3y"].fillna(med_rev_g).rank(pct=True)
        r_prof_g = df["net_profit_cagr_3y"].fillna(med_prof_g).rank(pct=True)
        df["score_growth"] = (r_rev_g * 0.50 + r_prof_g * 0.50) * 100.0

        # 3. Value Composite Score (1/PE, 1/PB)
        r_pe = (-df["pe_ratio_2016"]).rank(pct=True)
        r_pb = (-df["pb_ratio_2016"]).rank(pct=True)
        df["score_value"] = (r_pe * 0.50 + r_pb * 0.50) * 100.0

        # 4. Moat / Capital Efficiency Composite Score (Gross Margin, Asset Turnover, Cash Conversion Cycle)
        r_gm = df["gross_margin_2016"].fillna(df["operating_margin_2016"]).rank(pct=True)
        r_at = df["asset_turnover_2016"].fillna(df["asset_turnover_2016"].median()).rank(pct=True)
        df["score_moat"] = (r_gm * 0.50 + r_at * 0.50) * 100.0

        # Strategy Scores
        df[f"score_strat_a_{version_label}"] = df["score_quality"]
        df[f"score_strat_b_{version_label}"] = df["score_quality"] * 0.50 + df["score_growth"] * 0.50
        df[f"score_strat_c_{version_label}"] = (
            df["score_quality"] * 0.40 + df["score_growth"] * 0.30 + df["score_value"] * 0.30
        )
        df[f"score_strat_d_{version_label}"] = (
            df["score_quality"] * 0.30 + df["score_growth"] * 0.25 + df["score_value"] * 0.25 + df["score_moat"] * 0.20
        )

        # Strategy Ranks
        df[f"rank_strat_a_{version_label}"] = df[f"score_strat_a_{version_label}"].rank(ascending=False, method="min").astype(int)
        df[f"rank_strat_b_{version_label}"] = df[f"score_strat_b_{version_label}"].rank(ascending=False, method="min").astype(int)
        df[f"rank_strat_c_{version_label}"] = df[f"score_strat_c_{version_label}"].rank(ascending=False, method="min").astype(int)
        df[f"rank_strat_d_{version_label}"] = df[f"score_strat_d_{version_label}"].rank(ascending=False, method="min").astype(int)

        # Portfolios
        portfolios = {
            "Strategy_A": df.sort_values(f"rank_strat_a_{version_label}").head(10).copy(),
            "Strategy_B": df.sort_values(f"rank_strat_b_{version_label}").head(10).copy(),
            "Strategy_C": df.sort_values(f"rank_strat_c_{version_label}").head(10).copy(),
            "Strategy_D": df.sort_values(f"rank_strat_d_{version_label}").head(10).copy(),
        }

        return df, portfolios
