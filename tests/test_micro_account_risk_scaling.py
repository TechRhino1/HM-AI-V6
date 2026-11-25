import unittest
from datetime import datetime
from jarvis.data.schemas import PositionSnapshot, AccountSnapshot
from jarvis.risk.exposure import ExposureManager
from jarvis.risk.portfolio_heat import PortfolioHeatEngine

class TestMicroAccountRiskScaling(unittest.TestCase):
    def setUp(self):
        self.exp = ExposureManager(
            max_open_positions=3,
            max_portfolio_risk_pct=2.5
        )
        self.heat = PortfolioHeatEngine(
            max_portfolio_risk_pct=2.5,
            max_open_positions=3
        )

    def test_micro_account_allows_higher_portfolio_risk_and_4_positions(self):
        # 3 micro-positions on a $372 account totaling $30 risk (8.07% risk)
        positions = [
            PositionSnapshot(ticket=1, symbol="BTCUSD", type="BUY", volume=0.01, open_price=83400.0, current_price=83700.0, sl=81234.0, tp=89000.0, profit=3.0, swap=0.0, commission=0.0, open_time=datetime.now(), magic=888999),
            PositionSnapshot(ticket=2, symbol="EURUSD", type="BUY", volume=0.02, open_price=1.1188, current_price=1.1186, sl=1.1153, tp=1.1290, profit=-0.5, swap=0.0, commission=0.0, open_time=datetime.now(), magic=888999),
            PositionSnapshot(ticket=3, symbol="ETHUSD", type="SELL", volume=0.03, open_price=2504.0, current_price=2502.0, sl=2551.0, tp=2370.0, profit=0.5, swap=0.0, commission=0.0, open_time=datetime.now(), magic=888999)
        ]
        micro_account = AccountSnapshot(
            login=101059540,
            server="XMGlobal-MT5",
            balance=372.0,
            equity=372.0,
            margin=15.0,
            free_margin=357.0,
            margin_level=2480.0,
            leverage=500
        )

        # Check exposure for a 4th trade (XAUUSD Gold with incoming risk ~$2.0)
        res = self.exp.check_exposure("XAUUSD", positions, micro_account, incoming_risk_usd=2.0)
        
        # Must pass because micro account (<$500) has an adaptive cap of 10.0% and 4 open positions
        self.assertTrue(res["passed"], f"Expected to pass on micro account, but breached: {res.get('breaches')}")
        self.assertEqual(len(res["breaches"]), 0)

    def test_standard_account_strictly_enforces_2_point_5_ceiling(self):
        # Same $30 risk on an institutional account where equity is $1000
        positions = [
            PositionSnapshot(ticket=1, symbol="BTCUSD", type="BUY", volume=0.01, open_price=83400.0, current_price=83700.0, sl=81234.0, tp=89000.0, profit=3.0, swap=0.0, commission=0.0, open_time=datetime.now(), magic=888999),
            PositionSnapshot(ticket=2, symbol="EURUSD", type="BUY", volume=0.02, open_price=1.1188, current_price=1.1186, sl=1.1153, tp=1.1290, profit=-0.5, swap=0.0, commission=0.0, open_time=datetime.now(), magic=888999),
            PositionSnapshot(ticket=3, symbol="ETHUSD", type="SELL", volume=0.03, open_price=2504.0, current_price=2502.0, sl=2551.0, tp=2370.0, profit=0.5, swap=0.0, commission=0.0, open_time=datetime.now(), magic=888999)
        ]
        large_account = AccountSnapshot(
            login=101059540,
            server="XMGlobal-MT5",
            balance=10000.0,
            equity=10000.0,
            margin=15.0,
            free_margin=9985.0,
            margin_level=66000.0,
            leverage=500
        )
        # On a $10,000 account, if incoming risk is $300 (total $330 = 3.3% > 2.5%), it must breach
        res = self.exp.check_exposure("XAUUSD", positions, large_account, incoming_risk_usd=300.0)
        self.assertFalse(res["passed"])
        self.assertTrue(any("Portfolio Risk Budget exceeded" in b for b in res["breaches"]))

if __name__ == "__main__":
    unittest.main()


def test_forward_test_positions_do_not_fill_main_slots():
    # 2026-11-18: four FT_ trend-router trades held all 4 main-engine slots.
    exp = ExposureManager(max_open_positions=3, max_portfolio_risk_pct=2.5)
    acct = AccountSnapshot(login=1, server="demo", balance=520.0, equity=520.0, margin=5.0,
                           free_margin=515.0, margin_level=10000.0, leverage=500)

    def pos(t, comment):
        return PositionSnapshot(ticket=t, symbol="EURUSD", type="SELL", volume=0.01, open_price=1.0970,
                                current_price=1.0970, sl=1.1040, tp=1.0900, profit=0.0, swap=0.0,
                                commission=0.0, open_time=datetime.now(), magic=888999, comment=comment)

    ft = [pos(i, "FT_DCH_H4") for i in range(4)]
    assert not any("Max Concurrent" in b for b in exp.check_exposure("XAUUSD", ft, acct)["breaches"])
    main = [pos(i, "") for i in range(4)]
    assert any("Max Concurrent" in b for b in exp.check_exposure("XAUUSD", main, acct)["breaches"])


def test_forward_test_positions_do_not_use_symbol_slots():
    # 2026-11-19: two FT_ positions on EURUSD/USDJPY left the engine at HARD_SYMBOL_LIMIT all day.
    from jarvis.risk.exposure import is_forward_test
    exp = ExposureManager(max_open_positions=3, max_portfolio_risk_pct=2.5)
    acct = AccountSnapshot(login=1, server="demo", balance=520.0, equity=520.0, margin=5.0,
                           free_margin=515.0, margin_level=10000.0, leverage=500)

    def pos(t, comment):
        return PositionSnapshot(ticket=t, symbol="EURUSD", type="SELL", volume=0.01, open_price=1.0970,
                                current_price=1.0970, sl=1.1040, tp=1.0900, profit=0.0, swap=0.0,
                                commission=0.0, open_time=datetime.now(), magic=888999, comment=comment)

    ft = [pos(1, "FT_TR_EURUSD_D1_T3"), pos(2, "FT_TR_EURUSD_H4_T1")]
    assert not any("EURUSD" in b and "Exposure" in b for b in exp.check_exposure("EURUSD", ft, acct)["breaches"])
    assert exp.get_active_risk_positions_for_symbol("EURUSD", ft) == 0
    main = [pos(1, ""), pos(2, "")]
    assert any("Hard Max Exposure" in b for b in exp.check_exposure("EURUSD", main, acct)["breaches"])
    assert is_forward_test({"comment": "FT_X"}) and not is_forward_test({"comment": "JARVIS"})


def _acct(eq):
    return AccountSnapshot(login=1, server="demo", balance=eq, equity=eq, margin=5.0,
                           free_margin=eq - 5.0, margin_level=10000.0, leverage=500)


def _main(t, sym, price=1.0970):
    return PositionSnapshot(ticket=t, symbol=sym, type="SELL", volume=0.01, open_price=price,
                            current_price=price, sl=price * 1.01, tp=price * 0.98, profit=0.0, swap=0.0,
                            commission=0.0, open_time=datetime.now(), magic=888999)


def test_one_slot_is_always_held_for_gold():
    """User directive 2026-11-26: other symbols may never take the last slot while gold has none."""
    exp = ExposureManager(max_open_positions=3, max_portfolio_risk_pct=2.5)
    book = [_main(1, "EURUSD"), _main(2, "GBPUSD#"), _main(3, "USDCHF")]          # $462: 4 slots
    nongold = exp.check_exposure("NZDUSD", book, _acct(462.0))["breaches"]
    assert any("Max Concurrent" in b and "reserved for XAUUSD" in b for b in nongold)
    assert not any("Max Concurrent" in b for b in exp.check_exposure("XAUUSD", book, _acct(462.0))["breaches"])


def test_reserved_slot_is_released_once_gold_holds_it():
    exp = ExposureManager(max_open_positions=3, max_portfolio_risk_pct=2.5)
    book = [_main(1, "GOLD.i#", 3600.0), _main(2, "EURUSD"), _main(3, "GBPUSD")]
    assert not any("Max Concurrent" in b for b in exp.check_exposure("NZDUSD", book, _acct(462.0))["breaches"])
