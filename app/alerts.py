"""Alert and Notification Dispatcher for Indian Equity Paper Trading.

Supports:
- Telegram Bot Notifications
- Discord Webhooks
- Local Logging / Console Fallback
- No paid services required
"""

import logging
import requests
from typing import Optional, Dict
from app.config import CONFIG

logger = logging.getLogger("paper_trading.alerts")

class AlertDispatcher:
    def __init__(self):
        self.telegram_token = CONFIG.TELEGRAM_BOT_TOKEN
        self.telegram_chat_id = CONFIG.TELEGRAM_CHAT_ID
        self.discord_webhook = CONFIG.DISCORD_WEBHOOK_URL

    def send_alert(self, title: str, message: str, event_type: str = "INFO") -> bool:
        """Dispatch notification across configured channels."""
        formatted_text = f"🚨 [{event_type}] {title}\n\n{message}"
        logger.info(f"[ALERT] {title}: {message}")

        # 1. Dispatch to Telegram if configured
        if self.telegram_token and self.telegram_chat_id:
            try:
                url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
                payload = {
                    "chat_id": self.telegram_chat_id,
                    "text": formatted_text,
                    "parse_mode": "Markdown"
                }
                res = requests.post(url, json=payload, timeout=10.0)
                if res.status_code != 200:
                    logger.warning(f"Telegram alert delivery failed: {res.text}")
            except Exception as e:
                logger.error(f"Telegram dispatch exception: {e}")

        # 2. Dispatch to Discord if configured
        if self.discord_webhook:
            try:
                payload = {"content": formatted_text}
                res = requests.post(self.discord_webhook, json=payload, timeout=10.0)
                if res.status_code not in (200, 204):
                    logger.warning(f"Discord webhook delivery failed: {res.text}")
            except Exception as e:
                logger.error(f"Discord dispatch exception: {e}")

        return True

    def alert_new_signal(self, symbol: str, rel_vol: float, alloc_rs: float):
        self.send_alert(
            title="NEW SIGNAL GENERATED",
            message=f"Symbol: *{symbol}*\nRelative Volume: *{rel_vol:.2f}x*\nProposed Allocation: *₹{alloc_rs:,.2f}*",
            event_type="SIGNAL"
        )

    def alert_entry(self, symbol: str, price: float, shares: float, stop_price: float):
        self.send_alert(
            title="SIMULATED ENTRY EXECUTED",
            message=f"Symbol: *{symbol}*\nFill Price: *₹{price:.2f}*\nShares: *{shares:.2f}*\nInitial Stop (-3%): *₹{stop_price:.2f}*",
            event_type="ENTRY"
        )

    def alert_exit(self, symbol: str, exit_price: float, return_pct: float, reason: str):
        self.send_alert(
            title="SIMULATED EXIT EXECUTED",
            message=f"Symbol: *{symbol}*\nExit Price: *₹{exit_price:.2f}*\nReturn: *{return_pct:+.2f}%*\nReason: *{reason}*",
            event_type="EXIT"
        )

    def alert_stop_loss(self, symbol: str, exit_price: float, return_pct: float):
        self.send_alert(
            title="STOP-LOSS TRIGGERED",
            message=f"Symbol: *{symbol}*\nExecuted Price: *₹{exit_price:.2f}*\nRealized Return: *{return_pct:+.2f}%*",
            event_type="STOP_LOSS"
        )

    def alert_lower_circuit(self, symbol: str, price: float):
        self.send_alert(
            title="EXIT BLOCKED BY LOWER CIRCUIT",
            message=f"Symbol: *{symbol}* locked in lower circuit at *₹{price:.2f}*. Exit deferred until circuit opens.",
            event_type="LOWER_CIRCUIT"
        )

    def alert_system_failure(self, error_msg: str):
        self.send_alert(
            title="SYSTEM / DATA PIPELINE ERROR",
            message=f"Error encountered: ```{error_msg}```",
            event_type="ERROR"
        )
