"""Demo-only shadow tests of two institutional intraday edges (2026-11-19), H1 bars, UTC.

Neither is proven on this book. Rules are pre-registered here and NOT tuned on the data, so
the backtest in tools/research_session_leads.py has one trial per symbol x strategy and its
deflated Sharpe is honest. Each trades `FT_`-tagged on demo only, so it never uses the main
engine's per-symbol slots (risk.exposure.is_forward_test).

1. FT_ORB - session opening-range breakout (Crabel; Zarattini & Aziz 2023).
   Range = the first two H1 bars of London (07-09 UTC) and New York (13-15 UTC).
   Entry: the first completed bar in the next 3 bars that closes beyond the range.
   Stop: the opposite side of the range. Skipped when the range is < 0.3 or > 3 ATR14.
   Exit: 1.5R target, or a 6-bar time stop. One trade per session per day.
2. FT_AVW - anchored-VWAP stretch reversion (session VWAP fades in quiet tape).
3. IMOM (research only, 2026-11-27) - market intraday momentum on cash indices (Gao, Han, Li &
   Zhou 2018; Baltussen, Da, Lammers & Martens 2021): the return from the cash open to the start
   of the last full cash hour predicts that last hour. H1 bars, local session clock (DST-aware):
   signal at the close of the second-to-last full cash hour, trade the last one in the sign of
   the rest-of-day return, exit at its close. Stop 1 ATR14 (for R only). Not forward-tested.
   VWAP anchored at 00:00 UTC on tick volume. Signal when the close first stretches more than
   1.5 ATR14 from VWAP after 03:00 UTC while ADX14 < 20 (no trend). Fade toward VWAP.
   Stop: 1 ATR beyond the entry. Exit: 1.5R target, or an 8-bar time stop.

Promotion (one rule, `promotion_verdict`): at least MIN_LIVE_TRADES closed demo trades with a
positive mean R, a backtest that clears the asset-class OOS hurdle, and DSR >= DSR_BAR. Only
then is a strategy added to a symbol's live profile, by hand.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from jarvis.forward_tests.research_leads import _LeadBase, atr14

logger = logging.getLogger("JARVIS_ForwardTest")

# ── pre-registered rules (do not tune on data: that is what makes the DSR honest) ──
ORB_SESSIONS = ((7, 2, 3), (13, 2, 3))   # (range start hour UTC, range bars, entry window bars)
ORB_MIN_ATR, ORB_MAX_ATR = 0.3, 3.0
ORB_TP_R, ORB_MAX_BARS = 1.5, 6
AVW_DEV_ATR, AVW_ADX_MAX, AVW_START_H = 1.5, 20.0, 3
AVW_STOP_ATR, AVW_TP_R, AVW_MAX_BARS = 1.0, 1.5, 8

MIN_LIVE_TRADES = 30
DSR_BAR = 0.90


def adx14(df: pd.DataFrame) -> np.ndarray:
    """Wilder ADX(14)."""
    h, l, c = (df[k].astype(float) for k in ("high", "low", "close"))
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    ndm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    a = 1 / 14
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=a, adjust=False).mean() / atr
    ndi = 100 * ndm.ewm(alpha=a, adjust=False).mean() / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    return dx.ewm(alpha=a, adjust=False).mean().fillna(0.0).to_numpy(float)


def orb_signals(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Every ORB signal in ``df`` (oldest first, UTC ``time``): {"i", "side", "stop"}.
    Signal at the close of bar i; the stop is the opposite side of the range."""
    t = pd.to_datetime(df["time"], utc=True)
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    atr = atr14(df)
    day, hour = t.dt.floor("D").to_numpy(), t.dt.hour.to_numpy()
    n = len(c)
    out = []
    for start, n_rng, n_win in ORB_SESSIONS:
        for i0 in np.flatnonzero(hour == start):
            j = i0 + n_rng
            if j > n:
                continue
            # the range must be exactly this day's first session bars (no missing bar)
            if (day[i0:j] != day[i0]).any() or (hour[i0:j] != np.arange(start, start + n_rng)).any():
                continue
            hi, lo, a = h[i0:j].max(), l[i0:j].min(), atr[j - 1]
            if not (a > 0 and ORB_MIN_ATR * a <= hi - lo <= ORB_MAX_ATR * a):
                continue
            for i in range(j, min(j + n_win, n)):
                if day[i] != day[i0]:
                    break
                if c[i] > hi:
                    out.append({"i": i, "side": 1, "stop": lo})
                    break
                if c[i] < lo:
                    out.append({"i": i, "side": -1, "stop": hi})
                    break
    return sorted(out, key=lambda s: s["i"])


def avwap_signals(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Every anchored-VWAP stretch-fade signal: {"i", "side", "stop"}."""
    t = pd.to_datetime(df["time"], utc=True)
    h, l, c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
    vol = df["tick_volume"].to_numpy(float) if "tick_volume" in df.columns else np.ones(len(c))
    day = t.dt.floor("D").to_numpy()
    pv = pd.Series((h + l + c) / 3 * vol).groupby(day).cumsum().to_numpy()
    vv = pd.Series(vol).groupby(day).cumsum().to_numpy()
    vwap = np.where(vv > 0, pv / np.where(vv > 0, vv, 1.0), c)
    atr, adx, hour = atr14(df), adx14(df), t.dt.hour.to_numpy()
    dev = np.divide(c - vwap, atr, out=np.zeros(len(c)), where=atr > 0)
    out = []
    for i in range(1, len(c)):
        if hour[i] < AVW_START_H or adx[i] >= AVW_ADX_MAX or atr[i] <= 0 or day[i] != day[i - 1]:
            continue
        if dev[i] > AVW_DEV_ATR >= dev[i - 1]:
            out.append({"i": i, "side": -1, "stop": c[i] + AVW_STOP_ATR * atr[i]})
        elif dev[i] < -AVW_DEV_ATR <= dev[i - 1]:
            out.append({"i": i, "side": 1, "stop": c[i] - AVW_STOP_ATR * atr[i]})
    return out


# Cash sessions (local tz, first full H1 bar hour, last full H1 bar hour) for intraday momentum.
IMOM_SESSIONS = {"US30": ("America/New_York", 10, 15), "NAS100": ("America/New_York", 10, 15),
                 "US500": ("America/New_York", 10, 15), "GER40": ("Europe/Berlin", 9, 16),
                 "UK100": ("Europe/London", 8, 15)}
IMOM_STOP_ATR, IMOM_TP_R, IMOM_MAX_BARS = 1.0, 10.0, 1


def imom_signals(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Intraday-momentum signals for the index named in df.attrs["symbol"] (others: none)."""
    sess = IMOM_SESSIONS.get(str((getattr(df, "attrs", None) or {}).get("symbol", "")).upper())
    if sess is None:
        return []
    tz, first_h, last_h = sess
    local = pd.to_datetime(df["time"], utc=True).dt.tz_convert(tz)
    hour, day = local.dt.hour.to_numpy(), local.dt.date.to_numpy()
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    atr = atr14(df)
    out, open_i = [], {}
    for i in range(len(c)):
        if hour[i] == first_h:
            open_i[day[i]] = i
        # bar i is the second-to-last full cash hour; the trade fills at the next bar's open
        if hour[i] == last_h - 1 and day[i] in open_i and i + 1 < len(c) and hour[i + 1] == last_h                 and day[i + 1] == day[i] and atr[i] > 0:
            ret = c[i] - o[open_i[day[i]]]
            if ret != 0:
                side = 1 if ret > 0 else -1
                out.append({"i": i, "side": side, "stop": c[i] - side * IMOM_STOP_ATR * atr[i]})
    return out


SIGNALS = {"ORB": (orb_signals, ORB_TP_R, ORB_MAX_BARS), "AVWAP": (avwap_signals, AVW_TP_R, AVW_MAX_BARS),
           "IMOM": (imom_signals, IMOM_TP_R, IMOM_MAX_BARS)}


def to_candidates(df: pd.DataFrame, sigs: List[Dict[str, Any]], symbol: str, strategy: str,
                  spread_px: np.ndarray) -> pd.DataFrame:
    """Signals as simulator candidates: fill at the next open, paying the full spread either way
    (conservative for sells); the stop keeps its distance from the signal close."""
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    rows = []
    for s in sigs:
        i = s["i"]
        sd = abs(c[i] - s["stop"])
        if i + 1 >= len(df) or sd <= 0:
            continue
        fill = o[i + 1] + s["side"] * spread_px[i]
        rows.append({"symbol": symbol, "bar_idx": i, "side": "BUY" if s["side"] == 1 else "SELL",
                     "fill": fill, "sl": fill - s["side"] * sd, "score": 1.0,
                     "regime": "UNKNOWN", "strategy": strategy, "zone": "UNKNOWN"})
    return pd.DataFrame(rows)


def promotion_verdict(live_r: List[float], backtest: Dict[str, Any], hurdle: Dict[str, float]) -> Optional[str]:
    """None when a shadow strategy may be promoted to live on this symbol, else the reason it may not."""
    if len(live_r) < MIN_LIVE_TRADES:
        return f"only {len(live_r)} closed demo trades (needs {MIN_LIVE_TRADES})"
    if float(np.mean(live_r)) <= 0:
        return f"demo mean {np.mean(live_r):+.3f}R is not positive"
    if backtest.get("trades", 0) < hurdle["min_trades"] or backtest.get("expectancy_r", 0.0) < hurdle["min_expectancy_r"]:
        return (f"backtest {backtest.get('expectancy_r', 0.0):+.3f}R over {backtest.get('trades', 0)} trades "
                f"misses the hurdle ({hurdle['min_expectancy_r']:+.3f}R over {hurdle['min_trades']:.0f})")
    dsr = backtest.get("dsr")
    if dsr is None or dsr < DSR_BAR:
        return f"deflated Sharpe {dsr} below {DSR_BAR}"
    return None


def beats_live_verdict(route_r: List[float], live_r: List[float], backtest: Dict[str, Any],
                       hurdle: Dict[str, float]) -> Optional[str]:
    """None when an entry route (e.g. CALIBRATED_POLICY) has earned its place on a symbol, else why
    not: the promotion rule above, and its mean R must beat the legacy engine's on that symbol over
    the same window."""
    why = promotion_verdict(route_r, backtest, hurdle)
    if why is not None:
        return why
    if live_r and float(np.mean(route_r)) <= float(np.mean(live_r)):
        return f"route mean {np.mean(route_r):+.3f}R does not beat the legacy engine's {np.mean(live_r):+.3f}R"
    return None


class SessionLeadForwardTest(_LeadBase):
    """Shadow-trades one pre-registered signal on the symbols it is registered for."""
    TF = "H1"

    def __init__(self, orchestrator, tag: str, kind: str, symbols: tuple):
        super().__init__(orchestrator)
        self.TAG, self.STRATEGY, self.STYLE, self.SYMBOLS = tag, f"SHADOW_{kind}", "DAY_TRADING", symbols
        self.signal_fn, self.tp_r, self.max_bars = SIGNALS[kind]

    def _on_bar(self, sym: str, df: pd.DataFrame) -> None:
        pos = self._mine(sym)
        if pos is not None:
            opened = pd.Timestamp(pos.open_time)
            opened = opened.tz_localize("UTC") if opened.tzinfo is None else opened
            if datetime.now(timezone.utc) - opened.to_pydatetime() >= timedelta(hours=self.max_bars):
                self._close(pos, f"TIME_{self.max_bars}H")
            return
        sigs = self.signal_fn(df)
        if not sigs or sigs[-1]["i"] != len(df) - 1 or self._halted():
            return
        if self.orch._is_news_blackout(sym, datetime.now(timezone.utc)):
            return
        s = sigs[-1]
        spr = self._spread_px(sym, df)
        ref = float(df["close"].iloc[-1]) + (spr[-1] if s["side"] == 1 else 0.0)
        self._enter(sym, s["side"], ref, abs(float(df["close"].iloc[-1]) - s["stop"]), self.tp_r)


# Shadow symbols: those that clear the hurdle in >= 3/4 folds in tools/research_session_leads.py.
# 2026-11-19 (reports/SESSION_LEADS_RESEARCH_2026-11-19.md): none did -- gross edges were within
# +/-0.04R and costs made 28/32 negative -- so nothing is shadow-traded until a rerun says otherwise.
ORB_SYMBOLS: tuple = ()
AVWAP_SYMBOLS: tuple = ()


def build(orchestrator) -> List[_LeadBase]:
    leads: List[_LeadBase] = []
    if ORB_SYMBOLS:
        leads.append(SessionLeadForwardTest(orchestrator, "FT_ORB", "ORB", ORB_SYMBOLS))
    if AVWAP_SYMBOLS:
        leads.append(SessionLeadForwardTest(orchestrator, "FT_AVW", "AVWAP", AVWAP_SYMBOLS))
    return leads
