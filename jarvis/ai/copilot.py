"""AI copilot: answers only from live tool results, cites source and age, never trades."""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict, deque
from typing import Any, Callable, Dict, List, Optional

from . import client, tools
from .providers.base import Provider, ProviderBusy, ProviderError, redact, run_tool_loop

logger = logging.getLogger(__name__)

# Frozen: no timestamps or per-request text, so provider prompt caching hits on every turn.
SYSTEM_PROMPT = """You are the HM Algo market copilot for Indian F&O, Indian/US equities and the user's forex account.

Rules — follow all of them:
1. Answer ONLY from the results of the tools available to you. Call a tool for every figure you state. Never estimate, recall or invent a price, level, flow, probability or statistic.
2. For every figure, cite its source and age from the tool result's `prov` block, e.g. "(nse option chain, live, 40 s old)". If prov.kind is "unavailable" or "stale", say so plainly and do not use the value as current.
3. Keep validated edges separate from context. A validated edge is one the system itself gates and measures: the adviser's RECOMMEND with edge after costs, the ledger's realised hit rate, the forex calibration deployment gate. Everything else (PCR, max pain, OI walls, skew, GEX, FII/DII flows, news) is unvalidated context — label it that way.
4. When the adviser says NO_TRADE, a gate fails, evidence is missing, or data is unavailable, say "no trade / insufficient evidence" and give the reason from the tool result. Do not suggest a trade anyway.
5. You cannot place, modify or cancel orders and must refuse such requests; point the user to the order ticket in the app.
6. Be concise: short paragraphs or bullets, plain English, INR for Indian figures.
"""

_NUMBERS = re.compile(r"\d")
_NUMERIC_NAMES = re.compile(r"NIFTY ?50|NIFTY ?100|NIFTY ?200|NIFTY ?500|S&P ?500|NASDAQ ?100|\b(?:P|Q|H)[1-4]\b|\b20\d\d\b", re.I)
REFUSE_TO_GUESS = ("I couldn't fetch live data to answer that, so I won't guess any numbers. "
                   "Try naming the symbol (e.g. NIFTY, BANKNIFTY, RELIANCE) or ask about a specific metric.")
NO_PROVIDER = "AI copilot is not configured (set GEMINI_API_KEY or ANTHROPIC_API_KEY)."
_FOLLOWUPS = {
    "fno_advise": ["What would make this a trade?", "Show the ledger record for this strategy"],
    "fno_analytics": ["Where are the OI walls?", "What is the expected move to expiry?"],
    "fno_scan": ["Explain the top opportunity", "Which symbols were rejected and why?"],
    "fii_dii": ["How have FII flows trended this month?"],
    "india_vix": ["Is implied volatility rich or cheap right now?"],
    "ledger": ["Which strategy has the best realised hit rate?"],
    "forex_risk": ["How much daily loss budget is left?"],
    "calibration_deployment": ["Which forex symbols are cleared to trade?"],
}


def has_figures(text: str) -> bool:
    return bool(_NUMBERS.search(_NUMERIC_NAMES.sub("", text or "")))


class Memory:
    """Bounded per-session history of (user, assistant) text turns."""

    def __init__(self, max_sessions: int = 200, max_turns: int = 8, ttl_sec: float = 6 * 3600) -> None:
        self._d: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self.max_sessions, self.max_turns, self.ttl = max_sessions, max_turns, ttl_sec
        self._lock = threading.Lock()

    def get(self, sid: Optional[str]) -> List[tuple]:
        if not sid:
            return []
        with self._lock:
            e = self._d.get(sid)
            if not e or time.time() - e["ts"] > self.ttl:
                self._d.pop(sid, None)
                return []
            return list(e["turns"])

    def add(self, sid: Optional[str], user: str, answer: str) -> None:
        if not sid:
            return
        with self._lock:
            e = self._d.pop(sid, None) or {"turns": deque(maxlen=self.max_turns)}
            e["turns"].append((user[:2000], answer[:4000]))
            e["ts"] = time.time()
            self._d[sid] = e
            while len(self._d) > self.max_sessions:
                self._d.popitem(last=False)


MEMORY = Memory()


def _messages(p: Provider, sid: Optional[str], text: str) -> List[Any]:
    msgs: List[Any] = []
    for u, a in MEMORY.get(sid):
        msgs += [p.user(u), p.assistant_text(a)]
    msgs.append(p.user(text))
    return msgs


def ask(message: str, session_id: Optional[str] = None, context: Optional[Dict[str, Any]] = None,
        provider: Optional[Provider] = None, on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    p = provider or client.get_provider()
    base = {"provider": p.name if p else None, "model": p.model if p else None}
    message = (message or "").strip()[:4000]
    if not p:
        return {**base, "available": False, "answer": NO_PROVIDER, "citations": [], "followups": [], "tools_used": []}
    if not message:
        return {**base, "available": True, "answer": "Ask a question about markets, the adviser, or your account.",
                "citations": [], "followups": [], "tools_used": []}
    ctx = ""
    if isinstance(context, dict):
        ctx = "; ".join(f"{k}={str(v)[:60]}" for k, v in context.items() if k in ("symbol", "market", "page", "expiry") and v)
    user_text = f"[screen context: {ctx}]\n{message}" if ctx else message
    specs = tools.specs()
    try:
        out = run_tool_loop(p, SYSTEM_PROMPT, _messages(p, session_id, user_text), specs, tools.execute, on_event=on_event)
        if out["stop_reason"] != "refusal" and not out["calls"] and has_figures(out["text"]):
            # Grounding guard: figures without a tool call are not allowed. Re-ask once.
            retry = user_text + "\n\n(Use the tools to fetch live data for every figure. If no tool covers it, say so without numbers.)"
            out = run_tool_loop(p, SYSTEM_PROMPT, _messages(p, session_id, retry), specs, tools.execute, on_event=on_event)
            if not out["calls"] and has_figures(out["text"]):
                out = {**out, "text": REFUSE_TO_GUESS, "guarded": True}
    except ProviderError as exc:
        logger.warning("ai copilot provider error: %s", exc)
        answer = str(exc) if isinstance(exc, ProviderBusy) else "The AI provider failed; no answer was produced."
        return {**base, "model": p.model, "retried": p.retried, "busy": isinstance(exc, ProviderBusy), "available": True,
                "error": str(exc), "answer": answer, "citations": [], "followups": [], "tools_used": []}
    if out["stop_reason"] == "refusal":
        out["text"] = "The model declined to answer this request."
    answer = out["text"] or "No answer was produced."
    citations, seen = [], set()
    for c in out["calls"]:
        for pv in tools.provs(c["result"], c["name"]):
            key = (pv["tool"], pv["source"], pv["kind"])
            if key not in seen:
                seen.add(key)
                citations.append(pv)
    used = [c["name"] for c in out["calls"]]
    followups = list(dict.fromkeys(f for n in used for f in _FOLLOWUPS.get(n, [])))[:3]
    MEMORY.add(session_id, message, answer)
    return {**base, "model": p.model, "retried": p.retried, "available": True, "answer": redact(answer), "citations": citations[:20], "followups": followups,
            "tools_used": [{"name": c["name"], "args": c["args"]} for c in out["calls"]],
            "guarded": bool(out.get("guarded")), "stop_reason": out["stop_reason"]}
