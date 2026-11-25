# Gate audit, pre-send Verification Agent & monitoring — 2026-11-25

Branch `feat/gate-trace-verifier` (off `audit/institutional-2026-11-25`, PR #18).
Plan: approved "foundation first" scope. Recalibration is a separate, later plan.
User decisions:
- forward tests pass the same hard risk gates;
- the verifier fails closed;
- the LLM is advisory and off the hot path.

## Status legend
- **DONE**: implemented, wired into the live path, tested.
- **SHADOW**: implemented and wired, but records only until switched to `enforce`.
- **PENDING**: not done.

## 1. Inventory: what existed (research phase)
- **Gates.** About 45 distinct gates on the live path; the full table is in the session research.
  - Only `orchestrator._orchestration_loop_single_pass` (the arbiter dispatch) sends orders. The per-symbol scans run `dry_run=True`.
  - In order, the gate families are:
    1. scan quality gate (33 checks);
    2. calibrated entry policy;
    3. confidence gate;
    4. dispatch vetoes;
    5. arbiter `is_exec_ready`;
    6. UNSPLIT R:R;
    7. slot / cooldown checks;
    8. `RiskEngine.authorize_execution` (deployment / holdout, circuit breaker, drawdown, heat, exposure, `TradeGuard`, correlation, sizing multipliers, backstops);
    9. arbiter news blackout;
    10. execution-engine ceilings.
- **Agents.** ParallelAnalystCluster + DevilAdvocate (pre-gate penalty), LLM governor (per symbol, async, reduce-only), TradeGuard (pre-sizing). **No pre-send verifier existed.**
- **Monitoring.** Watchdog (10 s), state sync (1 s), AlertManager, metrics registry, decision journal.
  - Nothing read the journal.
  - `_last_heartbeat` was never updated.
  - There were no per-gate metrics.
- **Governance.** `model_registry` + `promote_model.py` covered only online_ml and strategy_bandit. Live config JSON files were overwritten in place.
- **Baseline (live journal, 2026-11-25, old code).**
  - 34,258 scan rows. First refusal reason: HOLDOUT_GATE 14,879, CALIBRATED_ENTRY 10,789, NEWS_BLACKOUT 5,163, EXPECTANCY_GATE 3,284.
  - Only 270 dispatch rows: 269 TIMEFRAME_CONFLICT vetoes and 1 fill.
  - Every arbiter-stage refusal between those was log-only and invisible to analysis.

## 2. Defects found and fixed

| # | Defect (root cause) | Fix | Status |
|---|---|---|---|
| G1 | Quarantine read the **demo** ledger on a live account (`decision_engine.py`, risk-engine sizing multiplier: no `execution_mode`) | Reads the account's ledger plus demo (union, so it never loosens). Mode-switch keeps it in sync. | DONE |
| G2 | Forward tests sent orders directly, skipping the risk engine, per-symbol cap, ceilings and (2 of 5) news. This caused the 4×EURUSD stack. | `gated_forward_entry`: shared hard gates (`RiskEngine.authorize_forward_test`) + SAFE MODE + pre-send verifier, then their own order (geometry untouched) | DONE |
| G3 | Manual dashboard orders bypassed every gate | Shadow verification + journal row `origin=manual` (operator override kept) | DONE |
| G4 | Most arbiter refusals log-only; BLOCKED rows without a reason | GateTrace on every attempt; `blocked_by` journaled | DONE |
| G5 | `HARD_SYMBOL_LIMIT` reason appended twice | One reason (keeps the established prefix) | DONE |
| G6 | NEWS_BLACKOUT reason said 10m/15m; constants are 30/30 | Built from the constants | DONE |
| G7 | News-blackout logic lived in an orchestrator method (unusable by the verifier or forward tests without an upward import) | Moved to `market.news.is_entry_blackout`; orchestrator delegates | DONE |
| G8 | Execution-engine pending dedup counted forward-test and foreign pendings | Own-magic, non-forward-test only | DONE |
| G9 | Elite bypass (ai≥80) overrode the calibrated policy, incl. "regime disabled by learned policy", unvalidated | `gates.elite_bypass_enabled=false`. When on: deployment gate must pass and it never beats a learned regime ban. | DONE (tightening) |
| G10 | WAIT promoted by `is_exec_ready` despite scalp Cost Friction / quality floor / confidence < 0.45 | `_promotion_hole` | SHADOW (`gates.promotion_hole_mode`) |
| G11 | R:R floor in 6 places; execution engine judged a stale TP with no calibrated exemption | `TradeGuard.rr_assessment` single source; execution engine compares | SHADOW (`gates.rr_floor_mode`) |
| G12 | "Asian window conflict" | **Not a conflict**: trade_guard 1-5 UTC is a crypto spread allowance, orchestrator 0-6 UTC a non-crypto blackout. The misleading comment was corrected. | DONE (no logic change) |
| G13 | No loop-liveness check; analyst fallbacks uncounted | Heartbeat + monitor; `ANALYST_FALLBACKS` metric | DONE |

## 3. Pre-send Verification Agent (extends TradeGuard, no new agent module)
- **Where.** `TradeGuard.verify_pre_send` runs at ONE choke point: `ExecutionEngine.execute_decision` (wrapper; the old body is `_execute_decision_impl`). Forward tests call the same `_pre_send_verify`.
- **Rules.**
  - Risk rules (failure gives BLOCKED_RISK): `stale_data`, `sl_tp_geometry` (side, broker stops_level, SL distance in ATR), `sizing_budget` (order $ risk vs equity × risk %, with the min-lot allowance), `exposure` (per-symbol count **incl. forward tests**).
  - Signal rules (failure gives REJECTED): `signal_age`, `price_drift` (fresh tick vs entry, in ATR), `rr_floor` (single source), `mtf_alignment` (hard TIMEFRAME_CONFLICT), `conflict` (open opposite position), `duplicate` (same symbol+side+origin inside the window), `news_window` (shared blackout).
- **Fail closed.** An exception or a blown time budget gives BLOCKED_RISK.
- **Modes.** `verifier.mode`: off | shadow (default) | enforce. Shadow records `SHADOW_REJECT` in the GateTrace, metrics and `/api/verifier/recent` without blocking.
- **Outcomes.** APPROVED / REJECTED / BLOCKED_RISK are produced. NEEDS_ANALYSIS is defined but no rule emits it yet (no rule has an "insufficient evidence" state that should not simply pass). PENDING by design.
- **Backtest parity.** `BacktestEngine` runs the same verifier in shadow at every entry and reports `verifier_would_block` per rule. Trades are unchanged.

## 4. Monitoring & advisory
- **System monitor.** `observability/system_monitor.py` checks, every 60 s from the existing watchdog (no new thread):
  - loop stall (CRITICAL);
  - no order for N hours, with the top blockers;
  - 30-min rejection spike vs the 24 h average;
  - analyst-fallback rate;
  - verifier error/timeout rate (CRITICAL, because the verifier fails closed);
  - forward-test exposure as a share of the risk budget.

  Results go through debounced `dispatch_alert`. `/health` and `/ready` return 503 on a stalled loop.
- **Position-monitor heartbeat** (added after a live check found no proof-of-life for the 2 s position manager, which is silent while idle):
  - `PositionMonitorEngine` records `last_tick_at` / `tick_errors` every tick, even when the tick raises.
  - The watchdog reports CRITICAL if the thread is dead or hasn't ticked for `monitor.position_monitor_stall_s` (30 s), and WARN on tick errors or when there are open trades with no monitor.
  - The status is shown in `/api/monitor` and in System → Health.
- **Advisory.** `llm_controller.review_operations`: hourly, background, reuses the governor provider and backoff. It writes `data/advisories/*.jsonl`, which nothing on the trading path reads, and does nothing without a provider.

## 5. Governance
- **Mechanism.** `model_registry.governed_write` / `deploy_version` / `check_param_bounds`, plus `config/param_bounds.json`.
- **Coverage.** Live `config/settings.json` (dashboard persists, incl. auto-tune symbol changes), `config/winrate_profiles.json` (WRProfileStore + calibrate_geometry + engine_backed_calibration) and `devil_gate_calibration.json`.
- **Behaviour.** v1 is bootstrapped from today's file. Every change is versioned, sha-stamped and audited.
  - Bounds violations are refused.
  - A change of more than `governance.max_auto_delta_pct` on a bounded key is held PENDING until `promote_model.py approve`.
  - `promote_model.py rollback` restores the file byte-for-byte.

## 6. API & dashboard
- **Endpoints.** `/api/monitor`, `/api/gates/stats`, `/api/decisions` (journal reader), `/api/verifier/recent`.
- **Views.** System → **Health** (checks, verifier verdicts, advisory, rollout switches). Analytics → **Gates** (blockers, shadow would-blocks, decision trace with the per-gate path).

## 7. Tests & validation
- **New test files** (all passing):

  | File | Tests |
  |---|---|
  | `test_gate_trace.py` | 7 |
  | `test_gate_fixes_phase2.py` | 5 |
  | `test_pre_send_verifier.py` | 20 |
  | `test_forward_test_gating.py` | 4 |
  | `test_system_monitor.py` | 8 |
  | `test_config_governance.py` | 5 |
  | `test_monitoring_api.py` | 5 |

- **Full suite.**
  - Clean baseline worktree at 9925012: 3 failed / 4116 passed.
  - This branch: 4169 passed. Failures: the same 3 pre-existing tests, plus one new test that was order-dependent. Its cause (the API preferring the in-memory buffer over the journal) was fixed and the test now passes in the file run. The full suite was not re-run after the final review fixes; the 76 affected/new tests were.
  - With a `-k` selection, `test_trade_guard.py` shows 5 spread failures on BOTH the baseline and this branch (pre-existing cross-test pollution).
- **Frontend.** `tsc -b` clean, vitest 38/38, `vite build` OK; the committed bundle `jarvis/ui/static/app` was rebuilt.
- **Real-MT5 backtest** (183 d, 16 symbol/style pairs with cached MTF data; same data before/after):

  | Style | Trades before / after | Total R before / after |
  |---|---|---|
  | SWING | 168 / 168 | +13.79 / +13.79 |
  | DAY_TRADING | 515 / 515 | −17.17 / −17.17 |

  Identical by design: everything new is shadow or telemetry.
- **Verifier shadow tally** (per backtest entry):
  - First run: **168 / 683 would block, all `sl_tp_geometry`**. The cause is a calibration flaw in the new verifier: structural H4/D1 stops measured 8–22× the primary-timeframe ATR on validated trades, against a ceiling of 8.
  - The ceiling was recalibrated to 30 ATR (an order-of-magnitude guard; bound 60).
  - Re-run: **1 / 683 would block** (one `sl_tp_geometry` outlier, to be reviewed before enforcing).
  - Shadow mode caught this exactly as intended. Enforcing first would have cut a quarter of trades.
- **Independent code review** (python-reviewer) findings, all fixed:
  - pending-dedup loosening reverted;
  - R:R enforce mode made purely additive;
  - `POSITION_CONFIRMED` treated as sent;
  - `note_sent` guarded;
  - governed writes skip unchanged content;
  - settings governance keyed to the real file path;
  - non-object config sections ignored.

  No order path sends more than before.
- **Not verified:** the new dashboard tabs in a running browser (see §8).

## 8. Remaining limitations / pending
- Shadow switches (`verifier.mode`, `gates.rr_floor_mode`, `gates.promotion_hole_mode`) must be reviewed on demo before `enforce`. Rollout criteria:
  - at least 72 h of shadow;
  - timeout rate below 0.5%;
  - every would-block reason checked by hand.
- In the main engine path, forward-test positions count toward the symbol cap only through the verifier's `exposure` rule, so that becomes binding at `enforce`.
- **Check before enforcing:**
  - the `duplicate` rule (600 s per symbol, side and origin) and the `exposure` rule would also block a legitimate second trade on a symbol;
  - with `HARD_MAX_TRADES_PER_SYMBOL=2`, Donchian systems 3+ on one symbol are now refused (forward tests are gated by default).
- The dashboard views are type-checked, built and API-tested, but were **not** viewed in a running browser. Running a second engine would reuse the live tunnel's public subdomain.
- Deferred to the next plan:
  - per-symbol / per-style / MTF recalibration;
  - the optimizer leakage fix;
  - calibrator↔live exit-ladder mismatch;
  - `merge_realised`;
  - trade-DB timeframe column;
  - NEEDS_ANALYSIS rules;
  - order_manager SELL-trail / R-recompute fixes.
