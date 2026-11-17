"""Trend portfolio, regime eligibility and meta-label v2 research on frozen real XM MT5 bars (Phase C).

Question (2026-11-17): combined into one portfolio on a $545 account with broker minimum lots, do the trend
components that pass tools/strategy_research.verdict (min-lot affordability aside) earn money, and at which
min-lot risk cap does the drawdown stay inside the 20% halt? Which regimes should the router fund, and does
a meta-label on new features add anything?

Components: every (symbol, candidate, TF) row of `strategy_research.py --trend` whose verdict reasons are only
    min-lot affordability (sr.edge_passes). Trades are re-generated here by sr.trend_raws on the same bars, so
    every cost rule (next-open entry, real spread, slippage, swap, stop first) is unchanged.
    Caveat: components are chosen on the full sample; the walk-forward selection check below measures that.
Pre-registered sizing (live settings, nothing fitted):
    target risk per position = equity at the previous UTC day's close x 1% (risk.max_risk_per_trade_pct)
        x vol scale x HRP multiplier. Every stop is 3 x ATR, so equal $ risk per stop is ATR risk parity.
    vol scale = clip(10% / annualised std of the account's own last 63 daily returns, 0.25, 2); 1 until 20
        days exist. Only past returns, a fixed target, no full-sample constant (Moreira-Muir look-ahead).
    HRP multiplier = clip(w x N, 0, 2): jarvis.risk.hrp_allocator.allocate_hrp_weights on the components'
        daily R series over the 756 days before each calendar quarter (components with >= 252 days of
        history and non-zero variance); 1 otherwise. This is the correlation cap.
    lots = floor(target / ($ risk per lot) / min lot) x min lot. Below one min lot: take the min lot only if
        its risk <= cap x equity (risk.min_lot_max_risk_pct semantics), else skip.
    Live RiskEngine limits: at most 3 open positions, 2 per symbol (first come by entry time); a 6-position
        variant is reported as sensitivity. Margin, volume steps above the minimum and commissions are ignored.
    Equity is marked to market at every bar close (bid for longs, ask for shorts); swap is booked at exit.
Validation: 4 equal calendar folds from the day half the components are live to the last bar; each fold is
    also a fresh $545 account. Benchmarks: each component alone (same sizing) and an equal-weight,
    daily-rebalanced buy-and-hold of the portfolio's symbols.
Gate (at a cap): final equity > start in >= 3 of 4 fresh-account folds, full-period Sharpe > buy-and-hold Sharpe,
    and max drawdown < 20% in the full run and in every fold. If 5% fails only on drawdown, the highest cap
    in CAPS that passes is recommended.
Regime eligibility: regime of the decision bar on the trade's own TF by tools/smc_research.regime (ADX,
    BB-width percentile, ATR5/ATR50, variance ratio; completed bars). A family x regime cell is ineligible if
    folds 1-2 hold >= 30 trades with expectancy <= 0; confirmed on folds 3-4. News: entry within +-30 min of a
    data/news_history_usd.json event (2018+ only).
Meta-label v2 (2018+ trades, news coverage): features regime one-hot, VR, hours to the next / since the last
    USD event, side x US500 20-day return, ATR5/ATR50, entry session one-hot. Logistic regression, label R > 0,
    jarvis.learning.walk_forward.PurgedKFold (5 splits, 2% embargo) plus purging of train trades whose
    life overlaps the test window. Adopt only if mean OOS AUC > 0.55 and the top half by score beats the
    bottom half in every fold.

Usage:
    python tools/portfolio_research.py <bars.pkl> <sr_trend.json> <outdir> [--start YYYY-MM-DD]   # bars: sr --fetch-universe
    python tools/portfolio_research.py --selftest                            # includes look-ahead perturbation

Results: reports/PORTFOLIO_ROUTER_RESEARCH_2026-11-17.md
"""
import os, sys, json, pickle
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import strategy_research as sr
import smc_research as smc
from jarvis.risk.hrp_allocator import HierarchicalRiskParityAllocator
from jarvis.learning.walk_forward import PurgedKFold

ACCOUNT, RISK_PCT, DD_HALT = 545.0, 0.01, 0.20
MAX_OPEN, MAX_SYM = 3, 2
TARGET_VOL, VOL_WIN, VS_LO, VS_HI = 0.10, 63, 0.25, 2.0
HRP_WIN, HRP_MIN, MULT_MAX = 756, 252, 2.0
CAPS = (0.05, 0.045, 0.04, 0.035, 0.03, 0.025, 0.02, 0.015, 0.01)
NEWS_MIN, NEWS_FROM = 30, pd.Timestamp("2018-01-01")
REGIMES = ("TREND", "RANGE", "HIGH_VOL_SHOCK", "DEAD")
MIN_CELL = 30
DAY_NS = 86_400 * 10**9
NEWS_PATH = os.path.join(os.path.dirname(HERE), "data", "news_history_usd.json")


# ── trades with daily mark-to-market paths ──────────────────────────────────

def mtm(a, side, i, j, r, sd):
    """Daily (UTC day index, R increment) of one trade: marks at every bar close from entry to exit, the last
    mark is the net R (costs + swap). Increments sum to r."""
    j0 = i + 1
    entry = a["o"][j0] + a["spr"][j0] if side == 1 else a["o"][j0]
    px = a["c"][j0:j] if side == 1 else a["c"][j0:j] + a["spr"][j0:j]
    v = np.append(side * (px - entry) / sd, r)
    d = a["tc"][j0:j + 1] // DAY_NS
    last = np.r_[d[1:] != d[:-1], True]
    return d[last], np.diff(np.r_[0.0, v[last]])


def load_news():
    ev = json.load(open(NEWS_PATH))["events"]
    t = pd.to_datetime([e["utc_iso"] for e in ev], utc=True).tz_localize(None)
    return np.sort(t.values.astype("datetime64[ns]").astype(np.int64))


def news_feats(t_ns, news):
    """Hours since the last and to the next scheduled USD event (capped at 168) and the +-30 min flag."""
    k = np.searchsorted(news, t_ns)
    big = 10**18
    prev = np.where(k > 0, news[np.maximum(k - 1, 0)], -big)
    nxt = np.where(k < len(news), news[np.minimum(k, len(news) - 1)], big)
    h = 3600 * 10**9
    since, to = np.minimum((t_ns - prev) / h, 168), np.minimum((nxt - t_ns) / h, 168)
    return since, to, np.minimum(since, to) * 60 <= NEWS_MIN


def cross_ret(t_ns, d1):
    """US500 20-bar D1 return as of the last D1 bar completed at t_ns (decision time)."""
    tc = d1["t_close"].values.astype("datetime64[ns]").astype(np.int64)
    r20 = (d1.close / d1.close.shift(20) - 1).to_numpy()
    k = np.searchsorted(tc, t_ns, side="right") - 1
    return np.where(k >= 0, r20[np.maximum(k, 0)], np.nan)


def build_trades(data, comps, news):
    """All sub-system trades of the components with paths and decision-time features."""
    cache, rows, paths = {}, [], []
    us = sr.setup("US500", data["US500"])[5]["D1"] if "US500" in data else None
    for comp in comps:
        name, cand, tf = comp.split("|")
        if name not in cache:
            info, slip, wk, ref, real_start, P, A = sr.setup(name, data[name])
            cache[name] = (info, P, A, {})
        info, P, A, regs = cache[name]
        if tf not in regs:
            regs[tf] = smc.regime(P[tf])
        a, rg, tvps = A[tf], regs[tf], sr.tvps(info)
        for k, raw in enumerate(sr.trend_raws(A, P, cand, tf)):
            for r, sd, side, i, j in zip(raw["strategy"], raw["sd"], raw["side"], raw["i"], raw["j"]):
                paths.append(mtm(a, side, i, j, r, sd))
                rows.append({"comp": comp, "sym": name, "cand": cand, "tf": tf, "sub": k, "side": side, "r": r,
                             "entry_ns": a["to"][i + 1], "exit_ns": a["tc"][j], "dec_ns": a["tc"][i],
                             "rpl": sd * tvps, "vmin": info["volume_min"],
                             "reg": rg.lab.iat[i], "vr": rg.vr.iat[i], "ar": rg.ar.iat[i], "adx": rg.adx.iat[i]})
    T = pd.DataFrame(rows)
    T["path"] = paths
    T["since_h"], T["to_h"], T["news"] = news_feats(T.entry_ns.to_numpy(), news)
    T["xret"] = T.side * (cross_ret(T.dec_ns.to_numpy(), us) if us is not None else np.nan)
    T["hour"] = pd.to_datetime(T.entry_ns).dt.hour
    T["entry"] = pd.to_datetime(T.entry_ns)
    return T.sort_values(["entry_ns", "comp", "sub"]).reset_index(drop=True)


# ── sizing pieces (past data only) ──────────────────────────────────────────

def vol_scale(eq_hist):
    """eq_hist: settled daily equity up to the previous day (oldest first)."""
    e = np.asarray(eq_hist[-(VOL_WIN + 1):], float)
    if len(e) < 21:
        return 1.0
    sd = np.std(np.diff(e) / e[:-1]) * np.sqrt(365)
    return float(np.clip(TARGET_VOL / sd, VS_LO, VS_HI)) if sd > 0 else VS_HI


def comp_daily(T, g0, nd):
    """Days x components matrix of daily R (mean over the sub-systems)."""
    M = pd.DataFrame(0.0, index=range(nd), columns=sorted(T.comp.unique()))
    for comp, (d, inc) in zip(T.comp, T.path):
        np.add.at(M[comp].values, d - g0, inc / 3.0)
    return M


def hrp_mults(M, first_day, q_starts):
    """{quarter start day index: {comp: multiplier}} from the HRP_WIN days strictly before each quarter."""
    out = {}
    for s in q_starts:
        w = M.iloc[max(0, s - HRP_WIN):max(0, s)]
        elig = [c for c in M.columns if s - first_day[c] >= HRP_MIN and w[c].var() > 0]
        if len(elig) < 2:
            out[s] = {}
            continue
        hw = HierarchicalRiskParityAllocator.allocate_hrp_weights(w[elig])
        out[s] = {c: float(np.clip(hw[c] * len(elig), 0, MULT_MAX)) for c in elig}
    return out


# ── account simulation ──────────────────────────────────────────────────────

def simulate(T, cap, frac=False, mults=None, q_starts=None, E0=ACCOUNT, max_open=MAX_OPEN, g0=None, nd=None):
    """Sequential $ account over T (sorted by entry). Returns daily equity, taken mask and counts."""
    if g0 is None:
        g0 = int(T.entry_ns.min() // DAY_NS)
        nd = int(max(p[0][-1] for p in T.path) - g0 + 1)
    pnl, eq = np.zeros(nd), np.full(nd, np.nan)
    settled, E, opn = 0, E0, []
    taken, risk_pct, n_cap, n_lim = np.zeros(len(T), bool), np.zeros(len(T)), 0, 0
    qs = np.asarray(q_starts if q_starts is not None else [], int)
    for x, t in enumerate(T.itertuples(index=False)):
        de = int(t.entry_ns // DAY_NS) - g0
        while settled < de:
            E += pnl[settled]; eq[settled] = E; settled += 1
        if E <= 0:
            break
        opn = [o for o in opn if o[0] > t.entry_ns]
        if len(opn) >= max_open or sum(o[1] == t.sym for o in opn) >= MAX_SYM:
            n_lim += 1
            continue
        m = 1.0
        if mults is not None and len(qs):
            q = qs[qs <= de]
            m = mults[int(q[-1])].get(t.comp, 1.0) if len(q) else 1.0
        target = E * RISK_PCT * vol_scale(eq[max(0, settled - VOL_WIN - 1):settled]) * m
        if frac:
            risk = target
        else:
            lots = np.floor(target / t.rpl / t.vmin + 1e-9) * t.vmin
            if lots < t.vmin:
                if t.rpl * t.vmin > cap * E:
                    n_cap += 1
                    continue
                lots = t.vmin
            risk = lots * t.rpl
        d, inc = t.path
        pnl[d - g0] += inc * risk
        opn.append((t.exit_ns, t.sym))
        taken[x], risk_pct[x] = True, risk / E
    while settled < nd:
        E += pnl[settled]; eq[settled] = E; settled += 1
    eq = pd.Series(eq).ffill().fillna(E0).to_numpy()
    return {"eq": eq, "taken": taken, "risk_pct": risk_pct, "n_cap": n_cap, "n_lim": n_lim, "g0": g0}


def metrics(eq, E0=ACCOUNT):
    eq = np.maximum(np.asarray(eq, float), 1e-9)
    r = eq / np.r_[E0, eq[:-1]] - 1
    yrs = len(eq) / 365.25
    peak = np.maximum.accumulate(np.r_[E0, eq])[1:]
    return {"final": round(float(eq[-1]), 2), "cagr": round(float((eq[-1] / E0) ** (1 / yrs) - 1), 4),
            "sharpe": round(float(r.mean() / r.std() * np.sqrt(365)), 2) if r.std() > 0 else 0.0,
            "max_dd": round(float(np.max(1 - eq / peak)), 4)}


def run_sim(T, cap, frac, mults, q_starts, folds, max_open=MAX_OPEN):
    """Full-period run plus each fold as a fresh $545 account. q_starts / mults keyed by day from folds[0][0]."""
    g0 = int(folds[0][0] // DAY_NS)
    Tp = T[T.entry_ns >= folds[0][0]]
    nd = int(max(p[0][-1] for p in Tp.path) - g0 + 1)
    full = simulate(Tp, cap, frac, mults, q_starts, max_open=max_open, g0=g0, nd=nd)
    attempted = int(full["taken"].sum()) + full["n_cap"]
    out = {"full": metrics(full["eq"]), "taken": int(full["taken"].sum()), "skipped_cap": full["n_cap"],
           "skipped_limits": full["n_lim"], "skip_share": round(full["n_cap"] / attempted, 3) if attempted else None,
           "median_risk_pct": round(float(np.median(full["risk_pct"][full["taken"]])) * 100, 2) if full["taken"].any() else None,
           "folds": []}
    for a, b in folds:
        Tf = T[(T.entry_ns >= a) & (T.entry_ns < b)]
        if Tf.empty:
            out["folds"].append(None)
            continue
        fg0 = int(a // DAY_NS)
        fnd = int(max(p[0][-1] for p in Tf.path) - fg0 + 1)
        sh = fg0 - g0
        fm = {q - sh: v for q, v in mults.items()} if mults is not None else None
        s = simulate(Tf, cap, frac, fm, [q - sh for q in q_starts], max_open=max_open, g0=fg0, nd=fnd)
        out["folds"].append({**metrics(s["eq"]), "taken": int(s["taken"].sum()), "skipped_cap": s["n_cap"]})
    out["eq"] = full["eq"]
    return out


def buy_hold(data, syms, folds):
    """Equal-weight, daily-rebalanced long of syms on the UTC calendar grid (D1 closes, forward-filled)."""
    g0 = int(folds[0][0] // DAY_NS)
    idx = pd.RangeIndex(g0, int(folds[-1][1] // DAY_NS) + 1)
    cl = {}
    for s in syms:
        d1 = sr.prep(data[s]["frames"]["D1"], "D1", data[s]["info"], {"bps": 0, "usd": 0, "model": "usd"})
        day = d1["t_close"].values.astype("datetime64[ns]").astype(np.int64) // DAY_NS
        cl[s] = pd.Series(d1.close.to_numpy(), index=day).groupby(level=0).last().reindex(idx).ffill()
    rets = pd.DataFrame(cl).pct_change(fill_method=None).mean(axis=1).fillna(0).to_numpy()
    eq = ACCOUNT * np.cumprod(1 + rets)
    out = {"full": metrics(eq), "folds": []}
    for a, b in folds:
        sl = slice(int(a // DAY_NS) - g0, int(b // DAY_NS) - g0)
        out["folds"].append(metrics(ACCOUNT * np.cumprod(1 + rets[sl])))
    return out


def gate(res, bh):
    f = [x for x in res["folds"] if x]
    pos = sum(x["final"] > ACCOUNT for x in f)
    worst = max([res["full"]["max_dd"]] + [x["max_dd"] for x in f])
    why = []
    if pos < 3: why.append(f"positive in {pos}/4 folds")
    if res["full"]["sharpe"] <= bh["full"]["sharpe"]: why.append(f"Sharpe {res['full']['sharpe']} <= buy-hold {bh['full']['sharpe']}")
    if worst >= DD_HALT: why.append(f"max DD {worst:.1%} >= 20% halt")
    return not why, why, pos, worst


# ── regime eligibility and meta-label v2 ────────────────────────────────────

def fold_of(T, folds):
    return np.select([(T.entry_ns >= a) & (T.entry_ns < b) for a, b in folds], [1, 2, 3, 4], 0)


def regime_table(T):
    T = T[T.fold > 0].assign(fam=lambda x: x.cand + "|" + x.tf)
    rows, elig = [], {}
    for fam, g in T.groupby("fam"):
        for reg in REGIMES:
            c = g[g.reg == reg]
            a, b = c[c.fold <= 2].r, c[c.fold >= 3].r
            bad = len(a) >= MIN_CELL and a.mean() <= 0
            elig[(fam, reg)] = not bad
            conf = None if len(b) < MIN_CELL or len(a) < MIN_CELL else bool((a.mean() > 0) == (b.mean() > 0))
            rows.append({"family": fam, "regime": reg, "n12": len(a), "exp12": round(a.mean(), 3) if len(a) else None,
                         "n34": len(b), "exp34": round(b.mean(), 3) if len(b) else None,
                         "eligible": not bad, "confirmed_34": conf})
    k = np.array([elig.get((f, r), True) for f, r in zip(T.fam, T.reg)])
    t34 = (T.fold >= 3).to_numpy()
    summary = {"exp34_all": round(T[t34].r.mean(), 3), "n34_all": int(t34.sum()),
               "exp34_eligible": round(T[t34 & k].r.mean(), 3), "n34_eligible": int((t34 & k).sum()),
               "exp34_ineligible": round(T[t34 & ~k].r.mean(), 3) if (t34 & ~k).any() else None,
               "n34_ineligible": int((t34 & ~k).sum())}
    summary["adopt_filter"] = bool(summary["n34_ineligible"] >= MIN_CELL and summary["exp34_eligible"] > summary["exp34_all"]
                                   and summary["exp34_ineligible"] <= 0)
    news = []
    Tn = T[T.entry >= NEWS_FROM]
    for fam, g in Tn.groupby("fam"):
        for tag, sel in (("1-2", g.fold <= 2), ("3-4", g.fold >= 3)):
            i_, o_ = g[sel & g.news].r, g[sel & ~g.news].r
            news.append({"family": fam, "folds": tag, "n_in": len(i_), "exp_in": round(i_.mean(), 3) if len(i_) else None,
                         "n_out": len(o_), "exp_out": round(o_.mean(), 3) if len(o_) else None})
    return rows, summary, news


def meta_features(T):
    X = pd.DataFrame({"vr": T.vr, "ar": T.ar, "since_h": T.since_h, "to_h": T.to_h, "xret": T.xret})
    for reg in REGIMES:
        X["reg_" + reg] = (T.reg == reg).astype(float)
    for nm, (a, b) in {"asia": (0, 7), "london": (7, 12), "ny": (12, 17), "late": (17, 24)}.items():
        X["sess_" + nm] = ((T.hour >= a) & (T.hour < b)).astype(float)
    return X


def meta_label(T):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    from sklearn.metrics import roc_auc_score
    T = T[T.entry >= NEWS_FROM].sort_values("entry_ns").reset_index(drop=True)
    X = meta_features(T)
    ok = X.notna().all(axis=1).to_numpy()
    T, X = T[ok].reset_index(drop=True), X[ok].reset_index(drop=True)
    y = (T.r > 0).astype(int).to_numpy()
    ent, ext, folds = T.entry_ns.to_numpy(), T.exit_ns.to_numpy(), []
    for tr, te in PurgedKFold(n_splits=5, embargo_frac=0.02).split(len(T)):
        lo, hi = ent[te[0]], ext[te].max()
        tr = tr[(ext[tr] < lo) | (ent[tr] > hi)]   # PurgedKFold only embargoes; also drop overlapping trade lives
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(X.iloc[tr], y[tr])
        p = m.predict_proba(X.iloc[te])[:, 1]
        top = p >= np.median(p)
        rt = T.r.to_numpy()[te]
        folds.append({"n_train": len(tr), "n_test": len(te), "auc": round(float(roc_auc_score(y[te], p)), 3),
                      "top_exp": round(float(rt[top].mean()), 3), "bottom_exp": round(float(rt[~top].mean()), 3)})
    auc = float(np.mean([f["auc"] for f in folds]))
    adopt = auc > 0.55 and all(f["top_exp"] > f["bottom_exp"] for f in folds)
    return {"n": len(T), "base_rate": round(float(y.mean()), 3), "folds": folds, "mean_auc": round(auc, 3),
            "adopt": bool(adopt), "features": list(X.columns)}


# ── driver ──────────────────────────────────────────────────────────────────

def components(srj):
    return sorted(f"{n}|{key}" for n, d in srj.items() for key, s in d.items()
                  if isinstance(s, dict) and "reasons" in s and sr.edge_passes(s))


def research(data, srj, outdir, start=None):
    comps = components(srj)
    print("components:", comps, flush=True)
    T = build_trades(data, comps, load_news())
    first = T.groupby("comp").entry_ns.min().sort_values()
    p0, p1 = int(first.iloc[(len(first) - 1) // 2]), int(T.exit_ns.max())
    if start is not None:   # sensitivity: a later period start (e.g. when every component is live)
        p0 = max(p0, int(pd.Timestamp(start).value))
    edges = np.linspace(p0, p1, 5).astype(np.int64)
    edges[-1] += 1
    folds = list(zip(edges[:-1], edges[1:]))
    T["fold"] = fold_of(T, folds)
    g0, a0 = int(p0 // DAY_NS), int(T.entry_ns.min() // DAY_NS)
    M = comp_daily(T, a0, int(max(p[0][-1] for p in T.path) - a0 + 1))
    fd = {c: int(T[T.comp == c].entry_ns.min() // DAY_NS) - a0 for c in M.columns}
    q_abs = [int(q.value // DAY_NS) for q in pd.date_range(pd.Timestamp(p0).normalize(), pd.Timestamp(p1), freq="QS")]
    m_abs = hrp_mults(M, fd, [q - a0 for q in q_abs])
    mults = {q - g0: m_abs[q - a0] for q in q_abs}
    q_starts = sorted(mults)
    res = {"components": comps, "folds": [[str(pd.Timestamp(a)), str(pd.Timestamp(b))] for a, b in folds],
           "n_trades": len(T), "n_trades_in_period": int((T.fold > 0).sum()),
           "hrp_last_quarter": mults[q_starts[-1]] if q_starts else {}}
    bh = buy_hold(data, sorted(T.sym.unique()), folds)
    res["buy_hold"] = bh
    print("buy_hold", bh["full"], [f["final"] for f in bh["folds"]], flush=True)
    res["portfolio"], curves = {}, {}
    runs = [("fractional", 0.0, True, MAX_OPEN)] + [(f"minlot_{c:.3f}", c, False, MAX_OPEN) for c in CAPS] \
        + [("minlot_0.050_open6", 0.05, False, 6), ("minlot_0.025_open6", 0.025, False, 6), ("fractional_open6", 0.0, True, 6)]
    for label, cap, frac, mo in runs:
        r = run_sim(T, cap, frac, mults, q_starts, folds, mo)
        ok, why, pos, worst = gate(r, bh)
        r.update(gate=ok, gate_reasons=why, pos_folds=pos, worst_dd=round(worst, 4))
        curves[label] = r.pop("eq")
        res["portfolio"][label] = r
        print(label, r["full"], "pos", pos, "worstDD", round(worst, 3), "skip", r["skip_share"], "GATE" if ok else why, flush=True)
    caps_ok = [c for c in CAPS if res["portfolio"][f"minlot_{c:.3f}"]["gate"]]
    res["recommended_cap"] = max(caps_ok) if caps_ok else None
    cap_eval = res["recommended_cap"] or 0.05
    res["cap_for_components"] = cap_eval
    res["components_alone"] = {}
    for c in comps:
        Tc = T[T.comp == c]
        if Tc[Tc.entry_ns >= p0].empty:
            continue
        r, rf = run_sim(Tc, cap_eval, False, None, [], folds), run_sim(Tc, 0.0, True, None, [], folds)
        r.pop("eq"); rf.pop("eq")
        res["components_alone"][c] = {"minlot": r, "fractional": rf, "n_period": int((Tc.fold > 0).sum()),
                                      "exp_r_period": round(float(Tc[Tc.fold > 0].r.mean()), 3)}
    wf = []   # selection-bias check: per fold, only components whose trades closed before it passed an edge rule
    for k, (a, b) in enumerate(folds[1:], 2):
        past = T[T.exit_ns < a].groupby("comp").r
        ok = [c for c, g in past if len(g) >= 30 and g.mean() > 0 and g[g > 0].sum() / max(-g[g < 0].sum(), 1e-9) > 1.1]
        r = None
        if ok:
            sh = int(a // DAY_NS) - g0
            r = run_sim(T[T.comp.isin(ok)], cap_eval, False, {q - sh: v for q, v in mults.items()},
                        [q - sh for q in q_starts], [(a, b)])
            r.pop("eq")
        wf.append({"fold": k, "components": ok, "result": r["folds"][0] if r else None})   # fresh $545, fold entries only
    res["walk_forward_selection"] = wf
    res["regime_table"], res["regime_summary"], res["news_table"] = regime_table(T)
    res["meta_label"] = meta_label(T)
    print("regime", res["regime_summary"], "\nmeta", res["meta_label"]["mean_auc"], res["meta_label"]["adopt"], flush=True)
    os.makedirs(outdir, exist_ok=True)
    json.dump(res, open(os.path.join(outdir, "portfolio_results.json"), "w"), indent=1, default=str)
    pd.DataFrame(curves).to_csv(os.path.join(outdir, "portfolio_equity.csv"))
    T.drop(columns=["path"]).to_parquet(os.path.join(outdir, "portfolio_trades.parquet"))
    return res


# ── selftest ────────────────────────────────────────────────────────────────

def _trade(entry_day, days, incs, rpl, sym="S", comp="C", vmin=0.01):
    return {"comp": comp, "sym": sym, "entry_ns": entry_day * DAY_NS + 1, "exit_ns": (days[-1] + 1) * DAY_NS,
            "rpl": rpl, "vmin": vmin, "path": (np.array(days), np.array(incs, float))}


def selftest():
    # mark-to-market increments sum to the net R and land on the bar-close days
    n = 6
    a = {"o": np.array([100, 100, 101, 102, 103, 104.]), "c": np.array([100, 101, 102, 103, 104, 105.]),
         "spr": np.full(n, 0.2), "tc": (np.arange(n) + 1) * DAY_NS // 2}
    d, inc = mtm(a, 1, 0, 4, 1.234, 2.0)
    assert abs(inc.sum() - 1.234) < 1e-12 and list(d) == [1, 2]
    # min-lot cap: $ risk per lot 1000 -> min lot (0.01) risks $10 = 1.8% of $545; the 1% target ($5.45) is below it
    T = pd.DataFrame([_trade(0, [0, 1], [0.0, 1.0], 1000.0, "A"), _trade(5, [5], [-1.0], 2000.0, "B")])
    s = simulate(T, 0.025)
    assert s["taken"].tolist() == [True, False] and s["n_cap"] == 1 and abs(s["eq"][-1] - 555.0) < 1e-9
    s = simulate(T, 0.05)                                   # B risks $20 = 3.6% of $555 -> fits 5%
    assert s["taken"].tolist() == [True, True] and abs(s["eq"][-1] - 535.0) < 1e-9
    assert simulate(T, 0.05, max_open=1)["taken"].all()     # the position limit only binds on overlap
    T2 = pd.DataFrame([_trade(0, [0, 9], [0.0, 1.0], 1000.0, "A"), _trade(5, [5], [-1.0], 1000.0, "B")])
    assert simulate(T2, 0.05, max_open=1)["taken"].tolist() == [True, False]
    m = metrics(np.array([600.0, 545.0, 654.0]))
    assert abs(m["max_dd"] - 55 / 600) < 1e-4 and m["final"] == 654.0
    # look-ahead perturbation 1: a trade entering on day 30 must not change equity or sizing before day 30
    rng = np.random.default_rng(3)
    base = [_trade(k, [k, k + 1, k + 2], rng.normal(0, 0.5, 3), 10.0, sym=f"S{k % 5}") for k in range(0, 60, 2)]
    late = _trade(30, [30, 31], [5.0, -9.0], 10.0, sym="Z")
    T1 = pd.DataFrame(base)
    T2 = pd.DataFrame(base + [late]).sort_values("entry_ns", kind="stable").reset_index(drop=True)
    s1 = simulate(T1, 0.05, frac=True, g0=0, nd=70, max_open=99)
    s2 = simulate(T2, 0.05, frac=True, g0=0, nd=70, max_open=99)
    assert np.allclose(s1["eq"][:30], s2["eq"][:30]) and not np.allclose(s1["eq"][31:], s2["eq"][31:])
    early = (T1.entry_ns < 30 * DAY_NS).to_numpy()
    assert np.allclose(s1["risk_pct"][early], s2["risk_pct"][:early.sum()])
    # look-ahead perturbation 2: HRP multipliers for a quarter use only days before it
    M = pd.DataFrame(rng.normal(0, 1, (1200, 3)), columns=["a", "b", "c"])
    M2 = M.copy(); M2.iloc[900:] = rng.normal(0, 5, (300, 3))
    fd = {"a": 0, "b": 0, "c": 0}
    assert hrp_mults(M, fd, [900]) == hrp_mults(M2, fd, [900]) and hrp_mults(M, fd, [900])[900]
    # look-ahead perturbation 3: regime labels and cross-asset feature at bar k ignore later bars
    m = 1200
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, m)))
    df = pd.DataFrame({"open": c, "high": c * 1.003, "low": c * 0.997, "close": c})
    df2 = df.copy(); df2.iloc[801:] *= 1.5
    assert smc.regime(df).iloc[:801].equals(smc.regime(df2).iloc[:801])
    t_ns = (np.arange(m) * DAY_NS).astype(np.int64)
    d1 = pd.DataFrame({"t_close": pd.to_datetime(t_ns), "close": c})
    d1b = d1.copy(); d1b.loc[801:, "close"] *= 2
    assert np.allclose(cross_ret(t_ns[:801], d1), cross_ret(t_ns[:801], d1b), equal_nan=True)
    since, to, near = news_feats(np.array([0, 10 * 60 * 10**9]), np.array([20 * 60 * 10**9]))
    assert near.tolist() == [True, True] and abs(to[0] - 1 / 3) < 1e-9
    print("selftest ok")


def main():
    if sys.argv[1] == "--selftest":
        return selftest()
    start = sys.argv[sys.argv.index("--start") + 1] if "--start" in sys.argv else None
    research(pickle.load(open(sys.argv[1], "rb")), json.load(open(sys.argv[2])), sys.argv[3], start)


if __name__ == "__main__":
    main()
