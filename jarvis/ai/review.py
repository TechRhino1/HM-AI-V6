"""Weekly review of the adviser ledger (real outcomes only)."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

from . import client
from .providers.base import Provider, ProviderError

PROMPT = ("Write a short weekly review of the adviser's recommendation ledger from the JSON given. Use only its figures. "
          "Cover: how many recommendations, hit rate, average P&L per lot, best and worst strategy, and whether the sample "
          "is too small to conclude anything (under 20 closed trades is too small). No trade advice. Under 200 words.")


def weekly_review(provider: Optional[Provider] = None, use_provider: bool = True) -> Dict[str, Any]:
    from jarvis.markets import ledger
    s = ledger.summary()
    week = time.time() - 7 * 86400
    items = [i for i in s["items"] if (i.get("ts") or 0) >= week]
    closed = [i for i in items if i["status"] == "CLOSED" and i["pnl_per_lot"] is not None]
    by: Dict[str, Dict[str, Any]] = {}
    for i in closed:
        b = by.setdefault(i["strategy"], {"n": 0, "wins": 0, "pnl": 0.0})
        b["n"] += 1
        b["wins"] += i["pnl_per_lot"] > 0
        b["pnl"] = round(b["pnl"] + i["pnl_per_lot"], 2)
    stats = {"window_days": 7, "recorded": len(items), "closed": len(closed), "open": sum(i["status"] == "OPEN" for i in items),
             "win_rate": round(sum(i["pnl_per_lot"] > 0 for i in closed) / len(closed) * 100, 1) if closed else None,
             "avg_pnl_per_lot": round(sum(i["pnl_per_lot"] for i in closed) / len(closed), 2) if closed else None,
             "by_strategy": by, "all_time": {k: s[k] for k in ("recorded", "closed", "win_rate", "avg_pnl_per_lot")}}
    prov = {"source": "markets.db ledger", "kind": "live", "as_of": time.time(), "note": "marked to live chain mids; settled on real closes"}
    p = (provider or client.get_provider()) if use_provider else None
    text, used = None, "template"
    if p:
        try:
            res = p.chat([p.user(json.dumps(stats))], [], PROMPT, effort="medium")
            if res.text and res.stop_reason != "refusal":
                text, used = res.text, p.name
        except ProviderError:
            pass
    if not text:
        if not closed:
            text = f"No recommendations closed in the last 7 days ({len(items)} recorded, {stats['open']} still open). Not enough evidence to judge."
        else:
            best = max(by.items(), key=lambda kv: kv[1]["pnl"])
            text = (f"Last 7 days: {len(closed)} closed, win rate {stats['win_rate']}%, average P&L/lot {stats['avg_pnl_per_lot']}. "
                    f"Best strategy by P&L: {best[0]} ({best[1]['n']} trades, {best[1]['pnl']}). "
                    + ("Sample is under 20 closed trades — too small to conclude." if len(closed) < 20 else ""))
    return {"stats": stats, "text": text.strip(), "provider": used, "prov": prov}
