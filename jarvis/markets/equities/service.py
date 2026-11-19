"""Equities: scanner, detail, news, compare — every number fetched from a real source and labelled.

    prices:      Yahoo spark (live, graded by last-trade time) → TradingView (15-min delayed) → unavailable
    technicals:  scanner rows use TradingView fields (delayed); detail computes from real Yahoo daily bars
    momentum:    12-1 month return from real Yahoo month-end closes; recommendations only if the
                 walk-forward test in tools/markets_model_validation.py published it
    news:        India: NSE corporate announcements (real exchange filings) first, Yahoo RSS headlines after;
                 US: Yahoo Finance RSS. Each item names its source; empty feed → unavailable
"""
from __future__ import annotations

import logging
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from ..data import feeds, tradingview, yahoo
from ..data.models import Provenance, unavailable
from ..data.nse import SourceError
from ..signals import direction
from . import calc, universe

logger = logging.getLogger(__name__)
SPARK = "https://query1.finance.yahoo.com/v8/finance/spark"
RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
_H = {"User-Agent": "Mozilla/5.0"}
_cache: Dict[str, Tuple[float, Any]] = {}
_lock = threading.Lock()


def _cached(key: str, ttl: float, fn: Callable[[], Any]) -> Any:
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (time.time(), val)
    return val


# ---------------------------------------------------------------- sources

def spark(symbols: List[str], market: str, session_open: bool) -> Dict[str, Dict[str, Any]]:
    t2s = {yahoo.ticker(s, market): s for s in symbols}
    tickers = list(t2s)

    def one(chunk: List[str]) -> Dict[str, Dict[str, Any]]:
        try:
            r = requests.get(SPARK, params={"symbols": ",".join(chunk), "range": "1d", "interval": "5m"}, headers=_H, timeout=12)
            return calc.parse_spark(r.json(), t2s, session_open)
        except Exception as exc:
            logger.info("spark batch failed: %s", exc)
            return {}

    out: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(4) as ex:
        for part in ex.map(one, [tickers[i:i + 20] for i in range(0, len(tickers), 20)]):  # Yahoo caps spark at 20
            out.update(part)
    return out


def _tv(symbols: List[str], market: str) -> Dict[str, Dict[str, Any]]:
    try:
        raw = tradingview.scan([universe.tv_id(s, market) for s in symbols], market)
    except SourceError as exc:
        logger.info("tradingview failed: %s", exc)
        return {}
    return {s: raw[universe.tv_id(s, market)] for s in symbols if universe.tv_id(s, market) in raw}


def _iso_date(epoch: Any) -> Optional[str]:
    return datetime.fromtimestamp(epoch, timezone.utc).date().isoformat() if isinstance(epoch, (int, float)) and epoch > 0 else None


def _closed(symbol: str, market: str, rng: str) -> List[Dict[str, float]]:
    b = yahoo.bars(symbol, market, "1d", rng)
    return b["bars"][:-1] if b.get("last_bar_forming") else b["bars"]


def momentum_now(market: str) -> Dict[str, Any]:
    """Current 12-1 scores from real month-end closes; formation = the last completed month."""
    def build():
        this_month = datetime.now(timezone.utc).strftime("%Y-%m")

        def one(s):
            try:
                return s, calc.month_end_closes(_closed(s, market, "2y"), this_month)
            except SourceError:
                return s, {}

        with ThreadPoolExecutor(8) as ex:
            monthly = dict(ex.map(one, universe.symbols(market)))
        formed = max((max(c) for c in monthly.values() if c), default=None)
        scores = {}
        for s, c in monthly.items():
            if formed in c:
                sc = calc.momentum_12_1([c[m] for m in sorted(c)])
                if sc is not None and len(c) >= 13:
                    scores[s] = sc
        prov = (Provenance(source="yahoo:chart 1d (month-end closes)", kind="close", as_of=None,
                           note=f"formed at {formed} month end; {len(scores)} of {len(monthly)} symbols have 13 month-ends")
                if scores else unavailable("yahoo:chart", "no symbol has 13 month-end closes"))
        return {"formed_at": formed, "scores": scores, "ranks": calc.rank(scores), "prov": prov.to_dict()}
    return _cached(f"mom|{market}", 900, build)


def _momentum_block(market: str, mom: Dict[str, Any]) -> Dict[str, Any]:
    reg = (direction.registry().get("momentum") or {}).get(market) or {}
    ok = bool(reg.get("published"))
    rec = [{"symbol": s, "rank": r["rank"], "momentum_12_1_pct": round(mom["scores"][s] * 100, 2)}
           for s, r in sorted(mom["ranks"].items(), key=lambda kv: kv[1]["rank"]) if r["top_quintile"]] if ok else []
    return {"signal": "12-1 month cross-sectional momentum: top quintile, equal weight, 1-month hold",
            "validated": ok, "stats": reg.get("overall"), "survivorship_note": reg.get("survivorship_note"),
            "reason": reg.get("reason") or "not yet validated: run tools/markets_model_validation.py",
            "formed_at": mom["formed_at"], "recommended": rec, "prov": mom["prov"]}


# ---------------------------------------------------------------- scanner

def _trend(tv: Dict[str, Any]) -> Optional[str]:
    m1, m3 = tv.get("Perf.1M"), tv.get("Perf.3M")
    if m1 is None or m3 is None:
        return None
    return "up" if m1 > 0 and m3 > 0 else "down" if m1 < 0 and m3 < 0 else "mixed"


def scan(market: str) -> Dict[str, Any]:
    return _cached(f"scan|{market}", 60, lambda: _scan(market))


def _scan(market: str) -> Dict[str, Any]:
    syms = universe.symbols(market)
    meta = universe.meta(market)
    is_open = feeds.session(market)["open"]
    with ThreadPoolExecutor(3) as ex:
        f_px, f_tv, f_mom = ex.submit(spark, syms, market, is_open), ex.submit(_tv, syms, market), ex.submit(momentum_now, market)
        px, tv, mom = f_px.result(), f_tv.result(), f_mom.result()
    rows = []
    for s in syms:
        t = tv.get(s) or {}
        p = px.get(s)
        if not p and t.get("close"):
            p = {"price": float(t["close"]), "change_pct": t.get("change"), "prov": t["prov"]}
        if not p:
            p = {"price": None, "change_pct": None, "prov": unavailable("yahoo:spark,tradingview", "no source answered").to_dict()}
        close = t.get("close")
        mr = mom["ranks"].get(s) or {}
        rows.append({
            "symbol": s, "name": meta[s]["name"], "sector": t.get("sector") or meta[s]["sector"], "industry": t.get("industry"),
            "price": p["price"], "change_pct": round(p["change_pct"], 3) if p["change_pct"] is not None else None, "price_prov": p["prov"],
            "volume": t.get("volume"), "rvol": t.get("relative_volume_10d_calc"), "rsi": t.get("RSI"),
            "atr_pct": round(t["ATR"] / close * 100, 2) if t.get("ATR") and close else None, "vwap": t.get("VWAP"),
            "perf_w": t.get("Perf.W"), "perf_1m": t.get("Perf.1M"), "perf_3m": t.get("Perf.3M"),
            "market_cap": t.get("market_cap_basic"), "earnings_date": _iso_date(t.get("earnings_release_next_date")),
            "trend": _trend(t),
            "tech_prov": t.get("prov") or unavailable("tradingview:scanner", "no row").to_dict(),
            "momentum_12_1_pct": round(mom["scores"][s] * 100, 2) if s in mom["scores"] else None,
            "momentum_rank": mr.get("rank"), "momentum_percentile": mr.get("percentile"),
        })
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        if r["change_pct"] is not None:
            by.setdefault(r["sector"], []).append(r)
    sectors = sorted(({"sector": k, "count": len(v), "avg_change_pct": round(sum(r["change_pct"] for r in v) / len(v), 3),
                       "leader": max(v, key=lambda r: r["change_pct"])["symbol"]} for k, v in by.items()),
                     key=lambda x: -x["avg_change_pct"])
    kinds: Dict[str, int] = {}
    for r in rows:
        kinds[r["price_prov"]["kind"]] = kinds.get(r["price_prov"]["kind"], 0) + 1
    return {"market": market, "session_open": is_open, "rows": rows, "sectors": sectors,
            "trend_basis": "TradingView Perf.1M and Perf.3M: up if both > 0, down if both < 0, else mixed",
            "momentum": _momentum_block(market, mom),
            "prov": Provenance(source="yahoo:spark + tradingview:scanner", kind=max(kinds, key=kinds.get), as_of=time.time(),
                               note="price kinds: " + ", ".join(f"{k}={v}" for k, v in kinds.items()) + "; each row has price_prov and tech_prov").to_dict()}


# ---------------------------------------------------------------- news

def news(symbol: str, market: str) -> Dict[str, Any]:
    return _cached(f"news|{market}|{symbol}", 300, lambda: _news(symbol.upper(), market))


def _news(symbol: str, market: str) -> Dict[str, Any]:
    if market != "IN":
        return _yahoo_news(symbol, market)
    from .. import inst
    ann = inst.announcements(symbol, limit=20)
    filings = [{"title": a["subject"] + (f": {a['text'][:200]}" if a["text"] else ""), "link": a["attachment"],
                "source": "NSE filing", "published": a["published"]} for a in ann["items"]]
    yn = _yahoo_news(symbol, market)
    items = filings + [{**i, "source": f"Yahoo: {i['source']}" if i.get("source") else "Yahoo"} for i in yn["items"]]
    if not items:
        return {"symbol": symbol, "items": [], "prov": unavailable("nse:corporate-announcements,yahoo:rss",
                                                                   f"NSE: {ann['prov'].get('note')}; Yahoo: {yn['prov'].get('note')}").to_dict()}
    primary = ann["prov"] if filings else yn["prov"]
    prov = dict(primary)
    prov["note"] = f"{len(filings)} NSE filings (primary) + {len(yn['items'])} Yahoo RSS headlines (secondary)"
    return {"symbol": symbol, "items": items, "sources": {"nse": ann["prov"], "yahoo": yn["prov"]}, "prov": prov}


def _yahoo_news(symbol: str, market: str) -> Dict[str, Any]:
    t = yahoo.ticker(symbol, market)
    try:
        r = requests.get(RSS, params={"s": t, "region": "US", "lang": "en-US"}, headers=_H, timeout=12)
        items = parse_rss(r.content)
    except Exception as exc:
        return {"symbol": symbol, "items": [], "prov": unavailable(f"yahoo:rss/{t}", f"{type(exc).__name__}: {exc}").to_dict()}
    if not items:
        return {"symbol": symbol, "items": [], "prov": unavailable(f"yahoo:rss/{t}", "feed returned no headlines for this ticker (common for NSE tickers)").to_dict()}
    newest = max(datetime.fromisoformat(i["published"]).timestamp() for i in items if i["published"]) if any(i["published"] for i in items) else None
    return {"symbol": symbol, "items": items,
            "prov": Provenance(source=f"yahoo:rss/{t}", kind="live", as_of=newest, note=f"{len(items)} headlines; no sentiment scoring").to_dict()}


def parse_rss(content: bytes) -> List[Dict[str, Any]]:
    out = []
    for it in ET.fromstring(content).iter("item"):
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate")
        try:
            iso = parsedate_to_datetime(pub).isoformat() if pub else None
        except (TypeError, ValueError):
            iso = None
        out.append({"title": (it.findtext("title") or "").strip(), "link": link,
                    "source": urlparse(link).netloc.removeprefix("www.") or None, "published": iso})
    return sorted(out, key=lambda i: i["published"] or "", reverse=True)


# ---------------------------------------------------------------- detail / compare

def detail(symbol: str, market: str, equity: Optional[float] = None, risk_pct: Optional[float] = None,
           atr_mult: float = 2.0, with_news: bool = True) -> Dict[str, Any]:
    s = symbol.upper()
    with ThreadPoolExecutor(5) as ex:
        f_q = ex.submit(feeds.quote, s, market)
        f_b = ex.submit(lambda: yahoo.bars(s, market, "1d", "1y"))
        f_tv = ex.submit(_tv, [s], market)
        f_m = ex.submit(momentum_now, market)
        f_n = ex.submit(news, s, market) if with_news else None
        q, tv, mom = f_q.result(), f_tv.result().get(s) or {}, f_m.result()
        try:
            b = f_b.result()
        except SourceError as exc:
            b = {"bars": [], "last_bar_forming": False, "prov": unavailable("yahoo:chart", str(exc)).to_dict()}
        nw = f_n.result() if f_n else None
    closed = b["bars"][:-1] if b["last_bar_forming"] else b["bars"]
    price = q.get("price")
    out: Dict[str, Any] = {"symbol": s, "market": market, "name": (q.get("extra") or {}).get("name") or universe.meta(market).get(s, {}).get("name"),
                           "sector": tv.get("sector"), "industry": tv.get("industry"), "market_cap": tv.get("market_cap_basic"),
                           "quote": q, "bars": b}
    if closed:
        tech = calc.technicals(closed, price)
        tech["prov"] = {**b["prov"], "note": f"computed from {len(closed)} closed daily bars; distances use the quote price"}
        last = closed[-1]
        out["technicals"] = tech
        out["pivots"] = {"based_on": datetime.fromtimestamp(last["time"], timezone.utc).date().isoformat(),
                         "method": "classic floor pivots from that day's high/low/close", **calc.pivots(last), "prov": b["prov"]}
    else:
        out["technicals"] = {"prov": b["prov"]}
        out["pivots"] = {"prov": b["prov"]}
    out["earnings"] = {"date": _iso_date(tv.get("earnings_release_next_date")),
                       "prov": tv.get("prov") or unavailable("tradingview:scanner", "no row").to_dict()}
    mr = mom["ranks"].get(s)
    out["momentum"] = {"momentum_12_1_pct": round(mom["scores"][s] * 100, 2) if mr else None,
                       "rank": mr and mr["rank"], "of": len(mom["ranks"]), "percentile": mr and mr["percentile"],
                       "universe": f"{market} scanner universe", "formed_at": mom["formed_at"], "prov": mom["prov"]}
    if nw is not None:
        out["news"] = nw
    atr_v = out["technicals"].get("atr14")
    if equity and risk_pct and atr_v and price:
        out["risk_sizing"] = {**calc.risk_sizing(equity, risk_pct, atr_v, atr_mult, price), "prov": q["prov"]}
    return out


def compare(a: str, b: str, market: str) -> Dict[str, Any]:
    keep = ("symbol", "name", "sector", "market_cap", "quote", "technicals", "pivots", "earnings", "momentum")
    with ThreadPoolExecutor(2) as ex:
        da, db = ex.map(lambda s: detail(s, market, with_news=False), [a, b])
    return {"market": market, "a": {k: da.get(k) for k in keep}, "b": {k: db.get(k) for k in keep},
            "note": "side-by-side facts only; no winner is chosen"}
