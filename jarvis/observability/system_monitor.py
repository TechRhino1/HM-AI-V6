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
    # A tick that fails every time still "completes": judge the last GOOD tick and the current
    # error streak, not the lifetime error count (one error used to mean WARN until restart).
    streak = int(status.get("consecutive_tick_errors") or 0)
    ok_at = float(status.get("last_ok_at") or last)
    ok_age = now - ok_at if ok_at else None
    if ok_age is not None and ok_age > cfg.position_monitor_stall_s and streak:
        return {"status": CRITICAL, "value": round(ok_age, 1), "threshold": cfg.position_monitor_stall_s,
                "detail": f"position monitor ticks are all failing ({streak} in a row, last good {ok_age:.0f}s ago): "
                          f"{status.get('last_tick_error')}"}
    return {"status": WARN if streak >= 3 else OK, "value": round(age, 1), "threshold": cfg.position_monitor_stall_s,
            "detail": f"last tick {age:.0f}s ago; {streak} consecutive tick error(s)"
                      + (f" (last: {status.get('last_tick_error')})" if streak else "")}


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


class Window:
    """Trailing-window delta of a monotonically increasing total (metrics Counters are lifetime
    totals, so a spike at start-up diluted forever and a fresh spike was averaged away)."""

    def __init__(self) -> None:
        self._pts: Dict[str, List[tuple]] = {}

    def delta(self, key: str, now: float, total: float, span: float) -> float:
        # Every total is a process-lifetime counter that started at 0, so a key seen for the first
        # time counts everything so far (the monitor's first pass is ~60 s after start).
        pts = self._pts.setdefault(key, [(now, 0.0)])
        pts.append((now, float(total)))
        while len(pts) > 2 and pts[1][0] <= now - span:
            pts.pop(0)
        return max(0.0, pts[-1][1] - pts[0][1])


WINDOW = Window()


def counter_by(counter: Any, label: str) -> Dict[str, float]:
    """Totals of a metrics Counter grouped by one label value."""
    out: Dict[str, float] = {}
    try:
        for smp in counter.samples():
            k = str(smp["labels"].get(label, ""))
            out[k] = out.get(k, 0.0) + float(smp["value"])
    except Exception:
        pass
    return out


def check_share(name: str, now: float, bad_total: float, all_total: float, warn_at: float, span: float,
                min_events: int = 20) -> Dict[str, Any]:
    """Share of `bad` events among all events in the trailing window."""
    bad = WINDOW.delta(name + ":bad", now, bad_total, span)
    tot = WINDOW.delta(name + ":all", now, all_total, span)
    share = bad / tot if tot > 0 else 0.0
    return {"status": WARN if tot >= min_events and share > warn_at else OK, "value": round(share, 3),
            "threshold": warn_at, "detail": f"{name}: {int(bad)}/{int(tot)} in the last {span / 60:.0f} min"}


def check_windowed_rate(name: str, now: float, num_total: float, den_total: float, warn_at: float,
                        span: float) -> Dict[str, Any]:
    num = WINDOW.delta(name + ":num", now, num_total, span)
    den = WINDOW.delta(name + ":den", now, den_total, span)
    return check_rate(f"{name} (last {span / 60:.0f} min)", num, den, warn_at)


def check_state_sync(now: float, last_ok_at: Optional[float], cfg: Any) -> Dict[str, Any]:
    if not last_ok_at:
        return {"status": WARN, "value": None, "threshold": cfg.state_sync_stall_s,
                "detail": "broker state sync has not completed a pass yet"}
    age = now - float(last_ok_at)
    return {"status": CRITICAL if age > cfg.state_sync_stall_s else OK, "value": round(age, 1),
            "threshold": cfg.state_sync_stall_s,
            "detail": f"last successful broker sync {age:.0f}s ago (account and positions are this old)"}


def check_symbol_feeds(symbols: Optional[Dict[str, Dict[str, Any]]], cfg: Any) -> Dict[str, Any]:
    """Per-symbol market data: STALE while quoting, or SYNTHETIC, is a symbol the engine cannot trade."""
    if not symbols:
        return {"status": OK, "value": 0, "threshold": cfg.stale_symbols_warn, "detail": "no fetches yet", "symbols": {}}
    bad = {s: h["status"] for s, h in symbols.items() if h.get("status") in ("STALE", "SYNTHETIC")}
    return {"status": WARN if len(bad) >= cfg.stale_symbols_warn else OK, "value": len(bad),
            "threshold": cfg.stale_symbols_warn,
            "detail": ("untradeable feeds: " + ", ".join(f"{s} {st}" for s, st in sorted(bad.items())))
            if bad else f"{len(symbols)} symbol feed(s) healthy or closed",
            "symbols": {s: h.get("status") for s, h in symbols.items()}}


def check_timeouts(guard: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not guard or "error" in guard:
        return {"status": WARN, "value": None, "threshold": None, "detail": "timeout guard health unavailable"}
    stuck = int(guard.get("stuck_workers") or guard.get("stuck") or 0)
    wedged = bool(guard.get("wedged"))
    return {"status": CRITICAL if wedged else (WARN if stuck else OK), "value": stuck, "threshold": None,
            "detail": "worker pool wedged (calls cannot be scheduled)" if wedged
            else f"{stuck} worker(s) stuck in calls that could not be cancelled"}


def check_risk_guards(halted: Optional[str], breaker: Optional[str], daily_pnl: float, peak: float,
                      daily_limit_pct: float = 4.0) -> Dict[str, Any]:
    """Drawdown halt, circuit breaker, and distance to the daily-loss lockout."""
    used = (-daily_pnl / peak * 100.0) if peak > 0 and daily_pnl < 0 else 0.0
    parts = []
    if halted:
        parts.append(f"drawdown halt: {halted}")
    if breaker:
        parts.append(f"circuit breaker: {breaker}")
    parts.append(f"daily loss {used:.2f}% of the {daily_limit_pct:g}% lockout")
    st = WARN if (halted or breaker or used >= 0.75 * daily_limit_pct) else OK
    return {"status": st, "value": round(used, 2), "threshold": daily_limit_pct, "detail": "; ".join(parts)}


def check_overrides(rows: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Operator deployment overrides on probation: how close each is to its stop."""
    if not rows:
        return {"status": OK, "value": 0, "threshold": None, "detail": "no deployment overrides", "overrides": []}
    stopped = [r for r in rows if r.get("stopped")]
    near = [r for r in rows if not r.get("stopped") and r.get("n", 0) >= 0.5 * r.get("stop_after", 30)
            and r.get("r", 0.0) < r.get("stop_below", -0.1)]
    detail = "; ".join(f"{r['symbol']} {r['style']}: {r['r']:+.3f}R over {r['n']}/{r['stop_after']}"
                       + (" STOPPED" if r.get("stopped") else "") for r in rows)
    return {"status": WARN if (stopped or near) else OK, "value": len(stopped), "threshold": None,
            "detail": detail, "overrides": rows}


def check_resources(cpu_pct: Optional[float], mem_pct: Optional[float], disk_free_gb: Optional[float],
                    data_gb: Optional[float], cfg: Any, threads: Optional[int] = None,
                    handles: Optional[int] = None) -> Dict[str, Any]:
    bad = []
    if threads is not None and threads > getattr(cfg, "threads_warn", 400):
        bad.append(f"{threads} threads (leak?)")
    if handles is not None and handles > getattr(cfg, "handles_warn", 20000):
        bad.append(f"{handles} handles (leak?)")
    if cpu_pct is not None and cpu_pct > cfg.cpu_warn_pct:
        bad.append(f"CPU {cpu_pct:.0f}%")
    if mem_pct is not None and mem_pct > cfg.memory_warn_pct:
        bad.append(f"memory {mem_pct:.0f}%")
    if disk_free_gb is not None and disk_free_gb < cfg.disk_free_warn_gb:
        bad.append(f"disk free {disk_free_gb:.1f} GB")
    if data_gb is not None and data_gb > cfg.data_dir_warn_gb:
        bad.append(f"data/ {data_gb:.1f} GB")
    crit = disk_free_gb is not None and disk_free_gb < 1.0
    return {"status": CRITICAL if crit else (WARN if bad else OK), "value": None, "threshold": None,
            "detail": ", ".join(bad) if bad else
            f"CPU {cpu_pct or 0:.0f}%, memory {mem_pct or 0:.0f}%, disk free {disk_free_gb or 0:.1f} GB, "
            f"data/ {data_gb or 0:.2f} GB, threads {threads if threads is not None else '?'}, "
            f"handles {handles if handles is not None else '?'}"}


def check_events(name: str, now: float, total: float, span: float, warn_at: int = 1,
                 what: str = "events") -> Dict[str, Any]:
    """Count of a failure event in the trailing window (spec fallbacks, broker-lock busy)."""
    n = WINDOW.delta(name, now, total, span)
    return {"status": WARN if n >= warn_at else OK, "value": int(n), "threshold": warn_at,
            "detail": f"{int(n)} {what} in the last {span / 60:.0f} min"}


def hist_p95(name: str, now: float, hist: Any, span: float) -> Optional[float]:
    """p95 (upper bucket edge, seconds) of a metrics Histogram over the trailing window; None
    without observations. All label series are pooled."""
    cum: Dict[str, float] = {}
    try:
        for smp in hist.samples():
            if smp.get("suffix") == "_bucket":
                le = str(smp["labels"].get("le"))
                cum[le] = cum.get(le, 0.0) + float(smp["value"])
    except Exception:
        return None
    if not cum:
        return None
    deltas = {le: WINDOW.delta(f"{name}:le={le}", now, v, span) for le, v in cum.items()}
    total = deltas.get("+Inf", 0.0)
    if total <= 0:
        return None
    for le in sorted((k for k in deltas if k != "+Inf"), key=float):
        if deltas[le] >= 0.95 * total:
            return float(le)
    return float("inf")


def check_latency(p95s: Dict[str, Optional[float]], limits: Dict[str, float]) -> Dict[str, Any]:
    slow = {k: v for k, v in p95s.items() if v is not None and v > limits.get(k, float("inf"))}
    shown = ", ".join(f"{k} {'>' + str(limits[k]) if v == float('inf') else f'{v:g}'}s" for k, v in p95s.items()
                      if v is not None) or "no observations yet"
    return {"status": WARN if slow else OK, "value": None, "threshold": limits,
            "detail": ("slow p95: " + ", ".join(f"{k} > {limits[k]:g}s" for k in slow) + "; ") * bool(slow)
            + f"p95 {shown}", "p95": p95s}


def check_account(acct: Any, mode: str) -> Dict[str, Any]:
    """The broker account a live/demo engine trades on: logged in and allowed to trade."""
    if str(mode).lower() in ("paper", "offline", "backtest"):
        return {"status": OK, "value": None, "threshold": None, "detail": f"{mode}: simulated account"}
    login = int(getattr(acct, "login", 0) or 0)
    if not login:
        return {"status": CRITICAL, "value": None, "threshold": None,
                "detail": "no broker account: MT5 not logged in or disconnected"}
    if not bool(getattr(acct, "trade_allowed", False)):
        return {"status": CRITICAL, "value": login, "threshold": None,
                "detail": f"account #{login} is logged in but trading is NOT allowed (terminal/broker setting)"}
    return {"status": OK, "value": login, "threshold": None, "detail": f"account #{login} connected, trading allowed"}


def check_quarantine(current: Iterable[str], previous: Optional[Iterable[str]]) -> Dict[str, Any]:
    """Strategy quarantine changes since the last pass (it blocks pairs automatically, silently)."""
    cur = set(current or [])
    prev = set(previous) if previous is not None else cur
    added, removed = sorted(cur - prev), sorted(prev - cur)
    parts = ([f"newly quarantined: {', '.join(added)}"] if added else []) + (
        [f"released: {', '.join(removed)}"] if removed else [])
    return {"status": WARN if added else OK, "value": len(cur), "threshold": None,
            "detail": "; ".join(parts) or f"{len(cur)} symbol x strategy pair(s) quarantined, unchanged",
            "quarantined": sorted(cur)}


def check_auto_style(streaks: Optional[Dict[str, int]], warn_after: int) -> Dict[str, Any]:
    """AUTO skipping a symbol sweep after sweep because every gate-allowed style is unaffordable."""
    bad = {s: n for s, n in (streaks or {}).items() if n >= warn_after}
    return {"status": WARN if bad else OK, "value": max(bad.values(), default=0), "threshold": warn_after,
            "detail": ("no affordable allowed style for " + ", ".join(f"{s} ({n} sweeps)" for s, n in sorted(bad.items())))
            if bad else "every allowed symbol had an affordable style recently"}


def check_gate_spikes(now: float, rows: List[Dict[str, Any]], factor: float, min_count: int = 10) -> Dict[str, Any]:
    """Per-gate rejections in the last 30 min against that gate's 24 h average (the total-rate
    check misses one gate suddenly blocking everything while another quietens)."""
    last30: Dict[str, int] = {}
    day: Dict[str, int] = {}
    for r in rows:
        g = r.get("blocked_by")
        if not g:
            continue
        age = now - _ts(r)
        if age <= 86400:
            day[g] = day.get(g, 0) + 1
            if age <= 1800:
                last30[g] = last30.get(g, 0) + 1
    spikes = {g: n for g, n in last30.items() if n >= min_count and n > factor * max(1.0, day.get(g, 0) / 48.0)}
    top = ", ".join(f"{g} x{n}" for g, n in sorted(last30.items(), key=lambda kv: -kv[1])[:5]) or "none"
    return {"status": WARN if spikes else OK, "value": len(spikes), "threshold": factor,
            "detail": ("spiking: " + ", ".join(f"{g} x{n}" for g, n in spikes.items()) + "; ") * bool(spikes)
            + f"last 30 min top blockers: {top}", "last_30min": last30}


def check_databases(sizes: Dict[str, Dict[str, float]], wal_warn_mb: float = 64.0) -> Dict[str, Any]:
    """Trade DB and WAL sizes (a WAL that keeps growing means checkpoints are not happening)."""
    big = {db: v for db, v in sizes.items() if v.get("wal_mb", 0.0) > wal_warn_mb}
    return {"status": WARN if big else OK, "value": None, "threshold": wal_warn_mb,
            "detail": ", ".join(f"{db} {v['db_mb']:.1f} MB (WAL {v.get('wal_mb', 0.0):.1f} MB)" for db, v in sizes.items())
            or "no databases found", "sizes": sizes}


def check_unmanaged(positions: Iterable[Any], monitor_running: bool) -> Dict[str, Any]:
    """Open bot positions while the position monitor is not running: nothing trails, locks or
    closes them. Forward-test positions are managed by their own routers (comment FT_), manual
    trades by the operator, so neither counts. (The monitor fills its symbol cache lazily, so a
    per-symbol test would false-alarm after every start.)"""
    from jarvis.risk.exposure import is_forward_test
    bot = [f"#{p.ticket} {p.symbol}" for p in positions
           if not is_forward_test(p) and str(getattr(p, "comment", "") or "").upper().startswith(("HMA", "JARVIS"))]
    out = bot if not monitor_running else []
    return {"status": CRITICAL if out else OK, "value": len(out), "threshold": None,
            "detail": ("bot positions with NO position monitor running: " + ", ".join(out)) if out
            else f"{len(bot)} bot position(s), managed by the position monitor; forward tests by their routers"}


_ALERT_STATE: Dict[str, Dict[str, Any]] = {}


def _alert_transitions(now: float, checks: Dict[str, Dict[str, Any]], cfg: Any) -> None:
    """Alert on a status change, a recovery, an escalation, and at most every repeat_alert_s for a
    problem that persists unchanged (the old 30-min debounce re-sent the same WARN forever)."""
    from jarvis.observability.alerting import AlertSeverity, dispatch_alert
    esc_after = int(getattr(cfg, "escalate_after_passes", 30) or 30)
    repeat_s = float(getattr(cfg, "repeat_alert_s", 21600.0) or 21600.0)
    for name, c in checks.items():
        st = c.get("status", OK)
        prev = _ALERT_STATE.get(name, {"status": OK, "passes": 0, "alerted_at": 0.0, "alerted_status": OK})
        passes = prev["passes"] + 1 if (st != OK and st == prev["status"]) else (1 if st != OK else 0)
        effective = CRITICAL if (st == WARN and passes >= esc_after) else st
        if effective != st:
            c["escalated"] = True
        send, sev, title = False, None, None
        if effective == OK and prev["alerted_status"] != OK:
            send, sev, title = True, AlertSeverity.INFO, f"Monitor: {name} recovered"
        elif effective != OK and (effective != prev["alerted_status"] or now - prev["alerted_at"] >= repeat_s):
            send = True
            sev = AlertSeverity.CRITICAL if effective == CRITICAL else AlertSeverity.WARNING
            title = f"Monitor: {name} {effective}" + (" (escalated: persistent)" if c.get("escalated") else "")
        if send:
            dispatch_alert(title=title, message=c.get("detail", ""), severity=sev, source="SystemMonitor",
                           details={k: v for k, v in c.items() if k != "detail"},
                           event_key=f"monitor_{name}_{effective}", debounce_seconds=0.0)
            prev = dict(prev, alerted_at=now, alerted_status=effective)
        _ALERT_STATE[name] = dict(prev, status=st, passes=passes)


def run_checks(*, now: float, heartbeat: float, rows: List[Dict[str, Any]], last_send: float,
               verifications: Iterable[Dict[str, Any]], positions: Iterable[Any], equity: float,
               max_portfolio_risk_pct: float, fallbacks: float, evaluations: float, cfg: Any,
               alert: bool = True, position_monitor: Optional[Dict[str, Any]] = None,
               has_position_monitor: bool = True, live_r: Optional[Dict[str, List[float]]] = None,
               profiles: Optional[Dict[str, Any]] = None, quarantine_r: float = -0.15,
               extra_checks: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    positions = list(positions)
    checks = {
        "loop_heartbeat": check_loop(now, heartbeat, cfg),
        "position_monitor": check_position_monitor(now, position_monitor if has_position_monitor else None,
                                                   len(positions), cfg),
        "no_trade": check_no_trade(now, rows, last_send, cfg),
        "rejection_spike": check_reject_spike(now, rows, cfg),
        "analyst_fallbacks": check_windowed_rate("analyst fallbacks per evaluation", now, fallbacks, evaluations,
                                                 cfg.fallback_rate_warn, float(getattr(cfg, "window_s", 1800.0))),
        "verifier_health": check_verifier(verifications, cfg),
        "forward_test_exposure": check_forward_exposure(positions, equity, max_portfolio_risk_pct, cfg),
        "currency_exposure": check_currency_exposure(positions, equity, max_portfolio_risk_pct),
        "stops_and_gap_risk": check_stops_and_gap(positions, equity, now),
        "live_vs_calibrated": check_live_drift(live_r, profiles, quarantine_r),
    }
    checks.update(extra_checks or {})
    worst = CRITICAL if any(c["status"] == CRITICAL for c in checks.values()) else (
        WARN if any(c["status"] == WARN for c in checks.values()) else OK)
    if alert:
        try:
            _alert_transitions(now, checks, cfg)
        except Exception:
            pass
        if any(c.get("escalated") for c in checks.values()):
            worst = CRITICAL
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
