"""Versioned, audited snapshots of learned state (learning governance, 2026-11-16).

Live trading reads only the ACTIVE version of each model. Learning keeps running
on a shadow copy; a candidate replaces the active version only through
``register(..., activate=True)`` from tools/promote_model.py, which records the
validation evidence. Every activation and every governor directive is appended
to an audit log, and any earlier version can be re-activated (rollback).

Layout under ``<DATA_DIR>/models/``::

    <name>/registry.json          {"active": "v3", "versions": {...}}
    <name>/v3.json                 the snapshot (read-only on disk)
    audit.jsonl                    append-only event log
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import threading
import time
from typing import Any, Dict, Optional

_LOCK = threading.Lock()


def _root() -> str:
    from jarvis.config.paths import DATA_DIR
    return os.path.join(DATA_DIR, "models")


def _dir(name: str) -> str:
    return os.path.join(_root(), name)


def _reg_path(name: str) -> str:
    return os.path.join(_dir(name), "registry.json")


def _read(name: str) -> Dict[str, Any]:
    try:
        with open(_reg_path(name), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"active": None, "versions": {}}


def _write(name: str, reg: Dict[str, Any]) -> None:
    os.makedirs(_dir(name), exist_ok=True)
    tmp = _reg_path(name) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)
    os.replace(tmp, _reg_path(name))


def audit(event: str, **fields: Any) -> None:
    """Append one event to the audit log. Never raises: auditing must not stop trading."""
    try:
        os.makedirs(_root(), exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}
        with _LOCK, open(os.path.join(_root(), "audit.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass


def register(name: str, src_path: str, reason: str, validation: Optional[Dict[str, Any]] = None,
             activate: bool = False, author: str = "system") -> str:
    """Snapshot ``src_path`` as a new immutable version of ``name``."""
    with _LOCK:
        reg = _read(name)
        version = f"v{len(reg['versions']) + 1}"
        os.makedirs(_dir(name), exist_ok=True)
        dst = os.path.join(_dir(name), f"{version}.json")
        shutil.copyfile(src_path, dst)
        os.chmod(dst, stat.S_IREAD)  # a frozen version is never rewritten in place
        with open(dst, "rb") as f:
            sha = hashlib.sha256(f.read()).hexdigest()[:16]
        reg["versions"][version] = {
            "file": os.path.basename(dst), "sha256": sha, "parent": reg.get("active"),
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": reason, "author": author, "validation": validation or {},
        }
        if activate:
            reg["active"] = version
        _write(name, reg)
    audit("register", model=name, version=version, activated=activate, reason=reason,
          sha256=sha, validation=validation or {})
    return version


def activate(name: str, version: str, reason: str, author: str = "operator") -> None:
    """Make ``version`` live (also the rollback path)."""
    with _LOCK:
        reg = _read(name)
        if version not in reg["versions"]:
            raise KeyError(f"{name} has no version {version}")
        previous = reg.get("active")
        reg["active"] = version
        _write(name, reg)
    audit("activate", model=name, version=version, previous=previous, reason=reason, author=author)


def active_info(name: str) -> Optional[Dict[str, Any]]:
    reg = _read(name)
    v = reg.get("active")
    return {"version": v, **reg["versions"][v]} if v else None


def active_path(name: str, seed_file: Optional[str] = None) -> Optional[str]:
    """Path of the active version; on first use, freeze ``seed_file`` (today's live state) as v1."""
    info = active_info(name)
    if info is None and seed_file and os.path.exists(seed_file):
        register(name, seed_file, reason="bootstrap: froze the state live trading was using", activate=True)
        info = active_info(name)
    return os.path.join(_dir(name), info["file"]) if info else None


def versions(name: str) -> Dict[str, Any]:
    return _read(name)


# ── Governed configuration files (2026-11-25) ───────────────────────────────
# The JSON files that drive live trading (settings, calibrated profiles, devil-gate
# calibration) used to be overwritten in place with no history. A governed write
# freezes the current file as v1 on first use, registers the new content as a new
# immutable version, checks parameter bounds, holds high-impact changes as PENDING
# until approved, and only then replaces the live file atomically. Rollback =
# deploy_version(name, older_version).

def _get_path(doc: Any, dotted: str) -> Any:
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def load_param_bounds(path: Optional[str] = None) -> Dict[str, Any]:
    if path is None:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(base, "config", "param_bounds.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def check_param_bounds(name: str, old: Any, new: Any, bounds: Optional[Dict[str, Any]] = None,
                       max_delta_pct: Optional[float] = None) -> Dict[str, list]:
    """{"violations": [...], "high_impact": [...]} for the bounded keys of ``name``."""
    if bounds is None:
        bounds = load_param_bounds()
    if max_delta_pct is None:
        try:
            from jarvis.config.settings import SETTINGS
            max_delta_pct = float(SETTINGS.governance.max_auto_delta_pct)
        except Exception:
            max_delta_pct = 20.0
    violations, high = [], []
    for key, (lo, hi) in (bounds.get(name) or {}).items():
        nv, ov = _get_path(new, key), _get_path(old, key)
        if nv is None:
            continue
        try:
            nvf = float(nv)
        except (TypeError, ValueError):
            violations.append(f"{key}={nv!r} is not numeric")
            continue
        if not float(lo) <= nvf <= float(hi):
            violations.append(f"{key}={nvf} outside [{lo}, {hi}]")
        if ov is not None:
            try:
                ovf = float(ov)
                if ovf and abs(nvf - ovf) / abs(ovf) * 100.0 > max_delta_pct:
                    high.append(f"{key}: {ovf} -> {nvf} (> {max_delta_pct:g}% change)")
            except (TypeError, ValueError):
                pass
    return {"violations": violations, "high_impact": high}


def _install(src: str, live_path: str) -> None:
    tmp = live_path + ".governed.tmp"
    shutil.copyfile(src, tmp)
    os.chmod(tmp, stat.S_IREAD | stat.S_IWRITE)  # the frozen copy is read-only; the live file is not
    os.replace(tmp, live_path)


def deploy_version(name: str, version: str, live_path: str, reason: str, author: str = "operator") -> None:
    """Install a registered version onto the live file and activate it (approve / rollback)."""
    reg = _read(name)
    if version not in reg["versions"]:
        raise KeyError(f"{name} has no version {version}")
    _install(os.path.join(_dir(name), reg["versions"][version]["file"]), live_path)
    with _LOCK:
        reg = _read(name)
        reg["versions"][version]["status"] = "ACTIVE"
        _write(name, reg)
    activate(name, version, reason=reason, author=author)


def governed_write(name: str, live_path: str, text: str, reason: str, author: str = "system",
                   approve: bool = False, validation: Optional[Dict[str, Any]] = None,
                   extra_high_impact: Optional[list] = None) -> Dict[str, Any]:
    """Version, bound-check and (unless high-impact and unapproved) install ``text`` at ``live_path``.

    Returns {"version", "status": ACTIVE | PENDING}. Raises ValueError on a bounds violation.
    """
    active_path(name, seed_file=live_path)  # bootstrap v1 from today's live file
    try:
        with open(live_path, "r", encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    new = json.loads(text)
    if new == old:  # no change: no new version, no churn (e.g. repeated refits)
        info = active_info(name) or {}
        return {"version": info.get("version"), "status": "UNCHANGED", "high_impact": []}
    chk = check_param_bounds(name, old, new)
    if chk["violations"]:
        audit("governed_refused", model=name, reason=reason, author=author, violations=chk["violations"])
        raise ValueError(f"{name}: parameter bounds violated: {chk['violations']}")
    high = chk["high_impact"] + list(extra_high_impact or [])
    tmp = live_path + ".candidate.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        version = register(name, tmp, reason=reason, validation=validation, activate=False, author=author)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if high and not approve:
        with _LOCK:
            reg = _read(name)
            reg["versions"][version]["status"] = "PENDING"
            reg["versions"][version]["high_impact"] = high
            _write(name, reg)
        audit("pending", model=name, version=version, reason=reason, author=author, high_impact=high)
        try:
            from jarvis.observability.alerting import AlertSeverity, dispatch_alert
            dispatch_alert(title=f"Config change pending approval: {name} {version}",
                           message="; ".join(high), severity=AlertSeverity.WARNING, source="Governance",
                           event_key=f"governed_pending_{name}_{version}", debounce_seconds=60.0)
        except Exception:
            pass
        return {"version": version, "status": "PENDING", "high_impact": high}
    deploy_version(name, version, live_path, reason=reason, author=author)
    return {"version": version, "status": "ACTIVE", "high_impact": high}
