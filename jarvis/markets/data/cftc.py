"""CFTC Commitments of Traders (Legacy, futures only) from the CFTC Public Reporting API.

Source: https://publicreporting.cftc.gov/resource/6dca-aqww.json (Socrata dataset 6dca-aqww,
"Legacy - Futures Only"). One report per week: positions as of Tuesday's close, released by the CFTC
on Friday 15:30 ET (Monday/Tuesday after a US holiday). Stored weekly in markets.db (`cot_weekly`);
a week the CFTC did not publish is absent, never filled.

Speculative positioning = "non-commercial" long/short (the Legacy report's large speculators);
hedgers = "commercial". The COT index is where this week's non-commercial net sits in its own
trailing 3-year (156 report) min-max range, 0..100.
"""
from __future__ import annotations

import calendar
import logging
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import requests

from .models import Provenance, unavailable

logger = logging.getLogger(__name__)
DATASET = "6dca-aqww"
URL = f"https://publicreporting.cftc.gov/resource/{DATASET}.json"
SOURCE = f"cftc:publicreporting/{DATASET} (Legacy COT, futures only)"
HISTORY_FROM = "2010-01-01"
COT_WINDOW = 156  # weekly reports in 3 years
EXTREME_LO, EXTREME_HI = 10, 90

# market key -> (CFTC contract market code, label)
MARKETS = {
    "EUR": ("099741", "Euro FX (CME)"),
    "GBP": ("096742", "British Pound (CME)"),
    "JPY": ("097741", "Japanese Yen (CME)"),
    "CAD": ("090741", "Canadian Dollar (CME)"),
    "GOLD": ("088691", "Gold (COMEX)"),
    "BTC": ("133741", "Bitcoin (CME)"),
    "ETH": ("146021", "Ether cash-settled (CME)"),
    "USD": ("098662", "USD Index (ICE)"),
}
_BY_CODE = {code: k for k, (code, _) in MARKETS.items()}
# trading symbol -> (market, sign). sign -1: the future is the symbol's quote currency, so speculators long
# JPY futures are short USDJPY.
SYMBOL_MAP = {"EURUSD": ("EUR", 1), "GBPUSD": ("GBP", 1), "USDJPY": ("JPY", -1), "USDCAD": ("CAD", -1),
              "XAUUSD": ("GOLD", 1), "BTCUSD": ("BTC", 1), "ETHUSD": ("ETH", 1)}
FIELDS = ("open_interest_all", "noncomm_positions_long_all", "noncomm_positions_short_all",
          "comm_positions_long_all", "comm_positions_short_all")
_session = requests.Session()
_checked = [0.0]


def _con():
    from . import store
    con = store._db()
    con.execute("CREATE TABLE IF NOT EXISTS cot_weekly (market TEXT, date TEXT, oi INTEGER, nc_long INTEGER, nc_short INTEGER, "
                "comm_long INTEGER, comm_short INTEGER, PRIMARY KEY (market, date))")
    return con


def parse(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Socrata rows → [{market, date, oi, nc_long, nc_short, comm_long, comm_short}]. Rows of other
    contracts, or missing any field, are skipped (never filled)."""
    out = []
    for r in rows or []:
        m = _BY_CODE.get(str(r.get("cftc_contract_market_code", "")).strip())
        if not m or any(r.get(f) in (None, "") for f in FIELDS):
            continue
        out.append({"market": m, "date": str(r["report_date_as_yyyy_mm_dd"])[:10], "oi": int(r["open_interest_all"]),
                    "nc_long": int(r["noncomm_positions_long_all"]), "nc_short": int(r["noncomm_positions_short_all"]),
                    "comm_long": int(r["comm_positions_long_all"]), "comm_short": int(r["comm_positions_short_all"])})
    return out


def fetch(since: str = HISTORY_FROM, markets: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    codes = ",".join(f"'{MARKETS[m][0]}'" for m in (markets or MARKETS))
    params = {"$where": f"cftc_contract_market_code in({codes}) AND report_date_as_yyyy_mm_dd >= '{since}'",
              "$order": "report_date_as_yyyy_mm_dd", "$limit": "50000"}
    r = _session.get(URL, params=params, timeout=60)
    r.raise_for_status()
    return parse(r.json())


def store_rows(rows: List[Dict[str, Any]]) -> int:
    from . import store
    with store._lock, _con() as con:
        con.executemany("INSERT OR REPLACE INTO cot_weekly VALUES (?,?,?,?,?,?,?)",
                        [(r["market"], r["date"], r["oi"], r["nc_long"], r["nc_short"], r["comm_long"], r["comm_short"]) for r in rows])
    return len(rows)


def latest_stored() -> Optional[str]:
    with _con() as con:
        return con.execute("SELECT MIN(d) FROM (SELECT MAX(date) d FROM cot_weekly GROUP BY market)").fetchone()[0]


def refresh() -> Dict[str, Any]:
    """Incremental: fetch every report since the oldest market's last stored week (full history on first run)."""
    last = latest_stored()
    since = (date.fromisoformat(last) - timedelta(days=7)).isoformat() if last else HISTORY_FROM
    n = store_rows(fetch(since))
    return {"since": since, "rows": n, "latest": latest_stored()}


def ensure_fresh() -> None:
    """Refresh at most every 6 h, and only when a newer report can exist (last stored week > 7 days old)."""
    if time.time() - _checked[0] < 6 * 3600:
        return
    _checked[0] = time.time()
    last = latest_stored()
    if last and (date.today() - date.fromisoformat(last)).days < 10:
        return
    try:
        refresh()
    except Exception as exc:  # stored history stays usable
        logger.info("cftc refresh: %s", exc)


def history(market: str) -> List[Dict[str, Any]]:
    with _con() as con:
        rows = con.execute("SELECT date, oi, nc_long, nc_short, comm_long, comm_short FROM cot_weekly WHERE market=? ORDER BY date",
                           (market,)).fetchall()
    return [{"date": d, "oi": oi, "nc_long": a, "nc_short": b, "comm_long": c, "comm_short": e} for d, oi, a, b, c, e in rows]


def cot_index(nets: List[float], window: int = COT_WINDOW) -> Optional[float]:
    """Last value's position in the min-max range of the last `window` values (inclusive), 0..100.
    None without a full window or with a flat range."""
    if len(nets) < window:
        return None
    w = nets[-window:]
    lo, hi = min(w), max(w)
    return round((w[-1] - lo) / (hi - lo) * 100, 1) if hi > lo else None


def derive(hist: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per week: non-commercial net, net % of OI, 1-week change, 3-year COT index; commercial net."""
    out, nets = [], []
    for i, h in enumerate(hist):
        net = h["nc_long"] - h["nc_short"]
        nets.append(net)
        out.append({**h, "nc_net": net, "nc_net_pct_oi": round(net / h["oi"] * 100, 2) if h["oi"] else None,
                    "nc_net_chg_1w": net - nets[-2] if i else None, "cot_index_3y": cot_index(nets),
                    "comm_net": h["comm_long"] - h["comm_short"]})
    return out


def _epoch(iso: str) -> float:
    return float(calendar.timegm(date.fromisoformat(iso).timetuple()))


def release_date(report_iso: str) -> str:
    """CFTC releases Tuesday's positions on the Friday of the same week (holiday weeks slip to Monday)."""
    return (date.fromisoformat(report_iso) + timedelta(days=3)).isoformat()


def prov_for(report_iso: str, weeks: int) -> Provenance:
    return Provenance(source=SOURCE, kind="eod", as_of=_epoch(report_iso),
                      note=f"positions as of Tuesday {report_iso}, released Friday {release_date(report_iso)} 15:30 ET; "
                           f"{weeks} weekly reports stored")


def positioning(symbol: str) -> Dict[str, Any]:
    """Latest COT block for a trading symbol, oriented to the symbol (inverted for USDJPY / USDCAD)."""
    sym = symbol.upper()
    if sym not in SYMBOL_MAP:
        return {"symbol": sym, "prov": unavailable(SOURCE, f"no CFTC futures market maps to {sym}").to_dict()}
    market, sign = SYMBOL_MAP[sym]
    ensure_fresh()
    rows = derive(history(market))
    if not rows:
        return {"symbol": sym, "market": market, "prov": unavailable(SOURCE, "no COT reports fetched or stored").to_dict()}
    last = rows[-1]
    idx = last["cot_index_3y"]
    return {
        "symbol": sym, "market": market, "contract": MARKETS[market][1], "cftc_code": MARKETS[market][0],
        "orientation": "direct" if sign > 0 else "inverted (future is the quote currency)",
        "report_date": last["date"], "release_date": release_date(last["date"]), "open_interest": last["oi"],
        "noncommercial": {"long": last["nc_long"], "short": last["nc_short"], "net": last["nc_net"],
                          "net_pct_oi": last["nc_net_pct_oi"], "chg_1w": last["nc_net_chg_1w"], "cot_index_3y": idx},
        "commercial": {"long": last["comm_long"], "short": last["comm_short"], "net": last["comm_net"]},
        "for_symbol": {"spec_net": sign * last["nc_net"], "spec_chg_1w": sign * last["nc_net_chg_1w"] if last["nc_net_chg_1w"] is not None else None,
                       "cot_index_3y": (idx if sign > 0 else round(100 - idx, 1)) if idx is not None else None},
        "history": [{"date": r["date"], "nc_net": r["nc_net"], "cot_index_3y": r["cot_index_3y"]} for r in rows[-26:]],
        "prov": prov_for(last["date"], len(rows)).to_dict(),
    }


def symbol_index_series(symbol: str) -> List[Dict[str, Any]]:
    """[{date, cot_index_3y (symbol-oriented)}] over all stored weeks with a full 3-year window."""
    market, sign = SYMBOL_MAP[symbol.upper()]
    return [{"date": r["date"], "cot_index_3y": r["cot_index_3y"] if sign > 0 else round(100 - r["cot_index_3y"], 1)}
            for r in derive(history(market)) if r["cot_index_3y"] is not None]
