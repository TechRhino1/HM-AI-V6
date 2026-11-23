"""Provider-neutral chat interface plus the tool loop every provider shares.

Each provider keeps its conversation in its own native message format (`messages` is opaque to
callers); the helpers `user`, `assistant_text`, `append_turn` and `append_tool_results` build it.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

KEY_ENV_VARS = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENROUTER_API_KEY")


def redact(text: Any) -> str:
    """Remove any configured key value from a string before it is logged or returned."""
    s = str(text)
    for var in KEY_ENV_VARS:
        v = os.environ.get(var)
        if v and len(v) >= 4:
            s = s.replace(v, "[REDACTED]")
    return re.sub(r"(key=|api[_-]?key[\"':= ]+)[A-Za-z0-9_\-]{8,}", r"\1[REDACTED]", s, flags=re.IGNORECASE)


class ProviderError(RuntimeError):
    """Transport/auth/shape failure. The message is always redacted."""

    def __init__(self, msg: Any) -> None:
        super().__init__(redact(msg))


class ProviderBusy(ProviderError):
    """Every model tried was overloaded/rate-limited after bounded retries. Message is UI-ready."""


class ModelSwitch(ProviderError):
    """Provider fell back to another model while history holds the old model's steps: restart the turn."""


# Outcome of the most recent provider call in this process (for client.status()); never holds a key.
LAST_CALL: Dict[str, Any] = {"busy": False, "last_model_used": None, "fallbacks_tried": []}


def note_call(model: Optional[str], busy: bool, fallbacks: List[str]) -> None:
    LAST_CALL.update(busy=busy, last_model_used=model, fallbacks_tried=list(fallbacks))


@dataclass
class ToolCall:
    id: str
    name: str
    args: Dict[str, Any]


@dataclass
class ChatResult:
    text: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"   # end_turn | tool_use | refusal | max_tokens
    native: Any = None              # provider-native assistant turn, appended back unchanged


class Provider:
    name = "none"
    model = ""
    retried = 0  # failed attempts (retries + model fallbacks) absorbed by this instance

    def available(self) -> bool:
        raise NotImplementedError

    def chat(self, messages: List[Any], tools: List[Dict[str, Any]], system: str, effort: str = "medium") -> ChatResult:
        """tools: neutral specs [{name, description, parameters (JSON schema)}]."""
        raise NotImplementedError

    def structured(self, prompt: str, json_schema: Dict[str, Any], system: str = "") -> Dict[str, Any]:
        raise NotImplementedError

    def user(self, text: str) -> Any:
        raise NotImplementedError

    def assistant_text(self, text: str) -> Any:
        raise NotImplementedError

    def append_turn(self, messages: List[Any], result: ChatResult) -> None:
        raise NotImplementedError

    def append_tool_results(self, messages: List[Any], results: List[tuple]) -> None:
        """results: [(ToolCall, payload_json_str)]"""
        raise NotImplementedError


def run_tool_loop(provider: Provider, system: str, messages: List[Any], tools: List[Dict[str, Any]],
                  execute: Callable[[str, Dict[str, Any]], Any], max_steps: int = 6, effort: str = "medium",
                  on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Call the model, run requested tools, feed results back, until it answers in text.

    Returns {text, stop_reason, calls: [{name, args, result}]}. `execute` returns a JSON-able payload.
    """
    start = len(messages)
    for _ in range(8):  # bounded restarts: one per model fallback at most
        del messages[start:]
        try:
            return _tool_loop(provider, system, messages, tools, execute, max_steps, effort, on_event)
        except ModelSwitch:
            continue  # restart this turn on the new model; never mix step histories across models
    raise ProviderError("model fallback did not settle")


def _tool_loop(provider, system, messages, tools, execute, max_steps, effort, on_event) -> Dict[str, Any]:
    calls: List[Dict[str, Any]] = []
    res = ChatResult(text="")
    for _ in range(max_steps):
        res = provider.chat(messages, tools, system, effort=effort)
        if res.stop_reason == "refusal" or not res.tool_calls:
            break
        provider.append_turn(messages, res)
        outs = []
        for tc in res.tool_calls:
            if on_event:
                on_event("tool", {"name": tc.name, "args": tc.args})
            try:
                payload = execute(tc.name, tc.args)
            except Exception as exc:
                payload = {"error": redact(f"{type(exc).__name__}: {exc}")}
            calls.append({"name": tc.name, "args": tc.args, "result": payload})
            s = json.dumps(payload, default=str)
            outs.append((tc, s if len(s) <= 24000 else s[:24000] + " …(truncated)"))
        provider.append_tool_results(messages, outs)
    else:
        res = ChatResult(text=res.text, stop_reason="max_steps")
    return {"text": res.text, "stop_reason": res.stop_reason, "calls": calls}
