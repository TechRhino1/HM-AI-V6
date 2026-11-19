"""
Real market-data provider for MT5 broker feeds and global equities.

Callers must never silently present fabricated price history as if it were
real. This module centralises the attempt to fetch genuine OHLCV candles from a
live source and returns ``None`` when none is reachable (MT5 unavailable,
yfinance not installed, or no network connectivity).

Live sources (attempted in order):
  1. `MetaTrader5` (MT5) — real-time broker prices & tick volume.
  2. TradingView scanner feed.
  3. `yfinance`  — free, no API key (e.g. ``AAPL``).
"""
from typing import Optional, List, Dict, Any

from jarvis.data.broker_symbols import resolve_broker_symbol
import logging
import re
import threading
import datetime as _dt

logger = logging.getLogger("jarvis.market_data")

# ── Candle provenance ────────────────────────────────────────────────────────
# A candle series must say where it came from. The engines used to report the
# provenance of the ANCHOR PRICE as the provenance of the SERIES, so a fully
# generated random walk anchored to a live quote was reported as "live"
# (`stock_engine.py:59`, `india_engine.py:46`). Measured: a series rebuilt from
# `stable_seed(f"{symbol}_{tf}_{hour}")` matched the returned bars to within the
# 2dp rounding, i.e. no bar was ever observed — while `data_source` said "live",
# and the last 12% of bars was a *guaranteed* monotonic surge (`stock_engine.py:98`).
SOURCE_LIVE = "live"                              # bars read from a real feed
SOURCE_SYNTHETIC_ANCHORED = "synthetic_anchored"  # bars generated, anchored to a live quote
SOURCE_CALIBRATED_FEED = "calibrated_feed"        # bars generated from a static reference price

# `calibrated_feed` keeps its existing wire value deliberately: `dashboard.js`
# SOURCE_META already renders it as "modelled", and `test_integrity_fixes` asserts on
# it. Only `synthetic_anchored` is new — the case that used to be mislabelled "live".
SYNTHETIC_SOURCES = frozenset({SOURCE_SYNTHETIC_ANCHORED, SOURCE_CALIBRATED_FEED})


class CandleSeries(list):
    """A list of OHLCV dicts that knows where it came from.

    A plain list cannot carry provenance, so the engines kept it in an instance
    attribute (`_last_data_source`) on a module-level SINGLETON that the stocks
    screener drives from a 16-thread pool (`stock_service.py:57`). Symbol A's label
    could therefore be read while symbol B's response was being built. Attaching the
    provenance to the series removes the shared state as well as the ambiguity.

    A `list` subclass keeps every existing consumer working unchanged:
    `pd.DataFrame(series)`, `len()`, iteration, slicing and `json.dumps` all behave
    as they did for a plain list.
    """

    __slots__ = ("source", "anchor_source")

    def __init__(self, candles, source=SOURCE_LIVE, anchor_source=None):
        super().__init__(candles)
        self.source = source
        self.anchor_source = anchor_source

    @property
    def is_synthetic(self) -> bool:
        """True when the bars were generated rather than observed."""
        return self.source in SYNTHETIC_SOURCES

    def __repr__(self):
        return f"CandleSeries({list.__len__(self)} bars, source={self.source!r})"


try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

_MT5_LOCK = threading.Lock()
_TF_TO_YF = {
    "1M": "1m", "5M": "5m", "15M": "15m", "30M": "30m",
    "1H": "1h", "4H": "4h", "1D": "1d", "1W": "1wk", "1MO": "1mo",
}

_TF_TO_MT5 = {
    "1M": getattr(mt5, "TIMEFRAME_M1", 1) if (MT5_AVAILABLE and mt5) else 1,
    "M1": getattr(mt5, "TIMEFRAME_M1", 1) if (MT5_AVAILABLE and mt5) else 1,
    "5M": getattr(mt5, "TIMEFRAME_M5", 5) if (MT5_AVAILABLE and mt5) else 5,
    "M5": getattr(mt5, "TIMEFRAME_M5", 5) if (MT5_AVAILABLE and mt5) else 5,
    "15M": getattr(mt5, "TIMEFRAME_M15", 15) if (MT5_AVAILABLE and mt5) else 15,
    "M15": getattr(mt5, "TIMEFRAME_M15", 15) if (MT5_AVAILABLE and mt5) else 15,
    "30M": getattr(mt5, "TIMEFRAME_M30", 30) if (MT5_AVAILABLE and mt5) else 30,
    "M30": getattr(mt5, "TIMEFRAME_M30", 30) if (MT5_AVAILABLE and mt5) else 30,
    "1H": getattr(mt5, "TIMEFRAME_H1", 16385) if (MT5_AVAILABLE and mt5) else 16385,
    "H1": getattr(mt5, "TIMEFRAME_H1", 16385) if (MT5_AVAILABLE and mt5) else 16385,
    "4H": getattr(mt5, "TIMEFRAME_H4", 16388) if (MT5_AVAILABLE and mt5) else 16388,
    "H4": getattr(mt5, "TIMEFRAME_H4", 16388) if (MT5_AVAILABLE and mt5) else 16388,
    "1D": getattr(mt5, "TIMEFRAME_D1", 16408) if (MT5_AVAILABLE and mt5) else 16408,
    "D1": getattr(mt5, "TIMEFRAME_D1", 16408) if (MT5_AVAILABLE and mt5) else 16408,
    "1W": getattr(mt5, "TIMEFRAME_W1", 32769) if (MT5_AVAILABLE and mt5) else 32769,
    "W1": getattr(mt5, "TIMEFRAME_W1", 32769) if (MT5_AVAILABLE and mt5) else 32769,
    "1MO": getattr(mt5, "TIMEFRAME_MN1", 49153) if (MT5_AVAILABLE and mt5) else 49153,
    "MN1": getattr(mt5, "TIMEFRAME_MN1", 49153) if (MT5_AVAILABLE and mt5) else 49153,
}

_COMMON_STOCK_ALIASES = {
    "GOOGL": "Google",
    "GOOG": "Google",
    "META": "Facebook",
    "FB": "Facebook",
    "AMD": "AdvMicroDev",
    "DIS": "Disney",
    "AAPL": "Apple",
    "NVDA": "Nvidia",
    "TSLA": "Tesla",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "NFLX": "Netflix",
    "PLTR": "Palantir",
    "COIN": "Coinbase",
    "UBER": "Uber",
    "BA": "Boeing",
    "INTC": "Intel",
    "AVGO": "Broadcom",
    "TSM": "Taiwan-Semiconductor",
    "ARM": "Arm Holdings",
    "SMCI": "Super Micro Computer",
    "MU": "Micron",
    "QCOM": "Qualcomm",
    "PANW": "PaloAltoNetworks",
    "CRM": "Salesforce",
    "SHOP": "Shopify",
    "LLY": "EliLilly",
    "JNJ": "J&J",
    "UNH": "UnitedHealth",
    "JPM": "JPMorgan",
    "V": "Visa",
    "BAC": "BofAmerica",
    "XOM": "ExxonMobil",
    "CVX": "Chevron",
    "CAT": "Caterpillar",
    "WMT": "WalMart",
    "COST": "Costco",
    "NIO": "NIO",
    "RIVN": "Rivian",
    "LCID": "LucidGroup",
    "XPEV": "Xpeng",
    "LI": "LiAuto",
    "HOOD": "Robinhood",
    "SOFI": "SoFiTechnologies",
    "CRWD": "Crowdstrike",
    "BABA": "Alibaba",
}

_DESC_PATTERN = re.compile(r'\(([A-Z0-9]+)(?:\.[A-Z]+)?\)')
_MT5_RESOLVED_CACHE: Dict[str, Optional[str]] = {}
_MT5_SYMBOL_MAP: Dict[str, str] = {}
_MT5_INDEX_BUILT: bool = False


def _ensure_mt5_connected() -> bool:
    """Check whether MT5 is connected, WITHOUT ever launching the terminal.

    This used to end in a bare ``mt5.initialize()``. With no terminal running that
    call blocks inside native code **holding the GIL** and never returns — measured:
    a child process calling ``generate_candles("NVDA")`` was still alive after 25s
    and had to be killed (``.scratch/prove_mt5_block.py``). Because the GIL is held,
    no other thread runs either, so a single candle request
    wedged the entire server — the process stayed alive
    and kept logging while answering nothing.

    ``ensure_mt5_terminal`` is the read-path gate: it refuses to call
    ``initialize()`` unless a terminal process is already running, throttles repeat
    calls, and logs once per outage. Launching a terminal stays a BOOT-TIME decision
    (``HM_start.py`` passes ``allow_launch=True``); a request thread must never make
    it. When the process check cannot answer (no psutil) the gate falls through to
    the old behaviour rather than inventing a dead terminal.
    """
    if not MT5_AVAILABLE or mt5 is None:
        return False
    try:
        t_info = mt5.terminal_info()
        if t_info is not None and getattr(t_info, "connected", False):
            return True
        # `terminal_info()` is a cheap cached read, so reaching here means "not
        # attached". Attach only if a terminal is already up.
        from jarvis.data.broker_symbols import ensure_mt5_terminal
        return ensure_mt5_terminal()
    except Exception as exc:
        logger.debug("MT5 connection check failed: %s", exc)
        return False


def _build_mt5_symbol_index():
    global _MT5_INDEX_BUILT
    if not _ensure_mt5_connected():
        return
    symbols = mt5.symbols_get()
    if not symbols:
        return
    for s in symbols:
        name = s.name
        desc = s.description or ""
        m = _DESC_PATTERN.search(desc)
        if m:
            ticker = m.group(1).upper()
            if ticker not in _MT5_SYMBOL_MAP:
                _MT5_SYMBOL_MAP[ticker] = name
        s_u = name.upper()
        if s_u not in _MT5_SYMBOL_MAP:
            _MT5_SYMBOL_MAP[s_u] = name
    _MT5_INDEX_BUILT = True


def _resolve_mt5_symbol(symbol: str) -> Optional[str]:
    """Dynamically resolve stock ticker to MT5 broker symbol."""
    ticker = symbol.strip().upper()
    with _MT5_LOCK:
        if ticker in _MT5_RESOLVED_CACHE:
            return _MT5_RESOLVED_CACHE[ticker]

        if not _ensure_mt5_connected():
            return None

        if not _MT5_INDEX_BUILT:
            _build_mt5_symbol_index()

        # 1. Direct match from regex-parsed descriptions
        if ticker in _MT5_SYMBOL_MAP:
            cand = _MT5_SYMBOL_MAP[ticker]
            if mt5.symbol_info(cand) is not None:
                _MT5_RESOLVED_CACHE[ticker] = cand
                return cand

        # 2. Direct match s.name.upper() == ticker or ticker + "#" or ticker + ".US"
        for suffix in ("", "#", ".US", ".C", "M"):
            key = f"{ticker}{suffix}"
            if key in _MT5_SYMBOL_MAP:
                cand = _MT5_SYMBOL_MAP[key]
                if mt5.symbol_info(cand) is not None:
                    _MT5_RESOLVED_CACHE[ticker] = cand
                    return cand
            info = mt5.symbol_info(key)
            if info is not None:
                _MT5_RESOLVED_CACHE[ticker] = info.name
                return info.name

        # 3. Common alias dictionary fallback
        if ticker in _COMMON_STOCK_ALIASES:
            cand = _COMMON_STOCK_ALIASES[ticker]
            if mt5.symbol_info(cand) is not None:
                _MT5_RESOLVED_CACHE[ticker] = cand
                return cand

        # 4. Direct scan across all symbols if index missed something
        all_syms = mt5.symbols_get() or []
        for s in all_syms:
            desc = s.description or ""
            m = _DESC_PATTERN.search(desc)
            if m and m.group(1).upper() == ticker:
                _MT5_RESOLVED_CACHE[ticker] = s.name
                return s.name
            s_u = s.name.upper()
            if s_u == ticker or s_u == f"{ticker}#" or s_u == f"{ticker}.US":
                _MT5_RESOLVED_CACHE[ticker] = s.name
                return s.name

        _MT5_RESOLVED_CACHE[ticker] = None
        return None


def _try_mt5(symbol: str, timeframe: str = "1D", num_bars: int = 120) -> Optional[List[Dict[str, Any]]]:
    """High-performance MT5 symbol resolver and rate fetcher."""
    if not MT5_AVAILABLE or mt5 is None:
        return None
    try:
        resolved_sym = _resolve_mt5_symbol(symbol)
        if not resolved_sym:
            return None

        with _MT5_LOCK:
            # Select symbol in MarketWatch
            mt5.symbol_select(resolved_sym, True)

            mt5_tf = _TF_TO_MT5.get(timeframe.upper(), getattr(mt5, "TIMEFRAME_D1", 16408))
            _broker_sym = resolve_broker_symbol(resolved_sym) or resolved_sym
            rates = mt5.copy_rates_from_pos(_broker_sym, mt5_tf, 0, num_bars)
        if rates is None or len(rates) == 0:
            return None

        candles: List[Dict[str, Any]] = []
        for r in rates:
            vol = int(r["tick_volume"]) if r["tick_volume"] > 0 else int(r["real_volume"])
            candles.append({
                "time": int(r["time"]),
                "open": round(float(r["open"]), 4),
                "high": round(float(r["high"]), 4),
                "low": round(float(r["low"]), 4),
                "close": round(float(r["close"]), 4),
                "volume": vol,
            })
        return candles if candles else None
    except Exception as exc:
        logger.warning("MT5 fetch failed for %s: %s", symbol, exc)
        return None


def _try_yfinance(ticker: str, timeframe: str, num_bars: int) -> Optional[List[Dict[str, Any]]]:
    try:
        import yfinance as yf
    except Exception:
        return None
    interval = _TF_TO_YF.get(timeframe.upper(), "1d")
    # Intraday histories are only available for a short window on Yahoo.
    period = "5d" if interval in ("1m", "5m", "15m", "30m") else "1y"
    try:
        df = yf.Ticker(ticker).history(
            period=period, interval=interval, actions=False, auto_adjust=False, timeout=1.5
        )
    except Exception as exc:  # noqa: BLE001 - any failure means "no live data"
        logger.warning("yfinance fetch failed for %s: %s", ticker, exc)
        return None
    if df is None or len(df) == 0:
        return None
    rows: List[Dict[str, Any]] = []
    for ts, row in df.iterrows():
        rows.append({
            "time": int(ts.timestamp()),
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
            "volume": int(row.get("Volume", 0) or 0),
        })
    rows = rows[-num_bars:]
    return rows if rows else None


def _try_tradingview(symbol: str, timeframe: str = "1D", num_bars: int = 120) -> Optional[List[Dict[str, Any]]]:
    """Attempt to fetch live candles via TradingView scanner and real-time feeds."""
    try:
        from jarvis.data.tradingview_provider import TRADINGVIEW_PROVIDER
        return TRADINGVIEW_PROVIDER.fetch_candles(symbol, timeframe=timeframe, num_bars=num_bars)
    except Exception as exc:
        logger.debug("TradingView fetch failed for %s: %s", symbol, exc)
        return None


def fetch_real_candles(
    symbol: str,
    timeframe: str = "1D",
    num_bars: int = 120,
    market: str = "US",
) -> Optional[List[Dict[str, Any]]]:
    """Attempt to fetch genuine OHLCV candles across the multi-tier data hierarchy.

    Hierarchy for US / Global (market == "US"):
      Tier 1: MT5 live broker feed
      Tier 2: TradingView Scanner real-time feed
      Tier 3: yfinance free exchange feed

    Returns a list of candle dicts (newest last) or ``None`` when no live
    source is reachable.
    """
    # US / Global equities:
    # Tier 1: MT5 live broker feed
    candles = _try_mt5(symbol, timeframe=timeframe, num_bars=num_bars)
    if candles:
        logger.info("Live MT5 candles for %s (%d bars)", symbol, len(candles))
        return candles

    # Tier 2: TradingView live scanner provider
    candles = _try_tradingview(symbol, timeframe=timeframe, num_bars=num_bars)
    if candles:
        logger.info("Live TradingView candles for %s (%d bars)", symbol, len(candles))
        return candles

    # Tier 3: yfinance free exchange feed
    candles = _try_yfinance(symbol, timeframe, num_bars)
    if candles:
        logger.info("Live yfinance candles for %s (%d bars)", symbol, len(candles))
        return candles

    return None
