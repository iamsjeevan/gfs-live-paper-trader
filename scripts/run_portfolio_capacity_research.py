"""Portfolio Capacity and Signal Ranking Research Suite.

Evaluates:
1. Simultaneous Signal Sets & Congestion
2. Portfolio Capacity Sweep (5, 10, 20, 30, 50, 100 positions)
3. Technical & Fundamental Signal Ranking Methods (RSI, Breakout, Rel Vol, EMA distances, Quality, Hybrid)
4. Realistic Execution (Fees, Slippage, Liquidity Turnover)
5. Out-of-Sample Stability (2018-2022 vs 2023-2026)
6. Representative Historical Date Selection Showcase
"""

import sqlite3
import time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import rankdata
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

DB_PATH = "data/indian_market.db"
BASELINE_CSV = "reports/indian_market_complete_trades.csv"

def prepare_opportunity_dataset():
    """Load and enrich complete trade opportunity set with ranking metrics."""
    conn = sqlite3.connect(DB_PATH)
    trades = pd.read_csv(BASELINE_CSV)
    sec = pd.read_sql("SELECT security_id, symbol FROM securities;", conn)
    trades = trades.merge(sec, left_on="Ticker", right_on="symbol", how="left")
    if "symbol" in trades.columns:
        trades = trades.drop(columns=["symbol"])

    # Load 20-day average volume and turnover on Breakout Date
    q_vol = """
    SELECT security_id, date, volume,
           (volume * close) / 1e7 as turnover_cr,
           AVG(volume) OVER (PARTITION BY security_id ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) as avg_vol_20
    FROM daily_ohlcv
    WHERE security_id IN (SELECT DISTINCT security_id FROM trades);
    """
    vol_df = pd.read_sql(q_vol, conn)

    trades = trades.merge(vol_df, left_on=["security_id", "Breakout Date"], right_on=["security_id", "date"], how="left")
    trades["rel_volume"] = np.where(trades["avg_vol_20"] > 0, trades["volume"] / trades["avg_vol_20"], 1.0)
    trades["turnover_cr"] = trades["turnover_cr"].fillna(0.0)

    # Technical ranking metrics
    trades["breakout_strength"] = (trades["Entry Price"] - trades["Resistance"]) / trades["Resistance"] * 100.0
    trades["monthly_ema9_dist"] = (trades["Entry Price"] - trades["Monthly EMA9"]) / trades["Monthly EMA9"] * 100.0
    trades["daily_ema21_dist"] = (trades["Entry Price"] - trades["Daily EMA21 At Setup"]) / trades["Daily EMA21 At Setup"] * 100.0
    trades["is_etf"] = trades["Ticker"].str.contains("BEES|ETF|GOLD", regex=True)

    # Fundamental ranking metrics from trades_fundamental_analysis
    fund_cols = ["Ticker", "Entry Date", "mcap_cr", "roe", "roce", "profit_cagr_3y", "sales_cagr_3y", "interest_coverage", "pe", "sector"]
    col_str = ", ".join([f'"{c}"' for c in fund_cols])
    t_fund = pd.read_sql(f"SELECT {col_str} FROM trades_fundamental_analysis;", conn)
    conn.close()

    # Drop duplicate columns if any
    trades = trades.merge(t_fund, on=["Ticker", "Entry Date"], how="left")

    # Filter out ETFs for clean corporate equity backtest
    trades = trades[~trades["is_etf"]].reset_index(drop=True)

    # Calculate normalized percentile ranks (0.0 to 1.0) for composite scores
    def pct_rank(series, ascending=True):
        valid = series.dropna()
        if len(valid) == 0:
            return pd.Series(0.0, index=series.index)
        ranks = rankdata(valid if ascending else -valid, method="average") / len(valid)
        res = pd.Series(np.nan, index=series.index)
        res.loc[valid.index] = ranks
        return res.fillna(0.0)

    trades["rank_rsi"] = pct_rank(trades["Monthly RSI"], ascending=True)
    trades["rank_breakout"] = pct_rank(trades["breakout_strength"], ascending=True)
    trades["rank_vol"] = pct_rank(trades["rel_volume"], ascending=True)
    trades["rank_ema9"] = pct_rank(trades["monthly_ema9_dist"], ascending=True)
    trades["rank_ema21"] = pct_rank(trades["daily_ema21_dist"], ascending=True)

    # Combined Technical Score
    trades["combined_tech_score"] = (
        trades["rank_rsi"] + trades["rank_breakout"] + trades["rank_vol"] + trades["rank_ema9"]
    ) / 4.0

    # Fundamental ranks (missing data assigned 0.0)
    trades["rank_mcap"] = pct_rank(trades["mcap_cr"], ascending=True)
    trades["rank_profit_growth"] = pct_rank(trades["profit_cagr_3y"], ascending=True)
    trades["rank_sales_growth"] = pct_rank(trades["sales_cagr_3y"], ascending=True)
    trades["rank_roe"] = pct_rank(trades["roe"], ascending=True)
    trades["rank_roce"] = pct_rank(trades["roce"], ascending=True)
    trades["rank_int_cov"] = pct_rank(trades["interest_coverage"], ascending=True)
    
    # For P/E, lower positive P/E is better; non-positive or missing ranked 0.0
    valid_pe = trades["pe"][(trades["pe"] > 0) & (trades["pe"] < 200)]
    pe_ranks = pct_rank(valid_pe, ascending=False) # lower PE gets higher rank
    trades["rank_pe"] = pd.Series(0.0, index=trades.index)
    trades.loc[valid_pe.index, "rank_pe"] = pe_ranks

    # Fundamental Quality Score
    trades["fundamental_quality_score"] = (
        trades["rank_roe"] + trades["rank_roce"] + trades["rank_profit_growth"] + trades["rank_mcap"]
    ) / 4.0

    # Hybrid Score (50% Tech + 50% Fundamental Quality)
    trades["hybrid_score"] = 0.50 * trades["combined_tech_score"] + 0.50 * trades["fundamental_quality_score"]

    return trades

def run_portfolio_capacity_suite():
    t0 = time.time()
    print("=" * 80)
    print("PORTFOLIO CAPACITY & SIGNAL RANKING RESEARCH SUITE")
    print("=" * 80)

    trades = prepare_opportunity_dataset()
    print(f"Total corporate equity opportunity set: {len(trades):,} trades (ETFs excluded).")

    # Load daily price lookup
    conn = sqlite3.connect(DB_PATH)
    daily_df = pd.read_sql(
        "SELECT security_id, date, close FROM daily_ohlcv WHERE security_id IN (SELECT DISTINCT security_id FROM trades) ORDER BY date ASC;",
        conn
    )
    conn.close()

    all_trading_days = sorted(daily_df["date"].unique())
    total_years = (pd.to_datetime(all_trading_days[-1]) - pd.to_datetime(all_trading_days[0])).days / 365.25
    price_dict = dict(zip(zip(daily_df["security_id"], daily_df["date"]), daily_df["close"]))

    # Simulator Engine
    def simulate_capacity_portfolio(
        capacity=10,
        ranking_col="Monthly RSI",
        ranking_ascending=False,
        min_liquidity_cr=0.0,
        cost_bps=25.0, # 0.25% per side = 50 bps roundtrip (brokerage + STT + slippage)
        start_date="2018-01-01",
        end_date="2026-08-31"
    ):
        STARTING_CAPITAL = 1_000_000.0
        MAX_POSITIONS = capacity
        SLOT_SIZE = STARTING_CAPITAL / MAX_POSITIONS
        cost_mult_entry = 1.0 + (cost_bps / 10000.0) # pay slightly more on entry
        cost_mult_exit = 1.0 - (cost_bps / 10000.0)  # receive slightly less on exit

        # Filter trades by liquidity and date range
        valid_set = trades[
            (trades["turnover_cr"] >= min_liquidity_cr) &
            (trades["Entry Date"] >= start_date) &
            (trades["Entry Date"] <= end_date)
        ].copy()

        # Group pending trades by Entry Date
        trades_by_entry = {}
        for t in valid_set.to_dict(orient="records"):
            trades_by_entry.setdefault(t["Entry Date"], []).append(t)

        sim_days = [d for d in all_trading_days if d >= start_date and d <= end_date]
        years = (pd.to_datetime(sim_days[-1]) - pd.to_datetime(sim_days[0])).days / 365.25

        portfolio_cash = STARTING_CAPITAL
        open_positions = {}
        daily_records = []
        trades_taken = 0
        signals_generated = 0
        signals_rejected_capacity = 0
        realized_returns = []

        for d in sim_days:
            # 1. Close positions exiting on date d
            to_close = []
            for sec_id, pos in open_positions.items():
                if pos["exit_date"] == d:
                    net_exit_p = pos["exit_price"] * cost_mult_exit
                    proceeds = pos["shares"] * net_exit_p
                    portfolio_cash += proceeds
                    trade_ret = (net_exit_p - pos["effective_entry_p"]) / pos["effective_entry_p"] * 100.0
                    realized_returns.append(trade_ret)
                    to_close.append(sec_id)
            for sec_id in to_close:
                del open_positions[sec_id]

            # 2. Enter new positions on date d
            if d in trades_by_entry:
                day_signals = trades_by_entry[d]
                signals_generated += len(day_signals)
                
                # Sort day signals by chosen ranking method
                day_signals = sorted(
                    day_signals,
                    key=lambda x: (x[ranking_col] if pd.notna(x[ranking_col]) else (-1e9 if not ranking_ascending else 1e9)),
                    reverse=(not ranking_ascending)
                )

                for t in day_signals:
                    if len(open_positions) < MAX_POSITIONS and portfolio_cash >= 1000.0:
                        slot_cash = min(portfolio_cash, SLOT_SIZE)
                        raw_entry_p = t["Entry Price"]
                        effective_entry_p = raw_entry_p * cost_mult_entry
                        shares = slot_cash / effective_entry_p
                        portfolio_cash -= (shares * effective_entry_p)
                        open_positions[t["security_id"]] = {
                            "shares": shares,
                            "effective_entry_p": effective_entry_p,
                            "exit_date": t["Exit Date"],
                            "exit_price": t["Exit Price"]
                        }
                        trades_taken += 1
                    else:
                        signals_rejected_capacity += 1

            # 3. Mark to market
            pos_val = sum(pos["shares"] * price_dict.get((sec_id, d), pos["effective_entry_p"]) for sec_id, pos in open_positions.items())
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
        cagr = ((final_eq / STARTING_CAPITAL) ** (1.0 / years) - 1.0) * 100.0 if years > 0 else 0.0
        peaks = p_df["equity"].cummax()
        max_dd = ((p_df["equity"] - peaks) / peaks).min() * 100.0
        exposure = (p_df["invested"] / p_df["equity"]).mean() * 100.0
        cash_pct = 100.0 - exposure
        avg_positions = p_df["positions"].mean()

        ret_series = pd.Series(realized_returns)
        win_rate = (ret_series > 0).mean() * 100.0 if len(ret_series) > 0 else 0.0
        avg_trade_ret = ret_series.mean() if len(ret_series) > 0 else 0.0
        wins = ret_series[ret_series > 0]
        losses = ret_series[ret_series < 0]
        profit_factor = (wins.sum() / abs(losses.sum())) if (len(losses) > 0 and abs(losses.sum()) > 0) else 0.0

        return {
            "Ending Equity": final_eq,
            "Total Return (%)": tot_ret,
            "CAGR (%)": cagr,
            "Max Drawdown (%)": max_dd,
            "Profit Factor": profit_factor,
            "Win Rate (%)": win_rate,
            "Trades Taken": trades_taken,
            "Avg Trade Return (%)": avg_trade_ret,
            "Capital Exposure (%)": exposure,
            "Cash Pct (%)": cash_pct,
            "Avg Simultaneous Positions": avg_positions,
            "Signals Generated": signals_generated,
            "Signals Rejected Capacity": signals_rejected_capacity,
            "Equity Curve": p_df
        }

    # =========================================================================
    # EXPERIMENT 1: PORTFOLIO CAPACITY SWEEP (5, 10, 20, 30, 50, 100 positions)
    # =========================================================================
    print("\n[1/4] Running Portfolio Capacity Sweep (5, 10, 20, 30, 50, 100 positions)...")
    capacities = [5, 10, 20, 30, 50, 100]
    capacity_results = []
    cap_equity_curves = {}

    for cap in capacities:
        res = simulate_capacity_portfolio(capacity=cap, ranking_col="Monthly RSI", cost_bps=25.0, min_liquidity_cr=0.50)
        cap_equity_curves[cap] = res["Equity Curve"]
        capacity_results.append({
            "Capacity (Slots)": cap,
            "Slot Size (₹)": f"₹{1_000_000 // cap:,.0f}",
            "Ending Equity (₹)": res["Ending Equity"],
            "Total Return (%)": res["Total Return (%)"],
            "CAGR (%)": res["CAGR (%)"],
            "Max Drawdown (%)": res["Max Drawdown (%)"],
            "Profit Factor": res["Profit Factor"],
            "Win Rate (%)": res["Win Rate (%)"],
            "Trades Taken": res["Trades Taken"],
            "Avg Trade Return (%)": res["Avg Trade Return (%)"],
            "Capital Exposure (%)": res["Capital Exposure (%)"],
            "Cash Pct (%)": res["Cash Pct (%)"],
            "Avg Positions": res["Avg Simultaneous Positions"],
            "Signals Rejected (Full)": res["Signals Rejected Capacity"]
        })

    capacity_df = pd.DataFrame(capacity_results)

    # =========================================================================
    # EXPERIMENT 2: SIGNAL RANKING METHODS (Tested at Capacity = 10 and 20)
    # =========================================================================
    print("\n[2/4] Testing Technical, Fundamental, and Hybrid Ranking Methods...")
    ranking_methods = [
        ("A. Highest Monthly RSI", "Monthly RSI", False),
        ("B. Strongest Breakout (Entry/Res)", "breakout_strength", False),
        ("C. Highest Relative Volume", "rel_volume", False),
        ("D. Distance Above Monthly EMA9", "monthly_ema9_dist", False),
        ("E. Distance Above Daily EMA21", "daily_ema21_dist", False),
        ("F. Combined Quantitative Tech Score", "combined_tech_score", False),
        ("G. Market Cap (Large-Cap Bias)", "rank_mcap", False),
        ("H. Profit Growth (3Y CAGR)", "rank_profit_growth", False),
        ("I. Revenue Growth (3Y CAGR)", "rank_sales_growth", False),
        ("J. ROE (High Quality Bias)", "rank_roe", False),
        ("K. ROCE (High Efficiency Bias)", "rank_roce", False),
        ("L. Interest Coverage (Solvency)", "rank_int_cov", False),
        ("M. P/E Valuation (Lower P/E)", "rank_pe", False),
        ("N. Hybrid (50% Tech + 50% Fund)", "hybrid_score", False),
    ]

    ranking_results = []
    ranking_equity_curves = {}

    for label, col, asc in ranking_methods:
        # Test at Capacity = 10
        res10 = simulate_capacity_portfolio(capacity=10, ranking_col=col, ranking_ascending=asc, cost_bps=25.0, min_liquidity_cr=0.50)
        # Test at Capacity = 20
        res20 = simulate_capacity_portfolio(capacity=20, ranking_col=col, ranking_ascending=asc, cost_bps=25.0, min_liquidity_cr=0.50)
        
        ranking_equity_curves[label] = res10["Equity Curve"]

        ranking_results.append({
            "Ranking Method": label,
            "Cap 10 Total Return (%)": res10["Total Return (%)"],
            "Cap 10 CAGR (%)": res10["CAGR (%)"],
            "Cap 10 MaxDD (%)": res10["Max Drawdown (%)"],
            "Cap 10 PF": res10["Profit Factor"],
            "Cap 10 WinRate (%)": res10["Win Rate (%)"],
            "Cap 10 Trades": res10["Trades Taken"],
            "Cap 10 AvgRet (%)": res10["Avg Trade Return (%)"],
            "Cap 10 Exposure (%)": res10["Capital Exposure (%)"],
            "Cap 20 CAGR (%)": res20["CAGR (%)"],
            "Cap 20 MaxDD (%)": res20["Max Drawdown (%)"],
            "Cap 20 PF": res20["Profit Factor"],
            "Cap 20 Trades": res20["Trades Taken"],
        })

    ranking_df = pd.DataFrame(ranking_results)

    # =========================================================================
    # EXPERIMENT 3: IN-SAMPLE VS OUT-OF-SAMPLE STABILITY
    # =========================================================================
    print("\n[3/4] Evaluating In-Sample (2018-2022) vs Out-of-Sample (2023-2026) Stability for Ranking Methods...")
    temporal_ranking = []
    for label, col, asc in ranking_methods:
        # In-Sample: 2018-01-01 to 2022-12-31
        is_res = simulate_capacity_portfolio(capacity=10, ranking_col=col, ranking_ascending=asc, cost_bps=25.0, min_liquidity_cr=0.50, start_date="2018-01-01", end_date="2022-12-31")
        # Out-of-Sample: 2023-01-01 to 2026-08-31
        oos_res = simulate_capacity_portfolio(capacity=10, ranking_col=col, ranking_ascending=asc, cost_bps=25.0, min_liquidity_cr=0.50, start_date="2023-01-01", end_date="2026-08-31")

        temporal_ranking.append({
            "Ranking Method": label,
            "IS CAGR (%)": is_res["CAGR (%)"],
            "IS MaxDD (%)": is_res["Max Drawdown (%)"],
            "IS Profit Factor": is_res["Profit Factor"],
            "IS Win Rate (%)": is_res["Win Rate (%)"],
            "IS Trades": is_res["Trades Taken"],
            "OOS CAGR (%)": oos_res["CAGR (%)"],
            "OOS MaxDD (%)": oos_res["Max Drawdown (%)"],
            "OOS Profit Factor": oos_res["Profit Factor"],
            "OOS Win Rate (%)": oos_res["Win Rate (%)"],
            "OOS Trades": oos_res["Trades Taken"],
            "CAGR Delta (OOS - IS)": oos_res["CAGR (%)"] - is_res["CAGR (%)"]
        })

    temporal_df = pd.DataFrame(temporal_ranking)

    # =========================================================================
    # EXPERIMENT 4: REPRESENTATIVE HISTORICAL DATE SELECTION SHOWCASE
    # =========================================================================
    print("\n[4/4] Building Top Selections Showcase for High-Signal Historical Dates...")
    sample_dates = ["2023-12-22", "2024-01-19", "2024-04-16"]
    date_showcase = {}

    for s_date in sample_dates:
        day_trades = trades[trades["Entry Date"] == s_date].copy()
        
        # Rank under 4 distinct paradigms
        rank_rsi = day_trades.sort_values("Monthly RSI", ascending=False)["Ticker"].tolist()
        rank_vol = day_trades.sort_values("rel_volume", ascending=False)["Ticker"].tolist()
        rank_tech = day_trades.sort_values("combined_tech_score", ascending=False)["Ticker"].tolist()
        rank_hyb = day_trades.sort_values("hybrid_score", ascending=False)["Ticker"].tolist()

        date_showcase[s_date] = {
            "Total Signals": len(day_trades),
            "Top 10 by Monthly RSI": rank_rsi[:10],
            "Top 10 by Relative Volume": rank_vol[:10],
            "Top 10 by Combined Tech Score": rank_tech[:10],
            "Top 10 by Hybrid (Tech + Fundamentals)": rank_hyb[:10],
            "Complete Opportunity Set": day_trades[["Ticker", "Monthly RSI", "rel_volume", "breakout_strength", "roe", "roce", "pe"]].to_dict(orient="records")
        }

    # Save CSV reports
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    capacity_df.to_csv(reports_dir / "portfolio_capacity_sweep.csv", index=False)
    ranking_df.to_csv(reports_dir / "signal_ranking_methods_comparison.csv", index=False)
    temporal_df.to_csv(reports_dir / "ranking_temporal_stability.csv", index=False)

    # Plot 1: Portfolio Capacity Sweep Equity Curves
    fig_dir = reports_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(13, 7))
    colors = {5: "crimson", 10: "darkorange", 20: "blue", 30: "purple", 50: "teal", 100: "gray"}
    for cap, p_df in cap_equity_curves.items():
        plt.plot(pd.to_datetime(p_df["date"]), p_df["equity"] / 100000.0, label=f"{cap} Slots (End: ₹{p_df.iloc[-1]['equity']/100000.0:.1f}L, CAGR: {capacity_df[capacity_df['Capacity (Slots)']==cap]['CAGR (%)'].values[0]:.1f}%)", color=colors[cap], linewidth=1.8)

    plt.title("Portfolio Capacity Curve: 5 vs 10 vs 20 vs 30 vs 50 vs 100 Slots (₹10 Lakh Initial Capital)", fontsize=13, fontweight="bold")
    plt.xlabel("Date", fontsize=11)
    plt.ylabel("Portfolio Equity (₹ Lakhs)", fontsize=11)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(loc="upper left", fontsize=9)
    plt.tight_layout()
    chart1_path = fig_dir / "portfolio_capacity_sweep.png"
    plt.savefig(chart1_path, dpi=300)
    plt.close()

    # Plot 2: Key Ranking Methods Equity Curves
    plt.figure(figsize=(13, 7))
    key_ranks = [
        ("A. Highest Monthly RSI", "black", 2.0, "-"),
        ("B. Strongest Breakout (Entry/Res)", "red", 1.6, "--"),
        ("C. Highest Relative Volume", "blue", 1.6, "-."),
        ("F. Combined Quantitative Tech Score", "darkorange", 2.0, "-"),
        ("G. Market Cap (Large-Cap Bias)", "purple", 1.5, ":"),
        ("J. ROE (High Quality Bias)", "magenta", 1.5, "--"),
        ("N. Hybrid (50% Tech + 50% Fund)", "teal", 2.2, "-"),
    ]
    for lbl, col, lw, ls in key_ranks:
        if lbl in ranking_equity_curves:
            p_df = ranking_equity_curves[lbl]
            plt.plot(pd.to_datetime(p_df["date"]), p_df["equity"] / 100000.0, label=f"{lbl} (End: ₹{p_df.iloc[-1]['equity']/100000.0:.1f}L)", color=col, linewidth=lw, linestyle=ls)

    plt.title("Signal Ranking Comparison (10-Slot Portfolio, Realistic Execution with Slippage & Fees)", fontsize=13, fontweight="bold")
    plt.xlabel("Date", fontsize=11)
    plt.ylabel("Portfolio Equity (₹ Lakhs)", fontsize=11)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(loc="upper left", fontsize=9)
    plt.tight_layout()
    chart2_path = fig_dir / "signal_ranking_comparison.png"
    plt.savefig(chart2_path, dpi=300)
    plt.close()

    print(f"\nAll capacity and ranking evaluations completed in {time.time() - t0:.2f}s.")
    return capacity_df, ranking_df, temporal_df, date_showcase

if __name__ == "__main__":
    c_df, r_df, t_df, d_show = run_portfolio_capacity_suite()
    print("\n" + "=" * 90)
    print("TABLE 1: PORTFOLIO CAPACITY SWEEP (EQUAL ALLOCATION)")
    print("=" * 90)
    print(c_df.to_string(index=False))

    print("\n" + "=" * 90)
    print("TABLE 2: SIGNAL RANKING METHODS EVALUATION (10-SLOT & 20-SLOT PORTFOLIOS)")
    print("=" * 90)
    print(r_df.to_string(index=False))

    print("\n" + "=" * 90)
    print("TABLE 3: IN-SAMPLE VS OUT-OF-SAMPLE STABILITY (10-SLOT PORTFOLIO)")
    print("=" * 90)
    print(t_df.to_string(index=False))

    print("\n" + "=" * 90)
    print("TABLE 4: REPRESENTATIVE HISTORICAL DATE SELECTIONS")
    print("=" * 90)
    for dt, info in d_show.items():
        print(f"\nDate: {dt} (Total Simultaneous Signals: {info['Total Signals']})")
        print(f"  Top 10 by Monthly RSI:     {info['Top 10 by Monthly RSI']}")
        print(f"  Top 10 by Relative Volume: {info['Top 10 by Relative Volume']}")
        print(f"  Top 10 by Combined Tech:   {info['Top 10 by Combined Tech Score']}")
        print(f"  Top 10 by Hybrid Score:    {info['Top 10 by Hybrid (Tech + Fundamentals)']}")
