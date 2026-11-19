"""Market data layer: parsing real recorded payloads, provenance grading and the serve-time guard."""
import json
import time
from pathlib import Path

import pytest

from jarvis.markets.api import ProvenanceMissing, require_provenance
from jarvis.markets.data import bse, nse
from jarvis.markets.data.models import Provenance, grade

FX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FX / name).read_text(encoding="utf-8"))


def test_nse_chain_keeps_real_bid_ask_and_oi_change():
    fx = _load("nse_nifty_chain.json")
    c = nse.parse_chain("NIFTY", fx["contract_info"], fx["v3"], fx["contract_info"]["expiryDates"][0], "https://www.nseindia.in", True)
    raw = {float(r["strikePrice"]): r for r in fx["v3"]["filtered"]["data"]}
    assert c.spot == fx["v3"]["records"]["underlyingValue"]
    for row in c.rows:
        ce = raw[row.strike].get("CE")
        if ce and ce.get("buyPrice1"):
            assert row.call.bid == ce["buyPrice1"] and row.call.ask == ce["sellPrice1"]  # exchange book, not ltp ± x%
            assert row.call.oi_change == ce["changeinOpenInterest"]
        if ce and not ce.get("impliedVolatility"):
            assert row.call.iv is None  # 0 from the exchange means "not quoted", not 0% IV
    assert c.prov.source.endswith("@www.nseindia.in")
    assert [r.strike for r in c.rows] == sorted(r.strike for r in c.rows)


def test_lot_size_comes_from_order_book_quantities():
    fx = _load("nse_nifty_chain.json")
    c = nse.parse_chain("NIFTY", fx["contract_info"], fx["v3"], fx["contract_info"]["expiryDates"][0], "h://x", True)
    assert c.lot_size == 65  # NSE NIFTY lot on the recording date


def test_bse_sensex_chain_parses_call_and_put_sides():
    fx = _load("bse_sensex_chain.json")
    row = next(r for r in fx["Table"] if r.get("Open_Interest"))
    put = bse._side(row, "")
    assert put.oi == int(float(row["Open_Interest"])) and put.bid == float(row["BidPrice"])
    assert bse._side(row, "C_") is not None


def test_grade_uses_real_age_not_source_claims():
    now = time.time()
    assert grade("s", now - 5, True, 60).kind == "live"
    assert grade("s", now - 900, True, 60).kind == "stale"
    assert grade("s", now - 900, False, 60).kind == "close"
    assert grade("s", now, True, 60, delay_sec=900).kind == "delayed"
    assert grade("s", None, True, 60).kind == "unavailable"
    with pytest.raises(ValueError):
        Provenance(source="s", kind="estimated", as_of=now)


def test_values_without_provenance_are_refused():
    require_provenance({"quotes": [{"price": 1.0, "prov": {}}]})
    require_provenance({"rows": [{"strike": 1, "call": {"ltp": 2.0}}], "prov": {}})  # inherited
    with pytest.raises(ProvenanceMissing):
        require_provenance({"rows": [{"price": 101.5}]})
