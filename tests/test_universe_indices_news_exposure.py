"""The six calibrated symbols added to the universe (2026-11-23) are covered by the news
blackout and the currency-concentration map: before, no US/EUR/GBP release ever named
US30/NAS100/GER40/UK100, so index entries were never blacked out around NFP or CPI."""
import inspect
from types import SimpleNamespace

from jarvis.config.settings import SETTINGS
from jarvis.market import news
from jarvis.risk.exposure import ExposureManager


def test_us_releases_cover_the_us_indices():
    assert {"US30", "NAS100"} <= set(news.USD_AFFECTED)


def test_eur_and_gbp_releases_cover_their_indices():
    src = inspect.getsource(news)
    assert src.count('["EURUSD", "EURGBP", "EURJPY", "GER40"]') == 2
    assert src.count('["GBPUSD", "EURGBP", "GBPJPY", "UK100"]') == 2


def test_added_symbols_are_in_the_universe():
    # Registered and tradable; whether each is ENABLED is the operator's allowed_symbols choice.
    from jarvis.data.symbol_registry import all_symbols
    registered = {s.canonical for s in all_symbols()}
    assert {"GER40", "UK100", "US30", "USDCHF", "NZDUSD", "XAGUSD"} <= registered


def _pos(sym, side):
    return SimpleNamespace(symbol=sym, side=side, type=side, comment="")


def test_silver_and_indices_count_toward_usd_concentration():
    em = ExposureManager()
    book = [_pos("XAGUSD", "BUY"), _pos("US30", "BUY"), _pos("XAUUSD", "BUY")]
    # three longs against USD already: a fourth USD-short leg is concentration
    assert em.check_currency_directional_exposure("EURUSD", "BUY", book)["passed"] is False
    assert em.check_currency_directional_exposure("EURUSD", "BUY", book[:1])["passed"] is True
