"""Read-only tools the AI may call. Each runs an existing in-process handler and returns its real
payload (provenance blocks kept), trimmed so a tool result stays small. No tool can place an order.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List

S = {"type": "string"}


def _obj(props: Dict[str, Any], required: List[str] = ()) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(required)}


MARKET3 = {"type": "string", "enum": ["FX", "IN", "US"], "description": "FX = forex/CFD via MT5 (XAUUSD, EURUSD); IN = NSE; US = US stocks/indices"}
CHART_PARAMS = _obj({"symbol": {"type": "string", "description": "e.g. XAUUSD, NIFTY, RELIANCE, AAPL"}, "market": MARKET3,
                     "interval": {"type": "string", "enum": ["M5", "M15", "H1", "H4", "D1", "W1"], "description": "bar size (H4 is FX only, W1 IN/US only); default H1"}},
                    ["symbol", "market"])
NSE_SYM = {"type": "string", "description": "NSE symbol, e.g. NIFTY, RELIANCE"}
# Parameters each /api/markets/inst/* route actually reads (others take none).
INST_PARAMS = {
    "participants": _obj({"days": {"type": "integer", "description": "history length, default 60"}}),
    "futures": _obj({"scope": {"type": "string", "enum": ["index", "stock"]}}),
    "events": _obj({"symbol": NSE_SYM}),
    "announcements": _obj({"symbol": NSE_SYM, "limit": {"type": "integer"}}),
    "delivery": _obj({"min_pct": {"type": "number", "description": "minimum delivery %"}, "symbols": {"type": "string", "description": "comma-separated NSE symbols"}}),
    "most-active": _obj({"limit": {"type": "integer"}}),
    "term-structure": _obj({"symbols": {"type": "string", "description": "comma-separated NSE symbols"}}),
    "global": _obj({"symbol": {"type": "string", "description": "engine symbol (XAUUSD, EURUSD) or NIFTY/BANKNIFTY"}}),
    "fno-universe": _obj({"symbol": NSE_SYM}),
}

# name -> (route, description, parameters)
MARKET_TOOLS: Dict[str, tuple] = {
    "fno_advise": ("/api/markets/fno/advise", "F&O adviser for one underlying: RECOMMEND / NO_TRADE with the gates, "
                   "evaluated strategies, edge after costs and the ledger's track record.",
                   _obj({"symbol": S, "expiry": S}, ["symbol"])),
    "fno_analytics": ("/api/markets/fno/analytics", "Live option-chain analytics: spot, ATM IV, expected move, max pain, "
                      "PCR, OI walls, rr25 skew, GEX, positioning.", _obj({"symbol": S, "expiry": S}, ["symbol"])),
    "fno_scan": ("/api/markets/fno/scan", "Run the adviser across indices and the most active F&O stocks (slow, ~10-60 s).",
                 _obj({"symbols": {"type": "string", "description": "comma-separated, optional"}})),
    "fno_evaluate": ("/api/markets/fno/evaluate", "Evaluate user legs on the live chain. legs format: strike:CE|PE:BUY|SELL:lots, comma-separated.",
                     _obj({"symbol": S, "expiry": S, "legs": S}, ["symbol", "legs"])),
    "fno_premium_forecast": ("/api/markets/fno/premium-forecast", "Premium distribution forecast for one option.",
                             _obj({"symbol": S, "expiry": S, "strike": {"type": "number"}, "type": {"type": "string", "enum": ["CE", "PE"]},
                                   "horizon_days": {"type": "number"}}, ["symbol", "strike", "type"])),
    "india_vix": ("/api/markets/vix", "India VIX with its 52-week range.", _obj({})),
    "fii_dii": ("/api/markets/fii-dii", "FII/DII provisional cash flows (₹ cr) plus recorded history.", _obj({})),
    "oi_spurts": ("/api/markets/oi-spurts", "Underlyings with the largest OI change today (NSE).", _obj({})),
    "indices": ("/api/markets/indices", "NSE indices: last, change %, breadth.", _obj({})),
    "quote": ("/api/markets/quote", "Quotes for symbols (comma-separated). market IN or US; raw Yahoo tickers like ^N225 with market US.",
              _obj({"symbols": S, "market": {"type": "string", "enum": ["IN", "US"]}}, ["symbols"])),
    "equities_scan": ("/api/markets/equities/scan", "Equity momentum/trend scan.", _obj({"market": {"type": "string", "enum": ["IN", "US"]}})),
    "equities_detail": ("/api/markets/equities/detail", "One stock: trend, levels, ATR-based plan.",
                        _obj({"symbol": S, "market": {"type": "string", "enum": ["IN", "US"]}}, ["symbol"])),
    "equities_news": ("/api/markets/equities/news", "Recent news headlines for a stock.",
                      _obj({"symbol": S, "market": {"type": "string", "enum": ["IN", "US"]}}, ["symbol"])),
    "ledger": ("/api/markets/ledger", "Adviser recommendation ledger: open/closed, hit rate, P&L per lot by strategy.", _obj({})),
    "chart_levels": ("/api/markets/chart/levels", "Support/resistance zones for one chart from real bars (swings, volume profile, prior day/week, "
                     "pivots, VWAP, OI walls) with each zone's measured hold rate on this symbol.", CHART_PARAMS),
    "chart_patterns": ("/api/markets/chart/patterns", "Recent chart structure for one symbol: breakouts, false breakouts, liquidity sweeps, "
                       "BOS/CHoCH, each with its prior forward-return record on this symbol.", CHART_PARAMS),
    "chart_signal": ("/api/markets/chart/signal", "The trading engine's live decision for one forex/CFD symbol: verdict, entry/SL/TP plan, "
                     "failing gates, devil's-advocate breakdown, adverse institutional flags and open positions.",
                     _obj({"symbol": {"type": "string", "description": "engine symbol, e.g. XAUUSD, EURUSD"}}, ["symbol"])),
    "chart_read": ("/api/markets/chart/read", "Five-bullet read of a chart grounded only on its levels, patterns, engine signal and quote "
                   "(deterministic when AI is unavailable). Use for 'what does this chart say'.", CHART_PARAMS),
    "overview_timeline": ("/api/markets/overview/timeline", "Today's desk timeline (from 00:00 IST), newest first: trades opened/closed, "
                          "fired alerts, AI briefs, engine verdict/gate changes, dispatch vetoes, adviser recommendations.",
                          _obj({"since": {"type": "number", "description": "epoch seconds; default start of today IST"},
                                "limit": {"type": "integer", "description": "max events (default 200)"}})),
    "overview_changes": ("/api/markets/overview/changes", "What changed since a time: equity/P&L, positions opened/closed, alerts, "
                         "per-symbol engine gate changes, index/VIX/DXY/US10Y moves, new recommendations and briefs.",
                         _obj({"since": {"type": "number", "description": "epoch seconds"}}, ["since"])),
    "sparklines": ("/api/markets/overview/sparklines", "Intraday closes for several symbols in one call (FX: MT5 M15 last 24 h; IN/US: "
                   "Yahoo 5m today), each with provenance.",
                   _obj({"symbols": {"type": "string", "description": "comma-separated"}, "market": MARKET3}, ["symbols", "market"])),
}

INST_DESCRIPTIONS = {
    "participant-oi": "Participant-wise open interest (FII/DII/Pro/Client) in index & stock futures/options.",
    "events": "Corporate events / board meetings / results calendar.",
    "bulk-deals": "Bulk and block deals.",
    "delivery": "Delivery percentage by stock.",
    "rollover": "Futures rollover and basis.",
}


def _q(args: Dict[str, Any]) -> Dict[str, List[str]]:
    return {k: [f"{v:g}" if isinstance(v, float) else str(v)] for k, v in (args or {}).items() if v not in (None, "")}


def _handlers() -> Dict[str, Callable]:
    from jarvis.markets.api import _HANDLERS
    return _HANDLERS


def _inst_tools() -> Dict[str, tuple]:
    """`/api/markets/inst/*` routes that exist right now (built by another module; may be absent)."""
    out = {}
    for path, fn in sorted(_handlers().items()):
        if not path.startswith("/api/markets/inst/"):
            continue
        slug = path.rsplit("/", 1)[-1]
        desc = INST_DESCRIPTIONS.get(slug) or ((fn.__doc__ or "").strip().splitlines() or [f"Institutional data: {slug}"])[0]
        out["inst_" + slug.replace("-", "_")] = (path, desc, INST_PARAMS.get(slug) or _obj({}))
    return out


# ---------------------------------------------------------------- forex side (read-only)

def _forex_account(_args) -> Dict[str, Any]:
    from jarvis.application.state_manager import GLOBAL_STATE
    snap = GLOBAL_STATE.get_state_snapshot()
    return {"account": snap.get("account"), "positions": snap.get("positions"), "positions_count": snap.get("positions_count"),
            "execution_mode": snap.get("execution_mode"), "safe_mode": snap.get("safe_mode"),
            "prov": {"source": "jarvis state manager (MT5 broker sync)", "kind": "live", "as_of": None,
                     "note": f"snapshot {snap.get('timestamp')} UTC"}}


def _forex_risk(_args) -> Dict[str, Any]:
    """Mirrors GET /api/risk_status without touching the HTTP layer."""
    from jarvis.api.server import JarvisRequestHandler as H
    mt5 = getattr(H, "mt5_client", None)
    connected = bool(mt5 and getattr(mt5, "is_connected", False))
    acc = mt5.get_account_snapshot() if connected else None
    pos = mt5.get_open_positions() if connected else []
    synced = {}
    if acc is None:
        from jarvis.application.state_manager import GLOBAL_STATE
        synced = GLOBAL_STATE.get_state_snapshot().get("account") or {}
    equity = float(getattr(acc, "equity", 0.0) or synced.get("equity") or 0.0)
    balance = float(getattr(acc, "balance", 0.0) or synced.get("balance") or 0.0)
    if equity <= 0:
        return {"status": "UNAVAILABLE", "error": "No broker account synced yet",
                "prov": {"source": "broker", "kind": "unavailable", "as_of": None}}
    orch = getattr(H, "orchestrator", None)
    if orch is not None and hasattr(orch, "risk_engine"):
        r = orch.risk_engine.get_risk_status(equity, balance, account=acc, positions=pos)
    else:
        from jarvis.risk.risk_engine import RiskEngine
        r = RiskEngine().get_risk_status(equity, balance, account=acc, positions=pos)
    r = dict(r) if isinstance(r, dict) else {"risk": r}
    r["prov"] = {"source": "risk engine over " + ("MT5 account" if acc else "last synced account"), "kind": "live", "as_of": time.time()}
    return r


def _calibration(_args) -> Dict[str, Any]:
    from jarvis.backtesting import exit_geometry as eg
    from jarvis.config.settings import SETTINGS
    rows = []
    for sym in list(getattr(SETTINGS.trading, "symbols", []) or []):
        prof = eg.live_profile(sym)
        rows.append({"symbol": sym, "geometry_mode": getattr(prof, "geometry_mode", None),
                     "oos_trades": getattr(prof, "oos_trades", None), "oos_win_rate": getattr(prof, "oos_win_rate", None),
                     "oos_expectancy_r": getattr(prof, "oos_expectancy_r", None),
                     "oos_profit_factor": getattr(prof, "oos_profit_factor", None), "refusal": eg.deployment_refusal(sym)})
    return {"min_oos_expectancy_r": eg.MIN_OOS_EXPECTANCY_R, "min_oos_trades": eg.MIN_OOS_TRADES, "symbols": rows,
            "prov": {"source": "calibration manifest (out-of-sample backtests)", "kind": "eod", "as_of": None}}


LOCAL_TOOLS: Dict[str, tuple] = {
    "forex_account": (_forex_account, "Forex/CFD trading account: balance, equity, open positions, mode.", _obj({})),
    "forex_risk": (_forex_risk, "Forex risk status: drawdown, daily loss limits, portfolio heat.", _obj({})),
    "calibration_deployment": (_calibration, "Per forex symbol: out-of-sample backtest evidence and whether the live "
                               "deployment gate lets it trade (validated edge or refusal).", _obj({})),
}


def specs() -> List[Dict[str, Any]]:
    """Neutral tool specs, deterministic order (sorted by name) so provider prompt caches stay warm."""
    all_ = {**{n: (d, p) for n, (_, d, p) in MARKET_TOOLS.items()}, **{n: (d, p) for n, (_, d, p) in _inst_tools().items()},
            **{n: (d, p) for n, (_, d, p) in LOCAL_TOOLS.items()}}
    return [{"name": n, "description": d, "parameters": p} for n, (d, p) in sorted(all_.items())]


def execute(name: str, args: Dict[str, Any]) -> Any:
    if name in LOCAL_TOOLS:
        return trim(LOCAL_TOOLS[name][0](args or {}))
    route = (MARKET_TOOLS.get(name) or _inst_tools().get(name) or (None,))[0]
    if route is None:
        return {"error": f"unknown tool {name}"}
    fn = _handlers().get(route)
    if fn is None:
        return {"error": f"route {route} not available"}
    return trim(fn(_q(args)))


# ---------------------------------------------------------------- trimming

MAX_LIST = 25


def trim(obj: Any, depth: int = 0) -> Any:
    """Keep prov blocks intact; strikes → ±10 around ATM; long lists capped (with a count)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "prov":
                out[k] = v
            elif k == "strikes" and isinstance(v, list) and v:
                atm = obj.get("atm_strike")
                i = next((j for j, s in enumerate(v) if isinstance(s, dict) and s.get("strike") == atm), len(v) // 2)
                out[k] = [trim(s, depth + 1) for s in v[max(0, i - 10): i + 11]]
                out["strikes_note"] = f"{len(out[k])} of {len(v)} strikes shown (±10 around ATM)"
            else:
                out[k] = trim(v, depth + 1)
        return out
    if isinstance(obj, list):
        body = [trim(x, depth + 1) for x in obj[:MAX_LIST]]
        return body + ([{"truncated": f"{len(obj) - MAX_LIST} more rows omitted"}] if len(obj) > MAX_LIST else [])
    if isinstance(obj, str) and len(obj) > 1500:
        return obj[:1500] + "…"
    return obj



def provs(payload: Any, tool: str) -> List[Dict[str, Any]]:
    """Every provenance block in a payload, for citations."""
    out: List[Dict[str, Any]] = []

    def walk(o):
        if isinstance(o, dict):
            p = o.get("prov")
            if isinstance(p, dict):
                out.append({"tool": tool, "source": p.get("source"), "kind": p.get("kind"),
                            "age_sec": p.get("age_sec"), "as_of": p.get("as_of"), "note": p.get("note")})
            for k, v in o.items():
                if k != "prov":
                    walk(v)
        elif isinstance(o, list):
            for v in o[:50]:
                walk(v)
    walk(payload)
    return out
