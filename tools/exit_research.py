"""Exit-policy comparison: the SAME entries replayed bar by bar under each trailing-stop policy,
through the production jarvis.execution.exit_policy.evaluate_exit (what the live monitor's core and
the backtester call).

Costs as tools/strategy_research.py: entry at the next open (BUY pays the spread), SELL exits pay the
spread, slippage on stop exits, stop checked before target in a bar, gaps through a stop fill at the
open, broker swap per night. A stop moved at a bar's close applies from the next bar.

Entries (fixed rules, no tuning), per symbol: Donchian 20/10 breakouts on H1 (DAY_TRADING exits) and H4
(SWING exits), and range_sr fades on H1, each with a 2.5R target (the live planned RR) unless the
entry carries its own. Policies:
  fixed            stop + target only
  legacy           ExitPolicy.for_symbol(symbol, style): today's BE / partial-lock / milestone /
                   progress-lock / capped ATR trail / time stop stack (partial_executable=False: min lot)
  inst_k{k}        trail_mode="institutional", chandelier k x ATR, same target and time stop
  inst_k3_noTP     institutional k=3 and no target (let the trail end the trade)

Usage:
    python tools/exit_research.py <bars.pkl> <out.json> [SYMBOL ...]
"""
import os, sys, json, pickle, dataclasses
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import strategy_research as sr
import range_research as rr
from jarvis.execution.exit_policy import ExitPolicy, evaluate_exit, _RESOLVED_POLICY_CACHE

TGT_R = 2.5
STYLE = {"H1": "DAY_TRADING", "H4": "SWING"}


def walk_managed(A, i, side, sd, tgt_r, pol, piv_lo, piv_hi):
    """Returns (net R incl. swap, exit bar) or None. pol None = fixed stop/target only."""
    o, h, l, c, spr, atr = A["o"], A["h"], A["l"], A["c"], A["spr"], A["atr"]
    n, j0, slip = len(o), i + 1, A["slip"]
    if j0 >= n:
        return None
    entry = o[j0] + spr[j0] if side == 1 else o[j0]
    init = stop = entry - side * sd
    tgt = entry + side * tgt_r * sd if tgt_r else None
    peak, partial, be = 0.0, False, False

    def fin(px, j):
        nights = A["W"][A["day"][j] - A["d0"]] - A["W"][A["day"][j0] - A["d0"]]
        sw = nights * sr.swap_px(A["info"], side, entry)
        return (side * (px - entry) + sw) / sd, j

    for j in range(j0, n):
        if side == 1:
            if l[j] <= stop:
                return fin(min(o[j], stop) - slip, j)
            if tgt is not None and h[j] >= tgt:
                return fin(tgt, j)
            px, best = c[j], h[j] - entry
        else:
            if h[j] + spr[j] >= stop:
                return fin(max(o[j] + spr[j], stop) + slip, j)
            if tgt is not None and l[j] + spr[j] <= tgt:
                return fin(tgt, j)
            px, best = c[j] + spr[j], entry - (l[j] + spr[j])
        peak = max(peak, best)
        if pol is None:
            continue
        # last confirmed swing beyond entry (BUY: a pivot low; SELL: a pivot high), as the live filter
        pv = piv_lo if side == 1 else piv_hi
        k = np.searchsorted(pv, j - rr.K, side="right")
        struct = None
        if k:
            p = pv[k - 1]
            lvl = l[p] if side == 1 else h[p]
            struct = lvl if p >= j0 and side * (lvl - entry) > 0 else None
        dec = evaluate_exit(side="BUY" if side == 1 else "SELL", entry=entry, initial_sl=init, current_sl=stop,
                            tp=tgt or 0.0, price=px, favorable_dist=max(0.0, side * (px - entry)), atr=atr[j],
                            policy=pol, partial_already_taken=partial, be_already_locked=be,
                            struct_level=struct, partial_executable=False,
                            hold_minutes=(A["tc"][j] - A["to"][j0]) / sr.NS_MIN, peak_favorable_dist=peak)
        if dec.close_position:
            if j + 1 >= n:
                return None
            return fin(o[j + 1] - slip if side == 1 else o[j + 1] + spr[j + 1] + slip, j + 1)
        be = be or dec.be_locked
        partial = partial or any(a.startswith("PARTIAL") for a in dec.actions)
        if dec.new_sl and side * (dec.new_sl - stop) > 0:
            stop = dec.new_sl
    return None


def replay(A, sig, policies, piv):
    """One position at a time, using the FIXED policy's exits to decide occupancy so every policy
    trades exactly the same entries."""
    out = {name: [] for name in policies}
    times, busy = [], -1
    for item in sig:
        i, side, sd = item[:3]
        tg = item[3] if len(item) > 3 else TGT_R
        if i < busy or not sd > 0:
            continue
        base = walk_managed(A, i, side, sd, tg, None, *piv)
        if base is None:
            continue
        res = {}
        for name, (pol, use_tgt) in policies.items():
            w = walk_managed(A, i, side, sd, tg if use_tgt else None, pol, *piv)
            if w is None:
                break
            res[name] = w[0]
        if len(res) != len(policies):
            continue
        for name, r in res.items():
            out[name].append(r)
        times.append(A["t"].iat[i])
        busy = base[1]
    return out, times


def summary(rs, times):
    rs = np.array(rs, float)
    if not len(rs):
        return {"n": 0}
    win, loss = rs[rs > 0], rs[rs <= 0]
    half = len(rs) // 2
    return {"n": int(len(rs)), "exp_r": round(float(rs.mean()), 3), "wr": round(float((rs > 0).mean()), 3),
            "pf": round(float(win.sum() / -loss.sum()), 2) if loss.sum() < 0 else None,
            "avg_win": round(float(win.mean()), 2) if len(win) else 0.0,
            "avg_loss": round(float(loss.mean()), 2) if len(loss) else 0.0,
            "h1": round(float(rs[:half].mean()), 3), "h2": round(float(rs[half:].mean()), 3)}


def policies_for(name, style):
    _RESOLVED_POLICY_CACHE.clear()
    legacy = ExitPolicy.for_symbol(name, trade_style=style)
    inst = lambda k: dataclasses.replace(legacy, trail_mode="institutional", chandelier_atr_mult=k)
    pols = {"fixed": (None, True), "legacy": (legacy, True)}
    for k in (2.0, 2.5, 3.0, 3.5):
        pols[f"inst_k{k}"] = (inst(k), True)
    pols["inst_k3_noTP"] = (inst(3.0), False)
    return pols


def research(data, symbols=None):
    res, pooled = {}, {}
    for name in (symbols or data):
        info, P, slip, weekends, _ = rr.prepare(name, data[name])
        res[name] = {}
        for tf, entry_set in (("H1", "donchian"), ("H4", "donchian"), ("H1", "range_sr")):
            A = sr.arrays(P[tf], info, slip, weekends)
            piv = rr.pivots(A["h"], A["l"])
            piv = (piv[1], piv[0])   # (lows, highs)
            if entry_set == "donchian":
                sig, _ = sr.donchian(A, 20, 10)
                sig = [(i, s, d) for i, s, d in sig]
            else:
                sig = rr.candidates(P, A, tf)[0][1]
            style = STYLE[tf]
            out, times = replay(A, sig, policies_for(name, style), piv)
            key = f"{entry_set}|{tf}|{style}"
            res[name][key] = {p: summary(v, times) for p, v in out.items()}
            for p, v in out.items():
                pooled.setdefault(key, {}).setdefault(p, []).extend(zip(times, v))
            print(name, key, {p: (s["n"], s["exp_r"], s["h1"], s["h2"]) for p, s in res[name][key].items()}, flush=True)
    res["_pooled"] = {}
    for key, by_pol in pooled.items():
        res["_pooled"][key] = {}
        for p, rows in by_pol.items():
            rows.sort(key=lambda x: x[0])
            res["_pooled"][key][p] = summary([r for _, r in rows], [t for t, _ in rows])
    return res


def table(res):
    out = ["| Entries | Policy | n | Exp R | WR | PF | Avg win | Avg loss | 1st half | 2nd half |", "|" + "---|" * 10]
    for key, by_pol in res["_pooled"].items():
        for p, s in by_pol.items():
            if s["n"]:
                out.append(f"| {key} | {p} | {s['n']} | {s['exp_r']:+.3f} | {s['wr']:.0%} | {s['pf']} | "
                           f"{s['avg_win']:+.2f} | {s['avg_loss']:+.2f} | {s['h1']:+.3f} | {s['h2']:+.3f} |")
    return "\n".join(out)


GROUPS = {"crypto": ("BTCUSD", "ETHUSD", "SOLUSD"), "metals": ("XAUUSD", "XAGUSD"),
          "indices": ("GER40", "UK100", "US30", "NAS100")}


def replay_live_trade(t, pol):
    """One closed live trade replayed on its real M1 path through evaluate_exit (None = fixed stop/target).
    Pessimistic intrabar order: the adverse extreme is checked before the favourable one."""
    sg, e, r, tp_r = t["side"], t["entry"], t["risk"], t["tp_r"]
    stop_r, banked, size, taken, peak = -1.0, 0.0, 1.0, False, 0.0
    for hi, lo, cl in t["path"]:                       # path in R: favourable, adverse, close
        if lo <= stop_r:
            return banked + size * stop_r
        if hi >= tp_r:
            return banked + size * tp_r
        if pol is None:
            continue
        peak = max(peak, hi)
        dec = evaluate_exit(side="BUY" if sg == 1 else "SELL", entry=e, initial_sl=e - sg * r,
                            current_sl=e + sg * stop_r * r, tp=e + sg * tp_r * r, price=e + sg * cl * r,
                            favorable_dist=max(0.0, cl * r), atr=r, policy=pol, partial_already_taken=taken,
                            partial_executable=t["splittable"], peak_favorable_dist=max(0.0, peak * r))
        if dec.partial_close_pct and not taken:
            banked += dec.partial_close_pct * cl
            size -= dec.partial_close_pct
            taken = True
        if dec.new_sl:
            stop_r = max(stop_r, sg * (dec.new_sl - e) / r)
        if dec.close_position:
            return banked + size * cl
    return banked + size * t["path"][-1][2]


def live_trades_main(out_md):
    """Closed live demo trades (data/jarvis_history.db) on real MT5 M1 bars, 48 h each: actual exits vs
    fixed stop/target vs legacy core vs the institutional lock. Read-only; MT5 history only."""
    import sqlite3
    from datetime import datetime, timezone
    import MetaTrader5 as mt5
    from jarvis.data.broker_symbols import resolve_broker_symbol
    from jarvis.data.broker_time import broker_utc_offset
    from jarvis.execution.exit_policy import institutional_lock
    mt5.initialize()
    off = broker_utc_offset(mt5_module=mt5, symbols=["EURUSD"]) or 0
    rows = sqlite3.connect("file:data/jarvis_history.db?mode=ro", uri=True).execute(
        "SELECT symbol, action, entry_price, sl, tp, exit_price, timestamp, volume FROM executed_trades "
        "WHERE closed_at IS NOT NULL AND realized_pnl IS NOT NULL AND exit_price IS NOT NULL AND sl > 0 "
        "AND entry_price <> sl AND execution_mode = 'demo' AND COALESCE(regime,'') != 'FORWARD_TEST' "
        "ORDER BY timestamp").fetchall()
    trades = []
    for sym, side, e, s_, tp, x, ts, vol in rows:
        t0 = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() + off
        bars = mt5.copy_rates_range(resolve_broker_symbol(sym, mt5_module=mt5) or sym, mt5.TIMEFRAME_M1,
                                    datetime.fromtimestamp(t0 + 60, timezone.utc),
                                    datetime.fromtimestamp(t0 + 48 * 3600, timezone.utc))
        if bars is None or not len(bars):
            continue
        sg, r = (1 if side == "BUY" else -1), abs(e - s_)
        hi_k, lo_k = ("high", "low") if sg == 1 else ("low", "high")
        trades.append(dict(sym=sym, side=sg, entry=e, risk=r, actual=sg * (x - e) / r,
                           tp_r=sg * (tp - e) / r if tp and sg * (tp - e) > 0 else 2.0,
                           splittable=(vol or 0) >= 0.02,
                           path=[(sg * (b[hi_k] - e) / r, sg * (b[lo_k] - e) / r, sg * (b["close"] - e) / r) for b in bars]))
    mt5.shutdown()
    legacy = ExitPolicy()
    pols = {"actual": "actual", "fixed stop/target": None, "legacy core": legacy,
            "institutional lock": institutional_lock(legacy)}
    n, h = len(trades), len(trades) // 2
    lines = [f"# Exit research on live trades {datetime.now(timezone.utc):%Y-%m-%d}", "",
             f"{n} closed live demo trades, real MT5 M1 bars (48 h each), replayed through `evaluate_exit`. "
             "R per trade; pessimistic intrabar order (adverse before favourable). The legacy core excludes the "
             "monitor's live-only layers, which only the `actual` row includes.", "",
             "| Exits | Total R | Avg R | Win % | 1st half | 2nd half | " + " | ".join(GROUPS) + " | FX |",
             "|---|---|---|---|---|---|" + "---|" * (len(GROUPS) + 1)]
    for name, pol in pols.items():
        v = [t["actual"] if pol == "actual" else replay_live_trade(t, pol) for t in trades]
        grp = [sum(x for x, t in zip(v, trades) if t["sym"] in g) for g in GROUPS.values()]
        fx = sum(x for x, t in zip(v, trades) if not any(t["sym"] in g for g in GROUPS.values()))
        lines.append(f"| {name} | {sum(v):+.1f} | {sum(v) / max(n, 1):+.3f} | {sum(x > 0 for x in v) / max(n, 1) * 100:.0f} | "
                     f"{sum(v[:h]):+.1f} | {sum(v[h:]):+.1f} | " + " | ".join(f"{g:+.1f}" for g in grp) + f" | {fx:+.1f} |")
    open(out_md, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--live-trades":
        return live_trades_main(sys.argv[2] if len(sys.argv) > 2 else "reports/EXIT_LOCK_RESEARCH.md")
    res = research(pickle.load(open(sys.argv[1], "rb")), sys.argv[3:] or None)
    json.dump(res, open(sys.argv[2], "w"), indent=1, default=str)
    print(table(res))


if __name__ == "__main__":
    main()
