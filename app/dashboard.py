"""Embedded Web Dashboard Server for Live Paper Trading.

Lightweight, dependency-free HTTP server exposing REST APIs and a modern responsive frontend.
Accessible via web browser at http://localhost:8080 (or configured host/port).
"""

import json
import sqlite3
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from typing import Optional

from app.config import CONFIG, DEFAULT_DB_PATH
from app.db import get_db_connection
from app.portfolio import PortfolioManager

logger = logging.getLogger("paper_trading.dashboard")

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Indian Equity Paper Trading Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg: #0d1117;
            --card-bg: #161b22;
            --border: #30363d;
            --text: #c9d1d9;
            --text-heading: #58a6ff;
            --green: #2ea043;
            --red: #f85149;
            --accent: #1f6feb;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 20px;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 15px;
            margin-bottom: 20px;
        }
        .header h1 {
            margin: 0;
            font-size: 24px;
            color: var(--text-heading);
        }
        .badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }
        .badge-paper { background-color: #388bfd33; color: #58a6ff; border: 1px solid #1f6feb; }
        .badge-live { background-color: #2ea04333; color: #3fb950; border: 1px solid #2ea043; }
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }
        .kpi-card {
            background-color: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
        }
        .kpi-title { font-size: 12px; text-transform: uppercase; color: #8b949e; margin-bottom: 6px; }
        .kpi-val { font-size: 24px; font-weight: bold; }
        .val-green { color: var(--green); }
        .val-red { color: var(--red); }
        .chart-container {
            background-color: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 25px;
            height: 340px;
        }
        .section-title { font-size: 18px; margin-bottom: 12px; color: #f0f6fc; }
        table {
            width: 100%;
            border-collapse: collapse;
            background-color: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 25px;
            font-size: 14px;
        }
        th, td {
            padding: 12px 14px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }
        th { background-color: #21262d; color: #8b949e; font-weight: 600; }
        tr:hover { background-color: #1f242c; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>Indian Equity Momentum Paper Trading</h1>
            <div style="font-size: 13px; color: #8b949e; margin-top: 4px;">
                Model C (Relative Volume Weighted) | 15 Slots | 10% Max Allocation
            </div>
        </div>
        <div>
            <span class="badge badge-paper">Mode: Virtual Shadow Only</span>
            <span id="system-status-badge" class="badge badge-live">Status: Running</span>
        </div>
    </div>

    <!-- KPIs -->
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-title">Virtual Equity</div>
            <div class="kpi-val" id="kpi-equity">₹--</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Cumulative Return</div>
            <div class="kpi-val" id="kpi-return">--%</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Max Drawdown</div>
            <div class="kpi-val val-red" id="kpi-maxdd">--%</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Win Rate</div>
            <div class="kpi-val" id="kpi-winrate">--%</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Available Cash</div>
            <div class="kpi-val" id="kpi-cash">₹--</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-title">Open Positions</div>
            <div class="kpi-val" id="kpi-positions">-- / 15</div>
        </div>
    </div>

    <!-- Equity Curve Chart -->
    <div class="chart-container">
        <canvas id="equityChart"></canvas>
    </div>

    <!-- Open Positions Table -->
    <div class="section-title">Active Open Positions</div>
    <table>
        <thead>
            <tr>
                <th>Symbol</th>
                <th>Entry Date</th>
                <th>Simulated Entry Price</th>
                <th>Current Price</th>
                <th>Allocation</th>
                <th>Unrealized P&L</th>
                <th>Return (%)</th>
                <th>Initial Stop</th>
                <th>+5% Trailing?</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody id="positions-table-body">
            <tr><td colspan="10" style="text-align:center; color:#8b949e;">Loading active positions...</td></tr>
        </tbody>
    </table>

    <!-- Today's Signals Table -->
    <div class="section-title">Latest Evaluated Signals</div>
    <table>
        <thead>
            <tr>
                <th>Symbol</th>
                <th>Signal Date</th>
                <th>Relative Volume</th>
                <th>Rank</th>
                <th>Proposed Allocation</th>
                <th>Status</th>
                <th>Reason</th>
            </tr>
        </thead>
        <tbody id="signals-table-body">
            <tr><td colspan="7" style="text-align:center; color:#8b949e;">Loading signals...</td></tr>
        </tbody>
    </table>

    <!-- Recent Closed Trades -->
    <div class="section-title">Recent Completed Trades</div>
    <table>
        <thead>
            <tr>
                <th>Symbol</th>
                <th>Entry Date</th>
                <th>Exit Date</th>
                <th>Entry Price</th>
                <th>Exit Price</th>
                <th>Return (%)</th>
                <th>Realized P&L</th>
                <th>Holding Days</th>
                <th>Reason</th>
            </tr>
        </thead>
        <tbody id="trades-table-body">
            <tr><td colspan="9" style="text-align:center; color:#8b949e;">Loading trades...</td></tr>
        </tbody>
    </table>

    <script>
        let equityChart = null;

        async function fetchDashboardData() {
            try {
                // Fetch metrics
                const resMetrics = await fetch('/api/metrics');
                const m = await resMetrics.json();

                document.getElementById('kpi-equity').innerText = '₹' + Number(m.current_equity || 0).toLocaleString('en-IN', {maximumFractionDigits: 0});
                const retElem = document.getElementById('kpi-return');
                const retVal = m.total_return_pct || 0;
                retElem.innerText = (retVal >= 0 ? '+' : '') + retVal.toFixed(2) + '%';
                retElem.className = 'kpi-val ' + (retVal >= 0 ? 'val-green' : 'val-red');

                document.getElementById('kpi-maxdd').innerText = (m.max_drawdown_pct || 0).toFixed(2) + '%';
                document.getElementById('kpi-winrate').innerText = (m.win_rate_pct || 0).toFixed(1) + '% (PF: ' + (m.profit_factor || 0).toFixed(2) + ')';
                document.getElementById('kpi-cash').innerText = '₹' + Number(m.current_equity * (m.average_cash_pct/100 || 0.25)).toLocaleString('en-IN', {maximumFractionDigits: 0});
                document.getElementById('kpi-positions').innerText = (m.open_positions || 0) + ' / 15';

                // Fetch positions
                const resPos = await fetch('/api/positions');
                const positions = await resPos.json();
                const posBody = document.getElementById('positions-table-body');
                if (positions.length === 0) {
                    posBody.innerHTML = '<tr><td colspan="10" style="text-align:center; color:#8b949e;">No active open positions. Cash is unallocated.</td></tr>';
                } else {
                    posBody.innerHTML = positions.map(p => {
                        const r = p.unrealized_return_pct || 0;
                        const rClass = r >= 0 ? 'val-green' : 'val-red';
                        return `<tr>
                            <td><strong>${p.symbol}</strong></td>
                            <td>${p.entry_date}</td>
                            <td>₹${Number(p.simulated_entry_price).toFixed(2)}</td>
                            <td>₹${Number(p.current_price || p.entry_price).toFixed(2)}</td>
                            <td>₹${Number(p.allocated_capital).toLocaleString('en-IN', {maximumFractionDigits: 0})}</td>
                            <td class="${rClass}">₹${Number(p.unrealized_pnl || 0).toLocaleString('en-IN', {maximumFractionDigits: 0})}</td>
                            <td class="${rClass}">${r >= 0 ? '+' : ''}${r.toFixed(2)}%</td>
                            <td>₹${Number(p.initial_stop).toFixed(2)}</td>
                            <td>${p.plus_5_reached ? '✅ YES' : '⏳ NO'}</td>
                            <td>${p.status}</td>
                        </tr>`;
                    }).join('');
                }

                // Fetch signals
                const resSig = await fetch('/api/signals');
                const signals = await resSig.json();
                const sigBody = document.getElementById('signals-table-body');
                if (signals.length === 0) {
                    sigBody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#8b949e;">No new signals evaluated today.</td></tr>';
                } else {
                    sigBody.innerHTML = signals.slice(0, 15).map(s => `<tr>
                        <td><strong>${s.symbol}</strong></td>
                        <td>${s.signal_date}</td>
                        <td>${Number(s.relative_volume || 1.0).toFixed(2)}x</td>
                        <td>${s.ranking || '-'}</td>
                        <td>₹${Number(s.allocation || 0).toLocaleString('en-IN', {maximumFractionDigits: 0})}</td>
                        <td><span class="badge ${s.status === 'ACCEPTED' ? 'badge-live' : 'badge-paper'}">${s.status}</span></td>
                        <td>${s.reason || ''}</td>
                    </tr>`).join('');
                }

                // Fetch trades
                const resTrades = await fetch('/api/trades');
                const trades = await resTrades.json();
                const trBody = document.getElementById('trades-table-body');
                if (trades.length === 0) {
                    trBody.innerHTML = '<tr><td colspan="9" style="text-align:center; color:#8b949e;">No trades closed yet.</td></tr>';
                } else {
                    trBody.innerHTML = trades.slice(-15).reverse().map(t => {
                        const r = t.return_pct || 0;
                        const rClass = r >= 0 ? 'val-green' : 'val-red';
                        return `<tr>
                            <td><strong>${t.symbol}</strong></td>
                            <td>${t.entry_date}</td>
                            <td>${t.exit_date}</td>
                            <td>₹${Number(t.entry_price).toFixed(2)}</td>
                            <td>₹${Number(t.exit_price).toFixed(2)}</td>
                            <td class="${rClass}">${r >= 0 ? '+' : ''}${r.toFixed(2)}%</td>
                            <td class="${rClass}">₹${Number(t.pnl_rs).toLocaleString('en-IN', {maximumFractionDigits: 0})}</td>
                            <td>${t.holding_days} d</td>
                            <td>${t.exit_reason}</td>
                        </tr>`;
                    }).join('');
                }

                // Fetch portfolio snapshots for chart
                const resSnaps = await fetch('/api/portfolio');
                const snapshots = await resSnaps.json();
                if (snapshots.length > 0) {
                    renderChart(snapshots);
                }

            } catch (err) {
                console.error("Dashboard fetch error:", err);
            }
        }

        function renderChart(snaps) {
            const labels = snaps.map(s => s.date);
            const equityData = snaps.map(s => s.total_equity);

            const ctx = document.getElementById('equityChart').getContext('2d');
            if (equityChart) {
                equityChart.destroy();
            }

            equityChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Virtual Portfolio Equity (₹)',
                        data: equityData,
                        borderColor: '#58a6ff',
                        backgroundColor: '#1f6feb22',
                        borderWidth: 2,
                        pointRadius: 1,
                        fill: true,
                        tension: 0.1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { labels: { color: '#c9d1d9' } },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    return '₹' + Number(context.parsed.y).toLocaleString('en-IN');
                                }
                            }
                        }
                    },
                    scales: {
                        x: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } },
                        y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } }
                    }
                }
            });
        }

        fetchDashboardData();
        setInterval(fetchDashboardData, 30000); // refresh every 30s
    </script>
</body>
</html>
"""

class DashboardRequestHandler(BaseHTTPRequestHandler):
    db_path = DEFAULT_DB_PATH

    def log_message(self, format, *args):
        # Suppress noisy HTTP logs
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
            return

        if path == "/api/status":
            self._handle_status()
        elif path == "/api/metrics":
            self._handle_metrics()
        elif path == "/api/positions":
            self._handle_positions()
        elif path == "/api/signals":
            self._handle_signals()
        elif path == "/api/trades":
            self._handle_trades()
        elif path == "/api/portfolio":
            self._handle_portfolio()
        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _handle_status(self):
        conn = get_db_connection(self.db_path)
        hb = conn.execute("SELECT * FROM system_heartbeat ORDER BY heartbeat_id DESC LIMIT 1;").fetchone()
        conn.close()
        res = dict(hb) if hb else {"status": "INITIALIZING", "open_positions": 0, "total_equity": CONFIG.STARTING_CAPITAL}
        self._send_json(res)

    def _handle_metrics(self):
        pm = PortfolioManager(self.db_path)
        metrics = pm.compute_comprehensive_metrics(CONFIG.STARTING_CAPITAL)
        self._send_json(metrics)

    def _handle_positions(self):
        conn = get_db_connection(self.db_path)
        rows = conn.execute(
            "SELECT * FROM positions WHERE capital_tier = ? AND status != 'CLOSED' ORDER BY entry_date DESC;",
            (CONFIG.STARTING_CAPITAL,)
        ).fetchall()
        conn.close()
        self._send_json([dict(r) for r in rows])

    def _handle_signals(self):
        conn = get_db_connection(self.db_path)
        rows = conn.execute("SELECT * FROM signals ORDER BY signal_date DESC, ranking ASC LIMIT 50;").fetchall()
        conn.close()
        self._send_json([dict(r) for r in rows])

    def _handle_trades(self):
        conn = get_db_connection(self.db_path)
        rows = conn.execute(
            "SELECT * FROM closed_trades WHERE capital_tier = ? ORDER BY exit_date DESC LIMIT 100;",
            (CONFIG.STARTING_CAPITAL,)
        ).fetchall()
        conn.close()
        self._send_json([dict(r) for r in rows])

    def _handle_portfolio(self):
        conn = get_db_connection(self.db_path)
        rows = conn.execute(
            "SELECT date, cash, invested_val, total_equity, cumulative_return_pct, drawdown_pct FROM portfolio_snapshots WHERE capital_tier = ? ORDER BY date ASC;",
            (CONFIG.STARTING_CAPITAL,)
        ).fetchall()
        conn.close()
        self._send_json([dict(r) for r in rows])

class DashboardServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080, db_path: Optional[str] = None):
        self.host = host
        self.port = port
        self.db_path = db_path or DEFAULT_DB_PATH
        DashboardRequestHandler.db_path = self.db_path
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start_background(self):
        """Start HTTP server in background thread."""
        self.server = HTTPServer((self.host, self.port), DashboardRequestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"Dashboard server running at http://{self.host}:{self.port}")

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            logger.info("Dashboard server stopped.")
