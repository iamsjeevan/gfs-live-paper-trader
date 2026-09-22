"""Winner Capture Audit and Forensic Root-Cause Analysis for Indian Equities."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

try:
    from india_stock_research.config.settings import setup_logger
except ImportError:
    from config.settings import setup_logger

logger = setup_logger("india_capture", "india_screening.log")


class IndiaWinnerCaptureAuditor:
    """Performs granular attribution and forensic categorization for 2016-2026 winners."""

    def __init__(self):
        pass

    def assign_winner_groups(self, returns_df: pd.DataFrame) -> pd.DataFrame:
        """Assign W1, W2, W3, W4 winner group labels based solely on realized 10-year TSR."""
        df = returns_df.copy()
        valid = df[df["has_valid_return"]].sort_values("total_return", ascending=False)

        top10_syms = set(valid.head(10)["symbol_2016"])
        top25_syms = set(valid.head(25)["symbol_2016"])
        top50_syms = set(valid.head(50)["symbol_2016"])

        df["winner_group"] = "NON_WINNER"
        for idx, row in df.iterrows():
            sym = row["symbol_2016"]
            cagr = row.get("cagr")
            has_ret = row.get("has_valid_return", False)

            if not has_ret:
                df.at[idx, "winner_group"] = "MISSING_DELISTED"
            elif sym in top10_syms:
                df.at[idx, "winner_group"] = "W1_TOP10"
            elif sym in top25_syms:
                df.at[idx, "winner_group"] = "W2_TOP25"
            elif sym in top50_syms:
                df.at[idx, "winner_group"] = "W3_TOP50"
            elif cagr is not None and cagr >= 0.20:
                df.at[idx, "winner_group"] = "W4_CAGR_GE_20"
            elif cagr is not None and cagr >= 0.15:
                df.at[idx, "winner_group"] = "W4_CAGR_15_20"
            elif cagr is not None and cagr > 0.0:
                df.at[idx, "winner_group"] = "LOW_POSITIVE_CAGR"
            else:
                df.at[idx, "winner_group"] = "NEGATIVE_RETURN"

        # Flags for membership
        df["is_w1"] = df["symbol_2016"].isin(top10_syms)
        df["is_w2"] = df["symbol_2016"].isin(top25_syms)
        df["is_w3"] = df["symbol_2016"].isin(top50_syms)
        df["is_w4"] = df["cagr"].fillna(0) >= 0.15
        df["is_high_compounder"] = df["cagr"].fillna(0) >= 0.20

        logger.info(
            f"Winner labels assigned: W1={df['is_w1'].sum()}, W2={df['is_w2'].sum()}, "
            f"W3={df['is_w3'].sum()}, W4(>=15%)={df['is_w4'].sum()}"
        )
        return df

    def categorize_winner_capture(
        self,
        labeled_df: pd.DataFrame,
        fund_df: pd.DataFrame,
        v1_scored_df: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Classify each winner into Category 1 (Found), Category 2 (Ranked Low),
        Category 3 (Rejected by Hard Filters), or Category 4 (Data/Sector Excluded).

        Also generates detailed root-cause records for missed winners in W1, W2, W3.
        """
        # Merge labeled returns with fundamentals
        merged = pd.merge(
            labeled_df,
            fund_df[[
                "symbol_2016", "roe_2016", "roce_2016", "roic_2016", "debt_equity_2016",
                "operating_margin_2016", "net_margin_2016", "free_cash_flow_cr_2016",
                "operating_cash_flow_cr_2016", "revenue_cagr_3y", "net_profit_cagr_3y",
                "pe_ratio_2016", "pb_ratio_2016", "ev_ebitda_2016", "debtor_days_2016",
                "inventory_days_2016", "cash_conversion_cycle_2016", "is_financial"
            ]],
            on="symbol_2016",
            how="left",
            suffixes=("", "_fund"),
        )

        v1_rank_map = {}
        if not v1_scored_df.empty:
            for _, r in v1_scored_df.iterrows():
                v1_rank_map[r["symbol_2016"]] = {
                    "rank_a": r.get("rank_strat_a_V1"),
                    "rank_b": r.get("rank_strat_b_V1"),
                    "rank_c": r.get("rank_strat_c_V1"),
                    "rank_d": r.get("rank_strat_d_V1"),
                    "score_a": r.get("score_strat_a_V1"),
                    "score_b": r.get("score_strat_b_V1"),
                    "score_c": r.get("score_strat_c_V1"),
                    "score_d": r.get("score_strat_d_V1"),
                }

        capture_records = []
        missed_records = []

        for _, row in merged.iterrows():
            sym = row["symbol_2016"]
            is_fin = bool(row.get("is_financial", False))
            roe = row.get("roe_2016")
            roce = row.get("roce_2016")
            de = row.get("debt_equity_2016")
            fcf = row.get("free_cash_flow_cr_2016")
            rev = row.get("revenue_cr_2016")
            mcap = row.get("market_cap_cr_2016")
            cagr = row.get("cagr")
            w_grp = row.get("winner_group", "NON_WINNER")

            # Evaluate filter rejection reasons
            filter_failures = []
            if is_fin:
                filter_failures.append("Financial Sector (Excluded)")
            if pd.isnull(roe) or roe < 12.0:
                val_s = f"{roe:.1f}%" if pd.notnull(roe) else "Missing"
                filter_failures.append(f"ROE < 12.0% ({val_s})")
            if pd.isnull(roce) or roce < 10.0:
                val_s = f"{roce:.1f}%" if pd.notnull(roce) else "Missing"
                filter_failures.append(f"ROCE < 10.0% ({val_s})")
            if pd.notnull(de) and de > 1.50:
                filter_failures.append(f"Debt/Equity > 1.50 ({de:.2f})")
            if pd.isnull(fcf) or fcf <= 0.0:
                val_s = f"₹{fcf:.1f} Cr" if pd.notnull(fcf) else "Missing"
                filter_failures.append(f"FCF <= 0 ({val_s})")
            if pd.isnull(rev) or rev <= 0.0:
                filter_failures.append("Revenue <= 0")

            passed_quality = len(filter_failures) == 0
            v1_info = v1_rank_map.get(sym)

            # Determine capture category for Strategy D (and general)
            cat_strat_d = "CATEGORY_3_REJECTED"
            rank_d = v1_info.get("rank_d") if v1_info else None
            rank_a = v1_info.get("rank_a") if v1_info else None
            rank_b = v1_info.get("rank_b") if v1_info else None
            rank_c = v1_info.get("rank_c") if v1_info else None

            if not row.get("has_valid_return", False):
                cat_strat_d = "CATEGORY_4_DATA_PROBLEM"
            elif is_fin:
                cat_strat_d = "CATEGORY_4_EXCLUDED_SECTOR"
            elif passed_quality:
                if rank_d is not None and rank_d <= 10:
                    cat_strat_d = "CATEGORY_1_FOUND_TOP10"
                elif rank_d is not None and rank_d <= 25:
                    cat_strat_d = "CATEGORY_1_FOUND_TOP25"
                else:
                    cat_strat_d = "CATEGORY_2_RANKED_LOW"
            else:
                cat_strat_d = "CATEGORY_3_REJECTED"

            # Determine Archetype Classification
            archetype = "Type_E_Unclassified"
            if pd.notnull(roce) and roce >= 18.0 and pd.notnull(de) and de <= 0.50 and pd.notnull(fcf) and fcf > 0:
                archetype = "Type_A_Existing_Compounder"
            elif pd.notnull(roe) and (roe < 5.0 or np.isnan(roe)) and pd.notnull(cagr) and cagr >= 0.25:
                archetype = "Type_B_Turnaround_Inflection"
            elif pd.notnull(roce) and roce >= 12.0 and pd.notnull(fcf) and fcf <= 0 and pd.notnull(cagr) and cagr >= 0.20:
                archetype = "Type_C_Capex_Reinvestor_Secular_Growth"
            elif row.get("sector") in ["Metals & Mining", "Real Estate", "Infrastructure", "Power", "Construction Materials"]:
                archetype = "Type_D_Cyclical_Commodity_Recovery"
            elif mcap is not None and mcap < 1000.0:
                archetype = "Type_E_Microcap_Optionality"
            else:
                archetype = "Type_A_Existing_Compounder" if passed_quality else "Type_B_Turnaround_Inflection"

            capture_records.append({
                "isin": row.get("isin"),
                "symbol_2016": sym,
                "modern_symbol": row.get("modern_symbol", sym),
                "company_name": row.get("company_name", sym),
                "sector": row.get("sector", "Unclassified"),
                "winner_group": w_grp,
                "total_return": row.get("total_return"),
                "cagr": cagr,
                "has_valid_return": row.get("has_valid_return", False),
                "market_cap_cr_2016": mcap,
                "passed_quality_filters_v1": passed_quality,
                "capture_category": cat_strat_d,
                "rank_strat_a": rank_a,
                "rank_strat_b": rank_b,
                "rank_strat_c": rank_c,
                "rank_strat_d": rank_d,
                "archetype": archetype,
                "filter_rejection_reasons": "; ".join(filter_failures) if filter_failures else "None (Passed)",
                "roe_2016": roe,
                "roce_2016": roce,
                "debt_equity_2016": de,
                "free_cash_flow_cr_2016": fcf,
                "pe_ratio_2016": row.get("pe_ratio_2016"),
                "revenue_cagr_3y": row.get("revenue_cagr_3y"),
            })

            # Missed winner audit record (W1, W2, W3)
            if row.get("is_w3", False):
                is_captured = (rank_d is not None and rank_d <= 10) or (rank_a is not None and rank_a <= 10)
                if not is_captured:
                    primary_root_cause = "Passed quality filters, but factor score ranked outside Top 10"
                    if filter_failures:
                        primary_root_cause = f"Failed hard quality filter: {filter_failures[0]}"
                    elif rank_d is not None:
                        primary_root_cause = f"Ranked #{rank_d} in Strategy D (score: {v1_info.get('score_d', 0):.1f})"

                    missed_records.append({
                        "symbol_2016": sym,
                        "company_name": row.get("company_name", sym),
                        "winner_group": w_grp,
                        "cagr": cagr,
                        "total_return": row.get("total_return"),
                        "market_cap_cr_2016": mcap,
                        "sector": row.get("sector", "Unclassified"),
                        "archetype": archetype,
                        "primary_root_cause": primary_root_cause,
                        "all_filter_failures": "; ".join(filter_failures) if filter_failures else "None",
                        "rank_strat_d": rank_d,
                        "rank_strat_a": rank_a,
                        "roe_2016": roe,
                        "roce_2016": roce,
                        "debt_equity_2016": de,
                        "fcf_cr_2016": fcf,
                        "pe_ratio_2016": row.get("pe_ratio_2016"),
                        "rev_cagr_3y": row.get("revenue_cagr_3y"),
                    })

        capture_df = pd.DataFrame(capture_records)
        missed_df = pd.DataFrame(missed_records)
        logger.info(f"Capture analysis complete. Total evaluated: {len(capture_df)}, Missed W1-W3: {len(missed_df)}")
        return capture_df, missed_df
