"""Global institutional layer (data/cftc.py, data/macro.py, inst_global.py): parsers on real recorded CFTC /
Yahoo / FRED payloads, COT index and correlation math, adverse_flags logic and route provenance."""
import json
from pathlib import Path

import pytest

from jarvis.markets import inst_global
from jarvis.markets.api import _HANDLERS, require_provenance
from jarvis.markets.data import cftc, macro

FX = Path(__file__).parent / "fixtures"
RAW = json.loads((FX / "cftc_legacy_fut_eur_jpy.json").read_text(encoding="utf-8"))


def _hist(market):
    return [{k: r[k] for k in ("date", "oi", "nc_long", "nc_short", "comm_long", "comm_short")}
            for r in cftc.parse(RAW) if r["market"] == market]


# ---------------------------------------------------------------- CFTC

def test_cot_parse_maps_codes_and_reads_fields_exactly():
    rows = cftc.parse(RAW)
    assert {r["market"] for r in rows} == {"EUR", "JPY"}
    last_raw = next(r for r in reversed(RAW) if r["cftc_contract_market_code"] == "099741")
    last = [r for r in rows if r["market"] == "EUR"][-1]
    assert last["date"] == last_raw["report_date_as_yyyy_mm_dd"][:10]
    assert last["nc_long"] == int(last_raw["noncomm_positions_long_all"])
    assert last["nc_short"] == int(last_raw["noncomm_positions_short_all"])
    assert last["oi"] == int(last_raw["open_interest_all"])


def test_cot_parse_skips_unknown_contracts_and_missing_fields():
    bad = [{**RAW[0], "cftc_contract_market_code": "999999"}, {k: v for k, v in RAW[0].items() if k != "open_interest_all"}]
    assert cftc.parse(bad) == []


def test_cot_index_math():
    assert cftc.cot_index([1, 2, 3], window=4) is None          # not a full window
    assert cftc.cot_index([5, 5, 5], window=3) is None          # flat range
    assert cftc.cot_index([0, 10, 5], window=3) == 50.0
    assert cftc.cot_index([100, 0, 10, 5], window=3) == 50.0    # only the last `window` values count
    assert cftc.cot_index([0, 10, 10], window=3) == 100.0


def test_cot_derive_on_real_history():
    rows = cftc.derive(_hist("EUR"))
    assert len(rows) > cftc.COT_WINDOW
    a, b = rows[-2], rows[-1]
    assert b["nc_net"] == b["nc_long"] - b["nc_short"]
    assert b["nc_net_chg_1w"] == b["nc_net"] - a["nc_net"]
    assert b["nc_net_pct_oi"] == round(b["nc_net"] / b["oi"] * 100, 2)
    assert b["comm_net"] == b["comm_long"] - b["comm_short"]
    nets = [r["nc_net"] for r in rows][-cftc.COT_WINDOW:]
    assert b["cot_index_3y"] == round((nets[-1] - min(nets)) / (max(nets) - min(nets)) * 100, 1)
    assert rows[cftc.COT_WINDOW - 2]["cot_index_3y"] is None


def test_positioning_inverts_quote_currency_futures(monkeypatch):
    monkeypatch.setattr(cftc, "ensure_fresh", lambda: None)
    monkeypatch.setattr(cftc, "history", _hist)
    eur, jpy = cftc.positioning("EURUSD"), cftc.positioning("USDJPY")
    assert eur["for_symbol"]["spec_net"] == eur["noncommercial"]["net"]
    assert eur["for_symbol"]["cot_index_3y"] == eur["noncommercial"]["cot_index_3y"]
    assert jpy["for_symbol"]["spec_net"] == -jpy["noncommercial"]["net"]
    assert jpy["for_symbol"]["cot_index_3y"] == round(100 - jpy["noncommercial"]["cot_index_3y"], 1)
    assert jpy["prov"]["kind"] == "eod" and "Tuesday" in jpy["prov"]["note"] and "Friday" in jpy["prov"]["note"]
    assert jpy["release_date"] == cftc.release_date(jpy["report_date"])
    sol = cftc.positioning("SOLUSD")
    assert sol["prov"]["kind"] == "unavailable" and "noncommercial" not in sol


# ---------------------------------------------------------------- macro

def test_corr_math_on_fixed_series():
    assert macro.corr([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert macro.corr([1, 2, 3, 4], [8, 6, 4, 2]) == -1.0
    assert macro.corr([1, 2, 3, 4], [1, 1, 1, 1]) is None
    assert macro.corr([1, 2], [1, 2]) is None
    assert macro.corr([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]) == 0.8


def test_aligned_changes_uses_common_dates_and_yield_differences():
    a = {"2026-01-01": 100.0, "2026-01-02": 110.0, "2026-01-03": 121.0, "2026-01-05": 133.1}
    b = {"2026-01-01": 4.0, "2026-01-03": 4.5, "2026-01-05": 4.25}
    x, y = macro.aligned_changes(a, b, 5, True, False)
    assert y == [0.5, -0.25]
    assert x == pytest.approx([2 * 0.0953101798, 0.0953101798], rel=1e-6)


def test_fx_bars_relabelled_to_the_session_they_close():
    """Yahoo's EURUSD=X bar dated D holds the London-midnight close of the previous weekday: relabelled, the real
    6-month EURUSD/DXY daily correlation is strongly negative (unrelabelled it is near zero)."""
    raw = json.loads((FX / "yahoo_dxy_eurusd_daily_6mo.json").read_text(encoding="utf-8"))

    def closes(t, fx):
        r = raw[t]
        return {macro._day(ts, fx): c for ts, c in zip(r["timestamp"], r["close"]) if c is not None}
    dxy = closes("DX-Y.NYB", False)
    x, y = macro.aligned_changes(closes("EURUSD=X", True), dxy, 100)
    assert macro.corr(x, y) < -0.7
    x0, y0 = macro.aligned_changes(closes("EURUSD=X", False), dxy, 100)
    assert abs(macro.corr(x0, y0)) < 0.5
    assert macro._day(1794873600, True) == "2026-11-16"   # Tue 2026-11-17 00:00 UTC bar → Monday
    assert macro._day(1794787200, True) == "2026-11-13"   # Mon 2026-11-16 00:00 UTC bar → Friday


def test_fred_parser_skips_missing_observations():
    vals = macro.parse_fred((FX / "fred_dfii10_tail.csv").read_text(encoding="utf-8"))
    assert vals and all(isinstance(v, float) for v in vals.values())
    assert "2026-11-11" not in vals          # Veterans Day: empty in the real file, skipped not filled


def test_trend_labels_and_realised_vol():
    c = {f"2026-01-{i:02d}": 100.0 + i for i in range(1, 23)}
    assert macro.trend(c, 20, True) == round((122 / 102 - 1) * 100, 3)
    assert macro.dollar_label(1.5) == "dollar strengthening" and macro.dollar_label(-0.2) == "dollar range-bound"
    assert macro.yield_label(0.2) == "yields rising" and macro.yield_label(-0.2) == "yields falling" and macro.yield_label(None) is None
    assert macro.realised_vol([100.0] * 21, 20, 252) == 0.0
    assert macro.realised_vol([100.0] * 5, 20, 252) is None
    assert macro.percentile_of_last(list(range(40))) == 100.0


# ---------------------------------------------------------------- adverse flags (pure over a view payload)

P = {"source": "test-fixture", "kind": "eod", "as_of": 1.0}


def _view(idx=50.0, dollar="dollar range-bound", dxy_corr=-0.9, yields="yields flat", y_corr=-0.3, real=None, vol="normal", sym="EURUSD"):
    return {"symbol": sym, "market": "global",
            "cot": {"contract": "Euro FX (CME)", "report_date": "2026-11-10", "for_symbol": {"cot_index_3y": idx}, "prov": P},
            "macro": {"regime": {"dollar": dollar, "dxy_chg_20d_pct": 1.7, "yields": yields, "us10y_chg_20d_pts": 0.2,
                                 "real_yields": real, "real10y_chg_20d_pts": 0.2, "prov": P},
                      "us10y": {"prov": P}, "real10y": {"prov": P}},
            "drivers": {"correlation_60d": {"dxy": dxy_corr, "us10y_change": y_corr},
                        "volatility": {"regime": vol, "realised_pctl_1y": 95.0, "realised_20d_pct": 9.0, "implied": {"value": None}}, "prov": P},
            "prov": P}


def flags(side, **kw):
    return [f["flag"] for f in inst_global.adverse_flags(kw.get("sym", "EURUSD"), side, _view(**kw))]


def test_adverse_flags_cot_extremes_only_against_the_trade():
    assert flags("BUY", idx=95.0) == ["cot_extreme_against"]
    assert flags("SELL", idx=95.0) == []
    assert flags("SELL", idx=5.0) == ["cot_extreme_against"]
    assert flags("BUY", idx=5.0) == []
    assert flags("BUY", idx=None) == []


def test_adverse_flags_dollar_trend_uses_the_measured_correlation():
    assert flags("BUY", dollar="dollar strengthening", dxy_corr=-0.9) == ["dollar_trend_against"]
    assert flags("SELL", dollar="dollar strengthening", dxy_corr=-0.9) == []
    assert flags("SELL", dollar="dollar strengthening", dxy_corr=0.7) == ["dollar_trend_against"]   # USDJPY-like
    assert flags("BUY", dollar="dollar weakening", dxy_corr=0.7) == ["dollar_trend_against"]
    assert flags("BUY", dollar="dollar strengthening", dxy_corr=-0.1) == []                         # driver not relevant


def test_adverse_flags_yields_against_gold_long_and_vol_spike():
    assert flags("BUY", sym="XAUUSD", yields="yields rising", y_corr=0.0) == ["yields_against"]
    assert flags("SELL", sym="XAUUSD", yields="yields rising") == []
    assert flags("BUY", sym="XAUUSD", real="yields rising") == ["real_yields_against"]
    assert flags("BUY", vol="spike") == ["volatility_spike"]
    assert flags("HOLD", idx=99.0) == []
    every = inst_global.adverse_flags("EURUSD", "BUY", _view(idx=95.0, dollar="dollar strengthening", vol="spike"))
    assert all(set(f) == {"flag", "detail", "value", "prov"} for f in every)


def test_adverse_flags_empty_when_sources_unavailable():
    un = {"source": "x", "kind": "unavailable", "as_of": None}
    v = _view(idx=99.0, dollar="dollar strengthening", vol="spike")
    v["cot"]["prov"] = v["drivers"]["prov"] = v["macro"]["regime"]["prov"] = un
    assert inst_global.adverse_flags("EURUSD", "BUY", v) == []


def test_canonical_strips_broker_suffixes():
    assert inst_global.canonical("usdjpy.m") == "USDJPY"
    assert inst_global.canonical("XAUUSD") == "XAUUSD"
    assert inst_global.canonical("NIFTY") == "NIFTY"


# ---------------------------------------------------------------- route provenance (no network)

def test_global_route_carries_provenance_everywhere(monkeypatch):
    raw = json.loads((FX / "yahoo_dxy_eurusd_daily_6mo.json").read_text(encoding="utf-8"))

    def daily(t, rng="2y"):
        if t not in raw:
            return {"closes": {}, "prov": {"source": f"yahoo:chart/{t}", "kind": "unavailable", "as_of": None}}
        r = raw[t]
        c = {macro._day(ts, t.endswith("=X")): v for ts, v in zip(r["timestamp"], r["close"]) if v is not None}
        return {"closes": c, "prov": {"source": f"yahoo:chart/{t}", "kind": "close", "as_of": float(r["timestamp"][-1])}}
    monkeypatch.setattr(macro, "daily", daily)
    monkeypatch.setattr(macro, "fred", lambda s: {"closes": {}, "prov": {"source": "fred", "kind": "unavailable", "as_of": None}})
    monkeypatch.setattr(macro, "live", lambda n: {"value": None, "prov": {"source": "yahoo", "kind": "unavailable", "as_of": None}})
    monkeypatch.setattr(macro, "_cache", {})
    monkeypatch.setattr(cftc, "ensure_fresh", lambda: None)
    monkeypatch.setattr(cftc, "history", _hist)
    out = _HANDLERS["/api/markets/inst/global"]({"symbol": ["EURUSD"]})
    require_provenance(out)
    assert out["symbol"] == "EURUSD" and out["cot"]["prov"]["kind"] == "eod"
    assert out["drivers"]["correlation_60d"]["dxy"] < -0.7
    assert out["macro"]["dxy"]["prov"]["kind"] == "close" and out["macro"]["us10y"]["value"] is None
    assert out["label"].startswith("validated") or out["label"] == inst_global.NOT_VALIDATED
    assert set(out["validation"]) == {"cot_extremes", "dxy_trend_EURUSD"}


# ---------------------------------------------------------------- every-F&O-stock summary (inst.universe_rows)

def test_fno_universe_rows_from_real_bhavcopy():
    from jarvis.markets import inst
    b = inst.parse_fo_bhav((FX / "nse_fo_bhavcopy_20261117_trimmed.csv.zip").read_bytes())
    b["source"] = "nse:archive/fo/BhavCopy_NSE_FO@fixture"
    stocks = sorted({s for s, _ in b["rows"] if s not in inst.INDEX_UNDERLYINGS})
    groups = inst.bhav_futures(b, stocks)
    sym = groups[0]["underlying"]
    deliv = [{"symbol": sym, "deliv_pct": 61.2, "deliv_x": 1.4, "volume_x": 1.9, "accumulation": True}]
    ev = [{"symbol": sym, "purpose": "Financial Results", "date": "2026-11-25", "is_results": True},
          {"symbol": sym, "purpose": "Dividend", "date": "2026-11-20", "is_results": False}]
    rows = inst.universe_rows(groups, deliv, ev, [sym])
    assert [r["symbol"] for r in rows] == sorted(g["underlying"] for g in groups)
    r = next(r for r in rows if r["symbol"] == sym)
    g = groups[0]
    assert r["fut_close"] == g["near"]["ltp"] and r["basis"] == g["near"]["basis"] and r["rollover_pct"] == g["rollover_pct"]
    assert r["accumulation"] is True and r["next_results"] == "2026-11-25" and r["upcoming_events"] == 2 and r["in_ban"]
    other = next((x for x in rows if x["symbol"] != sym), None)
    if other:
        assert other["deliv_pct"] is None and other["next_results"] is None and not other["in_ban"]
    require_provenance({"rows": rows, "prov": g["prov"]})
