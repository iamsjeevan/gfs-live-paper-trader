"""Point-in-Time 2016 Fundamental Data Extraction and Factor Calculation Engine.

STRICT ZERO LOOK-AHEAD GUARANTEE:
Only financial statements and ratios for fiscal years ended on or before 2016-12-31
(primarily FY2016 ended March 31, 2016, and historical FY2013-FY2015) are accessed.
Under NO circumstances is any financial data for year > 2016 queried or evaluated.
"""

from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

try:
    from india_stock_research.config.settings import MAIN_DB_PATH, setup_logger
except ImportError:
    from config.settings import MAIN_DB_PATH, setup_logger

logger = setup_logger("india_fundamentals", "india_screening.log")


class IndiaPointInTimeFundamentalsEngine:
    """Extracts and computes point-in-time 2016 fundamental metrics for Indian equities."""

    def __init__(self, db_path: Optional[Path] = None, screen_date: str = "2016-12-31"):
        self.db_path = db_path or MAIN_DB_PATH
        self.screen_date = screen_date
        self.screen_year = int(screen_date[:4])  # 2016

    def compute_universe_fundamentals(self, universe_df: pd.DataFrame) -> pd.DataFrame:
        """Compute comprehensive point-in-time fundamental profile for each company.

        Args:
            universe_df: DataFrame containing 2016 universe candidates with market_cap_cr_2016.

        Returns:
            DataFrame with enriched fundamental metrics.
        """
        logger.info(f"Extracting point-in-time fundamental metrics for {len(universe_df)} Indian companies...")
        conn = sqlite3.connect(self.db_path)

        # 1. Load FY16 Income Statement (filing year <= 2016)
        pl_query = """
            SELECT symbol, year, total_revenue, cost_of_materials, purchase_of_stock_in_trade,
                   employee_cost, finance_costs, depreciation_amortisation, other_expenses,
                   total_expenses, profit_before_tax, tax_expense, net_profit
            FROM financial_income_statement
            WHERE year <= 2016
            ORDER BY symbol, year ASC
        """
        pl_df = pd.read_sql(pl_query, conn)

        # 2. Load FY16 Balance Sheet (filing year <= 2016)
        bs_query = """
            SELECT symbol, year, share_capital, reserves_surplus, total_shareholders_funds,
                   long_term_borrowings, short_term_borrowings, total_debt, trade_payables,
                   tangible_assets, inventories, trade_receivables, cash_equivalents,
                   total_current_assets, total_current_liabilities, total_assets
            FROM financial_balance_sheet
            WHERE year <= 2016
            ORDER BY symbol, year ASC
        """
        bs_df = pd.read_sql(bs_query, conn)

        # 3. Load FY16 Pre-calculated Ratios (filing year <= 2016)
        ratios_query = """
            SELECT symbol, year, roe, roce, debt_equity, current_ratio, net_margin, operating_margin
            FROM financial_ratios
            WHERE year <= 2016
            ORDER BY symbol, year ASC
        """
        ratios_df = pd.read_sql(ratios_query, conn)
        conn.close()

        # Group by symbol for fast historical lookup
        pl_by_sym = {sym: group.set_index("year") for sym, group in pl_df.groupby("symbol")}
        bs_by_sym = {sym: group.set_index("year") for sym, group in bs_df.groupby("symbol")}
        ratios_by_sym = {sym: group.set_index("year") for sym, group in ratios_df.groupby("symbol")}

        records = []
        for _, row in universe_df.iterrows():
            sym_2016 = row["symbol_2016"]
            modern_sym = row.get("modern_symbol", sym_2016)
            mcap_cr = row.get("market_cap_cr_2016")
            sector = str(row.get("sector", "Unclassified")).strip()
            is_financial = sector in ["Finance", "Banks", "Insurance", "Financial Services"]

            # Lookup symbol in database (try 2016 symbol, then modern symbol)
            pl_hist = pl_by_sym.get(sym_2016) if sym_2016 in pl_by_sym else pl_by_sym.get(modern_sym)
            bs_hist = bs_by_sym.get(sym_2016) if sym_2016 in bs_by_sym else bs_by_sym.get(modern_sym)
            ratios_hist = ratios_by_sym.get(sym_2016) if sym_2016 in ratios_by_sym else ratios_by_sym.get(modern_sym)

            # FY16 observations
            pl_16 = pl_hist.loc[2016].to_dict() if (pl_hist is not None and 2016 in pl_hist.index) else {}
            bs_16 = bs_hist.loc[2016].to_dict() if (bs_hist is not None and 2016 in bs_hist.index) else {}
            ratios_16 = ratios_hist.loc[2016].to_dict() if (ratios_hist is not None and 2016 in ratios_hist.index) else {}

            # Prior year observations for growth & changes
            pl_15 = pl_hist.loc[2015].to_dict() if (pl_hist is not None and 2015 in pl_hist.index) else {}
            bs_15 = bs_hist.loc[2015].to_dict() if (bs_hist is not None and 2015 in bs_hist.index) else {}
            pl_13 = pl_hist.loc[2013].to_dict() if (pl_hist is not None and 2013 in pl_hist.index) else {}

            # Core Financial Facts (FY16)
            rev_16 = pl_16.get("total_revenue")
            net_profit_16 = pl_16.get("net_profit")
            pbt_16 = pl_16.get("profit_before_tax")
            fin_costs_16 = pl_16.get("finance_costs") or 0.0
            depr_16 = pl_16.get("depreciation_amortisation") or 0.0
            tax_16 = pl_16.get("tax_expense") or 0.0
            mat_cost_16 = pl_16.get("cost_of_materials") or 0.0
            stock_trade_16 = pl_16.get("purchase_of_stock_in_trade") or 0.0

            # Operating Profit and EBIT
            ebit_16 = None
            if pbt_16 is not None:
                ebit_16 = pbt_16 + (fin_costs_16 if fin_costs_16 > 0 else 0.0)
            ebitda_16 = None
            if ebit_16 is not None and depr_16 is not None:
                ebitda_16 = ebit_16 + depr_16

            # Balance Sheet Core Facts (FY16)
            equity_16 = bs_16.get("total_shareholders_funds")
            debt_16 = bs_16.get("total_debt")
            cash_16 = bs_16.get("cash_equivalents") or 0.0
            rec_16 = bs_16.get("trade_receivables") or 0.0
            inv_16 = bs_16.get("inventories") or 0.0
            pay_16 = bs_16.get("trade_payables") or 0.0
            tangible_16 = bs_16.get("tangible_assets")
            assets_16 = bs_16.get("total_assets")

            # Quality Metrics
            roe_val = ratios_16.get("roe")
            if (roe_val is None or np.isnan(roe_val)) and equity_16 and equity_16 > 0 and net_profit_16 is not None:
                roe_val = (net_profit_16 / equity_16) * 100.0

            roce_val = ratios_16.get("roce")
            if (roce_val is None or np.isnan(roce_val)) and ebit_16 is not None and equity_16 is not None:
                capital_employed = equity_16 + (debt_16 or 0.0)
                if capital_employed > 0:
                    roce_val = (ebit_16 / capital_employed) * 100.0

            # ROIC calculation: NOPAT / Invested Capital
            roic_val = None
            if ebit_16 is not None and equity_16 is not None:
                tax_rate = (tax_16 / pbt_16) if (pbt_16 and pbt_16 > 0 and tax_16 >= 0) else 0.30
                tax_rate = min(max(tax_rate, 0.0), 0.45)
                nopat = ebit_16 * (1.0 - tax_rate)
                invested_capital = equity_16 + (debt_16 or 0.0) - cash_16
                if invested_capital > 0:
                    roic_val = (nopat / invested_capital) * 100.0
                elif roce_val is not None:
                    roic_val = roce_val

            # Margins
            op_margin_val = ratios_16.get("operating_margin")
            if (op_margin_val is None or np.isnan(op_margin_val)) and ebit_16 is not None and rev_16 and rev_16 > 0:
                op_margin_val = (ebit_16 / rev_16) * 100.0

            net_margin_val = ratios_16.get("net_margin")
            if (net_margin_val is None or np.isnan(net_margin_val)) and net_profit_16 is not None and rev_16 and rev_16 > 0:
                net_margin_val = (net_profit_16 / rev_16) * 100.0

            gross_margin_val = None
            if rev_16 and rev_16 > 0:
                cogs = mat_cost_16 + stock_trade_16
                gross_margin_val = ((rev_16 - cogs) / rev_16) * 100.0 if cogs > 0 else op_margin_val

            # Leverage
            de_val = ratios_16.get("debt_equity")
            if (de_val is None or np.isnan(de_val)) and equity_16 and equity_16 > 0:
                de_val = (debt_16 or 0.0) / equity_16

            net_debt_val = ((debt_16 or 0.0) - cash_16) if debt_16 is not None else None

            # Interest Coverage
            interest_coverage_val = None
            if ebit_16 is not None:
                if fin_costs_16 and fin_costs_16 > 0:
                    interest_coverage_val = ebit_16 / fin_costs_16
                else:
                    interest_coverage_val = 999.0  # Zero interest cost

            # Working Capital and Cash Conversion Cycle
            debtor_days = (rec_16 / rev_16 * 365.0) if rev_16 and rev_16 > 0 else None
            inventory_days = (inv_16 / rev_16 * 365.0) if rev_16 and rev_16 > 0 else None
            creditor_days = (pay_16 / rev_16 * 365.0) if rev_16 and rev_16 > 0 else None
            ccc_days = None
            if debtor_days is not None and inventory_days is not None and creditor_days is not None:
                ccc_days = debtor_days + inventory_days - creditor_days

            wc_16 = (rec_16 + inv_16 - pay_16) if rev_16 else None
            wc_to_rev = (wc_16 / rev_16) if wc_16 is not None and rev_16 and rev_16 > 0 else None
            asset_turnover = (rev_16 / assets_16) if rev_16 and assets_16 and assets_16 > 0 else None

            # Cash Flow & Free Cash Flow (FCF) Estimation
            rec_15 = bs_15.get("trade_receivables") or 0.0
            inv_15 = bs_15.get("inventories") or 0.0
            pay_15 = bs_15.get("trade_payables") or 0.0
            wc_15 = rec_15 + inv_15 - pay_15 if bs_15 else None
            tangible_15 = bs_15.get("tangible_assets")

            delta_wc = (wc_16 - wc_15) if (wc_16 is not None and wc_15 is not None) else 0.0
            capex = 0.0
            if tangible_16 is not None and tangible_15 is not None:
                capex = max(0.0, (tangible_16 - tangible_15) + (depr_16 or 0.0))
            else:
                capex = depr_16 or 0.0

            ocf_est = None
            fcf_est = None
            if net_profit_16 is not None:
                ocf_est = net_profit_16 + (depr_16 or 0.0) - delta_wc
                fcf_est = ocf_est - capex

            # Growth Metrics (FY13 -> FY16 3-Year CAGR, and FY15 -> FY16 1-Year Growth)
            rev_13 = pl_13.get("total_revenue")
            rev_cagr_3y = None
            if rev_16 and rev_13 and rev_16 > 0 and rev_13 > 0:
                rev_cagr_3y = ((rev_16 / rev_13) ** (1.0 / 3.0)) - 1.0

            profit_13 = pl_13.get("net_profit")
            profit_cagr_3y = None
            if net_profit_16 and profit_13 and net_profit_16 > 0 and profit_13 > 0:
                profit_cagr_3y = ((net_profit_16 / profit_13) ** (1.0 / 3.0)) - 1.0

            rev_15 = pl_15.get("total_revenue")
            rev_growth_1y = None
            if rev_16 and rev_15 and rev_16 > 0 and rev_15 > 0:
                rev_growth_1y = (rev_16 / rev_15) - 1.0

            # EBITDA 3Y CAGR
            ebitda_13 = None
            if pl_13.get("profit_before_tax") is not None:
                ebitda_13 = pl_13.get("profit_before_tax") + (pl_13.get("finance_costs") or 0.0) + (pl_13.get("depreciation_amortisation") or 0.0)
            ebitda_cagr_3y = None
            if ebitda_16 and ebitda_13 and ebitda_16 > 0 and ebitda_13 > 0:
                ebitda_cagr_3y = ((ebitda_16 / ebitda_13) ** (1.0 / 3.0)) - 1.0

            # Valuation Multiples as of 2016-12-30 Close
            pe_ratio = None
            if mcap_cr and net_profit_16 and net_profit_16 > 0:
                pe_ratio = mcap_cr / net_profit_16

            pb_ratio = None
            if mcap_cr and equity_16 and equity_16 > 0:
                pb_ratio = mcap_cr / equity_16

            ps_ratio = None
            if mcap_cr and rev_16 and rev_16 > 0:
                ps_ratio = mcap_cr / rev_16

            ev_ebitda = None
            if mcap_cr and ebitda_16 and ebitda_16 > 0 and net_debt_val is not None:
                ev = mcap_cr + net_debt_val
                ev_ebitda = ev / ebitda_16

            # Financial Sector Specifics
            roa_val = None
            if is_financial and net_profit_16 is not None and assets_16 and assets_16 > 0:
                roa_val = (net_profit_16 / assets_16) * 100.0

            record = {
                "isin": row.get("isin"),
                "symbol_2016": sym_2016,
                "modern_symbol": modern_sym,
                "company_name": row.get("company_name", sym_2016),
                "sector": sector,
                "sub_sector": row.get("sub_sector", "Unclassified"),
                "is_financial": is_financial,
                "market_cap_cr_2016": mcap_cr,
                "price_2016_unadjusted": row.get("price_2016_unadjusted"),
                "revenue_cr_2016": rev_16,
                "net_profit_cr_2016": net_profit_16,
                "ebit_cr_2016": ebit_16,
                "ebitda_cr_2016": ebitda_16,
                "equity_cr_2016": equity_16,
                "debt_cr_2016": debt_16,
                "cash_cr_2016": cash_16,
                "net_debt_cr_2016": net_debt_val,
                "roe_2016": roe_val,
                "roce_2016": roce_val,
                "roic_2016": roic_val,
                "operating_margin_2016": op_margin_val,
                "net_margin_2016": net_margin_val,
                "gross_margin_2016": gross_margin_val,
                "debt_equity_2016": de_val,
                "interest_coverage_2016": interest_coverage_val,
                "operating_cash_flow_cr_2016": ocf_est,
                "free_cash_flow_cr_2016": fcf_est,
                "revenue_cagr_3y": rev_cagr_3y,
                "net_profit_cagr_3y": profit_cagr_3y,
                "ebitda_cagr_3y": ebitda_cagr_3y,
                "revenue_growth_1y": rev_growth_1y,
                "pe_ratio_2016": pe_ratio,
                "pb_ratio_2016": pb_ratio,
                "ps_ratio_2016": ps_ratio,
                "ev_ebitda_2016": ev_ebitda,
                "debtor_days_2016": debtor_days,
                "inventory_days_2016": inventory_days,
                "creditor_days_2016": creditor_days,
                "cash_conversion_cycle_2016": ccc_days,
                "working_capital_to_revenue_2016": wc_to_rev,
                "asset_turnover_2016": asset_turnover,
                "roa_2016": roa_val,
                "lifecycle_status": row.get("lifecycle_status", "ACTIVE"),
                "is_eligible_smallcap": row.get("is_eligible_smallcap", False),
            }
            records.append(record)

        res_df = pd.DataFrame(records)
        logger.info(f"Fundamental calculation completed. Total companies processed: {len(res_df)}")
        return res_df
