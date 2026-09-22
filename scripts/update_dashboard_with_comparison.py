#!/usr/bin/env python3
"""
update_dashboard_with_comparison.py
===================================
Updates reports/gfs_2026_trade_log_dashboard.html and reports/index.html
with full multi-strategy benchmark comparisons:
- GFS 10-Position Regime Super-Compounder (+13.32%)
- GFS 15-Position Regime Compounder (+9.88%)
- Breakout/Retest Strategy Model A (-1.54%)
- Breakout/Retest Strategy Model C (-2.93%)
- NIFTY 50 Benchmark (-7.37%)
"""

import json
import pandas as pd
from pathlib import Path

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
comp_csv = BASE_DIR / "reports" / "strategy_comparison_2026.csv"
trades_csv = BASE_DIR / "reports" / "gfs_2026_trade_log.csv"

comp_df = pd.read_csv(comp_csv)
trades_df = pd.read_csv(trades_csv)

dates = comp_df["date"].tolist()
gfs_10 = [round(x, 2) for x in comp_df["gfs_10_regime"].tolist()]
gfs_15 = [round(x, 2) for x in comp_df["gfs_15_regime"].tolist()]
bo_c = [round(x, 2) for x in comp_df["bo_c_relvol"].tolist()]
bo_a = [round(x, 2) for x in comp_df["bo_a_equal"].tolist()]
nifty = [round(x, 2) for x in comp_df["nifty_50"].tolist()]

# Read the existing trade rows from the current HTML file
with open(BASE_DIR / "reports" / "gfs_2026_trade_log_dashboard.html", "r") as f:
    old_html = f.read()

# Extract the tbody of trades
tbody_start = old_html.find("<tbody>")
tbody_end = old_html.find("</tbody>")
trades_tbody = old_html[tbody_start + 7:tbody_end]

# Extract events tbody
events_start = old_html.rfind("<tbody>")
events_end = old_html.rfind("</tbody>")
events_tbody = old_html[events_start + 7:events_end]

html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GFS vs Breakout vs NIFTY — 2026 Head-to-Head Benchmark Dashboard</title>
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
                    <span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">GFS 10-SLOT LEADER (+13.3%)</span>
                    <span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">BREAKOUT/RETEST (-1.5%)</span>
                    <span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-500/20 text-rose-400 border border-rose-500/30">NIFTY 50 (-7.4%)</span>
                </div>
                <h1 class="text-xl md:text-2xl font-black text-white mt-1">2026 Strategy Benchmark & Head-to-Head Comparison</h1>
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
            <div class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
                <!-- Strategy 1: GFS 10 -->
                <div class="bg-slate-900 border-2 border-emerald-500/60 rounded-xl p-4 shadow-lg shadow-emerald-950/20 relative">
                    <span class="absolute -top-2.5 right-3 px-2 py-0.5 text-[10px] font-bold uppercase rounded bg-emerald-500 text-slate-950">#1 Top Performer</span>
                    <span class="text-xs text-slate-400 font-medium">GFS 10-Slot Regime</span>
                    <p class="text-xl font-black font-mono text-emerald-400 mt-1">₹1,13,319</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-2">
                        <span class="text-emerald-400 font-bold">+13.32%</span>
                        <span class="text-slate-400">MaxDD: -13.8%</span>
                    </div>
                    <p class="text-[11px] text-slate-400 mt-1">16 trades &bull; Monthly EMA9 exit</p>
                </div>

                <!-- Strategy 2: GFS 15 -->
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <span class="text-xs text-slate-400 font-medium">GFS 15-Slot Regime</span>
                    <p class="text-xl font-black font-mono text-sky-400 mt-1">₹1,09,884</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-2">
                        <span class="text-sky-400 font-bold">+9.88%</span>
                        <span class="text-slate-400">MaxDD: -13.8%</span>
                    </div>
                    <p class="text-[11px] text-slate-400 mt-1">24 trades &bull; 3M momentum rank</p>
                </div>

                <!-- Strategy 3: Breakout Model A -->
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <span class="text-xs text-slate-400 font-medium">Breakout/Retest (Equal Wt)</span>
                    <p class="text-xl font-black font-mono text-amber-400 mt-1">₹98,462</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-2">
                        <span class="text-amber-400 font-bold">-1.54%</span>
                        <span class="text-slate-400">MaxDD: -9.1%</span>
                    </div>
                    <p class="text-[11px] text-slate-400 mt-1">122 trades &bull; -3% SL &bull; EMA21 exit</p>
                </div>

                <!-- Strategy 4: Breakout Model C -->
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <span class="text-xs text-slate-400 font-medium">Breakout (RelVol Model C)</span>
                    <p class="text-xl font-black font-mono text-purple-400 mt-1">₹97,068</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-2">
                        <span class="text-purple-400 font-bold">-2.93%</span>
                        <span class="text-slate-400">MaxDD: -9.9%</span>
                    </div>
                    <p class="text-[11px] text-slate-400 mt-1">122 trades &bull; Vol-weighted slots</p>
                </div>

                <!-- Benchmark: NIFTY 50 -->
                <div class="bg-slate-900 border border-slate-800 rounded-xl p-4">
                    <span class="text-xs text-slate-400 font-medium">NIFTY 50 Benchmark</span>
                    <p class="text-xl font-black font-mono text-rose-400 mt-1">₹92,628</p>
                    <div class="mt-2 flex justify-between text-xs border-t border-slate-800 pt-2">
                        <span class="text-rose-400 font-bold">-7.37%</span>
                        <span class="text-slate-400">MaxDD: -15.2%</span>
                    </div>
                    <p class="text-[11px] text-slate-400 mt-1">Passive Buy & Hold (Index)</p>
                </div>
            </div>
        </div>

        <!-- Multi-Strategy Comparison Chart -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <div class="flex flex-wrap justify-between items-center mb-4 gap-2">
                <div>
                    <h2 class="text-lg font-bold text-white">2026 Daily Equity Curves: GFS vs Breakout vs NIFTY (₹1 Lakh Initial Capital)</h2>
                    <p class="text-xs text-slate-400">Direct visual comparison of how each strategy handled the 2026 Indian market correction.</p>
                </div>
                <div class="flex flex-wrap gap-4 text-xs font-mono">
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-emerald-400 inline-block"></span> GFS 10-Slot (+13.3%)</span>
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-sky-400 inline-block"></span> GFS 15-Slot (+9.9%)</span>
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-amber-400 inline-block"></span> Breakout Model A (-1.5%)</span>
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-purple-400 inline-block"></span> Breakout Model C (-2.9%)</span>
                    <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-rose-500 inline-block"></span> NIFTY 50 (-7.4%)</span>
                </div>
            </div>
            <div class="h-96">
                <canvas id="multiEquityChart"></canvas>
            </div>
        </div>

        <!-- Strategy Architecture Comparison Table -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <h3 class="text-md font-bold text-white mb-4">Why Did GFS Outperform Breakout/Retest by +15% Alpha in 2026?</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-xs text-slate-300">
                    <thead class="bg-slate-950 text-slate-400 uppercase border-b border-slate-800">
                        <tr>
                            <th class="px-4 py-3">Strategy System</th>
                            <th class="px-4 py-3">Macro Market Filter</th>
                            <th class="px-4 py-3">Entry Mechanism</th>
                            <th class="px-4 py-3">Exit Mechanism</th>
                            <th class="px-4 py-3">2026 Trades</th>
                            <th class="px-4 py-3">Why It Performed This Way</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-800 font-mono text-xs">
                        <tr class="bg-emerald-950/20">
                            <td class="px-4 py-3 font-bold text-emerald-400">GFS 10-Slot Regime</td>
                            <td class="px-4 py-3">NIFTY 200 EMA Schedule 1 (100% / 70% / 30%)</td>
                            <td class="px-4 py-3">Monthly RSI>60, Weekly RSI>60, Daily RSI crosses >40</td>
                            <td class="px-4 py-3 text-emerald-300 font-semibold">Monthly Close &lt; Monthly EMA9 (T+1 Open)</td>
                            <td class="px-4 py-3 font-bold text-emerald-400">16 trades</td>
                            <td class="px-4 py-3 font-sans text-slate-200">Patient monthly holding allowed runners (Thangamayil +66%, Mahamaya Steel +44%, Federal Bank +32%) to compound without getting stopped out by daily noise. Regime engine preserved cash in March.</td>
                        </tr>
                        <tr>
                            <td class="px-4 py-3 font-bold text-amber-400">Breakout/Retest (Model A & C)</td>
                            <td class="px-4 py-3">None (Always fully invested if signals exist)</td>
                            <td class="px-4 py-3">Monthly RSI>70, 20D High Breakout, Retest &plusmn;0.5%, Bullish Confirm</td>
                            <td class="px-4 py-3 text-rose-300">-3% Stop Loss &bull; Once +5%, Close &lt; EMA21 trailing</td>
                            <td class="px-4 py-3 font-bold text-rose-400">122 trades</td>
                            <td class="px-4 py-3 font-sans text-slate-300">In choppy sideways/falling markets (NIFTY fell -7.4%), the tight -3% stop loss suffered severe whipsaw churn. 122 trades generated small recurring friction losses before winners could activate trailing stops.</td>
                        </tr>
                        <tr>
                            <td class="px-4 py-3 font-bold text-rose-400">NIFTY 50 Benchmark</td>
                            <td class="px-4 py-3">N/A</td>
                            <td class="px-4 py-3">Passive Buy on Jan 1, 2026</td>
                            <td class="px-4 py-3">Hold through cycle</td>
                            <td class="px-4 py-3">1 trade</td>
                            <td class="px-4 py-3 font-sans text-slate-300">Broad Indian large-cap index fell from 26,146 to 24,219 (-7.37%) with a -15.18% max drawdown.</td>
                        </tr>
                    </tbody>
                </table>
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
        const boCData = {json.dumps(bo_c)};
        const boAData = {json.dumps(bo_a)};
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
                        label: 'Breakout Model A - Equal Wt (-1.5%)',
                        data: boAData,
                        borderColor: '#f59e0b',
                        borderWidth: 2,
                        tension: 0.15,
                        pointRadius: 0
                    }},
                    {{
                        label: 'Breakout Model C - RelVol (-2.9%)',
                        data: boCData,
                        borderColor: '#c084fc',
                        borderWidth: 2,
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

with open(html_path, "w") as f:
    f.write(html_template)

with open(index_path, "w") as f:
    f.write(html_template)

print("Dashboard successfully updated with multi-strategy comparison.")
