"""Claude via the official `anthropic` SDK (imported lazily; optional dependency).

Model claude-opus-5-5, adaptive thinking, effort via output_config, server-side refusal
fallbacks (beta), a cached frozen system prompt and deterministic tool order. Forced
tool_choice is not supported on this model, so tool_choice is always `auto`.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from .base import ChatResult, Provider, ProviderBusy, ProviderError, ToolCall, note_call

DEFAULT_MODEL = "claude-opus-5-5"
BETAS = ["server-side-fallback-2026-07-01"]
MAX_RETRIES = 4  # the SDK itself retries 408/409/429/5xx/529 with exponential backoff + jitter; we don't add a second loop


class ClaudeProvider(Provider):
    name = "claude"

    def __init__(self, model: str = "", client: Any = None) -> None:
        self.model = model or os.environ.get("JARVIS_AI_MODEL") or DEFAULT_MODEL
        self._client = client

    def available(self) -> bool:
        if self._client is not None:
            return True
        if not any(os.environ.get(v, "").strip() for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")):
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise ProviderError("the 'anthropic' package is not installed (pip install anthropic)")
            self._client = anthropic.Anthropic(max_retries=MAX_RETRIES)  # SDK default credential chain
        return self._client

    def _create(self, **kw):
        try:
            resp = self.client.beta.messages.create(model=self.model, betas=BETAS, fallbacks="default",
                                                    thinking={"type": "adaptive"}, **kw)
        except ProviderError:
            raise
        except Exception as exc:  # SDK typed errors; message redacted by ProviderError
            code = getattr(exc, "status_code", None)
            if code in (429, 529) or (isinstance(code, int) and code >= 500):
                self.retried += MAX_RETRIES
                note_call(None, True, [self.model])
                raise ProviderBusy(f"AI busy at Anthropic ({code}) — retried {MAX_RETRIES}x")
            raise ProviderError(f"claude {type(exc).__name__}: {getattr(exc, 'message', exc)}")
        note_call(getattr(resp, "model", None) or self.model, False, [])
        return resp

    def chat(self, messages, tools, system, effort="medium") -> ChatResult:
        kw: Dict[str, Any] = {
            "max_tokens": 16000,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": messages, "output_config": {"effort": effort},
        }
        if tools:
            kw["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
            kw["tool_choice"] = {"type": "auto"}
        resp = self._create(**kw)
        if resp.stop_reason == "refusal":
            return ChatResult(text="", stop_reason="refusal", native=resp.content)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        calls = []
        for b in resp.content:
            if getattr(b, "type", "") == "tool_use":
                args = b.input if isinstance(b.input, dict) else json.loads(b.input or "{}")
                calls.append(ToolCall(id=b.id, name=b.name, args=args))
        stop = resp.stop_reason if resp.stop_reason in ("max_tokens", "tool_use") else "end_turn"
        if stop == "max_tokens":
            calls = []  # a truncated turn may carry a partial tool input; never run it
        return ChatResult(text=text, tool_calls=calls, stop_reason=stop, native=resp.content)

    def structured(self, prompt, json_schema, system="") -> Dict[str, Any]:
        kw: Dict[str, Any] = {"max_tokens": 8000, "messages": [{"role": "user", "content": prompt}],
                              "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": json_schema}}}
        if system:
            kw["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        resp = self._create(**kw)
        if resp.stop_reason in ("refusal", "max_tokens"):
            raise ProviderError(f"claude structured output stopped: {resp.stop_reason}")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            return json.loads(text)
        except ValueError:
            raise ProviderError("claude structured output was not valid JSON")

    def user(self, text):
        return {"role": "user", "content": text}

    def assistant_text(self, text):
        return {"role": "assistant", "content": text}

    def append_turn(self, messages, result):
        messages.append({"role": "assistant", "content": result.native})  # blocks unchanged (thinking included)

    def append_tool_results(self, messages, results):
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tc.id, "content": payload} for tc, payload in results]})
