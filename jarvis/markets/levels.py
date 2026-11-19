"""Chart intelligence from real bars: support/resistance zones with their measured behaviour, price-action
patterns with their own forward-return record, the engine's live signal for the symbol, and an AI read
grounded only on those facts.

Definitions (fixed constants, so every number can be reproduced from the bars):
  ATR          mean of the last 14 true ranges, using only bars up to that point.
  swing pivot  fractal: a bar whose high (low) is above (below) the FRACTAL bars on each side. It is only
               known FRACTAL bars later; nothing uses it before then.
  zone         levels merged while the zone stays within MERGE_ATR x ATR wide (no chaining). `strength` is a relative ranking
               (touch episodes + 2 per extra confluent source type + 1 if touched in the last 20 bars +
               10 x share of profile volume inside the zone); it is not a probability.
  touch        the first later bar whose range comes within TOUCH_ATR x ATR of the level, approached from
               the side of the previous close.
  hold         after a touch, price reaches HOLD_ATR x ATR away from the level in the reaction direction
               (checked from the bar after the touch) before any close beyond the level.
  break        a close beyond the level comes first (checked from the touch bar). Neither within
               RESOLVE_BARS: unresolved, not counted.
  hold_rate    holds / (holds + breaks) per level type, over every historical instance of that type on this
               symbol and interval, each measured only on bars after the level was known (walk-forward).
  pattern stat signed close-to-close move HORIZON bars after detection, in ATR at detection; win = move > 0.
               Each instance is labelled with stats from earlier instances that had already resolved.
  n < MIN_N    "insufficient history"; no rate is shown.
Types without a measurable history (OI walls, max pain, VWAP) are labelled "context · not validated".
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .data import feeds, yahoo
from .data.models import Provenance, unavailable
from .data.nse import SourceError

logger = logging.getLogger(__name__)

ATR_N = 14
FRACTAL = 2
MERGE_ATR = 0.5
TOUCH_ATR = 0.15
HOLD_ATR = 1.0
RESOLVE_BARS = 30
MAX_WAIT = 300           # a level not touched within this many bars is not counted
HORIZON = 10
MIN_N = 30
LOOKBACK = 300           # bars used for current zones
VP_BARS, VP_STEP, VP_BINS, VALUE_AREA = 200, 50, 48, 0.70
BREAKOUT_RANGE_ATR = 1.5
FALSE_BARS = 3
EQUAL_ATR = 0.1
NOT_VALIDATED = "context · not validated"
INSUFFICIENT = "insufficient history"

# interval -> (yahoo interval, yahoo range, seconds)
YAHOO_INTERVALS = {"M5": ("5m", "60d", 300), "M15": ("15m", "60d", 900), "H1": ("60m", "730d", 3600),
                   "D1": ("1d", "5y", 86400), "W1": ("1wk", "10y", 604800)}
FX_INTERVALS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
FX_BARS = 1500
TZ = {"FX": timezone.utc, "IN": ZoneInfo("Asia/Kolkata"), "US": ZoneInfo("America/New_York")}

_cache: Dict[Tuple, Tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: Tuple, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    with _lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (time.time(), v)
    return v


def ttl_for(interval: str) -> float:
    return 900.0 if interval in ("D1", "W1") else 60.0


def canonical(symbol: str) -> str:
    return re.sub(r"[#.].*$", "", (symbol or "").strip().upper())


# ---------------------------------------------------------------- bars

def _fx_bars(symbol: str, interval: str) -> Dict[str, Any]:
    """Closed broker bars from the same MT5 feed /api/candles serves; volume is the broker's tick volume."""
    if interval not in FX_INTERVALS:
        raise ValueError(f"interval must be one of {sorted(FX_INTERVALS)}")
    from jarvis.api.server import JarvisRequestHandler, _bars_unavailable, _broker_frame
    df = JarvisRequestHandler.data_feed.fetch_rates(symbol, timeframe=interval, num_bars=FX_BARS, include_current_bar=False)
    if not _broker_frame(df):
        return {"bars": [], "prov": _bars_unavailable(df), "volume_kind": None}
    out = []
    for r in df.to_dict(orient="records"):
        t = r["time"]
        if hasattr(t, "tzinfo") and t.tzinfo is None:
            t = t.tz_localize("UTC")
        out.append({"time": int(t.timestamp()) if hasattr(t, "timestamp") else int(t), "open": float(r["open"]),
                    "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"]),
                    "volume": float(r.get("tick_volume", r.get("volume", 0.0)) or 0.0)})
    prov = Provenance(source="mt5:copy_rates_from_pos", kind="live", as_of=float(out[-1]["time"] + FX_INTERVALS[interval]),  # last bar's close
                      note=f"{len(out)} closed broker bars; volume is broker tick volume").to_dict()
    return {"bars": out, "prov": prov, "volume_kind": "tick volume (broker)"}


def fx_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """Last broker price (forming M1 bar close) for FX/gold/crypto alerts; None when the broker returns nothing."""
    from jarvis.api.server import JarvisRequestHandler, _broker_frame
    sym = canonical(symbol)
    df = JarvisRequestHandler.data_feed.fetch_rates(sym, timeframe="M1", num_bars=2, include_current_bar=True)
    if not _broker_frame(df):
        return None
    r = df.iloc[-1]
    t = r["time"]
    ts = float(t.timestamp()) if hasattr(t, "timestamp") else float(t)
    return {"symbol": sym, "price": float(r["close"]), "prov": Provenance(source="mt5:copy_rates_from_pos M1", kind="live", as_of=ts).to_dict()}


def _yahoo_bars(symbol: str, market: str, interval: str) -> Dict[str, Any]:
    if interval not in YAHOO_INTERVALS:
        raise ValueError(f"interval must be one of {sorted(YAHOO_INTERVALS)} for {market}")
    yi, rng, _ = YAHOO_INTERVALS[interval]
    try:
        res = yahoo.bars(symbol, market, yi, rng)
    except SourceError as exc:
        return {"bars": [], "prov": unavailable("yahoo:chart", str(exc)).to_dict(), "volume_kind": None}
    bars = res["bars"][:-1] if res["last_bar_forming"] else res["bars"]
    prov = dict(res["prov"], note=f"{len(bars)} closed bars" + ("; forming bar excluded" if res["last_bar_forming"] else ""))
    return {"bars": bars, "prov": prov, "volume_kind": "exchange volume"}


def get_bars(symbol: str, market: str, interval: str) -> Dict[str, Any]:
    sym = canonical(symbol)
    return _cached(("bars", sym, market, interval), ttl_for(interval),
                   lambda: _fx_bars(sym, interval) if market == "FX" else _yahoo_bars(sym, market, interval))


def has_volume(bars: List[Dict[str, Any]]) -> bool:
    """Volume is usable only when most bars report it (Yahoo intraday indices report zeros)."""
    return bool(bars) and sum(1 for b in bars if b.get("volume", 0) > 0) >= 0.9 * len(bars)


# ---------------------------------------------------------------- primitives

def atr_series(b: List[Dict[str, Any]], n: int = ATR_N) -> List[float]:
    tr = [b[0]["high"] - b[0]["low"]] + [max(x["high"] - x["low"], abs(x["high"] - p["close"]), abs(x["low"] - p["close"]))
                                         for p, x in zip(b, b[1:])]
    out, s = [], 0.0
    for i, v in enumerate(tr):
        s += v - (tr[i - n] if i >= n else 0.0)
        out.append(s / min(i + 1, n))
    return out


def pivots(b: List[Dict[str, Any]], k: int = FRACTAL) -> List[Dict[str, Any]]:
    """Fractal swing highs/lows. `known` is the bar at whose close the pivot is confirmed."""
    out = []
    for i in range(k, len(b) - k):
        h, lo = b[i]["high"], b[i]["low"]
        if all(h > b[j]["high"] for j in range(i - k, i)) and all(h >= b[j]["high"] for j in range(i + 1, i + k + 1)):
            out.append({"i": i, "known": i + k, "price": h, "kind": "swing_high"})
        if all(lo < b[j]["low"] for j in range(i - k, i)) and all(lo <= b[j]["low"] for j in range(i + 1, i + k + 1)):
            out.append({"i": i, "known": i + k, "price": lo, "kind": "swing_low"})
    return sorted(out, key=lambda p: (p["known"], p["i"]))


def volume_profile(b: List[Dict[str, Any]], bins: int = VP_BINS, area: float = VALUE_AREA) -> Optional[Dict[str, Any]]:
    """Each bar's volume spread evenly over the price bins its range covers. POC = fullest bin (centre);
    value area grows from the POC toward the fuller neighbour until it holds `area` of the volume."""
    if not b:
        return None
    lo, hi = min(x["low"] for x in b), max(x["high"] for x in b)
    total = sum(x.get("volume", 0) for x in b)
    if hi <= lo or total <= 0:
        return None
    step = (hi - lo) / bins
    vols = [0.0] * bins
    for x in b:
        a, z = min(bins - 1, int((x["low"] - lo) / step)), min(bins - 1, int((x["high"] - lo) / step))
        share = x.get("volume", 0) / (z - a + 1)
        for j in range(a, z + 1):
            vols[j] += share
    poc = max(range(bins), key=lambda j: vols[j])
    i0 = i1 = poc
    acc = vols[poc]
    while acc < area * total and (i0 > 0 or i1 < bins - 1):
        up = vols[i1 + 1] if i1 < bins - 1 else -1.0
        dn = vols[i0 - 1] if i0 > 0 else -1.0
        if up >= dn:
            i1 += 1
            acc += up
        else:
            i0 -= 1
            acc += dn
    return {"poc": lo + (poc + 0.5) * step, "vah": lo + (i1 + 1) * step, "val": lo + i0 * step,
            "bars": len(b), "bin_size": step, "lo": lo, "hi": hi, "vols": vols, "total": total}


def periods(b: List[Dict[str, Any]], tz, unit: str) -> List[Dict[str, Any]]:
    """Calendar days or ISO weeks in `tz`: [{key, first (bar index), high, low, close}] in order."""
    g: "OrderedDict[Any, Dict[str, Any]]" = OrderedDict()
    for i, x in enumerate(b):
        dt = datetime.fromtimestamp(x["time"], tz)
        k = dt.date() if unit == "day" else tuple(dt.isocalendar()[:2])
        p = g.get(k)
        if p is None:
            g[k] = {"key": k, "first": i, "high": x["high"], "low": x["low"], "close": x["close"]}
        else:
            p["high"], p["low"], p["close"] = max(p["high"], x["high"]), min(p["low"], x["low"]), x["close"]
    return list(g.values())


def previous_period(b, tz, unit: str, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """The last complete period before the current calendar one."""
    ps = periods(b, tz, unit)
    if not ps:
        return None
    dt = datetime.fromtimestamp(now if now is not None else time.time(), tz)
    cur = dt.date() if unit == "day" else tuple(dt.isocalendar()[:2])
    if ps[-1]["key"] == cur:
        return ps[-2] if len(ps) >= 2 else None
    return ps[-1]


def floor_pivots(h: float, lo: float, c: float) -> Dict[str, float]:
    p = (h + lo + c) / 3
    return {"P": p, "R1": 2 * p - lo, "S1": 2 * p - h, "R2": p + (h - lo), "S2": p - (h - lo)}


def session_vwap(b: List[Dict[str, Any]], tz) -> Optional[float]:
    ps = periods(b, tz, "day")
    if not ps:
        return None
    seg = b[ps[-1]["first"]:]
    v = sum(x["volume"] for x in seg)
    return sum((x["high"] + x["low"] + x["close"]) / 3 * x["volume"] for x in seg) / v if v > 0 else None


# ---------------------------------------------------------------- measured level behaviour

def touch_outcome(b: List[Dict[str, Any]], atr: List[float], level: float, start: int) -> Optional[str]:
    """'hold' | 'break' | None for the first touch of `level` at or after bar `start` (see module docstring)."""
    n = len(b)
    for t in range(max(1, start), min(n, start + MAX_WAIT)):
        a = atr[t - 1]
        tol = TOUCH_ATR * a
        if not (b[t]["low"] - tol <= level <= b[t]["high"] + tol):
            continue
        pc = b[t - 1]["close"]
        side = 1 if pc > level else -1 if pc < level else 0
        if not side:
            continue
        for u in range(t, min(n, t + RESOLVE_BARS)):
            if (side > 0 and b[u]["close"] < level) or (side < 0 and b[u]["close"] > level):
                return "break"
            if u > t and ((side > 0 and b[u]["high"] >= level + HOLD_ATR * a) or (side < 0 and b[u]["low"] <= level - HOLD_ATR * a)):
                return "hold"
        return None
    return None


def level_instances(b: List[Dict[str, Any]], tz, vol_ok: bool) -> Dict[str, List[Tuple[float, int]]]:
    """Every historical level by type as (price, first bar index at which it may be used)."""
    out: Dict[str, List[Tuple[float, int]]] = {"swing": [], "prev_day": [], "prev_week": [], "floor_pivot": [], "volume_profile": []}
    for p in pivots(b):
        out["swing"].append((p["price"], p["known"] + 1))
    for unit, key in (("day", "prev_day"), ("week", "prev_week")):
        ps = periods(b, tz, unit)
        for prev, nxt in zip(ps, ps[1:]):
            out[key] += [(prev["high"], nxt["first"]), (prev["low"], nxt["first"]), (prev["close"], nxt["first"])]
            if unit == "day":
                out["floor_pivot"] += [(v, nxt["first"]) for v in floor_pivots(prev["high"], prev["low"], prev["close"]).values()]
    if vol_ok:
        for end in range(VP_BARS, len(b), VP_STEP):
            vp = volume_profile(b[end - VP_BARS:end])
            if vp:
                out["volume_profile"] += [(vp["poc"], end), (vp["vah"], end), (vp["val"], end)]
    return out


def behaviour(b: List[Dict[str, Any]], atr: List[float], tz, vol_ok: bool) -> Dict[str, Dict[str, Any]]:
    out = {}
    for typ, inst in level_instances(b, tz, vol_ok).items():
        res = [touch_outcome(b, atr, px, start) for px, start in inst]
        holds, breaks = res.count("hold"), res.count("break")
        n = holds + breaks
        out[typ] = {"type": typ, "n": n, "holds": holds, "breaks": breaks, "instances": len(inst),
                    "hold_rate": round(holds / n, 3) if n >= MIN_N else None,
                    "label": "measured walk-forward on this symbol's history" if n >= MIN_N else f"{INSUFFICIENT} (n={n})"}
    return out


# ---------------------------------------------------------------- current zones

def _oi_levels(symbol: str) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    from .options import chain_analytics
    try:
        c = feeds.chain(symbol)
    except Exception as exc:  # not an F&O underlying, or the exchange did not answer
        return [], {"note": f"no option chain: {exc}"[:200]}
    an = chain_analytics.analyse(c)
    w = an.get("walls") or {}
    out = [{"price": float(x["strike"]), "type": "oi_wall", "label": f"call OI wall {x['strike']:g} ({x['oi']:,} OI)"} for x in (w.get("resistance") or [])[:3]]
    out += [{"price": float(x["strike"]), "type": "oi_wall", "label": f"put OI wall {x['strike']:g} ({x['oi']:,} OI)"} for x in (w.get("support") or [])[:3]]
    if an.get("max_pain"):
        out.append({"price": float(an["max_pain"]), "type": "max_pain", "label": f"max pain {an['max_pain']:g} ({c.expiry})"})
    return out, {"expiry": c.expiry, "prov": c.prov.to_dict()}


def candidates(b: List[Dict[str, Any]], tz, vol_ok: bool, intraday: bool, now: Optional[float] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    n = len(b)
    recent = b[-LOOKBACK:]
    off = n - len(recent)
    c: List[Dict[str, Any]] = []
    for p in pivots(b):
        if p["i"] >= off:
            c.append({"price": p["price"], "type": "swing", "label": "swing high" if p["kind"] == "swing_high" else "swing low"})
    extra: Dict[str, Any] = {}
    for unit, typ, word in (("day", "prev_day", "prev day"), ("week", "prev_week", "prev week")):
        pp = previous_period(b, tz, unit, now)
        if pp:
            extra[typ] = {"high": pp["high"], "low": pp["low"], "close": pp["close"], "period": str(pp["key"])}
            c += [{"price": pp["high"], "type": typ, "label": f"{word} high"}, {"price": pp["low"], "type": typ, "label": f"{word} low"},
                  {"price": pp["close"], "type": typ, "label": f"{word} close"}]
            if unit == "day":
                fp = floor_pivots(pp["high"], pp["low"], pp["close"])
                extra["floor_pivots"] = fp
                c += [{"price": v, "type": "floor_pivot", "label": f"pivot {k}"} for k, v in fp.items()]
    vp = volume_profile(b[-VP_BARS:]) if vol_ok else None
    if vp:
        extra["volume_profile"] = {k: vp[k] for k in ("poc", "vah", "val", "bars", "bin_size")}
        c += [{"price": vp["poc"], "type": "volume_profile", "label": "POC"}, {"price": vp["vah"], "type": "volume_profile", "label": "VAH"},
              {"price": vp["val"], "type": "volume_profile", "label": "VAL"}]
    if intraday and vol_ok:
        vw = session_vwap(b, tz)
        if vw:
            extra["vwap"] = vw
            c.append({"price": vw, "type": "vwap", "label": "session VWAP"})
    return c, {**extra, "_vp": vp}


def merge_zones(cands: List[Dict[str, Any]], atr_now: float) -> List[Dict[str, Any]]:
    zones: List[Dict[str, Any]] = []
    for x in sorted(cands, key=lambda c: c["price"]):
        z = zones[-1] if zones else None
        if z and x["price"] - z["lo"] <= MERGE_ATR * atr_now:  # width-capped, so zones cannot chain
            z["hi"] = x["price"]
            z["members"].append(x)
        else:
            zones.append({"lo": x["price"], "hi": x["price"], "members": [x]})
    for z in zones:
        z["price"] = sum(m["price"] for m in z["members"]) / len(z["members"])
        z["types"] = sorted({m["type"] for m in z["members"]})
        cnt: "OrderedDict[str, int]" = OrderedDict()
        for m in z["members"]:
            cnt[m["label"]] = cnt.get(m["label"], 0) + 1
        z["sources"] = [f"{k} x{v}" if v > 1 else k for k, v in cnt.items()]
        z["confluence"] = len(z["types"])
    return zones


def _touch_stats(b: List[Dict[str, Any]], lo: float, hi: float, tol: float) -> Tuple[int, Optional[int]]:
    episodes, last, inside = 0, None, False
    for i, x in enumerate(b):
        hit = x["low"] - tol <= hi and x["high"] + tol >= lo
        if hit and not inside:
            episodes += 1
        if hit:
            last = i
        inside = hit
    return episodes, (len(b) - 1 - last) if last is not None else None


def zones_for(b: List[Dict[str, Any]], tz, intraday: bool, vol_ok: bool, extra_cands: List[Dict[str, Any]] = (),
              beh: Optional[Dict[str, Dict[str, Any]]] = None, now: Optional[float] = None, per_side: int = 6) -> Dict[str, Any]:
    atr = atr_series(b)
    a = atr[-1]
    cands, extra = candidates(b, tz, vol_ok, intraday, now)
    zones = merge_zones(cands + list(extra_cands), a)
    vp = extra.pop("_vp")
    beh = beh if beh is not None else behaviour(b, atr, tz, vol_ok)
    last = b[-1]["close"]
    recent = b[-LOOKBACK:]
    for z in zones:
        touches, since = _touch_stats(recent, z["lo"], z["hi"], TOUCH_ATR * a)
        vshare = None
        if vp:
            j0 = max(0, int((z["lo"] - vp["lo"]) / vp["bin_size"]))
            j1 = min(VP_BINS - 1, int((z["hi"] - vp["lo"]) / vp["bin_size"]))
            vshare = round(sum(vp["vols"][j0:j1 + 1]) / vp["total"], 3) if j1 >= j0 else 0.0
        z.update(touches=touches, bars_since_touch=since, volume_share=vshare,
                 strength=round(touches + 2 * (z["confluence"] - 1) + (1 if since is not None and since <= 20 else 0) + 10 * (vshare or 0), 1),
                 role="resistance" if z["price"] > last else "support",
                 distance_atr=round((z["price"] - last) / a, 2) if a else None)
        measured = [beh[t] for t in z["types"] if t in beh]
        best = max(measured, key=lambda s: s["n"]) if measured else None
        z["behaviour"] = measured
        if best and best["hold_rate"] is not None:
            z.update(hold_rate=best["hold_rate"], n=best["n"], hold_basis=best["type"], label=best["label"])
        else:
            z.update(hold_rate=None, n=best["n"] if best else 0, hold_basis=best["type"] if best else None,
                     label=best["label"] if best else NOT_VALIDATED)
        del z["members"]
    above = sorted([z for z in zones if z["role"] == "resistance"], key=lambda z: z["price"])[:per_side]
    below = sorted([z for z in zones if z["role"] == "support"], key=lambda z: -z["price"])[:per_side]
    # option-chain levels (OI walls, max pain) are kept even when farther than the nearest per_side zones
    keep = above + below + [z for z in zones if {"oi_wall", "max_pain"} & set(z["types"]) and z not in above and z not in below]
    return {"zones": sorted(keep, key=lambda z: z["price"]), "atr": a, "last_close": last, "behaviour": beh, **extra}


def levels(symbol: str, market: str, interval: str) -> Dict[str, Any]:
    sym, market = canonical(symbol), (market or "FX").upper()

    def build():
        src = get_bars(sym, market, interval)
        b = src["bars"]
        base = {"symbol": sym, "market": market, "interval": interval, "definitions": DEFINITIONS}
        if len(b) < 50:
            return {**base, "zones": [], "prov": src["prov"] if not b else unavailable(src["prov"].get("source", ""), f"only {len(b)} bars").to_dict()}
        vol_ok = has_volume(b)
        intraday = interval not in ("D1", "W1")
        oi, oi_meta = (_oi_levels(sym) if market == "IN" else ([], None))
        out = zones_for(b, TZ.get(market, timezone.utc), intraday, vol_ok, oi)
        out["volume"] = {"used": vol_ok, "kind": src["volume_kind"] if vol_ok else None,
                         "note": None if vol_ok else "no usable volume from this source; volume profile and VWAP skipped"}
        if oi_meta:
            out["options"] = oi_meta
        return {**base, **out, "bars_used": len(b), "prov": src["prov"]}
    return _cached(("levels", sym, market, interval), ttl_for(interval), build)


DEFINITIONS = {
    "hold": f"after a touch, price moved {HOLD_ATR:g}xATR away from the level before any close beyond it (within {RESOLVE_BARS} bars)",
    "break": "a close beyond the level came first",
    "hold_rate": f"holds / (holds + breaks) over every past level of that type on this symbol and interval, measured only on bars after each level was known; shown only when n >= {MIN_N}",
    "strength": "relative ranking: touch episodes + 2 per extra source type + 1 if touched in the last 20 bars + 10 x share of profile volume; not a probability",
    "pattern_stats": f"signed close-to-close move {HORIZON} bars after detection, in ATR; win = move > 0; from earlier instances that had already resolved",
}


# ---------------------------------------------------------------- patterns

def detect_patterns(b: List[Dict[str, Any]], atr: List[float]) -> List[Dict[str, Any]]:
    """Each event is detected at the close of bar `i`, using only pivots confirmed by bar i-1."""
    piv = pivots(b)
    ev: List[Dict[str, Any]] = []
    k = 0
    hi = lo = None              # last confirmed, not yet broken, swing high / low
    highs: List[Dict[str, Any]] = []
    lows: List[Dict[str, Any]] = []
    trend = 0
    pending: List[Tuple[int, int, float]] = []
    swept: set = set()
    for i in range(1, len(b)):
        while k < len(piv) and piv[k]["known"] <= i - 1:
            p = piv[k]
            if p["kind"] == "swing_high":
                hi = p
                highs.append(p)
            else:
                lo = p
                lows.append(p)
            k += 1
        a, x, pc = atr[i - 1], b[i], b[i - 1]["close"]
        c, rng = x["close"], x["high"] - x["low"]

        def add(kind, d, level, note):
            ev.append({"i": i, "time": x["time"], "kind": kind, "direction": "up" if d > 0 else "down", "dir": d,
                       "price": c, "level": level, "note": note})

        for j, d, lvl in list(pending):
            if i - j > FALSE_BARS:
                pending.remove((j, d, lvl))
            elif (d > 0 and c < lvl) or (d < 0 and c > lvl):
                add("false_breakout", -d, lvl, f"closed back {'below' if d > 0 else 'above'} {lvl:g} {i - j} bar(s) after breaking it")
                pending.remove((j, d, lvl))
        for d, sw in ((1, hi), (-1, lo)):
            if sw and ((d > 0 and pc <= sw["price"] < c) or (d < 0 and pc >= sw["price"] > c)):
                kind = "choch" if trend == -d else "bos"
                add(kind, d, sw["price"], f"close {'above swing high' if d > 0 else 'below swing low'} {sw['price']:g}"
                    + (" against the prior swing sequence" if kind == "choch" else ""))
                trend = d
                if rng >= BREAKOUT_RANGE_ATR * a:
                    add("breakout", d, sw["price"], f"range {rng / a:.1f}xATR")
                    pending.append((i, d, sw["price"]))
                if d > 0:
                    hi = None
                else:
                    lo = None
        for d, pool in ((-1, highs), (1, lows)):
            if len(pool) >= 2:
                p1, p2 = pool[-2], pool[-1]
                if abs(p1["price"] - p2["price"]) <= EQUAL_ATR * a and (p1["i"], p2["i"]) not in swept:
                    lvl = max(p1["price"], p2["price"]) if d < 0 else min(p1["price"], p2["price"])
                    if (d < 0 and x["high"] > lvl and c < lvl) or (d > 0 and x["low"] < lvl and c > lvl):
                        add("liquidity_sweep", d, lvl, f"wick through equal {'highs' if d < 0 else 'lows'} {lvl:g}, closed back")
                        swept.add((p1["i"], p2["i"]))
    return ev


def _stats(moves: List[float]) -> Dict[str, Any]:
    n = len(moves)
    if n < MIN_N:
        return {"n": n, "win_rate": None, "mean_atr": None, "label": f"{INSUFFICIENT} (n={n})"}
    return {"n": n, "win_rate": round(sum(1 for m in moves if m > 0) / n, 3), "mean_atr": round(sum(moves) / n, 3),
            "label": f"{HORIZON}-bar forward, measured on prior instances"}


def pattern_stats(b: List[Dict[str, Any]], atr: List[float], ev: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Attach to each event the stats of earlier, already-resolved events of the same kind; return the per-kind summary."""
    n = len(b)
    for e in ev:
        i = e["i"]
        e["fwd_atr"] = round((b[i + HORIZON]["close"] - b[i]["close"]) * e["dir"] / atr[i], 3) if i + HORIZON < n and atr[i] else None
    summary = {}
    for kind in sorted({e["kind"] for e in ev}):
        same = [e for e in ev if e["kind"] == kind]
        for e in same:
            e["stats"] = _stats([p["fwd_atr"] for p in same if p["i"] + HORIZON <= e["i"] and p["fwd_atr"] is not None])
        summary[kind] = _stats([p["fwd_atr"] for p in same if p["fwd_atr"] is not None])
    return summary


def patterns(symbol: str, market: str, interval: str, keep_bars: int = LOOKBACK) -> Dict[str, Any]:
    sym, market = canonical(symbol), (market or "FX").upper()

    def build():
        src = get_bars(sym, market, interval)
        b = src["bars"]
        base = {"symbol": sym, "market": market, "interval": interval, "horizon_bars": HORIZON}
        if len(b) < 50:
            return {**base, "events": [], "summary": {}, "prov": src["prov"]}
        atr = atr_series(b)
        ev = detect_patterns(b, atr)
        summary = pattern_stats(b, atr, ev)
        cut = len(b) - keep_bars
        recent = [{k: v for k, v in e.items() if k not in ("i", "dir")} for e in ev if e["i"] >= cut]
        return {**base, "events": recent, "summary": summary, "bars_used": len(b), "prov": src["prov"]}
    return _cached(("patterns", sym, market, interval), ttl_for(interval), build)


# ---------------------------------------------------------------- live engine signal

_PEN_RE = re.compile(r"penalty too high \(([\d.]+) / ([\d.]+)\)")
_ADVERSE: Dict[Tuple[str, str], Tuple[float, List[Dict[str, Any]]]] = {}


def _adverse(symbol: str, side: str) -> List[Dict[str, Any]]:
    key = (symbol, side)
    hit = _ADVERSE.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    from . import inst_global
    flags = inst_global.adverse_flags(symbol, side)
    _ADVERSE[key] = (time.time(), flags)
    return flags


def _ts(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.strptime(str(v)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()  # engine writes UTC
    except ValueError:
        return None


def signal_overlay(symbol: str, snap: Optional[Dict[str, Any]] = None, adverse=None) -> Dict[str, Any]:
    sym = canonical(symbol)
    if snap is None:
        from jarvis.application.state_manager import GLOBAL_STATE
        snap = GLOBAL_STATE.get_state_snapshot()
    adverse = adverse or _adverse
    d = (snap.get("latest_decisions") or {}).get(sym)
    rows = [r for r in snap.get("radar_opportunities") or [] if canonical(r.get("symbol", "")) == sym]
    radar = next((r for r in rows if d and r.get("trade_style") == d.get("trade_style")), rows[0] if rows else None)
    out: Dict[str, Any] = {"symbol": sym, "engine": None, "positions": [], "adverse_flags": []}
    as_of = _ts(d.get("timestamp")) if d else None
    if d:
        qg = d.get("quality_gate") or {}
        checks = dict(qg.get("checks") or (radar or {}).get("checks") or {})
        failing = list(qg.get("failing_reasons") or (radar or {}).get("failing_reasons") or [])
        devil_src = d.get("devil") or {}
        pen = devil_src.get("penalty", d.get("adversarial_penalty"))
        thr = None
        for r in d.get("rejection_reasons") or []:
            m = _PEN_RE.search(r)
            if m:
                pen, thr = float(m.group(1)), float(m.group(2))
        threats = devil_src.get("threats") or devil_src.get("threats_detected") or d.get("threats_detected") \
            or [r.split(": ", 1)[1] for r in d.get("rejection_reasons") or [] if r.startswith("Adversarial risk: ")] or d.get("risk_factors") or []
        devil = {"penalty": pen, "threshold": thr, "threats": threats,
                 "gate_passed": checks.get("Devil Adversarial Guard"),
                 "calibrated_loss_prob": devil_src.get("calibrated_loss_prob", d.get("calibrated_loss_prob")),
                 "calibration_group": devil_src.get("calibration_group", d.get("calibration_group")),
                 "threat_stats": devil_src.get("threat_stats", d.get("threat_stats")) or []}
        blocked = [g for g, ok in checks.items() if ok is False]
        chips = []
        for g in blocked:
            if g == "Devil Adversarial Guard":
                if devil["calibrated_loss_prob"] is not None:
                    chips.append(f"Blocked by: {g} (calibrated loss prob {devil['calibrated_loss_prob'] * 100:.0f}%)")
                elif pen is not None and thr is not None:
                    chips.append(f"Blocked by: {g} (penalty {pen:g} > {thr:g})")
                else:
                    chips.append(f"Blocked by: {g}" + (f" (penalty {pen:g})" if pen is not None else ""))
            else:
                chips.append(f"Blocked by: {g}")
        reg = d.get("regime")
        side = str(d.get("bias") or "").upper()
        out["engine"] = {
            "decision": d.get("decision"), "side": side, "strategy": d.get("strategy"), "trade_style": d.get("trade_style"),
            "entry": d.get("entry_price"), "stop_loss": d.get("stop_loss"), "take_profit": d.get("take_profit"),
            "tp1": d.get("tp1_price"), "tp2": d.get("tp2_price"), "risk_reward": d.get("risk_reward_ratio"),
            "win_prob": d.get("model_confidence"), "execution_authorized": d.get("execution_authorized"),
            "regime": reg.get("primary") if isinstance(reg, dict) else reg,
            "regime_confidence": reg.get("confidence") if isinstance(reg, dict) else None,
            "checks": checks, "failing": failing, "not_evaluated": qg.get("not_evaluated") or [],
            "rejection_reasons": d.get("rejection_reasons") or [], "waiting_reasons": d.get("waiting_reasons") or (radar or {}).get("waiting_reasons") or [],
            "invalidation_levels": d.get("invalidation_levels") or [], "gate_chips": chips, "devil": devil,
            "mtf": (radar or {}).get("mtf_alignment") or {}, "mtf_confluence": (radar or {}).get("mtf_confluence"),
            "timestamp": d.get("timestamp"),
        }
        if side in ("BUY", "SELL"):
            try:
                out["adverse_flags"] = adverse(sym, side)
            except Exception as exc:
                logger.info("adverse flags %s: %s", sym, exc)
    for p in snap.get("positions") or []:
        if canonical(p.get("symbol", "")) != sym:
            continue
        buy = "BUY" in str(p.get("type", "")).upper()
        op, cur, sl, tp = (float(p.get(k) or 0) for k in ("open_price", "current_price", "sl", "tp"))
        risk = (op - sl) if buy else (sl - op)
        out["positions"].append({
            "ticket": p.get("ticket"), "side": "BUY" if buy else "SELL", "volume": p.get("volume"), "open_price": op,
            "current_price": cur, "sl": sl or None, "tp": tp or None, "profit": p.get("profit"),
            "live_r": round(((cur - op) if buy else (op - cur)) / risk, 2) if sl and risk > 0 else None,
            "to_sl": round(abs(cur - sl), 6) if sl else None, "to_tp": round(abs(tp - cur), 6) if tp else None,
            "be_locked": p.get("is_be_locked")})
    stale = as_of is not None and time.time() - as_of > 900
    out["prov"] = Provenance(source="engine telemetry (in-process state)", kind="unavailable" if not d and not out["positions"] else ("stale" if stale else "live"),
                             as_of=as_of or (time.time() if out["positions"] else None),
                             note="" if d else "the engine has no decision for this symbol").to_dict()
    return out


# ---------------------------------------------------------------- AI chart read

_NUM = re.compile(r"(?<![A-Za-z\d.])-?\d[\d,]*(?:\.\d+)?")
SYSTEM = ("You read a trading chart for a trader using ONLY the JSON facts given. Every number you write must appear in the facts "
          "(you may round). Never invent prices, rates or probabilities. Hold rates and pattern stats are measured on this symbol's "
          "history; anything labelled 'context · not validated' must be called context. No trade advice beyond what the engine states.")


def _r(v: Any, d: int = 5) -> Any:
    return round(v, d) if isinstance(v, float) else v


def fact_sheet(lv: Dict[str, Any], pt: Dict[str, Any], sig: Dict[str, Any], quote: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    last = (quote or {}).get("price") or lv.get("last_close")
    zones = lv.get("zones") or []

    def z(x):
        return {"price": _r(x["price"]), "sources": x["sources"][:4], "strength": x["strength"],
                "hold_rate_pct": round(x["hold_rate"] * 100, 1) if x.get("hold_rate") is not None else None,
                "n": x.get("n"), "label": x["label"]}
    above = [z(x) for x in zones if x["role"] == "resistance"][:3]
    below = [z(x) for x in sorted([x for x in zones if x["role"] == "support"], key=lambda x: -x["price"])][:3]
    ev = (pt.get("events") or [])[-4:]
    e = sig.get("engine") or {}
    return {
        "symbol": lv.get("symbol"), "interval": lv.get("interval"), "last_price": _r(last), "atr": _r(lv.get("atr")),
        "resistance_above": above, "support_below": below,
        "recent_patterns": [{"kind": x["kind"], "direction": x["direction"], "level": _r(x["level"]),
                             "date": datetime.fromtimestamp(x["time"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                             "hist_win_rate_pct": round(x["stats"]["win_rate"] * 100, 1) if x.get("stats", {}).get("win_rate") is not None else None,
                             "hist_n": x.get("stats", {}).get("n"), "label": x.get("stats", {}).get("label")} for x in ev],
        "engine": {k: _r(e.get(k)) for k in ("decision", "side", "strategy", "regime", "entry", "stop_loss", "take_profit", "risk_reward")} | {
            "regime_confidence_pct": round(e["regime_confidence"] * 100) if e.get("regime_confidence") is not None else None,
            "mtf": e.get("mtf"), "blocked_by": e.get("gate_chips"), "devil_penalty": e.get("devil", {}).get("penalty"),
            "devil_threshold": e.get("devil", {}).get("threshold"), "threats": (e.get("devil", {}).get("threats") or [])[:4],
            "calibrated_loss_prob_pct": round(e["devil"]["calibrated_loss_prob"] * 100, 1) if e.get("devil", {}).get("calibrated_loss_prob") is not None else None,
            "invalidation": (e.get("invalidation_levels") or [])[:2]} if e else None,
        "adverse_flags": [f["detail"] for f in sig.get("adverse_flags") or []][:4],
        "open_positions": [{k: p[k] for k in ("side", "open_price", "live_r", "sl", "tp")} for p in sig.get("positions") or []],
    }


def _numbers(text: str) -> List[str]:
    return [m.replace(",", "") for m in _NUM.findall(text)]


def grounded(text: str, facts: Dict[str, Any]) -> bool:
    """Every figure in `text` equals a figure in the facts after rounding to the figure's own precision (small counts allowed)."""
    import json
    pool = [float(x) for x in _numbers(json.dumps(facts))]
    for tok in _numbers(text):
        try:
            v = float(tok)
        except ValueError:
            return False
        if v.is_integer() and 0 <= v <= 10:
            continue
        dec = len(tok.split(".")[1]) if "." in tok else 0
        tol = 0.5 * 10 ** -dec + 1e-9
        if not any(abs(abs(f) - abs(v)) <= tol for f in pool):
            return False
    return True


def _clean(t: str) -> str:
    return str(t).strip().rstrip(".")


def _fmt(v: Any) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def template(f: Dict[str, Any]) -> List[str]:
    e = f.get("engine") or {}
    pats = f.get("recent_patterns") or []
    lastp = pats[-1] if pats else None
    trend = (f"Regime {str(e.get('regime') or 'unknown').replace('_', ' ').lower()}"
             + (f" ({e['regime_confidence_pct']}% confidence)" if e.get("regime_confidence_pct") is not None else "")
             + (f"; MTF {', '.join(f'{k} {v.lower()}' for k, v in (e.get('mtf') or {}).items())}" if e.get("mtf") else "")) if e else "No engine regime for this symbol"
    if lastp:
        trend += f". Latest structure: {lastp['kind'].replace('_', ' ')} {lastp['direction']} at {_fmt(lastp['level'])} ({lastp['date']})"
    trend += f"; last {_fmt(f.get('last_price'))}."

    def lvl(z):
        return f"{_fmt(z['price'])} ({', '.join(z['sources'][:2])}; " + (f"held {z['hold_rate_pct']:g}% of n={z['n']}" if z.get("hold_rate_pct") is not None else z["label"]) + ")"
    res, sup = f.get("resistance_above") or [], f.get("support_below") or []
    levels_b = ("Resistance: " + (lvl(res[0]) if res else "none in range") + ". Support: " + (lvl(sup[0]) if sup else "none in range") + ".")
    if e:
        engine_b = (f"Engine: {e.get('decision')} {e.get('side') or ''}".strip()
                    + (f", plan entry {_fmt(e['entry'])} / SL {_fmt(e['stop_loss'])} / TP {_fmt(e['take_profit'])}" if e.get("entry") else "")
                    + (f"; {'; '.join(e['blocked_by'])}" if e.get("blocked_by") else "; no gate is blocking") + ".")
    else:
        engine_b = "Engine: no decision for this symbol (not in the engine's universe or not scanned yet)."
    risks = list(f.get("adverse_flags") or [])
    if e and e.get("devil_penalty") is not None:
        risks.append(f"devil penalty {_fmt(e['devil_penalty'])}" + (f" vs limit {_fmt(e['devil_threshold'])}" if e.get("devil_threshold") is not None else "")
                     + (f", calibrated loss prob {e['calibrated_loss_prob_pct']:g}%" if e.get("calibrated_loss_prob_pct") is not None else ""))
    if e and e.get("threats"):
        risks.append("threats: " + "; ".join(_clean(t) for t in e["threats"][:2]))
    risk_b = "Risks: " + ("; ".join(_clean(r) for r in risks) if risks else "no institutional adverse flags or devil threats reported") + "."
    change = []
    if res:
        change.append(f"a close above {_fmt(res[0]['price'])}")
    if sup:
        change.append(f"a close below {_fmt(sup[0]['price'])}")
    inv = (e.get("invalidation") or [None])[0] if e else None
    change_b = "What would change the view: " + (" or ".join(change) if change else "a new swing structure") + (f"; engine invalidation: {_clean(inv)}" if inv else "") + "."
    return [trend, levels_b, engine_b, risk_b, change_b]


def chart_read(symbol: str, market: str, interval: str, provider: Any = "auto") -> Dict[str, Any]:
    sym, market = canonical(symbol), (market or "FX").upper()
    lv = levels(sym, market, interval)
    pt = patterns(sym, market, interval)
    sig = signal_overlay(sym) if market == "FX" else {"engine": None, "positions": [], "adverse_flags": []}
    quote = feeds.quote(sym, market) if market in ("IN", "US") else None
    facts = fact_sheet(lv, pt, sig, quote)
    bullets, source, note = template(facts), "template", ""
    p = provider
    if p == "auto":
        try:
            from jarvis.ai import client
            p = client.get_provider()
        except Exception as exc:
            p, note = None, f"provider unavailable: {exc}"
    if p is not None:
        import json
        from jarvis.ai.providers.base import ProviderError
        prompt = ("Facts (JSON):\n" + json.dumps(facts, default=str) + "\n\nWrite exactly 5 bullets, one line each, starting with '- ': "
                  "1) trend/regime, 2) key levels above/below with their measured hold rates (or say 'context · not validated' / "
                  "'insufficient history'), 3) what the engine is doing and why, 4) risks (adverse flags, gates, devil threats), "
                  "5) what would change the view. Use only numbers present in the facts.")
        try:
            res = p.chat([p.user(prompt)], [], SYSTEM, effort="low")
            lines = [re.sub(r"^\s*(?:[-*•]|\d[.)])\s*", "", ln).strip() for ln in (res.text or "").splitlines() if ln.strip()]
            lines = [ln for ln in lines if ln][:5]
            if res.stop_reason != "refusal" and len(lines) >= 3 and grounded(" ".join(lines), facts):
                bullets, source = lines, p.name
            else:
                note = "AI answer cited a figure not in the facts (or was incomplete); deterministic read shown"
        except ProviderError as exc:
            note = f"AI provider busy or failed ({type(exc).__name__}); deterministic read shown"
        except Exception as exc:  # a provider bug must not break the chart
            note = f"AI provider error ({type(exc).__name__}); deterministic read shown"
    elif not note:
        note = "no AI provider configured; deterministic read shown"
    return {"symbol": sym, "market": market, "interval": interval, "bullets": bullets, "source": source, "note": note,
            "facts": facts, "prov": lv.get("prov") or unavailable("levels", "no bars").to_dict(),
            "sources_prov": {"levels": lv.get("prov"), "patterns": pt.get("prov"), "signal": sig.get("prov"), "quote": (quote or {}).get("prov")}}
