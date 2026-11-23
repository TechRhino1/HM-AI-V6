"""OpenRouter free models over its OpenAI-compatible API (POST /api/v1/chat/completions).

A second, independent free quota behind Gemini (2026-11-24): a free-tier key gets up to 50 `:free`
requests a day. The default model is `openrouter/free`, OpenRouter's router over its free models
that support the requested features (tools, structured output). Only free models are ever asked.
The key travels only in the Authorization header and is scrubbed by `redact`.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

import requests

from .base import ChatResult, Provider, ProviderBusy, ProviderError, ToolCall, note_call

ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openrouter/free"
BUSY_COOLDOWN_S = 60.0
# The free models are reasoning models: unbounded, they spent the whole token budget thinking and
# returned empty content (ERNIE 5.5: finish=length at 2048 tokens). Calibrated 2026-11-24 on the
# governor's request: low effort, reasoning excluded from the reply, 4096 tokens -> 4/4 valid JSON
# (ernie, openrouter/free, dots-3, nemotron-3.5). Turning reasoning off is rejected (400) by some.
REASONING = {"effort": "low", "exclude": True}
MAX_TOKENS = 4096
# Structured replies on long prompts (the governor's ~3k-char state) still ran some models out of
# budget (ERNIE 5.5, Nemotron 3.5 Super: finish=length, empty content, 2 of 4 runs): give them more
# room, and since `openrouter/free` picks a model per request, an empty reply is retried once.
STRUCTURED_MAX_TOKENS = 8192
EMPTY_RETRIES = 1

_health: Dict[str, Dict[str, Any]] = {}
_health_lock = threading.Lock()


def _mark(model: str, **fields: Any) -> None:
    with _health_lock:
        _health.setdefault(model, {}).update(fields)


def _blocked_until(model: str) -> float:
    h = _health.get(model) or {}
    return max(float(h.get("exhausted_until") or 0.0), float(h.get("busy_until") or 0.0))


def _next_utc_midnight(now: float) -> float:
    return (int(now // 86400) + 1) * 86400.0


def model_health(now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Rows like gemini.model_health, prefixed `openrouter/` so the dashboard can tell them apart."""
    now = time.time() if now is None else now
    with _health_lock:
        items = sorted(_health.items())
    out = []
    for m, h in items:
        until = _blocked_until(m)
        out.append({"model": m if m.startswith("openrouter/") else f"openrouter/{m}",
                    "state": (h.get("reason") or "busy") if until > now else "ok",
                    "until": until if until > now else None,
                    "last_ok_at": h.get("last_ok_at"), "last_status": h.get("last_status")})
    return out


def _is_free(model: str) -> bool:
    return model == DEFAULT_MODEL or model.endswith(":free")


class OpenRouterProvider(Provider):
    name = "openrouter"

    def __init__(self, model: str = "", session: Any = None, timeout: float = 60.0, purpose: str = "interactive") -> None:
        want = model or os.environ.get("JARVIS_OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL
        # Never a paid model: this key has no credits and the user asked for free versions.
        self.model = want if _is_free(want) else DEFAULT_MODEL
        self.purpose = purpose
        self._http = session or requests.Session()
        self.timeout = timeout
        self.retried = 0

    def available(self) -> bool:
        return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())

    def _post(self, body: Dict[str, Any]) -> Dict[str, Any]:
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ProviderError("OPENROUTER_API_KEY is not set")
        m, now = self.model, time.time()
        if _blocked_until(m) > now:
            note_call(None, True, [m])
            raise ProviderBusy(f"AI busy at OpenRouter (quota) — free again at "
                               f"{time.strftime('%H:%M UTC', time.gmtime(_blocked_until(m)))}")
        try:
            r = self._http.post(ENDPOINT, json={**body, "model": m}, timeout=self.timeout,
                                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            code = r.status_code
        except requests.RequestException as exc:
            r, code = None, ("timeout" if isinstance(exc, requests.Timeout) else type(exc).__name__)
        if code == 200:
            data = r.json()
            if data.get("error"):
                raise ProviderError(f"openrouter error: {json.dumps(data['error'])[:300]}")
            _mark(m, last_ok_at=time.time(), last_status=200, busy_until=0.0)
            note_call(f"openrouter:{data.get('model') or m}", False, [])
            return data
        self.retried += 1
        text = r.text if r is not None else ""
        if code == 429 and "per-day" in text.replace("_", "-").lower():
            # Daily free allowance spent: skip until OpenRouter's reset, else the next UTC midnight.
            reset = None
            try:
                reset = float((getattr(r, "headers", None) or {}).get("X-RateLimit-Reset")) / 1000.0
            except (TypeError, ValueError, AttributeError):
                reset = None
            _mark(m, exhausted_until=reset if reset and reset > now else _next_utc_midnight(now),
                  reason="quota", last_status=429)
        elif code in (429, 500, 502, 503, 504) or r is None:
            _mark(m, busy_until=now + BUSY_COOLDOWN_S, reason="busy", last_status=code)
        else:
            raise ProviderError(f"openrouter HTTP {code}: {text[:300]}")
        note_call(None, True, [m])
        raise ProviderBusy(f"AI busy at OpenRouter ({code})")

    @staticmethod
    def _message(data: Dict[str, Any]) -> Dict[str, Any]:
        return ((data.get("choices") or [{}])[0] or {}).get("message") or {}

    def chat(self, messages, tools, system, effort="medium") -> ChatResult:
        body: Dict[str, Any] = {"messages": [{"role": "system", "content": system}, *messages],
                                "max_tokens": MAX_TOKENS, "reasoning": REASONING}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                               "parameters": t["parameters"]}} for t in tools]
        data = self._post(body)
        msg = self._message(data)
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments") or "{}"
            calls.append(ToolCall(id=str(tc.get("id") or fn.get("name")), name=fn.get("name", ""),
                                  args=json.loads(args) if isinstance(args, str) else (args or {})))
        finish = ((data.get("choices") or [{}])[0] or {}).get("finish_reason")
        stop = "tool_use" if calls else ("max_tokens" if finish == "length" else "end_turn")
        native = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("tool_calls"):
            native["tool_calls"] = msg["tool_calls"]
        return ChatResult(text=(msg.get("content") or "").strip(), tool_calls=calls, stop_reason=stop, native=native)

    def structured(self, prompt, json_schema, system="") -> Dict[str, Any]:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {"messages": msgs, "max_tokens": STRUCTURED_MAX_TOKENS, "reasoning": REASONING,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "result", "strict": True, "schema": json_schema}}}
        for _ in range(EMPTY_RETRIES + 1):
            text = (self._message(self._post(body)).get("content") or "").strip()
            if text.startswith("```"):
                text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
            # Some free models wrap the object in prose; take the outermost {...}.
            i, j = text.find("{"), text.rfind("}")
            try:
                if i >= 0 and j > i:
                    return json.loads(text[i:j + 1])
            except ValueError:
                pass
            # Empty (out of reasoning budget) or unusable: the router may pick another model.
            self.retried += 1
        # No usable answer from a free model: not a fault. Busy lets callers fall back to rules quietly.
        raise ProviderBusy("AI busy at OpenRouter (free models returned no usable answer)")

    def user(self, text):
        return {"role": "user", "content": text}

    def assistant_text(self, text):
        return {"role": "assistant", "content": text}

    def append_turn(self, messages, result):
        messages.append(result.native or {"role": "assistant", "content": result.text})

    def append_tool_results(self, messages, results):
        for tc, payload in results:
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
