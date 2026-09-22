"""Comparative statistical and cross-sectional analysis for Milestone 7."""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from scipy import stats

from config.settings import setup_logger

logger = setup_logger("retrospective_analysis", "screening.log")


def compute_distribution_summary(series: pd.Series) -> Dict[str, Optional[float]]:
    """Compute mean, median, p25, p75, min, max for a numerical series."""
    s = series.dropna()
    if s.empty:
        return {
            "count": 0, "mean": None, "median": None,
            "p25": None, "p75": None, "min": None, "max": None
        }
    return {
        "count": int(len(s)),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "p25": float(s.quantile(0.25)),
        "p75": float(s.quantile(0.75)),
        "min": float(s.min()),
        "max": float(s.max()),
    }


def compare_winners_vs_non_winners(
    analysis_df: pd.DataFrame,
    signals: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Compare distribution stats between Future Winners and Non-Winners."""
    if signals is None:
        signals = [
            "roic_2016", "roe_2016", "operating_margin_2016", "gross_margin",
            "fcf_margin_2016", "debt_equity_2016", "revenue_cagr_3y",
            "net_income_cagr_3y", "fcf_cagr_3y", "pe_ratio", "price_fcf",
            "price_sales", "moat_score", "market_cap_2016"
        ]

    # Available signals
    signals = [s for s in signals if s in analysis_df.columns]

    w_top25 = analysis_df[analysis_df["is_w1_top25"] == True]
    w_top50 = analysis_df[analysis_df["is_w1_top50"] == True]
    w_cagr20 = analysis_df[analysis_df["is_w2_cagr20"] == True]
    control = analysis_df[analysis_df["is_non_winner"] == True]
    all_uni = analysis_df

    rows = []
    for sig in signals:
        s_top25 = compute_distribution_summary(w_top25[sig])
        s_top50 = compute_distribution_summary(w_top50[sig])
        s_cagr20 = compute_distribution_summary(w_cagr20[sig])
        s_ctl = compute_distribution_summary(control[sig])
        s_all = compute_distribution_summary(all_uni[sig])

        med_w = s_top25["median"]
        med_c = s_ctl["median"]
        diff = (med_w - med_c) if (med_w is not None and med_c is not None) else None

        rows.append({
            "signal": sig,
            "winners_top25_median": med_w,
            "winners_top25_mean": s_top25["mean"],
            "winners_top25_p25": s_top25["p25"],
            "winners_top25_p75": s_top25["p75"],
            "winners_top50_median": s_top50["median"],
            "winners_top50_mean": s_top50["mean"],
            "winners_cagr20_median": s_cagr20["median"],
            "control_median": med_c,
            "control_mean": s_ctl["mean"],
            "control_p25": s_ctl["p25"],
            "control_p75": s_ctl["p75"],
            "all_universe_median": s_all["median"],
            "median_diff_w25_vs_control": diff,
        })

    return pd.DataFrame(rows)


def analyze_valuation_buckets(
    analysis_df: pd.DataFrame,
) -> pd.DataFrame:
    """Analyze subsequent 10-year returns and winner frequency by starting valuation bucket."""
    df = analysis_df.copy()

    # Define P/E buckets
    pe_bins = [-np.inf, 0, 10, 15, 20, 30, 50, np.inf]
    pe_labels = ["Negative (<0x)", "Deep Value (<10x)", "Value (10-15x)", "Reasonable (15-20x)", "Growth (20-30x)", "Premium (30-50x)", "Speculative (>50x)"]

    df["pe_bucket"] = pd.cut(df["pe_ratio"].fillna(-1), bins=pe_bins, labels=pe_labels)

    records = []
    for bucket in pe_labels:
        b_df = df[df["pe_bucket"] == bucket]
        n = len(b_df)
        if n == 0:
            continue
        cagr_s = b_df["cagr"].dropna()
        tot_s = b_df["total_return"].dropna()

        records.append({
            "valuation_bucket": bucket,
            "count": n,
            "pct_of_universe": float(n / len(df)),
            "top25_winners_count": int(b_df["is_w1_top25"].sum()),
            "top50_winners_count": int(b_df["is_w1_top50"].sum()),
            "cagr20_winners_count": int(b_df["is_w2_cagr20"].sum()),
            "top25_capture_rate": float(b_df["is_w1_top25"].sum() / n),
            "median_10yr_cagr": float(cagr_s.median()) if not cagr_s.empty else None,
            "mean_10yr_cagr": float(cagr_s.mean()) if not cagr_s.empty else None,
            "median_total_return": float(tot_s.median()) if not tot_s.empty else None,
            "mean_total_return": float(tot_s.mean()) if not tot_s.empty else None,
        })

    return pd.DataFrame(records)


def analyze_market_cap_buckets(
    analysis_df: pd.DataFrame,
) -> pd.DataFrame:
    """Analyze subsequent 10-year returns and winner concentration across small-cap size tiers."""
    df = analysis_df.copy()

    mcap_bins = [0, 100_000_000, 250_000_000, 500_000_000, 1_000_000_000, np.inf]
    mcap_labels = ["Micro/Nano ($50M-$100M)", "Lower Small-Cap ($100M-$250M)", "Core Small-Cap ($250M-$500M)", "Upper Small-Cap ($500M-$1B)", "Control (>$1B)"]

    df["mcap_bucket"] = pd.cut(df["market_cap_2016"].fillna(0), bins=mcap_bins, labels=mcap_labels)

    records = []
    for bucket in mcap_labels:
        b_df = df[df["mcap_bucket"] == bucket]
        n = len(b_df)
        if n == 0:
            continue
        cagr_s = b_df["cagr"].dropna()
        tot_s = b_df["total_return"].dropna()

        records.append({
            "market_cap_bucket": bucket,
            "count": n,
            "pct_of_universe": float(n / len(df)),
            "top25_winners_count": int(b_df["is_w1_top25"].sum()),
            "top50_winners_count": int(b_df["is_w1_top50"].sum()),
            "cagr20_winners_count": int(b_df["is_w2_cagr20"].sum()),
            "top25_capture_rate": float(b_df["is_w1_top25"].sum() / n),
            "median_10yr_cagr": float(cagr_s.median()) if not cagr_s.empty else None,
            "mean_10yr_cagr": float(cagr_s.mean()) if not cagr_s.empty else None,
            "median_total_return": float(tot_s.median()) if not tot_s.empty else None,
            "mean_total_return": float(tot_s.mean()) if not tot_s.empty else None,
        })

    return pd.DataFrame(records)


def analyze_quality_growth_matrix(
    analysis_df: pd.DataFrame,
) -> pd.DataFrame:
    """Evaluate the Quality x Growth 2D grid."""
    df = analysis_df.copy()

    # Quality criterion: ROIC >= 12% and D/E <= 1.5
    # Growth criterion: Revenue 3y CAGR >= 10%
    has_high_q = (df["roic_2016"] >= 0.12) & (df["debt_equity_2016"] <= 1.5)
    has_high_g = (df["revenue_cagr_3y"] >= 0.10)

    conditions = [
        has_high_q & has_high_g,
        has_high_q & (~has_high_g),
        (~has_high_q) & has_high_g,
        (~has_high_q) & (~has_high_g),
    ]
    labels = [
        "Q1: High Quality / High Growth",
        "Q2: High Quality / Low Growth",
        "Q3: Low Quality / High Growth",
        "Q4: Low Quality / Low Growth",
    ]
    df["quadrant"] = np.select(conditions, labels, default="Unclassified")

    records = []
    for quad in labels:
        b_df = df[df["quadrant"] == quad]
        n = len(b_df)
        if n == 0:
            continue
        cagr_s = b_df["cagr"].dropna()
        tot_s = b_df["total_return"].dropna()

        records.append({
            "quadrant": quad,
            "count": n,
            "pct_of_universe": float(n / len(df)),
            "top25_winners_count": int(b_df["is_w1_top25"].sum()),
            "top50_winners_count": int(b_df["is_w1_top50"].sum()),
            "cagr20_winners_count": int(b_df["is_w2_cagr20"].sum()),
            "top25_rate": float(b_df["is_w1_top25"].sum() / n),
            "median_10yr_cagr": float(cagr_s.median()) if not cagr_s.empty else None,
            "mean_10yr_cagr": float(cagr_s.mean()) if not cagr_s.empty else None,
            "median_total_return": float(tot_s.median()) if not tot_s.empty else None,
            "mean_total_return": float(tot_s.mean()) if not tot_s.empty else None,
        })

    return pd.DataFrame(records)


def compute_spearman_correlations(
    analysis_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute Spearman rank correlations between 2016 metrics / strategy scores and 10-year CAGR."""
    target = "cagr"
    candidate_features = [
        "roic_2016", "roe_2016", "operating_margin_2016", "fcf_margin_2016",
        "debt_equity_2016", "revenue_cagr_3y", "net_income_cagr_3y", "fcf_cagr_3y",
        "pe_ratio", "price_fcf", "price_sales", "moat_score", "market_cap_2016",
        "score_strategy_a", "score_strategy_b", "score_strategy_c", "score_strategy_d"
    ]

    records = []
    for feat in candidate_features:
        if feat not in analysis_df.columns:
            continue
        valid = analysis_df[[feat, target]].dropna()
        if len(valid) < 10:
            continue
        corr, pval = stats.spearmanr(valid[feat], valid[target])
        records.append({
            "feature": feat,
            "sample_size": len(valid),
            "spearman_rho": float(corr),
            "p_value": float(pval),
            "is_significant_05": bool(pval < 0.05),
            "is_significant_01": bool(pval < 0.01),
        })

    return pd.DataFrame(records).sort_values("spearman_rho", ascending=False).reset_index(drop=True)


def analyze_irmd_outlier(
    analysis_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Perform specific forensic outlier analysis on IRADIMED (IRMD)."""
    irmd_row = analysis_df[analysis_df["ticker"] == "IRMD"]
    if irmd_row.empty:
        return {"found": False}

    r = irmd_row.iloc[0]
    w_df = analysis_df[analysis_df["is_w1_top25"] == True]

    metrics = [
        ("roic_2016", "ROIC"),
        ("fcf_margin_2016", "FCF Margin"),
        ("debt_equity_2016", "Debt/Equity"),
        ("revenue_cagr_3y", "Revenue 3y CAGR"),
        ("pe_ratio", "P/E Ratio"),
        ("moat_score", "Quantitative Moat Score"),
        ("market_cap_2016", "2016 Market Cap"),
        ("cagr", "10-Year CAGR"),
        ("total_return", "10-Year Total Return"),
    ]

    percentiles_universe = {}
    percentiles_winners = {}

    for col, name in metrics:
        val = r.get(col)
        if val is not None and not np.isnan(val):
            # Uni pct
            s_uni = analysis_df[col].dropna()
            pct_u = float((s_uni < val).mean() * 100.0) if not s_uni.empty else None
            percentiles_universe[name] = {"value": float(val), "percentile": pct_u}

            # Winners pct
            s_w = w_df[col].dropna()
            pct_w = float((s_w < val).mean() * 100.0) if not s_w.empty else None
            percentiles_winners[name] = {"value": float(val), "percentile": pct_w}

    return {
        "found": True,
        "ticker": "IRMD",
        "company_name": r.get("company_name", "IRADIMED CORP"),
        "return_rank": int(r.get("return_rank", 0)),
        "cagr": float(r.get("cagr", 0.0)),
        "total_return": float(r.get("total_return", 0.0)),
        "selected_by_strategy_d": bool(r.get("selected_strategy_d", False)),
        "strategy_d_rank": r.get("rank_strategy_d"),
        "strategy_d_score": r.get("score_strategy_d"),
        "metrics_vs_universe": percentiles_universe,
        "metrics_vs_winners": percentiles_winners,
    }
