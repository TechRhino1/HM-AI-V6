"""Shadow exits: the forward test of the pre-registered exit variants (exit audit, 2026-11-27).

For every live position on the institutional lock, the position monitor also runs each variant in
EXIT_VARIANTS on the same ticks (same price side, same peak, same evaluate_exit) and keeps a
virtual stop. Nothing is sent to the broker. When the real position closes, each variant's virtual
exit and R are written to the shadow_exits table, so a variant can be enabled for a cell only after
>= SHADOW_MIN_CLOSES complete shadow closes that are not worse than the real exits
(tools/promote_model.py approve mode_evidence).

The variants are never looser than the lock, so a virtual stop is always at or ahead of the real
one: a virtual exit happens no later than the real exit and every shadow completes. When the real
exit price is beyond a virtual stop that the 2 s sampling did not see crossed, the virtual exit is
that stop (the broker would have filled it); otherwise it is the real exit.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("JARVIS_ExitShadow")

SHADOW_MODES = ("early_protect", "ratchet", "early_ratchet")
SHADOW_MIN_CLOSES = 20
FROM_OPEN_SEC = 300.0     # a shadow is "complete" only if it started within 5 min of the open
_CAP = 500


class ExitShadow:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: Dict[int, Dict[str, Any]] = {}

    def update(self, *, ticket: int, symbol: str, style: str, side: str, entry: float, initial_sl: float,
               price: float, favorable_dist: float, atr: float, policy: Any, struct_level: Optional[float],
               regime: Optional[str], partial_executable: bool, open_dur_sec: Optional[float],
               peak_favorable_dist: Optional[float]) -> None:
        """One tick: advance every variant's virtual stop. Never raises."""
        try:
            if getattr(policy, "lock_floor_r", None) is None:
                return                                   # not on the lock: the variants do not apply
            from jarvis.execution.exit_policy import apply_exit_mode, evaluate_exit
            buy = str(side).upper() == "BUY"
            with self._lock:
                st = self._state.get(ticket)
                if st is None:
                    if len(self._state) >= _CAP:
                        self._state.pop(next(iter(self._state)))
                    st = self._state[ticket] = {
                        "symbol": symbol, "style": style, "side": "BUY" if buy else "SELL", "entry": float(entry),
                        "initial_sl": float(initial_sl), "partial": False,
                        "from_open": open_dur_sec is not None and 0 <= float(open_dur_sec) <= FROM_OPEN_SEC,
                        "modes": {m: {"sl": float(initial_sl), "exit": None, "policy": apply_exit_mode(policy, m)}
                                  for m in SHADOW_MODES}}
                if partial_executable:
                    st["partial"] = True                 # a split position: price R is not its net R
                for v in st["modes"].values():
                    if v["exit"] is not None:
                        continue
                    if (buy and price <= v["sl"]) or (not buy and price >= v["sl"]):
                        v["exit"] = v["sl"]              # the broker fills a resting stop at its price
                        continue
                    dec = evaluate_exit(side=st["side"], entry=st["entry"], initial_sl=st["initial_sl"],
                                        current_sl=v["sl"], tp=0.0, price=price, favorable_dist=favorable_dist,
                                        atr=atr, policy=v["policy"], partial_already_taken=True,
                                        be_already_locked=v["sl"] * (1 if buy else -1) >= st["entry"] * (1 if buy else -1),
                                        struct_level=struct_level, regime=regime, partial_executable=False,
                                        hold_minutes=(open_dur_sec / 60.0) if open_dur_sec else None,
                                        peak_favorable_dist=peak_favorable_dist)
                    if dec.new_sl:
                        v["sl"] = max(v["sl"], dec.new_sl) if buy else min(v["sl"], dec.new_sl)
        except Exception as exc:  # noqa: BLE001 - a shadow must never touch real management
            logger.debug("shadow exit update failed for #%s: %s", ticket, exc)

    def pop(self, ticket: int, actual_exit: Optional[float]) -> List[Dict[str, Any]]:
        """Rows for a ticket that just closed at `actual_exit` (price), one per variant."""
        with self._lock:
            st = self._state.pop(int(ticket), None)
        if not st or not actual_exit:
            return []
        buy = st["side"] == "BUY"
        risk = abs(st["entry"] - st["initial_sl"])
        if risk <= 0:
            return []
        r = (lambda px: ((px - st["entry"]) if buy else (st["entry"] - px)) / risk)
        rows = []
        for mode, v in st["modes"].items():
            hit = v["exit"] is not None
            px = v["exit"] if hit else (v["sl"] if ((buy and actual_exit < v["sl"]) or (not buy and actual_exit > v["sl"]))
                                        else float(actual_exit))
            rows.append({"ticket": int(ticket), "symbol": st["symbol"], "trade_style": st["style"], "mode": mode,
                         "entry": st["entry"], "initial_sl": st["initial_sl"], "shadow_exit": px,
                         "shadow_r": round(r(px), 4), "actual_exit": float(actual_exit),
                         "actual_r": round(r(float(actual_exit)), 4), "shadow_hit": hit,
                         "complete": bool(st["from_open"] and not st["partial"])})
        return rows
