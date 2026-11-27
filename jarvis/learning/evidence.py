"""Governed engine evidence for the deployment gate (PR D, 2026-11-27).

The engine-in-the-loop holdout report (reports/mode_backtest_report.json) decides which
symbol x style cells may trade live (exit_geometry.deployment_refusal). It is a governed model
in jarvis.learning.model_registry under the name ``mode_evidence``: the gate reads only the
ACTIVE version, and a new report reaches it only through ``promote``:

  * tightening (a cell that traded is now refused) applies automatically;
  * loosening (a refused cell would trade, or the evidence was measured on another exit policy)
    is registered PENDING until ``python tools/promote_model.py approve mode_evidence <v>``.

A cell that would newly trade must also pass a stricter bar than the gate's (the promotion
rule): the one-sided 80% lower bound of its holdout expectancy above 0, or DSR >= DSR_BAR, and a
positive train window when it has one. Cells that already trade keep the gate's own rule, so
promotion never silently refuses what trades today. Live drift (system_monitor.check_live_drift
CRITICAL) refuses its cell through ``refuse_cell``, a tightening; every change is a registry
version, so ``promote_model rollback mode_evidence <v>`` restores any earlier one.
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from jarvis.learning import model_registry as reg

logger = logging.getLogger("JARVIS_Evidence")

NAME = "mode_evidence"
LCB_Z = 1.2816   # one-sided 80% normal quantile
DSR_BAR = 0.5
INTEGRITY_PREFIXES = ("EVIDENCE_STALE", "EVIDENCE_MISMATCH")
_ACTIVE: Dict[str, Any] = {"mt": None, "path": None}


def live_path() -> str:
    from jarvis.config.paths import REPO_ROOT
    return os.path.join(REPO_ROOT, "reports", "mode_backtest_report.json")


def active_file() -> Optional[str]:
    """Path of the active evidence version; the first call freezes today's report as v1."""
    rp = reg._reg_path(NAME)
    mt = os.path.getmtime(rp) if os.path.exists(rp) else None
    if mt is None or mt != _ACTIVE["mt"]:
        path = reg.active_path(NAME, seed_file=live_path())
        _ACTIVE.update(mt=os.path.getmtime(rp) if os.path.exists(rp) else None, path=path)
    return _ACTIVE["path"]


def load(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cells(payload: Optional[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(SYMBOL, STYLE): per-symbol row} of a report (rows are the payload's own dicts)."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for mode in (payload or {}).get("modes", []) or []:
        st = str(mode.get("style") or "").upper()
        for r in mode.get("per_symbol", []) or []:
            out[(str(r.get("symbol") or "").upper(), st)] = r
    return out


def _exit_policy(payload: Dict[str, Any]) -> Tuple[str, Optional[List[str]]]:
    mode = str(payload.get("exit_mode") or "default").lower()
    hold = payload.get("exit_hold_symbols")
    return ("legacy" if mode in ("default", "") else mode,
            sorted(str(s).upper() for s in hold) if isinstance(hold, list) else None)


def _exit_cells(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """The per-cell exit modes a report was measured with (trading.exit_cells), or None for a
    report from before they were recorded."""
    cells = (payload or {}).get("exit_cells")
    return {str(k).upper(): str(v).lower() for k, v in cells.items()} if isinstance(cells, dict) else None


def holdout_end(payload: Optional[Dict[str, Any]]) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat(str((payload or {}).get("holdout_window", "")).split("..")[1][:10])
    except (IndexError, ValueError):
        return None


def integrity_refusal(payload: Optional[Dict[str, Any]], today: Optional[_dt.date] = None) -> Optional[str]:
    """Why the whole report may not be trusted live, or None: measured on another exit policy
    than live trades (EVIDENCE_MISMATCH), or a holdout that ended too long ago (EVIDENCE_STALE)."""
    if not payload or not payload.get("holdout_window"):
        return None
    from jarvis.config.settings import SETTINGS
    mode, hold = _exit_policy(payload)
    live_mode = str(getattr(SETTINGS.trading, "exit_mode", "legacy") or "legacy").lower()
    live_hold = sorted(str(s).upper() for s in (getattr(SETTINGS.trading, "exit_hold_symbols", None) or []))
    if mode != live_mode or (hold is not None and hold != live_hold):
        return (f"EVIDENCE_MISMATCH: evidence measured on exit {mode} hold={hold}, live trades exit {live_mode} "
                f"hold={live_hold}; revalidate on the live exit policy")
    cells = _exit_cells(payload)
    live_cells = {str(k).upper(): str(v).lower() for k, v in (getattr(SETTINGS.trading, "exit_cells", None) or {}).items()}
    if (cells or {}) != live_cells:  # an older report (None) can only vouch for no per-cell exits
        return (f"EVIDENCE_MISMATCH: evidence measured with exit_cells={cells}, live trades exit_cells={live_cells}; "
                f"approve the matching evidence version or revalidate")
    end = holdout_end(payload)
    max_age = float(getattr(SETTINGS.gates, "evidence_max_age_days", 35.0) or 35.0)
    age = ((today or _dt.datetime.now(_dt.timezone.utc).date()) - end).days if end else None
    if age is None or age > max_age:
        return (f"EVIDENCE_STALE: holdout {payload.get('holdout_window')} ended {age} days ago "
                f"(max {max_age:g}); run tools/revalidate.py")
    return None


def _gate(key: Tuple[str, str], row: Optional[Dict[str, Any]]) -> Optional[str]:
    from jarvis.backtesting.exit_geometry import _hurdle, cell_refusal
    return cell_refusal(key[0], key[1], row, *_hurdle(key[0]))


def strict_refusal(row: Dict[str, Any]) -> Optional[str]:
    """The promotion rule for a cell that would newly trade, or None when it passes."""
    lcb, dsr = row.get("lcb80_r"), row.get("dsr")
    if not ((lcb is not None and float(lcb) > 0.0) or (dsr is not None and float(dsr) >= DSR_BAR)):
        return (f"PROMOTION_RULE: {row.get('symbol')} needs an 80% lower bound > 0R (has {lcb}) "
                f"or DSR >= {DSR_BAR} (has {dsr}) before it may start trading")
    te = row.get("train_expectancy_r")
    if te is not None and float(te) <= 0.0:
        return f"PROMOTION_RULE: {row.get('symbol')} train window {float(te):+.3f}R is not positive"
    return None


def plan(active: Optional[Dict[str, Any]], candidate: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    """(candidate with the promotion rule applied, {"tighten", "loosen", "exit_policy"})."""
    cand = copy.deepcopy(candidate)
    a_cells, c_cells = cells(active), cells(cand)
    tighten, loosen = [], []
    for key in sorted(set(a_cells) | set(c_cells)):
        was = key in a_cells and _gate(key, a_cells[key]) is None
        row = c_cells.get(key)
        now = row is not None and _gate(key, row) is None
        if now and not was:
            why = strict_refusal(row)
            if why:
                row["refused"] = why            # stays refused: no change to live trading
            else:
                loosen.append(f"{key[0]} {key[1]} starts trading: {float(row.get('expectancy_r') or 0):+.3f}R over "
                              f"{row.get('trades')} (lcb80 {row.get('lcb80_r')}, dsr {row.get('dsr')})")
        elif was and not now:
            tighten.append(f"{key[0]} {key[1]} stops: {_gate(key, row)}")
    policy = []
    (am, ah), (cm, ch) = _exit_policy(active or {}), _exit_policy(cand)
    # A report from before exit_hold_symbols was recorded (None) replayed the same settings file.
    if active and (am != cm or (ah is not None and ch is not None and ah != ch)):
        policy.append(f"exit policy {(am, ah)} -> {(cm, ch)}")
    if active and (_exit_cells(active) or {}) != (_exit_cells(cand) or {}):
        policy.append(f"exit_cells {_exit_cells(active) or {}} -> {_exit_cells(cand) or {}}")
    return cand, {"tighten": tighten, "loosen": loosen, "exit_policy": policy}


def _write(payload: Dict[str, Any], reason: str, author: str, validation: Dict[str, Any],
           high: List[str], approve: bool = False) -> Dict[str, Any]:
    res = reg.governed_write(NAME, live_path(), json.dumps(payload, indent=2, default=str), reason=reason,
                             author=author, approve=approve, validation=validation, extra_high_impact=high)
    _ACTIVE["mt"] = None
    return res


def promote(candidate_path: str, reason: str, author: str = "revalidate") -> Dict[str, Any]:
    """Promote a candidate report: tightening applies now, loosening waits PENDING for approval."""
    cand = load(candidate_path) or {}
    if not cand.get("holdout_window"):
        raise ValueError(f"{candidate_path} is not a holdout report (no holdout_window)")
    active = load(active_file())
    scope = cand.get("scope")
    if scope and active:
        # A run over some symbols/styles says nothing about the rest: it must not refuse them.
        uncovered = sorted(f"{s}|{t}" for s, t in cells(active)
                           if s not in scope.get("symbols", []) or t not in scope.get("styles", []))
        if uncovered:
            raise ValueError(f"partial revalidation does not cover {len(uncovered)} active cell(s), "
                             f"e.g. {uncovered[:3]}; run every symbol x style to promote")
    cand, changes = plan(active, cand)
    high = changes["loosen"] + changes["exit_policy"]
    out: Dict[str, Any] = {"changes": changes}
    if high and changes["tighten"] and active:
        # A version that is all-or-nothing PENDING would hold the tightening back: apply it alone first.
        tight = copy.deepcopy(active)
        c_cells = cells(cand)
        for key, row in cells(tight).items():
            if _gate(key, row) is None and _gate(key, c_cells.get(key)) is not None:
                row["refused"] = f"REVALIDATION: {_gate(key, c_cells.get(key))}"
        out["tightened"] = _write(tight, f"{reason} (tightening only)", author,
                                  {"tighten": changes["tighten"], "source": candidate_path}, [])
    out["result"] = _write(cand, reason, author, {**changes, "source": candidate_path}, high)
    return out


def refuse_cell(symbol: str, style: str, reason: str, author: str = "drift_monitor") -> Optional[Dict[str, Any]]:
    """Refuse one cell in a new active version (a tightening: no approval). None when the cell has
    no evidence row or is already refused."""
    active = load(active_file())
    if not active:
        return None
    new = copy.deepcopy(active)
    row = cells(new).get((str(symbol).upper(), str(style).upper()))
    if row is None or row.get("refused"):
        return None
    row["refused"] = reason
    res = _write(new, f"refuse {symbol} {style}: {reason}", author, {"tighten": [reason]}, [])
    try:
        from jarvis.observability.alerting import AlertSeverity, dispatch_alert
        dispatch_alert(title=f"Deployment: {symbol} {style} refused", message=reason,
                       severity=AlertSeverity.CRITICAL, source="Evidence",
                       event_key=f"evidence_refuse_{symbol}_{style}", debounce_seconds=0.0)
    except Exception:
        pass
    logger.warning("evidence %s: %s %s refused (%s)", res.get("version"), symbol, style, reason)
    return res


def refuse_drifting_cells(monitor_state: Dict[str, Any]) -> List[str]:
    """Refuse every cell the drift check judged CRITICAL against its engine evidence."""
    c = ((monitor_state or {}).get("checks") or {}).get("live_vs_calibrated") or {}
    done = []
    for key, v in (c.get("symbols") or {}).items():
        if v.get("status") != "CRITICAL" or v.get("benchmark") != "engine_holdout" or "|" not in key:
            continue
        sym, st = key.split("|", 1)
        why = (f"LIVE_DRIFT: {sym} {st} live {v['live_r']:+.3f}R over {v['n']} closes vs holdout "
               f"{v['oos_r']:+.3f}R (more than 2 SE below, under the quarantine bar)")
        if refuse_cell(sym, st, why):
            done.append(key)
    return done


def status() -> Dict[str, Any]:
    """Facts for the monitor's evidence check."""
    info = reg.active_info(NAME) or {}
    payload = load(active_file())
    end = holdout_end(payload)
    pending = [v for v, m in reg.versions(NAME).get("versions", {}).items() if m.get("status") == "PENDING"]
    live_differs = False
    try:
        import hashlib
        with open(live_path(), "rb") as f:
            live_differs = bool(info.get("sha256")) and hashlib.sha256(f.read()).hexdigest()[:16] != info["sha256"]
    except OSError:
        pass
    return {"version": info.get("version"), "holdout_window": (payload or {}).get("holdout_window"),
            "age_days": (_dt.datetime.now(_dt.timezone.utc).date() - end).days if end else None,
            "integrity": integrity_refusal(payload), "pending": pending, "live_differs": live_differs,
            "refused_cells": sorted(f"{k[0]}|{k[1]}" for k, r in cells(payload).items() if r.get("refused"))}


# ── Per-cell exits (exit audit 2026-11-27): approval needs the shadow forward test ─────────
_NO_SHADOW_NEEDED = ("institutional_lock", "hold")     # the measured live policies


def shadow_failures(changed: Dict[str, str], db_path: Optional[str] = None) -> List[str]:
    """Why each changed cell's new exit mode has not passed its live shadow, or [] when all have:
    >= SHADOW_MIN_CLOSES complete demo/live shadow closes in that cell, mean shadow R >= mean real R."""
    import sqlite3
    from jarvis.data.symbol_registry import resolve
    from jarvis.execution.exit_shadow import SHADOW_MIN_CLOSES, SHADOW_MODES
    from jarvis.execution.exit_policy import _STYLE_ALIASES
    bad = []
    rows = None
    for key, mode in sorted(changed.items()):
        if mode in _NO_SHADOW_NEEDED:
            continue
        if mode not in SHADOW_MODES:
            bad.append(f"{key} -> {mode}: no live shadow exists for this mode (only {SHADOW_MODES} are shadowed)")
            continue
        if rows is None:
            if db_path is None:
                from jarvis.config.paths import resolve_db_path
                db_path = resolve_db_path("jarvis_history.db")
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                rows = con.execute("SELECT symbol, trade_style, mode, shadow_r, actual_r FROM shadow_exits "
                                   "WHERE complete = 1 AND lower(COALESCE(execution_mode, '')) IN ('demo', 'live')").fetchall()
            except sqlite3.OperationalError:
                rows = []
            finally:
                con.close()
        who, st = key.split("|", 1)
        sel = [(s, a) for sym, sty, m, s, a in rows if m == mode
               and _STYLE_ALIASES.get(str(sty or "").upper(), str(sty or "").upper()) == st
               and who in (str(resolve(sym).canonical).upper(), str(resolve(sym).asset_class).upper())]
        n = len(sel)
        ms, ma = (sum(s for s, _ in sel) / n, sum(a for _, a in sel) / n) if n else (None, None)
        if n < SHADOW_MIN_CLOSES or ms < ma:
            bad.append(f"{key} -> {mode}: {n} shadow closes (needs {SHADOW_MIN_CLOSES})"
                       + (f", shadow {ms:+.3f}R vs real {ma:+.3f}R" if n else ""))
    return bad


def install(version: str, reason: str, author: str = "operator", require_shadow: bool = True) -> Dict[str, Any]:
    """Make evidence `version` active together with the per-cell exits it was measured with
    (settings trading.exit_cells, a governed write). Approval requires the shadow forward test for
    every changed cell; a rollback (require_shadow=False) restores an earlier, already-approved pair.
    Between the two writes the gate sees a mismatch and refuses: it never trades a pair it has not."""
    from jarvis.config.settings import SETTINGS, _LIVE_SETTINGS_PATH
    meta = reg.versions(NAME).get("versions", {}).get(version)
    if not meta:
        raise KeyError(f"{NAME} has no version {version}")
    new_cells = _exit_cells(load(os.path.join(reg._dir(NAME), meta["file"]))) or {}
    live_cells = {str(k).upper(): str(v).lower() for k, v in (SETTINGS.trading.exit_cells or {}).items()}
    changed = {k: v for k, v in new_cells.items() if live_cells.get(k) != v}
    if require_shadow:
        bad = shadow_failures(changed)
        if bad:
            reg.audit("evidence_approval_refused", model=NAME, version=version, reasons=bad)
            raise ValueError("shadow forward test not passed: " + "; ".join(bad))
    if new_cells != live_cells:
        with open(_LIVE_SETTINGS_PATH, "r", encoding="utf-8") as f:
            doc = json.load(f)
        doc.setdefault("trading", {})["exit_cells"] = new_cells
        reg.governed_write("settings", _LIVE_SETTINGS_PATH, json.dumps(doc, indent=2), reason=f"{reason} ({NAME} {version})",
                           author=author, approve=True, validation={"exit_cells": new_cells})
        SETTINGS.trading.exit_cells = dict(new_cells)
    reg.deploy_version(NAME, version, live_path(), reason=reason, author=author)
    _ACTIVE["mt"] = None
    return {"version": version, "exit_cells": new_cells, "changed": changed}
