"""Per-symbol news verdict for Trade Style AUTO: CLEAR / CAUTION / BLOCK, a size multiplier <= 1,
and the directions the news vetoes.

Rules come first (live calendar, real RSS headlines). The AI (jarvis.ai) only reads those same
headlines and may *tighten* the verdict: cut size or veto the direction it reads against. It can
never open a trade or raise size -- every multiplier here is min(..., 1.0). The AI read runs in a
background thread and is cached, so a trading cycle never waits on a model.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BLOCK_MIN = 30            # = NEWS_BLACKOUT_PRE/POST_MIN
CAUTION_MIN = 120
HEADLINE_MAX_AGE_MIN = 240
AI_TTL = 600.0
BREAKING_WINDOW_MIN = 60
BREAKING_MIN = 3        # keyword 'breaking' tags are common; one or two are noise
AI_VETO_CONFIDENCE = 0.7
_MISSING = object()

SYSTEM = ("You read recent financial-news headlines for ONE traded instrument and judge only what they say. "
          "Use only the headlines given; never invent events or prices. If they don't clearly point one way, "
          "answer UNCLEAR. bias is the likely direction of the instrument itself (not of USD unless the instrument is USD-based).")
SCHEMA = {
    "type": "object",
    "properties": {
        "bias": {"type": "string", "enum": ["BULL", "BEAR", "NEUTRAL", "UNCLEAR"]},
        "confidence": {"type": "number"},
        "risk": {"type": "string", "enum": ["LOW", "ELEVATED", "HIGH"]},
        "reason": {"type": "string"},
    },
    "required": ["bias", "confidence", "risk", "reason"],
}

_ai_cache: Dict[str, Tuple[Tuple, float, Optional[Dict[str, Any]]]] = {}
_inflight: set = set()
_lock = threading.Lock()
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="news-ai")


def _spec(symbol: str):
    from jarvis.data.symbol_registry import resolve
    return resolve(symbol)


def symbol_matchers(symbol: str) -> Tuple[set, set]:
    """(currencies, asset classes) whose headlines concern this symbol."""
    spec = _spec(symbol)
    canon, ac = spec.canonical.upper(), str(spec.asset_class).upper()
    if ac == "CRYPTO":
        return set(), {"CRYPTO"}
    if ac == "FOREX" and len(canon) >= 6:
        return {canon[:3], canon[3:6]}, set()
    return {"USD"}, ({"COMMODITY"} if ac == "COMMODITY" else set())


def calendar_rule(symbol: str, calendar: List[Dict[str, Any]], now: datetime) -> Tuple[str, float, List[str], Optional[Dict[str, Any]]]:
    canon = _spec(symbol).canonical.upper()
    healthy = any(e.get("source") == "live_feed" and not e.get("is_fallback") and str(e.get("time_quality") or "") == "exact"
                  for e in calendar or [])
    if not healthy:
        return "CAUTION", 0.5, ["Economic calendar has no verified live rows; trading at half size"], None
    nearest = None
    for e in calendar:
        if str(e.get("impact", "")).upper() != "HIGH" or e.get("is_fallback") or e.get("source") != "live_feed" \
                or str(e.get("time_quality") or "") != "exact" or canon not in {str(p).upper() for p in e.get("affected_pairs") or []}:
            continue
        try:
            ts = datetime.fromisoformat(str(e.get("timestamp_iso")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        mins = (ts - now).total_seconds() / 60.0
        if -BLOCK_MIN <= mins <= CAUTION_MIN and (nearest is None or abs(mins) < abs(nearest[0])):
            nearest = (mins, e)
    if nearest is None:
        return "CLEAR", 1.0, [], None
    mins, e = nearest
    ev = {"event": e.get("event"), "currency": e.get("currency"), "minutes": round(mins), "time_utc": e.get("time_utc")}
    when = f"in {round(mins)}m" if mins >= 0 else f"{round(-mins)}m ago"
    if abs(mins) <= BLOCK_MIN:
        return "BLOCK", 0.0, [f"High-impact {e.get('currency')} {e.get('event')} {when}"], ev
    return "CAUTION", 0.5, [f"High-impact {e.get('currency')} {e.get('event')} {when}; half size"], ev


def relevant_headlines(symbol: str, headlines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ccys, assets = symbol_matchers(symbol)
    out = []
    for h in headlines or []:
        try:
            if float(h.get("age_minutes", 1e9)) > HEADLINE_MAX_AGE_MIN:
                continue
        except (TypeError, ValueError):
            continue
        if ccys & set(h.get("affected_currencies") or []) or assets & set(h.get("affected_assets") or []):
            out.append(h)
    return out[:20]


def ai_read(provider, symbol: str, heads: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """One structured read of the headlines. None on any provider error or malformed answer."""
    items = [{"title": h.get("title"), "summary": (h.get("summary") or "")[:280], "age_min": h.get("age_minutes"),
              "source": h.get("source")} for h in heads]
    try:
        res = provider.structured(f"Instrument: {symbol}\nHeadlines (newest first):\n{json.dumps(items)}", SCHEMA, SYSTEM)
        bias, risk = str(res.get("bias", "")).upper(), str(res.get("risk", "")).upper()
        if bias not in ("BULL", "BEAR", "NEUTRAL", "UNCLEAR") or risk not in ("LOW", "ELEVATED", "HIGH"):
            return None
        conf = max(0.0, min(1.0, float(res.get("confidence", 0.0))))
        return {"bias": bias, "confidence": round(conf, 2), "risk": risk, "reason": str(res.get("reason", ""))[:240],
                "provider": getattr(provider, "name", type(provider).__name__)}
    except Exception as exc:
        logger.debug("news AI read failed for %s: %s", symbol, exc)
        return None


def _ai_cached(symbol: str, heads: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Cached AI read for exactly these headlines; schedules a background refresh when stale."""
    if not heads:
        return None
    key = tuple(sorted(str(h.get("id") or h.get("title")) for h in heads))
    with _lock:
        hit = _ai_cache.get(symbol)
        if hit and hit[0] == key and time.time() - hit[1] < AI_TTL:
            return hit[2]
        if symbol in _inflight:
            return hit[2] if hit else None
        _inflight.add(symbol)

    def job():
        try:
            from jarvis.ai import client
            p = client.get_provider("background")
            res = ai_read(p, symbol, heads) if p else None
            with _lock:
                _ai_cache[symbol] = (key, time.time(), res)
        finally:
            with _lock:
                _inflight.discard(symbol)

    _pool.submit(job)
    return hit[2] if hit else None


def verdict(symbol: str, *, calendar=None, headlines=None, ai_result: Any = _MISSING, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if calendar is None or headlines is None:
        from jarvis.market.news import GLOBAL_NEWS_ENGINE
        if calendar is None:
            calendar = GLOBAL_NEWS_ENGINE.get_news_calendar(max_wait=0.2) or []
        if headlines is None:
            headlines = GLOBAL_NEWS_ENGINE.get_live_headlines(max_wait=0.2, limit=200) or []

    state, size, reasons, event = calendar_rule(symbol, calendar, now)
    heads = relevant_headlines(symbol, headlines)
    breaking = sum(1 for h in heads if h.get("urgency") == "BREAKING" and float(h.get("age_minutes", 1e9)) <= BREAKING_WINDOW_MIN)
    if breaking >= BREAKING_MIN:
        size = min(size, 0.5)
        reasons.append(f"{breaking} breaking headlines in the last hour; half size")
    scores = [float(h.get("sentiment_score") or 0) for h in heads]
    kw = (sum(scores) / len(scores)) if scores else 0.0
    kw_bias = "BULL" if kw >= 15 else "BEAR" if kw <= -15 else "NEUTRAL"

    ai = _ai_cached(symbol, heads) if ai_result is _MISSING else ai_result
    blocked = {"BUY", "SELL"} if state == "BLOCK" else set()
    if ai:
        if ai["risk"] == "HIGH":
            size = min(size, 0.5)
            reasons.append(f"AI reads high news risk: {ai['reason']}")
        if ai["confidence"] >= AI_VETO_CONFIDENCE and ai["bias"] in ("BULL", "BEAR"):
            against = "SELL" if ai["bias"] == "BULL" else "BUY"
            blocked.add(against)
            reasons.append(f"AI news read is {ai['bias'].lower()} ({ai['confidence']:.0%}); {against} vetoed")
    if state == "CLEAR" and (size < 1.0 or blocked):
        state = "CAUTION"
    return {
        "symbol": symbol, "state": state, "size_mult": round(min(1.0, max(0.0, size)), 2),
        "blocked_directions": sorted(blocked), "bias": (ai or {}).get("bias") or kw_bias,
        "ai_used": bool(ai), "ai": ai, "event": event, "headlines": len(heads), "keyword_score": round(kw, 1),
        "reasons": reasons or ["No high-impact event within 2h and no adverse headlines"],
        "prov": {"source": "economic calendar + RSS headlines" + (" + AI read" if ai else ""), "kind": "live",
                 "as_of": now.isoformat()},
    }
