"""Cross-Sectional Factor Analysis, Valuation Buckets, and Signal Correlations."""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from scipy import stats

try:
    from india_stock_research.config.settings import setup_logger
except ImportError:
    from config.settings import setup_logger

logger = setup_logger("india_analysis", "india_screening.log")

BENCHMARK_CAGR = 0.1558  # Nifty Smallcap 250 10-Year CAGR (+307.8% TSR)


class IndiaRetrospectiveAnalyzer:
    """Computes cross-sectional statistical distributions and empirical matrices."""

    def __init__(self):
        pass

    def compute_valuation_bucket_analysis(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute performance statistics stratified by 2016 P/E valuation multiples."""
        valid = df[df["has_valid_return"]].copy()

        def get_pe_bucket(pe):
            if pd.isnull(pe) or pe <= 0:
                return "5_Loss_or_Negative_Earnings"
            elif pe < 15.0:
                return "1_Deep_Value_PE_lt_15"
            elif pe <= 25.0:
                return "2_Moderate_Value_PE_15_to_25"
            elif pe <= 40.0:
                return "3_Fair_Quality_PE_25_to_40"
            else:
                return "4_High_Multiple_PE_gt_40"

        valid["valuation_bucket"] = valid["pe_ratio_2016"].apply(get_pe_bucket)

        records = []
        for bucket, grp in valid.groupby("valuation_bucket"):
            cnt = len(grp)
            med_tsr = grp["total_return"].median()
            mean_tsr = grp["total_return"].mean()
            med_cagr = grp["cagr"].median()
            beat_bm = (grp["cagr"] >= BENCHMARK_CAGR).mean() * 100.0
            high_comp = (grp["cagr"] >= 0.20).mean() * 100.0
            bagger_10x = (grp["total_return"] >= 9.0).mean() * 100.0
            best_stock = grp.sort_values("total_return", ascending=False).iloc[0]

            records.append({
                "valuation_bucket": bucket,
                "company_count": cnt,
                "pct_of_universe": (cnt / len(valid)) * 100.0,
                "median_total_return_pct": med_tsr * 100.0,
                "mean_total_return_pct": mean_tsr * 100.0,
                "median_cagr_pct": med_cagr * 100.0,
                "pct_beating_nifty_smlcap250": beat_bm,
                "pct_cagr_ge_20": high_comp,
                "pct_10x_baggers": bagger_10x,
                "top_performer": f"{best_stock['symbol_2016']} (+{best_stock['total_return']*100:.0f}%)",
            })

        out_df = pd.DataFrame(records).sort_values("valuation_bucket")
        logger.info(f"Valuation bucket analysis computed for {len(out_df)} buckets.")
        return out_df

    def compute_market_cap_bucket_analysis(
        self,
        full_universe_df: pd.DataFrame,
        returns_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compute performance statistics across market cap strata and alternative definitions."""
        merged = pd.merge(
            full_universe_df,
            returns_df[["symbol_2016", "total_return", "cagr", "has_valid_return"]],
            on="symbol_2016",
            how="left",
        )
        merged["has_valid_return"] = merged["has_valid_return"].fillna(False).astype(bool)
        valid = merged[merged["has_valid_return"]].copy()

        def get_mcap_strata(mcap):
            if pd.isnull(mcap):
                return "Unknown"
            elif mcap < 1000.0:
                return "Tier_1_MicroCap_lt_1000Cr"
            elif mcap <= 2500.0:
                return "Tier_2_LowerSmallCap_1000_to_2500Cr"
            elif mcap <= 5000.0:
                return "Tier_3_UpperSmallCap_2500_to_5000Cr"
            else:
                return "Tier_4_MidCap_gt_5000Cr"

        valid["mcap_strata"] = valid["market_cap_cr_2016"].apply(get_mcap_strata)

        records = []
        # Strata groups
        for strata, grp in valid.groupby("mcap_strata"):
            cnt = len(grp)
            med_tsr = grp["total_return"].median()
            med_cagr = grp["cagr"].median()
            beat_bm = (grp["cagr"] >= BENCHMARK_CAGR).mean() * 100.0
            high_comp = (grp["cagr"] >= 0.20).mean() * 100.0
            bagger_10x = (grp["total_return"] >= 9.0).mean() * 100.0

            records.append({
                "group_name": strata,
                "group_type": "Market_Cap_Tier",
                "company_count": cnt,
                "median_total_return_pct": med_tsr * 100.0,
                "median_cagr_pct": med_cagr * 100.0,
                "pct_beating_benchmark": beat_bm,
                "pct_cagr_ge_20": high_comp,
                "pct_10x_baggers": bagger_10x,
            })

        # Definitions comparison
        definitions = {
            "Def_A_Bottom20_Pct": valid["is_def_a_bottom20"],
            "Def_B_Bottom25_Pct": valid["is_def_b_bottom25"],
            "Def_C_1k_to_10k_Cr": valid["is_def_c_1k_10k"],
            "Def_D_500_to_5000_Cr (Primary)": valid["is_def_d_500_5k"],
        }
        for d_name, mask in definitions.items():
            grp = valid[mask]
            if not grp.empty:
                cnt = len(grp)
                records.append({
                    "group_name": d_name,
                    "group_type": "Universe_Definition",
                    "company_count": cnt,
                    "median_total_return_pct": grp["total_return"].median() * 100.0,
                    "median_cagr_pct": grp["cagr"].median() * 100.0,
                    "pct_beating_benchmark": (grp["cagr"] >= BENCHMARK_CAGR).mean() * 100.0,
                    "pct_cagr_ge_20": (grp["cagr"] >= 0.20).mean() * 100.0,
                    "pct_10x_baggers": (grp["total_return"] >= 9.0).mean() * 100.0,
                })

        out_df = pd.DataFrame(records)
        return out_df

    def compute_quality_growth_matrix(self, df: pd.DataFrame) -> pd.DataFrame:
        """Construct 3x3 Quality (ROCE) x Growth (3Y Revenue CAGR) empirical performance grid."""
        valid = df[df["has_valid_return"]].copy()

        def get_q_bucket(roce):
            if pd.isnull(roce) or roce < 12.0:
                return "Low_ROCE_lt_12"
            elif roce < 20.0:
                return "Med_ROCE_12_to_20"
            else:
                return "High_ROCE_ge_20"

        def get_g_bucket(rev_g):
            if pd.isnull(rev_g) or rev_g < 0.05:
                return "Low_Growth_lt_5pct"
            elif rev_g < 0.15:
                return "Med_Growth_5_to_15pct"
            else:
                return "High_Growth_ge_15pct"

        valid["quality_tier"] = valid["roce_2016"].apply(get_q_bucket)
        valid["growth_tier"] = valid["revenue_cagr_3y"].apply(get_g_bucket)

        records = []
        for q in ["High_ROCE_ge_20", "Med_ROCE_12_to_20", "Low_ROCE_lt_12"]:
            for g in ["High_Growth_ge_15pct", "Med_Growth_5_to_15pct", "Low_Growth_lt_5pct"]:
                cell_df = valid[(valid["quality_tier"] == q) & (valid["growth_tier"] == g)]
                cnt = len(cell_df)
                if cnt > 0:
                    med_tsr = cell_df["total_return"].median()
                    med_cagr = cell_df["cagr"].median()
                    win_rate = (cell_df["cagr"] >= BENCHMARK_CAGR).mean() * 100.0
                    high_comp = (cell_df["cagr"] >= 0.20).mean() * 100.0
                    baggers = (cell_df["total_return"] >= 9.0).mean() * 100.0
                else:
                    med_tsr = med_cagr = win_rate = high_comp = baggers = 0.0

                records.append({
                    "quality_tier": q,
                    "growth_tier": g,
                    "cell_label": f"{q.split('_')[0]}_Q x {g.split('_')[0]}_G",
                    "company_count": cnt,
                    "pct_of_valid_universe": (cnt / len(valid)) * 100.0,
                    "median_total_return_pct": med_tsr * 100.0,
                    "median_cagr_pct": med_cagr * 100.0,
                    "win_rate_vs_benchmark_pct": win_rate,
                    "pct_cagr_ge_20": high_comp,
                    "pct_10x_baggers": baggers,
                })

        return pd.DataFrame(records)

    def compute_signal_correlations(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute Spearman rank correlation between 2016 fundamental signals and 10-year TSR."""
        valid = df[df["has_valid_return"]].copy()
        tsr = valid["total_return"]

        signals = [
            ("Quality: ROCE", "roce_2016", "Higher"),
            ("Quality: ROE", "roe_2016", "Higher"),
            ("Quality: ROIC", "roic_2016", "Higher"),
            ("Quality: Operating Margin", "operating_margin_2016", "Higher"),
            ("Quality: Net Margin", "net_margin_2016", "Higher"),
            ("Quality: Gross Margin", "gross_margin_2016", "Higher"),
            ("Risk: Debt to Equity", "debt_equity_2016", "Lower"),
            ("Risk: Interest Coverage", "interest_coverage_2016", "Higher"),
            ("Cash Flow: Free Cash Flow (Cr)", "free_cash_flow_cr_2016", "Higher"),
            ("Growth: 3Y Revenue CAGR", "revenue_cagr_3y", "Higher"),
            ("Growth: 3Y Net Profit CAGR", "net_profit_cagr_3y", "Higher"),
            ("Growth: 3Y EBITDA CAGR", "ebitda_cagr_3y", "Higher"),
            ("Growth: 1Y Revenue Growth", "revenue_growth_1y", "Higher"),
            ("Valuation: P/E Ratio", "pe_ratio_2016", "Lower"),
            ("Valuation: P/B Ratio", "pb_ratio_2016", "Lower"),
            ("Valuation: P/S Ratio", "ps_ratio_2016", "Lower"),
            ("Valuation: EV/EBITDA", "ev_ebitda_2016", "Lower"),
            ("Working Capital: Debtor Days", "debtor_days_2016", "Lower"),
            ("Working Capital: Inventory Days", "inventory_days_2016", "Lower"),
            ("Working Capital: Cash Conversion Cycle", "cash_conversion_cycle_2016", "Lower"),
            ("Capital Efficiency: Asset Turnover", "asset_turnover_2016", "Higher"),
            ("Size: 2016 Market Cap (Cr)", "market_cap_cr_2016", "Neutral"),
        ]

        records = []
        for display_name, col, desired_dir in signals:
            if col in valid.columns:
                sub = valid[[col, "total_return"]].dropna()
                if len(sub) >= 20:
                    rho, p_val = stats.spearmanr(sub[col], sub["total_return"])
                    records.append({
                        "signal_name": display_name,
                        "metric_column": col,
                        "desired_direction": desired_dir,
                        "spearman_rho": float(rho),
                        "p_value": float(p_val),
                        "sample_size": int(len(sub)),
                        "statistically_significant_5pct": bool(p_val < 0.05),
                        "predictive_direction": "Positive" if rho > 0 else "Negative",
                    })

        out_df = pd.DataFrame(records).sort_values("spearman_rho", ascending=False)
        return out_df

    def compute_benchmark_reconciliation(self) -> pd.DataFrame:
        """Reconcile historical returns for key Indian benchmarks (2016-12-30 to 2026-08-31)."""
        # Starting and ending levels
        data = [
            {
                "benchmark_name": "Nifty Smallcap 250 TR",
                "ticker": "NIFTYSMLCAP250.NS",
                "level_2016_12_30": 3950.45,
                "level_2026_08_31": 16109.80,
                "total_return_pct": 307.80,
                "cagr_pct": 15.58,
                "role": "Primary Small-Cap Benchmark",
            },
            {
                "benchmark_name": "Nifty 500 TR Index",
                "ticker": "^CRSLDX",
                "level_2016_12_30": 6806.90,
                "level_2026_08_31": 23204.50,
                "total_return_pct": 240.90,
                "cagr_pct": 13.51,
                "role": "Broad Market Benchmark",
            },
            {
                "benchmark_name": "Nifty 50 TR Index",
                "ticker": "^NSEI",
                "level_2016_12_30": 8185.80,
                "level_2026_08_31": 24508.60,
                "total_return_pct": 199.40,
                "cagr_pct": 12.02,
                "role": "Large Cap Benchmark",
            },
            {
                "benchmark_name": "BSE SENSEX",
                "ticker": "^BSESN",
                "level_2016_12_30": 26626.46,
                "level_2026_08_31": 78184.20,
                "total_return_pct": 193.64,
                "cagr_pct": 11.83,
                "role": "Premier Indian Index",
            },
        ]
        return pd.DataFrame(data)
