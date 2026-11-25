"""System monitor checks run by the orchestrator watchdog (2026-11-25 plan, Phase 5).

Pure: every input is passed in, so the checks are unit-testable and the watchdog
stays the only thread. Each check returns OK | WARN | CRITICAL with a detail, and
``run_checks`` raises debounced alerts for anything that is not OK.
"""
from __future__ import annotations

from collections import Counter as _Tally
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

OK, WARN, CRITICAL = "OK", "WARN", "CRITICAL"
_SENT = {"FILLED", "PARTIAL", "PLACED", "UNKNOWN", "POSITION_CONFIRMED"}


def _ts(row: Dict[str, Any]) -> float:
    try:
        return datetime.strptime(str(row.get("ts")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def check_loop(now: float, heartbeat: float, cfg: Any) -> Dict[str, Any]:
    age = now - float(heartbeat or 0.0)
    status = CRITICAL if age > cfg.loop_stall_s else OK
    return {"status": status, "value": round(age, 1), "threshold": cfg.loop_stall_s,
            "detail": "orchestration loop heartbeat age (s)"}


def check_no_trade(now: float, rows: List[Dict[str, Any]], last_send: float, cfg: Any) -> Dict[str, Any]:
    horizon = cfg.no_trade_hours * 3600.0
    idle = now - last_send if last_send else None
    if idle is not None and idle <= horizon:
        return {"status": OK, "value": round(idle / 3600.0, 2), "threshold": cfg.no_trade_hours,
                "detail": "hours since last order sent"}
    blockers = _Tally(r.get("blocked_by") for r in rows if r.get("blocked_by") and now - _ts(r) <= horizon)
    top = ", ".join(f"{g} x{n}" for g, n in blockers.most_common(3)) or "no attempts journaled"
    return {"status": WARN, "value": None if idle is None else round(idle / 3600.0, 2),
            "threshold": cfg.no_trade_hours, "detail": f"no order sent in {cfg.no_trade_hours:g}h; top blockers: {top}",
            "top_blockers": blockers.most_common(3)}


def check_reject_spike(now: float, rows: List[Dict[str, Any]], cfg: Any) -> Dict[str, Any]:
    rej = [_ts(r) for r in rows if r.get("blocked_by")]
    last30 = sum(1 for t in rej if now - t <= 1800)
    day = sum(1 for t in rej if now - t <= 86400)
    baseline = day / 48.0  # average per 30-minute window over 24h
    spike = baseline >= 1.0 and last30 > cfg.reject_spike_factor * baseline
    return {"status": WARN if spike else OK, "value": last30, "threshold": round(cfg.reject_spike_factor * baseline, 1),
            "detail": "journaled rejections in the last 30 min vs 24h average"}


def check_rate(name: str, num: float, den: float, warn_at: float) -> Dict[str, Any]:
    rate = (num / den) if den > 0 else 0.0
    return {"status": WARN if den > 0 and rate > warn_at else OK, "value": round(rate, 4),
            "threshold": warn_at, "detail": f"{name} ({int(num)}/{int(den)})"}


def check_verifier(verifications: Iterable[Dict[str, Any]], cfg: Any) -> Dict[str, Any]:
    recent = list(verifications)[-200:]
    broken = sum(1 for v in recent if any(r.get("rule") in ("verifier_error", "time_budget") and not r.get("ok")
                                          for r in v.get("reasons", [])))
    out = check_rate("verifier errors/timeouts", broken, len(recent), cfg.verifier_fail_rate_warn)
    out["status"] = CRITICAL if out["status"] == WARN else OK  # a failing verifier blocks (fail closed)
    return out


def check_forward_exposure(positions: Iterable[Any], equity: float, max_portfolio_risk_pct: float,
                           cfg: Any) -> Dict[str, Any]:
    from jarvis.data.symbol_registry import get_dollar_risk_per_price_unit
    from jarvis.risk.exposure import is_forward_test
    risk = 0.0
    for p in positions:
        if not is_forward_test(p) or not float(getattr(p, "sl", 0.0) or 0.0):
            continue
        dist = max(0.0, (p.open_price - p.sl) if str(p.type).upper() == "BUY" else (p.sl - p.open_price))
        risk += dist * float(p.volume) * get_dollar_risk_per_price_unit(p.symbol)
    budget = equity * max_portfolio_risk_pct / 100.0 if equity > 0 else 0.0
    pct = (risk / budget * 100.0) if budget > 0 else 0.0
    return {"status": WARN if pct > cfg.forward_test_exposure_warn_pct else OK, "value": round(pct, 1),
            "threshold": cfg.forward_test_exposure_warn_pct,
            "detail": f"forward-test open risk ${risk:.2f} as % of the portfolio risk budget"}


def run_checks(*, now: float, heartbeat: float, rows: List[Dict[str, Any]], last_send: float,
               verifications: Iterable[Dict[str, Any]], positions: Iterable[Any], equity: float,
               max_portfolio_risk_pct: float, fallbacks: float, evaluations: float, cfg: Any,
               alert: bool = True) -> Dict[str, Any]:
    checks = {
        "loop_heartbeat": check_loop(now, heartbeat, cfg),
        "no_trade": check_no_trade(now, rows, last_send, cfg),
        "rejection_spike": check_reject_spike(now, rows, cfg),
        "analyst_fallbacks": check_rate("analyst fallbacks per evaluation", fallbacks, evaluations, cfg.fallback_rate_warn),
        "verifier_health": check_verifier(verifications, cfg),
        "forward_test_exposure": check_forward_exposure(positions, equity, max_portfolio_risk_pct, cfg),
    }
    worst = CRITICAL if any(c["status"] == CRITICAL for c in checks.values()) else (
        WARN if any(c["status"] == WARN for c in checks.values()) else OK)
    if alert:
        try:
            from jarvis.observability.alerting import AlertSeverity, dispatch_alert
            for name, c in checks.items():
                if c["status"] != OK:
                    dispatch_alert(title=f"Monitor: {name} {c['status']}", message=c["detail"],
                                   severity=AlertSeverity.CRITICAL if c["status"] == CRITICAL else AlertSeverity.WARNING,
                                   source="SystemMonitor", details={k: v for k, v in c.items() if k != "detail"},
                                   event_key=f"monitor_{name}", debounce_seconds=1800.0)
        except Exception:
            pass
    return {"status": worst, "checked_at": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"),
            "checks": checks}


def counter_total(counter: Any) -> float:
    """Sum of every series of a metrics Counter (0 when unavailable)."""
    try:
        return float(sum(s["value"] for s in counter.samples()))
    except Exception:
        return 0.0


def latest_send_ts(rows: List[Dict[str, Any]], fallback: Optional[float] = None) -> float:
    sends = [_ts(r) for r in rows if str(r.get("status") or "").upper() in _SENT]
    return max(sends + [fallback or 0.0])


# ── Read models for the API (/api/gates/stats, /api/decisions) ───────────────

def gate_stats(rows: List[Dict[str, Any]], hours: float, now: float, origin: Optional[str] = None) -> Dict[str, Any]:
    """Blocking-gate counts and sends over the last ``hours`` of journaled attempts."""
    cut = now - hours * 3600.0
    sel = [r for r in rows if _ts(r) >= cut and (not origin or str(r.get("origin", "arbiter")).startswith(origin))]
    blocked = _Tally(r.get("blocked_by") for r in sel if r.get("blocked_by"))
    shadow = _Tally(g.get("gate") for r in sel for g in (r.get("gates") or []) if g.get("verdict") == "SHADOW_REJECT")
    sent = sum(1 for r in sel if str(r.get("status") or "").upper() in _SENT)
    return {"window_hours": hours, "attempts": len(sel), "sent": sent,
            "blocked_by": dict(blocked.most_common()), "shadow_rejects": dict(shadow.most_common()),
            "note": "attempt rows are de-duplicated per (origin, symbol, style) verdict; "
                    "GATE_VERDICTS in /api/metrics counts every evaluation"}


def read_decisions(directory: str, *, since: Optional[float] = None, symbol: str = "", origin: str = "",
                   blocked_by: str = "", limit: int = 200, max_lines: int = 200_000) -> List[Dict[str, Any]]:
    """Newest-first dispatch rows from the decision journal files (capped scan)."""
    import json
    import os
    limit = max(1, min(int(limit), 1000))
    try:
        files = sorted((f for f in os.listdir(directory) if f.startswith("decisions_") and f.endswith(".jsonl")),
                       reverse=True)
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    scanned = 0
    for name in files:
        try:
            with open(os.path.join(directory, name), "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            continue
        for line in reversed(lines):
            scanned += 1
            if scanned > max_lines or len(out) >= limit:
                return out
            if '"dispatch"' not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if since and _ts(row) < since:
                return out
            if symbol and str(row.get("symbol", "")).upper() != symbol.upper():
                continue
            if origin and not str(row.get("origin", "arbiter")).startswith(origin):
                continue
            if blocked_by and row.get("blocked_by") != blocked_by:
                continue
            out.append(row)
    return out


def verdict_counts(counter: Any) -> List[Dict[str, Any]]:
    """GATE_VERDICTS samples as rows {gate, verdict, origin, count} (every evaluation counted)."""
    try:
        return sorted(({**s["labels"], "count": s["value"]} for s in counter.samples()),
                      key=lambda r: -r["count"])
    except Exception:
        return []
