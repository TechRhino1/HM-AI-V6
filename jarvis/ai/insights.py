"""Overview "needs attention" list: fixed rules pick and rank the items from live account/risk; the AI only words a headline."""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from . import client
from .providers.base import Provider, ProviderError

PROMPT = ("You get a JSON list of account warnings already ranked by severity. Write ONE plain-English sentence (under 35 words) "
          "telling the trader what matters most right now. Use only the figures given; add no numbers; give no trade advice.")
_RANK = {"danger": 0, "warn": 1, "info": 2}
_cache: Dict[Tuple, Tuple[str, str]] = {}
_lock = threading.Lock()


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _limit_rule(out: List[Dict[str, Any]], key: str, label: str, used: float, cap: float) -> None:
    if cap <= 0 or used < cap * 0.5:
        return
    out.append({"id": key, "level": "danger" if used >= cap * 0.8 else "warn", "route": "overview",
                "title": f"{label} at {used / cap * 100:.0f}% of its limit",
                "detail": f"Now {used:.2f}% against a {cap:.0f}% limit. At the limit the engine blocks new entries."})


def rules(account: Optional[Dict[str, Any]], positions: Optional[List[Dict[str, Any]]], risk: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ranked attention items from live data only. Empty when nothing is near a limit."""
    out: List[Dict[str, Any]] = []
    r = risk or {}
    if r.get("circuit_breaker_active"):
        out.append({"id": "circuit_breaker", "level": "danger", "route": "overview", "title": "Circuit breaker is active",
                    "detail": str(r.get("circuit_breaker_reason") or "New entries are blocked.")})
    elif r and r.get("allow_new_risk") is False:
        out.append({"id": "risk_blocked", "level": "warn", "route": "overview", "title": "New risk is blocked",
                    "detail": "The risk engine is not accepting new entries right now."})
    _limit_rule(out, "daily_loss", "Daily loss", max(0.0, _f(r.get("daily_loss_pct"))), _f(r.get("max_daily_loss_pct")))
    _limit_rule(out, "drawdown", "Drawdown", max(0.0, _f(r.get("total_dd_pct"))), _f(r.get("max_drawdown_pct")))
    heat = _f(r.get("portfolio_heat_score"))
    if heat >= 50:
        out.append({"id": "heat", "level": "danger" if heat >= 80 else "warn", "route": "overview",
                    "title": f"Portfolio heat {heat:.0f}/100", "detail": "; ".join(r.get("heat_reasons") or []) or "New position sizes are being reduced."})
    streak = int(_f(r.get("consecutive_losses")))
    if streak >= 3:
        out.append({"id": "loss_streak", "level": "warn", "route": "portfolio/history", "title": f"{streak} losses in a row",
                    "detail": "Review the recent closed trades before adding risk."})
    lots: Dict[str, float] = {}
    for p in positions or []:
        sym = str(p.get("symbol") or "").split("#")[0].split(".")[0]
        lots[sym] = lots.get(sym, 0.0) + abs(_f(p.get("volume")))
    total = sum(lots.values())
    if len(lots) >= 2 and total > 0:
        sym, top = max(lots.items(), key=lambda kv: kv[1])
        if top / total > 0.5:
            out.append({"id": "concentration", "level": "warn", "route": "portfolio/open", "symbol": sym,
                        "title": f"{sym} is {top / total * 100:.0f}% of open lots", "detail": "Exposure is concentrated in one symbol."})
    eq, margin = _f((account or {}).get("equity")), _f((account or {}).get("margin"))
    if eq > 0 and margin / eq >= 0.5:
        out.append({"id": "margin", "level": "danger" if margin / eq >= 0.8 else "warn", "route": "portfolio/open",
                    "title": f"Margin is {margin / eq * 100:.0f}% of equity", "detail": "Little free margin is left for new trades or adverse moves."})
    paused = r.get("paused_symbols") or []
    if paused:
        out.append({"id": "paused", "level": "info", "route": "overview", "title": f"Paused: {', '.join(map(str, paused))}",
                    "detail": "The engine will not trade these symbols until they are resumed."})
    return sorted(out, key=lambda i: _RANK[i["level"]])


def overview(provider: Optional[Provider] = None, use_provider: bool = True) -> Dict[str, Any]:
    from . import tools
    acc = tools._forex_account({})
    risk = tools._forex_risk({})
    risk_ok = risk.get("status") != "UNAVAILABLE"
    items = rules(acc.get("account"), acc.get("positions"), risk if risk_ok else None)
    if not acc.get("account"):
        headline, used = "No broker account is synced yet, so there is nothing to assess.", "template"
    elif not items:
        headline, used = "Nothing needs attention: all risk limits have room and exposure is spread out.", "template"
    else:
        more = len(items) - 1
        headline, used = items[0]["title"] + (f", plus {more} more item{'s' if more > 1 else ''}." if more else "."), "template"
        key = tuple((i["id"], i["title"]) for i in items)
        with _lock:
            hit = _cache.get(key)
        if hit:
            headline, used = hit
        else:
            p = (provider or client.get_provider("background")) if use_provider else None
            if p:
                try:
                    res = p.chat([p.user(json.dumps([{k: i[k] for k in ("level", "title", "detail")} for i in items]))], [], PROMPT, effort="low")
                    if res.text and res.stop_reason != "refusal":
                        headline, used = res.text.strip(), p.name
                        with _lock:
                            if len(_cache) > 200:
                                _cache.clear()
                            _cache[key] = (headline, used)
                except ProviderError:
                    pass
    src = (risk.get("prov") or {}).get("source", "risk engine")
    prov = {"source": f"rules over {src}" if risk_ok else "broker sync (risk unavailable)",
            "kind": "live" if risk_ok else "unavailable", "as_of": time.time()}
    return {"items": items, "headline": headline, "provider": used, "risk_available": risk_ok, "prov": prov}
