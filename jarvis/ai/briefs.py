"""Pre-open (08:50 IST) and post-close (15:45 IST) briefs, built only from a live fact sheet.

The fact sheet is assembled from the same read-only tools the copilot uses. With an AI provider
the model writes prose from the fact sheet alone; without one a deterministic template does.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, Optional

from . import client, tools
from .providers.base import Provider, ProviderError

logger = logging.getLogger(__name__)
INDEX_CHAINS = ("NIFTY", "BANKNIFTY", "SENSEX")
# Global cues as raw Yahoo tickers (served through feeds.quote with market="US").
GLOBAL_CUES = {"S&P 500": "^GSPC", "Nasdaq": "^IXIC", "Dow": "^DJI", "Nikkei 225": "^N225", "Hang Seng": "^HSI",
               "KOSPI": "^KS11", "Straits Times": "^STI", "ASX 200": "^AXJO"}

BRIEF_PROMPT = """You write a market brief for an Indian F&O trader from the JSON fact sheet you are given.
Use ONLY figures present in the fact sheet; never add outside numbers or recall. Cite each figure's source kind and age when given (e.g. "live", "close", "eod").
Say "unavailable" for any section whose prov.kind is unavailable or that is missing.
Keep validated items (adviser RECOMMEND with edge after costs, ledger realised results) separate from unvalidated context (flows, OI walls, PCR, max pain, global cues).
Never recommend placing an order. Structure: Headline (1 line), Global cues, India indices & VIX, Flows, Options positioning (per index: walls, max pain, expected move, PCR), Adviser & ledger, What to watch. Under 350 words."""


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:200], "prov": {"source": "n/a", "kind": "unavailable", "as_of": None}}


def _chain_facts(sym: str) -> Dict[str, Any]:
    an = tools.execute("fno_analytics", {"symbol": sym})
    keep = ("symbol", "expiry", "spot", "days_to_expiry", "atm_strike", "atm_iv", "expected_move", "max_pain", "pcr", "walls", "skew", "gex", "positioning", "prov", "error")
    out = {k: an.get(k) for k in keep if k in an}
    if isinstance(out.get("walls"), dict):
        out["walls"] = {k: out["walls"].get(k) for k in ("resistance", "support")}
    return out


def _scan_facts() -> Dict[str, Any]:
    sc = tools.execute("fno_scan", {})
    out = {k: v for k, v in sc.items() if k in ("scanned", "summary", "prov")}
    out["opportunities"] = [{k: o.get(k) for k in ("symbol", "status", "recommendation", "plan") if k in o}
                            for o in sc.get("opportunities", [])][:5]
    return out


def _global(name_ticker) -> Dict[str, Any]:
    name, t = name_ticker
    from jarvis.markets.data import feeds
    q = feeds.quote(t, "US")
    return {"name": name, "ticker": t, "price": q.get("price"), "change_pct": q.get("change_pct"), "prov": q.get("prov")}


def fact_sheet(kind: str = "pre", include_scan: bool = True) -> Dict[str, Any]:
    jobs = {
        "indices": lambda: tools.execute("indices", {}),
        "vix": lambda: tools.execute("india_vix", {}),
        "fii_dii": lambda: {k: v for k, v in tools.execute("fii_dii", {}).items() if k != "history"},
        "ledger": lambda: {k: v for k, v in tools.execute("ledger", {}).items() if k != "items"},
        **{f"options_{s}": (lambda s=s: _chain_facts(s)) for s in INDEX_CHAINS},
        **{f"inst_{n}": (lambda n=n: tools.execute(n, {})) for n in [t["name"] for t in tools.specs()] if n.startswith("inst_")},
    }
    if include_scan:
        jobs["adviser_scan"] = _scan_facts
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {k: ex.submit(_safe, fn) for k, fn in jobs.items()}
        glob = list(ex.map(lambda nt: _safe(_global, nt), GLOBAL_CUES.items()))
        facts = {k: f.result() for k, f in futs.items()}
    facts["global_cues"] = glob
    facts["generated_at_ist"] = datetime.now(_ist()).strftime("%Y-%m-%d %H:%M")
    facts["kind"] = kind
    return facts


def _ist():
    from jarvis.markets.data.nse import IST
    return IST


def _fmt(v, nd=2) -> str:
    return "unavailable" if v is None else (f"{v:,.{nd}f}" if isinstance(v, (int, float)) else str(v))


def _age(prov: Optional[Dict[str, Any]]) -> str:
    if not prov:
        return "no provenance"
    a = prov.get("age_sec")
    return f"{prov.get('kind')}, {prov.get('source')}" + (f", {a:.0f}s old" if isinstance(a, (int, float)) else "")


def template(facts: Dict[str, Any]) -> str:
    """Deterministic brief: every number is copied from the fact sheet."""
    title = "Pre-open brief" if facts.get("kind") == "pre" else "Post-close brief"
    lines = [f"{title} — {facts.get('generated_at_ist')} IST", "", "Global cues:"]
    for g in facts.get("global_cues", []):
        lines.append(f"  {g.get('name')}: {_fmt(g.get('price'))} ({_fmt(g.get('change_pct'))}%) [{_age(g.get('prov'))}]")
    ix = facts.get("indices") or {}
    lines += ["", f"India indices [{_age(ix.get('prov'))}]:"]
    for r in (ix.get("rows") or [])[:6]:
        lines.append(f"  {r.get('name')}: {_fmt(r.get('last'))} ({_fmt(r.get('change_pct'))}%)")
    v = facts.get("vix") or {}
    lines.append(f"India VIX: {_fmt(v.get('value'))} (52w {_fmt(v.get('year_low'))}–{_fmt(v.get('year_high'))}) [{_age(v.get('prov'))}]")
    fd = facts.get("fii_dii") or {}
    lines += ["", f"Flows (unvalidated context) [{_age(fd.get('prov'))}]:"]
    for r in fd.get("rows") or []:
        lines.append(f"  {r.get('category')} {r.get('date')}: net ₹{_fmt(r.get('net_cr'), 0)} cr")
    lines += ["", "Options positioning (unvalidated context):"]
    for s in INDEX_CHAINS:
        o = facts.get(f"options_{s}") or {}
        if o.get("error") or not o.get("spot"):
            lines.append(f"  {s}: unavailable")
            continue
        w = o.get("walls") or {}
        res = ", ".join(_fmt(x.get("strike"), 0) for x in (w.get("resistance") or [])[:2]) or "n/a"
        sup = ", ".join(_fmt(x.get("strike"), 0) for x in (w.get("support") or [])[:2]) or "n/a"
        em = (o.get("expected_move") or {}).get("one_sd")
        lines.append(f"  {s} {o.get('expiry')}: spot {_fmt(o.get('spot'))}, max pain {_fmt(o.get('max_pain'), 0)}, "
                     f"PCR {_fmt((o.get('pcr') or {}).get('oi'))}, call walls {res}, put walls {sup}, 1σ move ±{_fmt(em)} [{_age(o.get('prov'))}]")
    sc = facts.get("adviser_scan")
    lines += ["", "Adviser (validated gates):"]
    if not sc or sc.get("error"):
        lines.append("  scan unavailable")
    elif not sc.get("opportunities"):
        lines.append(f"  no trade / insufficient evidence across {sc.get('scanned')} symbols")
    for o in (sc or {}).get("opportunities", []):
        rec = o.get("recommendation") or {}
        lines.append(f"  {o.get('symbol')}: {rec.get('name')} edge/lot {_fmt(rec.get('edge_per_lot'))}")
    lg = facts.get("ledger") or {}
    lines.append(f"Ledger: {lg.get('closed', 0)} closed, win rate {_fmt(lg.get('win_rate'), 1)}%, avg P&L/lot {_fmt(lg.get('avg_pnl_per_lot'))}, {lg.get('open', 0)} open.")
    lines += ["", "No orders are placed by this brief; use the order ticket to act."]
    return "\n".join(lines)


def _init(con) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS ai_briefs (kind TEXT, day TEXT, ts REAL, provider TEXT, text TEXT, facts TEXT, PRIMARY KEY (kind, day))")


def generate(kind: str = "pre", provider: Optional[Provider] = None, facts: Optional[Dict[str, Any]] = None,
             use_provider: bool = True) -> Dict[str, Any]:
    if kind not in ("pre", "post"):
        raise ValueError("kind must be pre or post")
    facts = facts if facts is not None else fact_sheet(kind)
    p = (provider or client.get_provider()) if use_provider else None
    text, used = None, "template"
    if p:
        try:
            msgs = [p.user("Fact sheet (JSON):\n" + json.dumps(facts, default=str)[:60000])]
            res = p.chat(msgs, [], BRIEF_PROMPT, effort="high")
            if res.stop_reason not in ("refusal",) and res.text:
                text, used = res.text, p.name
        except ProviderError as exc:
            logger.warning("brief via %s failed, using template: %s", p.name, exc)
    text = text or template(facts)
    from jarvis.markets.data.store import _db, _lock
    day = datetime.now(_ist()).strftime("%Y-%m-%d")
    with _lock, _db() as con:
        _init(con)
        con.execute("INSERT OR REPLACE INTO ai_briefs VALUES (?,?,?,?,?,?)", (kind, day, time.time(), used, text, json.dumps(facts, default=str)))
    return {"kind": kind, "day": day, "ts": time.time(), "provider": used, "text": text, "facts": facts}


def latest(kind: str = "pre") -> Optional[Dict[str, Any]]:
    from jarvis.markets.data.store import _db, _lock
    with _lock, _db() as con:
        _init(con)
        row = con.execute("SELECT kind, day, ts, provider, text, facts FROM ai_briefs WHERE kind=? ORDER BY ts DESC LIMIT 1", (kind,)).fetchone()
    if not row:
        return None
    return {"kind": row[0], "day": row[1], "ts": row[2], "provider": row[3], "text": row[4], "facts": json.loads(row[5])}
