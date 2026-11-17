"""Demo-only forward tests of the three research leads that came close but did not pass (2026-11-17).

Each lead is traded with its research rules unchanged, so live results can be compared with the
backtest. None of them is a proven edge; they are on demo to collect a real, cost-included sample.

1. FT_SMCD - forex DAY (EURUSD, GBPUSD, USDJPY), M15 entry.
   Source: reports/SMC_ENTRY_EXIT_RESEARCH_2026-11-17.md, "base setup + session filter only":
   +0.195R, PF 1.29, n 281, all 4 folds positive.
   Setup: tools/smc_research.py rules (ported below). The displacement bar d has body > 70% of its
   range and range > 1.5 x ATR14(d-1), closes as a CHoCH in its direction, and leaves an FVG.
   Decision at the close of d+1, which must fall in 07-10 or 12-15 UTC.
   Stop distance: entry to beyond the extreme from the first sweep bar (or d-10) to d+1, plus 0.5 ATR.
   Exit X0: fixed 2.5R target, no trail, no time stop.
2. FT_SMCS - crypto SWING (BTCUSD, ETHUSD), H1 entry.
   Source: the same report, "base setup + X3 chandelier": +0.104R, PF 1.22, n 564, 4/4 folds positive.
   Same setup, no session filter, stop buffer 1.0 ATR.
   Exit X3: no target; once the best price reaches +1R, the stop trails 3 x ATR14 behind it on
   completed bars and is never loosened.
3. FT_ESW - EURUSD SWING engine signals with every quality gate removed.
   Source: reports/TRADE_STARVATION_ROOT_CAUSE_2026-11-17.md: +0.196R, n 65, all 4 quarters positive.
   On each completed H1 bar, the production pipeline (context -> regime -> analysts -> DecisionEngine,
   SWING) is run on completed bars. Any BUY/SELL bias with a valid stop is entered at market using
   the engine's own SL/TP distances, and closed after 48 H1 bars if still open.

All three:
- demo mode only;
- one position per test per symbol;
- sized by PositionSizer at 1% / 3 per test (the min-lot entry is skipped when it would breach the
  2.5% ceiling);
- circuit breaker and drawdown halts honoured;
- the position monitor leaves "FT_" positions alone.

Pre-registered promotion rule, per test: at least 100 closed trades and a live mean of at least
+0.05R after costs (GET /api/analytics/performance?by=strategy).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("JARVIS_ForwardTest")

ENABLED_MODES = ("demo",)
RISK_SPLIT = 3            # each test risks 1/3 of the per-trade risk budget, like the Donchian test
K, SWEEP_WIN, EQ_ATR = 3, 10, 0.1
BODY, RANGE_ATR = 0.7, 1.5
TGT_R, CHAND_ATR = 2.5, 3.0
SESSIONS = ((7, 10), (12, 15))
TF_MIN = {"M15": 15, "H1": 60, "H4": 240}


# ── setup detection: exact port of tools/smc_research.py (pivots, structure, levels, setups) ──

def _pivots(h, l):
    """Fractal highs/lows with K bars each side (range_research.pivots); pivot p is known at p + K."""
    ph, pl = [], []
    for p in range(K, len(h) - K):
        wh, wl = h[p - K:p + K + 1], l[p - K:p + K + 1]
        if h[p] == wh.max() and (wh == h[p]).sum() == 1:
            ph.append(p)
        if l[p] == wl.min() and (wl == l[p]).sum() == 1:
            pl.append(p)
    return ph, pl


def _eq(v, tol):
    v = v[-5:]
    for x in range(len(v) - 1, 0, -1):
        for y in range(x - 1, -1, -1):
            if abs(v[x] - v[y]) <= tol:
                return v[x], v[y]
    return None


def _structure(h, l, c, atr):
    ph, pl = _pivots(h, l)
    n = len(c)
    choch = np.zeros(n, int)
    eqh, eql = np.full(n, np.nan), np.full(n, np.nan)
    H, L, a, b, st = [], [], 0, 0, 0
    for i in range(n):
        while a < len(ph) and ph[a] + K <= i:
            H.append(h[ph[a]]); a += 1
        while b < len(pl) and pl[b] + K <= i:
            L.append(l[pl[b]]); b += 1
        if H and c[i] > H[-1] and st != 1:
            choch[i], st = (1 if st == -1 else 0), 1
        elif L and c[i] < L[-1] and st != -1:
            choch[i], st = (-1 if st == 1 else 0), -1
        if H:
            p = _eq(H, EQ_ATR * atr[i]); eqh[i] = max(p) if p else np.nan
        if L:
            p = _eq(L, EQ_ATR * atr[i]); eql[i] = min(p) if p else np.nan
    return choch, eqh, eql


def _levels(t_open: pd.Series, high: pd.Series, low: pd.Series):
    """Completed-session levels: previous UTC day; Asian (00-07) from 07:00; London (07-12) from 12:00."""
    e = pd.DataFrame({"t": t_open, "high": high, "low": low})
    day, hr = e.t.dt.floor("D"), e.t.dt.hour
    g = e.groupby(day)
    out = {"pdh": day.map(g.high.max().shift(1)), "pdl": day.map(g.low.min().shift(1))}
    for name, lo, hi in (("as", 0, 7), ("ln", 7, 12)):
        m = (hr >= lo) & (hr < hi)
        gs = e[m].groupby(day[m])
        out[name + "h"] = day.map(gs.high.max()).where(hr >= hi)
        out[name + "l"] = day.map(gs.low.min()).where(hr >= hi)
    return {k: v.to_numpy(float) for k, v in out.items()}


def atr14(df: pd.DataFrame) -> np.ndarray:
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / 14, adjust=False).mean().to_numpy(float)


def detect_last(df: pd.DataFrame, spr: np.ndarray, stop_atr: float) -> Optional[Dict[str, Any]]:
    """Setup whose decision bar is the LAST completed bar of ``df`` (oldest first, UTC 'time').

    Returns {"side", "sd", "atr"} or None. ``spr`` is the per-bar spread in price units."""
    if len(df) < SWEEP_WIN + 60:
        return None
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    atr = atr14(df)
    choch, eqh, eql = _structure(h, l, c, atr)
    lv = _levels(pd.to_datetime(df["time"]), df["high"], df["low"])
    with np.errstate(invalid="ignore"):
        sw_lo = np.zeros(len(c), bool)
        sw_hi = np.zeros(len(c), bool)
        for L_ in (lv["pdl"], lv["asl"], lv["lnl"], eql):
            sw_lo |= (l < L_) & (c > L_)
        for H_ in (lv["pdh"], lv["ash"], lv["lnh"], eqh):
            sw_hi |= (h > H_) & (c < H_)
    i = len(c) - 1
    d = i - 1
    a, rng = atr[d - 1], h[d] - l[d]
    if not (a > 0 and rng > RANGE_ATR * a and abs(c[d] - o[d]) > BODY * rng):
        return None
    side = 1 if c[d] > o[d] else -1
    if choch[d] != side or not (l[i] > h[d - 1] if side == 1 else h[i] < l[d - 1]):
        return None
    sw = np.flatnonzero((sw_lo if side == 1 else sw_hi)[d - SWEEP_WIN:d])
    s0 = d - SWEEP_WIN + (sw[0] if len(sw) else 0)
    k = stop_atr * atr[i]
    if side == 1:
        sd = c[i] + spr[i] - (l[s0:i + 1].min() - k)
    else:
        sd = (h[s0:i + 1].max() + k + spr[i]) - c[i]
    return {"side": side, "sd": float(sd), "atr": float(atr[i])} if sd > 0 else None


# ── shared plumbing ─────────────────────────────────────────────────────────

class _LeadBase:
    TAG = ""
    STRATEGY = ""
    STYLE = ""
    SYMBOLS: tuple = ()
    TF = "H1"

    def __init__(self, orchestrator):
        self.orch = orchestrator
        self._last_bar: Dict[str, Any] = {}

    def step(self) -> None:
        """Act once per newly completed bar per symbol. Never raises into the trading loop."""
        if str(getattr(self.orch, "mode", "")).lower() not in ENABLED_MODES:
            return
        for sym in self.SYMBOLS:
            try:
                df = self.orch.data_feed.fetch_rates(sym, timeframe=self.TF, num_bars=600, include_current_bar=False)
                if df is None or len(df) < 200 or "SYNTHETIC" in str(getattr(df, "attrs", {}).get("data_source", "")).upper():
                    continue
                bar = df["time"].iloc[-1]
                if self._last_bar.get(sym) == bar:
                    continue
                self._last_bar[sym] = bar
                self._on_bar(sym, df.reset_index(drop=True))
            except Exception as e:
                logger.warning("Forward test %s %s step failed: %s", self.TAG, sym, e)

    def _mine(self, sym: str):
        for p in self.orch.mt5_client.get_open_positions() or []:
            if str(getattr(p, "comment", "") or "").startswith(f"{self.TAG}_{sym}"):
                return p
        return None

    def _halted(self) -> bool:
        acct = self.orch.mt5_client.get_account_snapshot()
        if self.orch.circuit_breaker.check_status().get("active"):
            return True
        return not self.orch.drawdown_guard.check_limits(acct.equity, acct.balance).get("passed", False)

    def _spread_px(self, sym: str, df: pd.DataFrame) -> np.ndarray:
        spec = self.orch.mt5_client.get_symbol_trading_spec(sym) or {}
        point = float(spec.get("point") or 0.0)
        s = df["spread"].to_numpy(float) * point if ("spread" in df.columns and point > 0) else np.zeros(len(df))
        fallback = float(np.median(s[s > 0])) if (s > 0).any() else 0.0
        return np.where(s > 0, s, fallback)

    def _enter(self, sym: str, side: int, ref: float, sd: float, tp_r: Optional[float],
               comment: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Send the market order; returns the broker result, or None when the min lot is unaffordable."""
        from jarvis.config.settings import SETTINGS
        from jarvis.risk.position_sizing import PositionSizer

        client = self.orch.mt5_client
        acct = client.get_account_snapshot()
        spec = client.get_symbol_trading_spec(sym) or {}
        stop = ref - side * sd
        tp = (ref + side * tp_r * sd) if tp_r else 0.0
        lots = PositionSizer.calculate_lot_size(
            account_balance=acct.equity, entry_price=ref, sl_price=stop,
            risk_pct=float(SETTINGS.risk.max_risk_per_trade_pct) / RISK_SPLIT,
            symbol_info={**spec, "name": sym},
        )
        if lots <= 0:
            logger.info("%s %s entry skipped: minimum lot exceeds the risk policy.", self.TAG, sym)
            return None
        order = "BUY" if side == 1 else "SELL"
        res = client.send_market_order(sym, order, lots, sl_price=stop, tp_price=tp,
                                       comment=comment or f"{self.TAG}_{sym}", reference_price=ref)
        logger.info("%s %s %s %.2f lots @~%.5f stop %.5f tp %.5f: %s", self.TAG, sym, order, lots, ref, stop, tp, res)
        if res and res.get("status") in ("FILLED", "PARTIAL", "POSITION_CONFIRMED"):
            from jarvis.data import database
            database.TRADE_DB.log_trade(
                ticket=res.get("ticket"), position_id=res.get("position_id"), symbol=sym, action=order,
                entry=float(res.get("price") or ref), sl=stop, tp=tp, volume=lots, score=0.0,
                regime="FORWARD_TEST", ev=None, origin="broker", execution_mode="demo",
                account_login=getattr(acct, "login", None), server=getattr(acct, "server", None),
                strategy=self.STRATEGY, trade_style=self.STYLE, planned_rr=tp_r,
            )
        return res

    def _close(self, pos, reason: str) -> None:
        res = self.orch.mt5_client.close_position(pos.ticket)
        if res and res.get("status") in ("CLOSED", "PARTIALLY_CLOSED"):
            from jarvis.data import database
            database.TRADE_DB.set_exit_reason(pos.ticket, f"{self.TAG}_{reason}")
        logger.info("%s close #%s (%s): %s", self.TAG, pos.ticket, reason, res)


def chandelier_stop(side: int, entry: float, stop: float, best: float, atr: float) -> float:
    """X3: once the best price reached +1R (R = entry to the current stop while still untouched),
    trail CHAND_ATR x ATR behind the best price; never loosen."""
    r = abs(entry - stop)
    activated = side * (stop - entry) >= 0 or side * (best - entry) >= r   # already trailed past entry, or +1R
    if not activated:
        return stop
    trail = best - side * CHAND_ATR * atr
    return max(stop, trail) if side == 1 else min(stop, trail)


# ── lead 1 and 2: SMC base setup ────────────────────────────────────────────

class SMCLeadForwardTest(_LeadBase):
    def __init__(self, orchestrator, tag, strategy, style, symbols, tf, stop_atr, session_only, exit_mode):
        super().__init__(orchestrator)
        self.TAG, self.STRATEGY, self.STYLE, self.SYMBOLS, self.TF = tag, strategy, style, symbols, tf
        self.stop_atr, self.session_only, self.exit_mode = stop_atr, session_only, exit_mode

    def _in_session(self, bar_open) -> bool:
        t = pd.Timestamp(bar_open) + pd.Timedelta(minutes=TF_MIN[self.TF])   # decision at the bar close
        hod = t.hour + t.minute / 60
        return any(lo <= hod < hi for lo, hi in SESSIONS)

    def _on_bar(self, sym: str, df: pd.DataFrame) -> None:
        spr = self._spread_px(sym, df)
        pos = self._mine(sym)
        if pos is not None:
            if self.exit_mode == "X3":
                self._trail(pos, df)
            return
        if self.session_only and not self._in_session(df["time"].iloc[-1]):
            return
        s = detect_last(df, spr, self.stop_atr)
        if s is None or self._halted():
            return
        ref = float(df["close"].iloc[-1]) + (spr[-1] if s["side"] == 1 else 0.0)
        self._enter(sym, s["side"], ref, s["sd"], TGT_R if self.exit_mode == "X0" else None)

    def _trail(self, pos, df: pd.DataFrame) -> None:
        side = 1 if str(pos.type).upper() == "BUY" else -1
        opened = pd.Timestamp(pos.open_time).tz_localize(None) if pd.Timestamp(pos.open_time).tzinfo else pd.Timestamp(pos.open_time)
        since = df[pd.to_datetime(df["time"]) >= opened.floor(f"{TF_MIN[self.TF]}min")]
        if since.empty or not pos.sl:
            return
        best = float(since["high"].max()) if side == 1 else float(since["low"].min())
        new_sl = chandelier_stop(side, float(pos.open_price), float(pos.sl), best, float(atr14(df)[-1]))
        if abs(new_sl - pos.sl) > 1e-9:
            self.orch.mt5_client.modify_position(pos.ticket, sl=new_sl, tp=0.0)


# ── lead 3: EURUSD SWING engine signals, gates removed ──────────────────────

class EngineSwingForwardTest(_LeadBase):
    TAG = "FT_ESW"
    STRATEGY = "ENGINE_SWING_NO_GATES"
    STYLE = "SWING"
    SYMBOLS = ("EURUSD",)
    TF = "H1"
    HORIZON_H = 48

    def _on_bar(self, sym: str, df: pd.DataFrame) -> None:
        pos = self._mine(sym)
        if pos is not None:
            opened = pd.Timestamp(pos.open_time)
            opened = opened.tz_localize("UTC") if opened.tzinfo is None else opened
            if datetime.now(timezone.utc) - opened.to_pydatetime() >= timedelta(hours=self.HORIZON_H):
                self._close(pos, "HORIZON_48H")
            return
        d = self._decide(sym)
        if d is None or self._halted():
            return
        side = 1 if d["bias"] == "BUY" else -1
        spr = self._spread_px(sym, df)
        ref = float(df["close"].iloc[-1]) + (spr[-1] if side == 1 else 0.0)
        sd = abs(d["entry"] - d["sl"])
        tp_r = abs(d["tp"] - d["entry"]) / sd if d["tp"] > 0 and sd > 0 else None
        if sd > 0:
            self._enter(sym, side, ref, sd, tp_r)

    def _decide(self, sym: str) -> Optional[Dict[str, Any]]:
        """The production SWING pipeline on completed bars; returns its bias and levels, ignoring gates."""
        o = self.orch
        mtf = o.data_feed.fetch_multi_timeframe(sym, trade_style="SWING")
        prim = mtf.get("primary")
        if prim is not None and len(prim) and "time" in prim.columns:
            last = pd.Timestamp(prim["time"].iloc[-1])
            last = last.tz_localize("UTC") if last.tzinfo is None else last
            if last + pd.Timedelta(hours=1) > pd.Timestamp.now(tz="UTC"):   # drop the forming bar
                mtf["primary"] = prim.iloc[:-1]
        ctx = o.context_engine.build_context(sym, mtf, trade_style="SWING")
        regime = o.regime_classifier.classify_regime(ctx)
        tent = "BUY" if ctx.structure.bias == "BULLISH" else ("SELL" if ctx.structure.bias == "BEARISH" else (
            "SELL" if getattr(ctx.momentum, "trend_score", 0.0) < 0 else "BUY"))
        reports, devil = o.analyst_cluster.run_all_parallel(ctx, regime, tent)
        acct = o.mt5_client.get_account_snapshot()
        dec = o.decision_engine.evaluate(ctx, regime, reports, devil, account_balance=acct.equity,
                                         risk_per_trade_pct=0.5, mtf_data=mtf, trade_style="SWING")
        bias = str(getattr(dec, "bias", "") or "").upper()
        if bias not in ("BUY", "SELL") or not float(dec.stop_loss or 0) > 0:
            return None
        return {"bias": bias, "entry": float(dec.entry_price), "sl": float(dec.stop_loss), "tp": float(dec.take_profit or 0)}


def build_all(orchestrator) -> List[_LeadBase]:
    return [
        SMCLeadForwardTest(orchestrator, "FT_SMCD", "SMC_BASE_SESSION_M15", "DAY_TRADING",
                           ("EURUSD", "GBPUSD", "USDJPY"), "M15", stop_atr=0.5, session_only=True, exit_mode="X0"),
        SMCLeadForwardTest(orchestrator, "FT_SMCS", "SMC_BASE_CHANDELIER_H1", "SWING",
                           ("BTCUSD", "ETHUSD"), "H1", stop_atr=1.0, session_only=False, exit_mode="X3"),
        EngineSwingForwardTest(orchestrator),
    ]
