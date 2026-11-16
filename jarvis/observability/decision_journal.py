"""Decision journal: every evaluated setup, taken or vetoed, with its reasons.

One JSON line per (symbol, style) whenever its verdict changes (the scan runs
every few seconds, so identical verdicts are not repeated). Lines go to
``<DATA_DIR>/decisions/decisions_YYYYMMDD.jsonl``. Backtests write nothing, and a
journal failure never reaches the trading path.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict

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
        }
        verdict = json.dumps({k: row[k] for k in ("decision", "bias", "strategy", "failing",
                                                    "waiting", "authorized", "auth_reason", "executed")},
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
    except Exception:
        pass
