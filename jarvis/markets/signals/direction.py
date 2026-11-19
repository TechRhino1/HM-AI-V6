"""Direction model per symbol, validated walk-forward on real daily bars before it may be used.

Label: is the close 5 trading days ahead higher than today's close.
Model: logistic regression on price/volume features computed only from data up to the bar.
Validation: strictly forward, expanding window, 5-day embargo between train and test.
A model is *published* only if its out-of-sample Brier score beats the base-rate forecast
(the training-window up-frequency) by a margin and over enough test days. Unpublished
models contribute nothing: the adviser treats their symbol as "no validated direction".
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional

import numpy as np

HORIZON = 5
MIN_TEST = 150
MIN_BRIER_GAIN = 0.002  # absolute Brier improvement over the base rate required to publish


def features(bars: List[Dict[str, float]]) -> np.ndarray:
    c = np.array([b["close"] for b in bars], dtype=float)
    h = np.array([b["high"] for b in bars], dtype=float)
    lo = np.array([b["low"] for b in bars], dtype=float)
    v = np.array([b.get("volume") or 0.0 for b in bars], dtype=float)
    n = len(c)
    f = np.full((n, 8), np.nan)
    lr = np.diff(np.log(c), prepend=np.nan)
    for i in range(60, n):
        w20, w5 = c[i - 19:i + 1], c[i - 4:i + 1]
        up = np.clip(np.diff(c[i - 14:i + 1]), 0, None).sum()
        dn = -np.clip(np.diff(c[i - 14:i + 1]), None, 0).sum()
        rv5 = np.nanstd(lr[i - 4:i + 1])
        rv20 = np.nanstd(lr[i - 19:i + 1])
        vol20 = v[i - 19:i + 1].mean()
        f[i] = [
            math.log(c[i] / c[i - 1]), math.log(c[i] / c[i - 5]), math.log(c[i] / c[i - 20]),
            c[i] / w20.mean() - 1, c[i] / c[i - 49:i + 1].mean() - 1,
            (up / (up + dn) if up + dn > 0 else 0.5) - 0.5,
            (rv5 / rv20 - 1) if rv20 > 0 else 0.0,
            (v[i] / vol20 - 1) if vol20 > 0 else 0.0,
        ]
        _ = (h, lo, w5)
    return f


def labels(bars: List[Dict[str, float]]) -> np.ndarray:
    c = np.array([b["close"] for b in bars], dtype=float)
    y = np.full(len(c), np.nan)
    y[:-HORIZON] = (c[HORIZON:] > c[:-HORIZON]).astype(float)
    return y


def walk_forward(bars: List[Dict[str, float]], first_train: int = 250, step: int = 21) -> Dict[str, Any]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    X, y = features(bars), labels(bars)
    ok = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
    idx = np.where(ok)[0]
    if len(idx) < first_train + MIN_TEST:
        return {"published": False, "reason": f"only {len(idx)} usable days (need {first_train + MIN_TEST})"}
    p_model, p_base, truth = [], [], []
    start = first_train
    while start < len(idx):
        test = idx[start:start + step]
        train = idx[:max(0, start - HORIZON)]  # embargo: drop training labels that overlap the test window
        if len(train) < 100 or len(test) == 0:
            start += step
            continue
        sc = StandardScaler().fit(X[train])
        m = LogisticRegression(C=0.5, max_iter=500).fit(sc.transform(X[train]), y[train])
        p_model += list(m.predict_proba(sc.transform(X[test]))[:, 1])
        p_base += [float(y[train].mean())] * len(test)
        truth += list(y[test])
        start += step
    pm, pb, t = np.array(p_model), np.array(p_base), np.array(truth)
    brier_m, brier_b = float(np.mean((pm - t) ** 2)), float(np.mean((pb - t) ** 2))
    hit = float(np.mean((pm > 0.5) == (t > 0.5)))
    published = len(t) >= MIN_TEST and brier_b - brier_m >= MIN_BRIER_GAIN
    # Calibration table of the OOS forecasts, so the UI can show what "60%" has meant historically.
    bins = []
    for lo_b in (0.0, 0.4, 0.45, 0.5, 0.55, 0.6):
        hi_b = {0.0: 0.4, 0.4: 0.45, 0.45: 0.5, 0.5: 0.55, 0.55: 0.6, 0.6: 1.01}[lo_b]
        mask = (pm >= lo_b) & (pm < hi_b)
        if mask.sum() >= 10:
            bins.append({"range": f"{lo_b:.2f}-{min(hi_b, 1):.2f}", "n": int(mask.sum()), "predicted": round(float(pm[mask].mean()), 3),
                         "actual": round(float(t[mask].mean()), 3)})
    return {"published": published, "n_test": int(len(t)), "brier_model": round(brier_m, 5), "brier_base": round(brier_b, 5),
            "brier_gain": round(brier_b - brier_m, 5), "hit_rate": round(hit, 4), "base_up_rate": round(float(t.mean()), 4),
            "calibration": bins,
            "reason": None if published else f"OOS Brier {brier_m:.4f} does not beat base rate {brier_b:.4f} by {MIN_BRIER_GAIN}"}


def latest_probability(bars: List[Dict[str, float]]) -> Optional[float]:
    """Fit on all labelled history and score today's bar (only used for published models)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    X, y = features(bars), labels(bars)
    ok = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
    if ok.sum() < 200 or np.isnan(X[-1]).any():
        return None
    sc = StandardScaler().fit(X[ok])
    m = LogisticRegression(C=0.5, max_iter=500).fit(sc.transform(X[ok]), y[ok])
    return float(m.predict_proba(sc.transform(X[-1:]))[0, 1])


def _registry_path() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "markets_models.json")


def registry() -> Dict[str, Any]:
    try:
        with open(_registry_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def validated_view(symbol: str, market: str, forecast_vol: Optional[float]) -> Dict[str, Any]:
    """Probability and annual drift for the adviser — only for symbols whose model was published."""
    rec = registry().get("direction", {}).get(f"{market}:{symbol.upper()}")
    if not rec or not rec.get("published"):
        return {"validated": False, "reason": (rec or {}).get("reason") or "no validation run for this symbol",
                "drift": 0.0, "record": rec}
    from ..data import yahoo
    b = yahoo.bars(symbol, market, "1d", "5y")
    bars = b["bars"][:-1] if b.get("last_bar_forming") else b["bars"]
    p = latest_probability(bars)
    if p is None or not forecast_vol:
        return {"validated": False, "reason": "could not score today's bar", "drift": 0.0, "record": rec}
    from statistics import NormalDist
    h = HORIZON / 252
    pc = min(max(p, 0.01), 0.99)
    mu_h = forecast_vol * math.sqrt(h) * NormalDist().inv_cdf(pc) + 0.5 * forecast_vol ** 2 * h
    return {"validated": True, "p_up_5d": round(p, 4), "drift": mu_h / h, "record": rec}
