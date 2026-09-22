"""Execute the complete Bitcoin momentum research suite across all milestones."""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sys
import time

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backtest.experiments import run_full_research_suite

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("run_backtest_suite")


def main():
    logger.info("Starting Bitcoin Momentum Research Suite (2017 - 2026)...")
    t0 = time.time()

    results = run_full_research_suite()

    elapsed = time.time() - t0
    logger.info(f"=== Research Suite Execution Complete in {elapsed:.2f}s ===")

    # Print Baseline Metrics
    baseline = results["baseline_1d"]
    bm = baseline.metrics
    logger.info("\n--- BASELINE 1D STRATEGY METRICS ---")
    for k, v in bm.items():
        if isinstance(v, float):
            logger.info(f"  {k:28s}: {v:12.4f}")
        else:
            logger.info(f"  {k:28s}: {v}")

    # Print Timeframe Grid Summary
    grid = results["grid_summary"]
    logger.info("\n--- TIMEFRAME & LEVERAGE GRID SUMMARY ---")
    logger.info(grid[["timeframe", "mode", "leverage", "cagr", "sharpe_ratio", "max_drawdown", "total_costs"]].to_string())

    # Print Regimes Breakdown
    logger.info("\n--- REGIMES BREAKDOWN ---")
    for r in results["regimes"]:
        logger.info(
            f"  {r['regime_name']:28s} ({r['regime_category']:8s}): Strat Return={r['strategy_return']*100:+7.1f}%, "
            f"Bench Return={r['benchmark_return']*100:+7.1f}%, Alpha={r['alpha_return']*100:+7.1f}%, "
            f"Strat Sharpe={r['strategy_sharpe']:5.2f}, MaxDD={r['strategy_max_dd']*100:5.1f}%"
        )

    # Print Walk-Forward Split
    split = results["split_results"]
    logger.info("\n--- WALK-FORWARD SPLIT ---")
    logger.info(f"  In-Sample (2017-2021) Sharpe : {split['is_metrics']['sharpe_ratio']:.3f}, CAGR: {split['is_metrics']['cagr']*100:.1f}%")
    logger.info(f"  Out-of-Sample (2022-2026) Sharpe: {split['oos_metrics']['sharpe_ratio']:.3f}, CAGR: {split['oos_metrics']['cagr']*100:.1f}%")
    logger.info(f"  Sharpe Degradation Ratio     : {split['sharpe_degradation']:.3f}x")


if __name__ == "__main__":
    main()
