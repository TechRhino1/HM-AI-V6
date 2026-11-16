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
