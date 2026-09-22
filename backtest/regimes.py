"""Market regime definitions and regime-segmented performance evaluation."""

from typing import Any, Dict, List
import numpy as np
import pandas as pd

# Historical Bitcoin market regimes across the 2017-2026 history
REGIMES = [
    {
        "name": "2017 Bull Mania",
        "category": "BULL",
        "start": "2017-08-17 00:00:00",
        "end": "2017-12-17 23:59:59",
        "description": "Explosive retail mania from $4,000 to $20,000 ATH.",
    },
    {
        "name": "2018 Crypto Winter",
        "category": "BEAR",
        "start": "2017-12-18 00:00:00",
        "end": "2018-12-15 23:59:59",
        "description": "Prolonged bear market from $20k down to $3,120 (-84%).",
    },
    {
        "name": "2019 Recovery & Chop",
        "category": "SIDEWAYS",
        "start": "2018-12-16 00:00:00",
        "end": "2020-03-12 23:59:59",
        "description": "Rally to $14k followed by choppy bleed and COVID liquidity shock.",
    },
    {
        "name": "2020-2021 Bull Run",
        "category": "BULL",
        "start": "2020-03-13 00:00:00",
        "end": "2021-11-10 23:59:59",
        "description": "Institutional halving cycle run from $4,000 to $69,000 ATH.",
    },
    {
        "name": "2022 Crypto Crash",
        "category": "BEAR",
        "start": "2021-11-11 00:00:00",
        "end": "2022-11-21 23:59:59",
        "description": "Fed rate hiking cycle, Terra/Luna collapse, and FTX bankruptcy (-77%).",
    },
    {
        "name": "2023 Chop & Accumulation",
        "category": "SIDEWAYS",
        "start": "2022-11-22 00:00:00",
        "end": "2023-10-15 23:59:59",
        "description": "Grinding range-bound recovery from $16k to $27k.",
    },
    {
        "name": "2023-2024 ETF Bull Run",
        "category": "BULL",
        "start": "2023-10-16 00:00:00",
        "end": "2024-03-14 23:59:59",
        "description": "Spot ETF approvals, institutional inflows, rally to new ATH $73.7k.",
    },
    {
        "name": "2024 Summer Consolidation",
        "category": "SIDEWAYS",
        "start": "2024-03-15 00:00:00",
        "end": "2024-10-15 23:59:59",
        "description": "7-month post-halving chop and consolidation ($54k-$70k).",
    },
    {
        "name": "2024-2025 Post-Election ATH",
        "category": "BULL",
        "start": "2024-10-16 00:00:00",
        "end": "2025-01-20 23:59:59",
        "description": "US election catalyst, pro-crypto regulatory rally above $100k.",
    },
    {
        "name": "2025-2026 Late Cycle Chop",
        "category": "SIDEWAYS",
        "start": "2025-01-21 00:00:00",
        "end": "2026-09-12 23:59:59",
        "description": "High-level volatility, macro headwinds, and range consolidation.",
    },
]


def evaluate_regimes(equity_curve: pd.DataFrame, timeframe: str = "1d") -> List[Dict[str, Any]]:
    """Slice equity curve across distinct historical market regimes and evaluate performance.

    Parameters
    ----------
    equity_curve : pd.DataFrame
        DataFrame with 'datetime_utc', 'equity', 'benchmark_equity'.
    timeframe : str
        Candle timeframe.

    Returns
    -------
    List[Dict[str, Any]]
        List of regime performance summaries.
    """
    df = equity_curve.copy()
    from backtest.volatility import ANNUAL_PERIODS
    ann_periods = ANNUAL_PERIODS.get(timeframe.lower(), 365)

    results = []

    for reg in REGIMES:
        mask = (df["datetime_utc"] >= reg["start"]) & (df["datetime_utc"] <= reg["end"])
        sub_df = df[mask]

        if len(sub_df) < 5:
            continue

        init_strat = sub_df["equity"].iloc[0]
        final_strat = sub_df["equity"].iloc[-1]
        strat_return = (final_strat - init_strat) / init_strat if init_strat > 0 else 0.0

        init_bench = sub_df["benchmark_equity"].iloc[0]
        final_bench = sub_df["benchmark_equity"].iloc[-1]
        bench_return = (final_bench - init_bench) / init_bench if init_bench > 0 else 0.0

        # Sub-period returns
        pct_rets = sub_df["equity"].pct_change().dropna()
        strat_vol = pct_rets.std(ddof=1) * np.sqrt(ann_periods) if len(pct_rets) > 1 else 0.0
        strat_sharpe = (pct_rets.mean() * ann_periods / strat_vol) if strat_vol > 1e-8 else 0.0

        # Drawdown within regime
        peak = sub_df["equity"].cummax()
        reg_dd = (sub_df["equity"] - peak) / peak
        strat_max_dd = float(reg_dd.min())

        bench_pct_rets = sub_df["benchmark_equity"].pct_change().dropna()
        bench_vol = bench_pct_rets.std(ddof=1) * np.sqrt(ann_periods) if len(bench_pct_rets) > 1 else 0.0
        bench_sharpe = (bench_pct_rets.mean() * ann_periods / bench_vol) if bench_vol > 1e-8 else 0.0

        bench_peak = sub_df["benchmark_equity"].cummax()
        bench_max_dd = float(((sub_df["benchmark_equity"] - bench_peak) / bench_peak).min())

        results.append({
            "regime_name": reg["name"],
            "regime_category": reg["category"],
            "period_start": reg["start"],
            "period_end": reg["end"],
            "bars_count": len(sub_df),
            "strategy_return": strat_return,
            "benchmark_return": bench_return,
            "strategy_sharpe": strat_sharpe,
            "benchmark_sharpe": bench_sharpe,
            "strategy_max_dd": strat_max_dd,
            "benchmark_max_dd": bench_max_dd,
            "alpha_return": strat_return - bench_return,
        })

    return results
