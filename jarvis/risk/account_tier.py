"""
HM Algo 2.0 — Unified Account Tier & Micro Definition System.

Provides a single source of truth for account sizing tiers, micro-mode gating,
lot caps, and economic expected-value (EV) scaling across all HM Algo 2.0 engines.
"""
from enum import Enum

class AccountTier(str, Enum):
    ULTRA_SURVIVAL = "ULTRA_SURVIVAL"  # < $40
    MICRO_GROWTH   = "MICRO_GROWTH"    # $40 - $100
    SMALL_ACCOUNT  = "SMALL_ACCOUNT"   # $100 - $250
    STANDARD       = "STANDARD"        # $250 - $1,000
    INSTITUTIONAL  = "INSTITUTIONAL"   # >= $1,000

def get_account_tier(equity: float) -> AccountTier:
    """Returns canonical AccountTier based on current account equity."""
    eq = float(equity)
    if eq < 40.0:
        return AccountTier.ULTRA_SURVIVAL
    elif eq < 100.0:
        return AccountTier.MICRO_GROWTH
    elif eq < 250.0:
        return AccountTier.SMALL_ACCOUNT
    elif eq < 1000.0:
        return AccountTier.STANDARD
    else:
        return AccountTier.INSTITUTIONAL

def is_micro_account(equity: float) -> bool:
    """True if account is in micro or small capital mode (< $500 equity)."""
    return float(equity) < 500.0

def is_nano_account(equity: float) -> bool:
    """True if account is in nano tier (< $250 equity)."""
    return float(equity) < 250.0

def _risk_policy():
    from jarvis.config.settings import SETTINGS
    return SETTINGS.risk


def get_nano_risk_cap(equity: float, symbol: str = "") -> tuple[float, float]:
    """(max_risk_usd, max_risk_pct) a broker-minimum-lot trade may risk.

    One rule for every account size and symbol (risk policy 2026-11-16):
    ``min_lot_max_risk_pct`` of equity. A setup whose minimum lot would risk
    more is skipped, so wide-stop symbols (gold, BTC) wait until the account
    can afford them instead of taking an outsized loss. ``symbol`` is kept for
    call-site compatibility; the cap no longer varies by symbol.
    """
    pct = float(_risk_policy().min_lot_max_risk_pct)
    return float(equity) * pct / 100.0, pct


# Gold's 100 oz contract: on $250+ accounts its minimum lot may risk up to this much (c3ac298).
GOLD_MIN_LOT_RISK_PCT = 3.5


# Below $250, gold may still trade, but only SCALP setups, whose stops are tight enough (median 12
# points = $12 at 0.01 lot) to fit; a minimum lot may then risk up to this much (user decision
# 2026-11-24). Wider gold styles keep the policy cap, so they wait until the account can afford them.
GOLD_MICRO_SCALP_RISK_PCT = 5.0


def min_lot_risk_cap(equity: float, symbol: str = "", trade_style: str = "") -> tuple[float, float]:
    """(max_risk_usd, max_risk_pct) for a broker-minimum lot as the executor enforces it:
    the policy cap, with gold's headroom (3.5% on $250+ accounts; scalp-only 5% below $250).
    One place for both sizer and executor."""
    usd, pct = get_nano_risk_cap(equity, symbol)
    sym = (symbol or "").upper()
    if "XAU" in sym or "GOLD" in sym:
        if float(equity) >= 250.0:
            gold_pct = GOLD_MIN_LOT_RISK_PCT
        elif "SCALP" in str(trade_style or "").upper():
            gold_pct = GOLD_MICRO_SCALP_RISK_PCT
        else:
            gold_pct = pct
        if pct < gold_pct:
            pct = gold_pct
            usd = float(equity) * pct / 100.0
    return usd, pct


def get_milestone_risk_budget(equity: float, symbol: str = "") -> tuple[float, float]:
    """(target_risk_usd, target_risk_pct) for a normally sized trade: ``max_risk_per_trade_pct``."""
    pct = float(_risk_policy().max_risk_per_trade_pct)
    return float(equity) * pct / 100.0, pct

def get_max_lot_cap(equity: float, symbol: str = "") -> float:
    """
    Returns hard lot cap for risk protection on smaller accounts.
    Allows 0.02 lots on tight Forex stops on $100 accounts while keeping
    Gold strictly capped at 0.01 lots until $150+ to protect against liquidation spikes.
    """
    eq = float(equity)
    sym = (symbol or "").upper()
    is_gold = "XAU" in sym or "GOLD" in sym

    if eq < 100.0:
        return 0.01
    elif eq <= 150.0:
        # Gold and unspecified symbol default to 0.01 floor; explicit Forex allowed 0.02 lots
        return 0.01 if (is_gold or not sym) else 0.02
    elif eq < 250.0:
        # Gold unlocked for 0.02 lot multi-target split; Forex allowed up to 0.03 lots
        return 0.02 if (is_gold or not sym) else 0.03
    elif eq <= 500.0:
        return 0.05  # Enforce max 0.05 lots on $250-$500 micro accounts
    elif eq < 1000.0:
        return 0.10
    elif eq < 2500.0:
        return 0.15
    else:
        return 2.0  # Safe upper ceiling for standard retail accounts

def get_effective_min_ev(equity: float, planned_risk_dollars: float) -> float:
    """
    Returns mathematically sound expected-value hurdle (in dollars)
    scaled smoothly to account equity and 0.01 lot-floor constraints (§3).
    """
    eq = float(equity)
    prd = float(planned_risk_dollars)
    
    if eq < 100.0:
        return max(0.01, prd * 0.05)
    elif eq < 500.0:
        return max(0.05, prd * 0.10)
    elif eq < 1000.0:
        return max(0.10, prd * 0.20)
    else:
        return max(0.25, prd * 0.25)
