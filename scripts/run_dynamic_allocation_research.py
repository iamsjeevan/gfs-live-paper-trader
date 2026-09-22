"""Dynamic Capital Allocation and Signal Congestion Management Research Suite.

Comprehensive Evaluation:
1. Data Enrichment: Point-in-time Technical and Fundamental Metrics
2. Independent Factor Ranking Evaluation (13 individual factors + 3 composite scores)
3. Dynamic Capital Allocation Models:
   - Model A: Equal Weight (Baseline)
   - Model B1: Linear Rank Weighted
   - Model B2: Inverse Rank Weighted
   - Model C: Relative Volume Weighted
   - Model D: Composite Technical + Fundamental Score Weighted
4. Multi-Capacity Sweep: 10, 15, 20, 25, 30 Positions
5. Concentration Limits Sweep: 5%, 7.5%, 10%, 15% Max per Stock
6. Cash Reserve Buffers Sweep: 0%, 10%, 20% Cash Reserve
7. Signal Congestion Tracking: Full Opportunity Set, Signal Rejection by Reason
8. Multibagger Preservation Audit (>25%, >50%, >100%, >200%, BLISSGVS check)
9. In-Sample (2018-2022) vs Out-of-Sample (2023-2026) Temporal Split
10. Granular Risk Analytics: Worst Day, Worst Trade, Worst 10/20-Trade Sequence, Yearly Returns, Max Drawdown Duration & Recovery
11. High-Congestion Days Case Study (2023-12-22, 2024-01-19, 2024-04-16) with exact Rupee allocations
12. Publication-grade Equity & Drawdown Curves
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
    """Load and enrich complete corporate equity opportunity set with point-in-time metrics."""
    conn = sqlite3.connect(DB_PATH)
    trades = pd.read_csv(BASELINE_CSV)
    sec = pd.read_sql("SELECT security_id, symbol FROM securities;", conn)
    trades = trades.merge(sec, left_on="Ticker", right_on="symbol", how="left")
    if "symbol" in trades.columns:
        trades = trades.drop(columns=["symbol"])

    # Exclude ETFs for clean corporate equity universe
    trades["is_etf"] = trades["Ticker"].str.contains("BEES|ETF|GOLD", regex=True)
    trades = trades[~trades["is_etf"]].reset_index(drop=True)

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

    # Fundamental metrics from trades_fundamental_analysis
    fund_cols = ["Ticker", "Entry Date", "mcap_cr", "roe", "roce", "profit_cagr_3y", "sales_cagr_3y", "interest_coverage", "pe", "sector"]
    col_str = ", ".join([f'"{c}"' for c in fund_cols])
    t_fund = pd.read_sql(f"SELECT {col_str} FROM trades_fundamental_analysis;", conn)
    trades = trades.merge(t_fund, on=["Ticker", "Entry Date"], how="left")

    # Point-in-time YoY PAT Growth and Net Profit Positivity
    fa = pd.read_sql("SELECT security_id, symbol, fiscal_year, availability_date, net_profit FROM fundamental_annual ORDER BY security_id, fiscal_year;", conn)
    fa["prev_net_profit"] = fa.groupby("security_id")["net_profit"].shift(1)
    fa["prev_fiscal_year"] = fa.groupby("security_id")["fiscal_year"].shift(1)
    is_1y = (fa["fiscal_year"] - fa["prev_fiscal_year"] == 1)
    fa["pat_yoy_growth"] = np.where(
        is_1y & (fa["prev_net_profit"].abs() > 0),
        (fa["net_profit"] - fa["prev_net_profit"]) / fa["prev_net_profit"].abs() * 100.0,
        np.nan
    )
    fa["is_profit_positive"] = (fa["net_profit"] > 0).astype(float)
    fa["availability_date"] = pd.to_datetime(fa["availability_date"])
    fa = fa.sort_values("availability_date").reset_index(drop=True)

    trades["entry_dt"] = pd.to_datetime(trades["Entry Date"])
    trades = trades.sort_values("Entry Date").reset_index(drop=True)

    merged_fa = pd.merge_asof(
        trades[["Ticker", "entry_dt"]],
        fa[["symbol", "availability_date", "pat_yoy_growth", "is_profit_positive"]],
        left_by="Ticker",
        right_by="symbol",
        left_on="entry_dt",
        right_on="availability_date",
        direction="backward"
    )
    trades["pat_yoy_growth"] = merged_fa["pat_yoy_growth"]
    trades["is_profit_positive"] = merged_fa["is_profit_positive"].fillna(0.0)

    conn.close()

    # Calculate normalized percentile ranks (0.0 to 1.0) for composite scores
    def pct_rank(series, ascending=True):
        valid = series.dropna()
        if len(valid) == 0:
            return pd.Series(0.0, index=series.index)
        ranks = rankdata(valid if ascending else -valid, method="average") / len(valid)
        res = pd.Series(np.nan, index=series.index)
        res.loc[valid.index] = ranks
        return res.fillna(0.5)

    # Normalized factor percentiles
    trades["rank_rsi"] = pct_rank(trades["Monthly RSI"], ascending=True)
    trades["rank_breakout"] = pct_rank(trades["breakout_strength"], ascending=True)
    trades["rank_vol"] = pct_rank(trades["rel_volume"], ascending=True)
    trades["rank_ema9"] = pct_rank(trades["monthly_ema9_dist"], ascending=True)
    trades["rank_ema21"] = pct_rank(trades["daily_ema21_dist"], ascending=True)

    trades["rank_mcap"] = pct_rank(trades["mcap_cr"], ascending=True)
    trades["rank_smallcap"] = pct_rank(trades["mcap_cr"], ascending=False)
    trades["rank_profit_cagr"] = pct_rank(trades["profit_cagr_3y"], ascending=True)
    trades["rank_pat_yoy"] = pct_rank(trades["pat_yoy_growth"], ascending=True)
    trades["rank_pos_profit"] = trades["is_profit_positive"]
    trades["rank_roe"] = pct_rank(trades["roe"], ascending=True)
    trades["rank_roce"] = pct_rank(trades["roce"], ascending=True)
    trades["rank_int_cov"] = pct_rank(trades["interest_coverage"], ascending=True)

    valid_pe = trades["pe"][(trades["pe"] > 0) & (trades["pe"] < 200)]
    pe_ranks = pct_rank(valid_pe, ascending=False)
    trades["rank_pe"] = pd.Series(0.0, index=trades.index)
    trades.loc[valid_pe.index, "rank_pe"] = pe_ranks

    # Composite Technical Score (Rel Vol + RSI + Breakout)
    trades["combined_tech_score"] = (trades["rank_vol"] + trades["rank_rsi"] + trades["rank_breakout"]) / 3.0

    # Composite Fundamental Quality Score (ROE + ROCE + 3Y Profit CAGR + Market Cap)
    trades["fundamental_quality_score"] = (
        trades["rank_roe"] + trades["rank_roce"] + trades["rank_profit_cagr"] + trades["rank_mcap"]
    ) / 4.0

    # Hybrid Model D Score (50% Technical + 50% Fundamental Quality)
    trades["hybrid_score"] = 0.50 * trades["combined_tech_score"] + 0.50 * trades["fundamental_quality_score"]

    return trades

def run_simulation_engine(
    trades,
    all_trading_days,
    price_dict,
    capacity=10,
    allocation_model="MODEL_A",
    ranking_col="Monthly RSI",
    ranking_ascending=False,
    max_concentration_pct=0.10,
    cash_reserve_pct=0.0,
    min_liquidity_cr=0.50,
    cost_bps=25.0,
    start_date="2018-01-01",
    end_date="2026-08-31"
):
    """Dynamic Capital Allocation and Portfolio Simulator."""
    STARTING_CAPITAL = 1_000_000.0
    cost_mult_entry = 1.0 + (cost_bps / 10000.0)
    cost_mult_exit = 1.0 - (cost_bps / 10000.0)

    valid_set = trades[
        (trades["turnover_cr"] >= min_liquidity_cr) &
        (trades["Entry Date"] >= start_date) &
        (trades["Entry Date"] <= end_date)
    ].copy()

    trades_by_entry = {}
    for t in valid_set.to_dict(orient="records"):
        trades_by_entry.setdefault(t["Entry Date"], []).append(t)

    sim_days = [d for d in all_trading_days if d >= start_date and d <= end_date]
    if len(sim_days) < 2:
        return None

    years = (pd.to_datetime(sim_days[-1]) - pd.to_datetime(sim_days[0])).days / 365.25

    portfolio_cash = STARTING_CAPITAL
    open_positions = {}
    daily_records = []
    trades_taken = 0
    signals_generated = 0
    signals_rejected_pos_limit = 0
    signals_rejected_capital_limit = 0
    realized_trades = []
    total_tx_costs = 0.0

    for d in sim_days:
        # 1. Close exiting positions
        to_close = []
        for sec_id, pos in open_positions.items():
            if pos["exit_date"] == d:
                raw_exit_p = pos["exit_price"]
                net_exit_p = raw_exit_p * cost_mult_exit
                exit_proceeds = pos["shares"] * net_exit_p
                exit_cost = pos["shares"] * raw_exit_p * (cost_bps / 10000.0)
                total_tx_costs += (pos["entry_cost"] + exit_cost)
                portfolio_cash += exit_proceeds
                
                trade_ret = (net_exit_p - pos["effective_entry_p"]) / pos["effective_entry_p"] * 100.0
                realized_trades.append({
                    "ticker": pos["ticker"],
                    "entry_date": pos["entry_date"],
                    "exit_date": d,
                    "return_pct": trade_ret,
                    "holding_days": pos["holding_days"],
                    "invested": pos["allocated_capital"]
                })
                to_close.append(sec_id)
        for sec_id in to_close:
            del open_positions[sec_id]

        # 2. Mark current equity before entries
        current_invested_val = sum(pos["shares"] * price_dict.get((sec_id, d), pos["effective_entry_p"]) for sec_id, pos in open_positions.items())
        current_equity = portfolio_cash + current_invested_val

        # 3. Enter new positions
        if d in trades_by_entry:
            day_signals = trades_by_entry[d]
            signals_generated += len(day_signals)

            day_signals = sorted(
                day_signals,
                key=lambda x: (x[ranking_col] if pd.notna(x[ranking_col]) else (-1e9 if not ranking_ascending else 1e9)),
                reverse=(not ranking_ascending)
            )

            available_slots = max(0, capacity - len(open_positions))
            candidates_to_enter = day_signals[:available_slots]
            rejected_capacity_count = len(day_signals) - len(candidates_to_enter)
            signals_rejected_pos_limit += rejected_capacity_count

            if candidates_to_enter:
                k = len(candidates_to_enter)
                max_investable_equity = current_equity * (1.0 - cash_reserve_pct)
                deployable_cash = max(0.0, min(portfolio_cash - (current_equity * cash_reserve_pct), max_investable_equity - current_invested_val))

                raw_weights = np.zeros(k)
                if allocation_model == "MODEL_A":
                    raw_weights = np.ones(k) / capacity
                elif allocation_model == "MODEL_B1_LINEAR":
                    ranks = np.arange(k, 0, -1)
                    batch_proportions = ranks / ranks.sum()
                    raw_weights = (k / capacity) * batch_proportions
                elif allocation_model == "MODEL_B2_INVERSE":
                    inv_ranks = 1.0 / np.arange(1, k + 1)
                    batch_proportions = inv_ranks / inv_ranks.sum()
                    raw_weights = (k / capacity) * batch_proportions
                elif allocation_model == "MODEL_C_VOL":
                    vols = np.array([max(0.01, c["rel_volume"]) for c in candidates_to_enter])
                    batch_proportions = vols / vols.sum()
                    raw_weights = (k / capacity) * batch_proportions
                elif allocation_model == "MODEL_D_HYBRID":
                    scores = np.array([max(0.01, c["hybrid_score"]) for c in candidates_to_enter])
                    batch_proportions = scores / scores.sum()
                    raw_weights = (k / capacity) * batch_proportions
                else:
                    raw_weights = np.ones(k) / capacity

                capped_weights = np.minimum(raw_weights, max_concentration_pct)
                target_allocations = capped_weights * current_equity
                total_target = target_allocations.sum()

                if total_target > deployable_cash and total_target > 0:
                    scale_factor = deployable_cash / total_target
                    actual_allocations = target_allocations * scale_factor
                else:
                    actual_allocations = target_allocations

                for idx, t in enumerate(candidates_to_enter):
                    alloc_rs = actual_allocations[idx]
                    if alloc_rs >= 1000.0 and portfolio_cash >= alloc_rs:
                        raw_entry_p = t["Entry Price"]
                        effective_entry_p = raw_entry_p * cost_mult_entry
                        entry_tx_cost = alloc_rs * (cost_bps / 10000.0)
                        shares = alloc_rs / effective_entry_p
                        portfolio_cash -= alloc_rs
                        current_invested_val += alloc_rs

                        open_positions[t["security_id"]] = {
                            "ticker": t["Ticker"],
                            "shares": shares,
                            "effective_entry_p": effective_entry_p,
                            "entry_price": raw_entry_p,
                            "entry_date": t["Entry Date"],
                            "exit_date": t["Exit Date"],
                            "exit_price": t["Exit Price"],
                            "holding_days": t["Holding Days"],
                            "allocated_capital": alloc_rs,
                            "entry_cost": entry_tx_cost
                        }
                        trades_taken += 1
                    else:
                        signals_rejected_capital_limit += 1

        # 4. Mark to market
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
    drawdowns = (p_df["equity"] - peaks) / peaks * 100.0
    max_dd = drawdowns.min()
    exposure = (p_df["invested"] / p_df["equity"]).mean() * 100.0
    cash_pct = 100.0 - exposure
    max_cash_pct = (p_df["cash"] / p_df["equity"]).max() * 100.0
    avg_positions = p_df["positions"].mean()
    max_positions = p_df["positions"].max()

    t_df = pd.DataFrame(realized_trades)
    if len(t_df) > 0:
        win_rate = (t_df["return_pct"] > 0).mean() * 100.0
        avg_trade_ret = t_df["return_pct"].mean()
        median_trade_ret = t_df["return_pct"].median()
        avg_holding_days = t_df["holding_days"].mean()
        wins = t_df[t_df["return_pct"] > 0]["return_pct"]
        losses = t_df[t_df["return_pct"] < 0]["return_pct"]
        profit_factor = (wins.sum() / abs(losses.sum())) if (len(losses) > 0 and abs(losses.sum()) > 0) else 0.0

        loss_seq = (t_df["return_pct"] < 0).astype(int)
        max_consec_losses = 0
        curr_loss = 0
        for l in loss_seq:
            if l == 1:
                curr_loss += 1
                if curr_loss > max_consec_losses:
                    max_consec_losses = curr_loss
            else:
                curr_loss = 0

        w_gt_25 = (t_df["return_pct"] > 25.0).sum()
        w_gt_50 = (t_df["return_pct"] > 50.0).sum()
        w_gt_100 = (t_df["return_pct"] > 100.0).sum()
        w_gt_200 = (t_df["return_pct"] > 200.0).sum()
        has_blissgvs = ("BLISSGVS" in t_df["ticker"].values)

        ret_mult = 1.0 + t_df["return_pct"] / 100.0
        worst_single_trade = t_df["return_pct"].min()
        worst_single_stock = t_df.loc[t_df["return_pct"].idxmin()]["ticker"]

        worst_10_trade_seq = (ret_mult.rolling(10).apply(np.prod, raw=True) - 1.0).min() * 100.0 if len(ret_mult) >= 10 else np.nan
        worst_20_trade_seq = (ret_mult.rolling(20).apply(np.prod, raw=True) - 1.0).min() * 100.0 if len(ret_mult) >= 20 else np.nan
    else:
        win_rate = avg_trade_ret = median_trade_ret = avg_holding_days = profit_factor = max_consec_losses = 0.0
        w_gt_25 = w_gt_50 = w_gt_100 = w_gt_200 = 0
        has_blissgvs = False
        worst_single_trade = 0.0
        worst_single_stock = "N/A"
        worst_10_trade_seq = worst_20_trade_seq = np.nan

    p_df["daily_ret"] = p_df["equity"].pct_change() * 100.0
    worst_day_ret = p_df["daily_ret"].min()
    worst_day_date = p_df.loc[p_df["daily_ret"].idxmin()]["date"] if pd.notna(worst_day_ret) else "N/A"

    trough_idx = drawdowns.idxmin()
    peak_val = peaks.iloc[trough_idx]
    peak_idx = p_df[p_df["equity"] == peak_val].index[0]
    trough_date = p_df.iloc[trough_idx]["date"]
    peak_date = p_df.iloc[peak_idx]["date"]
    dd_duration_days = (pd.to_datetime(trough_date) - pd.to_datetime(peak_date)).days

    after_trough = p_df.iloc[trough_idx:]
    recovered_df = after_trough[after_trough["equity"] >= peak_val]
    if len(recovered_df) > 0:
        recovery_date = recovered_df.iloc[0]["date"]
        recovery_days = (pd.to_datetime(recovery_date) - pd.to_datetime(trough_date)).days
    else:
        recovery_days = np.nan

    p_df["year"] = pd.to_datetime(p_df["date"]).dt.year
    yearly_returns = {}
    for yr, y_df in p_df.groupby("year"):
        start_val = y_df.iloc[0]["equity"]
        end_val = y_df.iloc[-1]["equity"]
        yearly_returns[yr] = (end_val - start_val) / start_val * 100.0

    p_df["year_month"] = pd.to_datetime(p_df["date"]).dt.to_period("M")
    monthly_ret_list = []
    for ym, m_df in p_df.groupby("year_month"):
        m_start = m_df.iloc[0]["equity"]
        m_end = m_df.iloc[-1]["equity"]
        monthly_ret_list.append((m_end - m_start) / m_start * 100.0)
    m_series = pd.Series(monthly_ret_list)
    monthly_mean = m_series.mean() if len(m_series) > 0 else 0.0
    monthly_std = m_series.std() if len(m_series) > 1 else 0.0
    monthly_pos_pct = (m_series > 0).mean() * 100.0 if len(m_series) > 0 else 0.0

    total_signals_rejected = signals_rejected_pos_limit + signals_rejected_capital_limit
    pct_rejected = (total_signals_rejected / signals_generated * 100.0) if signals_generated > 0 else 0.0

    tx_charges = total_tx_costs * 0.50
    slippage_impact = total_tx_costs * 0.50

    return {
        "Starting Capital (₹)": STARTING_CAPITAL,
        "Ending Equity (₹)": final_eq,
        "Total Return (%)": tot_ret,
        "CAGR (%)": cagr,
        "Max Drawdown (%)": max_dd,
        "Profit Factor": profit_factor,
        "Win Rate (%)": win_rate,
        "Trades Taken": trades_taken,
        "Avg Trade Return (%)": avg_trade_ret,
        "Median Trade Return (%)": median_trade_ret,
        "Avg Holding Days": avg_holding_days,
        "Max Consec Losses": max_consec_losses,
        "Avg Capital Deployed (%)": exposure,
        "Avg Cash Pct (%)": cash_pct,
        "Max Cash Pct (%)": max_cash_pct,
        "Avg Positions": avg_positions,
        "Max Positions": max_positions,
        "Signals Generated": signals_generated,
        "Signals Rejected (Pos Limit)": signals_rejected_pos_limit,
        "Signals Rejected (Capital Limit)": signals_rejected_capital_limit,
        "Total Rejected Signals": total_signals_rejected,
        "Signals Rejected (%)": pct_rejected,
        "Transaction Costs (₹)": tx_charges,
        "Slippage Impact (₹)": slippage_impact,
        "Total Frictional Drag (₹)": total_tx_costs,
        "Winners > 25%": w_gt_25,
        "Winners > 50%": w_gt_50,
        "Winners > 100%": w_gt_100,
        "Winners > 200%": w_gt_200,
        "BLISSGVS Captured": has_blissgvs,
        "Worst Single Day (%)": worst_day_ret,
        "Worst Single Day Date": worst_day_date,
        "Worst Single Trade (%)": worst_single_trade,
        "Worst Single Stock": worst_single_stock,
        "Worst 10-Trade Seq (%)": worst_10_trade_seq,
        "Worst 20-Trade Seq (%)": worst_20_trade_seq,
        "Monthly Return Mean (%)": monthly_mean,
        "Monthly Return Std (%)": monthly_std,
        "Positive Months (%)": monthly_pos_pct,
        "Yearly Returns": yearly_returns,
        "Drawdown Duration (Days)": dd_duration_days,
        "Drawdown Recovery (Days)": recovery_days,
        "Equity Curve": p_df,
        "Drawdown Curve": drawdowns,
        "Realized Trades": t_df
    }

def run_all_research_experiments():
    t_start = time.time()
    print("=" * 90)
    print("DYNAMIC CAPITAL ALLOCATION & SIGNAL CONGESTION MANAGEMENT RESEARCH SUITE")
    print("=" * 90)

    print("\n[Phase 1] Preparing point-in-time opportunity dataset...")
    trades = prepare_opportunity_dataset()
    print(f"Total corporate equity opportunity set: {len(trades):,} trades.")

    conn = sqlite3.connect(DB_PATH)
    daily_df = pd.read_sql(
        "SELECT security_id, date, close FROM daily_ohlcv WHERE security_id IN (SELECT DISTINCT security_id FROM trades) ORDER BY date ASC;",
        conn
    )
    conn.close()
    all_trading_days = sorted(daily_df["date"].unique())
    price_dict = dict(zip(zip(daily_df["security_id"], daily_df["date"]), daily_df["close"]))
    print(f"Loaded {len(daily_df):,} daily price points across {len(all_trading_days):,} trading days.")

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    fig_dir = reports_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # 1. Independent Factor Ranking Evaluation
    print("\n[Phase 2] Evaluating 13 Independent Ranking Factors + 3 Composites...")
    factor_definitions = [
        ("Technical: Relative Volume", "rel_volume", False),
        ("Technical: Monthly RSI", "Monthly RSI", False),
        ("Technical: Breakout Strength", "breakout_strength", False),
        ("Technical: Proximity to Daily EMA21", "daily_ema21_dist", True),
        ("Technical: Distance Above EMA21", "daily_ema21_dist", False),
        ("Fundamental: Market Cap (Large-Cap Bias)", "rank_mcap", False),
        ("Fundamental: Market Cap (Small-Cap Bias)", "rank_smallcap", False),
        ("Fundamental: 3Y Profit CAGR", "profit_cagr_3y", False),
        ("Fundamental: Latest YoY PAT Growth", "pat_yoy_growth", False),
        ("Fundamental: Positive Profit Flag", "is_profit_positive", False),
        ("Fundamental: ROE", "roe", False),
        ("Fundamental: ROCE", "roce", False),
        ("Fundamental: Interest Coverage", "interest_coverage", False),
        ("Fundamental: P/E Valuation (Lower PE)", "rank_pe", False),
        ("Composite: Technical Score (RSI+Vol+Breakout)", "combined_tech_score", False),
        ("Composite: Fundamental Quality (ROE+ROCE+Growth+Mcap)", "fundamental_quality_score", False),
        ("Composite: Hybrid Tech + Fundamental (Model D)", "hybrid_score", False),
    ]

    factor_records = []
    for label, col, asc in factor_definitions:
        res10 = run_simulation_engine(trades, all_trading_days, price_dict, capacity=10, allocation_model="MODEL_A", ranking_col=col, ranking_ascending=asc)
        res20 = run_simulation_engine(trades, all_trading_days, price_dict, capacity=20, allocation_model="MODEL_A", ranking_col=col, ranking_ascending=asc)
        factor_records.append({
            "Ranking Factor": label,
            "Cap 10 CAGR (%)": res10["CAGR (%)"],
            "Cap 10 MaxDD (%)": res10["Max Drawdown (%)"],
            "Cap 10 Profit Factor": res10["Profit Factor"],
            "Cap 10 WinRate (%)": res10["Win Rate (%)"],
            "Cap 10 Trades": res10["Trades Taken"],
            "Cap 10 AvgTrade (%)": res10["Avg Trade Return (%)"],
            "Cap 10 Total Rej (%)": res10["Signals Rejected (%)"],
            "Cap 10 W>50%": res10["Winners > 50%"],
            "Cap 10 W>100%": res10["Winners > 100%"],
            "Cap 10 BLISSGVS": res10["BLISSGVS Captured"],
            "Cap 20 CAGR (%)": res20["CAGR (%)"],
            "Cap 20 MaxDD (%)": res20["Max Drawdown (%)"],
            "Cap 20 Profit Factor": res20["Profit Factor"],
            "Cap 20 Trades": res20["Trades Taken"],
            "Cap 20 W>50%": res20["Winners > 50%"],
            "Cap 20 W>100%": res20["Winners > 100%"]
        })
    factor_df = pd.DataFrame(factor_records)
    factor_df.to_csv(reports_dir / "independent_factors_ranking_comparison.csv", index=False)
    print("Saved independent_factors_ranking_comparison.csv")

    # 2. Dynamic Allocation Models Sweep
    print("\n[Phase 3] Sweeping Dynamic Allocation Models across Capacities (10, 15, 20, 25, 30)...")
    models_to_test = [
        ("Model A: Equal Weight (Baseline)", "MODEL_A", "Monthly RSI", False),
        ("Model B1: Linear Rank Weighted", "MODEL_B1_LINEAR", "Monthly RSI", False),
        ("Model B2: Inverse Rank Weighted", "MODEL_B2_INVERSE", "Monthly RSI", False),
        ("Model C: Relative Volume Weighted", "MODEL_C_VOL", "rel_volume", False),
        ("Model D: Composite Tech+Fund Weighted", "MODEL_D_HYBRID", "hybrid_score", False)
    ]
    capacities = [10, 15, 20, 25, 30]

    model_sweep_records = []
    equity_curves_dict = {}
    drawdown_curves_dict = {}

    for mod_label, mod_code, rank_col, asc in models_to_test:
        for cap in capacities:
            max_conc = min(0.15, max(0.05, 1.5 / cap))
            res = run_simulation_engine(
                trades, all_trading_days, price_dict,
                capacity=cap,
                allocation_model=mod_code,
                ranking_col=rank_col,
                ranking_ascending=asc,
                max_concentration_pct=max_conc,
                cash_reserve_pct=0.0
            )
            if cap == 15:
                equity_curves_dict[mod_label] = res["Equity Curve"]
                drawdown_curves_dict[mod_label] = res["Drawdown Curve"]

            model_sweep_records.append({
                "Allocation Model": mod_label,
                "Model Code": mod_code,
                "Capacity (Slots)": cap,
                "Concentration Cap (%)": max_conc * 100.0,
                "Starting Capital (₹)": res["Starting Capital (₹)"],
                "Ending Equity (₹)": res["Ending Equity (₹)"],
                "Total Return (%)": res["Total Return (%)"],
                "CAGR (%)": res["CAGR (%)"],
                "Max Drawdown (%)": res["Max Drawdown (%)"],
                "Profit Factor": res["Profit Factor"],
                "Win Rate (%)": res["Win Rate (%)"],
                "Trades Taken": res["Trades Taken"],
                "Avg Trade Return (%)": res["Avg Trade Return (%)"],
                "Median Trade Return (%)": res["Median Trade Return (%)"],
                "Avg Holding Days": res["Avg Holding Days"],
                "Max Consec Losses": res["Max Consec Losses"],
                "Avg Capital Deployed (%)": res["Avg Capital Deployed (%)"],
                "Avg Cash Pct (%)": res["Avg Cash Pct (%)"],
                "Max Cash Pct (%)": res["Max Cash Pct (%)"],
                "Avg Open Positions": res["Avg Positions"],
                "Max Open Positions": res["Max Positions"],
                "Signals Generated": res["Signals Generated"],
                "Total Rejected Signals": res["Total Rejected Signals"],
                "Signals Rejected (%)": res["Signals Rejected (%)"],
                "Transaction Costs (₹)": res["Transaction Costs (₹)"],
                "Slippage Impact (₹)": res["Slippage Impact (₹)"],
                "Total Friction (₹)": res["Total Frictional Drag (₹)"],
                "Winners > 25%": res["Winners > 25%"],
                "Winners > 50%": res["Winners > 50%"],
                "Winners > 100%": res["Winners > 100%"],
                "Winners > 200%": res["Winners > 200%"],
                "BLISSGVS Retained": res["BLISSGVS Captured"]
            })
    models_df = pd.DataFrame(model_sweep_records)
    models_df.to_csv(reports_dir / "dynamic_allocation_models_comparison.csv", index=False)
    print("Saved dynamic_allocation_models_comparison.csv")

    # 3. Concentration Limits Sweep
    print("\n[Phase 4] Testing Concentration Limits (5%, 7.5%, 10%, 15%)...")
    conc_limits = [0.05, 0.075, 0.10, 0.15]
    conc_records = []
    for conc in conc_limits:
        for mod_label, mod_code, rank_col, asc in models_to_test:
            res = run_simulation_engine(
                trades, all_trading_days, price_dict,
                capacity=15,
                allocation_model=mod_code,
                ranking_col=rank_col,
                ranking_ascending=asc,
                max_concentration_pct=conc,
                cash_reserve_pct=0.0
            )
            conc_records.append({
                "Concentration Limit (%)": conc * 100.0,
                "Allocation Model": mod_label,
                "CAGR (%)": res["CAGR (%)"],
                "Max Drawdown (%)": res["Max Drawdown (%)"],
                "Profit Factor": res["Profit Factor"],
                "Win Rate (%)": res["Win Rate (%)"],
                "Trades Taken": res["Trades Taken"],
                "Avg Trade Return (%)": res["Avg Trade Return (%)"],
                "Avg Capital Deployed (%)": res["Avg Capital Deployed (%)"],
                "Total Return (%)": res["Total Return (%)"],
                "Ending Equity (₹)": res["Ending Equity (₹)"]
            })
    conc_df = pd.DataFrame(conc_records)
    conc_df.to_csv(reports_dir / "concentration_limits_sweep.csv", index=False)
    print("Saved concentration_limits_sweep.csv")

    # 4. Cash Reserve Buffers Sweep
    print("\n[Phase 5] Testing Cash Reserve Buffers (0%, 10%, 20%)...")
    cash_buffers = [0.0, 0.10, 0.20]
    buffer_records = []
    for buf in cash_buffers:
        for mod_label, mod_code, rank_col, asc in models_to_test:
            res = run_simulation_engine(
                trades, all_trading_days, price_dict,
                capacity=15,
                allocation_model=mod_code,
                ranking_col=rank_col,
                ranking_ascending=asc,
                max_concentration_pct=0.10,
                cash_reserve_pct=buf
            )
            buffer_records.append({
                "Cash Reserve Buffer (%)": buf * 100.0,
                "Allocation Model": mod_label,
                "CAGR (%)": res["CAGR (%)"],
                "Max Drawdown (%)": res["Max Drawdown (%)"],
                "Profit Factor": res["Profit Factor"],
                "Trades Taken": res["Trades Taken"],
                "Avg Capital Deployed (%)": res["Avg Capital Deployed (%)"],
                "Avg Cash Pct (%)": res["Avg Cash Pct (%)"],
                "Signals Rejected (Cap Limit)": res["Signals Rejected (Capital Limit)"],
                "Ending Equity (₹)": res["Ending Equity (₹)"]
            })
    buffer_df = pd.DataFrame(buffer_records)
    buffer_df.to_csv(reports_dir / "cash_reserve_buffers_sweep.csv", index=False)
    print("Saved cash_reserve_buffers_sweep.csv")

    # 5. Tail-Winner Preservation Audit
    print("\n[Phase 6] Conducting Tail-Winner Preservation Audit...")
    base_gt_25 = (trades["Return %"] > 25.0).sum()
    base_gt_50 = (trades["Return %"] > 50.0).sum()
    base_gt_100 = (trades["Return %"] > 100.0).sum()
    base_gt_200 = (trades["Return %"] > 200.0).sum()

    tail_records = [{
        "Portfolio Configuration": "Unrestricted Technical Universe (Baseline)",
        "Trades Taken": len(trades),
        "Winners > 25%": base_gt_25,
        "Winners > 50%": base_gt_50,
        "Winners > 100%": base_gt_100,
        "Winners > 200%": base_gt_200,
        "BLISSGVS Retained": True,
        "Capture % (>50%)": 100.0,
        "Capture % (>100%)": 100.0
    }]

    for mod_label, mod_code, rank_col, asc in models_to_test:
        for cap in [10, 15, 20]:
            res = run_simulation_engine(
                trades, all_trading_days, price_dict,
                capacity=cap, allocation_model=mod_code, ranking_col=rank_col, ranking_ascending=asc,
                max_concentration_pct=0.10, cash_reserve_pct=0.0
            )
            tail_records.append({
                "Portfolio Configuration": f"{mod_label} ({cap} Slots)",
                "Trades Taken": res["Trades Taken"],
                "Winners > 25%": res["Winners > 25%"],
                "Winners > 50%": res["Winners > 50%"],
                "Winners > 100%": res["Winners > 100%"],
                "Winners > 200%": res["Winners > 200%"],
                "BLISSGVS Retained": res["BLISSGVS Captured"],
                "Capture % (>50%)": (res["Winners > 50%"] / base_gt_50) * 100.0,
                "Capture % (>100%)": (res["Winners > 100%"] / base_gt_100) * 100.0
            })
    tail_df = pd.DataFrame(tail_records)
    tail_df.to_csv(reports_dir / "tail_winner_preservation.csv", index=False)
    print("Saved tail_winner_preservation.csv")

    # 6. In-Sample vs Out-of-Sample Stability
    print("\n[Phase 7] Evaluating In-Sample (2018-2022) vs Out-of-Sample (2023-2026) Stability...")
    temporal_records = []
    for mod_label, mod_code, rank_col, asc in models_to_test:
        for cap in [10, 15, 20]:
            is_res = run_simulation_engine(
                trades, all_trading_days, price_dict,
                capacity=cap, allocation_model=mod_code, ranking_col=rank_col, ranking_ascending=asc,
                max_concentration_pct=0.10, cash_reserve_pct=0.0,
                start_date="2018-01-01", end_date="2022-12-31"
            )
            oos_res = run_simulation_engine(
                trades, all_trading_days, price_dict,
                capacity=cap, allocation_model=mod_code, ranking_col=rank_col, ranking_ascending=asc,
                max_concentration_pct=0.10, cash_reserve_pct=0.0,
                start_date="2023-01-01", end_date="2026-08-31"
            )
            temporal_records.append({
                "Allocation Model": mod_label,
                "Capacity": cap,
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
    temporal_df = pd.DataFrame(temporal_records)
    temporal_df.to_csv(reports_dir / "dynamic_allocation_temporal_stability.csv", index=False)
    print("Saved dynamic_allocation_temporal_stability.csv")

    # 7. Granular Risk Analysis & Yearly Returns
    print("\n[Phase 8] Computing Granular Risk Analytics & Yearly Returns...")
    risk_records = []
    yearly_rows = []
    for mod_label, mod_code, rank_col, asc in models_to_test:
        res = run_simulation_engine(
            trades, all_trading_days, price_dict,
            capacity=15, allocation_model=mod_code, ranking_col=rank_col, ranking_ascending=asc,
            max_concentration_pct=0.10, cash_reserve_pct=0.0
        )
        risk_records.append({
            "Allocation Model": mod_label,
            "Worst Single Day (%)": res["Worst Single Day (%)"],
            "Worst Day Date": res["Worst Single Day Date"],
            "Worst Single Trade (%)": res["Worst Single Trade (%)"],
            "Worst Single Stock": res["Worst Single Stock"],
            "Worst 10-Trade Sequence (%)": res["Worst 10-Trade Seq (%)"],
            "Worst 20-Trade Sequence (%)": res["Worst 20-Trade Seq (%)"],
            "Monthly Return Mean (%)": res["Monthly Return Mean (%)"],
            "Monthly Return Std (%)": res["Monthly Return Std (%)"],
            "Positive Months (%)": res["Positive Months (%)"],
            "Drawdown Duration (Days)": res["Drawdown Duration (Days)"],
            "Drawdown Recovery (Days)": res["Drawdown Recovery (Days)"]
        })
        y_row = {"Allocation Model": mod_label}
        y_row.update({f"{yr} (%)": ret for yr, ret in sorted(res["Yearly Returns"].items())})
        yearly_rows.append(y_row)

    risk_df = pd.DataFrame(risk_records)
    risk_df.to_csv(reports_dir / "dynamic_allocation_risk_analysis.csv", index=False)
    yearly_df = pd.DataFrame(yearly_rows)
    yearly_df.to_csv(reports_dir / "dynamic_allocation_yearly_returns.csv", index=False)
    print("Saved dynamic_allocation_risk_analysis.csv and dynamic_allocation_yearly_returns.csv")

    # 8. High-Congestion Days Case Study
    print("\n[Phase 9] Computing Exact High-Congestion Day Rupee Allocations...")
    congestion_dates = ["2023-12-22", "2024-01-19", "2024-04-16"]
    congestion_rows = []

    for c_date in congestion_dates:
        day_t = trades[trades["Entry Date"] == c_date].copy()
        
        day_t_rsi = day_t.sort_values("Monthly RSI", ascending=False).reset_index(drop=True)
        rsi_ranks = {row["Ticker"]: idx + 1 for idx, row in day_t_rsi.iterrows()}

        day_t_vol = day_t.sort_values("rel_volume", ascending=False).reset_index(drop=True)
        vol_ranks = {row["Ticker"]: idx + 1 for idx, row in day_t_vol.iterrows()}

        day_t_hyb = day_t.sort_values("hybrid_score", ascending=False).reset_index(drop=True)
        hyb_ranks = {row["Ticker"]: idx + 1 for idx, row in day_t_hyb.iterrows()}

        K = 10
        PORTFOLIO_CAPITAL = 1_000_000.0
        MAX_CONC = 0.15

        linear_raw = np.arange(10, 0, -1) / 55.0
        linear_capped = np.minimum(linear_raw, MAX_CONC)
        linear_allocs = (linear_capped / linear_capped.sum()) * PORTFOLIO_CAPITAL

        inv_raw = (1.0 / np.arange(1, 11))
        inv_raw = inv_raw / inv_raw.sum()
        inv_capped = np.minimum(inv_raw, MAX_CONC)
        inv_allocs = (inv_capped / inv_capped.sum()) * PORTFOLIO_CAPITAL

        top10_vol_stocks = day_t_vol.iloc[:10].copy()
        vol_weights_raw = top10_vol_stocks["rel_volume"].values / top10_vol_stocks["rel_volume"].sum()
        vol_capped = np.minimum(vol_weights_raw, MAX_CONC)
        vol_allocs = (vol_capped / vol_capped.sum()) * PORTFOLIO_CAPITAL

        top10_hyb_stocks = day_t_hyb.iloc[:10].copy()
        hyb_weights_raw = top10_hyb_stocks["hybrid_score"].values / top10_hyb_stocks["hybrid_score"].sum()
        hyb_capped = np.minimum(hyb_weights_raw, MAX_CONC)
        hyb_allocs = (hyb_capped / hyb_capped.sum()) * PORTFOLIO_CAPITAL

        for _, stock_row in day_t.iterrows():
            ticker = stock_row["Ticker"]
            r_rsi = rsi_ranks[ticker]
            alloc_pct_a = 10.0 if r_rsi <= 10 else 0.0
            cap_a = 100_000.0 if r_rsi <= 10 else 0.0

            alloc_pct_b1 = (linear_allocs[r_rsi - 1] / PORTFOLIO_CAPITAL * 100.0) if r_rsi <= 10 else 0.0
            cap_b1 = linear_allocs[r_rsi - 1] if r_rsi <= 10 else 0.0

            alloc_pct_b2 = (inv_allocs[r_rsi - 1] / PORTFOLIO_CAPITAL * 100.0) if r_rsi <= 10 else 0.0
            cap_b2 = inv_allocs[r_rsi - 1] if r_rsi <= 10 else 0.0

            r_vol = vol_ranks[ticker]
            alloc_pct_c = (vol_allocs[r_vol - 1] / PORTFOLIO_CAPITAL * 100.0) if r_vol <= 10 else 0.0
            cap_c = vol_allocs[r_vol - 1] if r_vol <= 10 else 0.0

            r_hyb = hyb_ranks[ticker]
            alloc_pct_d = (hyb_allocs[r_hyb - 1] / PORTFOLIO_CAPITAL * 100.0) if r_hyb <= 10 else 0.0
            cap_d = hyb_allocs[r_hyb - 1] if r_hyb <= 10 else 0.0

            congestion_rows.append({
                "Date": c_date,
                "Ticker": ticker,
                "Monthly RSI": stock_row["Monthly RSI"],
                "RSI Rank": r_rsi,
                "Relative Volume": stock_row["rel_volume"],
                "Vol Rank": r_vol,
                "Hybrid Score": stock_row["hybrid_score"],
                "Hybrid Rank": r_hyb,
                "Turnover (Cr)": stock_row["turnover_cr"],
                "Model A (%)": alloc_pct_a,
                "Model A (₹)": cap_a,
                "Model B1 Linear (%)": alloc_pct_b1,
                "Model B1 Linear (₹)": cap_b1,
                "Model B2 Inverse (%)": alloc_pct_b2,
                "Model B2 Inverse (₹)": cap_b2,
                "Model C Vol (%)": alloc_pct_c,
                "Model C Vol (₹)": cap_c,
                "Model D Hybrid (%)": alloc_pct_d,
                "Model D Hybrid (₹)": cap_d
            })

    congestion_df = pd.DataFrame(congestion_rows)
    congestion_df.to_csv(reports_dir / "congestion_day_allocations.csv", index=False)
    print("Saved congestion_day_allocations.csv")

    # 9. Publication Charts
    print("\n[Phase 10] Generating Figures & Visualizations...")
    plt.figure(figsize=(13, 7))
    model_colors = {
        "Model A: Equal Weight (Baseline)": ("black", "-", 2.0),
        "Model B1: Linear Rank Weighted": ("darkorange", "--", 1.8),
        "Model B2: Inverse Rank Weighted": ("crimson", ":", 1.8),
        "Model C: Relative Volume Weighted": ("blue", "-.", 2.2),
        "Model D: Composite Tech+Fund Weighted": ("teal", "-", 2.0)
    }
    for m_lbl, (c, ls, lw) in model_colors.items():
        if m_lbl in equity_curves_dict:
            p_df = equity_curves_dict[m_lbl]
            cagr_val = models_df[(models_df["Allocation Model"] == m_lbl) & (models_df["Capacity (Slots)"] == 15)]["CAGR (%)"].values[0]
            end_lakhs = p_df.iloc[-1]["equity"] / 100000.0
            plt.plot(pd.to_datetime(p_df["date"]), p_df["equity"] / 100000.0, label=f"{m_lbl} (CAGR: {cagr_val:.1f}%, End: ₹{end_lakhs:.1f}L)", color=c, linestyle=ls, linewidth=lw)

    plt.title("Dynamic Capital Allocation Models: Equity Curves (15 Positions, ₹10 Lakhs Initial)", fontsize=13, fontweight="bold")
    plt.xlabel("Date", fontsize=11)
    plt.ylabel("Portfolio Value (₹ Lakhs)", fontsize=11)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(loc="upper left", fontsize=9.5)
    plt.tight_layout()
    plt.savefig(fig_dir / "dynamic_allocation_equity_curves.png", dpi=300)
    plt.close()

    plt.figure(figsize=(13, 5))
    for m_lbl, (c, ls, lw) in model_colors.items():
        if m_lbl in drawdown_curves_dict:
            dd_series = drawdown_curves_dict[m_lbl]
            p_df = equity_curves_dict[m_lbl]
            maxdd_val = models_df[(models_df["Allocation Model"] == m_lbl) & (models_df["Capacity (Slots)"] == 15)]["Max Drawdown (%)"].values[0]
            plt.plot(pd.to_datetime(p_df["date"]), dd_series, label=f"{m_lbl} (MaxDD: {maxdd_val:.1f}%)", color=c, linestyle=ls, linewidth=lw)

    plt.title("Dynamic Capital Allocation Models: Drawdown Profiles (15 Positions)", fontsize=13, fontweight="bold")
    plt.xlabel("Date", fontsize=11)
    plt.ylabel("Drawdown (%)", fontsize=11)
    plt.grid(True, linestyle=":", alpha=0.6)
    plt.legend(loc="lower left", fontsize=9.5)
    plt.tight_layout()
    plt.savefig(fig_dir / "dynamic_allocation_drawdown_curves.png", dpi=300)
    plt.close()

    sample_cong = congestion_df[congestion_df["Date"] == "2023-12-22"].sort_values("Monthly RSI", ascending=False).iloc[:10]
    fig, ax = plt.subplots(figsize=(12, 6))
    x = np.arange(len(sample_cong))
    width = 0.20

    ax.bar(x - 1.5 * width, sample_cong["Model A (₹)"] / 1000.0, width, label="Model A (Equal)", color="gray", alpha=0.85)
    ax.bar(x - 0.5 * width, sample_cong["Model B1 Linear (₹)"] / 1000.0, width, label="Model B1 (Linear Rank)", color="darkorange", alpha=0.85)
    ax.bar(x + 0.5 * width, sample_cong["Model C Vol (₹)"] / 1000.0, width, label="Model C (Rel Vol)", color="blue", alpha=0.85)
    ax.bar(x + 1.5 * width, sample_cong["Model D Hybrid (₹)"] / 1000.0, width, label="Model D (Tech+Fund)", color="teal", alpha=0.85)

    ax.set_ylabel("Capital Allocated (₹ Thousands)", fontsize=11)
    ax.set_title("Capital Distribution on High-Congestion Date 2023-12-22 (Top 10 Stocks from 27 Signals)", fontsize=13, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(sample_cong["Ticker"], rotation=30, ha="right", fontsize=9.5)
    ax.legend(loc="upper right", fontsize=10)
    ax.grid(True, linestyle=":", alpha=0.5, axis="y")
    plt.tight_layout()
    plt.savefig(fig_dir / "congestion_day_allocation_distribution.png", dpi=300)
    plt.close()

    total_time = time.time() - t_start
    print(f"\nAll dynamic allocation experiments successfully completed in {total_time:.1f}s.")
    return models_df, factor_df, conc_df, buffer_df, tail_df, temporal_df, risk_df, yearly_df, congestion_df

if __name__ == '__main__':
    m_df, f_df, c_df, b_df, t_df, oos_df, r_df, y_df, cong_df = run_all_research_experiments()
