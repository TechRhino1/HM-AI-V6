"""Chart intelligence (jarvis/markets/levels.py) on recorded real bars: pivots, zone merge, volume profile,
walk-forward hold-rate bookkeeping, pattern detectors without look-ahead, the engine signal overlay and the
AI chart read's template fallback / grounding check."""
import copy
import json
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from jarvis.markets import levels as L
from jarvis.markets.api import _HANDLERS, require_provenance

FX = Path(__file__).parent / "fixtures"
YB = json.loads((FX / "yahoo_bars_levels.json").read_text(encoding="utf-8"))
REL = YB["RELIANCE|1d"]["bars"]
AAPL = YB["AAPL|15m"]["bars"]
XAU = json.loads((FX / "mt5_xauusd_h1.json").read_text(encoding="utf-8"))["candles"][:-1]   # last bar was forming
SNAP = json.loads((FX / "telemetry_snapshot_eurusd.json").read_text(encoding="utf-8"))
IST = ZoneInfo("Asia/Kolkata")


def bar(t, o, h, l, c, v=0.0):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v}


@pytest.fixture(autouse=True)
def _clear_cache():
    L._cache.clear()
    yield
    L._cache.clear()


@pytest.fixture
def fixture_bars(monkeypatch):
    src = {("RELIANCE", "IN"): (REL, "yahoo:chart/RELIANCE.NS", "exchange volume"),
           ("AAPL", "US"): (AAPL, "yahoo:chart/AAPL", "exchange volume"),
           ("XAUUSD", "FX"): (XAU, "mt5:copy_rates_from_pos", "tick volume (broker)")}

    def get(symbol, market, interval):
        b, s, vk = src[(symbol, market)]
        return {"bars": b, "prov": {"source": s, "kind": "close", "as_of": b[-1]["time"], "note": "fixture"}, "volume_kind": vk}
    monkeypatch.setattr(L, "get_bars", get)
    monkeypatch.setattr(L, "_oi_levels", lambda s: ([], None))


# ---------------------------------------------------------------- primitives

def test_atr_uses_only_past_bars():
    atr = L.atr_series(REL)
    assert len(atr) == len(REL)
    assert L.atr_series(REL[:200]) == atr[:200]
    tr = [max(x["high"] - x["low"], abs(x["high"] - p["close"]), abs(x["low"] - p["close"])) for p, x in zip(REL[99:113], REL[100:114])]
    assert atr[113] == pytest.approx(sum(tr) / 14)


def test_pivots_are_fractals_and_confirmed_two_bars_later():
    piv = L.pivots(REL)
    assert piv
    for p in piv:
        i, k = p["i"], L.FRACTAL
        assert p["known"] == i + k
        side = "high" if p["kind"] == "swing_high" else "low"
        sign = 1 if side == "high" else -1
        assert all(sign * REL[i][side] > sign * REL[j][side] for j in range(i - k, i))
        assert all(sign * REL[i][side] >= sign * REL[j][side] for j in range(i + 1, i + k + 1))
    # no look-ahead: pivots found on a prefix are exactly the full set's pivots confirmed inside it
    m = 300
    assert L.pivots(REL[:m]) == [p for p in piv if p["known"] < m]


def test_zone_merge_is_width_capped():
    c = [{"price": p, "type": t, "label": t} for p, t in [(100.0, "swing"), (100.4, "prev_day"), (100.8, "swing"), (103.0, "floor_pivot")]]
    z = L.merge_zones(c, atr_now=1.0)
    assert [(round(x["lo"], 2), round(x["hi"], 2)) for x in z] == [(100.0, 100.4), (100.8, 100.8), (103.0, 103.0)]
    assert z[0]["types"] == ["prev_day", "swing"] and z[0]["confluence"] == 2
    dup = L.merge_zones([{"price": 1.0, "type": "swing", "label": "swing high"}] * 3, 1.0)
    assert dup[0]["sources"] == ["swing high x3"]


def test_volume_profile_math():
    # bar 1 spans bins 0-1 (5 each), bar 2 sits in bin 3 (30): POC = bin 3
    b = [bar(0, 0, 1.9, 0, 1, 10), bar(1, 3, 4, 3.5, 3.6, 30)]
    vp = L.volume_profile(b, bins=4, area=0.7)
    assert vp["poc"] == pytest.approx(3.5) and vp["total"] == 40
    assert vp["vols"] == pytest.approx([5, 5, 0, 30])
    assert vp["vah"] == pytest.approx(4.0) and vp["val"] == pytest.approx(3.0)
    real = L.volume_profile(REL[-200:])
    assert real["val"] <= real["poc"] <= real["vah"]
    lo_i = round((real["val"] - real["lo"]) / real["bin_size"])
    hi_i = round((real["vah"] - real["lo"]) / real["bin_size"])
    assert sum(real["vols"][lo_i:hi_i]) >= 0.7 * real["total"] - 1e-6
    assert L.volume_profile([bar(0, 1, 2, 1, 1.5, 0)]) is None      # no volume -> no profile


def test_volume_detection_and_previous_period():
    assert L.has_volume(REL)
    assert not L.has_volume([bar(i, 1, 2, 0.5, 1.5, 0) for i in range(20)])
    ps = L.periods(AAPL, ZoneInfo("America/New_York"), "day")
    last_day_ts = AAPL[ps[-1]["first"]]["time"]
    prev = L.previous_period(AAPL, ZoneInfo("America/New_York"), "day", now=last_day_ts + 60)
    assert prev["key"] == ps[-2]["key"]
    seg = AAPL[ps[-2]["first"]:ps[-1]["first"]]
    assert prev["high"] == max(x["high"] for x in seg) and prev["low"] == min(x["low"] for x in seg) and prev["close"] == seg[-1]["close"]
    assert L.previous_period(AAPL, ZoneInfo("America/New_York"), "day", now=last_day_ts + 5 * 86400)["key"] == ps[-1]["key"]
    fp = L.floor_pivots(110, 90, 100)
    assert fp == {"P": 100, "R1": 110, "S1": 90, "R2": 120, "S2": 80}


# ---------------------------------------------------------------- hold-rate bookkeeping

def test_touch_outcome_definitions():
    flat = [bar(i, 100, 101, 99, 100) for i in range(14)]          # ATR 2
    hold = flat + [bar(14, 103, 104, 102.5, 103), bar(15, 102, 102.5, 100.1, 101), bar(16, 101, 103.5, 100.5, 103)]
    atr = L.atr_series(hold)
    assert L.touch_outcome(hold, atr, 100.0, 15) == "hold"         # touched 100.1, reached 102 before a close below
    brk = flat + [bar(14, 103, 104, 102.5, 103), bar(15, 102, 102.5, 99.5, 99.8)]
    assert L.touch_outcome(brk, L.atr_series(brk), 100.0, 15) == "break"
    assert L.touch_outcome(hold, atr, 50.0, 15) is None             # never touched


def test_hold_rate_has_no_look_ahead():
    atr = L.atr_series(REL)
    inst = L.level_instances(REL, IST, True)
    assert inst["swing"] == [(p["price"], p["known"] + 1) for p in L.pivots(REL)]   # usable only after confirmation
    # an outcome resolved inside a prefix is unchanged by the bars after it, and bars after resolution never matter
    for px, start in inst["swing"][:60]:
        full = L.touch_outcome(REL, atr, px, start)
        if full is None:
            continue
        for m in range(start + 1, len(REL)):
            if L.touch_outcome(REL[:m], atr[:m], px, start) == full:
                break
        cut = copy.deepcopy(REL)
        for x in cut[m:]:
            x.update(high=x["high"] * 3, low=x["low"] / 3)
        assert L.touch_outcome(cut, L.atr_series(cut), px, start) == full
    beh = L.behaviour(REL, atr, IST, True)
    for typ, s in beh.items():
        assert s["n"] == s["holds"] + s["breaks"] <= s["instances"]
        assert (s["hold_rate"] is None) == (s["n"] < L.MIN_N)
        if s["hold_rate"] is not None:
            assert s["hold_rate"] == round(s["holds"] / s["n"], 3)


def test_levels_payload_on_real_bars(fixture_bars):
    out = L.levels("RELIANCE", "IN", "D1")
    require_provenance(out)
    z = out["zones"]
    assert z and out["volume"]["used"] and out["volume"]["kind"] == "exchange volume"
    assert [x["price"] for x in z] == sorted(x["price"] for x in z)
    last = out["last_close"]
    assert all((x["role"] == "resistance") == (x["price"] > last) for x in z)
    for x in z:
        assert x["sources"] and x["strength"] >= 0 and x["hi"] - x["lo"] <= L.MERGE_ATR * out["atr"] + 1e-9
        assert (x["hold_rate"] is None) or x["n"] >= L.MIN_N
    vp = out["volume_profile"]
    assert vp["val"] <= vp["poc"] <= vp["vah"]


def test_levels_without_volume_skip_profile(fixture_bars, monkeypatch):
    nov = [dict(x, volume=0.0) for x in REL]
    monkeypatch.setattr(L, "get_bars", lambda s, m, i: {"bars": nov, "prov": {"source": "yahoo", "kind": "close", "as_of": 1}, "volume_kind": "exchange volume"})
    out = L.levels("NIFTY", "IN", "D1")
    assert not out["volume"]["used"] and "skipped" in out["volume"]["note"]
    assert "volume_profile" not in out and "volume_profile" not in out["behaviour"] or out["behaviour"]["volume_profile"]["n"] == 0
    assert all("volume_profile" not in x["types"] for x in out["zones"])


def test_oi_walls_are_context_not_validated():
    wall = round(REL[-1]["close"] * 1.2)
    out = L.zones_for(REL, IST, False, True, [{"price": wall, "type": "oi_wall", "label": "call OI wall"}], per_side=500)
    far = [x for x in out["zones"] if x["types"] == ["oi_wall"]]
    assert far and far[0]["hold_rate"] is None and far[0]["label"] == L.NOT_VALIDATED and far[0]["role"] == "resistance"


# ---------------------------------------------------------------- patterns

def test_patterns_have_no_look_ahead_and_prior_only_stats():
    atr = L.atr_series(AAPL)
    ev = L.detect_patterns(AAPL, atr)
    kinds = {e["kind"] for e in ev}
    assert {"bos", "choch", "breakout"} <= kinds
    m = 1000
    pre = L.detect_patterns(AAPL[:m], atr[:m])
    assert pre == [e for e in ev if e["i"] < m]
    L.pattern_stats(AAPL, atr, ev)
    for e in ev:
        prior = [p for p in ev if p["kind"] == e["kind"] and p["i"] + L.HORIZON <= e["i"]]
        assert e["stats"]["n"] == len(prior)
        if e["stats"]["n"] < L.MIN_N:
            assert e["stats"]["win_rate"] is None and "insufficient history" in e["stats"]["label"]
        else:
            assert e["stats"]["win_rate"] == round(sum(1 for p in prior if p["fwd_atr"] > 0) / len(prior), 3)


def test_pattern_detectors_on_shaped_sequence():
    b = [bar(i, 100, 101, 99, 100) for i in range(14)]
    b += [bar(14, 100, 103, 100, 102), bar(15, 102, 102.5, 101, 101.5), bar(16, 101.5, 102, 100.5, 101),   # swing high 103 (i=14)
          bar(17, 101, 101.5, 100, 100.5), bar(18, 100.5, 103, 100, 101), bar(19, 101, 101.5, 100, 100.5),  # equal high 103 (i=18)
          bar(20, 100.5, 101, 99.8, 100.2), bar(21, 100.2, 103.4, 100, 101)]                                  # wick through 103, close back
    ev = L.detect_patterns(b, L.atr_series(b))
    sweep = [e for e in ev if e["kind"] == "liquidity_sweep"]
    assert sweep and sweep[0]["direction"] == "down" and sweep[0]["level"] == 103
    b2 = b + [bar(22, 101, 107, 101, 106.5), bar(23, 106.5, 106.6, 102, 102.5)]                           # wide breakout, then back below
    ev2 = L.detect_patterns(b2, L.atr_series(b2))
    kinds = [(e["kind"], e["direction"]) for e in ev2 if e["i"] >= 22]
    assert ("breakout", "up") in kinds and ("false_breakout", "down") in kinds
    assert any(k in (("bos", "up"), ("choch", "up")) for k in kinds)


def test_patterns_route(fixture_bars):
    out = _HANDLERS["/api/markets/chart/patterns"]({"symbol": ["AAPL"], "market": ["US"], "interval": ["M15"]})
    require_provenance(out)
    assert out["events"] and all("i" not in e and "stats" in e for e in out["events"])
    assert set(out["summary"]) <= {"bos", "choch", "breakout", "false_breakout", "liquidity_sweep"}


# ---------------------------------------------------------------- signal overlay

def test_signal_overlay_without_devil_calibration():
    out = L.signal_overlay("EURUSD", snap=SNAP, adverse=lambda s, side: [{"flag": "x", "detail": "d", "value": 1, "prov": {}}])
    e = out["engine"]
    d = SNAP["latest_decisions"]["EURUSD"]
    assert e["decision"] == d["decision"] and e["side"] == d["bias"] and e["entry"] == d["entry_price"]
    assert e["failing"] == d["quality_gate"]["failing_reasons"]
    assert e["gate_chips"] == [f"Blocked by: {g}" for g, ok in d["quality_gate"]["checks"].items() if ok is False]
    assert e["devil"]["penalty"] == d["adversarial_penalty"] and e["devil"]["calibrated_loss_prob"] is None and e["devil"]["threat_stats"] == []
    assert e["devil"]["threats"] and e["regime"] == d["regime"]["primary"] and e["mtf"]
    assert out["adverse_flags"][0]["flag"] == "x"
    pos = out["positions"][0]
    p = SNAP["positions"][0]
    assert pos["side"] == "SELL" and pos["live_r"] == round((p["open_price"] - p["current_price"]) / (p["sl"] - p["open_price"]), 2)
    require_provenance(out)


def test_signal_overlay_with_devil_calibration_and_penalty_block():
    snap = copy.deepcopy(SNAP)
    d = snap["latest_decisions"]["EURUSD"]
    d["quality_gate"]["checks"]["Devil Adversarial Guard"] = False
    d["rejection_reasons"].append("Adversarial counter-thesis penalty too high (48.0 / 43.0).")
    out = L.signal_overlay("EURUSD", snap=snap, adverse=lambda s, side: [])
    assert "Blocked by: Devil Adversarial Guard (penalty 48 > 43)" in out["engine"]["gate_chips"]
    d["calibrated_loss_prob"] = 0.612
    d["threat_stats"] = [{"flag": "htf_conflict", "n": 412, "win_rate_delta": -0.08, "mean_r_delta": -0.21, "t_stat": -2.4}]
    out = L.signal_overlay("EURUSD", snap=snap, adverse=lambda s, side: [])
    dv = out["engine"]["devil"]
    assert dv["calibrated_loss_prob"] == 0.612 and dv["threat_stats"][0]["flag"] == "htf_conflict"
    assert "Blocked by: Devil Adversarial Guard (calibrated loss prob 61%)" in out["engine"]["gate_chips"]


def test_signal_overlay_unknown_symbol():
    out = L.signal_overlay("NIFTY", snap=SNAP)
    assert out["engine"] is None and out["positions"] == [] and out["prov"]["kind"] == "unavailable"


# ---------------------------------------------------------------- AI chart read

class _Res:
    def __init__(self, text):
        self.text, self.stop_reason = text, "end_turn"


class _Prov:
    name = "stub"

    def __init__(self, text=None, exc=None):
        self.text, self.exc = text, exc

    def user(self, t):
        return t

    def chat(self, msgs, tools, system, effort="medium"):
        if self.exc:
            raise self.exc
        return _Res(self.text)


_ORIG_OVERLAY = L.signal_overlay


@pytest.fixture
def read_env(fixture_bars, monkeypatch):
    monkeypatch.setattr(L, "signal_overlay", lambda s: _ORIG_OVERLAY(s, snap=SNAP, adverse=lambda a, b: []))


def test_chart_read_falls_back_to_template(read_env):
    from jarvis.ai.providers.base import ProviderBusy
    for p, word in ((None, "no AI provider"), (_Prov(exc=ProviderBusy("busy")), "busy or failed")):
        L._cache.clear()
        out = L.chart_read("XAUUSD", "FX", "H1", provider=p)
        assert out["source"] == "template" and word in out["note"] and len(out["bullets"]) == 5
        require_provenance(out)
    assert any("Resistance:" in b for b in out["bullets"])


def test_chart_read_rejects_invented_numbers_and_accepts_grounded(read_env):
    out = L.chart_read("XAUUSD", "FX", "H1", provider=_Prov("- price will hit 9999.5\n- a\n- b\n- c\n- d"))
    assert out["source"] == "template" and "not in the facts" in out["note"]
    f = out["facts"]
    good = "\n".join(f"- {t}" for t in [f"Last {f['last_price']}", f"ATR {f['atr']}", "Engine waits", "Risks noted", "Watch the levels"])
    out = L.chart_read("XAUUSD", "FX", "H1", provider=_Prov(good))
    assert out["source"] == "stub" and out["bullets"][0] == f"Last {f['last_price']}"


def test_grounded_number_matching():
    facts = {"a": 1.234567, "b": 62.5, "c": [4123.13]}
    assert L.grounded("held 62.5% near 1.2346 and 4,123.1 on H4 in 3 tests", facts)
    assert not L.grounded("target 4200", facts)
