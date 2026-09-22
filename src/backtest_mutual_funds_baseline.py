#!/usr/bin/env python3
"""
Mutual Funds & Benchmark Baseline Backtest Specialist Script
============================================================
Calculates exact 5-year historical returns (2021 to 2026) for Indian Benchmarks
and top Active Mutual Funds for ₹1 Lakh initial capital.

Benchmarks:
- Nifty 50 TRI (Proxy: UTI Nifty 50 Index Fund Direct Growth)
- Nifty Next 50 TRI (Proxy: ICICI Prudential Nifty Next 50 Index Fund Direct Growth)
- Nifty Midcap 150 TRI (Proxy: Motilal Oswal Nifty Midcap 150 Index Fund Direct Growth)
- Nifty Smallcap 250 TRI (Proxy: Motilal Oswal Nifty Smallcap 250 Index Fund Direct Growth)

Active Mutual Funds:
- Quant Small Cap Fund Direct Growth
- Parag Parikh Flexi Cap Fund Direct Growth
- Nippon India Small Cap Fund Direct Growth
- Mirae Asset Large Cap Fund Direct Growth
- HDFC Flexi Cap Fund Direct Growth
- SBI Small Cap Fund Direct Growth
- ICICI Prudential Bluechip Fund Direct Growth
"""

import os
import json
import argparse
import urllib.request
import urllib.parse
import pandas as pd
import numpy as np
from datetime import datetime

# AMFI Scheme Codes mapping
FUND_SCHEMES = {
    "Nifty 50 TRI (UTI Index)": {"code": 120716, "category": "Passive Large Cap Baseline"},
    "Nifty Next 50 TRI (ICICI Index)": {"code": 120684, "category": "Passive Large-Mid Baseline"},
    "Nifty Midcap 150 TRI (Motilal Index)": {"code": 147622, "category": "Passive Mid Cap Baseline"},
    "Nifty Smallcap 250 TRI (Motilal Index)": {"code": 147623, "category": "Passive Small Cap Baseline"},
    "Quant Small Cap Direct": {"code": 120828, "category": "Active Small Cap"},
    "Parag Parikh Flexi Cap Direct": {"code": 122639, "category": "Active Flexi Cap"},
    "Nippon India Small Cap Direct": {"code": 118778, "category": "Active Small Cap"},
    "Mirae Asset Large Cap Direct": {"code": 118825, "category": "Active Large Cap"},
    "HDFC Flexi Cap Direct": {"code": 118955, "category": "Active Flexi Cap"},
    "SBI Small Cap Direct": {"code": 125497, "category": "Active Small Cap"},
    "ICICI Pru Bluechip Direct": {"code": 120586, "category": "Active Large Cap"}
}

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "mf_cache")

def fetch_mf_nav_data(scheme_code: int, cache_dir: str = CACHE_DIR) -> pd.DataFrame:
    """Fetch daily NAV data for a scheme code from mfapi.in API with local disk caching."""
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f"{scheme_code}.json")
    
    data = None
    if os.path.exists(cache_file):
        # Check cache age (valid for 1 day)
        file_age_hours = (datetime.now().timestamp() - os.path.getmtime(cache_file)) / 3600
        if file_age_hours < 24:
            with open(cache_file, "r") as f:
                data = json.load(f)
    
    if data is None:
        url = f"https://api.mfapi.in/mf/{scheme_code}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            with open(cache_file, "w") as f:
                json.dump(data, f)
        except Exception as e:
            if os.path.exists(cache_file):
                with open(cache_file, "r") as f:
                    data = json.load(f)
            else:
                raise RuntimeError(f"Failed to fetch NAV for scheme {scheme_code}: {e}")

    nav_list = data.get("data", [])
    df = pd.DataFrame(nav_list)
    if df.empty:
        raise ValueError(f"No NAV data found for scheme code {scheme_code}")
    
    df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y")
    df["nav"] = df["nav"].astype(float)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def calculate_metrics(df: pd.DataFrame, start_date: str, end_date: str, initial_capital: float = 100000.0, rf_annual: float = 0.06) -> dict:
    """Calculate performance and risk metrics for a given NAV series between start_date and end_date."""
    sub_df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    if len(sub_df) < 2:
        raise ValueError(f"Insufficient data between {start_date} and {end_date}")
        
    start_nav = sub_df.iloc[0]["nav"]
    end_nav = sub_df.iloc[-1]["nav"]
    actual_start_date = sub_df.iloc[0]["date"]
    actual_end_date = sub_df.iloc[-1]["date"]
    
    days = (actual_end_date - actual_start_date).days
    years = days / 365.25 if days > 0 else 1.0
    
    final_capital = initial_capital * (end_nav / start_nav)
    abs_return = (end_nav - start_nav) / start_nav
    cagr = ((end_nav / start_nav) ** (1 / years)) - 1 if years > 0 else 0.0
    
    # Daily returns calculation
    sub_df["daily_ret"] = sub_df["nav"].pct_change()
    daily_rets = sub_df["daily_ret"].dropna()
    
    ann_volatility = daily_rets.std() * np.sqrt(252) if len(daily_rets) > 0 else 0.0
    
    # Max Drawdown
    sub_df["cummax"] = sub_df["nav"].cummax()
    sub_df["drawdown"] = (sub_df["nav"] - sub_df["cummax"]) / sub_df["cummax"]
    max_drawdown = sub_df["drawdown"].min()
    
    # Sharpe Ratio
    sharpe_ratio = (cagr - rf_annual) / ann_volatility if ann_volatility > 0 else 0.0
    
    # Sortino Ratio
    rf_daily = (1 + rf_annual) ** (1 / 252) - 1
    downside_rets = daily_rets[daily_rets < rf_daily] - rf_daily
    downside_std = np.sqrt(np.mean(downside_rets ** 2)) * np.sqrt(252) if len(downside_rets) > 0 else 0.0
    sortino_ratio = (cagr - rf_annual) / downside_std if downside_std > 0 else 0.0
    
    # Calmar Ratio
    calmar_ratio = (cagr - rf_annual) / abs(max_drawdown) if max_drawdown != 0 else 0.0
    
    return {
        "start_date": actual_start_date.strftime("%Y-%m-%d"),
        "end_date": actual_end_date.strftime("%Y-%m-%d"),
        "years": round(years, 3),
        "start_nav": round(start_nav, 4),
        "end_nav": round(end_nav, 4),
        "initial_capital": initial_capital,
        "final_capital": round(final_capital, 2),
        "absolute_return_pct": round(abs_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "ann_volatility_pct": round(ann_volatility * 100, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "sharpe_ratio": round(sharpe_ratio, 3),
        "sortino_ratio": round(sortino_ratio, 3),
        "calmar_ratio": round(calmar_ratio, 3),
        "sub_df": sub_df
    }


def run_benchmark_backtest(start_date: str = "2021-01-01", end_date: str = "2026-01-01", initial_capital: float = 100000.0, rf_annual: float = 0.06) -> pd.DataFrame:
    """Run full benchmark vs active mutual fund analysis."""
    print(f"\n==================================================================================================")
    print(f"MUTUAL FUND & BENCHMARK BASELINE BACKTEST (Initial Capital: ₹{initial_capital:,.0f} | {start_date} to {end_date})")
    print(f"==================================================================================================\n")
    
    results = []
    nav_series_dict = {}
    
    for fund_name, meta in FUND_SCHEMES.items():
        code = meta["code"]
        category = meta["category"]
        try:
            df = fetch_mf_nav_data(code)
            metrics = calculate_metrics(df, start_date, end_date, initial_capital, rf_annual)
            
            nav_series_dict[fund_name] = metrics["sub_df"].set_index("date")["daily_ret"]
            
            res_row = {
                "Fund/Benchmark Name": fund_name,
                "Category": category,
                "Scheme Code": code,
                "Start Date": metrics["start_date"],
                "End Date": metrics["end_date"],
                "Start NAV": metrics["start_nav"],
                "End NAV": metrics["end_nav"],
                "Final Capital (₹)": metrics["final_capital"],
                "Abs Return (%)": metrics["absolute_return_pct"],
                "CAGR (%)": metrics["cagr_pct"],
                "Volatility (%)": metrics["ann_volatility_pct"],
                "Max Drawdown (%)": metrics["max_drawdown_pct"],
                "Sharpe Ratio": metrics["sharpe_ratio"],
                "Sortino Ratio": metrics["sortino_ratio"],
                "Calmar Ratio": metrics["calmar_ratio"],
            }
            results.append(res_row)
        except Exception as e:
            print(f"Error processing {fund_name}: {e}")
            
    res_df = pd.DataFrame(results)
    
    # Calculate Alpha & Beta relative to Nifty 50 TRI baseline
    nifty50_ret = nav_series_dict.get("Nifty 50 TRI (UTI Index)")
    nifty50_cagr = res_df.loc[res_df["Fund/Benchmark Name"] == "Nifty 50 TRI (UTI Index)", "CAGR (%)"].values[0] / 100.0 if not res_df.empty else 0.0
    
    alphas = []
    betas = []
    
    for _, row in res_df.iterrows():
        fname = row["Fund/Benchmark Name"]
        fund_ret = nav_series_dict.get(fname)
        fund_cagr = row["CAGR (%)"] / 100.0
        
        if fund_ret is not None and nifty50_ret is not None:
            combined = pd.concat([fund_ret, nifty50_ret], axis=1, sort=True).dropna()
            if len(combined) > 20:
                cov = np.cov(combined.iloc[:, 0], combined.iloc[:, 1])[0, 1]
                var = np.var(combined.iloc[:, 1])
                beta = cov / var if var > 0 else 1.0
                alpha = (fund_cagr - rf_annual) - beta * (nifty50_cagr - rf_annual)
            else:
                beta, alpha = 1.0, 0.0
        else:
            beta, alpha = 1.0, 0.0
            
        betas.append(round(beta, 2))
        alphas.append(round(alpha * 100, 2))
        
    res_df["Beta vs Nifty50"] = betas
    res_df["Alpha vs Nifty50 (%)"] = alphas
    
    # Sort by Final Capital descending
    res_df = res_df.sort_values(by="Final Capital (₹)", ascending=False).reset_index(drop=True)
    return res_df


def main():
    parser = argparse.ArgumentParser(description="Backtest Mutual Funds and Benchmarks over 5-year period.")
    parser.add_argument("--start-date", type=str, default="2021-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2026-01-01", help="End date (YYYY-MM-DD)")
    parser.add_argument("--initial-capital", type=float, default=100000.0, help="Initial capital in INR")
    parser.add_argument("--rf-rate", type=float, default=0.06, help="Annual risk-free rate (default 0.06 = 6%%)")
    parser.add_argument("--output-json", type=str, default="results/mutual_funds_baseline_5yr.json", help="Output JSON filepath")
    parser.add_argument("--output-csv", type=str, default="results/mutual_funds_baseline_5yr.csv", help="Output CSV filepath")
    args = parser.parse_args()
    
    res_df = run_benchmark_backtest(args.start_date, args.end_date, args.initial_capital, args.rf_rate)
    
    print("\nSUMMARY RESULTS:")
    display_cols = [
        "Fund/Benchmark Name", "Category", "Final Capital (₹)", "CAGR (%)", 
        "Max Drawdown (%)", "Sharpe Ratio", "Sortino Ratio", "Alpha vs Nifty50 (%)"
    ]
    print(res_df[display_cols].to_string(index=False))
    
    # Save outputs
    out_dir = os.path.dirname(args.output_json)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        
    res_df.to_csv(args.output_csv, index=False)
    res_df.to_json(args.output_json, orient="records", indent=2)
    print(f"\nSaved CSV to {args.output_csv}")
    print(f"Saved JSON to {args.output_json}")

if __name__ == "__main__":
    main()
