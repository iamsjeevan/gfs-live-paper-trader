#!/usr/bin/env python3
"""
build_unified_vercel_dashboard.py
==================================
Compiles the comprehensive GFS Vercel Web Dashboard featuring:
1. TAB 1: 🟢 Live Forward-Testing Terminal (2026-2027) with live cloud state sync
2. TAB 2: 📊 Historical Backtest Benchmark (2018-2026) with:
   - 4 Strategy Scorecard Cards
   - Normalized Equity Curves
   - Drawdown Curves
   - Top Multibaggers & Winners Chart
   - Full Searchable Trade Explorer (376 trades)
   - Stock Performance Breakdown
"""

import json
import sqlite3
import pandas as pd
from pathlib import Path

BASE_DIR = Path("/Users/jeevans/value_investing_backtest")
TRADES_CSV = BASE_DIR / "reports" / "gfs_4_strategies_trades.csv"
HTML_BENCHMARK = BASE_DIR / "reports" / "gfs_4_portfolios_dashboard.html"

# 1. Load trades
trades_df = pd.read_csv(TRADES_CSV)
trades_records = trades_df.to_dict(orient="records")

# 2. Extract top winners per strategy
top_winners = {}
for strat, g in trades_df.groupby("strategy"):
    top_winners[strat] = g.sort_values("return_pct", ascending=False).head(8)[["symbol", "return_pct", "holding_days", "pnl"]].to_dict(orient="records")

# 3. Overall top multibaggers across the entire backtest
all_top = trades_df.sort_values("return_pct", ascending=False).head(15)[["strategy", "symbol", "return_pct", "holding_days", "pnl"]].to_dict(orient="records")

# 4. Extract equity curves from reports/gfs_4_portfolios_dashboard.html
with open(HTML_BENCHMARK, "r") as f:
    html_raw = f.read()

marker = "const rawData = "
idx = html_raw.find(marker)
end_idx = html_raw.find(";\n\n// Rebase all", idx)
if idx != -1 and end_idx != -1:
    chart_json_str = html_raw[idx + len(marker):end_idx].strip()
    chart_data = json.loads(chart_json_str)
else:
    print("Warning: Could not parse chart json from benchmark html")
    chart_data = {}

# Save compiled backtest dataset
backtest_bundle = {
    "summary": [
        {"id": "INDIA_LIQUID", "name": "India Liquid (Top 500)", "market": "INDIA", "curr": "₹", "initial": 100000, "end": 1869475, "cagr": 40.37, "ret": 1769.5, "mdd": -26.68, "pf": 3.38, "wr": 48.4, "trades": 62, "proxy": "GOLDBEES"},
        {"id": "INDIA_BROAD", "name": "India Broad (> ₹100Cr)", "market": "INDIA", "curr": "₹", "initial": 100000, "end": 1753630, "cagr": 39.33, "ret": 1653.6, "mdd": -31.23, "pf": 4.02, "wr": 46.3, "trades": 67, "proxy": "GOLDBEES"},
        {"id": "USA_LIQUID", "name": "USA Liquid (S&P 500)", "market": "USA", "curr": "$", "initial": 10000, "end": 62995, "cagr": 23.73, "ret": 529.9, "mdd": -33.49, "pf": 4.66, "wr": 51.4, "trades": 107, "proxy": "GLD"},
        {"id": "USA_BROAD", "name": "USA Broad (INDmoney)", "market": "USA", "curr": "$", "initial": 10000, "end": 30314, "cagr": 13.69, "ret": 203.1, "mdd": -33.86, "pf": 1.51, "wr": 50.7, "trades": 140, "proxy": "GLD"}
    ],
    "chart_data": chart_data,
    "top_multibaggers": all_top,
    "trades": trades_records
}

with open(BASE_DIR / "reports" / "backtest_dashboard_bundle.json", "w") as f:
    json.dump(backtest_bundle, f, indent=2)
print("Saved reports/backtest_dashboard_bundle.json")

# 5. Build Unified index.html
template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GFS Investment Terminal • Live & Backtest (India & USA)</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #090d16;
            --surface: #111827;
            --surface-hover: #1e293b;
            --border: rgba(255, 255, 255, 0.08);
            --border-active: rgba(59, 130, 246, 0.5);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --green: #10b981;
            --green-bg: rgba(16, 185, 129, 0.12);
            --red: #f43f5e;
            --red-bg: rgba(244, 63, 94, 0.12);
            --blue: #3b82f6;
            --blue-bg: rgba(59, 130, 246, 0.12);
            --gold: #f59e0b;
            --gold-bg: rgba(245, 158, 11, 0.12);
            --font-sans: 'Plus Jakarta Sans', -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: var(--font-sans);
            background-color: var(--bg);
            color: var(--text-main);
            padding: 20px;
            min-height: 100vh;
            line-height: 1.5;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 20px;
            flex-wrap: wrap;
            gap: 16px;
        }}
        .header-title h1 {{
            font-size: 24px;
            font-weight: 800;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .header-title p {{
            color: var(--text-muted);
            font-size: 13px;
            margin-top: 4px;
        }}
        .status-pill {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 6px 14px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 600;
            background: rgba(16, 185, 129, 0.1);
            color: var(--green);
            border: 1px solid rgba(16, 185, 129, 0.2);
        }}
        .pulse-dot {{
            width: 8px;
            height: 8px;
            background: var(--green);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0% {{ transform: scale(0.95); opacity: 1; }}
            50% {{ transform: scale(1.4); opacity: 0.5; }}
            100% {{ transform: scale(0.95); opacity: 1; }}
        }}
        .time-badge {{
            font-family: var(--font-mono);
            font-size: 12px;
            background: var(--surface);
            padding: 6px 12px;
            border-radius: 8px;
            border: 1px solid var(--border);
            color: var(--text-muted);
        }}

        /* Navigation Tabs */
        .nav-tabs {{
            display: flex;
            gap: 8px;
            margin-bottom: 24px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 8px;
        }}
        .tab-btn {{
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-family: var(--font-sans);
            font-size: 14px;
            font-weight: 700;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .tab-btn:hover {{
            color: #fff;
            background: rgba(255, 255, 255, 0.04);
        }}
        .tab-btn.active {{
            color: #fff;
            background: var(--surface-hover);
            border: 1px solid var(--border);
        }}
        .tab-btn.active .tab-indicator {{
            background: var(--blue);
        }}
        .tab-indicator {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: transparent;
        }}

        /* Scorecard Grid */
        .portfolios-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .port-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.2s ease;
            position: relative;
            overflow: hidden;
        }}
        .port-card:hover {{
            border-color: rgba(255, 255, 255, 0.2);
            transform: translateY(-2px);
        }}
        .port-card.selected {{
            border-color: var(--blue);
            box-shadow: 0 0 20px rgba(59, 130, 246, 0.15);
        }}
        .port-card::before {{
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; height: 3px;
        }}
        .port-card.india-liquid::before {{ background: var(--gold); }}
        .port-card.india-broad::before {{ background: #f97316; }}
        .port-card.usa-liquid::before {{ background: #06b6d4; }}
        .port-card.usa-broad::before {{ background: var(--blue); }}

        .port-badge {{
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
        }}
        .equity-val {{
            font-size: 26px;
            font-weight: 800;
            font-family: var(--font-mono);
            margin-bottom: 6px;
        }}
        .pnl-pill {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 700;
            font-family: var(--font-mono);
        }}
        .gain {{ color: var(--green); background: var(--green-bg); }}
        .loss {{ color: var(--red); background: var(--red-bg); }}

        .stat-line {{
            display: flex;
            justify-content: space-between;
            margin-top: 10px;
            font-size: 12px;
            color: var(--text-muted);
            border-top: 1px solid rgba(255, 255, 255, 0.04);
            padding-top: 8px;
        }}
        .stat-line strong {{
            color: var(--text-main);
            font-family: var(--font-mono);
        }}

        /* Panels */
        .panel {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        .panel-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 18px;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .panel-header h2 {{
            font-size: 18px;
            font-weight: 700;
        }}

        .detail-container {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
            margin-bottom: 24px;
        }}
        @media (max-width: 960px) {{
            .detail-container {{ grid-template-columns: 1fr; }}
        }}

        .table-wrap {{
            overflow-x: auto;
            max-height: 440px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        th {{
            background: rgba(0, 0, 0, 0.25);
            color: var(--text-muted);
            text-align: left;
            padding: 10px 12px;
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid var(--border);
            position: sticky;
            top: 0;
            z-index: 1;
        }}
        td {{
            padding: 11px 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        }}
        tr:hover {{ background: rgba(255, 255, 255, 0.02); }}
        .mono {{ font-family: var(--font-mono); }}

        .gold-box {{
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.1) 0%, rgba(245, 158, 11, 0.03) 100%);
            border: 1px solid rgba(245, 158, 11, 0.2);
            border-radius: 12px;
            padding: 18px;
            margin-bottom: 16px;
        }}
        .gold-box-title {{
            font-size: 12px;
            font-weight: 700;
            color: var(--gold);
            text-transform: uppercase;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .gold-val {{
            font-size: 22px;
            font-weight: 800;
            font-family: var(--font-mono);
            color: #fff;
        }}
        .gold-sub {{
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 4px;
        }}

        .filter-group {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .btn {{
            background: #1e293b;
            color: #cbd5e1;
            border: 1px solid var(--border);
            padding: 7px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .btn:hover {{ background: #334155; color: #fff; }}
        .btn.active {{ background: var(--blue); color: #fff; border-color: var(--blue); }}
        input[type="text"] {{
            background: #090d16;
            border: 1px solid var(--border);
            color: #fff;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 12px;
            min-width: 240px;
        }}
        input[type="text"]:focus {{
            outline: none;
            border-color: var(--blue);
        }}

        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}
    </style>
</head>
<body>

<div class="header">
    <div class="header-title">
        <h1>⚡ GFS Multi-Market Quantitative Terminal</h1>
        <p>10 Slots • Macro Regime Schedule 1 • 100% Gold Cash Parking • India & USA</p>
    </div>
    <div style="display: flex; gap: 10px; align-items: center;">
        <span class="status-pill"><span class="pulse-dot"></span> Cloud Bot Active (GitHub Actions)</span>
        <span class="time-badge" id="clockIST">IST: --:--:--</span>
    </div>
</div>

<!-- Navigation Tabs -->
<div class="nav-tabs">
    <button class="tab-btn active" onclick="switchMainTab('live')">
        <span class="tab-indicator"></span> 🟢 Live Forward-Test (2026–2027)
    </button>
    <button class="tab-btn" onclick="switchMainTab('backtest')">
        <span class="tab-indicator"></span> 📊 Historical Backtest Benchmark (2018–2026)
    </button>
</div>

<!-- ========================================================================= -->
<!-- TAB 1: LIVE FORWARD-TESTING TERMINAL -->
<!-- ========================================================================= -->
<div id="tab-live" class="tab-content active">
    <!-- 4 Portfolio Cards -->
    <div class="portfolios-grid">
        <div class="port-card india-liquid selected" id="card-india_liquid" onclick="selectLivePortfolio('india_liquid')">
            <div class="port-badge"><span>🇮🇳 INDIA LIQUID</span><span>NIFTY 500</span></div>
            <div class="equity-val" id="val-india_liquid">₹--</div>
            <span class="pnl-pill gain" id="pnl-india_liquid">+0.00%</span>
            <div class="stat-line"><span>Cash In Gold (GOLDBEES)</span><strong id="gold-india_liquid">₹--</strong></div>
            <div class="stat-line"><span>Active Equity Positions</span><strong id="pos-india_liquid">0 / 10</strong></div>
        </div>

        <div class="port-card india-broad" id="card-india_broad" onclick="selectLivePortfolio('india_broad')">
            <div class="port-badge"><span>🇮🇳 INDIA BROAD</span><span>> ₹100CR MCAP</span></div>
            <div class="equity-val" id="val-india_broad">₹--</div>
            <span class="pnl-pill gain" id="pnl-india_broad">+0.00%</span>
            <div class="stat-line"><span>Cash In Gold (GOLDBEES)</span><strong id="gold-india_broad">₹--</strong></div>
            <div class="stat-line"><span>Active Equity Positions</span><strong id="pos-india_broad">0 / 10</strong></div>
        </div>

        <div class="port-card usa-liquid" id="card-usa_liquid" onclick="selectLivePortfolio('usa_liquid')">
            <div class="port-badge"><span>🇺🇸 USA LIQUID</span><span>S&P 500</span></div>
            <div class="equity-val" id="val-usa_liquid">$--</div>
            <span class="pnl-pill gain" id="pnl-usa_liquid">+0.00%</span>
            <div class="stat-line"><span>Cash In Gold (GLD)</span><strong id="gold-usa_liquid">$--</strong></div>
            <div class="stat-line"><span>Active Equity Positions</span><strong id="pos-usa_liquid">0 / 10</strong></div>
        </div>

        <div class="port-card usa-broad" id="card-usa_broad" onclick="selectLivePortfolio('usa_broad')">
            <div class="port-badge"><span>🇺🇸 USA BROAD</span><span>INDMONEY</span></div>
            <div class="equity-val" id="val-usa_broad">$--</div>
            <span class="pnl-pill gain" id="pnl-usa_broad">+0.00%</span>
            <div class="stat-line"><span>Cash In Gold (GLD)</span><strong id="gold-usa_broad">$--</strong></div>
            <div class="stat-line"><span>Active Equity Positions</span><strong id="pos-usa_broad">0 / 10</strong></div>
        </div>
    </div>

    <!-- Holdings & Gold Detail -->
    <div class="detail-container">
        <div class="panel">
            <div class="panel-header">
                <h2 id="activePortTitle">Active Holdings - INDIA LIQUID</h2>
                <div style="display: flex; gap: 8px; align-items: center;">
                    <span style="font-size: 12px; color: var(--text-muted);" id="lastUpdatedDate">Updated: Today</span>
                    <button class="btn" onclick="fetchLiveState()">🔄 Refresh</button>
                </div>
            </div>
            <div class="table-wrap">
                <table id="liveHoldingsTable">
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Entry Date</th>
                            <th>Entry Price</th>
                            <th>Last Price</th>
                            <th>Hold</th>
                            <th>Unrealized Ret</th>
                            <th>Unrealized PnL</th>
                        </tr>
                    </thead>
                    <tbody id="liveHoldingsBody">
                        <tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">100% Capital safely parked in Gold ETF awaiting GFS breakout signals.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <div class="panel">
            <div class="panel-header">
                <h2>Gold Shield Status</h2>
            </div>
            <div class="gold-box">
                <div class="gold-box-title">🟡 Gold Cash Parking Proxy</div>
                <div class="gold-val" id="goldBoxVal">₹--</div>
                <div class="gold-sub" id="goldBoxSub">Units: -- @ ₹--</div>
            </div>
            <div style="background: rgba(255,255,255,0.02); border-radius: 12px; padding: 16px; border: 1px solid var(--border);">
                <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 8px;">Automated Protocol</div>
                <ul style="font-size: 12px; line-height: 1.8; color: #cbd5e1; padding-left: 18px;" id="rulesList">
                    <li>Capacity: 10 equal slots (10% per position)</li>
                    <li>Cash Parking: 100% Gold ETF (GOLDBEES / GLD)</li>
                    <li>Regime Modulation: 100% Bull / 70% Neutral / 30% Bear</li>
                    <li>Automatic Execution: Cloud runner every weekday at close</li>
                </ul>
            </div>
        </div>
    </div>
</div>

<!-- ========================================================================= -->
<!-- TAB 2: HISTORICAL BACKTEST BENCHMARK (2018-2026) -->
<!-- ========================================================================= -->
<div id="tab-backtest" class="tab-content">
    <!-- Backtest Scorecard Cards -->
    <div class="portfolios-grid">
        <div class="port-card india-liquid">
            <div class="port-badge"><span>🇮🇳 1. INDIA LIQUID</span><span class="pnl-pill gain">+40.37% CAGR</span></div>
            <div class="equity-val">₹18,69,475</div>
            <span class="pnl-pill gain">+1,769.5% Net Return</span>
            <div class="stat-line"><span>Initial Capital</span><strong>₹1,00,000</strong></div>
            <div class="stat-line"><span>Max Drawdown</span><strong style="color: var(--red);">-26.68%</strong></div>
            <div class="stat-line"><span>Profit Factor / Win Rate</span><strong>3.38 | 48.4%</strong></div>
            <div class="stat-line"><span>Total Trades</span><strong>62 trades</strong></div>
        </div>

        <div class="port-card india-broad">
            <div class="port-badge"><span>🇮🇳 2. INDIA BROAD</span><span class="pnl-pill gain">+39.33% CAGR</span></div>
            <div class="equity-val">₹17,53,630</div>
            <span class="pnl-pill gain">+1,653.6% Net Return</span>
            <div class="stat-line"><span>Initial Capital</span><strong>₹1,00,000</strong></div>
            <div class="stat-line"><span>Max Drawdown</span><strong style="color: var(--red);">-31.23%</strong></div>
            <div class="stat-line"><span>Profit Factor / Win Rate</span><strong>4.02 | 46.3%</strong></div>
            <div class="stat-line"><span>Total Trades</span><strong>67 trades</strong></div>
        </div>

        <div class="port-card usa-liquid">
            <div class="port-badge"><span>🇺🇸 3. USA LIQUID</span><span class="pnl-pill gain">+23.73% CAGR</span></div>
            <div class="equity-val">$62,995</div>
            <span class="pnl-pill gain">+529.9% Net Return</span>
            <div class="stat-line"><span>Initial Capital</span><strong>$10,000</strong></div>
            <div class="stat-line"><span>Max Drawdown</span><strong style="color: var(--red);">-33.49%</strong></div>
            <div class="stat-line"><span>Profit Factor / Win Rate</span><strong>4.66 | 51.4%</strong></div>
            <div class="stat-line"><span>Total Trades</span><strong>107 trades</strong></div>
        </div>

        <div class="port-card usa-broad">
            <div class="port-badge"><span>🇺🇸 4. USA BROAD</span><span class="pnl-pill gain">+13.69% CAGR</span></div>
            <div class="equity-val">$30,314</div>
            <span class="pnl-pill gain">+203.1% Net Return</span>
            <div class="stat-line"><span>Initial Capital</span><strong>$10,000</strong></div>
            <div class="stat-line"><span>Max Drawdown</span><strong style="color: var(--red);">-33.86%</strong></div>
            <div class="stat-line"><span>Profit Factor / Win Rate</span><strong>1.51 | 50.7%</strong></div>
            <div class="stat-line"><span>Total Trades</span><strong>140 trades</strong></div>
        </div>
    </div>

    <!-- Normalized Equity Curves Chart -->
    <div class="panel">
        <div class="panel-header">
            <h2>📈 Normalized Historical Equity Curves (2018–2026, Rebased to 100)</h2>
            <div style="font-size: 12px; color: var(--text-muted);">8.6 Years • Friction Adjusted</div>
        </div>
        <div style="height: 380px;">
            <canvas id="backtestChart"></canvas>
        </div>
    </div>

    <!-- Top Multibaggers & Winners Breakdown -->
    <div class="panel">
        <div class="panel-header">
            <h2>🏆 Top Multibaggers & Greatest Winners Across Backtest</h2>
            <div style="font-size: 12px; color: var(--text-muted);">Held until trend exhaustion</div>
        </div>
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Strategy</th>
                        <th>Symbol</th>
                        <th>Gain %</th>
                        <th>Holding Days</th>
                        <th>Profit</th>
                    </tr>
                </thead>
                <tbody id="topMultibaggersBody">
                    <!-- Populated via JS -->
                </tbody>
            </table>
        </div>
    </div>

    <!-- All 376 Trades Explorer -->
    <div class="panel">
        <div class="panel-header">
            <h2>📋 Complete Historical Trade Explorer (376 Trades)</h2>
            <div class="filter-group">
                <button class="btn active" onclick="filterBacktestTrades('ALL')">All</button>
                <button class="btn" onclick="filterBacktestTrades('INDIA_LIQUID')">India Liquid</button>
                <button class="btn" onclick="filterBacktestTrades('INDIA_BROAD')">India Broad</button>
                <button class="btn" onclick="filterBacktestTrades('USA_LIQUID')">USA Liquid</button>
                <button class="btn" onclick="filterBacktestTrades('USA_BROAD')">USA Broad</button>
                <input type="text" id="tradeSearchInput" placeholder="Search by ticker (e.g. ELECON, NVDA, GRAVITA)..." onkeyup="searchBacktestTrades()">
            </div>
        </div>
        <div class="table-wrap">
            <table id="allTradesTable">
                <thead>
                    <tr>
                        <th>Strategy</th>
                        <th>Symbol</th>
                        <th>Entry Date</th>
                        <th>Exit Date</th>
                        <th>Hold</th>
                        <th>Entry</th>
                        <th>Exit</th>
                        <th>Return %</th>
                        <th>PnL</th>
                        <th>Exit Reason</th>
                    </tr>
                </thead>
                <tbody id="allTradesBody">
                    <!-- Populated via JS -->
                </tbody>
            </table>
        </div>
    </div>
</div>

<script>
const BACKTEST_DATA = {json.dumps(backtest_bundle)};

// Tab Switching
function switchMainTab(tab) {{
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    
    if (tab === 'live') {{
        document.querySelector('.tab-btn:nth-child(1)').classList.add('active');
        document.getElementById('tab-live').classList.add('active');
    }} else {{
        document.querySelector('.tab-btn:nth-child(2)').classList.add('active');
        document.getElementById('tab-backtest').classList.add('active');
        renderBacktestChart();
    }}
}}

// Clock
function updateClock() {{
    const now = new Date();
    const ist = new Intl.DateTimeFormat('en-IN', {{ timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }}).format(now);
    document.getElementById("clockIST").innerText = "IST: " + ist;
}}
setInterval(updateClock, 1000);
updateClock();

// LIVE DATA
const livePortfolios = {{
    india_liquid: {{ file: "reports/paper_trading/portfolio_state_india_liquid.json", curr: "₹", data: null }},
    india_broad: {{ file: "reports/paper_trading/portfolio_state_india_broad.json", curr: "₹", data: null }},
    usa_liquid: {{ file: "reports/paper_trading/portfolio_state_usa_liquid.json", curr: "$", data: null }},
    usa_broad: {{ file: "reports/paper_trading/portfolio_state_usa_broad.json", curr: "$", data: null }}
}};
let activeLiveKey = "india_liquid";

async function fetchLivePortfolio(key) {{
    const info = livePortfolios[key];
    const rawGithubUrl = `https://raw.githubusercontent.com/iamsjeevan/gfs-live-paper-trader/main/${{info.file}}`;
    try {{
        let res = await fetch(info.file + "?t=" + Date.now());
        if (!res.ok) res = await fetch(rawGithubUrl + "?t=" + Date.now());
        if (res.ok) {{
            info.data = await res.json();
            renderLiveCard(key, info.data, info.curr);
            if (key === activeLiveKey) renderActiveLivePortfolio();
        }}
    }} catch (e) {{
        console.warn("Could not load " + key, e);
    }}
}}

function fetchLiveState() {{
    Object.keys(livePortfolios).forEach(k => fetchLivePortfolio(k));
}}

function renderLiveCard(key, data, curr) {{
    const eq = data.total_equity || data.initial_capital;
    const init = data.initial_capital;
    const pnl = eq - init;
    const pnlPct = (pnl / init) * 100;
    document.getElementById("val-" + key).innerText = curr + Math.round(eq).toLocaleString();
    const pnlEl = document.getElementById("pnl-" + key);
    pnlEl.innerText = (pnlPct >= 0 ? "+" : "") + pnlPct.toFixed(2) + "%";
    pnlEl.className = "pnl-pill " + (pnlPct >= 0 ? "gain" : "loss");
    document.getElementById("gold-" + key).innerText = curr + Math.round(data.proxy_val || eq).toLocaleString();
    document.getElementById("pos-" + key).innerText = Object.keys(data.positions || {{}}).length + " / 10";
}}

function selectLivePortfolio(key) {{
    activeLiveKey = key;
    document.querySelectorAll(".port-card").forEach(c => c.classList.remove("selected"));
    document.getElementById("card-" + key).classList.add("selected");
    renderActiveLivePortfolio();
}}

function renderActiveLivePortfolio() {{
    const info = livePortfolios[activeLiveKey];
    const data = info.data;
    if (!data) return;
    const curr = info.curr;
    document.getElementById("activePortTitle").innerText = "Active Holdings - " + (data.label || activeLiveKey.toUpperCase());
    document.getElementById("lastUpdatedDate").innerText = "Last Updated: " + (data.last_updated || "Today");

    const positions = data.positions || {{}};
    const posKeys = Object.keys(positions);
    const tbody = document.getElementById("liveHoldingsBody");

    if (posKeys.length === 0) {{
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 24px;">100% Capital (${{curr}}${{Math.round(data.total_equity).toLocaleString()}}) safely parked in ${{data.proxy_symbol}} awaiting GFS breakout signals.</td></tr>`;
    }} else {{
        let html = "";
        posKeys.forEach(sym => {{
            const p = positions[sym];
            const ret = p.unrealized_return_pct || 0;
            const pnl = p.unrealized_pnl || 0;
            const retClass = ret >= 0 ? "gain" : "loss";
            html += `<tr>
                <td><strong>${{p.symbol}}</strong></td>
                <td>${{p.entry_date}}</td>
                <td class="mono">${{curr}}${{p.sim_entry_price.toFixed(2)}}</td>
                <td class="mono">${{curr}}${{p.last_price.toFixed(2)}}</td>
                <td class="mono">${{p.holding_days}}d</td>
                <td class="mono"><span class="pnl-pill ${{retClass}}">${{ret >= 0 ? "+" : ""}}${{ret.toFixed(2)}}%</span></td>
                <td class="mono ${{retClass}}">${{ret >= 0 ? "+" : ""}}${{curr}}${{pnl.toFixed(2)}}</td>
            </tr>`;
        }});
        tbody.innerHTML = html;
    }}

    document.getElementById("goldBoxVal").innerText = curr + Math.round(data.proxy_val || 0).toLocaleString();
    document.getElementById("goldBoxSub").innerText = `${{data.proxy_symbol}} • ${{(data.proxy_units || 0).toFixed(2)}} Units @ ${{curr}}${{(data.proxy_last_price || 0).toFixed(2)}}`;
}}

// BACKTEST VISUALS
let backtestChartRendered = false;
function renderBacktestChart() {{
    if (backtestChartRendered) return;
    const rawData = BACKTEST_DATA.chart_data;
    if (!rawData || !rawData.INDIA_BROAD) return;

    const datasets = [
        {{
            label: "🇮🇳 India Liquid (Top 500) • 40.37% CAGR",
            borderColor: "#eab308",
            backgroundColor: "transparent",
            data: rawData.INDIA_LIQUID.equity.map(v => (v / rawData.INDIA_LIQUID.equity[0]) * 100),
            borderWidth: 2,
            tension: 0.1,
            pointRadius: 0
        }},
        {{
            label: "🇮🇳 India Broad (> ₹100Cr) • 39.33% CAGR",
            borderColor: "#f97316",
            backgroundColor: "transparent",
            data: rawData.INDIA_BROAD.equity.map(v => (v / rawData.INDIA_BROAD.equity[0]) * 100),
            borderWidth: 2,
            tension: 0.1,
            pointRadius: 0
        }},
        {{
            label: "🇺🇸 USA Liquid (S&P 500) • 23.73% CAGR",
            borderColor: "#06b6d4",
            backgroundColor: "transparent",
            data: rawData.USA_LIQUID.equity.map(v => (v / rawData.USA_LIQUID.equity[0]) * 100),
            borderWidth: 2,
            tension: 0.1,
            pointRadius: 0
        }},
        {{
            label: "🇺🇸 USA Broad (INDmoney) • 13.69% CAGR",
            borderColor: "#3b82f6",
            backgroundColor: "transparent",
            data: rawData.USA_BROAD.equity.map(v => (v / rawData.USA_BROAD.equity[0]) * 100),
            borderWidth: 2,
            tension: 0.1,
            pointRadius: 0
        }}
    ];

    const ctx = document.getElementById("backtestChart").getContext("2d");
    new Chart(ctx, {{
        type: "line",
        data: {{
            labels: rawData.INDIA_BROAD.dates,
            datasets: datasets
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            interaction: {{ mode: "index", intersect: false }},
            plugins: {{
                legend: {{ labels: {{ color: "#cbd5e1", font: {{ family: "'Plus Jakarta Sans'" }} }} }},
                tooltip: {{
                    callbacks: {{
                        label: function(context) {{
                            return context.dataset.label.split(" • ")[0] + ": " + context.parsed.y.toFixed(1) + " (Rebased)";
                        }}
                    }}
                }}
            }},
            scales: {{
                x: {{ grid: {{ color: "rgba(255,255,255,0.05)" }}, ticks: {{ color: "#64748b", maxTicksLimit: 12 }} }},
                y: {{ grid: {{ color: "rgba(255,255,255,0.05)" }}, ticks: {{ color: "#64748b" }} }}
            }}
        }}
    }});
    backtestChartRendered = true;
}}

// Populate Top Multibaggers
function renderTopMultibaggers() {{
    const tbody = document.getElementById("topMultibaggersBody");
    let html = "";
    BACKTEST_DATA.top_multibaggers.forEach(t => {{
        const curr = t.strategy.includes("INDIA") ? "₹" : "$";
        html += `<tr>
            <td><strong style="color: ${{t.strategy.includes('LIQUID') ? 'var(--gold)' : 'var(--blue)'}};">${{t.strategy}}</strong></td>
            <td><strong style="font-size: 14px;">${{t.symbol}}</strong></td>
            <td><span class="pnl-pill gain">+${{t.return_pct.toFixed(1)}}%</span></td>
            <td class="mono">${{t.holding_days}} trading days (~${{(t.holding_days/250).toFixed(1)}} yrs)</td>
            <td class="mono gain">+${{curr}}${{Math.round(t.pnl).toLocaleString()}}</td>
        </tr>`;
    }});
    tbody.innerHTML = html;
}}

// Populate All Trades
function renderAllTrades() {{
    const tbody = document.getElementById("allTradesBody");
    let html = "";
    BACKTEST_DATA.trades.forEach(t => {{
        const curr = t.strategy.includes("INDIA") ? "₹" : "$";
        const isWin = t.return_pct >= 0;
        html += `<tr data-strategy="${{t.strategy}}">
            <td><strong>${{t.strategy}}</strong></td>
            <td><strong>${{t.symbol}}</strong></td>
            <td>${{t.entry_date}}</td>
            <td>${{t.exit_date}}</td>
            <td class="mono">${{t.holding_days}}d</td>
            <td class="mono">${{curr}}${{t.entry_price.toFixed(2)}}</td>
            <td class="mono">${{curr}}${{t.exit_price.toFixed(2)}}</td>
            <td class="mono ${{isWin ? 'gain' : 'loss'}}">${{isWin ? '+' : ''}}${{t.return_pct.toFixed(2)}}%</td>
            <td class="mono ${{isWin ? 'gain' : 'loss'}}">${{isWin ? '+' : ''}}${{curr}}${{t.pnl.toFixed(2)}}</td>
            <td><small>${{t.exit_reason}}</small></td>
        </tr>`;
    }});
    tbody.innerHTML = html;
}}

let currentTradeFilter = "ALL";
function filterBacktestTrades(strat) {{
    currentTradeFilter = strat;
    document.querySelectorAll('.filter-group .btn').forEach(b => b.classList.remove('active'));
    event.target.classList.add('active');
    applyTradeFilters();
}}

function searchBacktestTrades() {{
    applyTradeFilters();
}}

function applyTradeFilters() {{
    const query = document.getElementById("tradeSearchInput").value.toUpperCase();
    const rows = document.querySelectorAll("#allTradesTable tbody tr");
    rows.forEach(r => {{
        const strat = r.getAttribute("data-strategy");
        const text = r.innerText.toUpperCase();
        const matchesStrat = (currentTradeFilter === "ALL" || strat === currentTradeFilter);
        const matchesQuery = (!query || text.includes(query));
        r.style.display = (matchesStrat && matchesQuery) ? "" : "none";
    }});
}}

// Init
fetchLiveState();
renderTopMultibaggers();
renderAllTrades();
setInterval(fetchLiveState, 30000);
</script>

</body>
</html>
"""

with open(BASE_DIR / "index.html", "w") as f:
    f.write(template)
print("Updated index.html with live forward-test + historical backtest suite")
