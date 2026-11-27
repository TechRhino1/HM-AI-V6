"""
HM Algo 2.0 — Canonical Exit Policy.

SINGLE SOURCE OF TRUTH for every trade-exit decision in the system.

WHY THIS MODULE EXISTS
----------------------
Historically the exit rules were re-implemented in at least three places with
divergent constants and semantics:

  * ``jarvis/backtesting/engine.py``      -> be_trigger_r, fast_cash_r, runner_trail_atr
  * ``jarvis/execution/position_monitor.py`` -> STAGE1/2/3 + STD ATR triggers
  * ``jarvis/execution/order_manager.py``    -> its own duplicate of the same stages

Because they drifted apart, the backtest could never reproduce live behaviour, and
parameters computed upstream (e.g. ``runner_trail_distance_atr`` from the entry
engine) were written into the trade plan but never read by the exit logic.

This module centralises the arithmetic. Both the backtester and the live position
monitor import :func:`evaluate_exit` and therefore cannot disagree.

DESIGN CONTRACT
---------------
``evaluate_exit`` is a *pure* function: given the current trade state and the
observed bar/price, it returns the new stop-loss and (optionally) a partial-close
instruction. It performs no I/O and mutates nothing, which makes it trivially
testable and safe to call from either an event loop or a live monitoring thread.

All thresholds are expressed in R-multiples (multiples of the initial risk
distance ``|entry - initial_sl|``) because R is the only scale-free unit that is
comparable across gold, FX, indices and crypto. ATR is used solely for the
*trailing distance*, where a volatility-relative width is genuinely desirable.

UNIT DISCIPLINE
---------------
``risk_dist`` is a PRICE DISTANCE, not pips. Any function receiving ``profit_dist``
must receive a price distance too. Mixing these was the source of a prior defect
where an ATR multiple was compared against a pip count.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Fallback defaults — used only when a symbol profile cannot be resolved.
# Phase 2: Adjusted for better expectancy - earlier trailing, higher TP targets
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_BE_TRIGGER_R = 2.0        # move SL to entry only after +2R
DEFAULT_FAST_CASH_R = 0.75        # bank the first partial at +0.75R
DEFAULT_FAST_CASH_VOLUME_PCT = 0.50
DEFAULT_BE_BUFFER_PCT = 0.05      # buffer above/below entry when locking BE
DEFAULT_RUNNER_TRAIL_ATR = 1.0    # trail width in ATR once running (Phase 2: tightened from 1.2)
DEFAULT_TRAIL_ACTIVATION_R = 1.0  # only start trailing beyond +1R (Phase 2: lowered from 2.0)

# Time stop (2026-10-20 ledger audit): half of all demo trades rode to a full
# -1.00R stop (median R) because nothing ever freed a trade that neither ran
# nor died. Institutional gold systems flatten dead trades at session end
# (WAKE) and " losers take hours, winners take days " is the classic shape of
# a lopsided book. The ceiling is expressed per asset class because index
# swings are naturally slower than gold's intraday pulse.
DEFAULT_TIME_STOP_MIN_R = 0.10    # a trade must be at least +0.10R to earn its age
DEFAULT_TIME_STOP_MINUTES = 120.0



# ── Resolved Policy In-Memory Memoization Cache ──────────────────────────────
# (symbol, trade_style, regime, digits) -> ExitPolicy for O(1) zero-alloc lookups.
_RESOLVED_POLICY_CACHE: dict = {}

@dataclass
class ExitPolicy:
    """Resolved, symbol-specific exit parameters expressed in R-multiples."""

    symbol: str = "UNKNOWN"
    trade_style: str = "SWING"
    be_trigger_r: float = DEFAULT_BE_TRIGGER_R
    fast_cash_r: float = DEFAULT_FAST_CASH_R
    fast_cash_volume_pct: float = DEFAULT_FAST_CASH_VOLUME_PCT
    be_buffer_pct: float = DEFAULT_BE_BUFFER_PCT
    runner_trail_atr: float = DEFAULT_RUNNER_TRAIL_ATR
    trail_activation_r: float = DEFAULT_TRAIL_ACTIVATION_R
    tp2_r: float = 2.0
    tp3_r: float = 3.5
    # Milestone ratchets: (favorable R threshold, R level to lock in)
    milestones: List[tuple] = field(
        default_factory=lambda: [(1.0, -0.35), (1.5, 0.25), (2.0, 0.60), (2.8, 1.25), (3.8, 2.25), (5.0, 3.50)]
    )
    # Bridge protection (DISABLED Phase 2): was capping winners at -0.25R
    # The bridge protection capped winners by locking SL at -0.25R after a +0.6R peak
    # retracted 0.45R. This prematurely capped winners that could have run 5-10R.
    # Disabled by setting activation threshold beyond practical reach.
    peak_bridge_activate_r: float = 100.0  # Disabled - never activates
    peak_bridge_retrace_r: float = 100.0   # Disabled
    peak_bridge_lock_r: float = -0.25
    # Time stop: a trade that has been alive longer than time_stop_minutes and
    # still sits below time_stop_min_r is flattened outright (a close decision,
    # not a stop move). 0 disables. See DEFAULT_* above for the audit basis.
    time_stop_minutes: float = DEFAULT_TIME_STOP_MINUTES
    time_stop_min_r: float = DEFAULT_TIME_STOP_MIN_R
    digits: int = 5
    pip_size: float = 0.0001
    # False for fixed-target symbols: skips the short-target breakeven and the
    # progress-to-TP ratchets, which apply regardless of the R levels above.
    profit_locks: bool = True
    # "legacy": the ratchet stack below. "institutional": stop untouched until +be_at_r, then
    # breakeven + buffer, a chandelier (best price since entry - k x ATR, LeBeau) and a swing
    # (structure) trail, whichever is tighter; no partials, milestones or progress locks.
    trail_mode: str = "legacy"
    chandelier_atr_mult: float = 3.0
    be_at_r: float = 1.0
    # Institutional lock (trading.exit_mode="institutional_lock", measured on 173 live trades
    # 2026-11-24): at +be_at_r bank lock_partial_pct when the position can be split (floor then
    # breakeven), else floor the stop at +lock_floor_r; then trail trail_r R behind the peak.
    # None = the plain institutional trail above.
    lock_floor_r: Optional[float] = None
    trail_r: Optional[float] = None
    lock_partial_pct: float = 0.0
    # Exit-audit variants (2026-11-27, EXIT_VARIANTS): a breakeven stop once the peak reaches
    # early_protect_r (< be_at_r), and a give-back that shrinks with the peak: trail_ladder =
    # ((peak_r, trail_r), ...) - the tightest rung reached applies. None = the measured lock.
    early_protect_r: Optional[float] = None
    trail_ladder: Optional[tuple] = None

    # ── Construction ────────────────────────────────────────────────────────
    @classmethod
    def for_symbol(cls, symbol: str, spec: Any = None, trade_style: str = "SWING",
                   regime: Optional[str] = None) -> "ExitPolicy":
        """The resolved policy, switched to the institutional lock when trading.exit_mode asks
        for it (live only: offline backtests and research keep the policy they calibrated)."""
        pol = cls._resolve(symbol, spec, trade_style, regime)
        try:
            from jarvis.config.runtime import backtest_exit_mode, is_offline
            from jarvis.config.settings import SETTINGS
            from jarvis.data.symbol_registry import resolve
            canon = str(getattr(resolve(symbol), "canonical", symbol) or symbol).upper()
            hold_set = {str(s).upper() for s in (getattr(SETTINGS.trading, "exit_hold_symbols", None) or [])}
            in_hold = canon in hold_set or str(symbol).upper() in hold_set
            if is_offline():
                # A backtest replays the live exit only when asked (JARVIS_BACKTEST_EXIT_MODE), so
                # the evidence the deployment gate reads is measured on the policy that trades.
                mode = backtest_exit_mode()
                if mode == "live":
                    return apply_exit_mode(pol, live_exit_mode(symbol, trade_style))
                return apply_exit_mode(pol, mode, hold=in_hold) if mode else pol
            return apply_exit_mode(pol, live_exit_mode(symbol, trade_style))
        except Exception:
            pass
        return pol

    @classmethod
    def _resolve(
        cls,
        symbol: str,
        spec: Any = None,
        trade_style: str = "SWING",
        regime: Optional[str] = None
    ) -> "ExitPolicy":
        """Build a dynamic, symbol-specific, style-specific, and regime-adaptive policy.

        Caches resolved policies for O(1) zero-alloc performance in the monitoring loop.
        Falls back to conservative defaults when the profile is unavailable.
        """
        digits = int(getattr(spec, "digits", 5) or 5)
        pip_size = float(getattr(spec, "pip_size", 0.0001) or 0.0001)
        sym_str = str(symbol or "UNKNOWN").upper().strip()
        style_str = str(trade_style or "SWING").upper().strip()
        reg_key = str(regime or "NORMAL").upper().strip()

        # The profile's fixed target switches the whole exit mode, so it is part of the key: a policy
        # cached under one fixed_target_r was otherwise served after the profile changed (a stale
        # entry written by a concurrent monitor thread outlived a test fixture's cache clear).
        try:
            from jarvis.intelligence.symbol_profile_config import get_symbol_profile_config as _gspc
            _fixed_key = getattr(_gspc(symbol), "fixed_target_r", None)
        except Exception:
            _fixed_key = None
        cache_key = (sym_str, style_str, reg_key, digits, _fixed_key)
        if cache_key in _RESOLVED_POLICY_CACHE:
            return _RESOLVED_POLICY_CACHE[cache_key]

        # Calibrated symbols exit on the geometry their out-of-sample expectancy was
        # measured with (same helper the BacktestEngine uses), not the style profile.
        from jarvis.backtesting.exit_geometry import live_exit_geometry
        _geom = live_exit_geometry(symbol)
        if _geom is not None:
            pol = _geom.to_policy(symbol, spec)
            pol.trade_style = style_str
            pol.time_stop_minutes = float(_geom.max_bars) * 60.0  # max_bars is H1-calibrated
            _RESOLVED_POLICY_CACHE[cache_key] = pol
            return pol

        try:
            from jarvis.intelligence.symbol_profile_config import get_style_profile, get_symbol_profile_config

            cfg = get_symbol_profile_config(symbol)
            sp = get_style_profile(symbol, trade_style)

            be_trig = float(sp.be_trigger_r)
            fast_cash_r = float(sp.fast_cash_r)
            fast_cash_vol = float(sp.fast_cash_volume_pct)
            runner_trail = float(sp.runner_trail_atr)
            trail_act = float(sp.trail_activation_r)
            time_stop_min = float(sp.time_stop_minutes)
            milestones = list(sp.milestones) if sp.milestones else [(1.0, -0.35), (1.5, 0.25), (2.0, 0.60), (2.8, 1.25), (3.8, 2.25), (5.0, 3.50)]

            # Apply Regime-Adaptive Modulators
            is_ranging = any(k in reg_key for k in ("RANGE", "CONSOLIDATION", "COMPRESSION", "CHOP"))
            is_trending = any(k in reg_key for k in ("TREND", "EXPANSION", "MOMENTUM"))
            is_extreme = any(k in reg_key for k in ("EXTREME", "HIGH_VOLATILITY", "SHOCK"))

            if is_ranging:
                # In range/compression: bank early before range boundary bounce, advance BE, tighten trail
                # Preserve full style time_stop_minutes so slow consolidation has time to resolve.
                fast_cash_r = min(fast_cash_r, 1.00)
                fast_cash_vol = max(fast_cash_vol, 0.50)
                be_trig = min(be_trig, 1.15)
                runner_trail = min(runner_trail, 1.00)
                trail_act = min(trail_act, 1.30)
            elif is_trending:
                # In trending: expand runner trail breathing room, defer partial to let runners ride
                runner_trail = runner_trail * 1.15
                if "SCALP" not in sp.trade_style:
                    fast_cash_vol = min(fast_cash_vol, 0.33)
            elif is_extreme:
                # High volatility: tighten fast-cash profit lock once in money
                fast_cash_r = min(fast_cash_r, 1.10)

            fixed_target = getattr(cfg, "fixed_target_r", None)
            if fixed_target:
                # Run to the fixed target or the stop; only the style's own time stop
                # remains. It was forced to 120 min for every style, which cut a
                # 2.5R SWING/H4/D1 gold trade off two hours after entry.
                be_trig = fast_cash_r = trail_act = 1e9
                milestones = []

            pol = cls(
                symbol=str(symbol),
                trade_style=sp.trade_style,
                be_trigger_r=be_trig,
                fast_cash_r=fast_cash_r,
                fast_cash_volume_pct=fast_cash_vol,
                be_buffer_pct=float(getattr(cfg, "be_buffer_pct", DEFAULT_BE_BUFFER_PCT)),
                runner_trail_atr=runner_trail,
                trail_activation_r=trail_act,
                tp2_r=float(getattr(sp, "min_target_rr", 2.0) or 2.0),
                tp3_r=float(getattr(sp, "asym_rr", 3.5) or 3.5),
                milestones=milestones,
                time_stop_minutes=time_stop_min,
                digits=int(getattr(cfg, "digits", digits) or digits),
                pip_size=float(getattr(cfg, "pip_size", pip_size) or pip_size),
                profit_locks=not fixed_target,
            )
            _RESOLVED_POLICY_CACHE[cache_key] = pol
            return pol
        except Exception:
            fallback_pol = cls(symbol=str(symbol), trade_style=trade_style, digits=digits, pip_size=pip_size)
            _RESOLVED_POLICY_CACHE[cache_key] = fallback_pol
            return fallback_pol

    def buffer_distance(self, risk_dist: float) -> float:
        """Breakeven buffer as a price distance, floored to cover spread noise."""
        return max(self.pip_size * 2.5, abs(risk_dist) * self.be_buffer_pct)


@dataclass
class ExitDecision:
    """Result of evaluating an exit policy against the current market state."""

    new_sl: float = 0.0
    partial_close_pct: float = 0.0
    partial_price: float = 0.0
    be_locked: bool = False
    trail_active: bool = False
    close_position: bool = False
    close_reason: str = ""
    close_volume: Optional[float] = None
    actions: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.close_position or self.partial_close_pct > 0.0 or bool(self.actions)

    @property
    def should_close(self) -> bool:
        """True when a full discretionary market exit is signalled."""
        return self.close_position

    @property
    def partial_due(self) -> bool:
        """True when a partial scale-out is signalled but not yet executed."""
        return self.partial_close_pct > 0.0


def evaluate_exit(
    *,
    side: str,
    entry: float,
    initial_sl: float,
    current_sl: float,
    tp: float,
    price: float,
    favorable_dist: float,
    atr: float,
    policy: ExitPolicy,
    partial_already_taken: bool = False,
    be_already_locked: bool = False,
    struct_level: Optional[float] = None,
    regime: Optional[str] = None,
    partial_executable: bool = True,
    hold_minutes: Optional[float] = None,
    peak_favorable_dist: Optional[float] = None,
) -> ExitDecision:
    """Compute the stop-loss / partial-profit action for an open trade.

    Parameters
    ----------
    side : "BUY" or "SELL"
    entry, initial_sl : the ORIGINAL entry and stop, which define 1R.
    current_sl : the stop currently resting on the position.
    price : the current (exit-side) price used for trailing arithmetic.
    favorable_dist : best favourable excursion so far, in PRICE units.
    atr : current ATR in PRICE units (used for trail width only).
    struct_level : optional structural support (BUY) / resistance (SELL) to ratchet behind.
    partial_executable : False when the position cannot actually be split into
        two tradeable lots (micro accounts at the 0.01 floor). The fast-cash
        step then degrades into a hard stop-lock at the same level instead of a
        close, so the profit is still ratcheted and can never round-trip away.
    hold_minutes : position age in minutes, when the caller knows it. Powers
        the time stop; None leaves the age check inert.

    Returns
    -------
    ExitDecision with the new stop and any partial-close instruction.
    """
    dec = ExitDecision(new_sl=current_sl)
    is_buy = str(side).upper().startswith("BUY")

    # 1R is the absolute distance from entry to the ORIGINAL stop. If that is
    # degenerate we cannot reason in R at all, so leave the position untouched
    # rather than manufacturing a spurious stop.
    risk_dist = abs(entry - initial_sl)
    if risk_dist <= 1e-6:
        if atr > 0:
            risk_dist = atr * 1.5
        else:
            return dec
    if not (price > 0):
        return dec

    r_multiple = favorable_dist / risk_dist
    # Current excursion in R (negative when the trade is under water). The time
    # stop used to test `r_multiple < 0`, but `favorable_dist` is a best-effort
    # maximum and can never be negative, so the check was unreachable.
    signed_move = (price - entry) if is_buy else (entry - price)
    current_r = signed_move / max(risk_dist, 1e-6)
    buffer_dist = policy.buffer_distance(risk_dist)
    digits = policy.digits

    # Safe Relative Progress-to-TP Calculation (SKILL.md §8 & §11, Issue 2 Guard)
    progress_tp = 0.0
    target_r = 0.0
    tp_dist = 0.0
    if tp is not None and tp > 0:
        signed_tp_dist = (tp - entry) if is_buy else (entry - tp)
        if signed_tp_dist > 1e-7:
            tp_dist = signed_tp_dist
            progress_tp = max(0.0, favorable_dist / signed_tp_dist)
            target_r = signed_tp_dist / max(risk_dist, 1e-6)

    # ── 0. Time stop: retire a trade that is dead, not just unlucky ─────────
    # The 2026-10-20 audit measured the median closed trade at exactly -1.00R:
    # half the book was never managed out of a trade that neither ran nor
    # stopped quickly. Once the position has outlived its expectation window
    # and cannot even book the nominal floor (+0.10R), holding it has no edge
    # thesis left — close it and recycle the risk budget. Skipped once a
    # partial has banked (de-risked runner may idle) and skipped while the
    # trailing regime is active (trade is managing itself).
    # Protect trades that already demonstrated live edge (peak >= +0.15R) or sit at/above
    # the trail/BE lock from getting flattened on a brief consolidation tick.
    _peak_r = (
        float(peak_favorable_dist) / max(risk_dist, 1e-6)
        if peak_favorable_dist is not None
        else r_multiple
    )
    if (
        policy.time_stop_minutes > 0
        and hold_minutes is not None
        and hold_minutes >= policy.time_stop_minutes
        and not partial_already_taken
        and not be_already_locked
        and r_multiple < policy.trail_activation_r
        and current_r < max(0.0, policy.time_stop_min_r)  # dead, not merely unlucky
        and _peak_r < max(0.15, policy.time_stop_min_r + 0.05)
    ):
        dec.close_position = True
        dec.close_reason = (
            f"TIME_STOP_{hold_minutes:.0f}min_{current_r:+.2f}R"
            f"_{policy.time_stop_minutes:.0f}min_limit"
        )
        dec.actions.append("TIME_STOP")
        return dec

    if policy.trail_mode == "institutional":
        return _institutional_trail(dec, is_buy, entry, current_sl, price, risk_dist, _peak_r * risk_dist,
                                    atr, struct_level, buffer_dist, policy,
                                    partial_already_taken=partial_already_taken,
                                    partial_executable=partial_executable)

    # ── 1. Partial profit banking (risk reduction) ──────────────────────────
    # Take a partial BEFORE moving to breakeven so the position is de-risked
    # while still giving the remainder room to run.
    #
    # Micro-account fallback (2026-10-20): a 0.01-lot position cannot be split
    # (the broker floor is 0.01 and nothing remains to trail), so live trades
    # at the bottom lot always executed the "bridge" all-or-nothing book
    # measured as 208 stop-out exits vs 52 TP exits with a median -1.00R and
    # winners capped at +0.5R. When a partial is impossible, RATCHET the stop
    # to (fast_cash_r - BE buffer) instead: the position becomes a free
    # option — it can never round-trip into a loss once it has reached the
    # fast-cash level, while the runner keeps all upside. This is the defence
    # of the same book the institutional research recommends (partial at a
    # level with a trailed remainder), executed with the tools a micro
    # account actually has.
    if not partial_already_taken and r_multiple >= policy.fast_cash_r:
        if partial_executable:
            dec.partial_close_pct = policy.fast_cash_volume_pct
            dec.partial_price = entry + (risk_dist * policy.fast_cash_r) * (1 if is_buy else -1)
            dec.partial_price = round(dec.partial_price, digits)
            dec.actions.append(f"PARTIAL_{policy.fast_cash_r:.2f}R")
        else:
            raw_lock = risk_dist * policy.fast_cash_r - buffer_dist
            if raw_lock > 0:
                lock_price = round(entry + (raw_lock if is_buy else -raw_lock), digits)
                if is_buy:
                    if lock_price > dec.new_sl:
                        dec.new_sl = lock_price
                        dec.actions.append(f"PARTIAL_FALLBACK_LOCK_{policy.fast_cash_r:.2f}R")
                else:
                    if dec.new_sl == 0 or lock_price < dec.new_sl:
                        dec.new_sl = lock_price
                        dec.actions.append(f"PARTIAL_FALLBACK_LOCK_{policy.fast_cash_r:.2f}R")

    # ── 2. Breakeven lock ───────────────────────────────────────────────────
    # Deferred until the trade has proven itself. Locking at 1R was the primary
    # cause of +20R winners being closed at +0.9R.
    #
    # Breakeven lock triggers when dedicated be_trigger_r is reached, OR on >= 50%
    # progress toward TP for scalps / sub-1.65R structural targets with >= +0.45R excursion.
    is_short_horizon_target = 0.0 < target_r <= 1.65
    be_by_tp = policy.profit_locks and (is_short_horizon_target and progress_tp >= 0.50 and r_multiple >= 0.45)
    be_triggered = be_already_locked or (r_multiple >= policy.be_trigger_r) or be_by_tp
    if not be_already_locked:
        if r_multiple >= policy.be_trigger_r:
            dec.actions.append(f"BE_LOCK_{policy.be_trigger_r:.2f}R")
        elif be_by_tp:
            dec.actions.append(f"BE_LOCK_50%TP({int(progress_tp*100)}%)")

    if be_triggered:
        dec.be_locked = True
        floor = round(entry + buffer_dist, digits) if is_buy else round(entry - buffer_dist, digits)
        # A locked breakeven must never loosen an already-better stop.
        if is_buy and floor > dec.new_sl:
            dec.new_sl = floor
        elif (not is_buy) and (dec.new_sl == 0 or floor < dec.new_sl):
            dec.new_sl = floor

    # ── 3. Milestone ratchet (progressive profit locking) ───────────────────
    for threshold_r, lock_r in policy.milestones:
        if r_multiple >= threshold_r:
            lock_price = round(
                entry + (risk_dist * lock_r) * (1 if is_buy else -1), digits
            )
            if is_buy and lock_price > dec.new_sl:
                dec.new_sl = lock_price
                dec.actions.append(f"MILESTONE_{lock_r:.1f}R")
            elif (not is_buy) and (dec.new_sl == 0 or lock_price < dec.new_sl):
                dec.new_sl = lock_price
                dec.actions.append(f"MILESTONE_{lock_r:.1f}R")

    # ── 3.6 Bridge protection (2026-10-21 master evaluation) ────────────────
    # Arms only when the trade is actively giving back its peak (retrace >=
    # peak_bridge_retrace_r): a runner sitting at its peak is untouched, so
    # no premature ratchet can occur. The cap locks the fixed peak_bridge_lock_r
    # level (a small controlled LOSS below entry) — it never locks profit, so
    # it cannot choke a future runner, and the one-way invariant in stage 6
    # keeps every ratchet already in place.
    peak_dist_raw = favorable_dist
    if peak_favorable_dist is not None:
        peak_dist_raw = max(0.0, float(peak_favorable_dist))
    peak_excursion_r = peak_dist_raw / risk_dist
    current_excursion_r = favorable_dist / risk_dist
    retrace_r = peak_excursion_r - current_excursion_r
    cap_dist = risk_dist * policy.peak_bridge_lock_r
    cap_price = round(entry + (cap_dist if is_buy else -cap_dist), digits)
    cap_improves = (cap_price > dec.new_sl) if is_buy else (dec.new_sl == 0 or cap_price < dec.new_sl)
    if (
        peak_excursion_r >= policy.peak_bridge_activate_r
        and retrace_r >= policy.peak_bridge_retrace_r
        and cap_improves
    ):
        dec.new_sl = cap_price
        dec.actions.append(f"BRIDGE_CAP_{policy.peak_bridge_lock_r:.2f}R")

    # ── 3.5 Progress-to-TP Ratchets (Institutional Target Proximity Protection) ─
    # Institutional rule (SKILL.md §8): Never let a trade reaching >= 65-80% of
    # its target turn into a loss, even on sub-1.5R scalps or structural fades.
    if policy.profit_locks and tp_dist > 1e-6 and progress_tp >= 0.65:
        progress_milestones = [(0.65, 0.25), (0.80, 0.55), (0.90, 0.75), (0.94, 0.82)]
        for prog_thresh, lock_pct in progress_milestones:
            if progress_tp >= prog_thresh:
                lock_dist = tp_dist * lock_pct
                raw_lock = round(entry + (lock_dist if is_buy else -lock_dist), digits)
                if is_buy:
                    clamped_lock = min(raw_lock, round(price - buffer_dist, digits)) if price > 0 else raw_lock
                    if clamped_lock > dec.new_sl and clamped_lock > entry:
                        dec.new_sl = clamped_lock
                        dec.actions.append(f"PROGRESS_LOCK_{int(prog_thresh*100)}%TP")
                else:
                    clamped_lock = max(raw_lock, round(price + buffer_dist, digits)) if price > 0 else raw_lock
                    if (dec.new_sl == 0 or clamped_lock < dec.new_sl) and clamped_lock < entry:
                        dec.new_sl = clamped_lock
                        dec.actions.append(f"PROGRESS_LOCK_{int(prog_thresh*100)}%TP")

    # ── 4. ATR runner trail ─────────────────────────────────────────────────
    # Engages only beyond the activation threshold, and the width must be TIGHTER
    # than the initial stop or the trail sits behind the stop and never ratchets.
    if r_multiple >= policy.trail_activation_r and atr > 0:
        dec.trail_active = True
        is_ranging = bool(regime and any(k in str(regime).upper() for k in ("RANGE", "CONSOLIDATION", "COMPRESSION", "CHOP")))
        if is_ranging:
            # Under ranging/choppy conditions, clamp trailing distance tighter so gains aren't given back at range boundaries
            effective_mult = min(policy.runner_trail_atr, 1.20)
        else:
            # Respect symbol-specific profile configuration (Gold 2.60, BTC 2.20, Indices 2.60)
            # Only tighten down if deep in windfall profit (>= 3.0R) to bank gains against massive swings
            effective_mult = min(policy.runner_trail_atr, 1.80) if r_multiple >= 3.00 else policy.runner_trail_atr
        raw_trail_dist = atr * effective_mult
        # Cap trail distance so it cannot lag behind entry on high-ATR instruments (e.g. Gold where runner_trail_atr=2.6)
        trail_dist = min(raw_trail_dist, max(risk_dist * 1.5, atr * 0.8))
        trail_sl = round(price - trail_dist, digits) if is_buy else round(price + trail_dist, digits)

        if is_buy:
            # Only trail once it is above entry, otherwise it cannot lock profit.
            if trail_sl > entry and trail_sl > dec.new_sl and trail_sl < price:
                dec.new_sl = trail_sl
                dec.actions.append(f"TRAIL_ATR_{effective_mult:.2f}")
        else:
            if trail_sl < entry and (dec.new_sl == 0 or trail_sl < dec.new_sl) and trail_sl > price:
                dec.new_sl = trail_sl
                dec.actions.append(f"TRAIL_ATR_{effective_mult:.2f}")

    # ── 5. Structural ratchet ───────────────────────────────────────────────
    # MUST be gated (>= 1.50R) to prevent suffocating trades in entry noise/spread!
    if r_multiple >= 1.50 and struct_level and struct_level > 0 and atr > 0:
        min_buffer = max(atr * 0.60, policy.buffer_distance(risk_dist))
        struct_sl = (
            round(struct_level - min_buffer, digits) if is_buy
            else round(struct_level + min_buffer, digits)
        )
        if is_buy and struct_sl > dec.new_sl and struct_sl < price:
            dec.new_sl = struct_sl
            dec.actions.append("SR_RATCHET")
        elif (not is_buy) and (dec.new_sl == 0 or struct_sl < dec.new_sl) and struct_sl > price:
            dec.new_sl = struct_sl
            dec.actions.append("SR_RATCHET")

    # ── 6. Cross-cutting invariants ─────────────────────────────────────────
    # A stop must never cross the current price (the broker would reject it) and
    # must never move backwards (ratchets are one-way by definition).
    min_dist_guard = max(policy.pip_size * 2.0, 1e-5)
    if is_buy:
        if dec.new_sl >= price - min_dist_guard:
            dec.new_sl = round(price - min_dist_guard, digits)
        if dec.new_sl < current_sl:
            dec.new_sl = current_sl
    else:
        if dec.new_sl > 0 and dec.new_sl <= price + min_dist_guard:
            dec.new_sl = round(price + min_dist_guard, digits)
        if current_sl > 0 and dec.new_sl > current_sl:
            dec.new_sl = current_sl

    return dec


def struct_level_for(side: str, entry: float, st: Any) -> Optional[float]:
    """The structural ratchet reference live and backtest both use: for a BUY the highest of the
    swing low / demand-zone low above entry while higher lows hold; mirrored for a SELL."""
    try:
        if st is None:
            return None
        if str(side).upper() == "BUY" and getattr(st, "higher_lows", False):
            sw = float(getattr(st, "swing_low", 0.0) or 0.0)
            dz = float(st.demand_zone[0]) if getattr(st, "demand_zone", None) else 0.0
            c = [x for x in (sw, dz) if x > entry]
            return max(c) if c else None
        if str(side).upper() == "SELL" and getattr(st, "lower_highs", False):
            sw = float(getattr(st, "swing_high", 0.0) or 0.0)
            sz = float(st.supply_zone[1]) if getattr(st, "supply_zone", None) else 0.0
            c = [x for x in (sw, sz) if 0 < x < entry]
            return min(c) if c else None
    except Exception:
        pass
    return None


def _institutional_trail(dec, is_buy, entry, current_sl, price, risk_dist, peak_dist, atr,
                         struct_level, buffer_dist, policy, partial_already_taken=False,
                         partial_executable=False) -> ExitDecision:
    """Initial stop until +be_at_r; then the tightest of breakeven+buffer, the chandelier
    (best price since entry - k x ATR) and the last swing beyond entry - 0.25 ATR. One-way.
    With lock_floor_r/trail_r set (the institutional lock) the candidates are only breakeven,
    the floor and the R trail - the rule that was measured - plus the partial when splittable.
    early_protect_r moves the stop to breakeven+buffer from that peak; trail_ladder narrows trail_r."""
    sgn = 1 if is_buy else -1
    guard = max(policy.pip_size * 2.0, 1e-5)
    if peak_dist < policy.be_at_r * risk_dist:
        ep = policy.early_protect_r
        if ep is not None and risk_dist > 0 and peak_dist >= ep * risk_dist:
            level = round(entry + sgn * buffer_dist, policy.digits)
            if sgn * (price - level) > guard and (dec.new_sl == 0 or sgn * (level - dec.new_sl) > 0):
                dec.new_sl = level
                dec.actions.append(f"EARLY_BE_{ep:.1f}R@{level}")
                dec.be_locked = True
        return dec
    cands = [(entry + sgn * buffer_dist, "BE_1R")]
    if policy.lock_floor_r is not None or policy.trail_r is not None:
        split = policy.lock_partial_pct > 0 and partial_executable
        if split and not partial_already_taken:
            dec.partial_close_pct = policy.lock_partial_pct
            dec.partial_price = round(entry + sgn * risk_dist * policy.be_at_r, policy.digits)
            dec.actions.append(f"LOCK_PARTIAL_{policy.lock_partial_pct:.0%}@{policy.be_at_r:.1f}R")
        if policy.lock_floor_r is not None and not (split or partial_already_taken):
            cands.append((entry + sgn * max(policy.lock_floor_r * risk_dist, buffer_dist),
                          f"LOCK_{policy.lock_floor_r:.1f}R"))
        if policy.trail_r is not None:
            trail = policy.trail_r
            peak_r = peak_dist / risk_dist if risk_dist > 0 else 0.0
            for at_r, tr in (policy.trail_ladder or ()):
                if peak_r >= at_r:
                    trail = min(trail, tr)
            cands.append((entry + sgn * (peak_dist - trail * risk_dist), f"R_TRAIL_{trail:.1f}R"))
    elif atr > 0:
        cands.append((entry + sgn * (peak_dist - policy.chandelier_atr_mult * atr),
                      f"CHANDELIER_{policy.chandelier_atr_mult:.1f}ATR"))
        if struct_level and sgn * (struct_level - entry) > 0:
            cands.append((struct_level - sgn * 0.25 * atr, "STRUCT_TRAIL"))
    for level, tag in cands:
        level = round(level, policy.digits)
        if sgn * (price - level) <= guard:                 # never at or through the market
            continue
        if dec.new_sl == 0 or sgn * (level - dec.new_sl) > 0:
            dec.new_sl = level
            dec.actions.append(f"{tag}@{level}")
    dec.be_locked = sgn * (dec.new_sl - entry) >= 0
    dec.trail_active = True
    return dec


# Pre-registered 2026-11-27 (exit audit), fixed before any run - one hypothesis each, no grid:
#   early_protect: trades that peak at 0.5-1.0R and still lose -1R (holdout: -341R over 471 trades)
#                  get a breakeven stop from a 0.6R peak.
#   ratchet:       winners give back ~0.8R from the peak; the 0.7R trail narrows to 0.5R from a
#                  1.5R peak and 0.4R from 2.5R.
# All are never looser than the lock, so a live shadow of them always completes (E5).
EXIT_VARIANTS = {
    "early_protect": {"early_protect_r": 0.6},
    "ratchet": {"trail_ladder": ((1.5, 0.5), (2.5, 0.4))},
    "early_ratchet": {"early_protect_r": 0.6, "trail_ladder": ((1.5, 0.5), (2.5, 0.4))},
}
_STYLE_ALIASES = {"DAY": "DAY_TRADING", "INTRADAY": "DAY_TRADING"}


def apply_exit_mode(pol: "ExitPolicy", mode: Optional[str], hold: bool = False) -> "ExitPolicy":
    """`pol` switched to exit `mode` (runtime.EXIT_MODES); legacy/unknown/None keep `pol`."""
    import dataclasses
    mode = str(mode or "").lower()
    if mode == "institutional_lock":
        return institutional_lock(pol, hold=hold)
    if mode == "hold":
        return institutional_lock(pol, hold=True)
    if mode == "chandelier":
        return dataclasses.replace(pol, trail_mode="institutional", be_at_r=1.0, profit_locks=False,
                                   lock_floor_r=None, trail_r=None, lock_partial_pct=0.0)
    if mode in EXIT_VARIANTS:
        return dataclasses.replace(institutional_lock(pol), **EXIT_VARIANTS[mode])
    return pol


_CELLS_CHECKED = [0.0]   # monotonic time of the last settings.json stat (one per second, not per lookup)


def live_exit_mode(symbol: str, trade_style: str) -> str:
    """The exit mode live trading uses for `symbol` x `trade_style`: trading.exit_cells
    "SYMBOL|STYLE", then "ASSETCLASS|STYLE", then "hold" for trading.exit_hold_symbols when the
    lock is on, else trading.exit_mode. With no exit_cells this is exactly the pre-2026-11-27 rule."""
    from jarvis.config.settings import SETTINGS, reload_deployment_overrides
    from jarvis.data.symbol_registry import resolve
    import time as _time
    if _time.monotonic() - _CELLS_CHECKED[0] >= 1.0:   # an approved exit_cells edit applies within ~1 s
        _CELLS_CHECKED[0] = _time.monotonic()
        reload_deployment_overrides()
    spec = resolve(symbol)
    canon = str(getattr(spec, "canonical", symbol) or symbol).upper()
    st = _STYLE_ALIASES.get(str(trade_style or "").upper(), str(trade_style or "").upper())
    cells = {str(k).upper(): str(v).lower() for k, v in (getattr(SETTINGS.trading, "exit_cells", None) or {}).items()}
    for key in (f"{canon}|{st}", f"{str(getattr(spec, 'asset_class', '') or '').upper()}|{st}"):
        if key in cells:
            return cells[key]
    mode = str(getattr(SETTINGS.trading, "exit_mode", "legacy") or "legacy").lower()
    hold_set = {str(s).upper() for s in (getattr(SETTINGS.trading, "exit_hold_symbols", None) or [])}
    if mode == "institutional_lock" and (canon in hold_set or str(symbol).upper() in hold_set):
        return "hold"
    return mode


def institutional_lock(pol: "ExitPolicy", hold: bool = False) -> "ExitPolicy":
    """A copy of `pol` on the institutional lock: +1R trigger, +0.3R floor (min lot) or a 50%
    partial (splittable), 0.7R trail from the peak, and no time stop (measured to hurt).
    hold=True never triggers the lock: the trade runs to its original stop or target, still with
    the monitor's discretionary layers off (trading.exit_hold_symbols)."""
    import dataclasses
    # profit_locks=False: the monitor's discretionary layers (proximity, MFE retrace, reversal, regime,
    # ML moves, TP1 partials) stay off - they are what lost R live (2026-11-24 replay).
    return dataclasses.replace(pol, trail_mode="institutional", be_at_r=float("inf") if hold else 1.0,
                               lock_floor_r=0.3, trail_r=0.7, lock_partial_pct=0.5, time_stop_minutes=0.0,
                               profit_locks=False)


__all__ = [
    "ExitPolicy",
    "institutional_lock",
    "ExitDecision",
    "evaluate_exit",
    "DEFAULT_BE_TRIGGER_R",
    "DEFAULT_FAST_CASH_R",
    "DEFAULT_RUNNER_TRAIL_ATR",
]
