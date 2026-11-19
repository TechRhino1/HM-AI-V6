"""Walk-forward calibration of the Devil's Advocate gate (written by tools/calibrate_devil_gate.py).

`config/devil_gate_calibration.json` holds, per symbol group, per-flag historical stats and an
L2-logistic P(loss | flags). The decision engine uses the calibrated threshold only for a group
whose entry is `published: true` (it beat the hand-weighted gate out-of-sample); otherwise the
original penalty/threat-count rule stands unchanged.
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("JARVIS_DevilCalibration")

PATH = Path(__file__).resolve().parents[2] / "config" / "devil_gate_calibration.json"

# Stable ids, one per threat check in DevilAdvocateAnalyst.critique_opportunity.
FLAG_IDS = (
    "trend_against", "rsi_overextended", "adx_strong_counter", "adverse_divergence", "unfavorable_zone",
    "trend_broken", "htf_conflict", "unswept_equal_levels", "adverse_sweep", "liquidity_imbalance",
    "absorption_trap", "adverse_delta", "excessive_spread", "extreme_volatility", "off_hours",
    "regime_transition", "low_regime_confidence", "correlated_conflict", "structural_collision",
    "dynamic_level_collision",
)

_cache: Dict[str, Any] = {"mtime": None, "doc": None, "path": None}


def group_for(symbol: str) -> Optional[str]:
    try:
        from jarvis.data.symbol_registry import resolve
        spec = resolve(symbol)
        canon = str(getattr(spec, "canonical", symbol)).upper()
        if getattr(spec, "is_crypto", False):
            return "crypto"
    except Exception:  # noqa: BLE001
        canon = str(symbol).upper()
    if canon.startswith(("XAU", "GOLD")):
        return "gold"
    if len(canon) == 6 and canon.isalpha():
        return "forex"
    return None


def load(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The calibration document (re-read when the file changes), or None."""
    p = Path(path or PATH)
    try:
        m = os.path.getmtime(p)
    except OSError:
        return None
    if _cache["path"] != str(p) or _cache["mtime"] != m:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("unreadable devil gate calibration %s: %s", p, exc)
            doc = None
        _cache.update(path=str(p), mtime=m, doc=doc)
    return _cache["doc"]


def _group_entry(symbol: str, doc: Optional[Dict[str, Any]]) -> tuple:
    g = group_for(symbol)
    groups = (doc or {}).get("groups") or {}
    return g, groups.get(g) if g else None, groups.get("pooled")


def threat_stats(symbol: str, flags: List[str], doc: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Historical stats for each fired flag (group stats, else pooled): [{flag, n, win_rate_delta, mean_r_delta}]."""
    doc = doc if doc is not None else load()
    _, entry, pooled = _group_entry(symbol, doc)
    src = entry or pooled
    if not src or not flags:
        return []
    by_flag = {s["flag"]: s for s in src.get("flag_stats") or []}
    out = []
    for f in flags:
        s = by_flag.get(f)
        if s and "win_rate_delta" in s:
            out.append({"flag": f, "n": s["n"], "win_rate_delta": s["win_rate_delta"],
                        "mean_r_delta": s["mean_r_delta"], "t_stat": s.get("t_stat")})
    return out


def published_model(symbol: str, doc: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    doc = doc if doc is not None else load()
    if not doc or not doc.get("published"):
        return None
    _, entry, _ = _group_entry(symbol, doc)
    return entry if entry and entry.get("published") else None


def loss_prob(model: Dict[str, Any], flags: List[str]) -> float:
    z = float(model["intercept"]) + sum(float(model["weights"].get(f, 0.0)) for f in set(flags))
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def annotate(report: Any, symbol: str) -> None:
    """Attach threat_stats always; calibrated_loss_prob/group only under a published calibration."""
    try:
        doc = load()
        report.threat_stats = threat_stats(symbol, report.threat_flags, doc)
        model = published_model(symbol, doc)
        if model is not None:
            report.calibrated_loss_prob = round(loss_prob(model, report.threat_flags), 4)
            report.calibration_group = group_for(symbol)
    except Exception as exc:  # noqa: BLE001 - annotation must never break the critic
        logger.warning("devil calibration annotate failed for %s: %s", symbol, exc)


def gate_passes(report: Any, symbol: str, ai_score: float, max_devil_penalty: float) -> bool:
    """The "Devil Adversarial Guard": calibrated threshold when published for the group, else the original rule."""
    model = published_model(symbol)
    if model is not None and getattr(report, "calibrated_loss_prob", None) is not None and report.penalty_score < 100.0:
        return report.calibrated_loss_prob <= float(model["threshold"])
    return (report.penalty_score <= (max_devil_penalty + (10.0 if ai_score >= 75.0 else 0.0))
            and len(report.threats_detected) <= 3)
