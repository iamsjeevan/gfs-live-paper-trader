#!/usr/bin/env python3
"""
update_dashboard_breakout_regime.py
===================================
Merges Breakout + Regime Schedule 1 series into the master comparison dataset
and updates reports/gfs_2026_trade_log_dashboard.html & reports/index.html.
"""

import json
import pandas as pd
from pathlib import Path

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
comp_csv = BASE_DIR / "reports" / "strategy_comparison_2026.csv"
bo_regime_csv = BASE_DIR / "reports" / "breakout_regime_comparison_2026.csv"
trades_csv = BASE_DIR / "reports" / "gfs_2026_trade_log.csv"

comp_df = pd.read_csv(comp_csv)
bo_df = pd.read_csv(bo_regime_csv)

# Merge columns
merged = comp_df.merge(bo_df[["date", "breakout_15_regime", "breakout_10_regime", "breakout_relvol_regime"]], on="date", how="left").ffill()
merged.to_csv(comp_csv, index=False)
print("Merged comparison dataset saved.")

dates = merged["date"].tolist()
gfs_10 = [round(x, 2) for x in merged["gfs_10_regime"].tolist()]
gfs_15 = [round(x, 2) for x in merged["gfs_15_regime"].tolist()]
bo_15_reg = [round(x, 2) for x in merged["breakout_15_regime"].tolist()]
bo_relvol_reg = [round(x, 2) for x in merged["breakout_relvol_regime"].tolist()]
bo_15_fixed = [round(x, 2) for x in merged["bo_a_equal"].tolist()]
nifty = [round(x, 2) for x in merged["nifty_50"].tolist()]

# Read the existing trade rows & event rows
with open(BASE_DIR / "reports" / "gfs_2026_trade_log_dashboard.html", "r") as f:
    old_html = f.read()

tbody_start = old_html.find("<tbody>")
tbody_end = old_html.find("</tbody>")
trades_tbody = old_html[tbody_start + 7:tbody_end]

events_start = old_html.rfind("<tbody>")
events_end = old_html.rfind("</tbody>")
events_tbody = old_html[events_start + 7:events_end]

html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GFS vs Breakout (Fixed vs Regime) vs NIFTY — 2026 Audit Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        body {{ font-family: 'Inter', sans-serif; }}
        .font-mono {{ font-family: 'JetBrains Mono', monospace; }}
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
    <!-- Top Nav -->
    <header class="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-6 py-4 flex flex-wrap justify-between items-center gap-4">
            <div>
                <div class="flex items-center gap-2">
                    <span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">GFS REGIME (+13.3%)</span>
                    <span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-cyan-500/20 text-cyan-400 border border-cyan-500/30">BREAKOUT + REGIME (+2.6%)</span>
                    <span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">BREAKOUT FIXED (-2.6%)</span>
                    <span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">NIFTY 50 (-7.4%)</span>
                </div>
                <h1 class="text-xl md:text-2xl font-black text-white mt-1">2026 Strategy Benchmark: Adding Regime to Breakout</h1>
            </div>
            <div class="text-right">
                <span class="text-xs text-slate-400">Exact Same Period</span>
                <p class="font-mono text-sm text-slate-200">2026-01-01 to 2026-08-24 (₹1 Lakh Capital)</p>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-6 py-8 space-y-8">

        <!-- Comparison Cards -->
        <div>
            <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">Head-to-Head Results (Starting with ₹1,00,000 on Jan 1, 2026)</h2>
            <div class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3">
                <!-- Strategy 1: GFS 10 -->
                <div class="bg-slate-900 border-2 border-emerald-500/70 rounded-xl p-4 shadow-lg shadow-emerald-950/20 relative">
                    <span class="absolute -top-2.5 right-2 px-2 py-0.2 text-[9px] font-bold uppercase rounded bg-emerald-500 text-slate-950">#1 Top Performer</span>
                    <span class="text-xs text-slate-400 font-medium">GFS 10-Slot Regime</span>
                    <p class="text-lg font-black font-mono text-emerald-400 mt-1">₹1,13,319</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-1.5">
                        <span class="text-emerald-400 font-bold">+13.32%</span>
                        <span class="text-slate-400">DD: -13.8%</span>
                    </div>
                    <p class="text-[10px] text-slate-400 mt-1">16 trades &bull; Monthly EMA9 exit</p>
                </div>

                <!-- Strategy 2: GFS 15 -->
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <span class="text-xs text-slate-400 font-medium">GFS 15-Slot Regime</span>
                    <p class="text-lg font-black font-mono text-sky-400 mt-1">₹1,09,884</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-1.5">
                        <span class="text-sky-400 font-bold">+9.88%</span>
                        <span class="text-slate-400">DD: -13.8%</span>
                    </div>
                    <p class="text-[10px] text-slate-400 mt-1">24 trades &bull; 3M momentum rank</p>
                </div>

                <!-- Strategy 3: Breakout RelVol + Regime -->
                <div class="bg-slate-900 border-2 border-cyan-500/60 rounded-xl p-4 relative">
                    <span class="absolute -top-2.5 right-2 px-2 py-0.2 text-[9px] font-bold uppercase rounded bg-cyan-500 text-slate-950">+5.5% Regime Boost</span>
                    <span class="text-xs text-slate-400 font-medium">Breakout RelVol + Regime</span>
                    <p class="text-lg font-black font-mono text-cyan-400 mt-1">₹1,02,629</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-1.5">
                        <span class="text-cyan-400 font-bold">+2.63%</span>
                        <span class="text-slate-400">DD: -10.3%</span>
                    </div>
                    <p class="text-[10px] text-slate-400 mt-1">84 trades &bull; RelVol allocation</p>
                </div>

                <!-- Strategy 4: Breakout Equal Wt + Regime -->
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <span class="text-xs text-slate-400 font-medium">Breakout 15 + Regime</span>
                    <p class="text-lg font-black font-mono text-indigo-300 mt-1">₹1,00,553</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-1.5">
                        <span class="text-indigo-300 font-bold">+0.55%</span>
                        <span class="text-slate-400">DD: -7.9%</span>
                    </div>
                    <p class="text-[10px] text-slate-400 mt-1">89 trades &bull; Turns positive!</p>
                </div>

                <!-- Strategy 5: Breakout Fixed (No Regime) -->
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <span class="text-xs text-slate-400 font-medium">Breakout 15 Fixed</span>
                    <p class="text-lg font-black font-mono text-amber-400 mt-1">₹97,418</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-1.5">
                        <span class="text-amber-400 font-bold">-2.58%</span>
                        <span class="text-slate-400">DD: -9.4%</span>
                    </div>
                    <p class="text-[10px] text-slate-400 mt-1">124 trades &bull; High stopout churn</p>
                </div>

                <!-- Benchmark: NIFTY 50 -->
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <span class="text-xs text-slate-400 font-medium">NIFTY 50 Index</span>
                    <p class="text-lg font-black font-mono text-rose-400 mt-1">₹92,628</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-1.5">
                        <span class="text-rose-400 font-bold">-7.37%</span>
                        <span class="text-slate-400">DD: -15.2%</span>
                    </div>
                    <p class="text-[10px] text-slate-400 mt-1">Passive Buy & Hold (Index)</p>
                </div>
            </div>
        </div>

        <!-- Multi-Strategy Comparison Chart -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <div class="flex flex-wrap justify-between items-center mb-4 gap-2">
                <div>
                    <h2 class="text-lg font-bold text-white">2026 Daily Equity Curves: Impact of Market Regime on Breakout vs GFS</h2>
                    <p class="text-xs text-slate-400">Regime Schedule 1 rescues Breakout/Retest from loss to profit, but GFS still leads by +10.7% to +13.3% alpha.</p>
                </div>
                <div class="flex flex-wrap gap-4 text-xs font-mono">
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-emerald-400 inline-block"></span> GFS 10-Slot Regime (+13.3%)</span>
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-sky-400 inline-block"></span> GFS 15-Slot Regime (+9.9%)</span>
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-cyan-400 inline-block"></span> Breakout RelVol + Regime (+2.6%)</span>
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-indigo-400 inline-block"></span> Breakout 15 + Regime (+0.55%)</span>
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-amber-400 inline-block"></span> Breakout 15 Fixed (-2.6%)</span>
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-rose-500 inline-block"></span> NIFTY 50 (-7.4%)</span>
                </div>
            </div>
            <div class="h-96">
                <canvas id="multiEquityChart"></canvas>
            </div>
        </div>

        <!-- What Happened When Regime was Added to Breakout -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <h3 class="text-md font-bold text-white mb-3">Key Empirical Finding: What Happened When We Added Regime to Breakout/Retest?</h3>
            <div class="grid md:grid-cols-2 gap-6 text-xs text-slate-300">
                <div class="bg-slate-950 p-4 rounded-lg border border-slate-800 space-y-2">
                    <span class="font-bold text-cyan-400 block text-sm">1. Regime Rescued Breakout from Negative to Positive</span>
                    <p>&bull; <strong>Without Regime</strong>: Breakout 15-Slot lost <strong>-2.58% (₹97,418)</strong> across 124 trades.</p>
                    <p>&bull; <strong>With Regime Schedule 1</strong>: Breakout 15-Slot ended positive at <strong>+0.55% (₹100,553)</strong> and Relative Volume Model C reached <strong>+2.63% (₹102,629)</strong>!</p>
                    <p>&bull; <strong>Whipsaw Trades Cut</strong>: Regime Schedule 1 eliminated <strong>35 to 40 losing stopout trades</strong> during the March 2026 market correction by keeping 70% cash in bear regimes.</p>
                </div>
                <div class="bg-slate-950 p-4 rounded-lg border border-slate-800 space-y-2">
                    <span class="font-bold text-emerald-400 block text-sm">2. Why GFS Still Outperforms by +10.7% Alpha</span>
                    <p>&bull; <strong>The Exit Difference</strong>: Breakout/Retest still uses the <strong>-3% stop loss and EMA21 trailing exit</strong>. In volatile Indian stocks, a tight -3% stop is frequently clipped before big winners can develop.</p>
                    <p>&bull; <strong>GFS Monthly EMA9 Exit</strong>: Allowed true winners like <strong>Thangamayil (+66.1%)</strong> and <strong>Mahamaya Steel (+43.9%)</strong> to breathe through normal daily dips.</p>
                    <p>&bull; <strong>Efficiency</strong>: GFS achieved <strong>+13.32% return with only 16 trades</strong>, while Breakout generated <strong>84 trades for +2.63%</strong>.</p>
                </div>
            </div>
        </div>

        <!-- Master Trade Audit Table (GFS) -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <div class="p-6 border-b border-slate-800 flex justify-between items-center">
                <div>
                    <h2 class="text-lg font-bold text-white">GFS 10-Slot Strategy: Complete 2026 Trade Audit (16 Stocks)</h2>
                    <p class="text-xs text-slate-400">Every stock traded by our best working strategy, RSI entry parameters, month-end review checkpoints, and P&L outcomes.</p>
                </div>
                <a href="gfs_2026_trade_log.csv" class="px-3 py-1.5 text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg transition">Export CSV</a>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm">
                    <thead class="bg-slate-950/80 text-xs uppercase tracking-wider text-slate-400 border-b border-slate-800">
                        <tr>
                            <th class="px-4 py-3">Symbol / Sector</th>
                            <th class="px-4 py-3">Status</th>
                            <th class="px-4 py-3">Signal & Entry Date</th>
                            <th class="px-4 py-3">Entry Open & Sizing</th>
                            <th class="px-4 py-3">RSI Metrics (D / W / M)</th>
                            <th class="px-4 py-3">Month-End Checkpoints</th>
                            <th class="px-4 py-3">Exit / Current Date & Price</th>
                            <th class="px-4 py-3 text-right">P&L % (₹ Net)</th>
                            <th class="px-4 py-3 text-center">Holding</th>
                        </tr>
                    </thead>
                    <tbody>
                        {trades_tbody}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Detailed Chronological Events Log -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <div class="p-6 border-b border-slate-800">
                <h2 class="text-lg font-bold text-white">Chronological Day-by-Day Event Log (2026)</h2>
                <p class="text-xs text-slate-400">Every single Buy, Sell, Month-End evaluation, and Market Regime shift recorded in chronological order.</p>
            </div>
            <div class="overflow-x-auto max-h-96 overflow-y-auto">
                <table class="w-full text-left text-sm">
                    <thead class="bg-slate-950/80 text-xs uppercase tracking-wider text-slate-400 border-b border-slate-800 sticky top-0">
                        <tr>
                            <th class="px-4 py-2.5">Date</th>
                            <th class="px-4 py-2.5">Event</th>
                            <th class="px-4 py-2.5">Symbol</th>
                            <th class="px-4 py-2.5">Details</th>
                        </tr>
                    </thead>
                    <tbody>
                        {events_tbody}
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <footer class="border-t border-slate-800 py-6 text-center text-xs text-slate-500">
        GFS Multi-Timeframe RSI Quantitative Research &bull; Indian Equity Market &bull; Zero Lookahead Bias Audit
    </footer>

    <script>
        const dates = {json.dumps(dates)};
        const gfs10Data = {json.dumps(gfs_10)};
        const gfs15Data = {json.dumps(gfs_15)};
        const bo15RegData = {json.dumps(bo_15_reg)};
        const boRelvolRegData = {json.dumps(bo_relvol_reg)};
        const bo15FixedData = {json.dumps(bo_15_fixed)};
        const niftyData = {json.dumps(nifty)};

        const ctx = document.getElementById('multiEquityChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: dates,
                datasets: [
                    {{
                        label: 'GFS 10-Slot Regime (+13.3%)',
                        data: gfs10Data,
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.05)',
                        borderWidth: 3,
                        fill: true,
                        tension: 0.15,
                        pointRadius: 0
                    }},
                    {{
                        label: 'GFS 15-Slot Regime (+9.9%)',
                        data: gfs15Data,
                        borderColor: '#38bdf8',
                        borderWidth: 2,
                        tension: 0.15,
                        pointRadius: 0
                    }},
                    {{
                        label: 'Breakout RelVol + Regime (+2.6%)',
                        data: boRelvolRegData,
                        borderColor: '#22d3ee',
                        borderWidth: 2,
                        tension: 0.15,
                        pointRadius: 0
                    }},
                    {{
                        label: 'Breakout 15 + Regime (+0.55%)',
                        data: bo15RegData,
                        borderColor: '#818cf8',
                        borderWidth: 2,
                        tension: 0.15,
                        pointRadius: 0
                    }},
                    {{
                        label: 'Breakout 15 Fixed (-2.6%)',
                        data: bo15FixedData,
                        borderColor: '#f59e0b',
                        borderWidth: 1.5,
                        borderDash: [3, 3],
                        tension: 0.15,
                        pointRadius: 0
                    }},
                    {{
                        label: 'NIFTY 50 Benchmark (-7.4%)',
                        data: niftyData,
                        borderColor: '#f43f5e',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        tension: 0.15,
                        pointRadius: 0
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                interaction: {{ intersect: false, mode: 'index' }},
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        backgroundColor: '#0f172a',
                        titleColor: '#94a3b8',
                        bodyColor: '#f8fafc',
                        borderColor: '#334155',
                        borderWidth: 1,
                        padding: 10
                    }}
                }},
                scales: {{
                    x: {{
                        grid: {{ color: 'rgba(51, 65, 85, 0.2)' }},
                        ticks: {{ color: '#64748b', maxTicksLimit: 12, font: {{ family: 'JetBrains Mono', size: 10 }} }}
                    }},
                    y: {{
                        grid: {{ color: 'rgba(51, 65, 85, 0.2)' }},
                        ticks: {{
                            color: '#64748b',
                            font: {{ family: 'JetBrains Mono', size: 10 }},
                            callback: function(v) {{ return '₹' + v.toLocaleString(); }}
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""

html_path = BASE_DIR / "reports" / "gfs_2026_trade_log_dashboard.html"
index_path = BASE_DIR / "reports" / "index.html"
brain_path = Path("/Users/jeevans/.gemini/antigravity-cli/brain/7d162b82-94da-4859-89c8-27cc503081a1/gfs_2026_trade_log_dashboard.html")

for p in [html_path, index_path, brain_path]:
    with open(p, "w") as f:
        f.write(html_template)

print("All HTML dashboards updated with Breakout + Regime Schedule 1.")
