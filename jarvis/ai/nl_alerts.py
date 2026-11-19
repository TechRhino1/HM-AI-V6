"""Natural language → alert rules for the user to confirm. Nothing is saved here."""
from __future__ import annotations

from typing import Any, Dict, Optional

from jarvis.markets.alerts import RULE_TYPES, validate_rule

from . import client
from .providers.base import Provider, ProviderError


def schema() -> Dict[str, Any]:
    props: Dict[str, Any] = {"type": {"type": "string", "enum": sorted(RULE_TYPES)}, "note": {"type": "string"}}
    for spec in RULE_TYPES.values():
        props.update(spec["props"])
    return {"type": "object", "properties": {"rules": {"type": "array", "items": {"type": "object", "properties": props, "required": ["type"]}},
                                             "unparsed": {"type": "string"}}, "required": ["rules"]}


SYSTEM = ("Convert the user's alert request into rules. Rule types: " +
          "; ".join(f"{t}({', '.join(s['props'])})" for t, s in sorted(RULE_TYPES.items())) +
          ". Symbols are NSE/BSE names like NIFTY, BANKNIFTY, SENSEX, RELIANCE; market IN unless a US ticker. "
          "directions: above/below. pct and points are numbers as the user gave them. Use only numbers the user wrote. "
          "If part of the request fits no rule type, put it in `unparsed`.")


def parse(text: str, provider: Optional[Provider] = None) -> Dict[str, Any]:
    p = provider or client.get_provider()
    if not p:
        return {"rules": [], "errors": ["no AI provider configured; create rules with the form instead"], "confirm_required": True}
    try:
        raw = p.structured(f"Alert request: {text[:1000]}", schema(), system=SYSTEM)
    except ProviderError as exc:
        return {"rules": [], "errors": [str(exc)], "confirm_required": True}
    rules, errors = [], []
    for r in (raw or {}).get("rules") or []:
        try:
            rules.append(validate_rule(r))
        except ValueError as exc:
            errors.append(f"{r.get('type')}: {exc}")
    return {"rules": rules, "errors": errors, "unparsed": (raw or {}).get("unparsed") or None, "confirm_required": True,
            "provider": p.name}
