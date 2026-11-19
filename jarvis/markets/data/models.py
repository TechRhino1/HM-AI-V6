"""One shape for every market value: the number plus where and when it came from.

`kind` is what the UI shows as a badge:
  live         fresh during an open session (age within the freshness window)
  delayed      a feed with a known delay (e.g. TradingView's free 15-minute feed)
  close        the market is closed; this is the last official price
  eod          published once per day (FII/DII, settlement figures)
  stale        was live, but has not been refreshed within the freshness window
  unavailable  no source answered; the value is absent, never filled in
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

KINDS = ("live", "delayed", "close", "eod", "stale", "unavailable")
# Recommendations may only be built on these.
TRUSTED_KINDS = ("live", "close", "eod")


@dataclass
class Provenance:
    source: str                 # e.g. "nse:option-chain-v3@nseindia.in", "yahoo:chart", "tradingview:scanner"
    kind: str                   # one of KINDS
    as_of: Optional[float]      # epoch seconds of the data itself (not of our fetch), None if unknown
    fetched_at: float = field(default_factory=time.time)
    delay_sec: Optional[int] = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown provenance kind {self.kind!r}")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["age_sec"] = round(time.time() - self.as_of, 1) if self.as_of else None
        return d


def unavailable(source: str, note: str) -> Provenance:
    return Provenance(source=source, kind="unavailable", as_of=None, note=note)


def grade(source: str, as_of: Optional[float], session_open: bool, fresh_sec: float,
          delay_sec: Optional[int] = None) -> Provenance:
    """Classify a real value by its actual age, not by what the source claims."""
    if as_of is None:
        return Provenance(source=source, kind="unavailable", as_of=None, note="no timestamp from source")
    if delay_sec:
        return Provenance(source=source, kind="delayed", as_of=as_of, delay_sec=delay_sec)
    if not session_open:
        return Provenance(source=source, kind="close", as_of=as_of)
    age = time.time() - as_of
    return Provenance(source=source, kind="live" if age <= fresh_sec else "stale", as_of=as_of)


@dataclass
class Quote:
    symbol: str
    price: float
    change_pct: Optional[float]
    prev_close: Optional[float]
    day_high: Optional[float]
    day_low: Optional[float]
    volume: Optional[float]
    currency: str
    prov: Provenance
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["prov"] = self.prov.to_dict()
        return d


@dataclass
class OptionSide:
    ltp: float
    bid: Optional[float]           # best bid from the exchange order book; None when there is no bid
    ask: Optional[float]
    bid_qty: int
    ask_qty: int
    oi: int
    oi_change: int                 # absolute change in open interest today
    oi_change_pct: float
    volume: int
    iv: Optional[float]            # exchange IV in %, None when the exchange reports 0
    change: float                  # premium change today
    change_pct: float


@dataclass
class ChainRow:
    strike: float
    call: Optional[OptionSide]
    put: Optional[OptionSide]


@dataclass
class OptionChain:
    symbol: str
    expiry: str                    # as the exchange writes it, e.g. "23-Nov-2026"
    expiries: List[str]
    spot: float
    rows: List[ChainRow]
    lot_size: Optional[int]
    prov: Provenance

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["prov"] = self.prov.to_dict()
        return d
