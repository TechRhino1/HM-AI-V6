"""Exit audit selection (2026-11-27): choose an exit per asset class x style on TRAIN, confirm on HOLDOUT.

Reads the grid stages exit_holdout / exit_train of tools/backtests/run_loss_audit_grid.sh
(reports/exit_audit/{holdout,train}_<mode>/<SYM>__<STYLE>.json) and writes
reports/EXIT_AUDIT_<date>.md + .json.

Rules, fixed before the runs:
  * baseline = "live" (what trades today). A variant is eligible in a class x style when, pooled over
    the class's cells on TRAIN, its expectancy beats the baseline, its profit factor is not lower, and
    its mean per-cell max drawdown is not higher. The eligible variant with the best train expectancy
    is chosen; otherwise the baseline stays.
  * HOLDOUT confirms only: the chosen variant must not be worse than the baseline there (pooled
    expectancy), else the choice is REJECTED and the baseline stays.
  * SCALP has no train window (M1 history starts inside the holdout): a SCALP variant can be chosen on
    the holdout only as PROVISIONAL - its out-of-sample test is the live shadow (>= 20 closes per cell).
  * One symbol gets its own rule only when its own best mode beats the class choice by >= SYMBOL_EDGE_R
    on both train and holdout with >= SYMBOL_MIN_N trades in each.
  * DSR per chosen cell over the true trial count (modes x cells).

    python tools/exit_audit_eval.py [--root reports/exit_audit] [--out reports/EXIT_AUDIT_2026-11-27]
           [--candidate reports/staging/exit_candidate]   (also builds the candidate evidence)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
from typing import Any, Dict, List, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from tools.loss_audit_eval import add_dsr, evaluate, load_run, write_mode_report  # noqa: E402

BASELINE = "live"
MODES = ("live", "early_protect", "ratchet", "early_ratchet")
SYMBOL_EDGE_R, SYMBOL_MIN_N = 0.05, 30


def _class(sym: str) -> str:
    from jarvis.data.symbol_registry import resolve
    return str(resolve(sym).asset_class).upper()


def pooled(ev: Dict[tuple, Dict[str, Any]], keys: List[tuple]) -> Dict[str, Any]:
    rs = [r for k in keys for r in ev.get(k, {}).get("_rs", [])]
    if not rs:
        return {"n": 0}
    wins, losses = [r for r in rs if r > 0], [r for r in rs if r < 0]
    dds = [ev[k]["max_dd_r"] for k in keys if ev.get(k, {}).get("n")]
    return {"n": len(rs), "exp_r": round(sum(rs) / len(rs), 4),
            "pf": round(sum(wins) / abs(sum(losses)), 3) if losses else None,
            "mean_dd_r": round(sum(dds) / len(dds), 2) if dds else None}


def _better(v: Dict[str, Any], b: Dict[str, Any]) -> bool:
    if not v.get("n") or not b.get("n"):
        return False
    return (v["exp_r"] > b["exp_r"] and (v["pf"] or 0) >= (b["pf"] or 0)
            and (v["mean_dd_r"] or 0) <= (b["mean_dd_r"] or 0))


def select(train: Dict[str, Dict], hold: Dict[str, Dict]) -> Dict[str, Any]:
    """{CLASS|STYLE: decision} with any symbol exceptions."""
    keys = {k for ev in list(hold.values()) + list(train.values()) for k in ev}
    groups: Dict[Tuple[str, str], List[tuple]] = {}
    for sym, st in keys:
        groups.setdefault((_class(sym), st), []).append((sym, st))
    out: Dict[str, Any] = {}
    for (cls, st), cells in sorted(groups.items()):
        has_train = all(any(k[1] == st for k in train.get(m, {})) for m in MODES)
        src = train if has_train else hold
        stats = {m: pooled(src.get(m, {}), cells) for m in MODES}
        elig = [m for m in MODES[1:] if _better(stats[m], stats[BASELINE])]
        choice = max(elig, key=lambda m: stats[m]["exp_r"]) if elig else BASELINE
        hs = {m: pooled(hold.get(m, {}), cells) for m in MODES}
        if choice == BASELINE:
            verdict = "KEEP"
        elif not has_train:
            verdict = "PROVISIONAL (no train window; needs the live shadow)"
        else:
            verdict = ("CONFIRMED" if hs[choice].get("n") and hs[BASELINE].get("n")
                       and hs[choice]["exp_r"] >= hs[BASELINE]["exp_r"] else "REJECTED")
        final = choice if verdict.startswith(("CONFIRMED", "PROVISIONAL")) else BASELINE
        dec = {"cells": sorted(f"{s}|{t}" for s, t in cells), "selected_on": "train" if has_train else "holdout",
               "selection": stats, "holdout": hs, "choice": choice, "verdict": verdict, "mode": final, "exceptions": {}}
        for sym, _ in cells:   # a symbol keeps its own rule only on clear, two-window evidence
            best = None
            for m in MODES:
                if m == final:
                    continue
                t_m, t_f = train.get(m, {}).get((sym, st), {}), train.get(final, {}).get((sym, st), {})
                h_m, h_f = hold.get(m, {}).get((sym, st), {}), hold.get(final, {}).get((sym, st), {})
                if not (t_m.get("n", 0) >= SYMBOL_MIN_N and h_m.get("n", 0) >= SYMBOL_MIN_N and t_f.get("n") and h_f.get("n")):
                    continue
                if t_m["exp_r"] - t_f["exp_r"] >= SYMBOL_EDGE_R and h_m["exp_r"] - h_f["exp_r"] >= SYMBOL_EDGE_R:
                    if best is None or t_m["exp_r"] > train[best][(sym, st)]["exp_r"]:
                        best = m
            if best:
                dec["exceptions"][f"{sym}|{st}"] = best
        out[f"{cls}|{st}"] = dec
    return out


def exit_cells(sel: Dict[str, Any]) -> Dict[str, str]:
    """trading.exit_cells for the confirmed / provisional choices (class keys, then symbol exceptions)."""
    cells = {k: v["mode"] for k, v in sel.items() if v["mode"] != BASELINE}
    for v in sel.values():
        cells.update(v["exceptions"])
    return cells


def _fmt(m: Dict[str, Any]) -> str:
    if not m.get("n"):
        return "—"
    ex = m.get("excursion") or {}
    return (f"{m['exp_r']:+.3f} / PF {m.get('pf')} / WR {m.get('win_pct')}% / DD {m.get('max_dd_r')} / "
            f"S {m.get('sharpe_trade')} / gb {ex.get('giveback_r')} / cap {ex.get('capture_pct')}% / n {m['n']}")


def _strip(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k != "_rs"}
    if isinstance(o, (list, tuple)):
        return [_strip(v) for v in o]
    return o


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.path.join(REPO, "reports", "exit_audit"))
    ap.add_argument("--out", default=os.path.join(REPO, "reports", f"EXIT_AUDIT_{dt.date.today()}"))
    ap.add_argument("--candidate", default="", help="build candidate evidence (holdout + train of the chosen modes) here")
    ap.add_argument("--holdout-window", default="2026-05-24..2026-11-26")
    a = ap.parse_args()
    hold = {m: evaluate(load_run(os.path.join(a.root, f"holdout_{m}"))) for m in MODES}
    train = {m: evaluate(load_run(os.path.join(a.root, f"train_{m}"))) for m in MODES}
    trials = sum(len(ev) for ev in hold.values())
    for ev in hold.values():
        add_dsr(ev, trials)
    sel = select(train, hold)
    cells = exit_cells(sel)
    lines = [f"# Exit audit selection ({dt.date.today()})", "",
             f"Baseline `{BASELINE}` (today's exit) vs the pre-registered variants {list(MODES[1:])}. "
             f"DSR over {trials} trials. Per cell: expectancy R / PF / win rate / max DD R / Sharpe per trade / "
             "give-back R / capture / trades.", "", "## Per asset class x style", "",
             "| Class x style | Chosen on | Choice | Verdict | Selection exp (base -> choice) | Holdout exp (base -> choice) |",
             "|---|---|---|---|---:|---:|"]
    for k, v in sel.items():
        b, c = v["selection"][BASELINE], v["selection"][v["choice"]]
        hb, hc = v["holdout"][BASELINE], v["holdout"][v["choice"]]
        lines.append(f"| {k} | {v['selected_on']} | {v['choice']} | {v['verdict']} | "
                     f"{b.get('exp_r')} -> {c.get('exp_r')} | {hb.get('exp_r')} -> {hc.get('exp_r')} |")
    lines += ["", "## Per cell, holdout", "", "| Cell | " + " | ".join(MODES) + " |", "|---|" + "---|" * len(MODES)]
    for k in sorted({k for ev in hold.values() for k in ev}):
        lines.append(f"| {k[0]} {k[1]} | " + " | ".join(_fmt(hold[m].get(k, {})) for m in MODES) + " |")
    lines += ["", f"Proposed `trading.exit_cells`: `{json.dumps(cells)}`", "",
              "Nothing changes live until the candidate evidence is promoted (PENDING: an exit-policy change), "
              "each changed cell has >= 20 complete live shadow closes not worse than the real exits, and the "
              "operator runs `python tools/promote_model.py approve mode_evidence <version> --reason ...`."]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(a.out + ".json", "w", encoding="utf-8") as f:
        json.dump(_strip({"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "trials": trials,
                          "baseline": BASELINE, "selection": sel, "exit_cells": cells,
                          "holdout": {m: {f"{s}|{t}": v for (s, t), v in ev.items()} for m, ev in hold.items()},
                          "train": {m: {f"{s}|{t}": v for (s, t), v in ev.items()} for m, ev in train.items()}}),
                  f, indent=2, default=str)
    if a.candidate:
        # Evidence for the chosen per-cell exits: each cell's holdout/train result from the mode it would trade.
        def mode_for(sym: str, st: str) -> str:
            return cells.get(f"{sym}|{st}") or cells.get(f"{_class(sym)}|{st}") or BASELINE
        for win, src in (("holdout", hold), ("train", train)):
            d = os.path.join(a.candidate, win)
            os.makedirs(d, exist_ok=True)
            for sym, st in {k for m in MODES for k in src[m]}:
                p = os.path.join(a.root, f"{win}_{mode_for(sym, st)}", f"{sym}__{st}.json")
                if os.path.exists(p):
                    shutil.copyfile(p, os.path.join(d, f"{sym}__{st}.json"))
        from jarvis.config.settings import SETTINGS
        ev = evaluate(load_run(os.path.join(a.candidate, "holdout")))
        add_dsr(ev, trials)
        rep = os.path.join(a.candidate, "mode_backtest_report.candidate.json")
        write_mode_report(ev, rep, a.holdout_window, str(SETTINGS.trading.exit_mode), a.candidate, trials,
                          evaluate(load_run(os.path.join(a.candidate, "train"))),
                          sorted(str(s).upper() for s in SETTINGS.trading.exit_hold_symbols or []))
        with open(rep, encoding="utf-8") as f:
            payload = json.load(f)
        payload["exit_cells"] = cells
        with open(rep, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print("candidate evidence:", rep)
    print("\n".join(lines[:8 + len(sel)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
