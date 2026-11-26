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


def check_position_monitor(now: float, status: Optional[Dict[str, Any]], open_positions: int,
                           cfg: Any) -> Dict[str, Any]:
    """Is the 2-second position manager alive? It is silent while idle, so check its heartbeat."""
    if status is None:
        return {"status": WARN if open_positions else OK, "value": None, "threshold": None,
                "detail": "position monitor not running (orchestrator inline trailing only)"
                          + (f"; {open_positions} open position(s)" if open_positions else "")}
    if not status.get("running") or not status.get("thread_alive"):
        return {"status": CRITICAL, "value": None, "threshold": None,
                "detail": "position monitor thread is not running: open trades are not being managed"}
    last = float(status.get("last_tick_at") or 0.0)
    age = now - last if last else None
    if age is None or age > cfg.position_monitor_stall_s:
        return {"status": CRITICAL, "value": None if age is None else round(age, 1),
                "threshold": cfg.position_monitor_stall_s,
                "detail": "position monitor has not completed a tick" + ("" if age is None else f" for {age:.0f}s")}
    errs = int(status.get("tick_errors") or 0)
    return {"status": WARN if errs else OK, "value": round(age, 1), "threshold": cfg.position_monitor_stall_s,
            "detail": f"last tick {age:.0f}s ago; {errs} tick error(s) since start"
                      + (f" (last: {status.get('last_tick_error')})" if errs else "")}


def _legs(symbol: str):
    """Currency legs of a symbol: (base, quote). Non-FX instruments map to (symbol, USD)."""
    try:
        from jarvis.data.symbol_registry import resolve
        canon = resolve(symbol).canonical.upper()
    except Exception:
        canon = str(symbol).upper()
    if len(canon) == 6 and canon.isalpha():
        return canon[:3], canon[3:]
    return canon, "USD"


def position_risk_usd(p: Any) -> float:
    from jarvis.data.symbol_registry import get_dollar_risk_per_price_unit
    sl = float(getattr(p, "sl", 0.0) or 0.0)
    if sl <= 0:
        return 0.0
    dist = (p.open_price - sl) if str(p.type).upper() == "BUY" else (sl - p.open_price)
    return max(0.0, dist) * float(p.volume) * get_dollar_risk_per_price_unit(p.symbol)


def currency_exposure(positions: Iterable[Any]) -> Dict[str, Dict[str, float]]:
    """Risk-to-stop per currency and direction across ALL open positions (bot + FT + manual).
    A BUY is long the base / short the quote; same-direction risk on a currency adds up."""
    out: Dict[str, Dict[str, float]] = {}
    for p in positions:
        risk = position_risk_usd(p)
        if risk <= 0:
            continue
        base, quote = _legs(p.symbol)
        buy = str(p.type).upper() == "BUY"
        for ccy, side in ((base, "long" if buy else "short"), (quote, "short" if buy else "long")):
            row = out.setdefault(ccy, {"long": 0.0, "short": 0.0})
            row[side] += risk
    return out


def check_currency_exposure(positions: Iterable[Any], equity: float, cap_pct: float) -> Dict[str, Any]:
    exp = currency_exposure(positions)
    if equity <= 0 or not exp:
        return {"status": OK, "value": 0.0, "threshold": cap_pct, "detail": "no open risk", "currencies": {}}
    worst_ccy, worst = None, 0.0
    for ccy, row in exp.items():
        directional = max(row["long"], row["short"])
        if directional > worst:
            worst_ccy, worst = ccy, directional
    pct = worst / equity * 100.0
    side = "long" if exp[worst_ccy]["long"] >= exp[worst_ccy]["short"] else "short"
    return {"status": WARN if pct > cap_pct else OK, "value": round(pct, 2), "threshold": cap_pct,
            "detail": f"largest same-direction currency risk: {side} {worst_ccy} ${worst:.2f} ({pct:.2f}% of equity)",
            "currencies": {c: {k: round(v, 2) for k, v in r.items()} for c, r in exp.items()}}


def check_stops_and_gap(positions: Iterable[Any], equity: float, now: float) -> Dict[str, Any]:
    """Any open position without a broker stop is CRITICAL. Also reports the gap-adjusted
    worst case: from Friday 20:00 UTC non-crypto stops are assumed to gap to 3x distance."""
    from jarvis.data.symbol_registry import resolve
    positions = list(positions)
    naked = [p.ticket for p in positions if float(getattr(p, "sl", 0.0) or 0.0) <= 0]
    moment = datetime.fromtimestamp(now, timezone.utc)
    weekend_risk = moment.weekday() == 4 and moment.hour >= 20 or moment.weekday() in (5, 6)
    worst = 0.0
    for p in positions:
        r = position_risk_usd(p)
        try:
            crypto = bool(getattr(resolve(p.symbol), "is_crypto", False))
        except Exception:
            crypto = False
        worst += r * (3.0 if weekend_risk and not crypto else 1.0)
    pct = worst / equity * 100.0 if equity > 0 else 0.0
    return {"status": CRITICAL if naked else OK, "value": round(pct, 2), "threshold": None,
            "detail": (f"{len(naked)} position(s) WITHOUT a broker stop: {naked}; " if naked else "all positions have a broker stop; ")
            + f"worst case to stops {'(gap-adjusted x3) ' if weekend_risk else ''}${worst:.2f} ({pct:.2f}% of equity)"}


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


def check_live_drift(live_r: Optional[Dict[str, List[float]]], profiles: Optional[Dict[str, Any]],
                     quarantine_r: float = -0.15, min_n: int = 20) -> Dict[str, Any]:
    """Live realised R per symbol vs the calibrated out-of-sample expectancy it was deployed on.

    WARN when the live mean sits more than 2 standard errors below the profile's OOS figure;
    CRITICAL when it is also below the quarantine bar. ``live_r`` is {symbol: [R, ...]}."""
    if not live_r or not profiles:
        return {"status": OK, "detail": "no live closes or calibrated profiles to compare", "symbols": {}}
    out: Dict[str, Any] = {}
    worst = OK
    for sym, rs in live_r.items():
        prof = profiles.get(sym)
        if prof is None or len(rs) < min_n:
            continue
        n = len(rs)
        mean = sum(rs) / n
        sd = (sum((r - mean) ** 2 for r in rs) / (n - 1)) ** 0.5
        se = sd / n ** 0.5
        # Judge against the walk-forward holdout when one was stamped (the evidence the deployment
        # gate uses), else the calibration's out-of-sample figure.
        hn = int(getattr(prof, "holdout_trades", 0) or 0)
        he = getattr(prof, "holdout_expectancy_r", None)
        use_holdout = he is not None and hn >= 10
        oos = float(he) if use_holdout else float(getattr(prof, "oos_expectancy_r", 0.0) or 0.0)
        st = OK
        if mean < oos - 2.0 * se:
            st = CRITICAL if mean < quarantine_r else WARN
        out[sym] = {"status": st, "n": n, "live_r": round(mean, 3), "se": round(se, 3), "oos_r": round(oos, 3),
                    "benchmark": "holdout" if use_holdout else "oos"}
        if st == CRITICAL or (st == WARN and worst == OK):
            worst = st
    bad = {k: v for k, v in out.items() if v["status"] != OK}
    detail = ("live expectancy below calibration: " + ", ".join(
        f"{k} {v['live_r']:+.2f}R vs OOS {v['oos_r']:+.2f}R (n={v['n']})" for k, v in bad.items())
              if bad else f"{len(out)} symbol(s) within 2 SE of their calibrated expectancy")
    return {"status": worst, "detail": detail, "symbols": out}


_LAST_DRIFT_ADVISORY: Dict[str, str] = {}


def record_drift_advisory(state: Dict[str, Any], directory: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Append a deterministic recommendation to data/advisories when live expectancy drifts below
    its validated benchmark. Read-only: it never changes a setting (promotion stays with
    tools/promote_model.py). Written once per day per distinct drift verdict."""
    import json
    import os
    import time
    try:
        c = ((state or {}).get("checks") or {}).get("live_vs_calibrated") or {}
        bad = {k: v for k, v in (c.get("symbols") or {}).items() if v.get("status") != OK}
        if not bad:
            return None
        day = time.strftime("%Y%m%d", time.gmtime())
        key = json.dumps(sorted((k, v["status"]) for k, v in bad.items()))
        if _LAST_DRIFT_ADVISORY.get(day) == key:
            return None
        recs = [f"{sym}: live {v['live_r']:+.2f}R over {v['n']} closes vs {v['benchmark']} {v['oos_r']:+.2f}R "
                f"({v['status']}). Re-validate with tools/engine_select.py on fresh data; the live-expectancy "
                f"quarantine acts automatically below its bar, any parameter change needs "
                f"tools/promote_model.py approval." for sym, v in bad.items()]
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source": "MONITOR_DRIFT",
               "recommendations": recs}
        if directory is None:
            from jarvis.config.paths import DATA_DIR
            directory = os.path.join(DATA_DIR, "advisories")
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, f"advisories_{day}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
        _LAST_DRIFT_ADVISORY.clear()
        _LAST_DRIFT_ADVISORY[day] = key
        return row
    except Exception:  # monitoring never reaches the trading path
        return None


def run_checks(*, now: float, heartbeat: float, rows: List[Dict[str, Any]], last_send: float,
               verifications: Iterable[Dict[str, Any]], positions: Iterable[Any], equity: float,
               max_portfolio_risk_pct: float, fallbacks: float, evaluations: float, cfg: Any,
               alert: bool = True, position_monitor: Optional[Dict[str, Any]] = None,
               has_position_monitor: bool = True, live_r: Optional[Dict[str, List[float]]] = None,
               profiles: Optional[Dict[str, Any]] = None, quarantine_r: float = -0.15) -> Dict[str, Any]:
    positions = list(positions)
    checks = {
        "loop_heartbeat": check_loop(now, heartbeat, cfg),
        "position_monitor": check_position_monitor(now, position_monitor if has_position_monitor else None,
                                                   len(positions), cfg),
        "no_trade": check_no_trade(now, rows, last_send, cfg),
        "rejection_spike": check_reject_spike(now, rows, cfg),
        "analyst_fallbacks": check_rate("analyst fallbacks per evaluation", fallbacks, evaluations, cfg.fallback_rate_warn),
        "verifier_health": check_verifier(verifications, cfg),
        "forward_test_exposure": check_forward_exposure(positions, equity, max_portfolio_risk_pct, cfg),
        "currency_exposure": check_currency_exposure(positions, equity, max_portfolio_risk_pct),
        "stops_and_gap_risk": check_stops_and_gap(positions, equity, now),
        "live_vs_calibrated": check_live_drift(live_r, profiles, quarantine_r),
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
