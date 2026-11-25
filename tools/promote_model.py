"""Validated promotion, rollback and status for learned models (learning governance, 2026-11-16).

Live trading uses the ACTIVE version in data/models/<name>/ (jarvis.learning.model_registry).
Learning continues in shadow; nothing reaches live trading except through this tool.

    python tools/promote_model.py status
    python tools/promote_model.py promote online_ml [--min-trades 30] [--margin 0.005]
    python tools/promote_model.py promote strategy_bandit --approve "why" [--min-trades 30]
    python tools/promote_model.py rollback <name> <version> --approve "why"

online_ml validation: a PREQUENTIAL replay of every closed demo/live trade recorded after
the active version was frozen. Each trade is predicted by the active and the candidate model
BEFORE the candidate learns from it, so every score is out-of-sample; the candidate is
promoted only if its Brier score beats the active one by --margin on >= --min-trades trades.
These are real executed trades, so the evaluation already includes costs and execution
(the paper-trading stage). Limitation: the probability model alone cannot be backtested on
bars; its effect on trade selection is measured by the engine backtests (Phase 4).

strategy_bandit validation: the shadow bandit must have seen >= --min-trades new outcomes and
an operator must approve with a reason; both are recorded.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from jarvis.config.paths import resolve_db_path  # noqa: E402
from jarvis.learning import model_registry as reg  # noqa: E402

# Governed config files: rollback/approve must also install the frozen version on disk.
GOVERNED = {
    "settings": os.path.join(REPO, "config", "settings.json"),
    "winrate_profiles": os.path.join(REPO, "config", "winrate_profiles.json"),
    "devil_gate_calibration": os.path.join(REPO, "config", "devil_gate_calibration.json"),
}


def _closed_trades_since(created_iso: str):
    db = resolve_db_path("jarvis_trade_memory.db")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT timestamp, ml_features, is_win FROM trade_records "
            "WHERE pnl IS NOT NULL AND is_win IS NOT NULL AND ml_features IS NOT NULL "
            "AND ml_features NOT IN ('', '[]') AND replace(timestamp, ' ', 'T') > ? ORDER BY timestamp",
            (created_iso.rstrip("Z"),),
        ).fetchall()
    finally:
        con.close()
    return [(ts, json.loads(f), int(w)) for ts, f, w in rows]


def evaluate_online_ml(active_file: str, trades) -> dict:
    """Prequential comparison; returns metrics and the candidate's weight file."""
    from jarvis.learning.online_ml_predictor import OnlineMLPredictor

    work = tempfile.mkdtemp(prefix="promote_ml_")
    cand_file = os.path.join(work, "candidate.json")
    shutil.copyfile(active_file, cand_file)
    os.chmod(cand_file, 0o600)
    active = OnlineMLPredictor(model_file=active_file)   # never updated: frozen reference
    cand = OnlineMLPredictor(model_file=cand_file)
    se_a = se_c = 0.0
    for _, feats, win in trades:
        pa, pc = active.predict_probability(feats), cand.predict_probability(feats)
        se_a += (pa - win) ** 2
        se_c += (pc - win) ** 2
        cand.update_online(feats, win)                   # learn only after scoring
    n = len(trades)
    return {"n": n, "brier_active": round(se_a / n, 5) if n else None,
            "brier_candidate": round(se_c / n, 5) if n else None,
            "base_rate": round(sum(w for *_, w in trades) / n, 3) if n else None,
            "candidate_file": cand_file}


def promote_online_ml(min_trades: int, margin: float) -> int:
    info = reg.active_info("online_ml")
    if not info:
        print("online_ml has no active version yet (start the engine once to freeze it).")
        return 1
    active_file = reg.active_path("online_ml")
    m = evaluate_online_ml(active_file, _closed_trades_since(info["created"]))
    passed = (m["n"] >= min_trades and m["brier_candidate"] is not None
              and m["brier_candidate"] <= m["brier_active"] - margin)
    validation = {k: v for k, v in m.items() if k != "candidate_file"}
    validation.update(min_trades=min_trades, margin=margin, method="prequential replay of closed trades",
                      passed=passed)
    print(json.dumps(validation, indent=2))
    if not passed:
        reg.audit("promotion_rejected", model="online_ml", validation=validation)
        print("REJECTED: active version stays live.")
        return 2
    v = reg.register("online_ml", m["candidate_file"], reason="validated prequential promotion",
                     validation=validation, activate=True, author="promote_model")
    print(f"PROMOTED online_ml -> {v} (restart the engine to load it).")
    return 0


def promote_bandit(min_trades: int, approve: str) -> int:
    info = reg.active_info("strategy_bandit")
    shadow = resolve_db_path("jarvis_bandit_state.json")
    if not info or not os.path.exists(shadow):
        print("strategy_bandit has no active version or shadow state yet.")
        return 1

    def pulls(path):
        with open(path, encoding="utf-8") as f:
            pri = json.load(f).get("priors", {})
        return sum(s.get("pulls", 0) for r in pri.values() for st in r.values() for s in st.values())

    new = pulls(shadow) - pulls(reg.active_path("strategy_bandit"))
    validation = {"new_outcomes": new, "min_trades": min_trades, "operator_reason": approve,
                  "passed": bool(approve) and new >= min_trades}
    print(json.dumps(validation, indent=2))
    if not validation["passed"]:
        reg.audit("promotion_rejected", model="strategy_bandit", validation=validation)
        print("REJECTED: needs --approve and enough new outcomes.")
        return 2
    v = reg.register("strategy_bandit", shadow, reason=approve, validation=validation,
                     activate=True, author="operator")
    print(f"PROMOTED strategy_bandit -> {v} (restart the engine to load it).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("promote")
    p.add_argument("name", choices=["online_ml", "strategy_bandit"])
    p.add_argument("--min-trades", type=int, default=30)
    p.add_argument("--margin", type=float, default=0.005)
    p.add_argument("--approve", default="")
    r = sub.add_parser("rollback")
    r.add_argument("name")
    r.add_argument("version")
    r.add_argument("--approve", required=True)
    ap_ = sub.add_parser("approve", help="install a PENDING governed config version")
    ap_.add_argument("name", choices=sorted(GOVERNED))
    ap_.add_argument("version")
    ap_.add_argument("--reason", required=True)
    a = ap.parse_args()

    if a.cmd == "status":
        for name in ("online_ml", "strategy_bandit", *GOVERNED):
            v = reg.versions(name)
            print(name, "active:", v.get("active"))
            for k, meta in v.get("versions", {}).items():
                print(f"  {k}  {meta['created']}  {meta.get('status', '-'):7}  {meta['reason']}  "
                      f"passed={meta.get('validation', {}).get('passed', '-')}")
        return 0
    if a.cmd == "approve":
        reg.deploy_version(a.name, a.version, GOVERNED[a.name], reason=a.reason)
        print(f"{a.name} {a.version} installed at {GOVERNED[a.name]} and activated.")
        return 0
    if a.cmd == "rollback":
        if a.name in GOVERNED:
            reg.deploy_version(a.name, a.version, GOVERNED[a.name], reason=a.approve)
            print(f"{a.name} -> {a.version}: file restored at {GOVERNED[a.name]} "
                  "(settings need an engine restart; profiles hot-reload).")
        else:
            reg.activate(a.name, a.version, reason=a.approve)
            print(f"{a.name} -> {a.version} (restart the engine to load it).")
        return 0
    if a.name == "online_ml":
        return promote_online_ml(a.min_trades, a.margin)
    return promote_bandit(a.min_trades, a.approve)


if __name__ == "__main__":
    sys.exit(main())
