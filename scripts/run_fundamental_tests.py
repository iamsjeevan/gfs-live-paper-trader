"""Point-in-Time Fundamental Filtering Backtest and Evaluation.

Compares technical-only baseline against individual and combination fundamental screens.
Calculates trade-level statistics, portfolio simulation (₹10L initial, 10 slots),
in-sample vs out-of-sample stability, sector exposure, rejected trades analysis,
and the BLISSGVS audit.
"""

import sqlite3
import time
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

DB_PATH = "data/indian_market.db"
OLD_DB_PATH = "data/nse_stocks_all_years.db"
BASELINE_CSV = "reports/indian_market_complete_trades.csv"

def run_fundamental_evaluation():
    t0 = time.time()
    print("=" * 80)
    print("POINT-IN-TIME FUNDAMENTAL FILTERING RESEARCH & BACKTEST")
    print("=" * 80)

    # 1. Load Baseline Trades
    print("\n[1/7] Loading Baseline Technical Trades...")
    trades_df = pd.read_csv(BASELINE_CSV)
    print(f"Loaded {len(trades_df):,} baseline trades from {BASELINE_CSV}.")

    # Connect to databases
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Load securities mapping
    sec_df = pd.read_sql("SELECT security_id, symbol FROM securities;", conn)
    trades_df = trades_df.merge(sec_df, left_on="Ticker", right_on="symbol", how="left")
    if "symbol" in trades_df.columns:
        trades_df = trades_df.drop(columns=["symbol"])

    # Load point-in-time fundamentals
    print("\n[2/7] Loading and Merging Point-in-Time Fundamentals...")
    ratios_df = pd.read_sql("SELECT * FROM fundamental_ratios;", conn)
    annual_df = pd.read_sql("SELECT security_id, fiscal_year, eps FROM fundamental_annual;", conn)
    fund_df = ratios_df.merge(annual_df, on=["security_id", "fiscal_year"], how="left")
    # Drop security_id from fund_df to avoid duplicate column suffix during merge_asof
    fund_df = fund_df.drop(columns=["security_id"])

    # Load shares outstanding & sector from old db
    conn_old = sqlite3.connect(OLD_DB_PATH)
    val_df = pd.read_sql("SELECT symbol as Ticker, shares_outstanding FROM technical_valuation_data;", conn_old)
    cm_df = pd.read_sql("SELECT symbol as Ticker, sector, sub_sector FROM company_master;", conn_old)
    conn_old.close()

    # Sort fundamentals by availability_date for point-in-time merge_asof
    fund_df["availability_date"] = pd.to_datetime(fund_df["availability_date"])
    fund_df = fund_df.sort_values("availability_date").reset_index(drop=True)

    trades_df["entry_dt"] = pd.to_datetime(trades_df["Entry Date"])
    trades_df = trades_df.sort_values("Entry Date").reset_index(drop=True)

    # Perform point-in-time merge_asof
    enriched_trades = pd.merge_asof(
        trades_df,
        fund_df,
        left_by="Ticker",
        right_by="symbol",
        left_on="entry_dt",
        right_on="availability_date",
        direction="backward"
    )
    if "symbol" in enriched_trades.columns:
        enriched_trades = enriched_trades.drop(columns=["symbol"])

    # Merge shares outstanding and sector
    enriched_trades = enriched_trades.merge(val_df, on="Ticker", how="left")
    enriched_trades = enriched_trades.merge(cm_df, on="Ticker", how="left")

    # Calculate point-in-time PE, PEG, and Market Cap (in Cr)
    enriched_trades["fundamental_snapshot_date"] = enriched_trades["availability_date"].dt.strftime("%Y-%m-%d")
    enriched_trades["pe"] = np.where(
        (enriched_trades["eps"] > 0) & enriched_trades["eps"].notna(),
        enriched_trades["Entry Price"] / enriched_trades["eps"],
        np.nan
    )
    enriched_trades["peg"] = np.where(
        (enriched_trades["pe"] > 0) & (enriched_trades["profit_cagr_3y"] > 0),
        enriched_trades["pe"] / enriched_trades["profit_cagr_3y"],
        np.nan
    )
    enriched_trades["mcap_cr"] = (enriched_trades["shares_outstanding"] * enriched_trades["Entry Price"]) / 1e7
    enriched_trades["sector"] = enriched_trades["sector"].fillna("Unclassified")

    # Rename / align growth columns
    enriched_trades["profit_growth"] = enriched_trades["profit_cagr_3y"]
    enriched_trades["sales_growth"] = enriched_trades["sales_cagr_3y"]
    enriched_trades["promoter_pledge"] = np.nan
    enriched_trades["institutional_holding"] = np.nan

    print(f"Point-in-time fundamentals attached. Total trades: {len(enriched_trades):,}.")
    print(f"Trades with available historical fundamentals: {enriched_trades['fiscal_year'].notna().sum():,} ({enriched_trades['fiscal_year'].notna().mean()*100:.1f}%).")

    # 3. Define Strategy Filters
    # Note: Missing fundamental data fails the filter (strictly zero look-ahead, no free pass)
    filters = {
        "1. Technical Only (Baseline)": pd.Series(True, index=enriched_trades.index),
        "2. Technical + ROE > 15%": enriched_trades["roe"] > 15.0,
        "3. Technical + ROE > 20%": enriched_trades["roe"] > 20.0,
        "4. Technical + ROCE > 15%": enriched_trades["roce"] > 15.0,
        "5. Technical + ROCE > 20%": enriched_trades["roce"] > 20.0,
        "6. Technical + Profit CAGR 3Y > 15%": enriched_trades["profit_cagr_3y"] > 15.0,
        "7. Technical + Profit CAGR 3Y > 25%": enriched_trades["profit_cagr_3y"] > 25.0,
        "8. Technical + Sales CAGR 3Y > 10%": enriched_trades["sales_cagr_3y"] > 10.0,
        "9. Technical + Sales CAGR 3Y > 15%": enriched_trades["sales_cagr_3y"] > 15.0,
        "10. Technical + Interest Coverage > 3": enriched_trades["interest_coverage"] > 3.0,
        "11. Technical + P/E < 50": (enriched_trades["pe"] > 0) & (enriched_trades["pe"] < 50.0),
        "12. Technical + PEG < 1.5": (enriched_trades["peg"] > 0) & (enriched_trades["peg"] < 1.5),
        "13. Combo A (ROCE>20 & ROE>20)": (enriched_trades["roce"] > 20.0) & (enriched_trades["roe"] > 20.0),
        "14. Combo B (Combo A + Profit>25)": (enriched_trades["roce"] > 20.0) & (enriched_trades["roe"] > 20.0) & (enriched_trades["profit_cagr_3y"] > 25.0),
        "15. Combo C (Combo A + Sales>15)": (enriched_trades["roce"] > 20.0) & (enriched_trades["roe"] > 20.0) & (enriched_trades["sales_cagr_3y"] > 15.0),
        "16. Combo D (Combo A + Both Growth)": (enriched_trades["roce"] > 20.0) & (enriched_trades["roe"] > 20.0) & (enriched_trades["profit_cagr_3y"] > 25.0) & (enriched_trades["sales_cagr_3y"] > 15.0),
        "17. Combo E (Combo A + IntCov>3 + PE<50)": (enriched_trades["roce"] > 20.0) & (enriched_trades["roe"] > 20.0) & (enriched_trades["interest_coverage"] > 3.0) & (enriched_trades["pe"] > 0) & (enriched_trades["pe"] < 50.0),
        "18. Combo F (Full Fundamental Screen)": (
            (enriched_trades["mcap_cr"] > 1000.0) &
            (enriched_trades["roce"] > 20.0) &
            (enriched_trades["roe"] > 20.0) &
            (enriched_trades["interest_coverage"] > 3.0) &
            ((enriched_trades["profit_cagr_3y"] > 25.0) | (enriched_trades["sales_cagr_3y"] > 15.0)) &
            (enriched_trades["pe"] > 0) & (enriched_trades["pe"] < 50.0) &
            (enriched_trades["peg"] > 0) & (enriched_trades["peg"] < 1.5)
        ),
    }

    # Store filter masks in enriched_trades
    filter_col_mapping = {
        "1. Technical Only (Baseline)": "pass_baseline",
        "2. Technical + ROE > 15%": "pass_roe_gt_15",
        "3. Technical + ROE > 20%": "pass_roe_gt_20",
        "4. Technical + ROCE > 15%": "pass_roce_gt_15",
        "5. Technical + ROCE > 20%": "pass_roce_gt_20",
        "6. Technical + Profit CAGR 3Y > 15%": "pass_profit_cagr_gt_15",
        "7. Technical + Profit CAGR 3Y > 25%": "pass_profit_cagr_gt_25",
        "8. Technical + Sales CAGR 3Y > 10%": "pass_sales_cagr_gt_10",
        "9. Technical + Sales CAGR 3Y > 15%": "pass_sales_cagr_gt_15",
        "10. Technical + Interest Coverage > 3": "pass_interest_coverage_gt_3",
        "11. Technical + P/E < 50": "pass_pe_lt_50",
        "12. Technical + PEG < 1.5": "pass_peg_lt_1_5",
        "13. Combo A (ROCE>20 & ROE>20)": "pass_combo_a",
        "14. Combo B (Combo A + Profit>25)": "pass_combo_b",
        "15. Combo C (Combo A + Sales>15)": "pass_combo_c",
        "16. Combo D (Combo A + Both Growth)": "pass_combo_d",
        "17. Combo E (Combo A + IntCov>3 + PE<50)": "pass_combo_e",
        "18. Combo F (Full Fundamental Screen)": "pass_combo_f",
    }

    for name, mask in filters.items():
        col_name = filter_col_mapping[name]
        enriched_trades[col_name] = pd.Series(mask, index=enriched_trades.index).fillna(False)

    # 4. Load Traded Securities Daily OHLCV for Mark-to-Market Simulation
    print("\n[3/7] Loading Traded Securities Daily OHLCV for Mark-to-Market Portfolio Simulation...")
    daily_df = pd.read_sql(
        "SELECT security_id, date, close FROM daily_ohlcv WHERE security_id IN (SELECT DISTINCT security_id FROM trades) ORDER BY date ASC;",
        conn
    )
    all_trading_days = sorted(daily_df["date"].unique())
    total_years = (pd.to_datetime(all_trading_days[-1]) - pd.to_datetime(all_trading_days[0])).days / 365.25
    price_dict = dict(zip(zip(daily_df["security_id"], daily_df["date"]), daily_df["close"]))
    print(f"Loaded {len(daily_df):,} daily candles across {len(all_trading_days)} trading days ({total_years:.2f} years).")

    # 5. Portfolio Simulation Function (Version B: ₹10L initial, 10 slots @ ₹1L max)
    def simulate_portfolio(valid_trades):
        STARTING_CAPITAL = 1_000_000.0
        MAX_POSITIONS = 10
        SLOT_SIZE_PCT = 1.0 / MAX_POSITIONS

        valid_records = valid_trades.to_dict(orient="records")
        trades_by_entry = {}
        for t in valid_records:
            trades_by_entry.setdefault(t["Entry Date"], []).append(t)

        portfolio_cash = STARTING_CAPITAL
        open_positions = {}
        daily_records = []
        trades_executed = 0

        for d in all_trading_days:
            # A. Close positions exiting on date d
            to_close = []
            for sec_id, pos in open_positions.items():
                if pos["exit_date"] == d:
                    portfolio_cash += pos["shares"] * pos["exit_price"]
                    to_close.append(sec_id)
            for sec_id in to_close:
                del open_positions[sec_id]

            # B. Enter new positions on date d
            if d in trades_by_entry:
                entries = trades_by_entry[d]
                entries = sorted(entries, key=lambda x: x["Monthly RSI"], reverse=True)
                for t in entries:
                    if len(open_positions) < MAX_POSITIONS and portfolio_cash >= 1000.0:
                        slot_cash = min(portfolio_cash, STARTING_CAPITAL * SLOT_SIZE_PCT)
                        entry_p = t["Entry Price"]
                        shares = slot_cash / entry_p
                        portfolio_cash -= (shares * entry_p)
                        open_positions[t["security_id"]] = {
                            "shares": shares,
                            "entry_p": entry_p,
                            "exit_date": t["Exit Date"],
                            "exit_price": t["Exit Price"]
                        }
                        trades_executed += 1

            # C. Mark to market
            pos_val = sum(pos["shares"] * price_dict.get((sec_id, d), pos["entry_p"]) for sec_id, pos in open_positions.items())
            total_eq = portfolio_cash + pos_val
            daily_records.append({
                "date": d,
                "equity": total_eq,
                "cash": portfolio_cash,
                "invested": pos_val,
                "positions": len(open_positions)
            })

        p_df = pd.DataFrame(daily_records)
        final_eq = p_df.iloc[-1]["equity"]
        tot_ret = (final_eq - STARTING_CAPITAL) / STARTING_CAPITAL * 100.0
        cagr = ((final_eq / STARTING_CAPITAL) ** (1.0 / total_years) - 1.0) * 100.0
        peaks = p_df["equity"].cummax()
        max_dd = ((p_df["equity"] - peaks) / peaks).min() * 100.0
        exposure = (p_df["invested"] / p_df["equity"]).mean() * 100.0
        return final_eq, tot_ret, cagr, max_dd, exposure, trades_executed, p_df

    # 6. Execute Simulations & Trade-Level Analysis
    print("\n[4/7] Running Trade-Level and Portfolio Simulations across all strategies...")
    summary_results = []
    rejected_trade_analysis = []
    equity_curves = {}

    for name, raw_mask in filters.items():
        mask = pd.Series(raw_mask, index=enriched_trades.index).fillna(False)
        passed_trades = enriched_trades[mask].copy()
        rejected_trades = enriched_trades[~mask].copy()

        n_passed = len(passed_trades)
        n_rejected = len(rejected_trades)
        pct_rejected = (n_rejected / len(enriched_trades)) * 100.0

        # Trade-level statistics
        ret_series = passed_trades["Return %"]
        wins = ret_series[ret_series > 0]
        losses = ret_series[ret_series < 0]

        win_rate = (len(wins) / n_passed * 100.0) if n_passed > 0 else 0.0
        avg_ret = ret_series.mean() if n_passed > 0 else 0.0
        med_ret = ret_series.median() if n_passed > 0 else 0.0
        avg_win = wins.mean() if len(wins) > 0 else 0.0
        avg_loss = losses.mean() if len(losses) > 0 else 0.0
        win_loss_ratio = (avg_win / abs(avg_loss)) if (len(losses) > 0 and abs(avg_loss) > 0) else 0.0
        profit_factor = (wins.sum() / abs(losses.sum())) if (len(losses) > 0 and abs(losses.sum()) > 0) else 0.0

        holding_days = passed_trades["Holding Days"]
        avg_holding = holding_days.mean() if n_passed > 0 else 0.0
        med_holding = holding_days.median() if n_passed > 0 else 0.0

        # Consecutive wins / losses
        is_win = (ret_series > 0).astype(int).tolist()
        max_cons_wins = 0
        max_cons_losses = 0
        cur_w = 0
        cur_l = 0
        for w in is_win:
            if w == 1:
                cur_w += 1
                cur_l = 0
                max_cons_wins = max(max_cons_wins, cur_w)
            else:
                cur_l += 1
                cur_w = 0
                max_cons_losses = max(max_cons_losses, cur_l)

        # Portfolio simulation
        final_eq, p_tot_ret, p_cagr, p_max_dd, p_exposure, p_trades_taken, p_df = simulate_portfolio(passed_trades)
        equity_curves[name] = p_df

        # Expectancy
        expectancy = (win_rate / 100.0 * avg_win) + ((100.0 - win_rate) / 100.0 * avg_loss)

        summary_results.append({
            "Strategy": name,
            "Total Trades": n_passed,
            "Rejected %": pct_rejected,
            "Win Rate (%)": win_rate,
            "Avg Return (%)": avg_ret,
            "Median Return (%)": med_ret,
            "Avg Win (%)": avg_win,
            "Avg Loss (%)": avg_loss,
            "Profit Factor": profit_factor,
            "Ending Equity (INR)": final_eq,
            "Total Return (%)": p_tot_ret,
            "CAGR (%)": p_cagr,
            "Max Drawdown (%)": p_max_dd,
            "Avg Exposure (%)": p_exposure,
            "Portfolio Trades Taken": p_trades_taken,
            "Avg Holding Days": avg_holding,
            "Max Cons Wins": max_cons_wins,
            "Max Cons Losses": max_cons_losses,
            "Expectancy (%)": expectancy
        })

        # Rejected trades breakdown
        if n_rejected > 0:
            rej_ret = rejected_trades["Return %"]
            rej_wins = (rej_ret > 0).sum()
            rej_losses = (rej_ret < 0).sum()
            rej_win_rate = (rej_wins / n_rejected) * 100.0
            rej_avg_ret = rej_ret.mean()
            rej_winners_gt_50 = (rej_ret >= 50.0).sum()
            rej_winners_gt_100 = (rej_ret >= 100.0).sum()
            rej_blissgvs = ("BLISSGVS" in rejected_trades["Ticker"].values)
        else:
            rej_wins = 0
            rej_losses = 0
            rej_win_rate = 0.0
            rej_avg_ret = 0.0
            rej_winners_gt_50 = 0
            rej_winners_gt_100 = 0
            rej_blissgvs = False

        rejected_trade_analysis.append({
            "Strategy": name,
            "Rejected Count": n_rejected,
            "Rejected %": pct_rejected,
            "Rejected Would-Be Wins": rej_wins,
            "Rejected Would-Be Losses": rej_losses,
            "Rejected Win Rate (%)": rej_win_rate,
            "Rejected Avg Return (%)": rej_avg_ret,
            "Rejected Winners > 50%": rej_winners_gt_50,
            "Rejected Winners > 100%": rej_winners_gt_100,
            "Rejected BLISSGVS?": "YES (Missed +109.8%)" if rej_blissgvs else "NO"
        })

    summary_df = pd.DataFrame(summary_results)
    rejected_df = pd.DataFrame(rejected_trade_analysis)

    # 7. In-Sample vs Out-of-Sample Validation (Temporal Stability)
    print("\n[5/7] Evaluating In-Sample (2018-2022) vs Out-of-Sample (2023-2026) Stability...")
    is_mask = enriched_trades["Entry Date"] <= "2022-12-31"
    oos_mask = enriched_trades["Entry Date"] > "2022-12-31"

    temporal_results = []
    for name, raw_mask in filters.items():
        mask = pd.Series(raw_mask, index=enriched_trades.index).fillna(False)
        
        # IS
        is_trades = enriched_trades[mask & is_mask]
        is_ret = is_trades["Return %"]
        is_wr = (is_ret > 0).mean() * 100 if len(is_trades) > 0 else 0
        is_avg = is_ret.mean() if len(is_trades) > 0 else 0
        is_pf = (is_ret[is_ret > 0].sum() / abs(is_ret[is_ret < 0].sum())) if (len(is_ret[is_ret < 0]) > 0 and abs(is_ret[is_ret < 0].sum()) > 0) else 0

        # OOS
        oos_trades = enriched_trades[mask & oos_mask]
        oos_ret = oos_trades["Return %"]
        oos_wr = (oos_ret > 0).mean() * 100 if len(oos_trades) > 0 else 0
        oos_avg = oos_ret.mean() if len(oos_trades) > 0 else 0
        oos_pf = (oos_ret[oos_ret > 0].sum() / abs(oos_ret[oos_ret < 0].sum())) if (len(oos_ret[oos_ret < 0]) > 0 and abs(oos_ret[oos_ret < 0].sum()) > 0) else 0

        temporal_results.append({
            "Strategy": name,
            "IS Trades (2018-22)": len(is_trades),
            "IS WinRate (%)": is_wr,
            "IS AvgRet (%)": is_avg,
            "IS ProfitFactor": is_pf,
            "OOS Trades (2023-26)": len(oos_trades),
            "OOS WinRate (%)": oos_wr,
            "OOS AvgRet (%)": oos_avg,
            "OOS ProfitFactor": oos_pf,
        })
    temporal_df = pd.DataFrame(temporal_results)

    # 8. Sector Exposure Analysis
    print("\n[6/7] Performing Sector Exposure and Performance Breakdown...")
    sector_summary = []
    for sector, group in enriched_trades.groupby("sector"):
        if len(group) < 20:
            continue
        base_trades = len(group)
        base_ret = group["Return %"].mean()
        base_wr = (group["Return %"] > 0).mean() * 100
        
        # Check pass rate for Combo A and Full Screen
        combo_a_group = group[group["pass_combo_a"]]
        full_group = group[group["pass_combo_f"]]
        
        sector_summary.append({
            "Sector": sector,
            "Baseline Trades": base_trades,
            "Baseline Win Rate (%)": base_wr,
            "Baseline Avg Return (%)": base_ret,
            "Combo A Trades": len(combo_a_group),
            "Combo A Pass %": (len(combo_a_group) / base_trades) * 100,
            "Combo A Avg Return (%)": combo_a_group["Return %"].mean() if len(combo_a_group) > 0 else 0,
            "Full Screen Trades": len(full_group),
            "Full Screen Pass %": (len(full_group) / base_trades) * 100,
            "Full Screen Avg Return (%)": full_group["Return %"].mean() if len(full_group) > 0 else 0,
        })
    sector_df = pd.DataFrame(sector_summary).sort_values("Baseline Trades", ascending=False)

    # 9. BLISSGVS Audit
    print("\n[7/7] Detailed Point-in-Time Audit of BLISSGVS Trade...")
    bliss_row = enriched_trades[enriched_trades["Ticker"] == "BLISSGVS"].iloc[0]
    bliss_details = {
        "Ticker": bliss_row["Ticker"],
        "Entry Date": bliss_row["Entry Date"],
        "Entry Price": bliss_row["Entry Price"],
        "Exit Date": bliss_row["Exit Date"],
        "Exit Price": bliss_row["Exit Price"],
        "Return %": bliss_row["Return %"],
        "Holding Days": bliss_row["Holding Days"],
        "Reporting Fiscal Year Available at Entry": bliss_row["fiscal_year"],
        "Financial Availability Date": bliss_row["fundamental_snapshot_date"],
        "ROE (%)": bliss_row["roe"],
        "ROCE (%)": bliss_row["roce"],
        "3Y Profit CAGR (%)": bliss_row["profit_cagr_3y"],
        "3Y Sales CAGR (%)": bliss_row["sales_cagr_3y"],
        "Interest Coverage": bliss_row["interest_coverage"],
        "EPS (INR)": bliss_row["eps"],
        "P/E Ratio": bliss_row["pe"],
        "PEG Ratio": bliss_row["peg"],
        "Market Cap (Cr)": bliss_row["mcap_cr"],
        "Filter Pass Status": {
            "ROE > 15%": bool(bliss_row["pass_roe_gt_15"]),
            "ROE > 20%": bool(bliss_row["pass_roe_gt_20"]),
            "ROCE > 15%": bool(bliss_row["pass_roce_gt_15"]),
            "ROCE > 20%": bool(bliss_row["pass_roce_gt_20"]),
            "Profit CAGR > 15%": bool(bliss_row["pass_profit_cagr_gt_15"]),
            "Profit CAGR > 25%": bool(bliss_row["pass_profit_cagr_gt_25"]),
            "Sales CAGR > 10%": bool(bliss_row["pass_sales_cagr_gt_10"]),
            "Sales CAGR > 15%": bool(bliss_row["pass_sales_cagr_gt_15"]),
            "Interest Coverage > 3": bool(bliss_row["pass_interest_coverage_gt_3"]),
            "P/E < 50": bool(bliss_row["pass_pe_lt_50"]),
            "PEG < 1.5": bool(bliss_row["pass_peg_lt_1_5"]),
            "Combo A": bool(bliss_row["pass_combo_a"]),
            "Combo B": bool(bliss_row["pass_combo_b"]),
            "Combo C": bool(bliss_row["pass_combo_c"]),
            "Combo D": bool(bliss_row["pass_combo_d"]),
            "Combo E": bool(bliss_row["pass_combo_e"]),
            "Combo F (Full Screen)": bool(bliss_row["pass_combo_f"]),
        }
    }

    # Save Enriched Trades to SQLite
    print("\nSaving enriched trades table to data/indian_market.db...")
    cur.execute("DROP TABLE IF EXISTS trades_fundamental_analysis;")
    
    save_cols = [
        "Ticker", "Company", "Monthly Signal Date", "Monthly RSI", "Monthly EMA9",
        "Entry Date", "Entry Price", "Exit Date", "Exit Price", "Exit Reason",
        "Return %", "Holding Days", "fundamental_snapshot_date", "fiscal_year",
        "roe", "roce", "debt_equity", "current_ratio", "net_margin", "interest_coverage",
        "profit_cagr_3y", "sales_cagr_3y", "eps", "pe", "peg", "mcap_cr", "sector",
        "promoter_pledge", "institutional_holding"
    ]
    # Add filter pass columns
    filter_cols = list(filter_col_mapping.values())
    final_save_cols = save_cols + filter_cols
    enriched_trades[final_save_cols].to_sql("trades_fundamental_analysis", conn, if_exists="replace", index=False)
    conn.commit()
    conn.close()

    # Save CSV reports
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(reports_dir / "fundamental_comparison_matrix.csv", index=False)
    rejected_df.to_csv(reports_dir / "fundamental_rejected_trades_analysis.csv", index=False)
    temporal_df.to_csv(reports_dir / "fundamental_temporal_stability.csv", index=False)
    sector_df.to_csv(reports_dir / "fundamental_sector_breakdown.csv", index=False)

    # Plot Equity Curves
    fig_dir = reports_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(14, 8))
    
    key_curves = [
        ("1. Technical Only (Baseline)", "black", 2.2, "-"),
        ("3. Technical + ROE > 20%", "blue", 1.5, "--"),
        ("5. Technical + ROCE > 20%", "purple", 1.5, "--"),
        ("11. Technical + P/E < 50", "green", 1.5, "-."),
        ("13. Combo A (ROCE>20 & ROE>20)", "darkorange", 1.8, "-"),
        ("17. Combo E (Combo A + IntCov>3 + PE<50)", "crimson", 1.8, "-"),
        ("18. Combo F (Full Fundamental Screen)", "teal", 2.0, "-"),
    ]
    
    for s_name, col, lw, ls in key_curves:
        if s_name in equity_curves:
            curve_df = equity_curves[s_name]
            plt.plot(pd.to_datetime(curve_df["date"]), curve_df["equity"] / 100000.0, label=f"{s_name} (End: ₹{curve_df.iloc[-1]['equity']/100000.0:.1f}L)", color=col, linewidth=lw, linestyle=ls)

    plt.title("Indian Equities Strategy: Baseline vs Point-in-Time Fundamental Screens (₹10 Lakh Initial Capital)", fontsize=13, fontweight="bold")
    plt.xlabel("Date", fontsize=11)
    plt.ylabel("Portfolio Equity (₹ Lakhs)", fontsize=11)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(loc="upper left", fontsize=9)
    plt.tight_layout()
    chart_path = fig_dir / "fundamental_filter_portfolio_comparison.png"
    plt.savefig(chart_path, dpi=300)
    plt.close()
    print(f"Equity curve comparison chart saved to {chart_path}.")

    print(f"\nAll evaluations complete in {time.time() - t0:.2f}s.")
    return summary_df, rejected_df, temporal_df, sector_df, bliss_details

if __name__ == "__main__":
    s_df, r_df, t_df, sec_df, b_info = run_fundamental_evaluation()
    print("\nSUMMARY MATRIX:")
    print(s_df[["Strategy", "Total Trades", "Rejected %", "Win Rate (%)", "Avg Return (%)", "Profit Factor", "CAGR (%)", "Max Drawdown (%)", "Total Return (%)"]].to_string(index=False))
    print("\nREJECTED TRADES ANALYSIS:")
    print(r_df[["Strategy", "Rejected Count", "Rejected Would-Be Wins", "Rejected Would-Be Losses", "Rejected Win Rate (%)", "Rejected Avg Return (%)", "Rejected Winners > 50%", "Rejected BLISSGVS?"]].to_string(index=False))
    print("\nBLISSGVS AUDIT DETAILS:")
    for k, v in b_info.items():
        if k != "Filter Pass Status":
            print(f"  {k}: {v}")
    print("  Filter Pass Status:")
    for fk, fv in b_info["Filter Pass Status"].items():
        print(f"    {fk:35s}: {'PASS' if fv else 'FAIL'}")
