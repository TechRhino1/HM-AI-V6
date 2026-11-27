"""Active alerting subsystem for the JARVIS quantitative platform.

Provides real-time multi-channel notifications (Logger, Ring Buffer, Webhook)
for operational anomalies, circuit breaker halts, risk limit breaches, and
system errors with thread-safe debouncing and rate limiting.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional
from urllib import request as urllib_request
from urllib.parse import urlparse

logger = logging.getLogger("JARVIS_Alerting")


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"


@dataclass
class Alert:
    title: str
    message: str
    severity: AlertSeverity = AlertSeverity.INFO
    source: str = "JARVIS"
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)
    event_key: str = ""
    id: str = field(default_factory=lambda: os.urandom(6).hex())
    acknowledged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value if hasattr(self.severity, "value") else str(self.severity)
        return d


class AlertManager:
    """Thread-safe active alert dispatcher with debouncing and webhook integration."""

    _instance: Optional[AlertManager] = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> AlertManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, max_history: int = 100, webhook_url: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self._max_history = max_history
        self._webhook_url = webhook_url or os.environ.get("JARVIS_ALERT_WEBHOOK_URL", "").strip()
        self._history: Deque[Alert] = deque(maxlen=max_history)
        self._last_alert_times: Dict[str, float] = {}
        self._history_lock = threading.Lock()
        self._initialized = True
        logger.info(
            "AlertManager initialized (webhook=%s, history_cap=%d)",
            "ENABLED" if self._webhook_url else "DISABLED (set JARVIS_ALERT_WEBHOOK_URL)",
            max_history,
        )

    def dispatch(
        self,
        title: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.INFO,
        source: str = "JARVIS",
        details: Optional[Dict[str, Any]] = None,
        event_key: str = "",
        debounce_seconds: float = 60.0,
    ) -> bool:
        """Dispatches an alert across all active channels if not debounced.

        Returns True if the alert was dispatched; False if suppressed by debouncing.
        """
        now = time.time()
        key = event_key or f"{source}:{title}"

        # 1. Debounce check
        with self._history_lock:
            last_time = self._last_alert_times.get(key, 0.0)
            if debounce_seconds > 0 and (now - last_time) < debounce_seconds:
                logger.debug("Alert '%s' suppressed by debouncing (cooldown: %.1fs)", key, debounce_seconds)
                return False
            self._last_alert_times[key] = now

        alert = Alert(
            title=title,
            message=message,
            severity=severity,
            source=source,
            timestamp=now,
            details=details or {},
            event_key=key,
        )

        # 2. Append to ring buffer (and the daily file, when persistence is on)
        with self._history_lock:
            self._history.append(alert)
        self._persist(alert.to_dict())

        # 3. Structured log dispatch
        log_msg = f"🔔 [{alert.severity.value}] [{alert.source}] {alert.title}: {alert.message}"
        if alert.severity in (AlertSeverity.FATAL, AlertSeverity.CRITICAL):
            logger.critical(log_msg)
        elif alert.severity == AlertSeverity.WARNING:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        # 4. Asynchronous Webhook Dispatch
        if self._webhook_url:
            threading.Thread(
                target=self._send_webhook_payload,
                args=(alert,),
                daemon=True,
                name="alert-webhook-worker",
            ).start()

        return True

    @staticmethod
    def format_webhook_payload(webhook_url: str, alert: Alert) -> Dict[str, Any]:
        """Auto-formats webhook payload for Discord, Telegram, or Slack/generic."""
        url_lower = webhook_url.lower()
        if "discord.com" in url_lower:
            return {
                "content": f"**[{alert.severity.value}] [{alert.source}] {alert.title}**\n{alert.message}"
            }
        elif "api.telegram.org" in url_lower:
            chat_id = os.environ.get("JARVIS_TELEGRAM_CHAT_ID", "")
            return {
                "chat_id": chat_id,
                "text": f"*{alert.severity.value} - {alert.source}: {alert.title}*\n{alert.message}",
                "parse_mode": "Markdown"
            }
        else:
            return {
                "text": f"*{alert.severity.value} Alert - {alert.source}*\n*{alert.title}*\n{alert.message}",
                "severity": alert.severity.value,
                "title": alert.title,
                "source": alert.source,
                "timestamp": alert.timestamp,
                "details": alert.details,
            }

    def _send_webhook_payload(self, alert: Alert) -> None:
        """Sends HTTP POST webhook payload without blocking the caller."""
        if not self._webhook_url:
            return
        payload = self.format_webhook_payload(self._webhook_url, alert)
        try:
            req = urllib_request.Request(
                self._webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "HM-Algo-Alerting/2.0"},
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=5.0) as resp:
                if resp.status >= 400:
                    logger.warning("Webhook alert failed with HTTP status %d", resp.status)
        except Exception as e:
            # Host only: Telegram/Discord webhook URLs embed their secret token.
            logger.warning("Webhook dispatch error to %s: %s", urlparse(self._webhook_url).netloc, e)

    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns the most recent alerts in chronological reverse (newest first)."""
        with self._history_lock:
            items = list(reversed(self._history))
        return [a.to_dict() for a in items[:limit]]

    # ── Persistence and acknowledgement (dashboard delivery, 2026-11-27) ─────
    def enable_persistence(self, directory: str, reload_days: int = 2) -> None:
        """Write every alert to directory/alerts_YYYYMMDD.jsonl and reload the last `reload_days`
        of history, so the dashboard keeps alerts (and acknowledgements) across restarts.
        Off by default: only the engine start-up turns it on, tests never write files."""
        self._persist_dir = directory
        try:
            os.makedirs(directory, exist_ok=True)
            names = sorted(n for n in os.listdir(directory) if n.startswith("alerts_") and n.endswith(".jsonl"))
            rows, acked = [], set()
            for name in names[-max(1, reload_days):]:
                with open(os.path.join(directory, name), encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if "ack" in row:
                            acked.add(row["ack"])
                        elif row.get("title"):
                            rows.append(row)
            with self._history_lock:
                for row in rows[-self._max_history:]:
                    a = Alert(title=row["title"], message=row.get("message", ""),
                              severity=AlertSeverity(row.get("severity", "INFO")), source=row.get("source", "JARVIS"),
                              timestamp=float(row.get("timestamp", 0.0)), details=row.get("details") or {},
                              event_key=row.get("event_key", ""), id=row.get("id") or os.urandom(6).hex(),
                              acknowledged=row.get("id") in acked)
                    self._history.append(a)
        except Exception as exc:  # noqa: BLE001 - alerts must never stop the engine
            logger.warning("Alert history reload failed: %s", exc)

    def _persist(self, row: Dict[str, Any]) -> None:
        d = getattr(self, "_persist_dir", None)
        if not d:
            return
        try:
            path = os.path.join(d, time.strftime("alerts_%Y%m%d.jsonl", time.gmtime()))
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Alert persistence failed: %s", exc)

    def acknowledge(self, ids: List[str]) -> int:
        """Mark alerts acknowledged (persisted as {"ack": id} lines). Returns how many matched."""
        want, n = {str(i) for i in ids or []}, 0
        with self._history_lock:
            for a in self._history:
                if a.id in want and not a.acknowledged:
                    a.acknowledged, n = True, n + 1
                    self._persist({"ack": a.id, "at": time.time()})
        return n

    def clear(self) -> None:
        """Clears alert history and debouncing state (primarily for tests)."""
        with self._history_lock:
            self._history.clear()
            self._last_alert_times.clear()


# Global singleton instance
ALERT_MANAGER = AlertManager()


def dispatch_alert(
    title: str,
    message: str,
    severity: AlertSeverity = AlertSeverity.INFO,
    source: str = "JARVIS",
    details: Optional[Dict[str, Any]] = None,
    event_key: str = "",
    debounce_seconds: float = 60.0,
) -> bool:
    """Convenience helper to dispatch an alert through the global AlertManager."""
    return ALERT_MANAGER.dispatch(
        title=title,
        message=message,
        severity=severity,
        source=source,
        details=details,
        event_key=event_key,
        debounce_seconds=debounce_seconds,
    )
