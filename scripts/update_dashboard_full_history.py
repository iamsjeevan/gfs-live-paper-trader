#!/usr/bin/env python3
"""
update_dashboard_full_history.py
================================
Updates reports/gfs_2026_trade_log_dashboard.html, reports/index.html,
and the brain artifact directory with:
1. Full 8.6-Year History (2018-2026): ₹1 Lakh -> ₹13.9 Lakhs (GFS 10-Slot)
2. 2026 Year-to-Date Audit: ₹1 Lakh -> ₹1.13 Lakhs (GFS 10-Slot)
3. Interactive Tab Switcher: Full History vs 2026 Detailed Audit
"""

import json
import pandas as pd
from pathlib import Path

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
full_csv = BASE_DIR / "reports" / "full_history_1lakh_comparison.csv"
comp_csv = BASE_DIR / "reports" / "strategy_comparison_2026.csv"
trades_csv = BASE_DIR / "reports" / "gfs_2026_trade_log.csv"

full_df = pd.read_csv(full_csv)
comp_df = pd.read_csv(comp_csv)
trades_df = pd.read_csv(trades_csv)

# Downsample full_df slightly for silky-smooth web rendering (1 point every 3 days or weekly, or all 2130 points)
full_dates = full_df["date"].tolist()
full_gfs10 = [round(x, 2) for x in full_df["gfs_10_regime"].tolist()]
full_gfs15 = [round(x, 2) for x in full_df["gfs_15_regime"].tolist()]
full_bo_rel = [round(x, 2) for x in full_df["breakout_relvol_regime"].tolist()]
full_bo_eq = [round(x, 2) for x in full_df["breakout_equal_regime"].tolist()]
full_nifty = [round(x, 2) for x in full_df["nifty_50"].tolist()]

# 2026 data
ytd_dates = comp_df["date"].tolist()
ytd_gfs10 = [round(x, 2) for x in comp_df["gfs_10_regime"].tolist()]
ytd_gfs15 = [round(x, 2) for x in comp_df["gfs_15_regime"].tolist()]
ytd_bo_rel = [round(x, 2) for x in comp_df["breakout_relvol_regime"].tolist()]
ytd_bo_eq = [round(x, 2) for x in comp_df["breakout_15_regime"].tolist()]
ytd_nifty = [round(x, 2) for x in comp_df["nifty_50"].tolist()]

# Read the existing trade rows & event rows from existing HTML
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
    <title>GFS vs Breakout vs NIFTY — Full History (2018–2026) & 2026 Audit</title>
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
                    <span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">8.6-YEAR COMPOUNDING STUDY</span>
                    <span class="px-2.5 py-0.5 rounded-full text-xs font-bold bg-sky-500/20 text-sky-400 border border-sky-500/30">₹1 LAKH CAPITAL</span>
                </div>
                <h1 class="text-xl md:text-2xl font-black text-white mt-1">Full Historical Wealth Compounding (2018–2026) & 2026 Live Audit</h1>
            </div>
            <div class="flex items-center gap-3">
                <button onclick="switchView('full')" id="btnFull" class="px-4 py-2 text-xs font-bold rounded-lg bg-emerald-600 text-white shadow-lg transition">Full History (2018–2026)</button>
                <button onclick="switchView('ytd')" id="btnYtd" class="px-4 py-2 text-xs font-bold rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition">2026 Year-to-Date</button>
            </div>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-6 py-8 space-y-8">

        <!-- VIEW 1: FULL HISTORY (2018-2026) -->
        <div id="fullHistorySection" class="space-y-8">
            <!-- Full History KPI Cards -->
            <div>
                <div class="flex justify-between items-center mb-3">
                    <h2 class="text-sm font-semibold uppercase tracking-wider text-slate-400">Total Wealth Generated from ₹1,00,000 (Jan 2, 2018 to Aug 24, 2026 — 8.64 Years)</h2>
                    <span class="text-xs font-mono text-emerald-400">2,130 Trading Days Evaluated</span>
                </div>
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    <!-- GFS 10 -->
                    <div class="bg-slate-900 border-2 border-emerald-500/70 rounded-xl p-5 shadow-xl shadow-emerald-950/20 relative">
                        <span class="absolute -top-2.5 right-3 px-2 py-0.5 text-[10px] font-black uppercase rounded bg-emerald-500 text-slate-950">#1 Ultimate Winner (13.9x)</span>
                        <span class="text-xs text-slate-400 font-medium">GFS 10-Slot + Regime Sch 1</span>
                        <p class="text-2xl font-black font-mono text-emerald-400 mt-1">₹13,90,019</p>
                        <div class="mt-3 flex justify-between text-xs border-t border-slate-800 pt-2 font-mono">
                            <span class="text-emerald-300 font-bold">+1290.0% (36.37% CAGR)</span>
                            <span class="text-slate-400">DD: -30.8%</span>
                        </div>
                        <p class="text-[11px] text-slate-400 mt-1">Only 74 trades &bull; Profit Factor 8.91 &bull; Calmar 1.18</p>
                    </div>

                    <!-- GFS 15 -->
                    <div class="bg-slate-900 border border-slate-800 rounded-xl p-5">
                        <span class="text-xs text-slate-400 font-medium">GFS 15-Slot + Regime Sch 1</span>
                        <p class="text-2xl font-black font-mono text-sky-400 mt-1">₹10,49,103</p>
                        <div class="mt-3 flex justify-between text-xs border-t border-slate-800 pt-2 font-mono">
                            <span class="text-sky-300 font-bold">+949.1% (31.92% CAGR)</span>
                            <span class="text-slate-400">DD: -26.5%</span>
                        </div>
                        <p class="text-[11px] text-slate-400 mt-1">114 trades &bull; Profit Factor 6.23 &bull; Calmar 1.20</p>
                    </div>

                    <!-- Breakout Equal + Regime -->
                    <div class="bg-slate-900 border border-slate-800 rounded-xl p-5">
                        <span class="text-xs text-slate-400 font-medium">Breakout 15 + Regime Sch 1</span>
                        <p class="text-2xl font-black font-mono text-indigo-400 mt-1">₹8,56,973</p>
                        <div class="mt-3 flex justify-between text-xs border-t border-slate-800 pt-2 font-mono">
                            <span class="text-indigo-300 font-bold">+757.0% (28.22% CAGR)</span>
                            <span class="text-slate-400">DD: -23.8%</span>
                        </div>
                        <p class="text-[11px] text-slate-400 mt-1">1,762 trades &bull; Profit Factor 1.77 &bull; Heavy churn</p>
                    </div>

                    <!-- NIFTY 50 -->
                    <div class="bg-slate-900 border border-slate-800 rounded-xl p-5">
                        <span class="text-xs text-slate-400 font-medium">NIFTY 50 Benchmark</span>
                        <p class="text-2xl font-black font-mono text-rose-400 mt-1">₹2,31,934</p>
                        <div class="mt-3 flex justify-between text-xs border-t border-slate-800 pt-2 font-mono">
                            <span class="text-rose-300 font-bold">+131.9% (10.23% CAGR)</span>
                            <span class="text-slate-400">DD: -38.4%</span>
                        </div>
                        <p class="text-[11px] text-slate-400 mt-1">Passive Buy & Hold &bull; 1 trade &bull; Severe 2020 crash</p>
                    </div>
                </div>
            </div>

            <!-- Full History Chart -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <div class="flex flex-wrap justify-between items-center mb-4 gap-2">
                    <div>
                        <h2 class="text-lg font-bold text-white">Full Historical Compounding Curves (Jan 2018 – Aug 2026, ₹1 Lakh Capital)</h2>
                        <p class="text-xs text-slate-400">Visualizing the 8.64-year exponential wealth explosion of GFS vs Breakout vs NIFTY 50.</p>
                    </div>
                    <div class="flex flex-wrap gap-4 text-xs font-mono">
                        <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-emerald-400 inline-block"></span> GFS 10-Slot (₹13.9L)</span>
                        <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-sky-400 inline-block"></span> GFS 15-Slot (₹10.5L)</span>
                        <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-indigo-400 inline-block"></span> Breakout + Regime (₹8.6L)</span>
                        <span class="flex items-center gap-1.5"><span class="w-3 h-3 rounded bg-rose-500 inline-block"></span> NIFTY 50 (₹2.3L)</span>
                    </div>
                </div>
                <div class="h-96">
                    <canvas id="fullHistoryChart"></canvas>
                </div>
            </div>

            <!-- Full History Deep Dive Comparison Table -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <h3 class="text-md font-bold text-white mb-4">Complete 8.6-Year Quantitative Audit Table (2018–2026)</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-xs font-mono text-slate-300">
                        <thead class="bg-slate-950 text-slate-400 uppercase border-b border-slate-800">
                            <tr>
                                <th class="px-4 py-3">Strategy / Benchmark</th>
                                <th class="px-4 py-3 text-right">Starting Capital</th>
                                <th class="px-4 py-3 text-right">Ending Capital</th>
                                <th class="px-4 py-3 text-right">Total Net Return</th>
                                <th class="px-4 py-3 text-right">Annual CAGR</th>
                                <th class="px-4 py-3 text-right">Max Drawdown</th>
                                <th class="px-4 py-3 text-right">Profit Factor</th>
                                <th class="px-4 py-3 text-center">Trades Taken</th>
                                <th class="px-4 py-3 text-center">Avg Trades / Yr</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-800">
                            <tr class="bg-emerald-950/20 font-semibold text-emerald-400">
                                <td class="px-4 py-3.5">GFS 10-Slot + Regime Sch 1 (Weekly RSI)</td>
                                <td class="px-4 py-3.5 text-right">₹1,00,000</td>
                                <td class="px-4 py-3.5 text-right font-bold text-emerald-300">₹13,90,019.32</td>
                                <td class="px-4 py-3.5 text-right">+1,290.0%</td>
                                <td class="px-4 py-3.5 text-right text-emerald-300">36.37%</td>
                                <td class="px-4 py-3.5 text-right">-30.83%</td>
                                <td class="px-4 py-3.5 text-right">8.91</td>
                                <td class="px-4 py-3.5 text-center">74</td>
                                <td class="px-4 py-3.5 text-center text-slate-400">~8.5</td>
                            </tr>
                            <tr class="text-sky-300">
                                <td class="px-4 py-3.5">GFS 15-Slot + Regime Sch 1 (3M Return)</td>
                                <td class="px-4 py-3.5 text-right">₹1,00,000</td>
                                <td class="px-4 py-3.5 text-right font-bold">₹10,49,103.10</td>
                                <td class="px-4 py-3.5 text-right">+949.1%</td>
                                <td class="px-4 py-3.5 text-right">31.92%</td>
                                <td class="px-4 py-3.5 text-right text-emerald-400">-26.54%</td>
                                <td class="px-4 py-3.5 text-right">6.23</td>
                                <td class="px-4 py-3.5 text-center">114</td>
                                <td class="px-4 py-3.5 text-center text-slate-400">~13.2</td>
                            </tr>
                            <tr>
                                <td class="px-4 py-3.5">GFS 15-Slot Fixed 100% (3M Return)</td>
                                <td class="px-4 py-3.5 text-right">₹1,00,000</td>
                                <td class="px-4 py-3.5 text-right">₹7,64,328.28</td>
                                <td class="px-4 py-3.5 text-right">+664.3%</td>
                                <td class="px-4 py-3.5 text-right">27.09%</td>
                                <td class="px-4 py-3.5 text-right">-32.84%</td>
                                <td class="px-4 py-3.5 text-right">5.06</td>
                                <td class="px-4 py-3.5 text-center">139</td>
                                <td class="px-4 py-3.5 text-center text-slate-400">~16.1</td>
                            </tr>
                            <tr class="text-indigo-300">
                                <td class="px-4 py-3.5">Breakout Equal Wt 15 + Regime Sch 1</td>
                                <td class="px-4 py-3.5 text-right">₹1,00,000</td>
                                <td class="px-4 py-3.5 text-right font-bold">₹8,56,973.05</td>
                                <td class="px-4 py-3.5 text-right">+757.0%</td>
                                <td class="px-4 py-3.5 text-right">28.22%</td>
                                <td class="px-4 py-3.5 text-right text-emerald-400">-23.82%</td>
                                <td class="px-4 py-3.5 text-right">1.77</td>
                                <td class="px-4 py-3.5 text-center text-amber-400">1,762</td>
                                <td class="px-4 py-3.5 text-center text-slate-400">~204.0</td>
                            </tr>
                            <tr class="text-cyan-300">
                                <td class="px-4 py-3.5">Breakout RelVol 15 + Regime Sch 1</td>
                                <td class="px-4 py-3.5 text-right">₹1,00,000</td>
                                <td class="px-4 py-3.5 text-right font-bold">₹8,33,297.80</td>
                                <td class="px-4 py-3.5 text-right">+733.3%</td>
                                <td class="px-4 py-3.5 text-right">27.80%</td>
                                <td class="px-4 py-3.5 text-right">-28.40%</td>
                                <td class="px-4 py-3.5 text-right">1.78</td>
                                <td class="px-4 py-3.5 text-center text-amber-400">1,727</td>
                                <td class="px-4 py-3.5 text-center text-slate-400">~199.9</td>
                            </tr>
                            <tr class="text-amber-400">
                                <td class="px-4 py-3.5">Breakout Equal Wt 15 Fixed 100%</td>
                                <td class="px-4 py-3.5 text-right">₹1,00,000</td>
                                <td class="px-4 py-3.5 text-right">₹9,72,621.41</td>
                                <td class="px-4 py-3.5 text-right">+872.6%</td>
                                <td class="px-4 py-3.5 text-right">30.11%</td>
                                <td class="px-4 py-3.5 text-right">-27.74%</td>
                                <td class="px-4 py-3.5 text-right">1.73</td>
                                <td class="px-4 py-3.5 text-center text-rose-400">2,041</td>
                                <td class="px-4 py-3.5 text-center text-slate-400">~236.2</td>
                            </tr>
                            <tr class="text-rose-400 font-bold bg-rose-950/10">
                                <td class="px-4 py-3.5">NIFTY 50 Benchmark (Buy & Hold)</td>
                                <td class="px-4 py-3.5 text-right">₹1,00,000</td>
                                <td class="px-4 py-3.5 text-right">₹2,31,934.37</td>
                                <td class="px-4 py-3.5 text-right">+131.9%</td>
                                <td class="px-4 py-3.5 text-right">10.23%</td>
                                <td class="px-4 py-3.5 text-right text-rose-500">-38.44%</td>
                                <td class="px-4 py-3.5 text-right">N/A</td>
                                <td class="px-4 py-3.5 text-center">1</td>
                                <td class="px-4 py-3.5 text-center text-slate-400">0.1</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Crucial Takeaways for Working Professional -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <h3 class="text-md font-bold text-white mb-3">Why GFS is Vastly Superior for a Working Professional</h3>
                <div class="grid md:grid-cols-3 gap-4 text-xs text-slate-300">
                    <div class="bg-slate-950 p-4 rounded-lg border border-slate-800">
                        <span class="font-bold text-emerald-400 text-sm block mb-1">1. 24x Less Work & Stress</span>
                        Over 8.6 years, Breakout forced <strong>1,762 to 2,041 trades</strong> (~200 trades/year, requiring daily stop checks). GFS required only <strong>74 trades total</strong> (~8 trades/year), requiring only a monthly check!
                    </div>
                    <div class="bg-slate-950 p-4 rounded-lg border border-slate-800">
                        <span class="font-bold text-emerald-400 text-sm block mb-1">2. +₹5.33 Lakhs Extra Profit</span>
                        Starting with ₹1 Lakh, GFS 10-Slot compounded to <strong>₹13.90 Lakhs</strong> vs <strong>₹8.57 Lakhs</strong> for Breakout and <strong>₹2.31 Lakhs</strong> for NIFTY 50.
                    </div>
                    <div class="bg-slate-950 p-4 rounded-lg border border-slate-800">
                        <span class="font-bold text-emerald-400 text-sm block mb-1">3. Monolithic Profit Factor (8.91)</span>
                        In GFS, gross winning profits were <strong>8.91 times larger than gross losses</strong>, because patient Monthly EMA9 holding allowed true multi-baggers (like +1465% in CUPID) to fully express themselves.
                    </div>
                </div>
            </div>
        </div>

        <!-- VIEW 2: 2026 YEAR-TO-DATE AUDIT (Hidden by default, toggled via button) -->
        <div id="ytdSection" class="space-y-8 hidden">
            <!-- 2026 Comparison Chart -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
                <div class="flex flex-wrap justify-between items-center mb-4 gap-2">
                    <div>
                        <h2 class="text-lg font-bold text-white">2026 Daily Equity Curves (Jan 1, 2026 – Aug 24, 2026)</h2>
                        <p class="text-xs text-slate-400">Head-to-head performance during the 2026 Indian market correction.</p>
                    </div>
                </div>
                <div class="h-80">
                    <canvas id="ytdChart"></canvas>
                </div>
            </div>

            <!-- Master Trade Audit Table (GFS 2026) -->
            <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
                <div class="p-6 border-b border-slate-800 flex justify-between items-center">
                    <div>
                        <h2 class="text-lg font-bold text-white">GFS 10-Slot Strategy: Complete 2026 Trade Audit (16 Stocks)</h2>
                        <p class="text-xs text-slate-400">Every stock traded by our best working strategy in 2026 with month-end review checkpoints.</p>
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
        </div>
    </main>

    <footer class="border-t border-slate-800 py-6 text-center text-xs text-slate-500">
        GFS Multi-Timeframe RSI Quantitative Research &bull; Indian Equity Market &bull; Zero Lookahead Bias Audit
    </footer>

    <script>
        // Full History Data
        const fullDates = {json.dumps(full_dates)};
        const fullGfs10 = {json.dumps(full_gfs10)};
        const fullGfs15 = {json.dumps(full_gfs15)};
        const fullBoEq = {json.dumps(full_bo_eq)};
        const fullNifty = {json.dumps(full_nifty)};

        // YTD Data
        const ytdDates = {json.dumps(ytd_dates)};
        const ytdGfs10 = {json.dumps(ytd_gfs10)};
        const ytdGfs15 = {json.dumps(ytd_gfs15)};
        const ytdBoRel = {json.dumps(ytd_bo_rel)};
        const ytdBoEq = {json.dumps(ytd_bo_eq)};
        const ytdNifty = {json.dumps(ytd_nifty)};

        // Render Full History Chart
        const ctxFull = document.getElementById('fullHistoryChart').getContext('2d');
        new Chart(ctxFull, {{
            type: 'line',
            data: {{
                labels: fullDates,
                datasets: [
                    {{
                        label: 'GFS 10-Slot Regime (₹13.9L | 36.4% CAGR)',
                        data: fullGfs10,
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.05)',
                        borderWidth: 2.5,
                        fill: true,
                        tension: 0.1,
                        pointRadius: 0
                    }},
                    {{
                        label: 'GFS 15-Slot Regime (₹10.5L | 31.9% CAGR)',
                        data: fullGfs15,
                        borderColor: '#38bdf8',
                        borderWidth: 2,
                        tension: 0.1,
                        pointRadius: 0
                    }},
                    {{
                        label: 'Breakout 15 + Regime (₹8.6L | 28.2% CAGR)',
                        data: fullBoEq,
                        borderColor: '#818cf8',
                        borderWidth: 1.5,
                        tension: 0.1,
                        pointRadius: 0
                    }},
                    {{
                        label: 'NIFTY 50 Benchmark (₹2.3L | 10.2% CAGR)',
                        data: fullNifty,
                        borderColor: '#f43f5e',
                        borderWidth: 1.5,
                        borderDash: [4, 4],
                        tension: 0.1,
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
                        padding: 10,
                        callbacks: {{
                            label: function(c) {{ return c.dataset.label.split('(')[0] + ': ₹' + Number(c.raw).toLocaleString(); }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        grid: {{ color: 'rgba(51, 65, 85, 0.2)' }},
                        ticks: {{ color: '#64748b', maxTicksLimit: 14, font: {{ family: 'JetBrains Mono', size: 10 }} }}
                    }},
                    y: {{
                        grid: {{ color: 'rgba(51, 65, 85, 0.2)' }},
                        ticks: {{
                            color: '#64748b',
                            font: {{ family: 'JetBrains Mono', size: 10 }},
                            callback: function(v) {{ return '₹' + (v/100000).toFixed(1) + 'L'; }}
                        }}
                    }}
                }}
            }}
        }});

        // Render YTD Chart
        let ytdChartInstance = null;
        function renderYtdChart() {{
            if (ytdChartInstance) return;
            const ctxYtd = document.getElementById('ytdChart').getContext('2d');
            ytdChartInstance = new Chart(ctxYtd, {{
                type: 'line',
                data: {{
                    labels: ytdDates,
                    datasets: [
                        {{ label: 'GFS 10-Slot (+13.3%)', data: ytdGfs10, borderColor: '#10b981', borderWidth: 2.5, pointRadius: 0 }},
                        {{ label: 'GFS 15-Slot (+9.9%)', data: ytdGfs15, borderColor: '#38bdf8', borderWidth: 2, pointRadius: 0 }},
                        {{ label: 'Breakout RelVol (+2.6%)', data: ytdBoRel, borderColor: '#22d3ee', borderWidth: 1.5, pointRadius: 0 }},
                        {{ label: 'Breakout 15 (+0.55%)', data: ytdBoEq, borderColor: '#818cf8', borderWidth: 1.5, pointRadius: 0 }},
                        {{ label: 'NIFTY 50 (-7.4%)', data: ytdNifty, borderColor: '#f43f5e', borderWidth: 1.5, borderDash: [4, 4], pointRadius: 0 }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {{
                        x: {{ grid: {{ color: 'rgba(51, 65, 85, 0.2)' }}, ticks: {{ color: '#64748b', maxTicksLimit: 10 }} }},
                        y: {{ grid: {{ color: 'rgba(51, 65, 85, 0.2)' }}, ticks: {{ color: '#64748b', callback: v => '₹' + v.toLocaleString() }} }}
                    }}
                }}
            }});
        }}

        function switchView(mode) {{
            const fullSec = document.getElementById('fullHistorySection');
            const ytdSec = document.getElementById('ytdSection');
            const btnFull = document.getElementById('btnFull');
            const btnYtd = document.getElementById('btnYtd');

            if (mode === 'full') {{
                fullSec.classList.remove('hidden');
                ytdSec.classList.add('hidden');
                btnFull.className = 'px-4 py-2 text-xs font-bold rounded-lg bg-emerald-600 text-white shadow-lg transition';
                btnYtd.className = 'px-4 py-2 text-xs font-bold rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition';
            }} else {{
                fullSec.classList.add('hidden');
                ytdSec.classList.remove('hidden');
                btnYtd.className = 'px-4 py-2 text-xs font-bold rounded-lg bg-emerald-600 text-white shadow-lg transition';
                btnFull.className = 'px-4 py-2 text-xs font-bold rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition';
                renderYtdChart();
            }}
        }}
    </script>
</body>
</html>
"""

for p in [BASE_DIR / "reports" / "gfs_2026_trade_log_dashboard.html", BASE_DIR / "reports" / "index.html", Path("/Users/jeevans/.gemini/antigravity-cli/brain/7d162b82-94da-4859-89c8-27cc503081a1/gfs_2026_trade_log_dashboard.html")]:
    with open(p, "w") as f:
        f.write(html_template)

print("HTML dashboard successfully updated with full 8.6-year history and tab switcher.")
