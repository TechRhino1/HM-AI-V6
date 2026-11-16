# HM Algo — platform upgrade report (2026-11-16)

Seven commits on `main`, `4613603..180381f`, each with tests that fail on the previous code. The full suite was compared against the previous phase after every commit: 3,631 passed; the 29 failures are all pre-existing, unchanged since before Phase 1. Nothing is pushed. The running engine still uses the old code until restarted.

## A. Audit — verified issues (code + data)

**Security / execution safety**
1. Every data API (account, positions, history, radar, pending orders, tunnel URL) was readable without login through the public cloudflared tunnel; only `/api/admin/*` was gated. A TRADER could lift a risk halt.
2. The watchdog released a symbol's execution lock when the *previous* execution was >60 s old — true for almost every new order — so the duplicate-order lock could be freed mid-dispatch.
3. An UNKNOWN-outcome order's risk reservation expired after 15 s. No single-instance guard. Shutdown only on Ctrl-C, with `mt5.shutdown()` possibly mid-order. `cancel_pending_order` had no timeout.

**Risk**
4. Contradictory small-account limits: min-lot cap 5% > daily halt 4%; per-trade caps of $2.50 / $5 / $12 / $20 (BTC) / $28 (gold) in four places; a micro boost to 1.25–2.5% per trade; nano accounts silently got 6% daily / 12% total. No weekly limit and no pre-trade margin check.
5. Position sizer float bug: an exact 0.02-lot budget computed as 0.0199999 and was floored a full step (masked by a "milestone" round-up that could exceed the budget).

**Self-learning**
6. Live behaviour changed itself on every close with no validation, version or rollback: online-ML weights (55% of win probability), strategy bandit, calibration curve. Threshold loosening after winning streaks; a gate policy silently lowered its 0.45 floor to 0.30 to skip up to 3 gates; the LLM governor could raise risk to 1.25×. Two emitted gates were unregistered (treated as softenable).

**Backtest validity**
7. The backtest's macro analyst scored every historical bar against **today's live economic calendar** (look-ahead; −5 per upcoming USD event). The post-news boost compared today's releases with the wall clock, so identical runs differed by the time of day they were run. Style-mode runs fed H1 bars to M5/M15 roles. MTF slicing was quadratic. Monte Carlo was unseeded.

**Traceability**
8. No account id in either journal (82 old-account rows indistinguishable). No exit reason, SL-change history or cost columns. MFE/MAE only in memory. Nothing wrote the decision journal. Production logs went to the console only. `scipy` was undeclared.

## B. Implemented (by commit)

| Commit | Change |
|---|---|
| `4613603` | Login for every `/api/` route except the auth flow (localhost stays auto-admin); resume/reset-drawdown ADMIN-only; Secure cookie via tunnel. Watchdog ages locks by claim time; UNKNOWN orders hold their reservation 10 min; one engine per mode (OS lock); SIGTERM/SIGBREAK → clean shutdown that waits for in-flight orders; cancel timeout; pending timeout = UNKNOWN. |
| `6a2f1be` | **Risk policy (approved):** 1% target, min lot ≤ 2.5% else skip, daily 5%, **weekly 10% (new)**, max DD 20%, one source in `config/settings.json`. Duplicate caps and the micro boost removed. Pre-trade margin check counts the new order (≤ 40%). Sizer float fix. |
| `4a25738` | `jarvis/learning/model_registry.py` (immutable versions, active pointer, audit log); live loads frozen versions, shadows learn; `tools/promote_model.py` (prequential out-of-sample promotion for the ML model, operator-approved bandit, rollback). No live refit, no loosening; governor may only reduce risk and is audited; gates registered. |
| `ffccd2d` | Backtest gets no live calendar; post-news boost off in backtests; bar clock in risk engine; `mtf_frames` real per-TF bars; O(log n) MTF slicing; seeded, vectorised Monte Carlo; new metrics (max losing streak, payoff, recovery factor, avg R, risk of ruin). |
| `022da98` | Journal migration 6: account/server, strategy, style, planned RR, exit reason (engine > broker), commission, swap, MFE/MAE; `sl_events` table; decision journal (`data/decisions/*.jsonl`); `GET /api/analytics/performance?by=symbol|strategy|trade_style|account_login|exit_reason`. |
| `d56be31` | LIQUIDITY_SWEEP_REVERSAL disabled for every symbol (evidence below). |
| `180381f` | Rotating JSON log file `data/logs/hm_engine.log`; `scipy` declared. |

## C. Strategy research and evidence

- **Reversal detection** (12 months H1, EURUSD/GBPUSD/BTCUSD): no signal predicts direction (hit rates 0.45–0.52 vs ~0.49–0.51 base).
- **Gold** (`reports/GOLD_RESEARCH_2026-11-16.md`): the HTF trend filter is the one robust ingredient. The DAY trend-pullback was best (PF 1.12) but failed the both-halves rule. SCALP has no edge; session sweep and Asian breakout lose.
- **Live demo expectancy by strategy** (trade memory, pnl / dollar risk):

| Strategy | n | Avg R | ± s.e. |
|---|---|---|---|
| TREND_PULLBACK | 99 | −0.06 | 0.06 |
| TREND_FOLLOWING | 88 | −0.21 | 0.09 |
| CHOCH_STRUCTURAL_REVERSAL | 47 | −0.08 | 0.06 |
| LIQUIDITY_SWEEP_REVERSAL | 33 | −0.21 | 0.09 |
| RANGE_MEAN_REVERSION | 15 | +0.17 | 0.26 |

- **Adopted:** disable LIQUIDITY_SWEEP_REVERSAL (three independent sources agree).
- **Rejected:** no other change has enough evidence. Statistical arbitrage (single small CFD account), Market Profile (tick volume only), fractional Kelly (no stable edge to size from), a full async rewrite (scan already concurrent).
- **Gold's live losses:** the institutional engine caps gold stops at $18 while H1 ATR is 13–40, so stops sit inside one bar's range. 36 of 37 gold trades in the original backtest lost exactly −1R.

## D. Performance comparison (identical frozen MT5 H1 data, 8 symbols, real spreads, commission, slippage)

| | Original (`437e3dd`) | Improved (`d56be31`) |
|---|---|---|
| Trades | 110 | 83 |
| Win rate | 20.9% | 22.9% |
| Avg R per trade | −0.331 | −0.256 |
| Total R | −36.4 | −21.3 |
| Profit factor | 0.51 | 0.63 |
| Longest losing streak | 30 | 21 |

Per symbol: ETHUSD moved from −0.06R to +0.03R (37 → 22 trades). XAUUSD stays at −0.9R per trade. The others are unchanged or too thin (SOLUSD and USDJPY took 0 trades; EURUSD and GBPUSD fewer than 4). **Both systems lose; the improved one loses less.** Sharpe and Sortino are not meaningful with these samples. Risk of ruin (50% loss) is 0% for both because sizes are small. The original journal R figures also flatter: earlier rows stored the trailed stop instead of the initial one (fixed in the earlier audit).

## E. Production-readiness checklist

| Area | Status |
|---|---|
| Security (auth, roles, cookie) | ✅ done; tunnel still public by design (your choice) |
| Duplicate-order / recovery safety | ✅ locks, reservation hold, single instance, graceful stop; ⚠ no order idempotency key |
| Risk management | ✅ unified, weekly limit, margin check; ⚠ loss-cooldown not persisted |
| Self-modification control | ✅ frozen + audited + rollback |
| Trade traceability / analytics | ✅ journal v6, SL history, decision journal, API; ⚠ no dashboard panel yet |
| Backtest validity | ✅ calendar leak and wall-clock fixed; ⚠ loop still steps hourly |
| Logging | ✅ rotating file; ⚠ alerts still only on 2 events |
| **Profitability** | ❌ **no demonstrated edge** — live and backtest |
| Deployment | ⚠ demo only; restart needed; real money **not** advised |

## F. Remaining issues (not done or not verified)

1. **No positive-expectancy strategy exists.** Recommended operator decision: keep trading on demo only, and consider pausing TREND_FOLLOWING (−0.21R live) until a validated strategy exists.
2. Not done from the plan:
   - regime hysteresis and a unified offline/live regime tagger;
   - the isotonic probability map replacing the boost stack;
   - correlation-aware ranking (Phase 7);
   - gold volatility-normalised stops;
   - dashboard panels (health, trailing state, analytics, learning status);
   - alerts;
   - a validated config schema;
   - dead-code removal (`calibration_engine`, `decision_battery`, `state_snapshot`, `split_guard`, `ensemble_bandit`);
   - persisted loss cooldown;
   - order idempotency key.
3. **Startup fallback orchestrator:** importing `intelligence_api` starts a pre-warm thread that can build a fallback orchestrator before HM_start's own exists. It never trades (no `start()`), but it is wasted startup work.
4. **Not verified live:** the new code has not run against the broker. On restart:
   - the journal migrates to v6 and the drawdown DB to v2;
   - the live ML/bandit state is frozen as v1;
   - the login requirement applies to your phone (sign in once).
5. **Demo effect of the risk policy:** gold and BTC min-lot trades are capped at $13.63 at today's $545 equity, so wide-stop setups on those symbols are skipped.
