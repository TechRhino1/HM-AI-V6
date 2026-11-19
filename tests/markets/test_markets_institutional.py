"""Institutional data (jarvis/markets/inst.py): parsers on real recorded NSE payloads plus the
basis / rollover / build-up / participant-OI arithmetic."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from jarvis.markets import inst
from jarvis.markets.api import require_provenance
from jarvis.markets.data import feeds
from jarvis.markets.data.nse import IST

FX = Path(__file__).parent / "fixtures"


def _txt(name):
    return (FX / name).read_text(encoding="utf-8")


def _json(name):
    return json.loads(_txt(name))


# ---------------------------------------------------------------- participant OI

def test_participant_oi_parses_all_four_rows_exactly():
    rows = inst.parse_participant_oi(_txt("nse_participant_oi_17112026.csv"))
    assert set(rows) == {"Client", "DII", "FII", "Pro"}
    raw = next(l for l in _txt("nse_participant_oi_17112026.csv").splitlines() if l.startswith("FII,")).split(",")
    assert rows["FII"]["fut_idx_long"] == int(raw[1]) and rows["FII"]["fut_idx_short"] == int(raw[2])
    assert rows["FII"]["total_short"] == int(raw[14])
    # long and short across the four participants must balance (every contract has two sides)
    for side in ("fut_idx", "opt_idx_call", "opt_idx_put"):
        assert sum(r[f"{side}_long"] for r in rows.values()) == sum(r[f"{side}_short"] for r in rows.values())


def test_participant_oi_parses_old_2018_layout():
    rows = inst.parse_participant_oi(_txt("nse_participant_oi_15112018.csv"))
    assert rows["Client"]["fut_idx_long"] == 160413


def test_participant_derived_metrics_and_day_change():
    cur = inst.parse_participant_oi(_txt("nse_participant_oi_17112026.csv"))["FII"]
    prev = inst.parse_participant_oi(_txt("nse_participant_oi_16112026.csv"))["FII"]
    d = inst.derive(cur, prev)
    assert d["net_idx_fut"] == cur["fut_idx_long"] - cur["fut_idx_short"]
    assert d["fut_idx_long_pct"] == round(cur["fut_idx_long"] / (cur["fut_idx_long"] + cur["fut_idx_short"]) * 100, 2)
    assert d["idx_call_net"] == cur["opt_idx_call_long"] - cur["opt_idx_call_short"]
    assert d["idx_put_net"] == cur["opt_idx_put_long"] - cur["opt_idx_put_short"]
    assert d["net_idx_fut_chg"] == d["net_idx_fut"] - (prev["fut_idx_long"] - prev["fut_idx_short"])
    p = inst.derive(prev)
    assert d["fut_idx_long_pct_chg"] == round(d["fut_idx_long_pct"] - p["fut_idx_long_pct"], 2)


def test_participant_oi_rejects_unexpected_layout():
    with pytest.raises(inst.SourceError):
        inst.parse_participant_oi("Client Type,Future Index Long\nClient,1\n")


# ---------------------------------------------------------------- futures

def test_basis_annualised_and_buildup():
    now = datetime(2026, 11, 18, 15, 30, tzinfo=IST)
    m = inst.contract_metrics(25200.0, 25100.0, "23-Nov-2026", 50.0, 1100, 1000, now)
    assert m["basis"] == 100.0 and m["days_to_expiry"] == 5.0
    assert m["basis_pct"] == round(100 / 25100 * 100, 3)
    assert m["basis_ann_pct"] == round(100 / 25100 * 100 * 365 / 5, 2)
    assert m["oi_change"] == 100 and m["buildup"] == "long_buildup"
    assert inst.contract_metrics(25200.0, 25100.0, "23-Nov-2026", -5.0, 900, 1000, now)["buildup"] == "long_unwinding"
    assert inst.contract_metrics(25200.0, 25100.0, "23-Nov-2026", -5.0, 900, None, now)["buildup"] is None  # unknown, not guessed


def test_rollover_is_share_of_oi_beyond_near_month():
    assert inst.rollover([{"oi": 600}, {"oi": 300}, {"oi": 100}]) == 40.0
    assert inst.rollover([{"oi": 600}]) is None


def test_fo_bhavcopy_parses_futures_in_contracts():
    b = inst.parse_fo_bhav((FX / "nse_fo_bhavcopy_20261117_trimmed.csv.zip").read_bytes())
    assert b["date"] == "2026-11-17"
    near = b["rows"][("NIFTY", "2026-11-23")]
    assert near["oi"] == round(11393265 / 65) and near["lot"] == 65 and near["close"] == 25415.30
    assert ("RELIANCE", "2026-12-29") in b["rows"]
    assert all(k[0] in ("NIFTY", "RELIANCE") for k in b["rows"])  # options rows are excluded


def test_live_futures_join_previous_bhavcopy_for_oi_change():
    data = _json("nse_live_futures_nifty.json")
    bhav = inst.parse_fo_bhav((FX / "nse_fo_bhavcopy_20261117_trimmed.csv.zip").read_bytes())
    [g] = inst.parse_live_futures(data, bhav, True, "https://www.nseindia.in", now=datetime(2026, 11, 18, 12, 0, tzinfo=IST))
    raw = sorted(data["data"], key=lambda r: datetime.strptime(r["expiryDate"], "%d-%b-%Y"))
    assert g["underlying"] == "NIFTY" and g["near"]["expiry"] == raw[0]["expiryDate"]
    assert g["near"]["ltp"] == raw[0]["lastPrice"] and g["spot"] == raw[0]["underlyingValue"]
    assert g["near"]["oi_change"] == raw[0]["openInterest"] - bhav["rows"][("NIFTY", "2026-11-23")]["oi"]
    assert g["near"]["basis"] == round(raw[0]["lastPrice"] - raw[0]["underlyingValue"], 2)
    total = sum(r["openInterest"] for r in raw)
    assert g["rollover_pct"] == round((total - raw[0]["openInterest"]) / total * 100, 2)
    assert "bhavcopy of 2026-11-17" in g["prov"]["note"]
    require_provenance({"rows": [g]})


def test_bhav_futures_are_labelled_eod():
    bhav = inst.parse_fo_bhav((FX / "nse_fo_bhavcopy_20261117_trimmed.csv.zip").read_bytes())
    bhav["source"] = "nse:archive/fo/BhavCopy_NSE_FO@test"
    [g] = inst.bhav_futures(bhav, ["RELIANCE"])
    assert g["prov"]["kind"] == "eod" and g["near"]["expiry"] == "23-Nov-2026"
    assert g["near"]["oi_change"] == bhav["rows"][("RELIANCE", "2026-11-23")]["oi_change"]


# ---------------------------------------------------------------- deals, events, announcements

def test_deals_parse_numbers_from_strings():
    d = inst.parse_deals(_json("nse_largedeal.json"))
    raw = _json("nse_largedeal.json")["BULK_DEALS_DATA"][0]
    assert d["bulk"][0]["qty"] == int(raw["qty"]) and d["bulk"][0]["price"] == float(raw["watp"])
    assert d["bulk"][0]["side"] == raw["buySell"]


def test_events_parse_and_flag_results():
    ev = inst.parse_events(_json("nse_event_calendar.json"))
    assert ev and all(len(e["date"]) == 10 for e in ev)
    assert [e["date"] for e in ev] == sorted(e["date"] for e in ev)
    assert any(e["is_results"] for e in ev) == any("result" in (r["purpose"] or "").lower() for r in _json("nse_event_calendar.json"))


def test_announcements_keep_exchange_attachment_and_time():
    items = inst.parse_announcements(_json("nse_announcements.json"))
    raw = _json("nse_announcements.json")
    assert {i["attachment"] for i in items} == {r["attchmntFile"] for r in raw}
    assert all(i["published"].endswith("+05:30") for i in items)
    assert [i["published"] for i in items] == sorted((i["published"] for i in items), reverse=True)


# ---------------------------------------------------------------- delivery

def test_delivery_parse_keeps_only_eq_with_delivery():
    rows = inst.parse_delivery(_txt("nse_sec_bhavdata_17112026_trimmed.csv"))
    assert rows and all(r["date"] == "2026-11-17" for r in rows)
    assert "21STCENMGM" not in {r["symbol"] for r in rows}  # BE series, delivery '-'
    r = next(r for r in rows if r["symbol"] == "360ONE")
    assert r["deliv_pct"] == 51.19 and r["volume"] == 1429280 and r["deliv_qty"] == 731701


def test_delivery_screen_needs_both_volume_and_delivery_elevated():
    def series(sym, vol_today, pct_today, n=20):
        rows = [{"symbol": sym, "date": f"2026-10-{i + 1:02d}", "volume": 100.0, "deliv_pct": 40.0} for i in range(n)]
        return rows + [{"symbol": sym, "date": "2026-11-17", "volume": vol_today, "deliv_pct": pct_today}]
    hist = {s: series(s, *a) for s, a in {"A": (200, 60), "B": (200, 41), "C": (110, 70), "D": (200, 60, 5)}.items()}
    out = inst.delivery_screen(hist, "2026-11-17")
    assert [(r["symbol"], r["volume_x"], r["deliv_x"]) for r in out] == [("A", 2.0, 1.5)]  # D lacks history
    assert inst.delivery_screen(hist, "2026-11-17", min_pct=65) == []
    flagged = inst.delivery_screen(hist, "2026-11-17", symbols=["B"])
    assert len(flagged) == 1 and flagged[0]["accumulation"] is False


# ---------------------------------------------------------------- ban, holidays

def test_ban_list_parses_symbols_and_nil():
    b = inst.parse_ban(_txt("nse_fo_secban_18112026.csv"))
    assert b == {"trade_date": "2026-11-18", "symbols": ["KAYNES"]}
    assert inst.parse_ban(_txt("nse_fo_secban_17112026_nil.csv")) == {"trade_date": "2026-11-17", "symbols": []}


def test_us_holiday_calendar_parse():
    h = feeds.parse_us_holidays(_txt("nasdaqtrader_calendar_snippet.html"))
    assert h["closed"]["2026-11-26"].startswith("Thanksgiving")
    assert "2026-11-27" in h["early"] and "2026-11-27" not in h["closed"]


def test_us_session_respects_holiday(monkeypatch):
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(feeds, "us_holidays", lambda: {"closed": {datetime.now(ZoneInfo("America/New_York")).date().isoformat(): "Test"}, "early": {}})
    s = feeds.session("US")
    assert s["open"] is False and "holiday" in s["source"]


def test_india_fallback_session_uses_holiday_master(monkeypatch):
    from jarvis.markets.data import nse
    today = datetime.now(IST).date().isoformat()

    def boom():
        raise nse.SourceError("down")
    monkeypatch.setattr(nse, "market_status", boom)
    monkeypatch.setattr(nse, "trading_holidays", lambda: {"days": {today: "Test holiday"}, "source": "x"})
    s = feeds.session("IN")
    assert s["open"] is False and "holiday master" in s["source"]


def test_holiday_master_fixture_dates_are_iso_parsable():
    rows = _json("nse_holiday_master.json")["CM"]
    assert all(datetime.strptime(r["tradingDate"], "%d-%b-%Y") for r in rows)
