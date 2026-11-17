"""Demo-only trend router: the components that passed the 2026-11-17 cost-honest edge tests.

Source: reports/PORTFOLIO_ROUTER_RESEARCH_2026-11-17.md.
- 12 symbol x strategy components pass on their own (both halves, spread x2, flipped/always-long).
- Combined, the portfolio breaches the 20% drawdown halt at every min-lot cap, so NOTHING is
  fundable live. This router runs them on demo only, to collect a real, cost-included sample.
- ETHUSD Donchian H4 is already traded by `donchian_eth_h4.py` (FT_DCH_H4), so it is not here.

Rules, unchanged from tools/strategy_research.py:
- Donchian ensemble: sub-systems (20,10), (55,20), (100,20). Enter on a completed-bar close beyond
  the prior n_in-bar high/low. Initial stop 3xATR, trailed at 3xATR from each later close, never
  loosened. Exit on a close beyond the opposite prior n_out channel.
- TSMOM ensemble: sub-systems of 1, 3 and 6 months (bars_per_month = bars in the last 365 days / 12).
  Side = sign of close vs the close lb bars ago. Fixed 3xATR stop, exit on a sign change.
- One position per sub-system. A sub-system that exits on a bar does not re-enter on that same bar
  (the research fills exits at the next open and only then accepts a new signal).

What the router decides on every completed bar, per component, and journals (kind=router):
- **Regime:** TREND / RANGE / HIGH_VOL_SHOCK / DEAD (research rules). Logged, not used as a filter:
  no regime filter passed the out-of-sample check.
- **News:** no new entry inside the -30/+30 min HIGH-impact blackout (the adopted N1 rule, via the
  orchestrator's own gate).
- **Capital:** circuit breaker and drawdown halts; at most MAX_OPEN router positions and
  PER_SYMBOL per symbol (the limits the portfolio simulation used); sizing by PositionSizer at
  1% / 3 per sub-system, min-lot entries skipped above the configured min-lot risk cap.
- **No meta-label:** its out-of-sample AUC (0.546) missed the 0.55 bar.

Promotion rule (unchanged): >= 100 closed trades per component and a live mean >= +0.05R after costs,
plus portfolio drawdown inside the 20% halt, before any live allocation. Each component logs its own
strategy name (TREND_<STRATEGY>_<SYMBOL>_<TF>) so /api/analytics/performance?by=strategy splits them.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from jarvis.forward_tests.research_leads import _LeadBase, atr14

logger = logging.getLogger("JARVIS_ForwardTest")

TAG = "FT_TR"
STOP_ATR = 3.0
MAX_OPEN, PER_SYMBOL = 3, 2
DONCHIAN = ((20, 10), (55, 20), (100, 20))
TSMOM_MONTHS = (1, 3, 6)
BARS = {"H4": 2300, "D1": 600}     # >= 1 year for bars_per_month plus the 6-month lookback
COMPONENTS: Tuple[Tuple[str, str, str], ...] = (   # (symbol, strategy, timeframe)
    ("BTCUSD", "tsmom", "D1"), ("BTCUSD", "donchian", "H4"), ("BTCUSD", "tsmom", "H4"),
    ("ETHUSD", "donchian", "D1"),
    ("EURUSD", "donchian", "D1"), ("EURUSD", "tsmom", "D1"), ("EURUSD", "tsmom", "H4"),
    ("USDJPY", "donchian", "D1"), ("USDJPY", "tsmom", "D1"),
    ("USDJPY", "donchian", "H4"), ("USDJPY", "tsmom", "H4"),
)


# ── signals on the LAST completed bar (ports of strategy_research.donchian / tsmom) ──

def bars_per_month(times: pd.Series) -> int:
    t = pd.to_datetime(times)
    return int(round((t > t.iloc[-1] - pd.Timedelta(days=365)).sum() / 12))


def donchian_signals(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    out = {}
    for n_in, n_out in DONCHIAN:
        out[f"D{n_in}"] = {
            "entry": 1 if c[-1] > h[-n_in - 1:-1].max() else (-1 if c[-1] < l[-n_in - 1:-1].min() else 0),
            "exit_long": bool(c[-1] < l[-n_out - 1:-1].min()),
            "exit_short": bool(c[-1] > h[-n_out - 1:-1].max()),
        }
    return out


def tsmom_signals(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    c = df["close"].to_numpy(float)
    bpm = bars_per_month(df["time"])
    out = {}
    for k in TSMOM_MONTHS:
        lb = k * bpm
        s = int(np.sign(c[-1] - c[-1 - lb])) if 0 < lb < len(c) else 0
        out[f"T{k}"] = {"entry": s, "exit_long": s < 0, "exit_short": s > 0}
    return out


def regime_label(df: pd.DataFrame) -> str:
    """tools/smc_research.regime on the completed last bar (logging only; not a filter)."""
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    a = 1 / 14
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=a, adjust=False).mean() / atr
    ndi = 100 * ndm.ewm(alpha=a, adjust=False).mean() / atr
    adx = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).ewm(alpha=a, adjust=False).mean()
    bbw = (4 * c.rolling(20).std() / c.rolling(20).mean()).rolling(500).rank(pct=True)
    ar = tr.rolling(5).mean() / tr.rolling(50).mean()
    adx_v, bbw_v, ar_v = adx.iloc[-1], bbw.iloc[-1], ar.iloc[-1]
    if pd.isna(bbw_v) or pd.isna(ar_v):
        return "NA"
    if ar_v > 1.8:
        return "HIGH_VOL_SHOCK"
    if adx_v >= 25:
        return "TREND"
    if bbw_v < 0.2 and ar_v < 0.8:
        return "DEAD"
    return "RANGE"


# ── the router ──────────────────────────────────────────────────────────────

class TrendRouter(_LeadBase):
    TAG = TAG
    STRATEGY = "TREND_ROUTER"
    STYLE = "TREND"

    def __init__(self, orchestrator):
        super().__init__(orchestrator)
        self._last_bar: Dict[Tuple[str, str], Any] = {}

    def step(self) -> None:
        """Act once per newly completed bar per (symbol, timeframe). Never raises into the loop."""
        if str(getattr(self.orch, "mode", "")).lower() not in ("demo",):
            return
        for sym, tf in dict.fromkeys((s, t) for s, _, t in COMPONENTS):
            try:
                df = self.orch.data_feed.fetch_rates(sym, timeframe=tf, num_bars=BARS[tf], include_current_bar=False)
                if df is None or len(df) < 250 or "SYNTHETIC" in str(getattr(df, "attrs", {}).get("data_source", "")).upper():
                    continue
                bar = df["time"].iloc[-1]
                if self._last_bar.get((sym, tf)) == bar:
                    continue
                self._last_bar[(sym, tf)] = bar
                self._on_bar(sym, tf, df.reset_index(drop=True))
            except Exception as e:
                logger.warning("Trend router %s %s step failed: %s", sym, tf, e)

    def _router_positions(self) -> Dict[str, Any]:
        out = {}
        for p in self.orch.mt5_client.get_open_positions() or []:
            com = str(getattr(p, "comment", "") or "")
            if com.startswith(TAG + "_"):
                out[com] = p
        return out

    def _on_bar(self, sym: str, tf: str, df: pd.DataFrame) -> None:
        from jarvis.observability import decision_journal

        regime = regime_label(df)
        news = bool(self.orch._is_news_blackout(sym, datetime.now(timezone.utc)))
        close, atr = float(df["close"].iloc[-1]), float(atr14(df)[-1])
        spr = self._spread_px(sym, df)
        for s, strat, t in COMPONENTS:
            if (s, t) != (sym, tf):
                continue
            sigs = donchian_signals(df) if strat == "donchian" else tsmom_signals(df)
            for sub, sig in sigs.items():
                comment = f"{TAG}_{sym}_{tf}_{sub}"
                action, reason = self._decide(comment, strat, sym, tf, sig, close, atr, spr, news)
                decision_journal.record_router({"component": comment, "strategy": strat, "regime": regime,
                                                "news_blackout": news, "signal": sig["entry"],
                                                "action": action, "reason": reason})

    def _decide(self, comment, strat, sym, tf, sig, close, atr, spr, news) -> Tuple[str, str]:
        mine = self._router_positions()
        pos = mine.get(comment)
        if pos is not None:
            is_buy = str(pos.type).upper() == "BUY"
            if (is_buy and sig["exit_long"]) or (not is_buy and sig["exit_short"]):
                self._close(pos, "SIGNAL_EXIT")
                return "EXIT", "opposite channel" if strat == "donchian" else "momentum sign flipped"
            if strat == "donchian":   # TSMOM keeps its fixed stop
                trail = close - STOP_ATR * atr if is_buy else close + STOP_ATR * atr
                new_sl = max(pos.sl, trail) if is_buy else (min(pos.sl, trail) if pos.sl > 0 else trail)
                if abs(new_sl - pos.sl) > 1e-9:
                    self.orch.mt5_client.modify_position(pos.ticket, sl=new_sl, tp=0.0)
                    return "TRAIL", f"stop -> {new_sl:.5f}"
            return "HOLD", "in position"
        side = int(sig["entry"])
        if side == 0:
            return "FLAT", "no signal"
        if news:
            return "SKIP", "news blackout (-30/+30 min HIGH impact)"
        if self._halted():
            return "SKIP", "circuit breaker / drawdown halt"
        if len(mine) >= MAX_OPEN:
            return "SKIP", f"router at {MAX_OPEN} open positions"
        if sum(1 for c in mine if c.split("_")[2] == sym) >= PER_SYMBOL:
            return "SKIP", f"{sym} at {PER_SYMBOL} router positions"
        ref = close + (float(spr[-1]) if side == 1 else 0.0)
        self.STRATEGY = f"TREND_{strat.upper()}_{sym}_{tf}"   # per-component analytics
        res = self._enter(sym, side, ref, STOP_ATR * atr, None, comment=comment)
        if res is None:
            return "SKIP", "minimum lot exceeds the risk policy"
        if res.get("status") not in ("FILLED", "PARTIAL", "POSITION_CONFIRMED"):
            return "SKIP", f"order {res.get('status')}: {res.get('reason', '')}"
        return "ENTER", f"{'BUY' if side == 1 else 'SELL'} stop {STOP_ATR}xATR"


def build(orchestrator) -> List[TrendRouter]:
    return [TrendRouter(orchestrator)]
