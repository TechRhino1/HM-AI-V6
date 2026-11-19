"""Prove the Markets section serves real, live data: fetch the exchanges directly (independently of
jarvis.markets) and compare with what the API returns at the same moment.

    python tools/markets_live_audit.py            # in-process (no server needed)
    python tools/markets_live_audit.py --url http://127.0.0.1:8501   # against a running server

Fails (exit 1) on any mismatch beyond tolerance or any value served without provenance.
Writes reports/MARKETS_LIVE_AUDIT_<date>.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import urlencode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class Served:
    def __init__(self, base: str | None) -> None:
        self.base = base

    def get(self, path: str, **params):
        if self.base:
            import requests
            return requests.get(f"{self.base}{path}?{urlencode(params)}", timeout=60).json()
        from jarvis.markets.api import _HANDLERS, require_provenance
        out = _HANDLERS[path]({k: [str(v)] for k, v in params.items()})
        require_provenance(out)
        return out


def direct_nse():
    from curl_cffi import requests as cffi
    s = cffi.Session(impersonate="chrome")
    s.get("https://www.nseindia.com/option-chain", timeout=15)
    h = {"Referer": "https://www.nseindia.com/option-chain"}
    info = s.get("https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY", timeout=15, headers=h).json()
    exp = info["expiryDates"][0]
    v3 = s.get(f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry={exp}", timeout=15, headers=h).json()
    ai = s.get("https://www.nseindia.com/api/allIndices", timeout=15, headers=h).json()
    fd = s.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=15, headers=h).json()
    return exp, v3, ai, fd


def direct_inst():
    """Participant OI file, NIFTY futures and event calendar straight from nseindia.com / nsearchives."""
    import csv
    from datetime import date, timedelta
    from curl_cffi import requests as cffi
    s = cffi.Session(impersonate="chrome")
    s.get("https://www.nseindia.com/", timeout=15)
    h = {"Referer": "https://www.nseindia.com/"}
    part = None
    d = date.today()
    for _ in range(10):
        r = s.get(f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv", timeout=20, headers=h)
        if r.status_code == 200:
            fii = next(row for row in csv.reader(r.text.splitlines()) if row and row[0].strip() == "FII")
            part = {"date": d.isoformat(), "long": int(fii[1]), "short": int(fii[2])}
            break
        d -= timedelta(days=1)
    fut = s.get("https://www.nseindia.com/api/liveEquity-derivatives?index=nse50_fut", timeout=15, headers=h).json()
    ev = s.get("https://www.nseindia.com/api/event-calendar", timeout=15, headers=h).json()
    return part, fut, ev


def direct_yahoo(t: str) -> float:
    import requests
    r = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{t}?interval=1m&range=1d",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=15).json()
    return float(r["chart"]["result"][0]["meta"]["regularMarketPrice"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    args = ap.parse_args()
    api = Served(args.url)
    checks = []

    def check(name, served, direct, tol_pct, prov=None):
        ok = served is not None and direct is not None and abs(served - direct) <= abs(direct) * tol_pct / 100 + 1e-9
        checks.append({"check": name, "served": served, "direct": direct, "tol_pct": tol_pct, "ok": ok,
                       "kind": (prov or {}).get("kind"), "source": (prov or {}).get("source"), "age_sec": (prov or {}).get("age_sec")})

    t0 = time.time()
    exp, v3, ai, fd = direct_nse()
    an = api.get("/api/markets/fno/analytics", symbol="NIFTY", expiry=exp)
    check("NIFTY chain spot (NSE v3 underlying)", an.get("spot"), float(v3["records"]["underlyingValue"]), 0.15, an.get("prov"))
    raw = {float(r["strikePrice"]): r for r in v3["filtered"]["data"]}
    atm = an.get("atm_strike")
    srv_row = next((s for s in an.get("strikes", []) if s["strike"] == atm), None)
    if srv_row and atm in raw:
        for side, key in (("call", "CE"), ("put", "PE")):
            check(f"NIFTY {atm:g} {key} open interest", srv_row[side]["oi"], float(raw[atm][key]["openInterest"]), 2.0, an.get("prov"))
            check(f"NIFTY {atm:g} {key} last price", srv_row[side]["ltp"], float(raw[atm][key]["lastPrice"]), 3.0, an.get("prov"))
    vix_srv = api.get("/api/markets/vix")
    vix_dir = next(float(r["last"]) for r in ai["data"] if r["index"] == "INDIA VIX")
    check("India VIX (NSE allIndices)", vix_srv.get("value"), vix_dir, 1.0, vix_srv.get("prov"))
    idx = {r["name"]: r for r in api.get("/api/markets/indices").get("rows", [])}
    for name in ("NIFTY 50", "NIFTY BANK"):
        d = next(float(r["last"]) for r in ai["data"] if r["index"] == name)
        check(f"{name} (NSE allIndices)", (idx.get(name) or {}).get("last"), d, 0.2)
    fii_srv = {r["category"]: r["net_cr"] for r in api.get("/api/markets/fii-dii").get("rows", [])}
    for r in fd:
        check(f"{r['category']} net ₹cr {r['date']} (NSE)", fii_srv.get(r["category"]), float(r["netValue"]), 0.0)
    for sym, market, yt in (("RELIANCE", "IN", "RELIANCE.NS"), ("HDFCBANK", "IN", "HDFCBANK.NS"), ("AAPL", "US", "AAPL")):
        q = api.get("/api/markets/quote", symbols=sym, market=market)["quotes"][0]
        check(f"{sym} price (Yahoo direct)", q.get("price"), direct_yahoo(yt), 0.3, q.get("prov"))
    sx = api.get("/api/markets/quote", symbols="SENSEX", market="IN")["quotes"][0]
    check("SENSEX price (Yahoo direct, cross-source)", sx.get("price"), direct_yahoo("^BSESN"), 0.5, sx.get("prov"))

    part, fut, ev = direct_inst()
    ps = api.get("/api/markets/inst/participants", days=5)
    fii = ((ps.get("latest") or {}).get("participants") or {}).get("FII") or {}
    if part:
        same_day = (ps.get("latest") or {}).get("date") == part["date"]
        check(f"FII index futures long {part['date']} (NSCCL file)", fii.get("fut_idx_long") if same_day else None, part["long"], 0.0, ps.get("prov"))
        check(f"FII index futures short {part['date']} (NSCCL file)", fii.get("fut_idx_short") if same_day else None, part["short"], 0.0, ps.get("prov"))
    near = min(fut["data"], key=lambda r: datetime.strptime(r["expiryDate"], "%d-%b-%Y"))
    fs = next((r for r in api.get("/api/markets/inst/futures", scope="index").get("rows", []) if r["underlying"] == "NIFTY"), None)
    srv_near = (fs or {}).get("near") or {}
    check(f"NIFTY {near['expiryDate']} future LTP (NSE live)", srv_near.get("ltp"), float(near["lastPrice"]), 0.3, (fs or {}).get("prov"))
    check(f"NIFTY {near['expiryDate']} future OI (NSE live)", srv_near.get("oi"), float(near["openInterest"]), 2.0, (fs or {}).get("prov"))
    es = api.get("/api/markets/inst/events")
    today = datetime.now().date()
    up = sum(1 for r in ev if datetime.strptime(r["date"], "%d-%b-%Y").date() >= today)
    check("Upcoming NSE events count (event-calendar)", len(es.get("upcoming") or []), up, 0.0, es.get("prov"))

    # Global institutional: latest CFTC Euro FX non-commercial positions (exact) and DXY (Yahoo direct)
    import requests
    cot = requests.get("https://publicreporting.cftc.gov/resource/6dca-aqww.json",
                       params={"cftc_contract_market_code": "099741", "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": "1"},
                       timeout=60).json()[0]
    g = api.get("/api/markets/inst/global", symbol="EURUSD")
    gc = g.get("cot") or {}
    same_week = gc.get("report_date") == cot["report_date_as_yyyy_mm_dd"][:10]
    for side in ("long", "short"):
        check(f"CFTC Euro FX non-commercial {side} {cot['report_date_as_yyyy_mm_dd'][:10]} (CFTC API)",
              (gc.get("noncommercial") or {}).get(side) if same_week else None,
              float(cot[f"noncomm_positions_{side}_all"]), 0.0, gc.get("prov"))
    dl = (g.get("macro") or {}).get("dxy_live") or {}
    check("DXY (Yahoo direct)", dl.get("value"), direct_yahoo("DX-Y.NYB"), 0.3, dl.get("prov"))

    failed = [c for c in checks if not c["ok"]]
    lines = [f"# Markets live audit — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
             f"Mode: {'server ' + args.url if args.url else 'in-process API handlers'}; direct fetches from nseindia.com and Yahoo (independent of jarvis.markets).", "",
             "| Check | Served | Direct | Tolerance | Served as | Age | Result |", "|---|---:|---:|---:|---|---:|---|"]
    for c in checks:
        lines.append(f"| {c['check']} | {c['served']} | {c['direct']} | {c['tol_pct']}% | {c['kind'] or ''} {c['source'] or ''} | {c['age_sec'] if c['age_sec'] is not None else ''} | {'OK' if c['ok'] else '**MISMATCH**'} |")
    lines += ["", f"**{len(checks) - len(failed)} / {len(checks)} checks passed** in {time.time() - t0:.1f}s. "
              "Tolerances allow for the seconds between the two fetches; FII/DII must match exactly."]
    out = os.path.join(ROOT, "reports", f"MARKETS_LIVE_AUDIT_{datetime.now().strftime('%Y-%m-%d')}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    sys.stdout.reconfigure(encoding="utf-8")  # the report has ₹; cp1252 consoles cannot print it
    print("\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
