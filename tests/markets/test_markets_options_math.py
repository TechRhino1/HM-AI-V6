"""Options maths against known identities, so the adviser's numbers can be trusted."""
import json
import math
from pathlib import Path

import pytest

from jarvis.markets.data import nse
from jarvis.markets.options import chain_analytics as ca
from jarvis.markets.options import strategies
from jarvis.markets.options.pricing import black76, greeks, implied_vol, prob_above


def test_put_call_parity_on_the_forward():
    for k in (90.0, 100.0, 115.0):
        c, p = black76(100, k, 0.25, 0.2, True), black76(100, k, 0.25, 0.2, False)
        assert c - p == pytest.approx(100 - k, abs=1e-9)


def test_implied_vol_round_trips():
    for vol in (0.08, 0.15, 0.4):
        price = black76(25000, 25300, 7 / 365, vol, True)
        assert implied_vol(price, 25000, 25300, 7 / 365, True) == pytest.approx(vol, abs=1e-4)
    assert implied_vol(0.5, 100, 90, 0.1, True) is None  # below intrinsic: no valid IV


def test_greeks_signs_and_atm_delta():
    g = greeks(100, 100, 0.1, 0.2, True)
    assert 0.5 < g["delta"] < 0.53 and g["gamma"] > 0 and g["theta"] < 0 and g["vega"] > 0
    assert greeks(100, 100, 0.1, 0.2, False)["delta"] == pytest.approx(g["delta"] - 1)


def test_probability_is_lognormal():
    assert prob_above(100, 100 * math.exp(-0.5 * 0.2 ** 2 * 1) , 1, 0.2) == pytest.approx(0.5, abs=1e-9)
    assert prob_above(100, 1e9, 1, 0.2) < 1e-6


@pytest.mark.parametrize("price,oi,label", [(1, 5, "long_buildup"), (-1, 5, "short_buildup"),
                                            (1, -5, "short_covering"), (-1, -5, "long_unwinding"), (1, 0, "neutral")])
def test_oi_buildup_table(price, oi, label):
    assert ca.buildup(price, oi) == label


def _fixture_analysis():
    fx = json.loads((Path(__file__).parent / "fixtures" / "nse_nifty_chain.json").read_text(encoding="utf-8"))
    chain = nse.parse_chain("NIFTY", fx["contract_info"], fx["v3"], fx["contract_info"]["expiryDates"][0], "h://x", True)
    return chain, ca.analyse(chain)


def test_max_pain_minimises_writer_payout():
    chain, _ = _fixture_analysis()
    mp = ca.max_pain(chain)
    pay = lambda s: sum(max(0, s - r.strike) * (r.call.oi if r.call else 0) + max(0, r.strike - s) * (r.put.oi if r.put else 0) for r in chain.rows)
    assert all(pay(mp) <= pay(r.strike) for r in chain.rows)


def test_no_edge_when_the_view_equals_the_market():
    """With forecast vol == implied vol, every strategy's expected value is exactly minus its costs:
    skew or pricing conventions must never show up as an edge."""
    _, an = _fixture_analysis()
    rows = {r["strike"]: r for r in an["strikes"]}
    vol = 0.15
    for k, row in rows.items():
        for kind in ("CE", "PE"):
            lg = strategies.leg(row, kind, "BUY")
            if not lg or not lg.get("iv"):
                continue
            r = strategies.evaluate([lg], an["forward"], an["years_to_expiry"], vol, vol, 65)
            assert r["edge_per_lot"] == pytest.approx(-r["cost_per_lot"], abs=1.0)
