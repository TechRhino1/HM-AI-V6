"""USD news research: does the news blackout, pre-release de-risking, or a post-release entry make money
after costs?  Same cost-honest machinery and adoption gate as tools/strategy_research.py (arrays, run,
walk, summarise, verdict); entries are tools/mtf_entry_research.py signals. All parameters fixed a priori.

History (step 1): data/news_history_usd.json -- FOMC / NFP / CPI release times in UTC from the published
schedules (Fed meeting calendars; BLS archive file names and release schedules). NFP/CPI at 08:30 and the
FOMC statement at 14:00 America/New_York, so DST is handled by zoneinfo (12:30/13:30, 18:00/19:00 UTC).
Each event is cross-checked on M5 and M15 bars: the release bar's range must exceed 3x the prior bar's ATR
on at least one symbol, otherwise it is flagged.

Studies (step 2), symbols XAUUSD EURUSD GBPUSD USDJPY USDCAD BTCUSD:
  N1 blackout on entries t in [event - pre, event + post): none vs -10/+15 (live) vs -30/+30.
     Entry proxy: MTF pullback + trigger-TF veto, 1R target, M15 and H1. Judged on trades whose holding
     window [entry, exit) contains an event, and on the whole curve.
  N2 open trades at the last completed bar closing <= release - 10 min: (a) close at the next open if
     >= +0.5R, (b) stop to break-even if in profit, (c) hold (live). Same entries.
  N3 post-release sweep reversal: a bar opening 15-45 min after release trades beyond the 60-min
     pre-release high (low) and closes back inside; then, on that bar or the next 3, a displacement candle
     the other way (body > 70% of range, range > 1.5 x prior ATR). Entry next open, stop beyond the
     sweep wick + 1 ATR, 2R target, 4h time stop. M5 and M15.
  N4 post-release momentum: side of the first 15 min (close at release+15 vs release-bar open); entry at
     release+15, stop beyond the 15-min range's far side + spread + 0.3 ATR (>= 1 ATR), 2R, 4h time stop.
Adoption: N3/N4 sr.verdict and PF > 1.5. N1/N2 vs live only if both the event-trade expectancy and the
max drawdown improve in both halves (split at the median baseline entry time).

Usage:
    python tools/news_research.py --build-history <bars.pkl>   # write data/news_history_usd.json
    python tools/news_research.py <bars.pkl> <out.json>        # run N1-N4, print markdown tables
    python tools/news_research.py --selftest
Results: reports/NEWS_RESEARCH_2026-11-17.md
"""
import os, sys, json, pickle
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_research as sr
import mtf_entry_research as mtf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "data", "news_history_usd.json")
NY = ZoneInfo("America/New_York")
SYMS = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCAD", "BTCUSD")
MIN = sr.NS_MIN
BLACKOUTS = {"none": None, "live -10/+15": (10, 15), "wide -30/+30": (30, 30)}
DERISK = {"hold (live)": None, "close if >= +0.5R": "close", "stop to BE": "be"}
POST = {"tgt": 2.0, "hold_min": 240}

# BLS archive file dates (MMDDYYYY): bls.gov/bls/news-release/empsit.htm and cpi.htm, fetched 2026-11-17;
# dates after 2026-11-10 from bls.gov/schedule/news_release/empsit.htm and cpi.htm.
NFP = """01052018 02022018 03092018 04062018 05042018 06012018 07062018 08032018 09072018 10052018 11022018 12072018
01042019 02012019 03082019 04052019 05032019 06072019 07052019 08022019 09062019 10042019 11012019 12062019
01102020 02072020 03062020 04032020 05082020 06052020 07022020 08072020 09042020 10022020 11062020 12042020
01082021 02052021 03052021 04022021 05072021 06042021 07022021 08062021 09032021 10082021 11052021 12032021
01072022 02042022 03042022 04012022 05062022 06032022 07082022 08052022 09022022 10072022 11042022 12022022
01062023 02032023 03102023 04072023 05052023 06022023 07072023 08042023 09012023 10062023 11032023 12082023
01052024 02022024 03082024 04052024 05032024 06072024 07052024 08022024 09062024 10042024 11012024 12062024
01102025 02072025 03072025 04042025 05022025 06062025 07032025 08012025 09052025 11202025 12162025
01092026 02112026 03062026 04032026 05082026 06052026 07022026 08072026 09042026 10022026 11062026 12042026
01082027 02052027 03052027 04022027 05072027 06042027 07022027 08062027 09032027 10082027 11052027 12032027"""
CPI = """01122018 02142018 03132018 04112018 05102018 06122018 07122018 08102018 09132018 10112018 11142018 12122018
01112019 02132019 03122019 04102019 05102019 06122019 07112019 08132019 09122019 10102019 11132019 12112019
01142020 02132020 03112020 04102020 05122020 06102020 07142020 08122020 09112020 10132020 11122020 12102020
01132021 02102021 03102021 04132021 05122021 06102021 07132021 08112021 09142021 10132021 11102021 12102021
01122022 02102022 03102022 04122022 05112022 06102022 07132022 08102022 09132022 10132022 11102022 12132022
01122023 02142023 03142023 04122023 05102023 06132023 07122023 08102023 09132023 10122023 11142023 12122023
01112024 02132024 03122024 04102024 05152024 06122024 07112024 08142024 09112024 10102024 11132024 12112024
01152025 02122025 03122025 04102025 05132025 06112025 07152025 08122025 09112025 10242025 12182025
01132026 02132026 03112026 04102026 05122026 06102026 07142026 08122026 09112026 10142026 11102026 12102026
01132027 02112027 03102027 04132027 05122027 06102027 07142027 08112027 09142027 10142027 11102027 12102027"""
# Statement (second) day of each scheduled meeting: federalreserve.gov fomccalendars.htm and fomchistorical<year>.htm.
FOMC = {2018: "01-31 03-21 05-02 06-13 08-01 09-26 11-08 12-19", 2019: "01-30 03-20 05-01 06-19 07-31 09-18 10-30 12-11",
        2020: "01-29 04-29 06-10 07-29 09-16 11-05 12-16", 2021: "01-27 03-17 04-28 06-16 07-28 09-22 11-03 12-15",
        2022: "01-26 03-16 05-04 06-15 07-27 09-21 11-02 12-14", 2023: "02-01 03-22 05-03 06-14 07-26 09-20 11-01 12-13",
        2024: "01-31 03-20 05-01 06-12 07-31 09-18 11-07 12-18", 2025: "01-29 03-19 05-07 06-18 07-30 09-17 10-29 12-10",
        2026: "01-28 03-18 04-29 06-17 07-29 09-16 10-28 12-09", 2027: "01-27 03-17 04-28 06-09 07-28 09-15 10-27 11-17"}
FOMC_UNSCHEDULED = (("2020-03-03", "10:00"), ("2020-03-15", "17:00"))  # emergency cuts (ET); March 17-18 2020 cancelled


# ── calendar ─────────────────────────────────────────────────────────────────

def et(day, hhmm):
    """New York wall clock -> UTC datetime (DST from zoneinfo)."""
    return datetime(*map(int, day.split("-")), *map(int, hhmm.split(":")), tzinfo=NY).astimezone(timezone.utc)


def schedule():
    ev = [(name, et(f"{s[4:]}-{s[:2]}-{s[2:4]}", "08:30")) for name, ds in (("NFP", NFP), ("CPI", CPI)) for s in ds.split()]
    ev += [("FOMC", et(f"{y}-{md}", "14:00")) for y, ds in FOMC.items() for md in ds.split()]
    ev += [("FOMC", et(d, hm)) for d, hm in FOMC_UNSCHEDULED]
    return sorted(ev, key=lambda e: e[1])


def first_friday(y, m):
    d = date(y, m, 1)
    return d + timedelta((4 - d.weekday()) % 7)


def ns(t):
    t = pd.Timestamp(t)
    return (t.tz_convert(None) if t.tzinfo else t).value


def load_events(path=HIST):
    ev = json.load(open(path))["events"]
    return np.array(sorted(ns(e["utc_iso"]) for e in ev), dtype=np.int64)


def release_ratio(df, tf, ev_ns):
    """Range of the bar opening at each event / ATR of the bar before; NaN where no such bar."""
    d = sr.gr.prep(df, tf)
    to = d.t_open.values.astype("datetime64[ns]").astype(np.int64)
    rng, atr = (d.high - d.low).to_numpy(), d.atr.shift().to_numpy()
    k = np.minimum(np.searchsorted(to, ev_ns), len(to) - 1)
    return np.where((to[k] == ev_ns) & (k > 0), rng[k] / atr[k], np.nan)


def build_history(bars_path):
    ev = schedule()
    data = pickle.load(open(bars_path, "rb"))
    e_ns = np.array([ns(t) for _, t in ev], dtype=np.int64)
    check = {"rule": "release bar range > 3 x prior-bar ATR(14) on at least one of " + ", ".join(SYMS)
                     + "; 'dst_ok' = share of checked events whose stated-time ratio beats the same time +-1h"}
    for tf in ("M5", "M15"):
        r = np.array([[release_ratio(data[s]["frames"][tf], tf, e_ns + off) for s in SYMS]
                      for off in (0, -3600 * 10**9, 3600 * 10**9)])        # (offset, symbol, event)
        best = np.nanmax(np.where(np.isnan(r), -1, r), axis=1)              # (offset, event); -1 = no bar
        seen = best[0] >= 0
        flagged = [{"event": ev[k][0], "utc_iso": ev[k][1].isoformat(), "max_ratio": round(float(best[0, k]), 2)}
                   for k in np.flatnonzero(seen & (best[0] <= 3))]
        check[tf] = {"checked": int(seen.sum()), "flagged": flagged,
                     "dst_ok": round(float(((best[0] > best[1]) & (best[0] > best[2]))[seen].mean()), 3),
                     "median_ratio": round(float(np.median(best[0][seen])), 2)}
    exc = [t.date().isoformat() for name, t in ev if name == "NFP"
           and t.astimezone(NY).date() != first_friday(t.astimezone(NY).year, t.astimezone(NY).month)]
    out = {"format": "events: list of {event, currency, utc_iso, impact}. event is FOMC | NFP | CPI, currency USD, "
                     "utc_iso the release time in UTC (ISO 8601), impact HIGH. NFP/CPI 08:30 and FOMC statement 14:00 "
                     "America/New_York (12:30/13:30 and 18:00/19:00 UTC by DST); 2020-03-03 and 2020-03-15 are "
                     "unscheduled FOMC cuts. Future dates are only those published on 2026-11-17 (BLS through "
                     "Dec 2027, Fed through Nov 2027): extend before relying on this file past them.",
           "built_by": "tools/news_research.py --build-history",
           "sources": {"NFP": "bls.gov/bls/news-release/empsit.htm + bls.gov/schedule/news_release/empsit.htm",
                       "CPI": "bls.gov/bls/news-release/cpi.htm + bls.gov/schedule/news_release/cpi.htm",
                       "FOMC": "federalreserve.gov/monetarypolicy/fomccalendars.htm + fomchistorical2018-2020.htm"},
           "nfp_not_first_friday": exc,
           "events": [{"event": n, "currency": "USD", "utc_iso": t.isoformat(), "impact": "HIGH"} for n, t in ev],
           "bar_check": check}
    json.dump(out, open(HIST, "w"), indent=1)
    print(len(ev), "events ->", HIST)
    print(json.dumps(check, indent=1))


# ── event-window arithmetic ─────────────────────────────────────────────────

def blocked(t, ev, pre, post):
    """True if entry time t is in [e - pre, e + post) for some event e (all ns, pre/post minutes)."""
    return np.searchsorted(ev, t + pre * MIN, "right") > np.searchsorted(ev, t - post * MIN, "right")


def overlaps(t_in, t_out, ev):
    """An event in [t_in, t_out)."""
    return np.searchsorted(ev, t_out) > np.searchsorted(ev, t_in)


def derisk_bars(tc, ev, tf_min, lead=10):
    """dr[k]: bar k is the last completed bar closing <= release - lead min (and not a stale bar)."""
    dr = np.zeros(len(tc), bool)
    t = ev - lead * MIN
    k = np.searchsorted(tc, t, "right") - 1
    ok = (k >= 0) & (t - tc[np.maximum(k, 0)] < tf_min * MIN)
    dr[k[ok]] = True
    return dr


# ── simulation ───────────────────────────────────────────────────────────────

def walk(A, i, side, sd, ex, dr=None, mode=None):
    """sr.walk for {tgt, max_bars} exits plus a pre-release action at dr bars. Returns (R, exit bar, open at a dr bar)."""
    o, h, l, c, spr, slip = A["o"], A["h"], A["l"], A["c"], A["spr"], A["slip"]
    n, j0 = len(o), i + 1
    if j0 >= n:
        return None
    entry = o[j0] + spr[j0] if side == 1 else o[j0]
    stop, tgt, hit = entry - side * sd, entry + side * ex["tgt"] * sd, False

    def fin(px, j):
        nights = A["W"][A["day"][j] - A["d0"]] - A["W"][A["day"][j0] - A["d0"]]
        return (side * (px - entry) + nights * sr.swap_px(A["info"], side, entry)) / sd, j, hit

    for j in range(j0, n):
        if side == 1:
            if l[j] <= stop:
                return fin(min(o[j], stop) - slip, j)
            if h[j] >= tgt:
                return fin(tgt, j)
            px = c[j]
        else:
            if h[j] + spr[j] >= stop:
                return fin(max(o[j] + spr[j], stop) + slip, j)
            if l[j] + spr[j] <= tgt:
                return fin(tgt, j)
            px = c[j] + spr[j]
        out = j - j0 + 1 >= ex["max_bars"]
        if dr is not None and dr[j] and not out:
            hit, u = True, side * (px - entry) / sd
            if mode == "close" and u >= 0.5:
                out = True
            elif mode == "be" and u > 0:
                stop = max(stop, entry) if side == 1 else min(stop, entry)
        if out:
            if j + 1 >= n:
                return None
            return fin(o[j + 1] - slip if side == 1 else o[j + 1] + spr[j + 1] + slip, j + 1)
    return None


def trades(A, sig, ex, ev, block=None, dr=None, mode=None):
    """One position at a time -> rows (t_in, t_out, R, open-at-derisk)."""
    rows, busy, n = [], -1, len(A["o"])
    for i, side, sd in sig:
        if i < busy or not sd > 0 or i + 1 >= n:
            continue
        if block and blocked(A["to"][i + 1], ev, *block):
            continue
        w = walk(A, i, side, sd, ex, dr, mode)
        if w is None:
            continue
        r, j, hit = w
        rows.append((A["to"][i + 1], A["tc"][j], r, hit))
        busy = j
    return rows


def entry_setup(P, tf, info, slip, weekends):
    """tools/mtf_entry_research.py frame + pullback/veto signals (the variant nearest the live engine)."""
    htf, ltf = mtf.PAIRS[tf]
    hd, ld = P[htf].copy(), P[ltf].copy()
    hd["trend"], ld["bias"] = mtf.htf_trend(hd), mtf.bias(ld)
    e = sr.gr.attach(P[tf], hd, ["trend"], "h_")
    e = sr.gr.attach(e, ld, ["bias"], "l_").reset_index(drop=True)
    A = sr.arrays(e, info, slip, weekends)
    return A, mtf.signals(e, A, "pullback", "veto")


# ── post-release entries ─────────────────────────────────────────────────────

def n3_signals(A, ev):
    o, h, l, c, atr, to = A["o"], A["h"], A["l"], A["c"], A["atr"], A["to"]
    n, sig = len(o), []
    for e in ev:
        k0, kp = np.searchsorted(to, e), np.searchsorted(to, e - 60 * MIN)
        if k0 >= n or to[k0] != e or k0 - kp < 2:
            continue
        hi, lo = h[kp:k0].max(), l[kp:k0].min()
        found = False
        for s in range(np.searchsorted(to, e + 15 * MIN), np.searchsorted(to, e + 45 * MIN)):
            side = -1 if h[s] > hi and c[s] < hi else 1 if l[s] < lo and c[s] > lo else 0
            for d in range(s, min(s + 4, n - 1)) if side else ():
                rg = h[d] - l[d]
                if rg > 0 and side * (c[d] - o[d]) > 0.7 * rg and rg > 1.5 * atr[d - 1]:
                    ext = h[s:d + 1].max() if side == -1 else l[s:d + 1].min()
                    sig.append((d, side, side * (c[d] - ext) + atr[d]))
                    found = True
                    break
            if found:
                break
    return sig


def n4_signals(A, ev):
    o, h, l, c, atr, spr, to, tc = A["o"], A["h"], A["l"], A["c"], A["atr"], A["spr"], A["to"], A["tc"]
    n, sig = len(o), []
    for e in ev:
        k0, k = np.searchsorted(to, e), np.searchsorted(tc, e + 15 * MIN)
        if k >= n - 1 or to[k0] != e or tc[k] != e + 15 * MIN:
            continue
        side = int(np.sign(c[k] - o[k0]))
        if side:
            far = c[k] - l[k0:k + 1].min() if side == 1 else h[k0:k + 1].max() - c[k]
            sig.append((k, side, max(far + spr[k] + 0.3 * atr[k], atr[k])))
    return sig


def gate(s, name, tf):
    ok, why, _ = sr.verdict(s, name, tf)
    if s["strategy"]["n"] and (s["strategy"]["pf"] or 0) <= 1.5:
        why.append(f"PF {s['strategy']['pf']} <= 1.5")
    return not why, why


def pooled(raws):
    p = sr.pool(raws)
    s = {k: sr.gr.stats(p[k], p["time"]) for k in ("strategy", "always_long", "flipped", "spread_x2")}
    s["afford_100"] = 1.0   # pooled across symbols: edge tests only, affordability is per symbol
    return s


# ── study ───────────────────────────────────────────────────────────────────

def half_stats(rows, split, subset):
    out = {}
    for half in ("all", "h1", "h2"):
        r = np.array([x[2] for x in rows if subset(x) and (half == "all" or (x[0] < split) == (half == "h1"))])
        eq = np.r_[0, np.cumsum(r)]
        out[half] = {"n": len(r), "exp": round(float(r.mean()), 3) if len(r) else None, "total": round(float(r.sum()), 1),
                     "dd": round(float(np.max(np.maximum.accumulate(eq) - eq)), 1)}
    return out


def better(v, ref):
    return all(v[h]["exp"] is not None and ref[h]["exp"] is not None and v[h]["exp"] > ref[h]["exp"]
               and v[h]["dd"] < ref[h]["dd"] for h in ("h1", "h2"))


def research(data):
    ev = load_events()
    res = {"N1": {}, "N2": {}, "N3": {}, "N4": {}}
    pre = {name: mtf.frames(name, data[name]) for name in SYMS}
    for tf in ("M15", "H1"):
        rows1, rows2 = {k: [] for k in BLACKOUTS}, {k: [] for k in DERISK}
        for name in SYMS:
            info, P, slip, weekends, _ = pre[name]
            A, sig = entry_setup(P, tf, info, slip, weekends)
            ex = {"tgt": 1.0, "max_bars": mtf.MAX_BARS[tf]}
            dr = derisk_bars(A["tc"], ev, sr.gr.TF_MIN[tf])
            for k, b in BLACKOUTS.items():
                rows1[k] += trades(A, sig, ex, ev, block=b)
            for k, m in DERISK.items():
                rows2[k] += trades(A, sig, ex, ev, dr=dr, mode=m or "hold")
        for study, rows, ref, sub in (("N1", rows1, "live -10/+15", lambda x: overlaps(x[0], x[1], ev)),
                                      ("N2", rows2, "hold (live)", lambda x: x[3])):
            for k in rows:
                rows[k].sort(key=lambda x: x[0])
            split = np.median([x[0] for x in rows[ref]])
            res[study][tf] = {"split": str(pd.Timestamp(int(split)))}
            for k, rs in rows.items():
                res[study][tf][k] = {"event": half_stats(rs, split, sub), "full": half_stats(rs, split, lambda x: True)}
            for k in rows:
                if k != ref:
                    res[study][tf][k]["adopt_vs_live"] = better(res[study][tf][k]["event"], res[study][tf][ref]["event"])
    for study, fn in (("N3", n3_signals), ("N4", n4_signals)):
        for tf in ("M5", "M15"):
            raws = []
            for name in SYMS:
                info, P, slip, weekends, real_start = pre[name]
                A = sr.arrays(P[tf], info, slip, weekends)
                raw = sr.run(A, fn(A, ev), {"tgt": POST["tgt"], "max_bars": POST["hold_min"] // sr.gr.TF_MIN[tf]})
                s = sr.summarise(raw, info, real_start)
                ok, why = gate(s, name, tf)
                res[study][f"{name}|{tf}"] = {"s": s, "adopt": ok, "why": why}
                raws.append(raw)
            s = pooled(raws)
            ok, why = gate(s, "pooled", tf)
            res[study][f"pooled|{tf}"] = {"s": s, "adopt": ok, "why": why}
    return res


def tables(res):
    out = []
    for study, ref in (("N1", "live -10/+15"), ("N2", "hold (live)")):
        out += [f"\n### {study}", "| TF | Variant | Event trades n (h1/h2) | Event exp R h1 / h2 | Event max DD R h1 / h2 "
                "| Event total R | All trades n | All exp R | All total R | All max DD R | Adopt vs live |", "|" + "---|" * 11]
        for tf, d in res[study].items():
            for k, v in d.items():
                if k == "split":
                    continue
                e, f = v["event"], v["full"]
                verdict = "reference" if k == ref else ("**ADOPT**" if v["adopt_vs_live"] else "reject")
                out.append(f"| {tf} | {k} | {e['all']['n']} ({e['h1']['n']}/{e['h2']['n']}) | {e['h1']['exp']} / {e['h2']['exp']} | "
                           f"{e['h1']['dd']} / {e['h2']['dd']} | {e['all']['total']} | {f['all']['n']} | {f['all']['exp']} | "
                           f"{f['all']['total']} | {f['all']['dd']} | {verdict} |")
    for study in ("N3", "N4"):
        out += [f"\n### {study}", "| Symbol | TF | n | Win | Exp R | PF | 1st half | 2nd half | Spread x2 | Always long | Flipped "
                "| Max DD R | Verdict |", "|" + "---|" * 13]
        for key, v in res[study].items():
            name, tf = key.split("|")
            s = v["s"]
            st = s["strategy"]
            if not st["n"]:
                out.append(f"| {name} | {tf} | 0 |" + " |" * 9 + " reject: no trades |")
                continue
            out.append(f"| {name} | {tf} | {st['n']} | {st['wr']:.0%} | {st['exp_r']:+.3f} | {st['pf']} | {st['h1_exp']:+.3f} | "
                       f"{st['h2_exp']:+.3f} | {s['spread_x2']['exp_r']:+.3f} | {s['always_long']['exp_r']:+.3f} | "
                       f"{s['flipped']['exp_r']:+.3f} | {st['max_dd_r']} | "
                       + ("**ADOPT**" if v["adopt"] else "reject: " + "; ".join(v["why"])) + " |")
    return "\n".join(out)


# ── checks ───────────────────────────────────────────────────────────────────

def selftest():
    utc = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    # DST: US clocks change 2026-03-08 and 2026-11-01; 2018-11-04
    assert et("2026-03-06", "08:30") == utc("2026-03-06T13:30")   # EST
    assert et("2026-03-11", "08:30") == utc("2026-03-11T12:30")   # EDT, 3 days after the change
    assert et("2026-10-02", "08:30") == utc("2026-10-02T12:30")
    assert et("2026-11-06", "08:30") == utc("2026-11-06T13:30")   # back on EST
    assert et("2026-07-29", "14:00") == utc("2026-07-29T18:00") and et("2026-12-09", "14:00") == utc("2026-12-09T19:00")
    assert et("2018-11-08", "14:00") == utc("2018-11-08T19:00") and et("2018-11-02", "08:30") == utc("2018-11-02T12:30")
    ev = schedule()
    assert len({t for _, t in ev}) == len(ev)
    for name, t in ev:
        ok = ((12, 30), (13, 30)) if name != "FOMC" else ((18, 0), (19, 0), (15, 0), (21, 0))
        assert (t.hour, t.minute) in ok, (name, t)
    assert first_friday(2026, 5) == date(2026, 5, 1) and first_friday(2026, 8) == date(2026, 8, 7)
    # window arithmetic: event 12:30, half-open [e - pre, e + post)
    e = np.array([pd.Timestamp("2026-06-05 12:30").value])
    T = lambda s: pd.Timestamp(f"2026-06-05 {s}").value
    assert blocked(T("12:20"), e, 10, 15) and not blocked(T("12:19"), e, 10, 15)
    assert blocked(T("12:44"), e, 10, 15) and not blocked(T("12:45"), e, 10, 15)
    assert blocked(T("12:00"), e, 30, 30) and blocked(T("12:59"), e, 30, 30) and not blocked(T("13:00"), e, 30, 30)
    assert overlaps(T("12:30"), T("12:45"), e) and not overlaps(T("12:00"), T("12:30"), e)
    # de-risk decision bar: last close <= 12:20 -> M15 bar closing 12:15, H1 bar closing 12:00
    for tf_min, want in ((15, "12:15"), (60, "12:00")):
        tc = np.array([T("09:00") + k * tf_min * MIN for k in range(1, 400 // tf_min)])
        dr = derisk_bars(tc, e, tf_min)
        assert dr.sum() == 1 and tc[dr][0] == T(want), (tf_min, tc[dr])
    # walk() without a de-risk action reproduces sr.walk
    rng = np.random.default_rng(1)
    n = 600
    c = 100 + np.cumsum(rng.normal(0, 0.3, n))
    o = np.r_[100, c[:-1]]
    hh, ll = np.maximum(o, c) + rng.random(n) * 0.3, np.minimum(o, c) - rng.random(n) * 0.3
    info = {"price_now": 100.0, "point": 0.01, "trade_tick_value": 1.0, "trade_tick_size": 0.01,
            "swap_long": -5.0, "swap_short": -5.0, "swap_mode": 1, "swap_rollover3days": 3}
    A = {"o": o, "h": hh, "l": ll, "c": c, "spr": np.full(n, 0.05), "atr": np.ones(n), "slip": 0.02, "info": info,
         "to": np.arange(n) * 15 * MIN, "tc": (np.arange(n) + 1) * 15 * MIN, "day": 20_000 + np.arange(n) // 96}
    A["d0"], A["W"] = sr.night_weights(A["day"], info, False)
    for i in rng.integers(0, n - 50, 200):
        side, sd = int(rng.choice([-1, 1])), float(rng.uniform(0.3, 2))
        a, b = walk(A, i, side, sd, {"tgt": 1.0, "max_bars": 32}), sr.walk(A, i, side, sd, {"tgt": 1.0, "max_bars": 32}, side)
        assert (a is None and b is None) or (abs(a[0] - b[0]) < 1e-12 and a[1] == b[1])
    # close if >= +0.5R: buy at 100.05, sd 1; bar 2 closes 100.7 (+0.65R) on the de-risk bar -> exit at bar 3 open - slip
    m = 6
    B = {**A, "o": np.array([100, 100, 100.3, 100.6, 100.6, 100.6]), "c": np.array([100, 100.3, 100.7, 100.6, 100.6, 100.6]),
         "spr": np.full(m, 0.05), "day": np.full(m, 20_000)}
    B["h"], B["l"] = B["c"] + 0.1, B["o"] - 0.1
    B["d0"], B["W"] = sr.night_weights(B["day"], info, False)
    dr = np.zeros(m, bool); dr[2] = True
    ex = {"tgt": 2.0, "max_bars": 4}
    r, j, hit = walk(B, 0, 1, 1.0, ex, dr, "close")
    assert j == 3 and hit and abs(r - (100.6 - 0.02 - 100.05)) < 1e-9
    r, j, hit = walk(B, 0, 1, 1.0, ex, dr, "hold")
    assert hit and j == 5                                                      # held to the 4-bar time stop
    B["l"] = np.array([99.9, 99.9, 100.2, 100.0, 99.0, 99.0])                 # bar 3 trades through the BE stop
    r, j, _ = walk(B, 0, 1, 1.0, ex, dr, "be")
    assert j == 3 and abs(r - (-0.02)) < 1e-9
    if os.path.exists(HIST):
        h = json.load(open(HIST))
        assert set(h["events"][0]) == {"event", "currency", "utc_iso", "impact"} and len(h["events"]) == len(ev)
    print("selftest ok")


def main():
    if sys.argv[1] == "--selftest":
        return selftest()
    if sys.argv[1] == "--build-history":
        return build_history(sys.argv[2])
    res = research(pickle.load(open(sys.argv[1], "rb")))
    json.dump(res, open(sys.argv[2], "w"), indent=1, default=str)
    print(tables(res))


if __name__ == "__main__":
    main()
