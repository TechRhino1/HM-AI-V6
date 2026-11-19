"""Which model answers: JARVIS_AI_PROVIDER=gemini|claude, else whichever key is set (Claude first)."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .providers.base import LAST_CALL, Provider
from .providers.claude import ClaudeProvider
from .providers.gemini import GeminiProvider


def get_provider() -> Optional[Provider]:
    want = os.environ.get("JARVIS_AI_PROVIDER", "").strip().lower()
    order = {"gemini": [GeminiProvider], "claude": [ClaudeProvider]}.get(want, [ClaudeProvider, GeminiProvider])
    for cls in order:
        p = cls()
        if p.available():
            return p
    return None


def status() -> Dict[str, Any]:
    """Never includes a key — only which provider/model would answer."""
    p = get_provider()
    return {"provider": p.name if p else None, "model": p.model if p else None, "available": p is not None,
            "requested": os.environ.get("JARVIS_AI_PROVIDER", "").strip().lower() or "auto",
            "busy": bool(LAST_CALL["busy"]), "last_model_used": LAST_CALL["last_model_used"],
            "fallbacks_tried": list(LAST_CALL["fallbacks_tried"])}
