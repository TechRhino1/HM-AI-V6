"""Cost-honest backtest of the pre-registered session leads (jarvis/forward_tests/session_leads.py).

Real MT5 H1 bars only (data/market/real/<SYM>/<SYM>_H1_730d.parquet, provenance checked).
Same simulator and cost model as tools/calibrate_winrate.py: next-bar-open fill, full spread
paid, 0.5-pip stop slippage, commission from the symbol profile. Rules are fixed, so the trial
count for the deflated Sharpe is symbols x strategies, with no parameter search.

    python tools/research_session_leads.py
Writes reports/SESSION_LEADS_RESEARCH_<date>.md and data/signals/session_leads_research.json.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jarvis.backtesting.exit_geometry import OOS_HURDLES  # noqa: E402
from jarvis.backtesting.trade_simulator import Geometry, select_sequential, simulate_all_candidates, summarise  # noqa: E402
from jarvis.config.paths import DATA_DIR  # noqa: E402
from jarvis.data.symbol_registry import get_dollar_risk_per_price_unit, resolve  # noqa: E402
from jarvis.forward_tests.session_leads import IMOM_SESSIONS, SIGNALS, to_candidates  # noqa: E402
from jarvis.intelligence.winrate_targeting import WRTargetCalibrator, _selection_bias_stats  # noqa: E402

REAL_DIR = Path(DATA_DIR) / "market" / "real"
FOLDS = 4


def evaluate(df: pd.DataFrame, symbol: str, kind: str, digits: int) -> dict:
    fn, tp_r, max_bars = SIGNALS[kind]
    spec = resolve(symbol)
    spread_px = df["spread"].to_numpy(float) * 10.0 ** (-digits) if "spread" in df.columns else np.zeros(len(df))
    cands = to_candidates(df, fn(df), symbol, kind, spread_px)
    if cands.empty:
        return {"trades": 0, "r": [], "folds": []}
    mpu = get_dollar_risk_per_price_unit(symbol)
    cal = WRTargetCalibrator(slippage_pips=0.5)
    outs = select_sequential(simulate_all_candidates(
        df=df, candidates=cands, geom=Geometry(tp_r=tp_r, max_bars=max_bars), money_per_unit=mpu,
        cost_price_equiv=cal._cost_price_equiv(symbol, mpu),
        slippage_price_equiv=0.5 * float(getattr(spec, "pip_size", 0.0001) or 0.0001),
        spec=spec, symbol=symbol))
    s = summarise(outs)
    edges = np.linspace(0, len(df), FOLDS + 1).astype(int)
    folds = [summarise([o for o in outs if lo <= o.entry_idx < hi])["expectancy_r"] for lo, hi in zip(edges, edges[1:])]
    return {**s, "r": [o.pnl_r for o in outs], "folds": folds}


def main() -> int:
    results = {}
    for d in sorted(p for p in REAL_DIR.iterdir() if p.is_dir()):
        sym = d.name
        path, man = d / f"{sym}_H1_730d.parquet", d / f"{sym}_H1_730d.manifest.json"
        if not path.exists() or not man.exists():
            continue
        meta = json.loads(man.read_text(encoding="utf-8"))
        if meta.get("synthetic") or meta.get("provenance") != "MT5_TERMINAL_REAL":
            print(f"{sym}: skipped, not real MT5 data")
            continue
        df = pd.read_parquet(path).reset_index(drop=True)
        df.attrs["symbol"] = sym  # IMOM reads it to pick the index's cash session
        digits = int((meta.get("meta") or {}).get("digits", resolve(sym).digits))
        for kind in SIGNALS:
            if kind == "IMOM" and sym not in IMOM_SESSIONS:
                continue
            results[(sym, kind)] = evaluate(df, sym, kind, digits)
            r = results[(sym, kind)]
            print(f"{sym:7s} {kind:5s} n={r['trades']:4d} exp={r.get('expectancy_r', 0):+.3f}R")
    all_r = [r["r"] for r in results.values()]
    rows = []
    for (sym, kind), r in results.items():
        psr, dsr, trl = _selection_bias_stats(r["r"], all_r)
        hurdle = OOS_HURDLES.get(str(resolve(sym).asset_class).upper(), OOS_HURDLES["DEFAULT"])
        clears = r["trades"] >= hurdle["min_trades"] and r.get("expectancy_r", 0.0) >= hurdle["min_expectancy_r"]
        rows.append({"symbol": sym, "strategy": kind, "trades": r["trades"],
                     "expectancy_r": r.get("expectancy_r", 0.0), "total_r": r.get("total_r", 0.0),
                     "win_rate": r.get("win_rate", 0.0), "profit_factor": r.get("profit_factor", 0.0),
                     "max_dd_r": r.get("max_dd_r", 0.0), "folds_positive": sum(f > 0 for f in r["folds"]),
                     "psr": psr, "dsr": dsr, "min_trl": trl, "clears_hurdle": clears,
                     "shadow": bool(clears and sum(f > 0 for f in r["folds"]) >= 3)})
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (Path(DATA_DIR) / "signals" / "session_leads_research.json").write_text(
        json.dumps({"generated_utc": day, "trials": len(rows), "rows": rows}, indent=2), encoding="utf-8")

    def f(x, fmt):
        return "n/a" if x is None else format(x, fmt)
    md = [f"# Session leads research {day}", "",
          "Pre-registered ORB and anchored-VWAP rules (`jarvis/forward_tests/session_leads.py`), real MT5 H1 "
          f"bars over 730 days, calibrator cost model. {len(rows)} trials; DSR is deflated across all of them.",
          "Shadow = clears the asset-class hurdle and is positive in at least 3 of 4 time folds. "
          "Live promotion additionally needs DSR >= 0.90 and 30+ positive demo trades.", "",
          "| Symbol | Strategy | Trades | Exp R | Total R | Win % | PF | Max DD R | Folds + | PSR | DSR | Shadow |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["strategy"], -x["expectancy_r"])):
        md.append(f"| {r['symbol']} | {r['strategy']} | {r['trades']} | {r['expectancy_r']:+.3f} | {r['total_r']:+.1f} | "
                  f"{r['win_rate']*100:.1f} | {r['profit_factor']:.2f} | {r['max_dd_r']:.1f} | {r['folds_positive']}/{FOLDS} | "
                  f"{f(r['psr'], '.2f')} | {f(r['dsr'], '.2f')} | {'yes' if r['shadow'] else 'no'} |")
    for kind in SIGNALS:
        md.append(f"\n{kind} shadow symbols: " + (", ".join(r["symbol"] for r in rows if r["strategy"] == kind and r["shadow"]) or "none"))
    out = REPO_ROOT / "reports" / f"SESSION_LEADS_RESEARCH_{day}.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
