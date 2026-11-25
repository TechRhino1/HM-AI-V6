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
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()
_LAST: Dict[tuple, str] = {}

#: Last dispatch-attempt rows (de-duplicated like the file) for the API and the watchdog.
RECENT: Deque[Dict[str, Any]] = deque(maxlen=5000)

#: Order statuses that mean an order reached the broker; such attempts are never de-duplicated.
SENT_STATUSES = frozenset({"FILLED", "PARTIAL", "PLACED", "UNKNOWN", "POSITION_CONFIRMED"})


@dataclass
class GateTrace:
    """Every gate verdict for ONE order attempt, in the order the gates ran.

    Rides on ``decision.gate_trace`` so no signatures change; anything that
    receives a decision without one (backtests, tests) simply records nothing.
    verdict is PASS | REJECT | SCALE | SKIP | SHADOW_REJECT.
    """
    symbol: str
    style: str = ""
    bias: str = ""
    origin: str = "arbiter"  # arbiter | forward_test:<TAG> | manual
    attempt_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    gates: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, gate: str, verdict: str, reason: str = "", value: Any = None,
            threshold: Any = None, ms: Optional[float] = None) -> "GateTrace":
        step: Dict[str, Any] = {"gate": gate, "verdict": verdict}
        if reason:
            step["reason"] = str(reason)[:300]
        if value is not None:
            step["value"] = value
        if threshold is not None:
            step["threshold"] = threshold
        if ms is not None:
            step["ms"] = round(float(ms), 2)
        self.gates.append(step)
        return self

    def reject(self, gate: str, reason: str = "", **kw: Any) -> "GateTrace":
        return self.add(gate, "REJECT", reason, **kw)

    def blocked_by(self) -> Optional[str]:
        for g in self.gates:
            if g["verdict"] == "REJECT":
                return g["gate"]
        return None

    def final(self) -> str:
        return self.blocked_by() or "SENT"


def trace_of(decision: Any) -> Optional[GateTrace]:
    """The GateTrace riding on a decision, or None (backtests / tests / legacy callers)."""
    t = getattr(decision, "gate_trace", None)
    return t if isinstance(t, GateTrace) else None


def record_attempt(trace: GateTrace, **extra: Any) -> None:
    """Journal one order attempt with its full gate trace (kind=dispatch).

    Every verdict is counted in GATE_VERDICTS. The row itself is de-duplicated
    per (origin, symbol, style) on the blocking gate + reason, because the arbiter
    re-evaluates every candidate every few seconds; an attempt that reached the
    broker is always written.
    """
    try:
        # No offline check here: record_dispatch owns it (and tests patch record_dispatch).
        origin_kind = trace.origin.split(":", 1)[0]
        try:
            from jarvis.observability.instruments import GATE_VERDICTS
            for g in trace.gates:
                GATE_VERDICTS.inc(gate=g["gate"], verdict=g["verdict"], origin=origin_kind)
        except Exception:  # metrics never reach the trading path
            pass
        blocked = trace.blocked_by()
        block_reason = next((g.get("reason", "") for g in trace.gates if g["verdict"] == "REJECT"), "")
        row = {"symbol": trace.symbol, "style": trace.style, "bias": trace.bias,
               "origin": trace.origin, "attempt_id": trace.attempt_id,
               "blocked_by": blocked, "gates": trace.gates, **extra}
        sent = str(extra.get("status") or "").upper() in SENT_STATUSES
        key = ("ATTEMPT", trace.origin, trace.symbol, trace.style)
        verdict = json.dumps([blocked, block_reason, extra.get("status")], default=str)
        with _LOCK:
            if not sent and _LAST.get(key) == verdict:
                return
            _LAST[key] = verdict
        record_dispatch(row)
    except Exception as e:
        logger.warning("decision journal attempt write failed: %s", e)


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
            RECENT.append(row)
            os.makedirs(_dir(), exist_ok=True)
            path = os.path.join(_dir(), time.strftime("decisions_%Y%m%d.jsonl", time.gmtime()))
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")
    except Exception as e:
        logger.warning("decision journal dispatch write failed: %s", e)


#: Last position-monitor actions (enforced and shadow) for the API.
MONITOR_ACTIONS: Deque[Dict[str, Any]] = deque(maxlen=2000)


def record_monitor(row: Dict[str, Any]) -> None:
    """Journal one position-monitor action (kind=monitor): SL/TP change, close, or a
    SHADOW "would have" verdict. Never raises into the monitor loop."""
    try:
        out = {"kind": "monitor", **row, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        with _LOCK:
            MONITOR_ACTIONS.append(out)
        from jarvis.config.runtime import is_offline
        if is_offline():
            return
        with _LOCK:
            os.makedirs(_dir(), exist_ok=True)
            path = os.path.join(_dir(), time.strftime("decisions_%Y%m%d.jsonl", time.gmtime()))
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(out, default=str) + "\n")
    except Exception as e:
        logger.warning("decision journal monitor write failed: %s", e)


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
