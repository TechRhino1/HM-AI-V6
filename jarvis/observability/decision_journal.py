"""Decision journal: every evaluated setup, taken or vetoed, with its reasons.

One JSON line per (symbol, style) whenever its verdict changes (the scan runs
every few seconds, so identical verdicts are not repeated). Lines go to
``<DATA_DIR>/decisions/decisions_YYYYMMDD.jsonl``. Backtests write nothing, and a
journal failure never reaches the trading path.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()
_LAST: Dict[tuple, str] = {}


def _dir() -> str:
    from jarvis.config.paths import DATA_DIR
    return os.path.join(DATA_DIR, "decisions")


def record(result: Dict[str, Any]) -> None:
    try:
        from jarvis.config.runtime import is_offline
        if is_offline():
            return
        d = result.get("decision")
        qg = getattr(d, "quality_gate", None)
        row = {
            "symbol": result.get("symbol"),
            "style": result.get("trade_style"),
            "decision": getattr(d, "decision", None),
            "bias": getattr(d, "bias", None),
            "strategy": getattr(getattr(d, "strategy", None), "value", getattr(d, "strategy", None)),
            "score": getattr(d, "ai_score", None),
            "win_prob": getattr(d, "model_confidence", None),
            "rr": getattr(d, "risk_reward_ratio", None),
            "ev": getattr(d, "expected_value", None),
            "entry": getattr(d, "entry_price", None),
            "sl": getattr(d, "stop_loss", None),
            "tp": getattr(d, "take_profit", None),
            "failing": list(getattr(qg, "failing_reasons", []) or []),
            "waiting": list(getattr(d, "waiting_reasons", []) or []),
            "authorized": bool(result.get("authorized")),
            "auth_reason": result.get("auth_reason") or "",
            "executed": (result.get("execution") or {}).get("status"),
            "vetoes": list(getattr(d, "dispatch_vetoes", None) or []),
        }
        verdict = json.dumps({k: row[k] for k in ("decision", "bias", "strategy", "failing",
                                                    "waiting", "authorized", "auth_reason", "executed",
                                                    "vetoes")},
                             default=str, sort_keys=True)
        key = (row["symbol"], row["style"])
        with _LOCK:
            if _LAST.get(key) == verdict:
                return
            _LAST[key] = verdict
            os.makedirs(_dir(), exist_ok=True)
            row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            path = os.path.join(_dir(), time.strftime("decisions_%Y%m%d.jsonl", time.gmtime()))
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")
    except Exception as e:
        logger.warning("decision journal write failed: %s", e)


def record_dispatch(row: Dict[str, Any]) -> None:
    """Journal one arbiter dispatch (the path that actually places orders), tagged
    kind=dispatch. Never de-duplicated: every attempt is a real event."""
    try:
        from jarvis.config.runtime import is_offline
        if is_offline():
            return
        row = dict(row, kind="dispatch", ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        with _LOCK:
            os.makedirs(_dir(), exist_ok=True)
            path = os.path.join(_dir(), time.strftime("decisions_%Y%m%d.jsonl", time.gmtime()))
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")
    except Exception as e:
        logger.warning("decision journal dispatch write failed: %s", e)


def record_auto(row: Dict[str, Any]) -> None:
    """Journal one Trade Style AUTO verdict for a symbol (tagged kind=auto); written only when that
    symbol's verdict changes, so a quiet symbol doesn't add a row every cycle."""
    try:
        from jarvis.config.runtime import is_offline
        if is_offline():
            return
        verdict = json.dumps({k: v for k, v in row.items() if k != "ts"}, default=str, sort_keys=True)
        key = ("AUTO", row.get("symbol"))
        with _LOCK:
            if _LAST.get(key) == verdict:
                return
            _LAST[key] = verdict
            os.makedirs(_dir(), exist_ok=True)
            out = {"kind": "auto", **row, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            path = os.path.join(_dir(), time.strftime("decisions_%Y%m%d.jsonl", time.gmtime()))
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(out, default=str) + "\n")
    except Exception as e:
        logger.warning("decision journal auto write failed: %s", e)


def record_router(row: Dict[str, Any]) -> None:
    """Journal one trend-router decision (component, regime, news, action, reason) in the same
    daily file, tagged kind=router; written only when that component's verdict changes."""
    try:
        from jarvis.config.runtime import is_offline
        if is_offline():
            return
        verdict = json.dumps({k: v for k, v in row.items() if k != "ts"}, default=str, sort_keys=True)
        key = ("ROUTER", row.get("component"))
        with _LOCK:
            if _LAST.get(key) == verdict:
                return
            _LAST[key] = verdict
            os.makedirs(_dir(), exist_ok=True)
            out = {"kind": "router", **row, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            path = os.path.join(_dir(), time.strftime("decisions_%Y%m%d.jsonl", time.gmtime()))
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(out, default=str) + "\n")
    except Exception:
        pass
