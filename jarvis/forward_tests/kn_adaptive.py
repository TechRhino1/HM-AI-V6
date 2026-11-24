"""KN-Adaptive: the "KN - Smart TP SL" EMA 5/13 crossover with four switchable dynamic layers.

Raw KN (V0): EMA(5) crosses EMA(13) -> trade that way; stop 1.5 x ATR(14); TP1/2/3 at 1/2/3R; an
opposite cross closes the trade. Layers, each computed from completed bars only (no look-ahead):
  1 regime   - take the cross only if Kaufman ER(20) >= er_min, or ADX(14) >= 20 and rising
  2 htf      - only in the direction of the higher-TF bias (close vs EMA200, EMA50 slope agreeing)
  3 adaptive - stop k x ATR with k = clip(1.5 x sqrt(ATR / 100-bar median ATR), 1.2, 2.5), floored at
               the 5-bar swing extreme + spread (still capped at 2.5 x ATR); skip if spread > 10% of the stop
  4 ladder   - TP1/TP2 = 40th/65th percentile of this symbol's past signal MFE (R, last 6 months,
               only signals already finished), runner on a chandelier trail, stop to entry after TP1

Pure functions shared by tools/kn_research.py (research) and any forward test, so both trade one rule.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from jarvis.forward_tests.research_leads import CHAND_ATR, _LeadBase, atr14
from jarvis.forward_tests.session_leads import adx14

logger = logging.getLogger(__name__)

WARMUP = 200
RAW_STOP_ATR = 1.5
K_MIN, K_MAX = 1.2, 2.5
MAX_COST_SHARE = 0.10
ADX_MIN = 20.0
MFE_LOOKBACK = pd.Timedelta(days=182)
MFE_MIN_SAMPLES = 30
TP_MIN, TP_MAX = 0.8, 4.0
LEG = 1.0 / 3.0


@dataclass(frozen=True)
class KNConfig:
    regime: bool = False
    er_min: float = 0.30
    htf: bool = False
    adaptive_stop: bool = False
    dyn_ladder: bool = False


VARIANTS: Dict[str, KNConfig] = {
    "V0_raw": KNConfig(),
    "V1_regime": KNConfig(regime=True),
    "V2_htf": KNConfig(regime=True, htf=True),
    "V3_stop": KNConfig(regime=True, htf=True, adaptive_stop=True),
    "V4_ladder": KNConfig(regime=True, htf=True, adaptive_stop=True, dyn_ladder=True),
}
ER_GRID = (0.25, 0.30, 0.35)


def combos() -> List[Tuple[str, str, KNConfig]]:
    """Every (variant, combo name, config) tried: V0 once, the regime variants once per ER threshold."""
    out = []
    for name, cfg in VARIANTS.items():
        for er in (ER_GRID if cfg.regime else (cfg.er_min,)):
            out.append((name, f"{name}@{er:g}" if cfg.regime else name, replace(cfg, er_min=er)))
    return out


def features(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Per-bar inputs from completed OHLC bars (oldest first)."""
    c = df["close"].astype(float)
    ef = c.ewm(span=5, adjust=False).mean().to_numpy()
    es = c.ewm(span=13, adjust=False).mean().to_numpy()
    atr = atr14(df)
    move = (c - c.shift(20)).abs()
    path = c.diff().abs().rolling(20).sum()
    er = (move / path.replace(0, np.nan)).fillna(0.0).to_numpy()
    med = pd.Series(atr).rolling(100, min_periods=20).median().to_numpy()
    up = np.r_[False, (ef[1:] > es[1:]) & (ef[:-1] <= es[:-1])]
    dn = np.r_[False, (ef[1:] < es[1:]) & (ef[:-1] >= es[:-1])]
    return {
        "c": c.to_numpy(), "atr": atr, "er": er, "adx": adx14(df),
        "atr_ratio": np.where(med > 0, atr / np.where(med > 0, med, 1.0), 1.0),
        "swing_lo": df["low"].astype(float).rolling(5, min_periods=1).min().to_numpy(),
        "swing_hi": df["high"].astype(float).rolling(5, min_periods=1).max().to_numpy(),
        "cross_up": up, "cross_dn": dn,
    }


def htf_bias(df: pd.DataFrame) -> np.ndarray:
    """+1 / -1 / 0 per higher-TF bar: close above EMA200 with EMA50 rising (mirror for -1)."""
    c = df["close"].astype(float)
    e50, e200 = c.ewm(span=50, adjust=False).mean(), c.ewm(span=200, adjust=False).mean()
    slope = e50.diff()
    return np.where((c > e200) & (slope > 0), 1, np.where((c < e200) & (slope < 0), -1, 0)).astype(int)


def stop_distance(F: Dict[str, np.ndarray], i: int, side: int, cfg: KNConfig, spr: float = 0.0) -> float:
    a = F["atr"][i]
    if not cfg.adaptive_stop:
        return RAW_STOP_ATR * a
    k = float(np.clip(RAW_STOP_ATR * np.sqrt(F["atr_ratio"][i]), K_MIN, K_MAX))
    struct = (F["c"][i] - F["swing_lo"][i] if side == 1 else F["swing_hi"][i] - F["c"][i]) + spr
    return float(min(max(k * a, struct), K_MAX * a))


def signals(F: Dict[str, np.ndarray], cfg: KNConfig, bias: Optional[Sequence[int]] = None,
            spr: Optional[Sequence[float]] = None, start: int = WARMUP) -> List[Tuple[int, int, float]]:
    """(bar index, side, stop distance) for every crossover that passes the enabled layers.
    The decision is at bar i's close; execution is at bar i+1's open."""
    out = []
    for i in range(max(start, 1), len(F["c"])):
        side = 1 if F["cross_up"][i] else (-1 if F["cross_dn"][i] else 0)
        if not side or not F["atr"][i] > 0:
            continue
        if cfg.regime and not (F["er"][i] >= cfg.er_min or (F["adx"][i] >= ADX_MIN and F["adx"][i] > F["adx"][i - 1])):
            continue
        if cfg.htf and (bias is None or bias[i] != side):
            continue
        s = float(spr[i]) if spr is not None else 0.0
        sd = stop_distance(F, i, side, cfg, s)
        if cfg.adaptive_stop and s > MAX_COST_SHARE * sd:
            continue
        out.append((i, side, sd))
    return out


def signal_mfe(h: np.ndarray, l: np.ndarray, o: np.ndarray, F: Dict[str, np.ndarray],
               i: int, side: int, sd: float) -> Tuple[float, int]:
    """Best favourable move in R from entry (bar i+1 open) until the stop or the opposite cross.
    Returns (mfe_r, bar index where the signal finished; len(o) if still open)."""
    n = len(o)
    if i + 1 >= n or sd <= 0:
        return 0.0, n
    entry, best = o[i + 1], 0.0
    stop = entry - side * sd
    opp = F["cross_dn"] if side == 1 else F["cross_up"]
    for j in range(i + 1, n):
        if (l[j] <= stop) if side == 1 else (h[j] >= stop):
            return best / sd, j
        best = max(best, side * ((h[j] if side == 1 else l[j]) - entry))
        if opp[j]:
            return best / sd, j
    return best / sd, n


def ladder_levels(mfe_r: Sequence[float]) -> Tuple[float, float]:
    """TP1 / TP2 in R from past MFE samples; 1R / 2R until there are MFE_MIN_SAMPLES of them."""
    x = np.asarray(mfe_r, float)
    if len(x) < MFE_MIN_SAMPLES:
        return 1.0, 2.0
    tp1 = float(np.clip(np.percentile(x, 40), TP_MIN, TP_MAX))
    tp2 = float(np.clip(max(np.percentile(x, 65), tp1 + 0.5), TP_MIN, TP_MAX))
    return tp1, tp2


def exit_plan(cfg: KNConfig, levels: Tuple[float, float] = (1.0, 2.0)):
    """(legs [(weight, target R or None = runner)], stop to entry after TP1, chandelier ATR for the runner)."""
    if not cfg.dyn_ladder:
        return [(LEG, 1.0), (LEG, 2.0), (LEG, 3.0)], False, None
    return [(LEG, levels[0]), (LEG, levels[1]), (LEG, None)], True, CHAND_ATR


# ── demo forward test ────────────────────────────────────────────────────────

class KNForwardTest(_LeadBase):
    """Demo-only probation run of KN-Adaptive V2 (regime gate ER >= 0.35 or rising ADX >= 20, plus the
    EMA200/EMA50 bias of the same H4 bars) on GBPUSD H4: one leg, stop 1.5 x ATR, TP 2R, closed on the
    opposite cross. Research (reports/KN_ADAPTIVE_RESEARCH_2026-11-24.md): OOS +0.19R, PF 1.46, but
    DSR 0.92 < 0.95, so it is on probation, not adopted; single leg because 3 x min lot does not fit."""
    TAG, STRATEGY, STYLE, TF = "FT_KN", "SHADOW_KN_ADAPTIVE", "SWING", "H4"
    SYMBOLS = ("GBPUSD",)
    CFG = KNConfig(regime=True, htf=True, er_min=0.35)
    TP_R = 2.0

    def step(self) -> None:
        # Probation: demo account only, even when trading.forward_test_modes also lists paper/live.
        if str(getattr(self.orch, "mode", "")).lower() == "demo":
            super().step()

    def _on_bar(self, sym: str, df: pd.DataFrame) -> None:
        F = features(df)
        i = len(df) - 1
        pos = self._mine(sym)
        if pos is not None:
            side = 1 if str(pos.type).upper() == "BUY" else -1
            if (F["cross_dn"] if side == 1 else F["cross_up"])[i]:
                self._close(pos, "OPPOSITE_CROSS")   # no same-bar re-entry: the research did not flip
            return
        spr = self._spread_px(sym, df)
        sig = signals(F, self.CFG, htf_bias(df), spr, start=i)
        if not sig or self._halted() or self.orch._is_news_blackout(sym, datetime.now(timezone.utc)):
            return
        _, side, sd = sig[-1]
        ref = float(df["close"].iloc[-1]) + (float(spr[-1]) if side == 1 else 0.0)
        self._enter(sym, side, ref, sd, self.TP_R)


def build(orchestrator) -> List[_LeadBase]:
    return [KNForwardTest(orchestrator)]
