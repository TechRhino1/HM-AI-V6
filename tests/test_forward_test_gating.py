"""Forward tests pass the same hard risk gates as the main engine (plan Phase 4).

2026-11-25: four EURUSD shorts stacked because forward tests sent orders directly,
skipping the risk engine, the per-symbol cap, and (for two of them) the news gate.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jarvis.data.schemas import AccountSnapshot, PositionSnapshot
from jarvis.forward_tests.research_leads import gated_forward_entry
from jarvis.observability import decision_journal as dj
from jarvis.risk.risk_engine import RiskEngine
from jarvis.risk import trade_guard as tg

ACCOUNT = AccountSnapshot(login=1, server="demo", balance=10_000.0, equity=10_000.0, margin=0.0,
                          free_margin=10_000.0, margin_level=0.0, leverage=100)


def _ft_pos(ticket, tag):
    return PositionSnapshot(ticket=ticket, symbol="EURUSD#", type="SELL", volume=0.01, open_price=1.0947,
                            current_price=1.0947, sl=1.1015, tp=0.0, profit=0.0, swap=0.0, commission=0.0,
                            open_time="2026-11-25 14:23:00", magic=888999, comment=tag)


def _orch(positions):
    o = SimpleNamespace(mode="demo", risk_engine=RiskEngine(is_backtest=True), mt5_client=MagicMock(),
                        state_manager=SimpleNamespace(is_safe_mode=False), execution_engine=MagicMock())
    o.mt5_client.get_account_snapshot.return_value = ACCOUNT
    o.mt5_client.get_open_positions.return_value = list(positions)
    o.mt5_client.get_symbol_trading_spec.return_value = {"volume_min": 0.01, "volume_step": 0.01,
                                                         "trade_contract_size": 100000.0, "point": 0.00001,
                                                         "trade_tick_value": 1.0, "trade_tick_size": 0.00001}
    o.mt5_client.send_market_order.return_value = {"status": "FILLED", "ticket": 99, "position_id": 99, "price": 1.0947}
    o.execution_engine._pre_send_verify.return_value = None
    return o


def test_third_stacked_forward_test_entry_is_refused_and_journaled():
    o = _orch([_ft_pos(1, "FT_TR_EURUSD_H4_T1"), _ft_pos(2, "FT_TR_EURUSD_H4_T3")])
    dj._LAST.clear()
    with patch.object(dj, "record_dispatch") as rec:
        res = gated_forward_entry(o, "EURUSD", "SELL", 0.01, stop=1.1015, tp=0.0, ref=1.0947,
                                  comment="FT_ESW_EURUSD", style="SWING", strategy="ESW")
    assert res["status"] == "BLOCKED" and "HARD_SYMBOL_LIMIT" in res["reason"]
    o.mt5_client.send_market_order.assert_not_called()
    row = rec.call_args[0][0]
    assert row["origin"] == "forward_test:FT_ESW_EURUSD" and row["blocked_by"] == "HARD_SYMBOL_LIMIT"


def test_clean_forward_test_entry_still_sends_its_own_order():
    o = _orch([])
    tg._RECENT_SENDS.clear()
    with patch.object(dj, "record_dispatch"):
        res = gated_forward_entry(o, "EURUSD", "SELL", 0.01, stop=1.1015, tp=0.0, ref=1.0947,
                                  comment="FT_ESW_EURUSD", style="SWING", strategy="ESW")
    assert res["status"] == "FILLED"
    kwargs = o.mt5_client.send_market_order.call_args.kwargs
    assert kwargs["comment"] == "FT_ESW_EURUSD" and kwargs["tp_price"] == 0.0  # geometry untouched
    o.execution_engine._pre_send_verify.assert_called_once()
    assert tg._RECENT_SENDS  # recorded for the duplicate rule


def test_verifier_block_stops_a_forward_test_entry():
    o = _orch([])
    o.execution_engine._pre_send_verify.return_value = {"status": "BLOCKED", "reason": "VERIFIER_BLOCKED_RISK: x"}
    with patch.object(dj, "record_dispatch"):
        res = gated_forward_entry(o, "EURUSD", "BUY", 0.01, stop=1.0900, tp=0.0, ref=1.0947,
                                  comment="FT_TR_EURUSD_H4_T1")
    assert res["status"] == "BLOCKED"
    o.mt5_client.send_market_order.assert_not_called()


def test_drawdown_halt_blocks_forward_tests_too():
    o = _orch([])
    with patch.object(o.risk_engine.drawdown_guard, "check_limits",
                      return_value={"passed": False, "breaches": ["Max Weekly Loss breached (10.49% >= 10.00%)."]}), \
         patch.object(dj, "record_dispatch"):
        res = gated_forward_entry(o, "EURUSD", "BUY", 0.01, stop=1.0900, tp=0.0, ref=1.0947,
                                  comment="FT_TR_EURUSD_H4_T1")
    assert res["status"] == "BLOCKED" and "Weekly" in res["reason"]
