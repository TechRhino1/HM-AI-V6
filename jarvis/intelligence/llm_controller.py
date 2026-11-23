"""
HM Algo 2.0 — Autonomous LLM Master Controller & Market Governor.

Provides dynamic, macro-aware governance over the algorithmic trading system:
1. Gathers real-time account state, symbol spreads, market regimes, and recent trade outcomes.
2. Uses an LLM (jarvis.ai provider, e.g. Gemini; reduce-only) or an institutional heuristic fallback
   to determine:
   - Dynamic Risk Posture: DEFENSIVE (0.50x-0.75x), NORMAL (1.00x), or AGGRESSIVE (1.15x-1.25x).
   - Dynamic Symbol Directives: ENABLED, THROTTLED, or PAUSED per symbol.
   - Dynamic Strategy Prioritization: symbol-specific preferred strategies based on session and regime.
   - Max Concurrent Position limits for low-balance account protection.
3. Thread-safe caching with TTL prevents latency impact on the high-frequency execution hot path.
4. Hard institutional bounds guarantee safety: LLM risk multipliers are clamped to [0.35, 1.0]
   and micro-account single-trade loss caps are never compromised.
"""

import os
import json
import time
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict

from jarvis.application.state_manager import StateManager, GLOBAL_STATE
from jarvis.config.runtime import is_offline
from jarvis.data.schemas import MarketRegime

logger = logging.getLogger("JARVIS_LLMController")

_DEFAULT_PROVIDER = object()  # sentinel: explicit provider=None still means "heuristic only"

# The governor may only cut risk; the engine never trades above its base risk.
MIN_RISK_MULT, MAX_RISK_MULT = 0.35, 1.0
# After a failed AI call (Google 429/503) the governor stays rule-based this long. On 2026-11-24 every
# 3-minute cache expiry fired one Gemini call per scan thread: 78 failures in minutes, each retried
# across 6 models inside the trading loop.
AI_FAILURE_BACKOFF_SEC = 600.0
# The AI is asked at most this often (default 15 min = 96 calls/day on the free lite models); the
# rules still run every refresh and the last AI read is merged into them while it is this fresh.
GOVERNOR_AI_INTERVAL_S = float(os.environ.get("JARVIS_GOVERNOR_AI_INTERVAL_S", "900") or 900)

_GOVERNOR_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "risk_posture": {"type": "string", "enum": ["DEFENSIVE", "NORMAL"]},
        "risk_multiplier": {"type": "number"},
        "max_concurrent_trades": {"type": "integer"},
        "macro_reasoning": {"type": "string"},
        "confidence": {"type": "number"},
        "symbol_directives": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["ENABLED", "THROTTLED", "PAUSED"]},
                    "preferred_strategy": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["status", "preferred_strategy", "reason"],
            },
        },
    },
    "required": ["risk_posture", "risk_multiplier", "max_concurrent_trades", "macro_reasoning", "symbol_directives"],
}


def _default_provider():
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None  # tests never reach a real model, even with a key in the shell
    try:
        from jarvis.ai.client import get_provider
        return get_provider("background")  # free lite/Gemma models; flash quota is for the Copilot
    except Exception as exc:
        logger.debug("Governor AI provider unavailable: %s", exc)
        return None


@dataclass
class SymbolDirective:
    symbol: str
    status: str  # "ENABLED", "THROTTLED", "PAUSED"
    preferred_strategy: str
    reason: str


@dataclass
class GovernorDirectives:
    risk_posture: str  # "DEFENSIVE", "NORMAL", "AGGRESSIVE"
    risk_multiplier: float  # [0.35, 1.25]
    max_concurrent_trades: int  # 1 to 3
    symbol_directives: Dict[str, SymbolDirective] = field(default_factory=dict)
    macro_reasoning: str = ""
    confidence: float = 0.80
    source: str = "OFFLINE_HEURISTIC"  # "LLM" or "OFFLINE_HEURISTIC"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Convert SymbolDirective dataclass to plain dict
        d["symbol_directives"] = {k: asdict(v) for k, v in self.symbol_directives.items()}
        return d


def recent_governor_activity(limit: int = 10) -> List[Dict[str, Any]]:
    """The last `limit` governor decisions from the audit log, newest first (reads only its tail)."""
    try:
        from jarvis.learning.model_registry import _root
        path = os.path.join(_root(), "audit.jsonl")
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 65536))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in reversed(lines):
        if '"governor_directive"' not in line:
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        out.append({k: r.get(k) for k in ("ts", "source", "posture", "risk_multiplier", "paused",
                                           "throttled", "reasoning")})
        if len(out) >= limit:
            break
    return out


def governor_status(controller: Any = None, published: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the dashboard shows about the governor: current directive, AI telemetry, recent decisions."""
    cur = dict(published or {})
    if controller is not None and getattr(controller, "_cached_directives", None) is not None:
        cur = controller._cached_directives.to_dict()
    syms = cur.get("symbol_directives") or {}
    return {
        "source": cur.get("source"),
        "risk_posture": cur.get("risk_posture"),
        "risk_multiplier": cur.get("risk_multiplier"),
        "reasoning": cur.get("macro_reasoning"),
        "updated_at": cur.get("timestamp"),
        "paused": sorted(s for s, d in syms.items() if (d or {}).get("status") == "PAUSED"),
        "throttled": sorted(s for s, d in syms.items() if (d or {}).get("status") == "THROTTLED"),
        "ai": controller.ai_status() if controller is not None else (published or {}).get("ai"),
        "activity": recent_governor_activity(),
    }


class AutonomousLLMSystemController:
    """
    Master Algorithmic Governor using LLM reasoning (with robust offline fallback)
    to dynamically adapt risk dials, symbol routing, and strategy preferences.
    """

    def __init__(
        self,
        state_manager: StateManager = GLOBAL_STATE,
        provider: Any = _DEFAULT_PROVIDER,
        cache_ttl_sec: float = 180.0,  # 3 minutes default evaluation cache
    ):
        self.state_manager = state_manager or GLOBAL_STATE
        self.provider = _default_provider() if provider is _DEFAULT_PROVIDER else provider
        self.cache_ttl_sec = cache_ttl_sec

        self._lock = threading.Lock()
        self._last_eval_time: float = 0.0
        self._cached_directives: Optional[GovernorDirectives] = None
        # One background AI refresh at a time; the trading loop never waits on the model.
        self._refreshing = False
        self._ai_backoff_until = 0.0
        self._last_ai: Optional[GovernorDirectives] = None
        self._last_ai_at = 0.0
        self.ai_stats: Dict[str, Any] = {"calls": 0, "failures": 0, "last_ok_at": None,
                                         "last_error": None, "last_error_at": None,
                                         "last_latency_ms": None}

    def ai_status(self) -> Dict[str, Any]:
        """The governor's AI telemetry for the dashboard (no keys, no prompts)."""
        p = self.provider
        now = time.time()
        return {
            **self.ai_stats,
            "provider": getattr(p, "name", None) if p is not None else None,
            "model": getattr(p, "model", None) if p is not None else None,
            "enabled": p is not None and not is_offline(),
            "backoff_until": (datetime.fromtimestamp(self._ai_backoff_until, timezone.utc).isoformat()
                              if self._ai_backoff_until > now else None),
            "refreshing": self._refreshing,
        }

    def get_latest_directives(self, force_refresh: bool = False) -> GovernorDirectives:
        """
        Returns the latest active governor directives.
        Uses cached evaluation unless expired or forced.
        """
        now = time.time()
        with self._lock:
            cached = self._cached_directives
            if not force_refresh and cached is not None and (now - self._last_eval_time) < self.cache_ttl_sec:
                return cached
            ai_path = not force_refresh and self.provider is not None
            start_bg = ai_path and not self._refreshing
            if start_bg:
                self._refreshing = True
        if ai_path:
            # Never block the trading loop on the model: serve the last directives (rule-based on
            # the very first call) and let one background thread ask the AI.
            if start_bg:
                threading.Thread(target=self._refresh_in_background, daemon=True,
                                 name="llm_governor_refresh").start()
            if cached is not None:
                return cached
            return self._store(self._heuristic_governor(self._gather_system_context()), now)

        return self._store(self._evaluate_system_and_market(), now)

    def _refresh_in_background(self) -> None:
        try:
            self._store(self._evaluate_system_and_market(), time.time())
        except Exception as e:
            logger.warning(f"Governor background refresh failed: {e}")
        finally:
            with self._lock:
                self._refreshing = False

    def _store(self, directives: "GovernorDirectives", now: float) -> "GovernorDirectives":
        with self._lock:
            previous = self._cached_directives
            self._cached_directives = directives
            self._last_eval_time = now
        if previous is None or (
            previous.risk_multiplier, previous.risk_posture,
            {s: d.status for s, d in previous.symbol_directives.items()},
        ) != (
            directives.risk_multiplier, directives.risk_posture,
            {s: d.status for s, d in directives.symbol_directives.items()},
        ):
            from jarvis.learning.model_registry import audit
            audit("governor_directive", source=directives.source, posture=directives.risk_posture,
                  risk_multiplier=directives.risk_multiplier,
                  paused=[s for s, d in directives.symbol_directives.items() if d.status == "PAUSED"],
                  throttled=[s for s, d in directives.symbol_directives.items() if d.status == "THROTTLED"],
                  reasoning=directives.macro_reasoning)

        # Publish to state manager for UI visibility
        try:
            if hasattr(self.state_manager, "update_llm_governor_state"):
                self.state_manager.update_llm_governor_state({**directives.to_dict(), "ai": self.ai_status()})
        except Exception as e:
            logger.debug(f"Could not push governor state to state_manager: {e}")

        return directives

    def _gather_system_context(self) -> Dict[str, Any]:
        """Gathers real-time telemetry from state_manager, open positions, and account."""
        acc = getattr(self.state_manager, "account", None)
        equity = float(getattr(acc, "equity", 500.0) or 500.0)
        balance = float(getattr(acc, "balance", 500.0) or 500.0)
        drawdown_pct = max(0.0, ((balance - equity) / max(1.0, balance)) * 100.0)

        open_positions = getattr(self.state_manager, "positions", []) or []
        open_count = len(open_positions)
        floating_pnl = sum(float(getattr(p, "profit", 0.0) or 0.0) for p in open_positions)

        active_symbols = getattr(self.state_manager, "active_symbols", [])
        if not active_symbols:
            try:
                from jarvis.config.settings import SETTINGS
                active_symbols = list(SETTINGS.trading.symbols)
            except Exception:
                active_symbols = ["XAUUSD", "BTCUSD", "ETHUSD", "EURUSD", "GBPUSD"]

        # Gather per-symbol context
        now_dt = datetime.now(timezone.utc)
        current_hour_utc = now_dt.hour
        is_weekend = now_dt.weekday() >= 5

        symbol_contexts = {}
        for sym in active_symbols:
            ctx = self.state_manager.get_market_context(sym) if hasattr(self.state_manager, "get_market_context") else getattr(self.state_manager, "market_contexts", {}).get(sym)
            dec = getattr(self.state_manager, "latest_decisions", {}).get(sym)
            regime = getattr(dec, "regime", None)
            regime_str = (
                getattr(regime, "primary_regime", MarketRegime.RANGE).value
                if hasattr(getattr(regime, "primary_regime", None), "value")
                else str(getattr(regime, "primary_regime", "RANGE") if regime else "RANGE")
            )
            spread_pips = float(getattr(ctx, "live_spread_pips", 0.0) or 0.0)
            typical_spread = 2.0
            try:
                # The old import targeted jarvis.market.broker_symbols, a module
                # that does not exist. Every symbol silently fell back to 2.0
                # pips, inflating BTC (1500), ETH (345), SOL (35) and XAG (4.0)
                # spreads into permanent "spread spike" pauses.
                from jarvis.data.symbol_registry import resolve

                typical_spread = float(resolve(sym).typical_spread_pips)
            except Exception as exc:
                logger.debug("Governor spread baseline fallback for %s: %s", sym, exc)

            spread_ratio = spread_pips / max(0.1, typical_spread) if spread_pips > 0 else 1.0

            symbol_contexts[sym] = {
                "regime": regime_str,
                "spread_pips": round(spread_pips, 2),
                "spread_ratio": round(spread_ratio, 2),
                "has_open_position": any(getattr(p, "symbol", "") == sym for p in open_positions),
            }

        return {
            "equity": round(equity, 2),
            "balance": round(balance, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "open_position_count": open_count,
            "floating_pnl": round(floating_pnl, 2),
            "current_hour_utc": current_hour_utc,
            "is_weekend": is_weekend,
            "symbols": symbol_contexts,
        }

    def _evaluate_system_and_market(self) -> GovernorDirectives:
        """
        Executes governance evaluation:
        Tries LLM reasoning if available; otherwise seamlessly falls back to institutional heuristic.
        """
        ctx = self._gather_system_context()
        rules = self._heuristic_governor(ctx)
        now = time.time()

        if (self.provider is not None and not is_offline() and now >= self._ai_backoff_until
                and now - self._last_ai_at >= GOVERNOR_AI_INTERVAL_S):
            t0 = time.time()
            try:
                if self.provider.available():
                    self.ai_stats["calls"] += 1
                    self._last_ai_at = now  # budget the attempt, not only the success
                    llm_directives = self._call_llm_governor(ctx)
                    self.ai_stats["last_latency_ms"] = int((time.time() - t0) * 1000)
                    if llm_directives is not None:
                        self.ai_stats["last_ok_at"] = datetime.now(timezone.utc).isoformat()
                        self._last_ai = llm_directives
            except Exception as e:
                from jarvis.ai.providers.base import redact
                self.ai_stats["failures"] += 1
                self.ai_stats["last_error"] = redact(e)[:200]
                self.ai_stats["last_error_at"] = datetime.now(timezone.utc).isoformat()
                self._ai_backoff_until = time.time() + AI_FAILURE_BACKOFF_SEC
                logger.warning(f"LLM Governor API call failed, rule-based for {AI_FAILURE_BACKOFF_SEC:.0f}s: "
                               f"{self.ai_stats['last_error']}")

        if self._last_ai is not None and now - self._last_ai_at <= GOVERNOR_AI_INTERVAL_S:
            return self._merge(rules, self._last_ai)
        # Institutional Bayesian / Rule-Based Offline Governor
        return rules

    @staticmethod
    def _merge(rules: "GovernorDirectives", ai: "GovernorDirectives") -> "GovernorDirectives":
        """The stricter of the current rules and the last AI read: the AI can only tighten.
        Its multiplier used to be capped at 1.0 only, so an AI 1.0x could undo a rules drawdown cut."""
        rank = {"ENABLED": 0, "THROTTLED": 1, "PAUSED": 2}
        syms = dict(rules.symbol_directives)
        for sym, d in ai.symbol_directives.items():
            base = syms.get(sym)
            if base is None or rank.get(d.status, 0) > rank.get(base.status, 0):
                syms[sym] = d
        defensive = "DEFENSIVE" in (rules.risk_posture, ai.risk_posture)
        return GovernorDirectives(
            risk_posture="DEFENSIVE" if defensive else rules.risk_posture,
            risk_multiplier=round(min(rules.risk_multiplier, ai.risk_multiplier), 2),
            max_concurrent_trades=min(rules.max_concurrent_trades, ai.max_concurrent_trades),
            symbol_directives=syms,
            macro_reasoning=ai.macro_reasoning,
            confidence=ai.confidence,
            source="LLM",
        )

    def _build_llm_prompt(self, ctx: Dict[str, Any]) -> str:
        return f"""You are the Chief Risk Officer and Master Algorithmic Governor for HM Algo 2.0.
Current Live System State:
- Equity: ${ctx['equity']}, Balance: ${ctx['balance']}, Drawdown: {ctx['drawdown_pct']}%
- Open Positions: {ctx['open_position_count']} (Floating PnL: ${ctx['floating_pnl']})
- Time UTC: {ctx['current_hour_utc']}:00 (Weekend: {ctx['is_weekend']})
- Active Symbols & Market Context:
{json.dumps(ctx['symbols'], indent=2)}

Institutional Rules:
1. Micro accounts ($400-$500) MUST preserve capital: Max 1-2 concurrent positions.
2. If Drawdown > 3.0% or multiple open losses, enforce DEFENSIVE posture (risk_multiplier 0.50x to 0.75x).
3. Asian session (00:00-06:00 UTC) & Rollover (21:00-23:00 UTC): PAUSE or THROTTLE Gold and Forex majors.
4. Weekends: PAUSE all FX and Gold; set Crypto to THROTTLED with preferred_strategy="RANGE_MEAN_REVERSION".
5. Prime London/NY sessions with normal spreads: NORMAL posture, risk_multiplier 1.0x.
6. You may only REDUCE risk or pause/throttle symbols. risk_multiplier must be between 0.35 and 1.0; never above 1.0.
7. Crypto high momentum: Prefer "TREND_FOLLOWING" or "BREAKOUT_EXPANSION" on weekdays.
8. Gold prime hours: Prefer "LIQUIDITY_SWEEP_REVERSAL" or "CHOCH_STRUCTURAL_REVERSAL".

Return one directive per active symbol. status is ENABLED, THROTTLED or PAUSED; preferred_strategy is one of
LIQUIDITY_SWEEP_REVERSAL, TREND_FOLLOWING, TREND_PULLBACK, RANGE_MEAN_REVERSION, CHOCH_STRUCTURAL_REVERSAL,
BREAKOUT_EXPANSION. max_concurrent_trades is 1 or 2; confidence is 0.60 to 0.95."""

    def _call_llm_governor(self, ctx: Dict[str, Any]) -> Optional[GovernorDirectives]:
        """Asks the provider for schema-constrained directives; reduce-only by construction."""
        data = self.provider.structured(
            self._build_llm_prompt(ctx),
            json_schema=_GOVERNOR_SCHEMA,
            system="You are an institutional algorithmic risk governor. You may only reduce risk, never raise it.",
        )
        if not isinstance(data, dict) or not data:
            return None

        posture = str(data.get("risk_posture", "NORMAL")).upper()
        if posture not in ("DEFENSIVE", "NORMAL"):
            posture = "NORMAL"

        raw_mult = float(data.get("risk_multiplier", 1.0))
        risk_mult = max(MIN_RISK_MULT, min(MAX_RISK_MULT, raw_mult))

        max_conc = int(data.get("max_concurrent_trades", 2))
        max_conc = max(1, min(2 if ctx["equity"] < 500.0 else 3, max_conc))

        # The LLM may tighten a symbol but never loosen what the rule-based governor paused/throttled.
        rank = {"ENABLED": 0, "THROTTLED": 1, "PAUSED": 2}
        sym_dirs = dict(self._heuristic_governor(ctx).symbol_directives)
        for sym, d in (data.get("symbol_directives") or {}).items():
            status = str(d.get("status", "ENABLED")).upper()
            if status == "PAUSED":
                # Only the rule-based governor hard-pauses (spread spikes, weekends). Gemini paused
                # 5-14 symbols per call on generic "micro account" grounds (2026-11-24), a different
                # set each call, which would have stopped trading; its view is shown, not enforced.
                status = "THROTTLED"
            base = sym_dirs.get(sym)
            if status not in rank or (base is not None and rank.get(base.status, 0) >= rank[status]):
                continue
            sym_dirs[sym] = SymbolDirective(
                symbol=sym,
                status=status,
                preferred_strategy=str(d.get("preferred_strategy", "TREND_PULLBACK")),
                reason="AI advisory: " + str(d.get("reason", "LLM directive")),
            )

        return GovernorDirectives(
            risk_posture=posture,
            risk_multiplier=round(risk_mult, 2),
            max_concurrent_trades=max_conc,
            symbol_directives=sym_dirs,
            macro_reasoning=str(data.get("macro_reasoning", "Autonomous LLM reasoning")),
            confidence=float(data.get("confidence", 0.85)),
            source="LLM",
        )

    def _heuristic_governor(self, ctx: Dict[str, Any]) -> GovernorDirectives:
        """
        Robust, institutional-grade Bayesian heuristic fallback when no LLM key is configured.
        Adheres to ICT/SMC principles, session killzones, and micro-account protection.
        """
        equity = ctx["equity"]
        dd_pct = ctx["drawdown_pct"]
        hour = ctx["current_hour_utc"]
        is_weekend = ctx["is_weekend"]
        open_count = ctx["open_position_count"]
        symbols = ctx["symbols"]

        # 1. Base Posture Determination
        if dd_pct >= 3.0 or (open_count >= 2 and ctx["floating_pnl"] < -5.0):
            posture = "DEFENSIVE"
            risk_mult = 0.65
            max_conc = 1
            reason = f"Defensive posture engaged: drawdown at {dd_pct:.1f}% on small account (${equity:.2f})."
        elif dd_pct >= 1.5:
            posture = "DEFENSIVE"
            risk_mult = 0.80
            max_conc = 1
            reason = f"Moderate risk damping: drawdown at {dd_pct:.1f}%."
        elif not is_weekend and (7 <= hour <= 16):
            # Prime London / NY killzone window
            posture = "NORMAL"
            risk_mult = 1.00
            max_conc = 2 if equity >= 350.0 else 1
            reason = f"Prime institutional session ({hour:02d}:00 UTC). Normal risk allocation active."
        else:
            posture = "NORMAL"
            risk_mult = 0.85
            max_conc = 1
            reason = f"Off-peak liquidity hours ({hour:02d}:00 UTC). Micro risk damped to 0.85x."

        # 2. Per-Symbol Directives
        sym_directives: Dict[str, SymbolDirective] = {}
        for sym, s_data in symbols.items():
            canonical = sym.upper()
            regime = s_data.get("regime", "RANGE")
            spread_ratio = s_data.get("spread_ratio", 1.0)
            is_crypto = any(c in canonical for c in ("BTC", "ETH", "SOL", "CRYPTO"))
            is_gold = any(g in canonical for g in ("XAU", "GOLD"))

            # Spread blowout protection
            if spread_ratio > 1.80:
                sym_directives[sym] = SymbolDirective(
                    symbol=sym,
                    status="PAUSED",
                    preferred_strategy="RANGE_MEAN_REVERSION",
                    reason=f"Spread spike detected ({spread_ratio:.1f}x typical spread). Entries halted.",
                )
                continue

            # Weekend governance
            if is_weekend:
                if is_crypto:
                    sym_directives[sym] = SymbolDirective(
                        symbol=sym,
                        status="THROTTLED",
                        preferred_strategy="RANGE_MEAN_REVERSION",
                        reason="Weekend crypto regime: lower volume and mean-reverting chop. Breakouts banned.",
                    )
                else:
                    sym_directives[sym] = SymbolDirective(
                        symbol=sym,
                        status="PAUSED",
                        preferred_strategy="NONE",
                        reason="Traditional market closed on weekend.",
                    )
                continue

            # Weekday Session Governance
            if is_gold:
                # Prime Gold hours: 07:00 to 19:00 UTC
                if 7 <= hour <= 18:
                    sym_directives[sym] = SymbolDirective(
                        symbol=sym,
                        status="ENABLED",
                        preferred_strategy="LIQUIDITY_SWEEP_REVERSAL" if "RANGE" in regime else "CHOCH_STRUCTURAL_REVERSAL",
                        reason="Prime London/NY liquidity session for Gold. Clean institutional displacement.",
                    )
                else:
                    sym_directives[sym] = SymbolDirective(
                        symbol=sym,
                        status="THROTTLED",
                        preferred_strategy="RANGE_MEAN_REVERSION",
                        reason="Off-hours Asian session or Rollover window. Gold entries throttled with reduced risk.",
                    )
            elif is_crypto:
                if 12 <= hour <= 20:
                    sym_directives[sym] = SymbolDirective(
                        symbol=sym,
                        status="ENABLED",
                        preferred_strategy="TREND_FOLLOWING" if "TREND" in regime else "TREND_PULLBACK",
                        reason="US cash equity open: maximum crypto trend persistence and CVD volume.",
                    )
                else:
                    sym_directives[sym] = SymbolDirective(
                        symbol=sym,
                        status="ENABLED",
                        preferred_strategy="TREND_PULLBACK",
                        reason="Normal crypto session. Requiring discount/premium pullback before entry.",
                    )
            else:
                # Forex Majors, Indices, Commodities
                is_asian_native = any(c in canonical for c in ("JPY", "AUD", "NZD"))
                is_index = any(c in canonical for c in ("US30", "NAS100", "US500", "GER40", "UK100"))
                if is_asian_native and (0 <= hour <= 9):
                    sym_directives[sym] = SymbolDirective(
                        symbol=sym,
                        status="ENABLED",
                        preferred_strategy="LIQUIDITY_SWEEP_REVERSAL" if hour <= 4 else "TREND_PULLBACK",
                        reason="Tokyo/Sydney session open for Asia-Pacific currency. Active institutional order flow.",
                    )
                elif 7 <= hour <= 21:
                    sym_directives[sym] = SymbolDirective(
                        symbol=sym,
                        status="ENABLED",
                        preferred_strategy="LIQUIDITY_SWEEP_REVERSAL" if hour <= 9 else ("BREAKOUT_EXPANSION" if is_index and 13 <= hour <= 17 else "TREND_PULLBACK"),
                        reason="London/NY overlap killzone. High volume and institutional expansion active.",
                    )
                else:
                    sym_directives[sym] = SymbolDirective(
                        symbol=sym,
                        status="THROTTLED",
                        preferred_strategy="RANGE_MEAN_REVERSION",
                        reason="Off-peak session. Throttled risk to avoid low-liquidity chop.",
                    )

        # Micro-account hard constraint
        if equity < 500.0:
            max_conc = min(2, max_conc)
            risk_mult = min(1.10, risk_mult)

        return GovernorDirectives(
            risk_posture=posture,
            risk_multiplier=round(risk_mult, 2),
            max_concurrent_trades=max_conc,
            symbol_directives=sym_directives,
            macro_reasoning=reason,
            confidence=0.88,
            source="OFFLINE_HEURISTIC",
        )
