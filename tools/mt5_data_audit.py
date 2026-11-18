"""MT5 data + contract-spec audit (calibration step 0).

Proves the bars and contract specs the per-symbol recalibration will use are
correct, by comparing the live terminal against the code's two spec sources:

  * ``jarvis/data/symbol_registry.py``          (SymbolSpec: sizing + spread gate)
  * ``jarvis/intelligence/symbol_profile_config.py`` (SYMBOL_PROFILES: volume,
    commission, a second copy of sizing + spread)

For each traded symbol it checks alias resolution, bar depth / gaps / broker
clock, contract fields, spread (median of recent M5 bar spreads, not one tick),
commission (from this account's own deal history) and min-lot risk at
1.5 x ATR(14) H1 against ``config/settings.json``.

Read-only against the terminal: no orders, no symbol changes beyond
``symbol_select`` (adds to Market Watch).

Usage:
  python tools/mt5_data_audit.py [--out reports/MT5_DATA_AUDIT_2026-11-18.md]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from jarvis.data.broker_symbols import ensure_mt5_terminal, resolve_broker_symbol  # noqa: E402
from jarvis.data.broker_time import BROKER_TZ, broker_bar_times_to_utc  # noqa: E402
from jarvis.data.schemas import is_observed_price  # noqa: E402
from jarvis.data.symbol_registry import is_registered, resolve as resolve_spec  # noqa: E402
from jarvis.intelligence.symbol_profile_config import get_symbol_profile_config  # noqa: E402

CORE = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD", "SOLUSD"]
TFS = ["M5", "M15", "H1", "H4", "D1"]
TF_SEC = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
DEPTH_TRIES = (50_000, 20_000, 10_000, 5_000, 1_000)  # fallbacks below the terminal maxbars - 1
SPREAD_BARS = 288 * 20  # ~20 trading days of M5
TYPICAL_BAND = (0.8, 1.25)  # registry typical spread must sit within this x of the measured median
PIP_VALUE_TOL = 0.02        # USD-quoted: exact
PIP_VALUE_TOL_CROSS = 0.05  # non-USD quote: the static value drifts with the FX rate


def traded_symbols() -> list:
    """Core list + every canonical in config/symbol_profiles.json, deduped, in order."""
    with open(os.path.join(REPO, "config", "symbol_profiles.json"), encoding="utf-8") as f:
        keys = list(json.load(f))
    out = []
    for s in CORE + [resolve_spec(k).canonical for k in keys if is_registered(k)]:
        if s not in out:
            out.append(s)
    return out


def max_depth(mt5, name, tf):
    """Deepest copy_rates_from_pos the terminal will serve (bounded by its Max bars setting)."""
    tfc = getattr(mt5, f"TIMEFRAME_{tf}")
    # The terminal refuses count >= maxbars with (-2, 'Invalid params') rather than clamping.
    for n in (mt5.terminal_info().maxbars - 1,) + DEPTH_TRIES:
        r = mt5.copy_rates_from_pos(name, tfc, 0, n)
        if r is not None and len(r):
            return r
    return None


def gap_stats(times_utc: pd.Series, tf: str, crypto: bool):
    """Gaps > 1.5 bars. Weekend closures are expected for non-crypto and counted separately."""
    d = times_utc.diff().dt.total_seconds().iloc[1:]
    gaps = d[d > 1.5 * TF_SEC[tf]]
    weekend = short = 0
    odd = []
    for idx, sec in gaps.items():
        start = times_utc.iloc[idx - 1]
        # A gap < 3.5 days spanning a Saturday is the normal weekend close.
        days = pd.date_range(start.normalize(), (start + pd.Timedelta(seconds=sec)).normalize())
        if not crypto and sec < 3.5 * 86400 and any(d.weekday() == 5 for d in days):
            weekend += 1
        elif sec <= 3 * 3600:  # daily CFD session break / crypto maintenance window
            short += 1
        else:
            odd.append((start, sec))
    biggest = max((s for _, s in odd), default=0.0)
    odd_2y = sum(1 for st, _ in odd if st >= times_utc.iloc[-1] - pd.Timedelta(days=730))
    return len(gaps), weekend, short, odd, biggest, odd_2y


def atr14(rates) -> float:
    h, l, c = rates["high"], rates["low"], rates["close"]
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return float(pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])  # Wilder


def commission_per_lot(mt5, name):
    """Round-trip commission per 1.0 lot from this account's own deals (last 180 d), or (None, 0)."""
    deals = mt5.history_deals_get(datetime.now() - timedelta(days=180), datetime.now() + timedelta(days=1),
                                  group=name)
    vol = comm = 0.0
    for d in deals or []:
        if d.entry in (mt5.DEAL_ENTRY_IN, mt5.DEAL_ENTRY_OUT) and d.volume > 0:
            vol += d.volume
            comm += d.commission
    # each lot appears twice (in + out), so per round-trip lot = 2 * comm / vol
    return (round(2 * comm / vol, 4), int(len(deals or []))) if vol else (None, 0)


def audit_symbol(mt5, canon, equity, risk_cap, minlot_cap, offset_sec):
    row = {"canonical": canon, "mismatches": [], "notes": []}
    mm, notes = row["mismatches"], row["notes"]
    spec = resolve_spec(canon)
    prof = get_symbol_profile_config(canon)
    row["registered"] = is_registered(canon)
    if not row["registered"]:
        mm.append("not in symbol_registry (generic FX fallback)")

    name = resolve_broker_symbol(canon)
    row["broker"] = name
    if not name:
        mm.append("alias does not resolve to any broker symbol")
        return row
    if not mt5.symbol_select(name, True):
        mm.append(f"{name} not selectable")
        return row
    info = mt5.symbol_info(name)
    row["trade_mode"] = info.trade_mode
    if info.trade_mode == 0:
        mm.append(f"{name} trade_mode=DISABLED")

    # --- bars -----------------------------------------------------------
    now = pd.Timestamp.now(tz="UTC")
    row["bars"] = {}
    h1 = None
    for tf in TFS:
        r = max_depth(mt5, name, tf)
        if r is None:
            mm.append(f"{tf}: no bars")
            continue
        t = broker_bar_times_to_utc(r["time"], offset_sec).reset_index(drop=True)
        n, wk, short, odd, biggest, odd_2y = gap_stats(t, tf, spec.is_crypto)
        lag_min = (now - t.iloc[-1]).total_seconds() / 60
        row["bars"][tf] = {"n": len(r), "first": str(t.iloc[0])[:16], "last": str(t.iloc[-1])[:16],
                           "gaps": n, "weekend": wk, "short": short, "odd": len(odd), "odd_2y": odd_2y, "biggest_odd_h": round(biggest / 3600, 1),
                           "lag_min": round(lag_min, 1)}
        if lag_min < -5:
            mm.append(f"{tf}: last bar {lag_min:.0f} min in the FUTURE after UTC conversion (clock offset wrong)")
        if tf == "H1":
            h1 = r

    # --- contract fields ------------------------------------------------
    pip_value_broker = info.trade_tick_value / info.trade_tick_size * spec.pip_size if info.trade_tick_size else 0
    tol = PIP_VALUE_TOL if info.currency_profit == "USD" else PIP_VALUE_TOL_CROSS
    row["contract"] = {
        "digits": info.digits, "point": info.point, "tick_size": info.trade_tick_size,
        "tick_value": round(info.trade_tick_value, 6), "contract_size": info.trade_contract_size,
        "volume_min": info.volume_min, "volume_step": info.volume_step, "stops_level": info.trade_stops_level,
        "currency_profit": info.currency_profit, "pip_value_broker": round(pip_value_broker, 4),
    }
    for src, obj in (("registry", spec), ("profile", prof)):
        if int(obj.digits) != info.digits:
            mm.append(f"{src}.digits {obj.digits} != broker {info.digits}")
        if abs(obj.contract_size - info.trade_contract_size) > 1e-9:
            mm.append(f"{src}.contract_size {obj.contract_size} != broker {info.trade_contract_size}")
        if abs(obj.pip_size - spec.pip_size) > 1e-12:
            mm.append(f"{src}.pip_size {obj.pip_size} != registry {spec.pip_size}")
        if pip_value_broker and abs(obj.pip_value_per_lot / pip_value_broker - 1) > tol:
            mm.append(f"{src}.pip_value_per_lot {obj.pip_value_per_lot} vs broker {pip_value_broker:.4f} "
                      f"(tol {tol:.0%})")
    if abs(prof.min_volume - info.volume_min) > 1e-9:
        mm.append(f"profile.min_volume {prof.min_volume} != broker {info.volume_min}")
    if abs(prof.volume_step - info.volume_step) > 1e-9:
        mm.append(f"profile.volume_step {prof.volume_step} != broker {info.volume_step}")

    # --- spread (pips, registry pip convention) -------------------------
    m5 = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_M5, 0, SPREAD_BARS)
    tick = mt5.symbol_info_tick(name)
    to_pips = info.point / spec.pip_size
    live = ((tick.ask - tick.bid) / spec.pip_size
            if tick and is_observed_price(tick.bid) and is_observed_price(tick.ask) else None)
    sp = m5["spread"][m5["spread"] > 0] * to_pips if m5 is not None else np.array([])
    med = float(np.median(sp)) if len(sp) else None
    p95 = float(np.percentile(sp, 95)) if len(sp) else None
    row["spread"] = {"live": None if live is None else round(live, 2), "median": med and round(med, 2),
                     "p95": p95 and round(p95, 2), "reg_typ": spec.typical_spread_pips, "reg_max": spec.max_spread_pips,
                     "prof_typ": prof.typical_spread_pips, "prof_max": prof.max_allowed_spread_pips}
    if med:
        for src, typ, mx in (("registry", spec.typical_spread_pips, spec.max_spread_pips),
                             ("profile", prof.typical_spread_pips, prof.max_allowed_spread_pips)):
            if not (TYPICAL_BAND[0] <= typ / med <= TYPICAL_BAND[1]):
                mm.append(f"{src}.typical_spread {typ} vs measured median {med:.2f}")
            if mx < p95:
                mm.append(f"{src}.max_spread {mx} < measured p95 {p95:.2f} (gate rejects >5% of bars)")

    # --- commission -----------------------------------------------------
    comm, ndeals = commission_per_lot(mt5, name)
    row["commission"] = {"measured_rt_per_lot": comm, "deals": ndeals, "profile": prof.commission_per_lot}
    if comm is not None and abs(abs(comm) - prof.commission_per_lot) > 0.01:
        mm.append(f"profile.commission_per_lot {prof.commission_per_lot} vs measured {abs(comm)} per round-trip lot")
    elif comm is None:
        notes.append("no deals on this account to measure commission")

    # --- min-lot risk ---------------------------------------------------
    if h1 is not None and len(h1) > 20:
        atr = atr14(h1[-500:])
        stop = 1.5 * atr
        loss = stop / info.trade_tick_size * info.trade_tick_value * info.volume_min
        pct = 100 * loss / equity
        row["risk"] = {"atr_h1": round(atr, info.digits), "stop": round(stop, info.digits),
                       "loss_usd": round(loss, 2), "pct_equity": round(pct, 2),
                       "stops_level_ok": bool(stop >= info.trade_stops_level * info.point)}
        if pct > minlot_cap:
            notes.append(f"min-lot risk {pct:.2f}% > min_lot_max_risk_pct {minlot_cap}% -> untradeable at this equity")
        elif pct > risk_cap:
            notes.append(f"min-lot risk {pct:.2f}% > max_risk_per_trade_pct {risk_cap}% "
                         f"(allowed only via min-lot cap {minlot_cap}%)")
        if not row["risk"]["stops_level_ok"]:
            mm.append(f"1.5xATR stop {stop} < stops_level {info.trade_stops_level} pts")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "reports", f"MT5_DATA_AUDIT_{datetime.now():%Y-%m-%d}.md"))
    ap.add_argument("--json", default=None, help="also dump raw results here")
    args = ap.parse_args()

    import MetaTrader5 as mt5
    if not ensure_mt5_terminal():
        sys.exit("MT5 terminal not available")
    acct, term = mt5.account_info(), mt5.terminal_info()
    with open(os.path.join(REPO, "config", "settings.json"), encoding="utf-8") as f:
        risk = json.load(f)["risk"]
    risk_cap, minlot_cap = float(risk["max_risk_per_trade_pct"]), float(risk["min_lot_max_risk_pct"])

    # Broker clock: freshest tick vs real UTC, rounded to the 30-min grid; vs the calendar BROKER_TZ.
    fresh = [mt5.symbol_info_tick(resolve_broker_symbol(s) or s) for s in ("EURUSD", "GBPUSD", "BTCUSD")]
    tick_t = max(t.time for t in fresh if t)
    raw = tick_t - time.time()
    tick_off = int(round(raw / 1800) * 1800)
    cal_off = int(pd.Timestamp.now(tz=BROKER_TZ).utcoffset().total_seconds())
    clock = {"tick_minus_utc_s": round(raw), "tick_offset_h": tick_off / 3600, "calendar_offset_h": cal_off / 3600,
             "match": tick_off == cal_off}

    rows = [audit_symbol(mt5, s, acct.equity, risk_cap, minlot_cap, tick_off) for s in traded_symbols()]
    if not clock["match"]:
        rows.append({"canonical": "(clock)", "broker": "-", "notes": [],
                     "mismatches": [f"tick offset {tick_off/3600}h != BROKER_TZ {cal_off/3600}h"]})

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"clock": clock, "rows": rows}, f, indent=1, default=str)
    write_report(args.out, acct, term, clock, risk_cap, minlot_cap, rows)
    n = sum(len(r["mismatches"]) for r in rows)
    print(f"wrote {args.out}: {len(rows)} symbols, {n} mismatches")
    for r in rows:
        for m in r["mismatches"]:
            print(f"  {r['canonical']:7} {m}")
        for m in r["notes"]:
            print(f"  {r['canonical']:7} note: {m}")


def write_report(path, acct, term, clock, risk_cap, minlot_cap, rows):
    L = [f"# MT5 data audit — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
         f"Server `{acct.server}`, account currency {acct.currency}, equity {acct.equity:.2f}, "
         f"leverage 1:{acct.leverage}, terminal max bars {term.maxbars}.", "",
         f"Broker clock: freshest tick − UTC = {clock['tick_minus_utc_s']} s → {clock['tick_offset_h']} h; "
         f"`BROKER_TZ` calendar = {clock['calendar_offset_h']} h → **{'OK' if clock['match'] else 'MISMATCH'}**.", "",
         "## Alias resolution", "", "| canonical | broker | trade_mode | registered |", "|---|---|---|---|"]
    for r in rows:
        if r["canonical"].startswith("("):
            continue
        L.append(f"| {r['canonical']} | `{r.get('broker')}` | {r.get('trade_mode', '-')} | {r.get('registered')} |")
    L += ["", "## Bar depth and gaps (UTC)", "",
          "`gaps` = bar-to-bar jumps > 1.5 bars; `weekend` = the Fri→Sun close; `short` = ≤ 3 h (daily CFD "
          "session break, crypto maintenance); `odd` = everything else (holidays, outages, sparse old history); "
          "`lag` = minutes since last bar open.", "",
          "| symbol | tf | bars | first | last | lag min | gaps | weekend | short | odd | odd last 2y | biggest odd h |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        for tf, b in r.get("bars", {}).items():
            L.append(f"| {r['canonical']} | {tf} | {b['n']} | {b['first']} | {b['last']} | {b['lag_min']} | "
                     f"{b['gaps']} | {b['weekend']} | {b['short']} | {b['odd']} | {b['odd_2y']} | {b['biggest_odd_h']} |")
    L += ["", "## Contract fields (broker)", "",
          "| symbol | digits | tick size | tick value | contract | vol min/step | stops lvl | profit ccy "
          "| pip $/lot broker | registry | profile |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c = r.get("contract")
        if not c:
            continue
        spec, prof = resolve_spec(r["canonical"]), get_symbol_profile_config(r["canonical"])
        L.append(f"| {r['canonical']} | {c['digits']} | {c['tick_size']} | {c['tick_value']} | {c['contract_size']} | "
                 f"{c['volume_min']}/{c['volume_step']} | {c['stops_level']} | {c['currency_profit']} | "
                 f"{c['pip_value_broker']} | {spec.pip_value_per_lot} | {prof.pip_value_per_lot} |")
    L += ["", "## Spread (pips, registry pip size) and commission", "",
          "Median / p95 over the last ~20 days of M5 bar spreads.", "",
          "| symbol | live | median | p95 | registry typ/max | profile typ/max | commission measured (deals) | profile |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        s, cm = r.get("spread"), r.get("commission")
        if not s:
            continue
        L.append(f"| {r['canonical']} | {s['live']} | {s['median']} | {s['p95']} | {s['reg_typ']}/{s['reg_max']} | "
                 f"{s['prof_typ']}/{s['prof_max']} | {cm['measured_rt_per_lot']} ({cm['deals']}) | {cm['profile']} |")
    L += ["", f"## Min-lot risk (1.5×ATR(14) H1 stop at volume_min; caps: per-trade {risk_cap}%, "
          f"min-lot {minlot_cap}%)", "",
          "| symbol | ATR H1 | stop | loss $ | % equity | ≥ stops level |", "|---|---|---|---|---|---|"]
    for r in rows:
        k = r.get("risk")
        if k:
            flag = " ⚠" if k["pct_equity"] > minlot_cap else (" (>per-trade)" if k["pct_equity"] > risk_cap else "")
            L.append(f"| {r['canonical']} | {k['atr_h1']} | {k['stop']} | {k['loss_usd']} | "
                     f"{k['pct_equity']}{flag} | {k['stops_level_ok']} |")
    L += ["", "## Mismatches", ""]
    any_mm = False
    for r in rows:
        for m in r["mismatches"]:
            any_mm = True
            L.append(f"- **{r['canonical']}**: {m}")
    if not any_mm:
        L.append("None.")
    L += ["", "## Notes", ""]
    for r in rows:
        for m in r["notes"]:
            L.append(f"- {r['canonical']}: {m}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
