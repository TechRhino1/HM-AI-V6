"""Which model answers: JARVIS_AI_PROVIDER=gemini|claude, else whichever key is set (Claude first)."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .providers.base import LAST_CALL, Provider
from .providers.claude import ClaudeProvider
from .providers.gemini import GeminiProvider, model_health as gemini_model_health


def get_provider(purpose: str = "interactive") -> Optional[Provider]:
    """purpose="background" for unattended engine work: Gemini then uses only its free lite/Gemma
    models, so the governor and widgets never spend the 20/day flash quota the Copilot needs."""
    want = os.environ.get("JARVIS_AI_PROVIDER", "").strip().lower()
    order = {"gemini": [GeminiProvider], "claude": [ClaudeProvider]}.get(want, [ClaudeProvider, GeminiProvider])
    for cls in order:
        p = GeminiProvider(purpose=purpose) if cls is GeminiProvider else cls()
        if p.available():
            return p
    return None


def status() -> Dict[str, Any]:
    """Never includes a key — only which provider/model would answer."""
    p = get_provider()
    return {"provider": p.name if p else None, "model": p.model if p else None, "available": p is not None,
            "requested": os.environ.get("JARVIS_AI_PROVIDER", "").strip().lower() or "auto",
            "busy": bool(LAST_CALL["busy"]), "last_model_used": LAST_CALL["last_model_used"],
            "fallbacks_tried": list(LAST_CALL["fallbacks_tried"]),
            "models": gemini_model_health()}
