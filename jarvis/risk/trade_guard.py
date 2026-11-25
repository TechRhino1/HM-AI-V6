"""
HM Algo 2.0 — Autonomous Trade Quality Guard.
Executes hard independent pre-flight checks before approving any trade for execution.
"""
import math
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from jarvis.data.schemas import (
    DecisionObject,
    AccountSnapshot,
    PositionSnapshot,
    is_observed_price,
)
from jarvis.data.symbol_registry import resolve


def _is_finite(value: Any) -> bool:
    """True only for a real, finite number.

    NaN compares False against everything, so `nan > cap` and `nan >= entry` are
    both False and a NaN sails through every threshold below. An infinity passes
    one direction of each pair. Neither is ever a tradeable order.
    """
    try:
        return value is not None and math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


class TradeGuard:
    @staticmethod
    def validate_pre_execution(
        decision: DecisionObject,
        account: AccountSnapshot,
        positions: List[PositionSnapshot],
        max_spread_pips: float = 35.0,
        current_spread_pips: float = 2.0,
        entry_authorized_override: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Validate order geometry and spread before execution.

        ``entry_authorized_override`` exists because entry selection has two
        legitimate authorities. The legacy path is the 29-check gate stack, whose
        verdict lands in ``decision.decision``. The calibrated path is
        ``jarvis.execution.entry_policy``, which deliberately trades setups the
        legacy stack rejected — so checking ``decision.decision != "EXECUTE"``
        here silently reimposed the legacy veto and blocked every calibrated
        trade. Passing an explicit verdict keeps this guard focused on what it
        actually owns: geometry, spread and account permissions.
        """
        reasons = []

        if entry_authorized_override is None:
            if decision.decision != "EXECUTE":
                reasons.append(f"AI Decision status is '{decision.decision}' (Requires 'EXECUTE').")
        elif not entry_authorized_override:
            reasons.append("Entry not authorized by the calibrated entry policy.")

        if not account.trade_allowed:
            reasons.append("Account trade permissions disabled by broker.")

        symbol_data = resolve(decision.symbol)
        
        # Fix #5: Use correct attribute name 'max_spread_pips' (not 'max_spread')
        allowed_max_spread = getattr(symbol_data, 'max_spread_pips', max_spread_pips)
        
        # Crypto SPREAD ALLOWANCE window, 01:00-04:59 UTC: crypto spreads widen in
        # Asian hours, so the allowance doubles. This is NOT the orchestrator's
        # 00:00-06:00 non-crypto ASIAN_SESSION_BLACKOUT (a different rule).
        #
        # The hour must come from the BAR being evaluated, not from the wall
        # clock. Using datetime.now() made a backtest's spread allowance depend
        # on when the backtest was run — a reproducibility defect and, since the
        # allowance differs between sessions, a form of look-ahead.
        _bar_ts = getattr(getattr(decision, "context", None), "timestamp", None)
        if _bar_ts is not None and hasattr(_bar_ts, "hour"):
            # The window above is defined in UTC. Bar timestamps arrive with
            # their tzinfo intact (market_context passes them straight through)
            # and MT5 runs on the broker's clock, so an aware value has to be
            # converted — `.hour` alone would shift the window by the offset.
            if getattr(_bar_ts, "tzinfo", None) is not None:
                try:
                    _bar_ts = _bar_ts.astimezone(timezone.utc)
                except (AttributeError, TypeError, ValueError):
                    pass
            current_hour = int(_bar_ts.hour)
        else:
            current_hour = datetime.now(timezone.utc).hour
        is_asian_session = 1 <= current_hour < 5
        
        # Fix #5b: Use correct attribute for crypto detection
        is_crypto = getattr(symbol_data, 'is_crypto', False) or getattr(symbol_data, 'asset_class', '').upper() == 'CRYPTO' or 'BTC' in decision.symbol or 'ETH' in decision.symbol
        
        if is_crypto and is_asian_session:
            allowed_max_spread *= 2.0

        if not _is_finite(current_spread_pips):
            reasons.append(f"Spread is not a finite number ({current_spread_pips} pips).")
        elif current_spread_pips > allowed_max_spread:
            reasons.append(f"Spread ({current_spread_pips} pips) exceeds maximum threshold ({allowed_max_spread} pips).")

        # A price must be a real number AND strictly positive. `_is_finite(0.0)` is
        # True, so a finiteness check alone admitted a zero entry — and with entry at
        # ~0 the inverted-geometry comparisons below are all False, so a NEGATIVE stop
        # loss passed as well. Measured: an empty primary frame gives `market_context`
        # current_price = bid = 0.0 and ask = spread * pip, from which the levels
        # engine minted entry 0.02 / stop -0.04 for BTCUSD; the sizer read a risk
        # distance of 0.06 against a 65 000 instrument and returned 100 lots — 6.5M
        # USD of exposure for a 50 USD risk budget. `is_observed_price` is the same
        # predicate the producers of these numbers use, so the gate and the source
        # cannot drift apart.
        for _label, _value in (
            ("entry price", decision.entry_price),
            ("stop loss", decision.stop_loss),
            ("take profit", decision.take_profit),
        ):
            if not _is_finite(_value):
                reasons.append(f"Invalid order geometry: {_label} is not a finite number ({_value}).")
            elif not is_observed_price(_value):
                reasons.append(
                    f"Invalid order geometry: {_label} is not a positive, observed price ({_value})."
                )

        # Inverted or invalid stop loss / take profit check. The `else` matters:
        # geometry can only be judged against a direction, so a bias that is
        # neither BUY nor SELL (including a lower-cased one) used to skip both
        # checks and approve an inverted stop.
        if decision.bias == "BUY":
            if decision.stop_loss >= decision.entry_price:
                reasons.append("Invalid BUY order geometry: Stop loss is above entry price.")
            if decision.take_profit <= decision.entry_price:
                reasons.append("Invalid BUY order geometry: Take profit is below entry price.")
        elif decision.bias == "SELL":
            if decision.stop_loss <= decision.entry_price:
                reasons.append("Invalid SELL order geometry: Stop loss is below entry price.")
            if decision.take_profit >= decision.entry_price:
                reasons.append("Invalid SELL order geometry: Take profit is above entry price.")
        else:
            reasons.append(
                f"Invalid order geometry: unrecognised bias '{decision.bias}' (expected BUY or SELL)."
            )

        rr = TradeGuard.rr_assessment(decision)
        if not rr["ok"]:
            reasons.append(
                f"Sub-minimum Risk:Reward ratio {rr['rr']:.2f}:1 "
                f"(risk={rr['risk_dist']:.2f}, reward={rr['tp_dist']:.2f}, minimum {rr['floor']:.2f} required)."
            )

        is_passed = len(reasons) == 0
        return {
            "passed": is_passed,
            "reasons": reasons
        }

    @staticmethod
    def rr_assessment(decision: DecisionObject) -> Dict[str, Any]:
        """THE R:R floor (single source): the R:R the order will actually carry vs its floor.

        execution_engine rewrites the TP to the calibrated live target at dispatch, so the
        scan's TP is stale (2026-11-23: 844 ETH/SOL refusals against a target never sent).
        A deployable calibrated geometry was validated out of sample, so it is not held to
        the generic floor. Floor: decision.min_allowed_rr, else 1.30 scalp / 1.50 otherwise,
        with a 0.05 tolerance.
        """
        risk_dist = abs(decision.entry_price - decision.stop_loss)
        tp_dist = abs(decision.take_profit - decision.entry_price)
        rr = (tp_dist / risk_dist) if risk_dist > 1e-6 else 0.0
        skip_floor = False
        try:
            from jarvis.backtesting.exit_geometry import deployment_refusal, live_target_r
            fixed_r = live_target_r(decision.symbol)
            if fixed_r:
                rr = float(fixed_r)
                tp_dist = rr * risk_dist
                skip_floor = deployment_refusal(decision.symbol) is None
        except Exception:
            pass
        trade_style = str(getattr(decision, "trade_style", "") or "").upper()
        default_min = 1.30 if "SCALP" in trade_style else 1.50
        floor = float(getattr(decision, "min_allowed_rr", None) or default_min)
        ok = bool(skip_floor or rr >= (floor - 0.05))
        return {"ok": ok, "rr": rr, "floor": floor, "skip_floor": skip_floor,
                "risk_dist": risk_dist, "tp_dist": tp_dist}


# ─────────────────────────────────────────────────────────────────────────────
# Pre-send Verification Agent (2026-11-25 plan, Phase 3)
#
# The LAST independent check before an order reaches the broker, run by
# execution_engine.execute_decision for every origin (arbiter, forward test).
# It re-verifies the FINAL order (after sizing, governor scaling, promotion)
# with small pure rules. It never replaces a gate above it, never loosens one,
# and fails CLOSED: an exception or a blown time budget is BLOCKED_RISK.
# ─────────────────────────────────────────────────────────────────────────────
import threading as _threading
import time as _time
from dataclasses import dataclass as _dataclass, field as _field

APPROVED, REJECTED, NEEDS_ANALYSIS, BLOCKED_RISK = "APPROVED", "REJECTED", "NEEDS_ANALYSIS", "BLOCKED_RISK"
_RISK, _SIGNAL = "risk", "signal"

_SENDS_LOCK = _threading.Lock()
_RECENT_SENDS: Dict[tuple, float] = {}


def note_sent(symbol: str, side: str, origin: str = "arbiter", ts: Optional[float] = None) -> None:
    """Record a sent order for the duplicate rule (execution_engine calls this after a fill)."""
    with _SENDS_LOCK:
        _RECENT_SENDS[(resolve(symbol).canonical, str(side).upper(), origin.split(":", 1)[0])] = ts or _time.time()


@_dataclass
class PreSendContext:
    decision: Any
    lots: float
    spec: Dict[str, Any] = _field(default_factory=dict)   # broker symbol spec
    tick: Optional[Dict[str, float]] = None               # {bid, ask, age_s} or None
    positions: List[Any] = _field(default_factory=list)
    equity: float = 0.0
    origin: str = "arbiter"
    now: Optional[datetime] = None
    check_news: bool = True


def _atr(d: Any) -> float:
    try:
        return float(getattr(getattr(getattr(d, "context", None), "volatility", None), "atr", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _side(d: Any) -> str:
    return str(getattr(d, "bias", "") or "").upper()


def _r_signal_age(c, cfg):
    ts = getattr(c.decision, "timestamp", None)
    if not isinstance(ts, datetime):
        return True, _SIGNAL, None, cfg.max_signal_age_s, "no decision timestamp"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = (c.now - ts).total_seconds()
    return age <= cfg.max_signal_age_s, _SIGNAL, round(age, 1), cfg.max_signal_age_s, "signal age (s)"


def _r_stale_data(c, cfg):
    if not c.tick:
        return True, _RISK, None, cfg.max_tick_age_s, "no live tick (paper/offline)"
    age = float(c.tick.get("age_s", 0.0))
    return age <= cfg.max_tick_age_s, _RISK, round(age, 1), cfg.max_tick_age_s, "tick age (s)"


def _r_price_drift(c, cfg):
    d = c.decision
    if str(getattr(d, "order_type", "MARKET")).upper() == "LIMIT" or not c.tick:
        return True, _SIGNAL, None, None, "limit order or no tick"
    atr = _atr(d)
    if atr <= 0:
        return True, _SIGNAL, None, None, "no ATR to judge drift"
    px = c.tick["ask"] if _side(d) == "BUY" else c.tick["bid"]
    drift = abs(px - float(d.entry_price)) / atr
    return drift <= cfg.max_drift_atr, _SIGNAL, round(drift, 3), cfg.max_drift_atr, "price drift (ATR)"


def _r_geometry(c, cfg):
    d = c.decision
    side, entry, sl, tp = _side(d), float(d.entry_price), float(d.stop_loss), float(d.take_profit or 0.0)
    px = (c.tick["ask"] if side == "BUY" else c.tick["bid"]) if c.tick else entry
    if side not in ("BUY", "SELL") or sl <= 0:
        return False, _RISK, None, None, f"invalid side/stop ({side}, sl={sl})"
    wrong = (sl >= px or (tp > 0 and tp <= px)) if side == "BUY" else (sl <= px or (tp > 0 and tp >= px))
    if wrong:
        return False, _RISK, round(px, 6), None, f"SL/TP on the wrong side of price (sl={sl}, tp={tp})"
    point = float(c.spec.get("point", 0.0) or 0.0)
    min_dist = float(c.spec.get("trade_stops_level", 0) or 0) * point
    if min_dist > 0 and abs(px - sl) < min_dist:
        return False, _RISK, abs(px - sl), min_dist, "stop inside broker stops_level"
    atr = _atr(d)
    if atr > 0:
        sl_atr = abs(entry - sl) / atr
        if not (cfg.min_sl_atr <= sl_atr <= cfg.max_sl_atr):
            return False, _RISK, round(sl_atr, 3), [cfg.min_sl_atr, cfg.max_sl_atr], "stop distance (ATR)"
    return True, _RISK, None, None, "geometry ok"


def _r_sizing(c, cfg):
    from jarvis.config.settings import SETTINGS
    from jarvis.data.symbol_registry import get_dollar_risk_per_price_unit
    d = c.decision
    if c.equity <= 0:
        return False, _RISK, None, None, "account equity unknown"
    dpu = get_dollar_risk_per_price_unit(d.symbol, c.spec or None)
    risk_usd = float(c.lots) * dpu * abs(float(d.entry_price) - float(d.stop_loss))
    pct = float(SETTINGS.risk.max_risk_per_trade_pct)
    vol_min = float(c.spec.get("volume_min", 0.01) or 0.01)
    if float(c.lots) <= vol_min + 1e-9:  # a minimum lot may use the min-lot allowance
        pct = max(pct, float(SETTINGS.risk.min_lot_max_risk_pct))
    budget = c.equity * pct / 100.0 * (1.0 + cfg.sizing_tolerance)
    return risk_usd <= budget, _RISK, round(risk_usd, 2), round(budget, 2), "order risk $ vs budget"


def _same_symbol(c, p) -> bool:
    try:
        return resolve(getattr(p, "symbol", "")).canonical == resolve(c.decision.symbol).canonical
    except Exception:
        return False


def _r_exposure(c, cfg):
    from jarvis.config.settings import SETTINGS
    from jarvis.risk.exposure import HARD_MAX_TRADES_PER_SYMBOL, is_forward_test
    count_ft = SETTINGS.forward_tests.count_toward_symbol_caps
    n = sum(1 for p in c.positions if _same_symbol(c, p) and (count_ft or not is_forward_test(p)))
    return n < HARD_MAX_TRADES_PER_SYMBOL, _RISK, n, HARD_MAX_TRADES_PER_SYMBOL, "open positions on symbol"


def _r_conflict(c, cfg):
    side = _side(c.decision)
    opp = [p for p in c.positions if _same_symbol(c, p) and str(getattr(p, "type", "")).upper() not in ("", side)]
    return not opp, _SIGNAL, len(opp), 0, "open opposite-side positions"


def _r_duplicate(c, cfg):
    key = (resolve(c.decision.symbol).canonical, _side(c.decision), c.origin.split(":", 1)[0])
    with _SENDS_LOCK:
        last = _RECENT_SENDS.get(key)
    if last is None:
        return True, _SIGNAL, None, cfg.conflict_window_s, "no recent same-side send"
    gap = _time.time() - last
    return gap >= cfg.conflict_window_s, _SIGNAL, round(gap, 1), cfg.conflict_window_s, "seconds since same-side send"


def _r_rr(c, cfg):
    if not float(getattr(c.decision, "take_profit", 0.0) or 0.0):
        return True, _SIGNAL, None, None, "no fixed target (runner)"
    a = TradeGuard.rr_assessment(c.decision)
    return a["ok"], _SIGNAL, round(a["rr"], 2), a["floor"], "R:R vs single-source floor"


def _r_mtf(c, cfg):
    vetoes = [v for v in (getattr(c.decision, "dispatch_vetoes", None) or []) if "TIMEFRAME_CONFLICT" in str(v)]
    return not vetoes, _SIGNAL, None, None, (vetoes[0] if vetoes else "no higher-timeframe conflict")


def _r_news(c, cfg):
    if not c.check_news:
        return True, _SIGNAL, None, None, "news check disabled for this caller"
    from jarvis.market.news import is_entry_blackout
    hit = is_entry_blackout(c.decision.symbol, c.now)
    return not hit, _SIGNAL, None, None, "high-impact news window" if hit else "no news window"


#: (name, rule). Risk rules run first so a blown budget still covered the hard checks.
RULES = (
    ("stale_data", _r_stale_data), ("sl_tp_geometry", _r_geometry), ("sizing_budget", _r_sizing),
    ("exposure", _r_exposure), ("signal_age", _r_signal_age), ("price_drift", _r_price_drift),
    ("rr_floor", _r_rr), ("mtf_alignment", _r_mtf), ("conflict", _r_conflict),
    ("duplicate", _r_duplicate), ("news_window", _r_news),
)


def verify_pre_send(ctx: PreSendContext, cfg: Any = None) -> Dict[str, Any]:
    """Run every rule; outcome APPROVED | REJECTED | BLOCKED_RISK (fail closed).

    REJECTED = a signal-quality rule failed; BLOCKED_RISK = a risk rule failed, the
    verifier raised, or the time budget was exceeded.
    """
    if cfg is None:
        from jarvis.config.settings import SETTINGS
        cfg = SETTINGS.verifier
    t0 = _time.perf_counter()
    ctx.now = ctx.now or datetime.now(timezone.utc)
    reasons: List[Dict[str, Any]] = []
    outcome = APPROVED
    try:
        for name, rule in RULES:
            ok, severity, value, threshold, detail = rule(ctx, cfg)
            reasons.append({"rule": name, "ok": bool(ok), "value": value, "threshold": threshold, "detail": detail})
            if not ok:
                outcome = BLOCKED_RISK if severity == _RISK else (outcome if outcome == BLOCKED_RISK else REJECTED)
            if (_time.perf_counter() - t0) * 1000.0 > cfg.budget_ms:
                reasons.append({"rule": "time_budget", "ok": False, "value": None,
                                "threshold": cfg.budget_ms, "detail": f"budget exceeded after {name}"})
                outcome = BLOCKED_RISK
                break
    except Exception as exc:  # fail closed
        reasons.append({"rule": "verifier_error", "ok": False, "value": None, "threshold": None,
                        "detail": f"{type(exc).__name__}: {exc}"})
        outcome = BLOCKED_RISK
    return {"outcome": outcome, "reasons": reasons,
            "ms": round((_time.perf_counter() - t0) * 1000.0, 2), "mode": getattr(cfg, "mode", "shadow")}


from collections import deque as _deque

#: Last verifier results (newest last) for /api/verifier/recent and the watchdog.
VERIFICATIONS = _deque(maxlen=1000)
