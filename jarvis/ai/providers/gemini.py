"""Google Gemini over the documented Interactions REST API (POST /v1beta/interactions).

Verified against https://aistudio.google.com/api-reference/interactions-api.md,
.../docs/function-calling and .../docs/structured-output (2026-11). Stateless (`store: false`):
the full step history is resent each turn and the model's own steps are passed back exactly as
received, which carries Gemini 3 thought signatures. The key travels only in `x-goog-api-key`.
"""
from __future__ import annotations

import json
import os
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
RETRYABLE = {429, 500, 502, 503, 504}
MAX_TRIES = 3            # per model
MODEL_BUDGET_S = 20.0    # retrying one model stops once this much wall time is spent on it
DISCOVERY_TTL_S = 6 * 3600
_INPUT_STEPS = {"user_input", "function_result"}

_discovery: Dict[str, Any] = {"at": 0.0, "ttl": 0.0, "models": None}
_discovery_lock = threading.Lock()


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

    def __init__(self, model: str = "", session: Any = None, timeout: float = 45.0, sleep=time.sleep) -> None:
        self.model = model or os.environ.get("JARVIS_AI_MODEL") or DEFAULT_MODEL
        self._http = session or requests.Session()
        self.timeout = timeout
        self._sleep = sleep
        self._steps_model: Optional[str] = None  # model whose native steps are in the current history
        self.retried = 0
        self.fallbacks_tried: List[str] = []

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    def _chain(self, key: str) -> List[str]:
        m = self.model
        chain = list(FALLBACK_CHAIN[FALLBACK_CHAIN.index(m):]) if m in FALLBACK_CHAIN else [m, *FALLBACK_CHAIN]
        listed = discover_models(self._http, key)
        if listed:
            chain = [x for x in chain if x in listed] or chain[:1]
        return chain

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
                    note_call(m, False, self.fallbacks_tried)
                    return data
                if code == 404:  # model not served to this key: next model, no retry
                    last = code
                    break
                if r is not None and code not in RETRYABLE:
                    raise ProviderError(f"gemini HTTP {code}: {r.text[:300]}")
                last = code
                self.retried += 1
                # deterministic spread (no `random` under jarvis/ai): 50-100% of the exponential step
                delay = min(8.0, 2.0 ** (attempt - 1)) * (0.5 + (time.monotonic_ns() % 1000) / 2000.0)
                if attempt == MAX_TRIES or time.monotonic() - t0 + delay > MODEL_BUDGET_S:
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
