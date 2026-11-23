"""Google Gemini over the documented Interactions REST API (POST /v1beta/interactions).

Verified against https://aistudio.google.com/api-reference/interactions-api.md,
.../docs/function-calling and .../docs/structured-output (2026-11). Stateless (`store: false`):
the full step history is resent each turn and the model's own steps are passed back exactly as
received, which carries Gemini 3 thought signatures. The key travels only in `x-goog-api-key`.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Set

import requests

from .base import ChatResult, ModelSwitch, Provider, ProviderBusy, ProviderError, ToolCall, note_call

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.8-flash"
FALLBACK_CHAIN = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                  "gemini-flash-latest", "gemini-flash-lite-latest")
# Free-tier models with room to spare. Each flash model above allows only 20 requests/day on the
# free tier (measured 2026-11-24: "limit: 20 requests per day on Free Tier"), so background work
# (governor, attention headline, news check) runs on these, and interactive use falls back to them.
LITE_CHAIN = ("gemini-3.5-flash-lite", "gemma-4-26b-a4b-it", "gemini-3.1-flash-lite",
              "gemini-flash-lite-latest", "gemma-4-31b-it")
RETRYABLE = {429, 500, 502, 503, 504}
MAX_TRIES = 2            # per model, for transient 5xx/timeouts; a 429 or 404 moves on at once
BUSY_COOLDOWN_S = 60.0   # a model that stayed busy is skipped this long
QUOTA_FALLBACK_S = 60.0  # a 429 without "retry in ..." is skipped this long
RETIRED_S = 24 * 3600.0  # a 404 model (retired / not served to this key) is skipped this long
MODEL_BUDGET_S = 20.0    # retrying one model stops once this much wall time is spent on it
DISCOVERY_TTL_S = 6 * 3600
_INPUT_STEPS = {"user_input", "function_result"}

_discovery: Dict[str, Any] = {"at": 0.0, "ttl": 0.0, "models": None}
_discovery_lock = threading.Lock()

# Per-model health shared by every provider instance in this process: a model whose daily quota is
# spent, that is retired, or that just stayed busy is skipped without a request until it recovers.
_health: Dict[str, Dict[str, Any]] = {}
_health_lock = threading.Lock()
_RETRY_IN = re.compile(r"retry in\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+(?:\.\d+)?)s)?", re.IGNORECASE)


def _retry_after_s(text: str) -> Optional[float]:
    """Seconds from Google's 429 text ("Please retry in 11h59m49s"), or None if it gives none."""
    m = _RETRY_IN.search(text or "")
    if not m or not any(m.groups()):
        return None
    h, mi, se = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mi * 60 + se


def _mark(model: str, **fields: Any) -> None:
    with _health_lock:
        _health.setdefault(model, {}).update(fields)


def _blocked_until(model: str) -> float:
    h = _health.get(model) or {}
    return max(float(h.get("exhausted_until") or 0.0), float(h.get("busy_until") or 0.0))


def model_health(now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Each model this process has called: ok / busy / quota (daily cap) / retired, and until when."""
    now = time.time() if now is None else now
    out = []
    with _health_lock:
        items = sorted(_health.items())
    for m, h in items:
        until = _blocked_until(m)
        state = "ok"
        if until > now:
            state = h.get("reason") or "busy"
        out.append({"model": m, "state": state, "until": until if until > now else None,
                    "last_ok_at": h.get("last_ok_at"), "last_status": h.get("last_status")})
    return out


def discover_models(session: Any, key: str) -> Optional[Set[str]]:
    """Model ids this key can use (GET /v1beta/models), cached 6 h; None if the list could not be read."""
    with _discovery_lock:
        now = time.time()
        if _discovery["at"] and now - _discovery["at"] < _discovery["ttl"]:
            return _discovery["models"]
        models = None
        try:
            r = session.get(MODELS_URL, params={"pageSize": 1000}, headers={"x-goog-api-key": key}, timeout=10)
            if r.status_code == 200:
                models = {str(m["name"]).split("/", 1)[-1] for m in r.json().get("models") or [] if m.get("name")} or None
        except Exception:  # discovery is advisory; never log (the request carried the key)
            models = None
        _discovery.update(at=now, ttl=DISCOVERY_TTL_S if models else 300.0, models=models)
        return models


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model: str = "", session: Any = None, timeout: float = 45.0, sleep=time.sleep,
                 purpose: str = "interactive") -> None:
        # background = unattended engine work: free lite/Gemma models only, never the 20/day flash quota.
        self.purpose = "background" if purpose == "background" else "interactive"
        default = LITE_CHAIN[0] if self.purpose == "background" else DEFAULT_MODEL
        self.model = model or (os.environ.get("JARVIS_AI_MODEL") if self.purpose == "interactive" else "") or default
        self._http = session or requests.Session()
        # A free lite model under "high demand" can hang a request for 60 s (measured 2026-11-24);
        # unattended calls give up sooner so a stuck model is skipped instead of stalling a refresh.
        self.timeout = min(timeout, 20.0) if self.purpose == "background" else timeout
        self._sleep = sleep
        self._steps_model: Optional[str] = None  # model whose native steps are in the current history
        self.retried = 0
        self.fallbacks_tried: List[str] = []

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    def _chain(self, key: str) -> List[str]:
        m = self.model
        base = LITE_CHAIN if self.purpose == "background" else FALLBACK_CHAIN + LITE_CHAIN
        chain = list(base[base.index(m):]) if m in base else [m, *base]
        chain = list(dict.fromkeys(chain))
        listed = discover_models(self._http, key)
        if listed:
            chain = [x for x in chain if x in listed] or chain[:1]
        now = time.time()
        ready = [x for x in chain if _blocked_until(x) <= now]
        if not ready:
            nxt = min(_blocked_until(x) for x in chain)
            note_call(None, True, chain)
            raise ProviderBusy(f"AI busy at Google (quota) — next model free at "
                               f"{time.strftime('%H:%M UTC', time.gmtime(nxt))}")
        return ready

    def _post(self, body: Dict[str, Any], history: bool = False) -> Dict[str, Any]:
        """POST with bounded retry (exp. backoff + jitter) per model, then the model fallback chain."""
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise ProviderError("GEMINI_API_KEY is not set")
        last = None
        for m in self._chain(key):
            if m != self.model:
                self.fallbacks_tried.append(self.model)
                self.model = m
                if history and self._steps_model:
                    self._steps_model = None
                    raise ModelSwitch(f"gemini fell back to {m}")
            t0 = time.monotonic()
            for attempt in range(1, MAX_TRIES + 1):
                try:
                    r = self._http.post(ENDPOINT, json={**body, "model": m}, timeout=self.timeout,
                                        headers={"x-goog-api-key": key, "Content-Type": "application/json"})
                    code = r.status_code
                except requests.RequestException as exc:
                    r, code = None, ("timeout" if isinstance(exc, requests.Timeout) else type(exc).__name__)
                if code == 200:
                    data = r.json()
                    if data.get("status") == "failed" or data.get("errors"):
                        raise ProviderError(f"gemini failed: {json.dumps(data.get('errors'))[:300]}")
                    _mark(m, last_ok_at=time.time(), last_status=200, busy_until=0.0)
                    note_call(m, False, self.fallbacks_tried)
                    return data
                if code == 404:  # retired / not served to this key: skip it for a day, no retry
                    _mark(m, exhausted_until=time.time() + RETIRED_S, reason="retired", last_status=404)
                    last = code
                    break
                if code == 429:  # quota: the daily cap says when it resets; retrying now only burns calls
                    wait = _retry_after_s(r.text if r is not None else "") or QUOTA_FALLBACK_S
                    _mark(m, exhausted_until=time.time() + wait, reason="quota", last_status=429)
                    last = code
                    break
                if r is not None and code not in RETRYABLE:
                    raise ProviderError(f"gemini HTTP {code}: {r.text[:300]}")
                last = code
                self.retried += 1
                # deterministic spread (no `random` under jarvis/ai): 50-100% of the exponential step
                delay = min(8.0, 2.0 ** (attempt - 1)) * (0.5 + (time.monotonic_ns() % 1000) / 2000.0)
                if attempt == MAX_TRIES or time.monotonic() - t0 + delay > MODEL_BUDGET_S:
                    _mark(m, busy_until=time.time() + BUSY_COOLDOWN_S, reason="busy", last_status=code)
                    break
                self._sleep(delay)
        self.fallbacks_tried.append(self.model)
        tried = list(dict.fromkeys(self.fallbacks_tried))
        note_call(None, True, tried)
        raise ProviderBusy(f"AI busy at Google ({last}) — retried {len(tried)} models")

    @staticmethod
    def _text(steps: List[Dict[str, Any]]) -> str:
        parts = []
        for s in steps:
            if s.get("type") != "model_output":
                continue
            c = s.get("content")
            if isinstance(c, str):
                parts.append(c)
            for p in c if isinstance(c, list) else []:
                if isinstance(p, dict) and p.get("type", "text") == "text" and p.get("text"):
                    parts.append(p["text"])
        return "".join(parts).strip()

    def chat(self, messages, tools, system, effort="medium") -> ChatResult:
        body: Dict[str, Any] = {"model": self.model, "store": False, "input": list(messages), "system_instruction": system,
                                "generation_config": {"max_output_tokens": 8192}}
        if tools:
            body["tools"] = [{"type": "function", "name": t["name"], "description": t["description"],
                              "parameters": t["parameters"]} for t in tools]
        data = self._post(body, history=self._steps_model is not None)
        steps = [s for s in data.get("steps") or [] if s.get("type") not in _INPUT_STEPS]
        calls = []
        for s in steps:
            if s.get("type") == "function_call":
                args = s.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args or "{}")
                calls.append(ToolCall(id=str(s.get("id") or s.get("name")), name=s["name"], args=args))
        stop = "tool_use" if calls else ("max_tokens" if data.get("status") == "incomplete" else "end_turn")
        return ChatResult(text=self._text(steps), tool_calls=calls, stop_reason=stop, native=steps)

    def structured(self, prompt, json_schema, system="") -> Dict[str, Any]:
        body = {"model": self.model, "store": False, "input": prompt,
                "response_format": {"type": "text", "mime_type": "application/json", "schema": json_schema}}
        if system:
            body["system_instruction"] = system
        data = self._post(body)
        text = data.get("output_text") or self._text(data.get("steps") or [])
        try:
            return json.loads(text)
        except ValueError:
            raise ProviderError("gemini structured output was not valid JSON")

    def user(self, text):
        return {"type": "user_input", "content": text}

    def assistant_text(self, text):
        return {"type": "model_output", "content": [{"type": "text", "text": text}]}

    def append_turn(self, messages, result):
        self._steps_model = self.model
        messages.extend(result.native or [])

    def append_tool_results(self, messages, results):
        for tc, payload in results:
            messages.append({"type": "function_result", "name": tc.name, "call_id": tc.id,
                             "result": [{"type": "text", "text": payload}]})
