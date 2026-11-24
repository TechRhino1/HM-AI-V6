"""HM Algo 2.0 Settings Engine."""
import os
import json
import logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger("JARVIS_Config")

AUTO_TUNE_MODES = ("off", "dynamic")

def verify_execution_mode(mode: str) -> str:
    """
    Verifies execution mode.
    Defaults to 'demo' for broker-connected paper testing (safe default).
    'live' requires the explicit JARVIS_CONFIRM_LIVE=1 acknowledgement and
    otherwise falls back to 'paper' with a loud warning, matching README §7.
    Returns 'paper' for offline / backtest simulation.
    """
    norm_mode = str(mode or "demo").lower().strip()
    if norm_mode == "live":
        confirmed = str(os.environ.get("JARVIS_CONFIRM_LIVE", "")).strip().lower()
        if confirmed in {"1", "true", "yes", "on"}:
            return "live"
        logger.critical(
            "LIVE EXECUTION BLOCKED: mode='live' was requested without "
            "JARVIS_CONFIRM_LIVE=1. Falling back to 'paper'. Set the variable "
            "explicitly only after verifying the account, symbols, and risk limits."
        )
        return "paper"
    if norm_mode in {"paper", "backtest", "simulated", "offline"}:
        return "paper"
    return "demo"


@dataclass
class RiskSettings:
    # Unified risk policy (approved 2026-11-16): one source of truth for every
    # account size. Sizing targets max_risk_per_trade_pct; a broker-minimum lot
    # may risk up to min_lot_max_risk_pct, otherwise the trade is skipped.
    max_risk_per_trade_pct: float = 1.0
    min_lot_max_risk_pct: float = 2.5
    max_portfolio_risk_pct: float = 2.5
    max_daily_loss_pct: float = 5.0
    max_weekly_loss_pct: float = 10.0
    max_drawdown_pct: float = 20.0
    max_open_positions: int = 3
    max_symbol_positions: int = 2
    partial_tp_r_multiple: float = 1.5
    # Approved 2026-10-23: a capped recovery channel for perfect A+ setups after
    # the daily halt. Disabled until out-of-sample validation proves the edge;
    # when enabled it is one attempt per day at 0.5% risk, and never past 6.5%.
    recovery_channel_enabled: bool = False
    recovery_risk_pct: float = 0.5
    recovery_max_daily_loss_pct: float = 6.5
    recovery_max_attempts_per_day: int = 1
    # NOTE: `breakeven_atr_multiple` was REMOVED here. It was declared but never
    # read anywhere, and its value (1.0) directly contradicted the canonical exit
    # policy, which defers breakeven to +2R. Leaving a dead field named this
    # invites someone to "fix" it and reintroduce the premature-breakeven defect
    # that was responsible for the negative net profit. Breakeven is now owned
    # solely by jarvis.execution.exit_policy.
    max_sector_exposure_count: int = 2
    correlation_scaling_enabled: bool = True
    correlation_scaling_floor: float = 0.40
    breakeven_clears_correlation: bool = True

@dataclass
class TradingSettings:
    default_mode: str = "demo"
    magic_number: int = 888999
    primary_timeframe: str = "H1"
    symbols: List[str] = field(default_factory=lambda: ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD"])
    # Entry selection authority. False (the default) keeps the legacy 29-check
    # gate stack, which is what the platform has always traded on. True hands
    # selection to jarvis.execution.entry_policy, using the out-of-sample
    # calibrated profile in config/winrate_profiles.json.
    #
    # This is deliberately opt-in. The profiles on disk currently show a
    # NEGATIVE out-of-sample expectancy for 11 of the 16 calibrated symbols, so
    # enabling this does not "improve" the trade set -- it switches most of the
    # universe off. That is a trading decision, not a bug fix, and it must be
    # taken knowingly rather than shipped as a default.
    use_calibrated_entry_policy: bool = False
    # Live exit management: "legacy" (the layered stack) or "institutional_lock" (one measured rule:
    # lock at +1R, trail 0.7R behind the peak; see exit_policy.institutional_lock).
    exit_mode: str = "legacy"
    # Under institutional_lock, these symbols hold to their original stop/target instead (no lock,
    # no trail): measured better in both halves for crypto on 353 clean live trades, 2026-11-24.
    exit_hold_symbols: List[str] = field(default_factory=list)
    # Symbol-universe auto-tune: "off" (manual button only) or "dynamic" (AutoTuneEngine DYNAMIC
    # every 30 min from the watchdog; see reports/AUTO_TUNE_RESEARCH_2026-11-24.md).
    auto_tune: str = "off"
    # Calibrated policy as its own entry route (2026-11-23): a SWING candidate the calibrated
    # policy allows is dispatched at market even when the legacy gates said WAIT/NO_TRADE, through
    # the full dispatch path (vetoes, slots, cooldowns, RiskEngine sizing/heat/correlation/circuit
    # breaker, news). Off by default for a fresh install; config/settings.json turns it on.
    calibrated_policy_trader: bool = False
    # Modes in which the FT_ forward tests (trend_router, donchian_eth_h4, research_leads) trade.
    # Demo only by default; config/settings.json can extend it to paper/live.
    forward_test_modes: List[str] = field(default_factory=lambda: ["demo"])
    # AdaptiveGatePolicy knobs. The SOFTEN pathway historically never fired
    # because the decision engine always passed recent_win_rate=None; with the
    # pathway now live, these two knobs decide how permissive it is.
    # max_soft_fail: how many failing SOFT gates may be converted into a
    # confidence penalty instead of a block.
    # min_recent_win_rate: the recent closed-trade win rate (last 30) required
    # before any softening is allowed. With fewer than 10 closed trades there is
    # no evidence and the policy blocks regardless.
    gate_policy_max_soft_fail: int = 3
    gate_policy_min_recent_win_rate: float = 0.45
    # 2026-10-20 profitability audit: 83 gold trades taken in days on a micro
    # account all resolved through an all-or-nothing book with -0.44R/trade
    # expectancy; overtrading spread churn was a first-order cost. Cap new
    # entries per symbol per UTC day (position management/trailing unaffected).
    # 0 disables the cap.
    max_daily_entries_per_symbol: int = 4
    # Live-expectancy quarantine (jarvis.execution.strategy_quarantine): a
    # (symbol, strategy) pair whose last ``quarantine_window`` closed trades
    # average <= ``quarantine_expectancy_r`` R is vetoed on every entry route.
    quarantine_expectancy_r: float = -0.15
    quarantine_window: int = 30

@dataclass
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8501
    cors_origin: str = ""

@dataclass
class MLSettings:
    sgd_learning_rate: float = 0.05
    sgd_l2_regularization: float = 0.01
    brier_score_drift_threshold: float = 0.28

@dataclass
class JarvisConfig:
    risk: RiskSettings = field(default_factory=RiskSettings)
    trading: TradingSettings = field(default_factory=TradingSettings)
    server: ServerSettings = field(default_factory=ServerSettings)
    ml: MLSettings = field(default_factory=MLSettings)

    @classmethod
    def load(cls) -> "JarvisConfig":
        cfg = cls()
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        json_path = os.path.join(base_dir, "config", "settings.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                r_data = data.get("risk", {})
                # (str-key, attr, caster) — previously only three of these were
                # read, so editing settings.json silently had no effect for the
                # rest. Keep the mapping explicit so the contract is obvious.
                risk_keys = (
                    ("max_risk_per_trade_pct", "max_risk_per_trade_pct", float),
                    ("max_portfolio_risk_pct", "max_portfolio_risk_pct", float),
                    ("max_daily_loss_pct", "max_daily_loss_pct", float),
                    ("max_weekly_loss_pct", "max_weekly_loss_pct", float),
                    ("min_lot_max_risk_pct", "min_lot_max_risk_pct", float),
                    ("max_drawdown_pct", "max_drawdown_pct", float),
                    ("max_open_positions", "max_open_positions", int),
                    ("max_symbol_positions", "max_symbol_positions", int),
                    ("recovery_channel_enabled", "recovery_channel_enabled", lambda v: str(v).strip().lower() in {"1", "true", "yes", "on"}),
                    ("recovery_risk_pct", "recovery_risk_pct", float),
                    ("recovery_max_daily_loss_pct", "recovery_max_daily_loss_pct", float),
                    ("recovery_max_attempts_per_day", "recovery_max_attempts_per_day", int),
                    ("max_sector_exposure_count", "max_sector_exposure_count", int),
                    ("correlation_scaling_enabled", "correlation_scaling_enabled", lambda v: str(v).strip().lower() in {"1", "true", "yes", "on"}),
                    ("correlation_scaling_floor", "correlation_scaling_floor", float),
                    ("breakeven_clears_correlation", "breakeven_clears_correlation", lambda v: str(v).strip().lower() in {"1", "true", "yes", "on"}),
                )
                for json_key, attr, caster in risk_keys:
                    if json_key in r_data and r_data[json_key] is not None:
                        try:
                            setattr(cfg.risk, attr, caster(r_data[json_key]))
                        except (TypeError, ValueError) as exc:
                            logger.warning(
                                f"Ignoring invalid risk.{json_key}={r_data[json_key]!r}: {exc}"
                            )
                # `breakeven_atr_trigger` is intentionally NOT loaded: breakeven
                # timing is owned by jarvis.execution.exit_policy. Warn loudly if
                # someone still has it in the file so its presence is not mistaken
                # for an active setting.
                if "breakeven_atr_trigger" in r_data:
                    logger.warning(
                        "config/settings.json contains 'risk.breakeven_atr_trigger' which is "
                        "IGNORED. Breakeven timing is defined in jarvis.execution.exit_policy "
                        "(be_trigger_r, default +2R). Remove the stale key to avoid confusion."
                    )
                t_data = data.get("trading", {})
                if "default_mode" in t_data and str(t_data["default_mode"]).lower() in {"live", "paper", "demo"}:
                    cfg.trading.default_mode = str(t_data["default_mode"]).lower()
                if "allowed_symbols" in t_data:
                    cfg.trading.symbols = list(t_data["allowed_symbols"])
                if "magic_number" in t_data:
                    cfg.trading.magic_number = int(t_data["magic_number"])
                if "primary_timeframe" in t_data:
                    cfg.trading.primary_timeframe = str(t_data["primary_timeframe"])
                if "use_calibrated_entry_policy" in t_data:
                    raw = t_data["use_calibrated_entry_policy"]
                    if isinstance(raw, bool):
                        cfg.trading.use_calibrated_entry_policy = raw
                    else:
                        cfg.trading.use_calibrated_entry_policy = str(raw).strip().lower() in {
                            "1", "true", "yes", "on",
                        }
                if str(t_data.get("exit_mode", "")).lower() in ("legacy", "institutional_lock"):
                    cfg.trading.exit_mode = str(t_data["exit_mode"]).lower()
                if str(t_data.get("auto_tune", "")).lower() in AUTO_TUNE_MODES:
                    cfg.trading.auto_tune = str(t_data["auto_tune"]).lower()
                if isinstance(t_data.get("exit_hold_symbols"), list):
                    cfg.trading.exit_hold_symbols = [str(s).upper() for s in t_data["exit_hold_symbols"]]
                if "calibrated_policy_trader" in t_data:
                    raw = t_data["calibrated_policy_trader"]
                    cfg.trading.calibrated_policy_trader = (
                        raw if isinstance(raw, bool) else str(raw).strip().lower() in {"1", "true", "yes", "on"}
                    )
                if "forward_test_modes" in t_data and isinstance(t_data["forward_test_modes"], list):
                    cfg.trading.forward_test_modes = [str(m).strip().lower() for m in t_data["forward_test_modes"]]
                if "gate_policy_max_soft_fail" in t_data:
                    try:
                        cfg.trading.gate_policy_max_soft_fail = int(t_data["gate_policy_max_soft_fail"])
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"Ignoring invalid gate_policy_max_soft_fail={t_data['gate_policy_max_soft_fail']!r}: {exc}")
                if "gate_policy_min_recent_win_rate" in t_data:
                    try:
                        cfg.trading.gate_policy_min_recent_win_rate = float(t_data["gate_policy_min_recent_win_rate"])
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"Ignoring invalid gate_policy_min_recent_win_rate={t_data['gate_policy_min_recent_win_rate']!r}: {exc}")
                if "max_daily_entries_per_symbol" in t_data:
                    try:
                        cfg.trading.max_daily_entries_per_symbol = int(t_data["max_daily_entries_per_symbol"])
                    except (TypeError, ValueError) as exc:
                        logger.warning(f"Ignoring invalid max_daily_entries_per_symbol={t_data['max_daily_entries_per_symbol']!r}: {exc}")
                for _qk, _qcast in (("quarantine_expectancy_r", float), ("quarantine_window", int)):
                    if _qk in t_data:
                        try:
                            setattr(cfg.trading, _qk, _qcast(t_data[_qk]))
                        except (TypeError, ValueError) as exc:
                            logger.warning(f"Ignoring invalid {_qk}={t_data[_qk]!r}: {exc}")
                m_data = data.get("ml", {})
                ml_keys = (
                    ("sgd_learning_rate", "sgd_learning_rate", float),
                    ("sgd_l2_regularization", "sgd_l2_regularization", float),
                    ("brier_score_drift_threshold", "brier_score_drift_threshold", float),
                )
                for json_key, attr, caster in ml_keys:
                    if json_key in m_data and m_data[json_key] is not None:
                        try:
                            setattr(cfg.ml, attr, caster(m_data[json_key]))
                        except (TypeError, ValueError) as exc:
                            logger.warning(
                                f"Ignoring invalid ml.{json_key}={m_data[json_key]!r}: {exc}"
                            )
            except Exception as e:
                logger.warning(f"Could not load config/settings.json: {e}")

        env_mode = os.environ.get("JARVIS_MODE")
        if env_mode and env_mode.lower() in {"live", "paper", "demo"}:
            cfg.trading.default_mode = env_mode.lower()
        env_port = os.environ.get("JARVIS_PORT")
        if env_port and env_port.isdigit():
            cfg.server.port = int(env_port)
        env_symbols = os.environ.get("JARVIS_SYMBOLS")
        if env_symbols:
            cfg.trading.symbols = [s.strip().upper() for s in env_symbols.split(",") if s.strip()]
        env_calibrated = os.environ.get("JARVIS_CALIBRATED_ENTRY")
        if env_calibrated:
            cfg.trading.use_calibrated_entry_policy = env_calibrated.strip().lower() in {
                "1", "true", "yes", "on",
            }
        env_risk = os.environ.get("JARVIS_MAX_RISK_PCT")
        if env_risk:
            try:
                cfg.risk.max_risk_per_trade_pct = float(env_risk)
            except Exception as e:
                logger.warning(f"Ignoring invalid JARVIS_MAX_RISK_PCT={env_risk!r}: {e}")
        return cfg

SETTINGS = JarvisConfig.load()


def persist_auto_tune(mode: str) -> bool:
    """Set and persist trading.auto_tune ("off" | "dynamic")."""
    mode = str(mode or "").strip().lower()
    if mode not in AUTO_TUNE_MODES:
        return False
    SETTINGS.trading.auto_tune = mode
    return _persist_trading("auto_tune", mode)


def persist_allowed_symbols(symbols: List[str]) -> bool:
    """Atomically write the allowed_symbols list back to config/settings.json."""
    clean = [str(s).strip().upper() for s in symbols if str(s).strip()]
    if not _persist_trading("allowed_symbols", clean):
        return False
    SETTINGS.trading.symbols = list(clean)
    return True


def _persist_trading(key: str, value: object) -> bool:
    """Atomically write one trading.<key> back to config/settings.json."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    json_path = os.path.join(base_dir, "config", "settings.json")
    try:
        data = {}
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if "trading" not in data or not isinstance(data["trading"], dict):
            data["trading"] = {}
        data["trading"][key] = value

        temp_path = json_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, json_path)
        logger.info(f"💾 SETTINGS: Persisted trading.{key} to {json_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to persist trading.{key} to {json_path}: {e}")
        return False

