"""
live_paper_trader.notifier
==========================
Handles email notifications (Monthly Performance Reports and Trade Execution Alerts)
using standard SMTP (e.g. Gmail App Password, Resend, SendGrid) with optional
Telegram fallback.
"""

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests
from typing import Dict, Any, List

from live_paper_trader.config import (
    EMAIL_HOST,
    EMAIL_PORT,
    EMAIL_USER,
    EMAIL_PASSWORD,
    EMAIL_TO,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    LOGS_DIR
)

logger = logging.getLogger("live_paper_trader.notifier")

class PaperTradingNotifier:
    def __init__(self):
        self.email_enabled = bool(EMAIL_USER and EMAIL_PASSWORD and EMAIL_TO)
        self.telegram_enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
        
        if not self.email_enabled:
            logger.info("Email notifications are currently inactive. Set EMAIL_USER, EMAIL_PASSWORD, and EMAIL_TO in env or GitHub Secrets.")

    def _send_email(self, subject: str, html_body: str, text_body: str) -> bool:
        if not self.email_enabled:
            print(f"\n[EMAIL SIMULATION] Subject: {subject}\n{text_body}\n")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = EMAIL_USER
            msg["To"] = EMAIL_TO
            
            part_text = MIMEText(text_body, "plain")
            part_html = MIMEText(html_body, "html")
            msg.attach(part_text)
            msg.attach(part_html)

            with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT, timeout=20.0) as server:
                server.starttls()
                server.login(EMAIL_USER, EMAIL_PASSWORD)
                server.sendmail(EMAIL_USER, [EMAIL_TO], msg.as_string())

            logger.info(f"Email successfully delivered to {EMAIL_TO}: '{subject}'")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            print(f"[EMAIL ERROR] Failed to send email to {EMAIL_TO}: {e}")
            return False

    def _send_telegram(self, text: str) -> bool:
        if not self.telegram_enabled:
            return False
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
            res = requests.post(url, json=payload, timeout=10.0)
            return res.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_trade_alert(
        self,
        market: str,
        action: str, # "BUY", "SELL", "EVICT"
        symbol: str,
        price: float,
        shares: float,
        value: float,
        ret_pct: float = 0.0,
        pnl: float = 0.0,
        reason: str = "",
        holding_days: int = 0
    ):
        """Sends immediate email alert upon paper trade execution."""
        curr = "₹" if market.upper() == "INDIA" else "$"
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        if action == "BUY":
            title = f"🟢 [{market.upper()}] BUY: {symbol}"
            summary_txt = f"Executed BUY on {symbol} at {curr}{price:,.2f} ({shares:,.2f} shares, Total: {curr}{value:,.2f})."
        elif action in ("SELL", "EVICT"):
            pnl_sign = "+" if pnl >= 0 else "-"
            icon = "🔴" if pnl < 0 else "🎯"
            title = f"{icon} [{market.upper()}] {action}: {symbol} ({pnl_sign}{ret_pct:.2f}%)"
            summary_txt = (
                f"Executed {action} on {symbol} at {curr}{price:,.2f} after {holding_days} days.\n"
                f"Return: {pnl_sign}{ret_pct:.2f}% | PnL: {curr}{abs(pnl):,.2f}\n"
                f"Reason: {reason}"
            )
        else:
            title = f"ℹ️ [{market.upper()}] ORDER: {symbol}"
            summary_txt = f"{action} {symbol} at {curr}{price:,.2f}"

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
            <div style="background-color: {'#2e7d32' if action == 'BUY' else '#c62828' if ret_pct < 0 else '#1565c0'}; color: white; padding: 12px 20px; border-radius: 6px 6px 0 0;">
                <h2 style="margin: 0;">{title}</h2>
                <small>{date_str} (Paper Trading Forward Test)</small>
            </div>
            <div style="padding: 20px; background-color: #fafafa;">
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Market:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{market.upper()}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Symbol:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>{symbol}</strong></td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Action:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{action}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Fill Price:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{curr}{price:,.2f}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Shares:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{shares:,.2f}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Total Value:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{curr}{value:,.2f}</td></tr>
                    {"<tr><td style='padding: 8px; border-bottom: 1px solid #eee;'><strong>Return:</strong></td><td style='padding: 8px; border-bottom: 1px solid #eee; color: " + ('#2e7d32' if ret_pct >= 0 else '#c62828') + "; font-weight: bold;'>" + f"{ret_pct:+.2f}% ({curr}{pnl:+,.2f})" + "</td></tr>" if action != "BUY" else ""}
                    {"<tr><td style='padding: 8px; border-bottom: 1px solid #eee;'><strong>Holding Days:</strong></td><td style='padding: 8px; border-bottom: 1px solid #eee;'>" + str(holding_days) + " trading days</td></tr>" if action != "BUY" else ""}
                    {"<tr><td style='padding: 8px; border-bottom: 1px solid #eee;'><strong>Exit Trigger:</strong></td><td style='padding: 8px; border-bottom: 1px solid #eee;'>" + reason + "</td></tr>" if reason else ""}
                </table>
            </div>
            <p style="font-size: 12px; color: #888; text-align: center; margin-top: 20px;">
                GFS Automated 1-Year Forward Testing Pipeline • Real orders are architecturally disabled.
            </p>
        </body>
        </html>
        """

        self._send_email(subject=title, html_body=html_body, text_body=summary_txt)
        self._send_telegram(f"*{title}*\n\n{summary_txt}")

    def send_monthly_report(self, market: str, state: Dict[str, Any]):
        """Generates and sends the complete Monthly Performance Report email."""
        curr = "₹" if market.upper() == "INDIA" else "$"
        date_str = datetime.now().strftime("%B %Y")
        init_cap = state.get("initial_capital", 100000.0)
        total_equity = state.get("total_equity", init_cap)
        tot_ret_pct = ((total_equity - init_cap) / init_cap) * 100.0
        tot_pnl = total_equity - init_cap
        
        positions = state.get("positions", {})
        proxy_val = state.get("proxy_val", 0.0)
        proxy_sym = state.get("proxy_symbol", "PROXY")
        proxy_units = state.get("proxy_units", 0.0)
        closed_trades = state.get("closed_trades", [])

        # Filter trades closed this month
        current_month = datetime.now().strftime("%Y-%m")
        this_month_trades = [t for t in closed_trades if str(t.get("exit_date", "")).startswith(current_month)]

        subject = f"📊 [{market.upper()}] Monthly GFS Report - {date_str} (Equity: {curr}{total_equity:,.0f} | {tot_ret_pct:+.2f}%)"

        # Build Holdings Table HTML
        holdings_rows = ""
        for sym, pos in positions.items():
            u_ret = pos.get("unrealized_return_pct", 0.0)
            u_pnl = pos.get("unrealized_pnl", 0.0)
            holdings_rows += f"""
            <tr>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee;"><strong>{sym}</strong></td>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee;">{pos.get('entry_date')}</td>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee;">{curr}{pos.get('entry_price', 0):,.2f}</td>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee;">{curr}{pos.get('last_price', 0):,.2f}</td>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee;">{pos.get('holding_days', 0)}d</td>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee; color: {'#2e7d32' if u_ret >= 0 else '#c62828'}; font-weight: bold;">{u_ret:+.2f}% ({curr}{u_pnl:+,.0f})</td>
            </tr>
            """

        if not holdings_rows:
            holdings_rows = "<tr><td colspan='6' style='padding: 10px; text-align: center; color: #777;'>No open equity positions (100% parked in cash/proxy ETF).</td></tr>"

        # Build Closed Trades Table HTML
        closed_rows = ""
        for t in this_month_trades:
            t_ret = t.get("return_pct", 0.0)
            t_pnl = t.get("pnl", 0.0)
            closed_rows += f"""
            <tr>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee;"><strong>{t.get('symbol')}</strong></td>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee;">{t.get('entry_date')} $\\rightarrow$ {t.get('exit_date')}</td>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee;">{t.get('holding_days')}d</td>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee; color: {'#2e7d32' if t_ret >= 0 else '#c62828'}; font-weight: bold;">{t_ret:+.2f}% ({curr}{t_pnl:+,.0f})</td>
                <td style="padding: 6px 10px; border-bottom: 1px solid #eee; font-size: 11px;">{t.get('exit_reason')}</td>
            </tr>
            """

        if not closed_rows:
            closed_rows = "<tr><td colspan='5' style='padding: 10px; text-align: center; color: #777;'>No closed trades this month.</td></tr>"

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 700px; margin: 0 auto; padding: 20px;">
            <div style="background-color: #1a237e; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
                <h1 style="margin: 0; font-size: 24px;">📈 {market.upper()} Market - Monthly Performance Review</h1>
                <p style="margin: 5px 0 0 0; opacity: 0.85;">{date_str} • 1-Year Forward Test Automated Tracking</p>
            </div>

            <div style="padding: 20px; background-color: #f8f9fa; border-left: 1px solid #ddd; border-right: 1px solid #ddd;">
                <table style="width: 100%; border-collapse: collapse; text-align: center; margin-bottom: 20px;">
                    <tr>
                        <td style="padding: 15px; background: white; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); width: 30%;">
                            <span style="font-size: 12px; color: #666; text-transform: uppercase;">Portfolio Value</span><br>
                            <strong style="font-size: 20px; color: #1a237e;">{curr}{total_equity:,.0f}</strong>
                        </td>
                        <td style="width: 5%;"></td>
                        <td style="padding: 15px; background: white; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); width: 30%;">
                            <span style="font-size: 12px; color: #666; text-transform: uppercase;">Total PnL</span><br>
                            <strong style="font-size: 20px; color: {'#2e7d32' if tot_pnl >= 0 else '#c62828'};">{curr}{tot_pnl:+,.0f} ({tot_ret_pct:+.2f}%)</strong>
                        </td>
                        <td style="width: 5%;"></td>
                        <td style="padding: 15px; background: white; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); width: 30%;">
                            <span style="font-size: 12px; color: #666; text-transform: uppercase;">Idle Cash / {proxy_sym}</span><br>
                            <strong style="font-size: 20px; color: #f57f17;">{curr}{proxy_val:,.0f}</strong>
                        </td>
                    </tr>
                </table>

                <h3 style="color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 5px;">Active Portfolio Holdings ({len(positions)} / 10 slots)</h3>
                <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 6px; overflow: hidden; font-size: 13px;">
                    <thead style="background: #e8eaf6; text-align: left;">
                        <tr>
                            <th style="padding: 8px 10px;">Symbol</th>
                            <th style="padding: 8px 10px;">Entry Date</th>
                            <th style="padding: 8px 10px;">Entry</th>
                            <th style="padding: 8px 10px;">Last</th>
                            <th style="padding: 8px 10px;">Hold</th>
                            <th style="padding: 8px 10px;">Unrealized PnL</th>
                        </tr>
                    </thead>
                    <tbody>
                        {holdings_rows}
                    </tbody>
                </table>

                <h3 style="color: #1a237e; border-bottom: 2px solid #1a237e; padding-bottom: 5px; margin-top: 25px;">Closed Trades This Month</h3>
                <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 6px; overflow: hidden; font-size: 13px;">
                    <thead style="background: #e8eaf6; text-align: left;">
                        <tr>
                            <th style="padding: 8px 10px;">Symbol</th>
                            <th style="padding: 8px 10px;">Period</th>
                            <th style="padding: 8px 10px;">Hold</th>
                            <th style="padding: 8px 10px;">Return</th>
                            <th style="padding: 8px 10px;">Reason</th>
                        </tr>
                    </thead>
                    <tbody>
                        {closed_rows}
                    </tbody>
                </table>
            </div>

            <div style="background: #e0e0e0; padding: 12px; text-align: center; font-size: 12px; color: #555; border-radius: 0 0 8px 8px;">
                GFS Quantitative Engine • 1-Year Forward Test Pipeline • Designed for Capital Accumulation Verification
            </div>
        </body>
        </html>
        """

        plain_text = (
            f"=== {market.upper()} MONTHLY PERFORMANCE REPORT ({date_str}) ===\n"
            f"Total Equity: {curr}{total_equity:,.0f} ({tot_ret_pct:+.2f}%)\n"
            f"Initial Capital: {curr}{init_cap:,.0f}\n"
            f"Active Holdings: {len(positions)} stocks\n"
            f"Idle Cash in {proxy_sym}: {curr}{proxy_val:,.0f} ({proxy_units:,.1f} units)\n"
            f"Total Closed Trades to Date: {len(closed_trades)}\n"
        )

        self._send_email(subject=subject, html_body=html_body, text_body=plain_text)
        self._send_telegram(f"📊 *{market.upper()} Monthly Report*\nEquity: {curr}{total_equity:,.0f} ({tot_ret_pct:+.2f}%)\nActive Slots: {len(positions)}/10")
