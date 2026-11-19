"""Institutional data from NSE: participant-wise OI, futures basis/rollover, bulk & block deals, corporate
events and announcements, delivery %, 52-week highs/lows, most active contracts, F&O ban list and the
ATM IV term structure.

Every value is parsed from an NSE API response or an NSE archive file. Daily archive files
(participant OI, security-wise delivery) are stored in markets.db so history accumulates; a day
with no file (holiday, weekend, not yet published) is skipped, never filled.

    daily_job()  — idempotent; refreshes participant OI (last 10 trading days) and delivery history
                   (last 30 trading days), then precomputes the every-F&O-stock summary (refresh_all_fno →
                   table inst_fno_universe, served by /api/markets/inst/fno-universe). Safe to call
                   repeatedly, e.g. once per recorder cycle after 18:00 IST; already-stored days cost no requests.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from .data import feeds, nse
from .data.models import Provenance, grade, unavailable
from .data.nse import CLIENT, IST, NotPublished, SourceError, _ist_epoch, _src
from .options import chain_analytics
from .options.pricing import years_to_expiry

logger = logging.getLogger(__name__)
POLITE_SEC = 0.34  # ≤ 3 archive requests per second
TERM_SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")
INDEX_FUT_LISTS = ("nse50_fut", "nifty_bank_fut", "finnifty_fut", "niftynxt50_fut")  # NSE serves no live MIDCPNIFTY list
INDEX_UNDERLYINGS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50")
DELIV_VOL_X, DELIV_PCT_X, DELIV_MIN_HISTORY = 1.5, 1.2, 10

# ---------------------------------------------------------------- storage

def _con():
    from .data import store
    con = store._db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS inst_participant_oi (date TEXT, category TEXT, payload TEXT, PRIMARY KEY (date, category));
        CREATE TABLE IF NOT EXISTS inst_delivery (date TEXT, symbol TEXT, close REAL, volume REAL, deliv_qty REAL,
            deliv_pct REAL, PRIMARY KEY (date, symbol));
    """)
    return con


def _lock():
    from .data import store
    return store._lock


def _close_epoch(iso: str) -> float:
    """A daily file describes the session that ended 15:30 IST on its date."""
    return datetime.fromisoformat(iso).replace(hour=15, minute=30, tzinfo=IST).timestamp()


# ---------------------------------------------------------------- 1. participant-wise OI

PARTICIPANT_FIELDS = {
    "Future Index Long": "fut_idx_long", "Future Index Short": "fut_idx_short",
    "Future Stock Long": "fut_stk_long", "Future Stock Short": "fut_stk_short",
    "Option Index Call Long": "opt_idx_call_long", "Option Index Put Long": "opt_idx_put_long",
    "Option Index Call Short": "opt_idx_call_short", "Option Index Put Short": "opt_idx_put_short",
    "Option Stock Call Long": "opt_stk_call_long", "Option Stock Put Long": "opt_stk_put_long",
    "Option Stock Call Short": "opt_stk_call_short", "Option Stock Put Short": "opt_stk_put_short",
    "Total Long Contracts": "total_long", "Total Short Contracts": "total_short",
}
PARTICIPANTS = ("Client", "DII", "FII", "Pro")


def parse_participant_oi(text: str) -> Dict[str, Dict[str, int]]:
    """NSCCL fao_participant_oi CSV → {"FII": {"fut_idx_long": n, ...}, ...} (contracts)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    hdr_i = next(i for i, ln in enumerate(lines) if ln.startswith("Client Type"))
    reader = csv.reader(lines[hdr_i:])
    header = [h.strip() for h in next(reader)]
    out: Dict[str, Dict[str, int]] = {}
    for row in reader:
        cat = row[0].strip() if row else ""
        if cat not in PARTICIPANTS:
            continue
        out[cat] = {PARTICIPANT_FIELDS[h]: int(float(v)) for h, v in zip(header[1:], row[1:]) if h in PARTICIPANT_FIELDS and v.strip()}
    if set(out) != set(PARTICIPANTS) or any(len(v) != len(PARTICIPANT_FIELDS) for v in out.values()):
        raise SourceError(f"participant OI: unexpected layout ({sorted(out)})")
    return out


def derive(rows: Dict[str, int], prev: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    """Net positions per participant and the day change vs the previous file."""
    fl, fs = rows["fut_idx_long"], rows["fut_idx_short"]
    d = {
        "net_idx_fut": fl - fs,
        "fut_idx_long_pct": round(fl / (fl + fs) * 100, 2) if fl + fs else None,
        "net_stk_fut": rows["fut_stk_long"] - rows["fut_stk_short"],
        "idx_call_net": rows["opt_idx_call_long"] - rows["opt_idx_call_short"],
        "idx_put_net": rows["opt_idx_put_long"] - rows["opt_idx_put_short"],
    }
    if prev:
        p = derive(prev)
        for k in ("net_idx_fut", "net_stk_fut", "idx_call_net", "idx_put_net"):
            d[f"{k}_chg"] = d[k] - p[k]
        d["fut_idx_long_pct_chg"] = round(d["fut_idx_long_pct"] - p["fut_idx_long_pct"], 2) \
            if d["fut_idx_long_pct"] is not None and p["fut_idx_long_pct"] is not None else None
    return d


def _fetch_participant_day(d: date) -> None:
    raw, _ = CLIENT.get_archive(f"/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv")
    rows = parse_participant_oi(raw.decode("utf-8", "replace"))
    with _lock(), _con() as con:
        con.executemany("INSERT OR REPLACE INTO inst_participant_oi VALUES (?,?,?)",
                        [(d.isoformat(), c, json.dumps(v)) for c, v in rows.items()])


def _stored(table: str) -> set:
    with _con() as con:
        return {r[0] for r in con.execute(f"SELECT DISTINCT date FROM {table}")}


def _walk_back(table: str, fetch: Callable[[date], None], days: int, polite: bool = True) -> Dict[str, Any]:
    """Make sure the last `days` trading days of a daily archive file are stored. Weekends are skipped
    without a request; a 404 is a holiday (or not yet published) and is skipped, not filled."""
    have = _stored(table)
    d = datetime.now(IST).date()
    got = fetched = missing = errors = 0
    for _ in range(int(days * 1.6) + 10):
        if got >= days or errors >= 5:
            break
        if d.weekday() < 5:
            if d.isoformat() in have:
                got += 1
            else:
                try:
                    fetch(d)
                    got += 1
                    fetched += 1
                except NotPublished:
                    missing += 1
                except SourceError as exc:
                    errors += 1
                    logger.info("inst %s %s: %s", table, d, exc)
                if polite:
                    time.sleep(POLITE_SEC)
        d -= timedelta(days=1)
    return {"trading_days": got, "fetched": fetched, "not_published": missing, "errors": errors}


def backfill(days: int = 60) -> Dict[str, Any]:
    """Fetch participant-wise OI for the last `days` trading days (NSE archives go back years)."""
    return _walk_back("inst_participant_oi", _fetch_participant_day, days)


def participant_history(days: int = 60) -> List[Dict[str, Any]]:
    """[{date, rows: {cat: {...}}}] oldest first, at most `days` trading days."""
    with _con() as con:
        raw = con.execute("SELECT date, category, payload FROM inst_participant_oi WHERE date IN "
                          "(SELECT DISTINCT date FROM inst_participant_oi ORDER BY date DESC LIMIT ?) ORDER BY date",
                          (days,)).fetchall()
    by: Dict[str, Dict[str, Any]] = {}
    for d, c, p in raw:
        by.setdefault(d, {})[c] = json.loads(p)
    return [{"date": d, "rows": r} for d, r in sorted(by.items()) if set(r) == set(PARTICIPANTS)]


def participants(days: int = 60) -> Dict[str, Any]:
    src = "nse:archive/nsccl/fao_participant_oi"
    try:
        _walk_back("inst_participant_oi", _fetch_participant_day, 3, polite=False)
    except Exception as exc:  # a fetch failure must not hide stored history
        logger.info("participants refresh: %s", exc)
    hist = participant_history(max(2, days) + 1)
    if not hist:
        return {"latest": None, "history": [], "prov": unavailable(src, "no participant OI file fetched or stored").to_dict()}
    series = []
    for i, h in enumerate(hist):
        prev = hist[i - 1]["rows"] if i else None
        row = {"date": h["date"]}
        for c in PARTICIPANTS:
            dv = derive(h["rows"][c], prev[c] if prev else None)
            row[c.lower()] = {k: dv[k] for k in ("net_idx_fut", "fut_idx_long_pct", "idx_call_net", "idx_put_net", "net_stk_fut")}
        series.append(row)
    last, prev = hist[-1], (hist[-2] if len(hist) > 1 else None)
    latest = {"date": last["date"], "participants": {
        c: {**last["rows"][c], **derive(last["rows"][c], prev["rows"][c] if prev else None)} for c in PARTICIPANTS},
        "previous_date": prev["date"] if prev else None}
    return {"latest": latest, "history": series[-days:],
            "prov": Provenance(source=src, kind="eod", as_of=_close_epoch(last["date"]),
                               note=f"NSCCL file dated {last['date']}; {len(series[-days:])} stored trading days").to_dict()}


# ---------------------------------------------------------------- 2. futures dashboard

def parse_fo_bhav(raw_zip: bytes) -> Dict[str, Any]:
    """NSE UDiFF F&O bhavcopy → futures rows keyed by (symbol, expiry ISO). OI is converted from
    quantity to contracts with the file's own lot size, matching the live API's contract counts."""
    z = zipfile.ZipFile(io.BytesIO(raw_zip))
    out: Dict[tuple, Dict[str, Any]] = {}
    trade_date = None
    with z.open(z.namelist()[0]) as f:
        for r in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8")):
            if r.get("FinInstrmTp") not in ("IDF", "STF"):
                continue
            lot = float(r["NewBrdLotQty"] or 0)
            if lot <= 0:
                continue
            trade_date = r["TradDt"]
            out[(r["TckrSymb"], r["XpryDt"])] = {
                "close": float(r["ClsPric"]), "settle": float(r["SttlmPric"]), "spot": float(r["UndrlygPric"]),
                "oi": round(float(r["OpnIntrst"]) / lot), "oi_change": round(float(r["ChngInOpnIntrst"]) / lot),
                "prev_close": float(r["PrvsClsgPric"]), "lot": int(lot), "contracts_traded": int(float(r["TtlTradgVol"] or 0)),
            }
    return {"date": trade_date, "rows": out}


_bhav_cache: Dict[str, Dict[str, Any]] = {}


def fo_bhav_before(day: date) -> Optional[Dict[str, Any]]:
    """The latest F&O bhavcopy strictly before `day` (previous trading session), or None."""
    d = day - timedelta(days=1)
    for _ in range(10):
        if d.weekday() < 5:
            key = d.isoformat()
            if key in _bhav_cache:
                return _bhav_cache[key]
            try:
                raw, host = CLIENT.get_archive(f"/content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
                b = parse_fo_bhav(raw)
                b["source"] = f"nse:archive/fo/BhavCopy_NSE_FO@{host.split('//')[1]}"
                if len(_bhav_cache) > 3:
                    _bhav_cache.clear()
                _bhav_cache[key] = b
                return b
            except NotPublished:
                pass
        d -= timedelta(days=1)
    return None


def contract_metrics(ltp: float, spot: float, expiry: str, price_chg: float, oi: int, prev_oi: Optional[int],
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """Basis, annualised basis (calendar days to the 15:30 IST expiry) and price×OI build-up."""
    dte = years_to_expiry(expiry, now) * 365
    basis = ltp - spot
    oi_chg = oi - prev_oi if prev_oi is not None else None
    return {"basis": round(basis, 2), "basis_pct": round(basis / spot * 100, 3),
            "basis_ann_pct": round(basis / spot * 100 * 365 / dte, 2), "days_to_expiry": round(dte, 2),
            "oi_change": oi_chg, "buildup": chain_analytics.buildup(price_chg, oi_chg) if oi_chg is not None else None}


def rollover(contracts: List[Dict[str, Any]]) -> Optional[float]:
    """Share of open interest in the months after the near month (contracts sorted by expiry)."""
    total = sum(c["oi"] for c in contracts)
    return round((total - contracts[0]["oi"]) / total * 100, 2) if len(contracts) > 1 and total else None


def _group(contracts: List[Dict[str, Any]], prov: Dict[str, Any]) -> Dict[str, Any]:
    cs = sorted(contracts, key=lambda c: datetime.strptime(c["expiry"], "%d-%b-%Y"))
    return {"underlying": cs[0]["underlying"], "spot": cs[0]["spot"], "near": cs[0], "next": cs[1] if len(cs) > 1 else None,
            "contracts": cs, "rollover_pct": rollover(cs), "total_oi": sum(c["oi"] for c in cs), "prov": prov}


def parse_live_futures(data: Dict[str, Any], bhav: Optional[Dict[str, Any]], session_open: bool,
                       host: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    as_of = _ist_epoch(str(data.get("timestamp") or ""), "%d-%b-%Y %H:%M:%S")
    prov = grade(_src(host, "liveEquity-derivatives"), as_of, session_open, fresh_sec=120).to_dict()
    if bhav:
        prov["note"] = f"OI change vs NSE F&O bhavcopy of {bhav['date']}"
    else:
        prov["note"] = "previous-day bhavcopy unavailable: OI change not computed"
    by: Dict[str, List[Dict[str, Any]]] = {}
    for r in data.get("data") or []:
        if r.get("instrumentType") not in ("FUTIDX", "FUTSTK"):
            continue
        ltp, spot = float(r.get("lastPrice") or 0), float(r.get("underlyingValue") or 0)
        if ltp <= 0 or spot <= 0:
            continue
        exp = r["expiryDate"]
        iso = datetime.strptime(exp, "%d-%b-%Y").date().isoformat()
        prev = (bhav or {}).get("rows", {}).get((r["underlying"], iso))
        oi = int(r.get("openInterest") or 0)
        c = {"underlying": r["underlying"], "expiry": exp, "ltp": ltp, "spot": spot, "change": r.get("change"),
             "change_pct": r.get("pChange"), "oi": oi, "volume": r.get("volume"), "value": r.get("value"),
             **contract_metrics(ltp, spot, exp, float(r.get("change") or 0), oi, prev["oi"] if prev else None, now)}
        by.setdefault(r["underlying"], []).append(c)
    return [_group(cs, prov) for cs in by.values()]


def bhav_futures(bhav: Dict[str, Any], symbols: List[str]) -> List[Dict[str, Any]]:
    """End-of-day futures rows straight from the bhavcopy, for underlyings NSE has no live list for."""
    prov = Provenance(source=bhav["source"], kind="eod", as_of=_close_epoch(bhav["date"]),
                      note=f"NSE F&O bhavcopy {bhav['date']} (no live list for this underlying)").to_dict()
    now = datetime.fromisoformat(bhav["date"]).replace(hour=15, minute=30, tzinfo=IST)
    by: Dict[str, List[Dict[str, Any]]] = {}
    for (sym, iso), r in bhav["rows"].items():
        if sym in symbols:
            exp = datetime.fromisoformat(iso).strftime("%d-%b-%Y")
            c = {"underlying": sym, "expiry": exp, "ltp": r["close"], "spot": r["spot"], "change": round(r["close"] - r["prev_close"], 2),
                 "oi": r["oi"], "contracts_traded": r["contracts_traded"],
                 **contract_metrics(r["close"], r["spot"], exp, r["close"] - r["prev_close"], r["oi"], r["oi"] - r["oi_change"], now)}
            by.setdefault(sym, []).append(c)
    return [_group(cs, prov) for cs in by.values()]


def futures(scope: str = "index") -> Dict[str, Any]:
    lists = INDEX_FUT_LISTS if scope == "index" else ("stock_fut",)
    is_open = feeds.session("IN")["open"]
    payloads, errors = [], []
    for name in lists:
        try:
            payloads.append(CLIENT.get_json(f"/api/liveEquity-derivatives?index={name}", ttl=20, referer="/market-data/equity-derivatives-watch"))
        except SourceError as exc:
            errors.append(str(exc))
    # OI change is measured against the bhavcopy of the session before the one the live data belongs to.
    stamp = _ist_epoch(str((payloads[0][0] if payloads else {}).get("timestamp") or ""), "%d-%b-%Y %H:%M:%S")
    session_day = datetime.fromtimestamp(stamp, IST).date() if stamp else datetime.now(IST).date()
    bhav = None
    try:
        bhav = fo_bhav_before(session_day)
    except SourceError as exc:
        logger.info("fo bhavcopy: %s", exc)
    rows = [g for data, host in payloads for g in parse_live_futures(data, bhav, is_open, host)]
    if scope == "index" and bhav:
        rows += bhav_futures(bhav, [s for s in INDEX_UNDERLYINGS if s not in {r["underlying"] for r in rows}])
    if not rows:
        return {"scope": scope, "rows": [], "prov": unavailable("nse:liveEquity-derivatives", "; ".join(errors) or "no rows").to_dict()}
    top = dict(rows[0]["prov"])
    top["note"] = (top.get("note") or "") + "; each row carries its own provenance" + (f"; failed: {'; '.join(errors)}" if errors else "")
    if scope == "stock":
        rows.sort(key=lambda r: -(r["near"].get("value") or 0))
    else:
        rows.sort(key=lambda r: INDEX_UNDERLYINGS.index(r["underlying"]) if r["underlying"] in INDEX_UNDERLYINGS else 99)
    return {"scope": scope, "rows": rows, "prov": top}


def futures_for(symbol: str) -> Optional[Dict[str, Any]]:
    """Live futures row for one underlying (NSE's live lists), else the latest bhavcopy row (eod)."""
    sym = symbol.upper()
    hit = next((r for r in futures("index" if sym in INDEX_UNDERLYINGS else "stock")["rows"] if r["underlying"] == sym), None)
    if hit:
        return hit
    bhav = fo_bhav_before(datetime.now(IST).date() + timedelta(days=1))
    rows = bhav_futures(bhav, [sym]) if bhav else []
    return rows[0] if rows else None


# ---------------------------------------------------------------- 3. bulk / block deals

def parse_deals(data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    out = {}
    for key, name in (("BULK_DEALS_DATA", "bulk"), ("BLOCK_DEALS_DATA", "block"), ("SHORT_DEALS_DATA", "short")):
        out[name] = [{"symbol": r.get("symbol"), "name": r.get("name"), "client": r.get("clientName"), "side": r.get("buySell"),
                      "qty": int(float(r["qty"])) if r.get("qty") not in (None, "", "-") else None,
                      "price": float(r["watp"]) if r.get("watp") not in (None, "", "-") else None,
                      "date": r.get("date"), "remarks": r.get("remarks")} for r in data.get(key) or []]
    return out


def deals() -> Dict[str, Any]:
    try:
        data, host = CLIENT.get_json("/api/snapshot-capital-market-largedeal", ttl=900, referer="/market-data/large-deals")
    except SourceError as exc:
        return {"bulk": [], "block": [], "short": [], "prov": unavailable("nse:snapshot-capital-market-largedeal", str(exc)).to_dict()}
    as_on = data.get("as_on_date")
    return {**parse_deals(data), "as_on_date": as_on,
            "prov": Provenance(source=_src(host, "snapshot-capital-market-largedeal"), kind="eod",
                               as_of=_ist_epoch(f"{as_on} 15:30", "%d-%b-%Y %H:%M"), note=f"deals as on {as_on}").to_dict()}


# ---------------------------------------------------------------- 4. events / 5. announcements

def parse_events(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows or []:
        try:
            iso = datetime.strptime(r["date"], "%d-%b-%Y").date().isoformat()
        except (KeyError, ValueError):
            continue
        out.append({"symbol": r.get("symbol"), "company": r.get("company"), "purpose": r.get("purpose"),
                    "description": (r.get("bm_desc") or "").strip(), "date": iso,
                    "is_results": "result" in (r.get("purpose") or "").lower()})
    return sorted(out, key=lambda e: e["date"])


def events(symbol: str = "") -> Dict[str, Any]:
    """Board meetings / results calendar. With a symbol: its upcoming events plus the last 120 days."""
    sym = symbol.upper().strip()
    path = f"/api/event-calendar?index=equities&symbol={sym}" if sym else "/api/event-calendar"
    try:
        data, host = CLIENT.get_json(path, ttl=1800, referer="/companies-listing/corporate-filings-event-calendar")
    except SourceError as exc:
        return {"symbol": sym or None, "upcoming": [], "recent": [], "prov": unavailable("nse:event-calendar", str(exc)).to_dict()}
    ev = parse_events(data if isinstance(data, list) else [])
    today = datetime.now(IST).date()
    cutoff = (today - timedelta(days=120)).isoformat()
    return {"symbol": sym or None, "upcoming": [e for e in ev if e["date"] >= today.isoformat()],
            "recent": [e for e in ev if cutoff <= e["date"] < today.isoformat()][::-1],
            "prov": Provenance(source=_src(host, "event-calendar"), kind="eod", as_of=time.time(),
                               note="NSE event calendar as published now; as_of is the fetch time").to_dict()}


def events_for(symbol: str, until: Optional[str] = None) -> List[Dict[str, Any]]:
    """Upcoming NSE events for a symbol (optionally up to an ISO date). Empty list when the source fails."""
    up = events(symbol).get("upcoming") or []
    return [e for e in up if until is None or e["date"] <= until]


def parse_announcements(rows: List[Dict[str, Any]], limit: int = 30) -> List[Dict[str, Any]]:
    out = []
    for r in rows or []:
        ts = _ist_epoch(str(r.get("an_dt") or ""), "%d-%b-%Y %H:%M:%S")
        out.append({"symbol": r.get("symbol"), "company": r.get("sm_name"), "subject": r.get("desc"),
                    "text": (r.get("attchmntText") or "").strip(), "time": r.get("an_dt"),
                    "published": datetime.fromtimestamp(ts, IST).isoformat() if ts else None,
                    "attachment": r.get("attchmntFile") or None})
    out.sort(key=lambda a: a["published"] or "", reverse=True)
    return out[:limit]


def announcements(symbol: str = "", limit: int = 30) -> Dict[str, Any]:
    sym = symbol.upper().strip()
    path = "/api/corporate-announcements?index=equities" + (f"&symbol={sym}" if sym else "")
    try:
        data, host = CLIENT.get_json(path, ttl=300, referer="/companies-listing/corporate-filings-announcements")
    except SourceError as exc:
        return {"symbol": sym or None, "items": [], "prov": unavailable("nse:corporate-announcements", str(exc)).to_dict()}
    items = parse_announcements(data if isinstance(data, list) else [], limit)
    if not items:
        return {"symbol": sym or None, "items": [], "prov": unavailable(_src(host, "corporate-announcements"), "no filings returned").to_dict()}
    newest = datetime.fromisoformat(items[0]["published"]).timestamp() if items[0]["published"] else None
    return {"symbol": sym or None, "items": items,
            "prov": Provenance(source=_src(host, "corporate-announcements"), kind="live", as_of=newest,
                               note=f"{len(items)} exchange filings (newest first)").to_dict()}


# ---------------------------------------------------------------- 6. delivery %

def parse_delivery(text: str) -> List[Dict[str, Any]]:
    """sec_bhavdata_full CSV → EQ-series rows with delivery %."""
    rd = csv.reader(io.StringIO(text))
    header = [h.strip() for h in next(rd)]
    out = []
    for raw in rd:
        r = {h: v.strip() for h, v in zip(header, raw)}
        if r.get("SERIES") != "EQ" or r.get("DELIV_PER") in (None, "", "-"):
            continue
        out.append({"symbol": r["SYMBOL"], "date": datetime.strptime(r["DATE1"], "%d-%b-%Y").date().isoformat(),
                    "close": float(r["CLOSE_PRICE"]), "volume": float(r["TTL_TRD_QNTY"]),
                    "deliv_qty": float(r["DELIV_QTY"]), "deliv_pct": float(r["DELIV_PER"])})
    return out


def _fetch_delivery_day(d: date) -> None:
    raw, _ = CLIENT.get_archive(f"/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv")
    rows = parse_delivery(raw.decode("utf-8", "replace"))
    if not rows:
        raise SourceError(f"delivery {d}: no EQ rows")
    with _lock(), _con() as con:
        con.executemany("INSERT OR REPLACE INTO inst_delivery VALUES (?,?,?,?,?,?)",
                        [(r["date"], r["symbol"], r["close"], r["volume"], r["deliv_qty"], r["deliv_pct"]) for r in rows])


def backfill_delivery(days: int = 30) -> Dict[str, Any]:
    return _walk_back("inst_delivery", _fetch_delivery_day, days)


def delivery_screen(history: Dict[str, List[Dict[str, Any]]], latest: str, min_pct: float = 0.0,
                    symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """`history[symbol]` = rows oldest first. A row is flagged accumulation when delivery % ≥ DELIV_PCT_X × and
    volume ≥ DELIV_VOL_X × its own average over the previous (up to) 20 sessions."""
    out = []
    for sym, rows in history.items():
        if symbols and sym not in symbols:
            continue
        if not rows or rows[-1]["date"] != latest:
            continue
        today, prior = rows[-1], rows[:-1][-20:]
        if len(prior) < DELIV_MIN_HISTORY:
            continue
        avg_v = sum(r["volume"] for r in prior) / len(prior)
        avg_d = sum(r["deliv_pct"] for r in prior) / len(prior)
        vx = today["volume"] / avg_v if avg_v else None
        dx = today["deliv_pct"] / avg_d if avg_d else None
        acc = bool(vx and dx and vx >= DELIV_VOL_X and dx >= DELIV_PCT_X and today["deliv_pct"] >= min_pct)
        if acc or symbols:
            out.append({**today, "avg_volume_20d": round(avg_v), "avg_deliv_pct_20d": round(avg_d, 2),
                        "volume_x": round(vx, 2) if vx else None, "deliv_x": round(dx, 2) if dx else None,
                        "history_days": len(prior), "accumulation": acc})
    return sorted(out, key=lambda r: -(r["volume_x"] or 0))


_DELIV_CHECKED = [0.0]


def delivery(min_pct: float = 0.0, symbols: Optional[List[str]] = None, limit: int = 50) -> Dict[str, Any]:
    src = "nse:archive/products/content/sec_bhavdata_full"
    # The file is published once a day; checking the archive on every request only adds latency and lock waits.
    if time.time() - _DELIV_CHECKED[0] > 900:
        _DELIV_CHECKED[0] = time.time()
        try:
            _walk_back("inst_delivery", _fetch_delivery_day, 2, polite=False)
        except Exception as exc:
            logger.info("delivery refresh: %s", exc)
    with _con() as con:
        dates = [r[0] for r in con.execute("SELECT DISTINCT date FROM inst_delivery ORDER BY date DESC LIMIT 21")]
        if not dates:
            return {"rows": [], "prov": unavailable(src, "no delivery file fetched or stored").to_dict()}
        rows = con.execute("SELECT date, symbol, close, volume, deliv_qty, deliv_pct FROM inst_delivery WHERE date >= ? ORDER BY date",
                           (dates[-1],)).fetchall()
    hist: Dict[str, List[Dict[str, Any]]] = {}
    for d, s, c, v, q, p in rows:
        hist.setdefault(s, []).append({"date": d, "symbol": s, "close": c, "volume": v, "deliv_qty": q, "deliv_pct": p})
    out = delivery_screen(hist, dates[0], min_pct, symbols)
    note = f"bhavdata {dates[0]}; {len(dates) - 1} prior sessions stored"
    if len(dates) - 1 < DELIV_MIN_HISTORY:
        note += f"; collecting: screen needs {DELIV_MIN_HISTORY} prior sessions (run inst.backfill_delivery)"
    return {"date": dates[0], "rows": out[:limit], "matches": len(out),
            "rule": f"delivery % ≥ {DELIV_PCT_X}× and volume ≥ {DELIV_VOL_X}× own 20-session average" + (f", delivery ≥ {min_pct}%" if min_pct else ""),
            "prov": Provenance(source=src, kind="eod", as_of=_close_epoch(dates[0]), note=note).to_dict()}


# ---------------------------------------------------------------- 7. 52-week, most active / 8. ban list

def week52() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    is_open = feeds.session("IN")["open"]
    for kind, path in (("highs", "52weekhighstock"), ("lows", "52weeklowstock")):
        try:
            data, host = CLIENT.get_json(f"/api/live-analysis-data-{path}", ttl=60, referer="/market-data/52-week-high-equity-market")
            out[kind] = {"rows": [{"symbol": r.get("symbol"), "company": r.get("comapnyName"), "series": r.get("series"),
                                   "ltp": r.get("ltp"), "change_pct": r.get("pChange"), "new_52w": r.get("new52WHL"),
                                   "prev_52w": r.get("prev52WHL"), "prev_52w_date": r.get("prevHLDate")} for r in data.get("data") or []],
                         "prov": grade(_src(host, path), _ist_epoch(str(data.get("timestamp") or ""), "%d-%b-%Y %H:%M:%S"), is_open, 180).to_dict()}
        except SourceError as exc:
            out[kind] = {"rows": [], "prov": unavailable(f"nse:{path}", str(exc)).to_dict()}
    out["prov"] = out["highs"]["prov"]
    return out


def most_active(limit: int = 20) -> Dict[str, Any]:
    try:
        data, host = CLIENT.get_json(f"/api/snapshot-derivatives-equity?index=contracts&limit={limit}", ttl=60,
                                     referer="/market-data/most-active-contracts")
    except SourceError as exc:
        return {"by_volume": [], "by_value": [], "prov": unavailable("nse:snapshot-derivatives-equity", str(exc)).to_dict()}
    is_open = feeds.session("IN")["open"]
    out: Dict[str, Any] = {}
    for key in ("volume", "value"):
        blk = data.get(key) or {}
        out[f"by_{key}"] = [{"contract": r.get("identifier"), "instrument": r.get("instrument"), "underlying": r.get("underlying"),
                             "expiry": r.get("expiryDate"), "option_type": r.get("optionType"), "strike": r.get("strikePrice"),
                             "ltp": r.get("lastPrice"), "change_pct": r.get("pChange"), "contracts": r.get("numberOfContractsTraded"),
                             "turnover_lakh": r.get("totalTurnover"), "oi": r.get("openInterest"), "spot": r.get("underlyingValue")}
                            for r in blk.get("data") or []]
        out[f"{key}_timestamp"] = blk.get("timestamp")
    as_of = _ist_epoch(str(out.get("volume_timestamp") or ""), "%d-%b-%Y %H:%M:%S")
    out["prov"] = grade(_src(host, "snapshot-derivatives-equity"), as_of, is_open, 180).to_dict()
    return out


def parse_ban(text: str) -> Dict[str, Any]:
    """fo_secban.csv: 'Securities in Ban For Trade Date 18-NOV-2026:' then '1,SYMBOL' lines (or ': NIL')."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    head = lines[0]
    d = head.split("Trade Date", 1)[1].strip().split(":")[0].strip()
    trade_date = datetime.strptime(d.title(), "%d-%b-%Y").date().isoformat()
    syms = [ln.split(",", 1)[1].strip().upper() for ln in lines[1:] if "," in ln]
    return {"trade_date": trade_date, "symbols": syms}


def ban() -> Dict[str, Any]:
    try:
        raw, host = CLIENT.get_archive("/content/fo/fo_secban.csv", ttl=900)
        b = parse_ban(raw.decode("utf-8", "replace"))
    except (SourceError, IndexError, ValueError) as exc:
        return {"symbols": [], "prov": unavailable("nse:archive/content/fo/fo_secban.csv", str(exc)).to_dict()}
    return {**b, "prov": Provenance(source=f"nse:archive/fo_secban@{host.split('//')[1]}", kind="eod",
                                    as_of=datetime.fromisoformat(b["trade_date"]).replace(hour=9, tzinfo=IST).timestamp(),
                                    note=f"securities in F&O ban for trade date {b['trade_date']}").to_dict()}


# ---------------------------------------------------------------- 9. IV term structure

def _term_one(sym: str) -> Dict[str, Any]:
    try:
        near = feeds.chain(sym)
        exps = near.expiries
        if len(exps) < 2:
            raise SourceError("fewer than two expiries listed")
        nxt = feeds.chain(sym, next(e for e in exps if e != near.expiry))
    except (SourceError, StopIteration) as exc:
        return {"symbol": sym, "near": None, "next": None, "prov": unavailable("option chain", str(exc)).to_dict()}
    legs = {}
    for name, c in (("near", near), ("next", nxt)):
        an = chain_analytics.analyse(c)
        legs[name] = {"expiry": c.expiry, "atm_iv": an["atm_iv"], "days_to_expiry": an["days_to_expiry"], "atm_strike": an["atm_strike"]}
    a, b = legs["near"]["atm_iv"], legs["next"]["atm_iv"]
    slope = round(b - a, 2) if a and b else None
    shape = None if slope is None else "upward (contango)" if slope > 0.25 else "inverted (backwardation)" if slope < -0.25 else "flat"
    return {"symbol": sym, "spot": near.spot, **legs, "slope_pts": slope, "shape": shape, "prov": near.prov.to_dict()}


def term_structure(symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    syms = list(symbols or TERM_SYMBOLS)
    with ThreadPoolExecutor(max_workers=5) as ex:
        rows = list(ex.map(_term_one, syms))
    ok = [r for r in rows if r.get("near")]
    prov = dict(ok[0]["prov"]) if ok else unavailable("option chains", "no chain answered").to_dict()
    prov["note"] = "ATM IV solved from live mids for the near and next expiry; each row carries its chain's provenance"
    return {"rows": rows, "prov": prov}


# ---------------------------------------------------------------- 10. every F&O stock, precomputed

def universe_rows(groups: List[Dict[str, Any]], deliv: List[Dict[str, Any]], upcoming: List[Dict[str, Any]],
                  banned: List[str]) -> List[Dict[str, Any]]:
    """One summary row per F&O stock from bhavcopy futures groups, the delivery screen, upcoming events and the ban list."""
    dv = {r["symbol"]: r for r in deliv or []}
    ev: Dict[str, List[Dict[str, Any]]] = {}
    for e in upcoming or []:
        ev.setdefault(e["symbol"], []).append(e)
    out = []
    for g in groups:
        sym, n = g["underlying"], g["near"]
        d, es = dv.get(sym) or {}, ev.get(sym) or []
        res = next((e["date"] for e in es if e["is_results"]), None)
        out.append({"symbol": sym, "expiry": n["expiry"], "fut_close": n["ltp"], "spot": n["spot"], "basis": n["basis"],
                    "basis_pct": n["basis_pct"], "basis_ann_pct": n["basis_ann_pct"], "days_to_expiry": n["days_to_expiry"],
                    "oi": n["oi"], "oi_change": n["oi_change"], "buildup": n["buildup"], "total_oi": g["total_oi"],
                    "expiry_week": n["days_to_expiry"] <= 7, "rollover_pct": g["rollover_pct"],
                    "deliv_pct": d.get("deliv_pct"), "deliv_x": d.get("deliv_x"), "volume_x": d.get("volume_x"),
                    "accumulation": d.get("accumulation"), "next_results": res, "upcoming_events": len(es), "in_ban": sym in banned})
    return sorted(out, key=lambda r: r["symbol"])


_UNIVERSE: Dict[str, Any] = {}
UNIVERSE_MAX_AGE = 6 * 3600


def refresh_all_fno() -> Dict[str, Any]:
    """Precompute the summary for every F&O stock (EOD bhavcopy futures, delivery, events, ban) into markets.db."""
    bhav = fo_bhav_before(datetime.now(IST).date() + timedelta(days=1))
    if not bhav:
        raise SourceError("no F&O bhavcopy in the last 10 days")
    stocks = sorted({s for s, _ in bhav["rows"] if s not in INDEX_UNDERLYINGS})
    groups = bhav_futures(bhav, stocks)
    d, ev, b = delivery(0.0, stocks, limit=100000), events(), ban()
    rows = universe_rows(groups, d.get("rows"), ev.get("upcoming"), b.get("symbols") or [])
    prov = dict(groups[0]["prov"]) if groups else unavailable(bhav["source"], "no stock futures in bhavcopy").to_dict()
    prov["note"] = f"futures/basis/build-up/rollover from NSE F&O bhavcopy {bhav['date']}; delivery, events, ban: see sources"
    payload = {"date": bhav["date"], "count": len(rows), "rows": rows,
               "summary": {k: sum(1 for r in rows if r["buildup"] == k) for k in ("long_buildup", "short_buildup", "short_covering", "long_unwinding")}
               | {"accumulation": sum(1 for r in rows if r["accumulation"]), "in_ban": sum(1 for r in rows if r["in_ban"]),
                  "results_upcoming": sum(1 for r in rows if r["next_results"])},
               "sources": {"futures": prov, "delivery": d["prov"], "events": ev["prov"], "ban": b["prov"]}, "prov": prov}
    with _lock(), _con() as con:
        con.execute("CREATE TABLE IF NOT EXISTS inst_fno_universe (date TEXT PRIMARY KEY, built REAL, payload TEXT)")
        con.execute("INSERT OR REPLACE INTO inst_fno_universe VALUES (?,?,?)", (bhav["date"], time.time(), json.dumps(payload)))
    _UNIVERSE["v"] = (time.time(), payload)
    return {"date": bhav["date"], "stocks": len(rows)}


def fno_universe() -> Dict[str, Any]:
    """Latest precomputed F&O-stock summary; rebuilt when older than 6 h (a failed rebuild serves the stored one)."""
    hit = _UNIVERSE.get("v")
    if not hit:
        with _con() as con:
            con.execute("CREATE TABLE IF NOT EXISTS inst_fno_universe (date TEXT PRIMARY KEY, built REAL, payload TEXT)")
            row = con.execute("SELECT built, payload FROM inst_fno_universe ORDER BY date DESC LIMIT 1").fetchone()
        if row:
            hit = _UNIVERSE["v"] = (row[0], json.loads(row[1]))
    if not hit or time.time() - hit[0] > UNIVERSE_MAX_AGE:
        try:
            refresh_all_fno()
            hit = _UNIVERSE["v"]
        except Exception as exc:
            logger.info("fno universe refresh: %s", exc)
    if not hit:
        return {"rows": [], "prov": unavailable("nse:archive/fo/BhavCopy_NSE_FO", "universe not built yet").to_dict()}
    return {**hit[1], "built_at": hit[0]}


# ---------------------------------------------------------------- 11. daily job

def daily_job() -> Dict[str, Any]:
    """Idempotent: store any missing participant-OI (last 10 trading days) and delivery (last 30) files, then
    precompute the every-F&O-stock summary (refresh_all_fno)."""
    out = {}
    for name, fn in (("participant_oi", lambda: backfill(10)), ("delivery", lambda: backfill_delivery(30)),
                     ("fno_universe", refresh_all_fno)):
        try:
            out[name] = fn()
        except Exception as exc:
            out[name] = {"error": f"{type(exc).__name__}: {exc}"}
    return out
