"""Phase-0 #8: the intraday direction resolver must be mirror-symmetric when the HTF bias and
the D1 anchor disagree (it used to send BOTH conflicts into the bullish CASE A)."""
from datetime import datetime, timezone

from jarvis.data.schemas import (MarketContext, StructureContext, MomentumContext, VolatilityContext,
                                 LiquidityContext, SessionContext, RegimeOutput, MarketRegime)
from jarvis.intelligence.decision_engine import DecisionEngine


def _ctx(htf, d1, primary, trend):
    st = StructureContext(bias=primary, bos=False, choch=False,
                          demand_zone=(1975.0, 1980.0), supply_zone=(2020.0, 2025.0),
                          discount_premium_zone="EQUILIBRIUM")
    mom = MomentumContext(trend_score=trend, rsi=50.0, adx=25.0, plus_di=20.0, minus_di=20.0)
    return MarketContext(
        symbol="EURUSD", timestamp=datetime.now(timezone.utc), current_price=2000.0, bid=1999.9, ask=2000.1,
        structure=st, momentum=mom, volatility=VolatilityContext(atr=5.0),
        liquidity=LiquidityContext(sweep_detected=False),
        session=SessionContext(current_session="LONDON", is_prime_session=True),
        mtf_alignment={"D1": d1, "H1": htf, "M15": primary, "M5": primary}, mtf_confluence_score=0.0)


def test_intraday_htf_vs_d1_conflict_is_mirror_symmetric():
    eng = DecisionEngine()
    reg = RegimeOutput(primary_regime=MarketRegime.TRANSITION, probabilities={"TRANSITION": 0.6}, confidence=0.6)
    sell = eng.resolve_direction(_ctx("BEARISH", "BULLISH", "BEARISH", -30.0), reg, trade_style="SCALP")
    buy = eng.resolve_direction(_ctx("BULLISH", "BEARISH", "BULLISH", 30.0), reg, trade_style="SCALP")
    mirror = {"BUY": "SELL", "SELL": "BUY", "HOLD": "HOLD"}
    assert sell == mirror[buy], (buy, sell)
    assert buy == "BUY"                               # H1 bullish + primary bullish -> BUY
