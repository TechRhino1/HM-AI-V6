"""BSE derivatives (SENSEX, BANKEX option chains) from api.bseindia.com — the only source for these."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote as urlquote

from .models import ChainRow, OptionChain, OptionSide, Provenance
from .nse import SourceError, _lot_from_book

API = "https://api.bseindia.com/BseIndiaAPI/api"
HEADERS = {"Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}
SCRIP = {"SENSEX": "1", "BANKEX": "12"}
_lock = threading.Lock()
_session = None
_cache: Dict[str, Tuple[float, Any]] = {}


def _get(url: str, ttl: float) -> Any:
    global _session
    hit = _cache.get(url)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    for attempt in (0, 1):
        try:
            with _lock:
                if _session is None or attempt == 1:
                    from curl_cffi import requests as cffi
                    _session = cffi.Session(impersonate="chrome")
                    _session.get("https://www.bseindia.com/", timeout=12)
                s = _session
            r = s.get(url, headers=HEADERS, timeout=12)
            if r.status_code == 200:
                data = r.json()
                _cache[url] = (time.time(), data)
                return data
        except Exception:
            continue
    raise SourceError(f"BSE {url.split('/api/')[-1][:60]} did not answer")


def _f(v: Any) -> float:
    try:
        return float(str(v).replace(",", "")) if str(v).strip() else 0.0
    except ValueError:
        return 0.0


def _side(row: Dict[str, Any], p: str) -> Optional[OptionSide]:
    """BSE prefixes call fields with C_ and leaves put fields bare."""
    if not row.get(f"{p}Series_Code" if p else "p_Series_Code"):
        return None
    ltp = _f(row.get(f"{p}Last_Trd_Price"))
    bid, ask = _f(row.get(f"{p}BidPrice")), _f(row.get(f"{p}OfferPrice"))
    oi = int(_f(row.get(f"{p}Open_Interest")))
    chg_oi = int(_f(row.get(f"{p}Absolute_Change_OI")))
    iv = _f(row.get(f"{p}IV"))
    prev_oi = oi - chg_oi
    return OptionSide(
        ltp=ltp, bid=bid or None, ask=ask or None,
        bid_qty=int(_f(row.get(f"{p}BIdQty"))), ask_qty=int(_f(row.get(f"{p}OfferQty"))),
        oi=oi, oi_change=chg_oi, oi_change_pct=round(chg_oi / prev_oi * 100, 2) if prev_oi > 0 else 0.0,
        volume=int(_f(row.get(f"{p}Vol_Traded"))), iv=iv if iv > 0 else None,
        change=_f(row.get(f"{p}NetChange")),
        change_pct=round(_f(row.get(f"{p}NetChange")) / (ltp - _f(row.get(f"{p}NetChange"))) * 100, 2)
        if ltp and ltp - _f(row.get(f"{p}NetChange")) > 0 else 0.0,
    )


def expiries(symbol: str) -> Dict[str, Any]:
    data = _get(f"{API}/ddlExpiry_IV/w?ProductType=IO&scrip_cd={SCRIP[symbol]}", ttl=600)
    exps = [e.get("ExpiryDate") for e in data.get("Table1") or [] if e.get("ExpiryDate")]
    spot = _f(((data.get("Table2") or [{}])[0]).get("UlaValue"))
    return {"expiries": exps, "spot": spot}


def option_chain(symbol: str, expiry: Optional[str] = None, session_open: bool = True) -> OptionChain:
    sym = symbol.upper()
    if sym not in SCRIP:
        raise SourceError(f"BSE has no option chain mapping for {sym}")
    meta = expiries(sym)
    if not meta["expiries"]:
        raise SourceError(f"BSE {sym}: no expiries listed")
    want = expiry.replace("-", " ") if expiry else None  # callers pass the normalised "19-Nov-2026" form back
    exp = want if want in meta["expiries"] else meta["expiries"][0]
    data = _get(f"{API}/DerivOptionChain_IV/w?Expiry={urlquote(exp)}&scrip_cd={SCRIP[sym]}&strprice=0", ttl=20)
    table = data.get("Table") or []
    rows = [ChainRow(strike=_f(r.get("Strike_Price1") or r.get("Strike_Price")), call=_side(r, "C_"), put=_side(r, ""))
            for r in table]
    rows = [r for r in rows if r.strike > 0 and (r.call or r.put)]
    if not rows:
        raise SourceError(f"BSE {sym} {exp}: empty chain")
    rows.sort(key=lambda r: r.strike)
    spot = _f(table[0].get("UlaValue")) or meta["spot"]
    # BSE sends no timestamp: we record when we fetched it and say so.
    prov = Provenance(source="bse:DerivOptionChain_IV@api.bseindia.com", kind="live" if session_open else "close",
                      as_of=time.time(), note="BSE payload has no timestamp; as_of is our fetch time")
    exp_norm = datetime.strptime(exp, "%d %b %Y").strftime("%d-%b-%Y")
    return OptionChain(symbol=sym, expiry=exp_norm, expiries=[datetime.strptime(e, "%d %b %Y").strftime("%d-%b-%Y") for e in meta["expiries"]],
                       spot=spot, rows=rows, lot_size=_lot_from_book(rows), prov=prov)
