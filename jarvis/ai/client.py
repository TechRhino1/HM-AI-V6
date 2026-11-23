"""Which model answers: JARVIS_AI_PROVIDER=gemini|claude|openrouter, else whichever key is set (Claude
first, then Gemini). With an OPENROUTER_API_KEY as well, OpenRouter's free models back the primary up
whenever every primary model is busy or out of free quota (see FallbackProvider)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .providers.base import LAST_CALL, ModelSwitch, Provider, ProviderBusy
from .providers.claude import ClaudeProvider
from .providers.gemini import GeminiProvider, model_health as gemini_model_health
from .providers.openrouter import OpenRouterProvider, model_health as openrouter_model_health


class FallbackProvider(Provider):
    """Tries each provider in order and moves on when one raises ProviderBusy.

    Messages built with `user`/`assistant_text` are provider-neutral and translated for whichever
    provider answers. A switch after native turns exist raises ModelSwitch, so `run_tool_loop`
    restarts the turn on the next provider and never mixes two providers' histories."""

    def __init__(self, providers: List[Provider]) -> None:
        self.providers = providers
        self._i = 0

    @property
    def active(self) -> Provider:
        return self.providers[self._i]

    @property
    def name(self) -> str:  # type: ignore[override]
        return self.active.name

    @property
    def model(self) -> str:  # type: ignore[override]
        return self.active.model

    @property
    def retried(self) -> int:  # type: ignore[override]
        return sum(int(getattr(p, "retried", 0) or 0) for p in self.providers)

    def available(self) -> bool:
        return any(p.available() for p in self.providers)

    @staticmethod
    def _neutral(m: Any) -> bool:
        return isinstance(m, dict) and "_neutral" in m

    def _for(self, p: Provider, m: Any) -> Any:
        if not self._neutral(m):
            return m
        return p.user(m["text"]) if m["_neutral"] == "user" else p.assistant_text(m["text"])

    def chat(self, messages, tools, system, effort="medium"):
        has_native = any(not self._neutral(m) for m in messages)
        for i in range(self._i, len(self.providers)):
            if i != self._i:
                self._i = i
                if has_native:
                    raise ModelSwitch(f"fell back to {self.active.name}")
            p = self.providers[i]
            try:
                return p.chat([self._for(p, m) for m in messages], tools, system, effort=effort)
            except ProviderBusy:
                if i == len(self.providers) - 1:
                    raise
        raise ProviderBusy("AI busy at every provider")

    def structured(self, prompt, json_schema, system=""):
        for i in range(self._i, len(self.providers)):
            self._i = i
            try:
                return self.providers[i].structured(prompt, json_schema, system)
            except ProviderBusy:
                if i == len(self.providers) - 1:
                    raise
        raise ProviderBusy("AI busy at every provider")

    def user(self, text):
        return {"_neutral": "user", "text": text}

    def assistant_text(self, text):
        return {"_neutral": "assistant", "text": text}

    def append_turn(self, messages, result):
        self.active.append_turn(messages, result)

    def append_tool_results(self, messages, results):
        self.active.append_tool_results(messages, results)


def get_provider(purpose: str = "interactive") -> Optional[Provider]:
    """purpose="background" for unattended engine work: Gemini then uses only its free lite/Gemma
    models, so the governor and widgets never spend the 20/day flash quota the Copilot needs."""
    want = os.environ.get("JARVIS_AI_PROVIDER", "").strip().lower()
    order = {"gemini": [GeminiProvider], "claude": [ClaudeProvider],
             "openrouter": [OpenRouterProvider]}.get(want, [ClaudeProvider, GeminiProvider])
    primary = None
    for cls in order:
        p = cls(purpose=purpose) if cls in (GeminiProvider, OpenRouterProvider) else cls()
        if p.available():
            primary = p
            break
    backup = OpenRouterProvider(purpose=purpose)
    if not backup.available() or isinstance(primary, OpenRouterProvider):
        return primary
    if primary is None:
        return backup if want in ("", "openrouter") else None
    return FallbackProvider([primary, backup])


def status() -> Dict[str, Any]:
    """Never includes a key — only which provider/model would answer."""
    p = get_provider()
    return {"provider": p.name if p else None, "model": p.model if p else None, "available": p is not None,
            "requested": os.environ.get("JARVIS_AI_PROVIDER", "").strip().lower() or "auto",
            "busy": bool(LAST_CALL["busy"]), "last_model_used": LAST_CALL["last_model_used"],
            "fallbacks_tried": list(LAST_CALL["fallbacks_tried"]),
            "providers": [x.name for x in getattr(p, "providers", [p] if p else [])],
            "models": gemini_model_health() + openrouter_model_health()}
