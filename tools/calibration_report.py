"""Per-symbol calibration report: what each profile proves and whether it may trade live.

Reads config/winrate_profiles.json (real-data calibrator output) and writes
reports/calibration_<YYYY-MM-DD>.md. Nothing here changes trading behaviour.

    python tools/calibration_report.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jarvis.backtesting.exit_geometry import deployment_refusal  # noqa: E402
from jarvis.intelligence.winrate_targeting import load_profiles  # noqa: E402

DSR_PROMOTION_BAR = 0.90  # new strategies only (shadow -> live); informational for existing ones


def _f(x, fmt):
    return "n/a" if x is None else format(x, fmt)


def build_rows(profiles) -> list[dict]:
    rows = []
    for sym, p in sorted(profiles.items()):
        refusal = deployment_refusal(sym)
        rows.append({
            "symbol": sym, "trades": p.oos_trades, "exp": p.oos_expectancy_r, "total": p.oos_total_r,
            "wr": p.oos_win_rate, "pf": p.oos_profit_factor, "dd": p.max_dd_r,
            "psr": p.oos_psr, "dsr": p.oos_dsr, "trl": p.oos_min_trl, "trials": p.n_trials,
            "geom": p.geometry.key(), "live": refusal is None, "why": refusal or "clears asset-class hurdle",
        })
    return rows


def render(rows: list[dict], generated: str) -> str:
    out = [f"# Calibration report {generated}", "",
           "Out-of-sample (purged walk-forward) results on real candles, from `config/winrate_profiles.json`.",
           "PSR = P(Sharpe > 0). DSR deflates that for the number of configurations tried; "
           f"new strategies need DSR >= {DSR_PROMOTION_BAR} to go live. Min TRL = trades needed for PSR 95%.", "",
           "| Symbol | OOS trades | Exp R | Total R | Win % | PF | In-sample max DD R | PSR | DSR | Min TRL | Trials | Live | Reason |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(
            f"| {r['symbol']} | {r['trades']} | {r['exp']:+.3f} | {r['total']:+.1f} | {r['wr']*100:.1f} | "
            f"{r['pf']:.2f} | {r['dd']:.1f} | {_f(r['psr'], '.2f')} | {_f(r['dsr'], '.2f')} | "
            f"{_f(r['trl'], '.0f')} | {r['trials']} | {'yes' if r['live'] else 'no'} | {r['why']} |")
    live = [r["symbol"] for r in rows if r["live"]]
    out += ["", f"Live-eligible: {len(live)}/{len(rows)} ({', '.join(live) or 'none'}).",
            "Geometry per symbol: " + "; ".join(f"{r['symbol']} `{r['geom']}`" for r in rows), ""]
    return "\n".join(out)


def main() -> int:
    profiles = load_profiles()
    if not profiles:
        print("no calibrated profiles found")
        return 1
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = REPO_ROOT / "reports" / f"calibration_{day}.md"
    path.write_text(render(build_rows(profiles), day), encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
