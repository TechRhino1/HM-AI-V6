"""Equity universes: symbol metadata only (names, fallback sectors, TradingView ids). No prices live here.

Symbols/names taken from jarvis/stocks/universe.py and jarvis/india/universe.py; TradingView exchanges
were resolved against the live scanner on 2026-11-18 (ZOMATO is now listed as ETERNAL; GOOG dropped as
a duplicate share class of GOOGL). These are today's large caps, so any backtest on them is survivorship-biased.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

# symbol, name, fallback sector (TradingView's live sector is preferred when it answers)
IN: List[Tuple[str, str, str]] = [
    ("RELIANCE", "Reliance Industries", "Energy"), ("TCS", "Tata Consultancy Services", "Technology"),
    ("HDFCBANK", "HDFC Bank", "Financial Services"), ("INFY", "Infosys", "Technology"),
    ("ICICIBANK", "ICICI Bank", "Financial Services"), ("SBIN", "State Bank of India", "Financial Services"),
    ("BHARTIARTL", "Bharti Airtel", "Telecommunications"), ("LT", "Larsen & Toubro", "Industrials"),
    ("BAJFINANCE", "Bajaj Finance", "Financial Services"), ("TMPV", "Tata Motors Passenger Vehicles", "Consumer Cyclical"),
    ("ITC", "ITC", "Consumer Defensive"), ("SUNPHARMA", "Sun Pharmaceutical", "Healthcare"),
    ("MARUTI", "Maruti Suzuki India", "Consumer Cyclical"), ("TITAN", "Titan Company", "Consumer Cyclical"),
    ("ADANIENT", "Adani Enterprises", "Industrials"), ("TTML", "Tata Teleservices (Maharashtra)", "Technology"),
    ("TATASTEEL", "Tata Steel", "Basic Materials"), ("AXISBANK", "Axis Bank", "Financial Services"),
    ("WIPRO", "Wipro", "Technology"), ("HCLTECH", "HCL Technologies", "Technology"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Financial Services"), ("ONGC", "Oil & Natural Gas Corporation", "Energy"),
    ("NTPC", "NTPC", "Utilities"), ("POWERGRID", "Power Grid Corporation of India", "Utilities"),
    ("COALINDIA", "Coal India", "Energy"), ("ETERNAL", "Eternal (Zomato)", "Consumer Cyclical"),
    ("PAYTM", "One97 Communications (Paytm)", "Financial Services"), ("JIOFIN", "Jio Financial Services", "Financial Services"),
    ("HAL", "Hindustan Aeronautics", "Industrials"), ("BEL", "Bharat Electronics", "Industrials"),
    ("TRENT", "Trent", "Consumer Cyclical"), ("VEDL", "Vedanta", "Basic Materials"),
    ("DLF", "DLF", "Real Estate"), ("SWIGGY", "Swiggy", "Consumer Cyclical"),
    ("HYUNDAI", "Hyundai Motor India", "Consumer Cyclical"), ("DIXON", "Dixon Technologies (India)", "Technology"),
]

US: List[Tuple[str, str, str]] = [
    ("NVDA", "NVIDIA", "Technology"), ("AMD", "Advanced Micro Devices", "Technology"), ("AVGO", "Broadcom", "Technology"),
    ("TSM", "Taiwan Semiconductor Manufacturing", "Technology"), ("ARM", "Arm Holdings", "Technology"),
    ("SMCI", "Super Micro Computer", "Technology"), ("MU", "Micron Technology", "Technology"), ("QCOM", "Qualcomm", "Technology"),
    ("AAPL", "Apple", "Technology"), ("MSFT", "Microsoft", "Technology"), ("AMZN", "Amazon.com", "Consumer Cyclical"),
    ("GOOGL", "Alphabet", "Communication Services"), ("META", "Meta Platforms", "Communication Services"),
    ("TSLA", "Tesla", "Consumer Cyclical"), ("PLTR", "Palantir Technologies", "Technology"),
    ("COIN", "Coinbase Global", "Financial Services"), ("MSTR", "Strategy (MicroStrategy)", "Technology"),
    ("NFLX", "Netflix", "Communication Services"), ("UBER", "Uber Technologies", "Technology"),
    ("DIS", "Walt Disney", "Communication Services"), ("PANW", "Palo Alto Networks", "Technology"),
    ("CRM", "Salesforce", "Technology"), ("SHOP", "Shopify", "Technology"), ("LLY", "Eli Lilly", "Healthcare"),
    ("JNJ", "Johnson & Johnson", "Healthcare"), ("UNH", "UnitedHealth Group", "Healthcare"),
    ("JPM", "JPMorgan Chase", "Financial Services"), ("V", "Visa", "Financial Services"),
    ("BAC", "Bank of America", "Financial Services"), ("XOM", "Exxon Mobil", "Energy"), ("CVX", "Chevron", "Energy"),
    ("BA", "Boeing", "Industrials"), ("CAT", "Caterpillar", "Industrials"), ("WMT", "Walmart", "Consumer Defensive"),
    ("COST", "Costco Wholesale", "Consumer Defensive"), ("NIO", "NIO", "Consumer Cyclical"),
    ("RIVN", "Rivian Automotive", "Consumer Cyclical"), ("LCID", "Lucid Group", "Consumer Cyclical"),
    ("XPEV", "XPeng", "Consumer Cyclical"), ("LI", "Li Auto", "Consumer Cyclical"),
    ("HOOD", "Robinhood Markets", "Financial Services"), ("SOFI", "SoFi Technologies", "Financial Services"),
    ("MARA", "MARA Holdings", "Financial Services"), ("CRWD", "CrowdStrike", "Technology"),
    ("INTC", "Intel", "Technology"), ("BABA", "Alibaba Group", "Consumer Cyclical"),
]

_NYSE = {"BA", "BABA", "BAC", "CAT", "CRM", "CVX", "DIS", "JNJ", "JPM", "LLY", "NIO", "TSM", "UBER", "UNH", "V", "XOM", "XPEV"}


def members(market: str) -> List[Tuple[str, str, str]]:
    return IN if market == "IN" else US


def symbols(market: str) -> List[str]:
    return [s for s, _, _ in members(market)]


def meta(market: str) -> Dict[str, Dict[str, str]]:
    return {s: {"name": n, "sector": sec} for s, n, sec in members(market)}


def tv_id(symbol: str, market: str) -> str:
    s = symbol.upper()
    if market == "IN":
        return f"NSE:{s}"
    return f"{'NYSE' if s in _NYSE else 'NASDAQ'}:{s}"
