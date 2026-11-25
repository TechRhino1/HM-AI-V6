"""
HM Algo 2.0 — Master Trader AI Autonomous Universe Auto-Tune Engine.
Evaluates the entire multi-asset universe across four selectable strategy profiles:
1. BALANCED (Optimal Edge - Default)
2. CONSERVATIVE (Grade A+ / Highest Edge Only)
3. AGGRESSIVE (High Coverage & Broad Discovery)
4. SESSION_ADAPTIVE (Time-of-Day Global Flow Alignment)
5. DYNAMIC (live evidence: each symbol's own closed-trade R, shrunk toward its calibrated
   out-of-sample prior, with hysteresis; runs every 30 min when trading.auto_tune="dynamic")

Takes into account live market open/closed sessions, spread friction defense,
currency correlation caps, setup quality grades, and master confluence scores.
"""
from __future__ import annotations

import time
import logging
from typing import Dict, List, Set, Any, Optional, Tuple

from jarvis.data.symbol_registry import _REGISTRY, resolve as resolve_symbol, is_crypto
from jarvis.market.sessions import SessionEngine
from jarvis.market.data_feed import _is_weekend_gap

logger = logging.getLogger("JARVIS_AutoTuneEngine")

# DYNAMIC: edge = (n * live_R + K * prior_R) / (n + K), the AutoStyleSelector shrinkage (K=30).
# A symbol switches on at >= ENTER and, once on, stays on until it falls below EXIT (the
# quarantine threshold), so one bad trade does not flip it. Without a calibrated prior or
# MIN_LIVE closes there is no evidence, and the symbol keeps whatever state it has.
DYN_K = 30.0
DYN_ENTER_R = -0.05
DYN_EXIT_R = -0.15
DYN_MIN_LIVE = 6
DYN_MAX_SYMBOLS = 8
DYN_MAX_USD = 3


def _deployment_refusal(symbol: str) -> Optional[str]:
    """The execution-time deployment gate (holdout / expectancy). Fails open: the
    risk engine enforces the same gate on every order, so an error here only
    loses the pre-filter, never a safety check."""
    try:
        from jarvis.backtesting.exit_geometry import deployment_refusal
        return deployment_refusal(symbol)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Auto-tune: deployment gate unavailable for %s: %s", symbol, exc)
        return None


def dynamic_edge(n: int, live_r: float, prior_r: float, k: float = DYN_K) -> float:
    """Live mean R shrunk toward the calibrated prior; n=0 returns the prior."""
    return (n * live_r + k * prior_r) / (n + k)


def dynamic_score(n: int, live_r: float, prior_r: Optional[float]) -> Dict[str, Any]:
    """The DYNAMIC fields for one symbol: evidence = enough live closes or a calibrated prior."""
    return {"n": n, "live_r": live_r, "prior_r": prior_r,
            "evidence": n >= DYN_MIN_LIVE or prior_r is not None,
            "edge": dynamic_edge(n, live_r, prior_r or 0.0)}


def dynamic_on(edge: float, was_on: bool) -> bool:
    """Hysteresis: the bar to stay on (EXIT) is lower than the bar to switch on (ENTER)."""
    return edge >= (DYN_EXIT_R if was_on else DYN_ENTER_R)


def _dynamic_inputs(orchestrator: Any) -> Tuple[Dict[str, Tuple[int, float]], Dict[str, float]]:
    """({symbol: (n, live mean R)}, {symbol: calibrated out-of-sample R}); empty on failure."""
    live: Dict[str, Tuple[int, float]] = {}
    priors: Dict[str, float] = {}
    try:
        from jarvis.execution.strategy_quarantine import load_symbol_expectancy
        live = load_symbol_expectancy(execution_mode=str(getattr(orchestrator, "mode", "demo") or "demo"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dynamic auto-tune: live ledger unavailable: %s", exc)
    try:
        from jarvis.intelligence.winrate_targeting import load_profiles
        priors = {k.upper(): float(p.oos_expectancy_r) for k, p in load_profiles().items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dynamic auto-tune: calibrated priors unavailable: %s", exc)
    return live, priors


class AutoTuneEngine:
    """
    Autonomous Universe Auto-Tune Engine for Master Trader AI Symbol Control Center.
    Calculates the mathematically optimal active trading universe based on live market conditions.
    """

    # Currency groups for correlation risk management
    USD_PAIRS = {"EURUSD", "GBPUSD", "USDJPY", "USDCAD", "AUDUSD", "NZDUSD", "USDCHF"}
    CRYPTO_PAIRS = {"BTCUSD", "ETHUSD", "SOLUSD"}
    INDEX_PAIRS = {"US500", "GER40", "UK100"}
    COMMODITY_PAIRS = {"XAUUSD", "XAGUSD", "WTI"}

    @classmethod
    def dynamic_select(cls, candidates: List[Dict[str, Any]], incumbents: Set[str]) -> Tuple[Set[str], List[Dict[str, Any]]]:
        """DYNAMIC selection over scored candidates (keys: symbol, edge, n, live_r, prior_r, evidence,
        confluence, ev, is_open, is_spread_spiked, spread_pips, max_spread). Pure: no I/O."""
        selected_symbols: Set[str] = set()
        tuning_details: List[Dict[str, Any]] = []
        # Rank by edge; the current radar (confluence, EV) only breaks near-ties.
        ranked = sorted(candidates, key=lambda x: x["edge"] + 0.02 * (x["confluence"] - 50.0) / 50.0
                        + 0.01 * max(-1.0, min(1.0, x["ev"])), reverse=True)
        usd_count = 0
        for c in ranked:
            sym, was_on = c["symbol"], c["symbol"] in incumbents
            why = (f"edge {c['edge']:+.2f}R (live {c['live_r']:+.2f}R n={c['n']}, prior "
                   + (f"{c['prior_r']:+.2f}R" if c["prior_r"] is not None else "none") + ")")
            if not c["is_open"]:
                tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "Market session closed"})
                continue
            if c["is_spread_spiked"]:
                tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"Spread friction high ({c['spread_pips']}p > {c['max_spread']}p)"})
                continue
            if not c["evidence"]:
                if was_on:
                    selected_symbols.add(sym)
                tuning_details.append({"symbol": sym, "status": "ACTIVATED" if was_on else "DEACTIVATED",
                                       "reason": f"No evidence yet (n={c['n']}, no calibrated prior): kept as it was"})
                continue
            if not dynamic_on(c["edge"], was_on):
                bar = DYN_EXIT_R if was_on else DYN_ENTER_R
                tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"{why} below {bar:+.2f}R"})
                continue
            if sym in cls.USD_PAIRS:
                if usd_count >= DYN_MAX_USD:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"USD pair correlation limit reached (max {DYN_MAX_USD})"})
                    continue
                usd_count += 1
            if len(selected_symbols) >= DYN_MAX_SYMBOLS:
                tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"Universe cap reached (max {DYN_MAX_SYMBOLS})"})
                continue
            selected_symbols.add(sym)
            tuning_details.append({"symbol": sym, "status": "ACTIVATED", "reason": why,
                                   "edge_r": round(c["edge"], 3), "n": c["n"]})

        return selected_symbols, tuning_details

    @classmethod
    def tune_universe(
        cls,
        orchestrator: Any = None,
        state_manager: Any = None,
        mt5_client: Any = None,
        mode: str = "BALANCED",
        asset_class: str = "ALL"
    ) -> Dict[str, Any]:
        """
        Executes multi-factor universe auto-tuning.
        Returns:
            {
                "active_symbols": List[str],
                "active_count": int,
                "summary": str,
                "details": List[Dict[str, Any]],
                "mode": str
            }
        """
        profile = (mode or "BALANCED").strip().upper()
        if profile not in ("BALANCED", "CONSERVATIVE", "AGGRESSIVE", "SESSION_ADAPTIVE", "DYNAMIC"):
            profile = "BALANCED"

        target_class = (asset_class or "ALL").strip().upper()
        now = time.time()
        is_weekend = _is_weekend_gap(now)

        # 1. Gather all symbol data from radar and state manager
        radar_map: Dict[str, Dict[str, Any]] = {}
        if state_manager and hasattr(state_manager, "radar_opportunities"):
            for item in list(state_manager.radar_opportunities or []):
                s = item.get("symbol")
                if s and s not in radar_map:
                    radar_map[s] = item

        latest_decisions = getattr(state_manager, "latest_decisions", {}) or {}

        # 2. Evaluate every registered symbol
        candidates: List[Dict[str, Any]] = []
        for sym_name, spec in _REGISTRY.items():
            sym_upper = sym_name.upper()

            # Filter by asset class if specific asset class was requested
            if target_class != "ALL" and spec.asset_class.upper() != target_class:
                continue

            # Session open status
            mkt_status = SessionEngine.get_market_trading_status(sym_upper)
            is_open = mkt_status.get("is_open", True)
            current_session = mkt_status.get("current_session", "GLOBAL")

            # Check spread & friction
            spread_pips = float(spec.typical_spread_pips or 1.0)
            if mt5_client and hasattr(mt5_client, "get_symbol_trading_spec"):
                try:
                    spec_info = mt5_client.get_symbol_trading_spec(sym_upper)
                    if spec_info:
                        pts = float(spec_info.get("spread") or 0.0)
                        digits = int(spec_info.get("digits") or spec.digits or 5)
                        point = float(spec_info.get("point") or (10 ** -digits))
                        pip_sz = float(spec.pip_size or 0.0001)
                        if pts > 0 and pip_sz > 0:
                            spread_pips = round((pts * point) / pip_sz, 1)
                except Exception:
                    pass

            max_spread = float(spec.max_spread_pips or 5.0)
            is_spread_spiked = spread_pips > (max_spread * 1.4)

            # Radar and setup metrics
            radar_item = radar_map.get(sym_upper, {})
            dec_obj = latest_decisions.get(sym_upper)

            confluence = float(radar_item.get("confluence_score") or getattr(dec_obj, "master_confluence_score", 0.0) or 0.0)
            win_prob = float(radar_item.get("win_prob") or (round(dec_obj.model_confidence * 100.0, 1) if (dec_obj and hasattr(dec_obj, "model_confidence") and dec_obj.model_confidence is not None) else 50.0))
            ev = float(radar_item.get("ev") or radar_item.get("expected_value")
                       or getattr(dec_obj, "expected_value", 0.0) or 0.0)
            bias = str(radar_item.get("bias") or (getattr(dec_obj, "bias", None) if dec_obj else "NEUTRAL")).upper()
            regime = str(radar_item.get("regime") or "NORMAL").upper()
            grade = str(radar_item.get("setup_grade") or (radar_item.get("grade") or "B")).upper()

            # Utility score
            utility = float(radar_item.get("utility_score") or 0.0)

            candidates.append({
                "symbol": sym_upper,
                "asset_class": spec.asset_class.upper(),
                "is_open": is_open,
                "is_weekend": is_weekend,
                "is_crypto": is_crypto(sym_upper),
                "current_session": current_session,
                "spread_pips": spread_pips,
                "max_spread": max_spread,
                "is_spread_spiked": is_spread_spiked,
                "confluence": confluence,
                "win_prob": win_prob,
                "ev": ev,
                "bias": bias,
                "regime": regime,
                "grade": grade,
                "utility": utility
            })

        # 3. Apply profile-specific selection rules
        selected_symbols: Set[str] = set()
        tuning_details: List[Dict[str, Any]] = []

        # Rule 0: On weekend gap, non-crypto markets are shut
        if is_weekend:
            for c in candidates:
                if c["is_crypto"]:
                    selected_symbols.add(c["symbol"])
                    tuning_details.append({
                        "symbol": c["symbol"],
                        "status": "ACTIVATED",
                        "reason": f"Weekend 24/7 Crypto Asset (Conf {c['confluence']:.0f})"
                    })
                else:
                    tuning_details.append({
                        "symbol": c["symbol"],
                        "status": "DEACTIVATED",
                        "reason": "Weekend Market Closed (TradFi shut)"
                    })
            summary = f"Weekend Mode: Activated {len(selected_symbols)} 24/7 Crypto symbols; TradFi shut."
            return {
                "active_symbols": sorted(list(selected_symbols)),
                "active_count": len(selected_symbols),
                "summary": summary,
                "details": tuning_details,
                "mode": profile
            }

        # Weekday Selection Logic by Profile:
        if profile == "CONSERVATIVE":
            # Only Grade A/A+ with high confluence, strictly open, normal spread
            # Sort by utility descending
            sorted_cands = sorted(candidates, key=lambda x: (x["confluence"], x["utility"], x["win_prob"]), reverse=True)
            usd_count = 0
            for c in sorted_cands:
                sym = c["symbol"]
                if not c["is_open"]:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "Market session closed"})
                    continue
                if c["is_spread_spiked"]:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"Spread friction high ({c['spread_pips']}p > {c['max_spread']}p)"})
                    continue
                if c["grade"] not in ("A+", "A", "GRADE A+", "GRADE A") and c["confluence"] < 55:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"Below Conservative quality threshold (Grade {c['grade']}, Conf {c['confluence']:.0f})"})
                    continue
                # Currency correlation cap: max 2 USD pairs
                if sym in cls.USD_PAIRS:
                    if usd_count >= 2:
                        tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "USD correlation concentration cap reached (max 2)"})
                        continue
                    usd_count += 1

                # Cap total symbols to 5
                if len(selected_symbols) >= 5 and "XAU" not in sym:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "Conservative universe cap reached (max 5)"})
                    continue

                selected_symbols.add(sym)
                tuning_details.append({
                    "symbol": sym,
                    "status": "ACTIVATED",
                    "reason": f"Elite Grade {c['grade']} Setup | Conf {c['confluence']:.0f} | WinP {c['win_prob']:.0f}%"
                })

        elif profile == "DYNAMIC":
            live, priors = _dynamic_inputs(orchestrator)
            try:
                from jarvis.config.settings import SETTINGS
                incumbents = {str(x).upper() for x in (getattr(orchestrator, "symbols", None)
                                                        or SETTINGS.trading.symbols or [])}
            except Exception:  # noqa: BLE001
                incumbents = set()
            for c in candidates:
                c.update(dynamic_score(*live.get(c["symbol"], (0, 0.0)), priors.get(c["symbol"])))
            sel, det = cls.dynamic_select(candidates, incumbents)
            selected_symbols |= sel
            tuning_details.extend(det)

        elif profile == "AGGRESSIVE":
            # Broad coverage: enable anything open with directional bias and normal spread
            for c in candidates:
                sym = c["symbol"]
                if not c["is_open"]:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "Market session closed"})
                    continue
                if c["is_spread_spiked"]:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "Excessive spread friction"})
                    continue
                if any(r in c["regime"] for r in ("CHOP", "COMPRESSION")) and c["confluence"] < 25:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"Low-edge choppy compression (Conf {c['confluence']:.0f})"})
                    continue

                selected_symbols.add(sym)
                tuning_details.append({
                    "symbol": sym,
                    "status": "ACTIVATED",
                    "reason": f"Active {c['asset_class']} Setup ({c['bias']} {c['regime']})"
                })

        elif profile == "SESSION_ADAPTIVE":
            # Align with active global session
            # London: EUR, GBP, GER40, UK100, XAUUSD
            # NY: US500, XAUUSD, WTI, USD pairs
            # Asian/Pacific: JPY, AUD, NZD, Crypto
            from datetime import datetime, timezone
            utc_hour = datetime.now(timezone.utc).hour

            for c in candidates:
                sym = c["symbol"]
                if not c["is_open"]:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "Market session closed"})
                    continue
                if c["is_spread_spiked"]:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "Spread spiked"})
                    continue

                is_session_favored = False
                reason_tag = ""

                # Gold is universal priority
                if "XAU" in sym or "GOLD" in sym:
                    is_session_favored = True
                    reason_tag = "Universal Gold Priority"
                elif 7 <= utc_hour < 16:  # London Cash
                    if any(x in sym for x in ("EUR", "GBP", "GER40", "UK100", "USDCHF")):
                        is_session_favored = True
                        reason_tag = "London Core Cash Flow"
                elif 12 <= utc_hour < 21:  # New York Cash
                    if any(x in sym for x in ("US500", "WTI", "USDCAD", "EURUSD", "GBPUSD", "BTC")):
                        is_session_favored = True
                        reason_tag = "New York Core Liquidity"
                else:  # Asian / Pacific
                    if any(x in sym for x in ("JPY", "AUD", "NZD", "BTC", "ETH", "SOL")):
                        is_session_favored = True
                        reason_tag = "Tokyo/Pacific Session Flow"

                if is_session_favored and (c["confluence"] >= 35 or "TREND" in c["regime"]):
                    selected_symbols.add(sym)
                    tuning_details.append({"symbol": sym, "status": "ACTIVATED", "reason": f"{reason_tag} (Conf {c['confluence']:.0f})"})
                else:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"Off-peak session or low edge (Conf {c['confluence']:.0f})"})

        else:
            # BALANCED (Default Optimal Institutional Edge)
            # Grade >= B with positive EV, open market, spread within bounds, max 3 USD pairs
            sorted_cands = sorted(candidates, key=lambda x: (x["confluence"], x["utility"], x["win_prob"]), reverse=True)
            usd_count = 0
            for c in sorted_cands:
                sym = c["symbol"]
                if not c["is_open"]:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "Market session closed"})
                    continue
                if c["is_spread_spiked"]:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"Spread friction high ({c['spread_pips']}p > {c['max_spread']}p)"})
                    continue

                # Filter out low-confluence chop
                if any(r in c["regime"] for r in ("CHOP", "COMPRESSION", "RANGE")) and c["confluence"] < 35:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"Low-confluence range compression ({c['confluence']:.0f})"})
                    continue

                if c["confluence"] < 30 and c["grade"] in ("C", "F", "GRADE C", "GRADE F"):
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": f"Below Balanced threshold (Conf {c['confluence']:.0f})"})
                    continue

                # Currency correlation cap: max 3 USD pairs
                if sym in cls.USD_PAIRS:
                    if usd_count >= 3:
                        tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "USD pair correlation limit reached (max 3)"})
                        continue
                    usd_count += 1

                # Cap total symbols to 8 to avoid margin dilution
                if len(selected_symbols) >= 8 and "XAU" not in sym:
                    tuning_details.append({"symbol": sym, "status": "DEACTIVATED", "reason": "Balanced active universe cap reached (max 8)"})
                    continue

                selected_symbols.add(sym)
                tuning_details.append({
                    "symbol": sym,
                    "status": "ACTIVATED",
                    "reason": f"High Confluence Setup (Grade {c['grade']} | Conf {c['confluence']:.0f} | {c['regime']})"
                })

        # Never activate a symbol the execution gate will refuse anyway. The risk
        # engine rejects every deployment-refused symbol, so selecting them by a
        # different edge score left the bot scanning 8 symbols it could not trade.
        refused = {s: r for s in selected_symbols if (r := _deployment_refusal(s))}
        if refused:
            selected_symbols -= set(refused)
            for d in tuning_details:
                if d.get("symbol") in refused and d.get("status") == "ACTIVATED":
                    d.update(status="DEACTIVATED", reason=refused[d["symbol"]])

        # Ensure active universe is never completely empty
        if not selected_symbols:
            # Fallback to liquid anchors the gate allows; only if none pass, the old anchors.
            anchors = [a for a in ("XAUUSD", "EURUSD", "BTCUSD") if a in _REGISTRY]
            for anchor in ([a for a in anchors if not _deployment_refusal(a)] or anchors):
                selected_symbols.add(anchor)
                tuning_details.append({"symbol": anchor, "status": "ACTIVATED", "reason": "Default liquid anchor guarantee"})

        active_list = sorted(list(selected_symbols))
        summary = f"Auto-Tuned {len(active_list)} active symbols under {profile} profile ({len(active_list)} activated, {len(candidates) - len(active_list)} filtered)."
        logger.info(summary)

        return {
            "active_symbols": active_list,
            "active_count": len(active_list),
            "summary": summary,
            "details": tuning_details,
            "mode": profile
        }
