"""Multi-factor scoring and ranking engine for historical stock selection.

Implements the four required strategy variants:
1. Strategy A: Quality Only
2. Strategy B: Quality + Growth
3. Strategy C: Quality + Growth + Value
4. Strategy D: Full Strategy (Quality + Growth + Value + Quantitative Moat)

Uses cross-sectional percentile ranking to prevent outliers from dominating.
"""

from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd


def compute_percentile_ranks(
    series: pd.Series,
    ascending: bool = True,
    missing_value: float = 50.0,
) -> pd.Series:
    """Compute percentile ranks in [0.0, 100.0] for a pandas Series.

    If ascending=True, higher values get higher ranks (e.g. ROIC, Growth).
    If ascending=False, lower values get higher ranks (e.g. P/E, Debt/Equity).
    Missing values receive missing_value (default 50.0).
    """
    valid = series.dropna()
    if valid.empty:
        return pd.Series(missing_value, index=series.index)

    ranks = valid.rank(ascending=ascending, pct=True) * 100.0
    return ranks.reindex(series.index).fillna(missing_value)



def score_universe_candidates(
    candidates_data: List[Dict[str, Any]],
) -> Dict[str, pd.DataFrame]:
    """Calculate normalized factor scores and rankings across all four strategy variants.

    Returns:
        Dict mapping strategy_name -> ranked DataFrame with complete metric and score columns.
    """
    if not candidates_data:
        return {}

    df = pd.DataFrame(candidates_data)

    # 1. Compute Individual Factor Percentile Scores
    # Higher is better:
    df["score_roic"] = compute_percentile_ranks(df["roic"], ascending=True)
    df["score_roe"] = compute_percentile_ranks(df["roe"], ascending=True)
    df["score_op_margin"] = compute_percentile_ranks(df["operating_margin"], ascending=True)
    df["score_fcf_margin"] = compute_percentile_ranks(df["fcf_margin"], ascending=True)
    df["score_rev_growth"] = compute_percentile_ranks(df["revenue_growth"], ascending=True)
    df["score_rev_cagr"] = compute_percentile_ranks(df["revenue_cagr"], ascending=True)
    df["score_ni_growth"] = compute_percentile_ranks(df["net_income_growth"], ascending=True)
    df["score_ni_cagr"] = compute_percentile_ranks(df["net_income_cagr"], ascending=True)
    df["score_fcf_cagr"] = compute_percentile_ranks(df["fcf_cagr"], ascending=True)
    df["score_consistency"] = compute_percentile_ranks(df["growth_consistency"], ascending=True)
    df["score_moat"] = compute_percentile_ranks(df["quantitative_moat_score"], ascending=True)

    # Lower is better (cheapness / lower leverage):
    df["score_debt_equity"] = compute_percentile_ranks(df["debt_equity"], ascending=False)

    def _score_valuation(val_series: pd.Series) -> pd.Series:
        pos_mask = (val_series > 0)
        res = pd.Series(0.0, index=val_series.index)
        pos_vals = val_series[pos_mask]
        if not pos_vals.empty:
            ranks = pos_vals.rank(ascending=False, pct=True) * 100.0
            res.loc[pos_mask] = ranks
        return res

    df["score_pe"] = _score_valuation(df["pe"])
    df["score_ev_ebitda"] = _score_valuation(df["ev_ebitda"])
    df["score_price_fcf"] = _score_valuation(df["price_fcf"])


    # 2. Sub-Pillar Aggregate Scores
    # Quality Score (0 to 100)
    df["quality_score"] = (
        0.30 * df["score_roic"] +
        0.25 * df["score_roe"] +
        0.25 * df["score_debt_equity"] +
        0.10 * df["score_op_margin"] +
        0.10 * df["score_fcf_margin"]
    )

    # Growth Score (0 to 100)
    df["growth_score"] = (
        0.35 * df["score_rev_cagr"] +
        0.25 * df["score_ni_cagr"] +
        0.20 * df["score_fcf_cagr"] +
        0.20 * df["score_consistency"]
    )

    # Valuation Score (0 to 100)
    df["valuation_score"] = (
        0.40 * df["score_pe"] +
        0.30 * df["score_ev_ebitda"] +
        0.30 * df["score_price_fcf"]
    )

    # Quantitative Moat Score (0 to 100)
    df["moat_score"] = df["score_moat"]

    # -------------------------------------------------------------------------
    # 3. Four Strategy Variants
    # -------------------------------------------------------------------------
    results: Dict[str, pd.DataFrame] = {}

    # Strategy A: Quality Only
    df_a = df.copy()
    df_a["composite_score"] = df_a["quality_score"]
    df_a = df_a.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df_a["rank"] = df_a.index + 1
    results["Strategy A (Quality Only)"] = df_a

    # Strategy B: Quality + Growth
    df_b = df.copy()
    df_b["composite_score"] = 0.50 * df_b["quality_score"] + 0.50 * df_b["growth_score"]
    df_b = df_b.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df_b["rank"] = df_b.index + 1
    results["Strategy B (Quality + Growth)"] = df_b

    # Strategy C: Quality + Growth + Value
    df_c = df.copy()
    df_c["composite_score"] = (
        0.40 * df_c["quality_score"] +
        0.40 * df_c["growth_score"] +
        0.20 * df_c["valuation_score"]
    )
    df_c = df_c.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df_c["rank"] = df_c.index + 1
    results["Strategy C (Quality + Growth + Value)"] = df_c

    # Strategy D: Full Proposed Strategy (Quality + Growth + Value + Moat)
    df_d = df.copy()
    df_d["composite_score"] = (
        0.20 * df_d["score_roic"] +
        0.15 * df_d["score_roe"] +
        0.15 * df_d["score_rev_cagr"] +
        0.10 * df_d["score_ni_cagr"] +
        0.10 * df_d["score_fcf_cagr"] +
        0.10 * df_d["score_debt_equity"] +
        0.05 * df_d["score_op_margin"] +
        0.05 * df_d["score_fcf_margin"] +
        0.05 * df_d["valuation_score"] +
        0.05 * df_d["moat_score"]
    )
    df_d = df_d.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df_d["rank"] = df_d.index + 1
    results["Strategy D (Full Strategy: Quality + Growth + Value + Moat)"] = df_d

    return results
