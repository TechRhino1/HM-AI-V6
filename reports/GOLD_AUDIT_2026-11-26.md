# Gold (XAUUSD) end-to-end audit — 2026-11-26

Branch `fix/gold-audit-2026-11-25`. All market data is real MT5 history (`data/market/real/XAUUSD`, broker symbol `GOLD.i#`, provenance `MT5_TERMINAL_REAL`). All trade data is the broker-synced ledger `data/jarvis_history.db → executed_trades`.

## 1. Verdict

**Gold has no proven, statistically significant edge in this system.** The live gates that refuse it today (HOLDOUT_GATE, UNSPLIT_RR_GATE, min-lot risk) are right to refuse it. This audit fixes real defects on the live order path and makes the gates consistent and fail-closed. It does **not** show a profitability improvement, because none was measured. Gold stays blocked under the promotion rule set before testing (§6).

## 2. Real P&L (XM demo account 101059540, 2026-08-24 → 11-24)

None of these trades used real money. 205 rows labelled `live` are demo trades (see §9).

| Slice | n | Win rate | PF | Avg win | Avg loss | Expectancy | Net | Max losing streak | Max DD |
|---|---|---|---|---|---|---|---|---|---|
| All closed | 315 | 27.6% | 0.42 | $10.60 | $9.68 | −$4.08 | **−$1,284** | 28 | $1,352 |
| Bot | 183 | 23.5% | 0.45 | $7.60 | $5.22 | −$2.21 | −$404 | 18 | $472 |
| Manual | 132 | 33.3% | 0.40 | $13.53 | $16.77 | −$6.67 | −$880 | 26 | $901 |
| Bot since 11-16 | 13 | 23.1% | 0.81 | — | — | −$0.90 | −$12 | 8 | $26 |

Bot R-multiples: mean −0.57R, median −1.00R. 83 of 121 bot trades had no take-profit set.

### Exact root causes of the losses, by size

1. **No edge in the signal.**
   - Every validated test is at or near zero: calibrated holdout −0.106R over 347 trades; engine-select best +0.044R (DSR 0.46); this audit's walk-forward holdout +0.062R (PF 1.09, §6).
   - Score-calibration AUC is about 0.52.
2. **Very short holds.** Trades held under 5 minutes: 128 trades, PF 0.19, −$600. Trades with no recorded duration: 91 trades, PF 0.15, −$540. Holds of 15 minutes to 24 hours are about breakeven.
3. **Stacking and bursts.**
   - Same-direction re-entries within 5 minutes: 120 trades, 19% win rate, −$363.
   - 2026-09-24: 139 trades in one day, 43 of them in a single minute, −$388. This was the order-retry duplicate bug plus manual stacking; the retry bug was fixed on 11-25.
4. **Manual trading:** −$880 of the −$1,284 total.
5. **Direction vs regime.** Bot BUYs won 18.9% while gold fell from about 4,660 to about 3,580.
6. **Sizing.** At about $480 equity, one 0.01 lot on a typical gold stop risks about 5.8%, above Gold's 3.5% cap. Gold can't be traded within policy at this account size.

### Things that are *not* causes

- **Costs.** XM charges no commission on this account, so commission = 0 is correct. Swap is recorded (20 non-zero rows). Spread is about 20 points ($0.20), steady across bars.
- **News.** Only 6 trades opened within ±30 min of FOMC/NFP/CPI, for −$10.

## 3. Why trades execute automatically

This is by design, not a bug. Every launcher starts the trading loop:
- `HM_start.py` defaults to live mode and falls back to the account type.
- Safe mode is off by default.
- `JARVIS_AUTO_STYLE_LIVE` defaults to 1.

Three routes reach an order:
1. **Legacy gate stack.** The decision engine says EXECUTE.
2. **Ranking-step promotion.** A WAIT is promoted when it is grade A/A+ with EV ≥ 0.40, R:R ≥ 1.4 and at most one failing check (`opportunity_arbiter.py:166-187`).
3. **Calibrated route.** `calibrated_policy_trader: true` turns a legacy NO_TRADE into a MARKET SWING order (`orchestrator.py` dispatch). Before this audit it checked only OOS expectancy, not the holdout (fixed, A2).

Two further unintended order paths existed and are fixed:
- `main.py --once` ("telemetry sweep") could send a real order.
- `jarvis.py start` ran without the single-engine lock.

To stop automatic trading: turn on safe mode from the dashboard, or start in `paper` mode.

## 4. Gate audit: what was fixed

| # | Defect | Effect | Fix |
|---|---|---|---|
| A1 | Calibrated TP rewrite (`execution_engine.py`) did not update `decision.tp_distance`, so the post-fill re-anchor restored the old target | A slipped fill put the broker TP at about 5R instead of the validated 1.5R (11-24 ledger: SELL 3622.88, SL 3640.88, TP 3533.08) | Keep `sl_distance`/`tp_distance` in sync with the rewrite. Test fails before, passes after. |
| A2 | The calibrated route used `evaluate_entry` (OOS only); the risk engine used `deployment_refusal` (OOS + holdout) | Journal showed PASS then REFUSE for the same order | `_calibrated_entry_decision` applies `deployment_refusal` first |
| A3 | Fail-open: `deployment_refusal` when settings fail to load; strategy-quarantine errors; premium daily-cap errors | A broken check authorised trades | All three now fail closed |
| A4 | Premium off-window floor was `min(profile, 68)` | Gold's 85 elite floor was lowered to 68 | Uses the profile floor |
| A5 | `jarvis.py` skipped the engine lock; `main.py --once` was not a dry run | Duplicate engines or orders possible | Lock taken; `--once` is `dry_run=True` |
| A6 | The same-symbol cooldown only applied with **no** position open | A second gold entry could stack seconds after the first | Cooldown applies with a position open; a stop-and-reverse flip still clears it |
| B | The verifier's min-lot sizing rule used 2.5% while the executor allows 3.5% for Gold | The verifier would reject Gold min-lot orders the executor accepts | The verifier uses `account_tier.min_lot_risk_cap` |

Checked and left alone:
- `config/symbol_profiles.json`: its spread/SL values are read by nothing in `jarvis/` (only `tools/mt5_data_audit.py` reads the symbol list). They are dead values, so treat `symbol_profile_config.py` and `symbol_registry.py` as the source of truth.
- Gold `session_restriction=False` (trades 24/5): the session P&L split doesn't support a change (London/NY overlap loses the most, Asia the least), so no session gate was added without a backtest showing a gain.
- Gates that never fired (ADAPTIVE_GATE 9/11/13, SPREAD_FILTER, etc.): they never fire because earlier gates refuse first. This is not a defect.

### Verifier enforcement: attempted, then reverted

The pre-send verifier would have blocked 0 of the 166 entries it checked in the backtests. But switching it to `enforce` failed 16 execution tests. It runs **before** the executor moves stops out to the broker's minimum distance, so it blocks orders the executor would correct ("stop inside broker stops_level"). It stays in `shadow`. To enforce it, move the call after geometry alignment in `execution_engine.execute_decision`.

## 5. Monitoring agent (extended, not duplicated)

`system_monitor.run_checks` gains `live_vs_calibrated`. The watchdog already runs it every 60 s, it is served at `/api/monitor`, and it alerts through `dispatch_alert`.
- For each symbol with at least 20 live closes (all strategies pooled, same ledger as strategy quarantine), it compares live mean R with the profile's OOS expectancy.
- WARN when live R is more than 2 standard errors below the OOS figure. CRITICAL when it is also below the quarantine bar (−0.15R).

The existing monitor already covered loop stalls, the position monitor, rejection spikes, verifier health, exposure, stops/gaps, circuit breaker, quarantine and loss cooldown.

## 6. Backtests: real MT5 data, before vs after

Cost model: the broker's median spread (20 points), 0.5-pip slippage on market exits (now also on stop and time-stop exits), and commission from the profile. Swap is not modelled.

### 6a. Production engine per style, 6 months (2026-05-18 → 11-16; SCALP 09-09 → 11-16 because the M1/M5 history is shorter)

`tools/backtests/run_mode_backtest.py --symbols XAUUSD --days 183`. "Before" = `main` (b263659), "after" = this branch. Per-trade files: `reports/gold_audit_before/`, `reports/gold_audit_after/`.

| Style | | Trades | Win rate | PF | Exp R | Net $ | Max DD | Sharpe | Max losing streak | 1st half R | 2nd half R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SWING | before | 40 | 17.5% | 0.57 | −0.200 | −315.79 | 5.40% | −1.47 | 15 | −0.81 | +0.41 |
| | after | 40 | 17.5% | 0.56 | −0.202 | −317.94 | 5.42% | −1.48 | 15 | −0.82 | +0.41 |
| DAY_TRADING | before | 40 | 42.5% | 1.85 | +0.421 | +699.13 | 3.00% | 1.70 | 6 | +0.29 | +0.55 |
| | after | 40 | 42.5% | 1.85 | +0.420 | +697.98 | 3.01% | 1.69 | 6 | +0.29 | +0.55 |
| SCALP | before | 86 | 25.6% | 1.45 | +0.131 | +300.07 | 0.98% | 1.21 | 11 | +0.03 | +0.23 |
| | after | 86 | 25.6% | 1.45 | +0.130 | +298.12 | 0.98% | 1.20 | 11 | +0.03 | +0.23 |

Reading these numbers:
- **Before and after take the same trades.** The fixes are on the live dispatch path (re-anchor, route parity, fail-closed gates, cooldown, locks), which this offline engine doesn't exercise. The only measured change is honest stop-exit slippage, about −$2 per style.
- **DAY_TRADING's +0.42R is not evidence of an edge.** It is 40 trades, 33 of them SELLs during a 23% gold decline, and BUYs lose (−0.45R). That's a trend-regime result.
- **SCALP's +0.13R is thin.** It covers 68 days, with 83 of 86 trades SELLs.

### 6b. Walk-forward / out-of-sample (the promotion test)

- **Training:** `calibrate_winrate.py --symbols XAUUSD --days 730 --wide-grid --train-end 2026-05-21 --purge-days 3`, using purged k-fold (now embargoed on both sides).
- **Holdout:** that profile was scored by the production engine on the unseen 2026-05-24 → 11-24 holdout (`run_3month_backtest.py --start 2026-05-24`). Reports: `reports/gold_audit_holdout_2026-11-26.md` and `.json`.

| | Trades | Win rate | Exp R | PF | Net $ | Max DD | Sharpe | PSR / DSR |
|---|---|---|---|---|---|---|---|---|
| Calibrator's own OOS claim (simulator) | 587 | 65.2% | +1.255 | 4.60 | — | — | — | DSR 0.24 |
| **Production engine on the holdout** | 529 | 41.2% | **+0.062** | **1.09** | +515.62 | 8.03% | 0.63 | 0.85 (with 1 trial) |

The simulator's +1.25R falls to +0.06R in the real engine. This is the known simulator-vs-engine gap, and simulator numbers must never be used for go-live.

**Promotion rule** (set before running): holdout expectancy > 0 over ≥ 100 trades, PF > 1.1, DSR ≥ 0.95, both halves positive, and min-lot risk within the cap.
- **Result: FAIL.** PF is 1.09, DSR is < 0.95 even before correcting for the 320-trial search, and min-lot risk is about 5.8% against a 3.5% cap.
- **Gold stays blocked.** Nothing was promoted and `config/winrate_profiles.json` is unchanged.

The PurgedKFold fix produced an identical XAUUSD profile before and after: at this candidate density the extra embargo removes no training trade that changes the selection.

## 7. Files changed

| File | Change |
|---|---|
| `jarvis/execution/execution_engine.py` | A1 |
| `jarvis/application/orchestrator.py` | A2, A3 (quarantine, premium cap), A4, A6, drift-monitor inputs |
| `jarvis/backtesting/exit_geometry.py` | A3 (deployment gate fails closed) |
| `jarvis.py`, `main.py` | A5 |
| `jarvis/risk/trade_guard.py` | B |
| `jarvis/backtesting/engine.py` | Slippage on stop/time exits; dead cost variables removed |
| `jarvis/learning/walk_forward.py` | Two-sided embargo; `threshold_optimize` takes `probs`, not outcomes |
| `jarvis/observability/system_monitor.py` | `check_live_drift` |
| `tests/test_gold_audit_2026_11_26.py` (new) | Tests for A1, A2, A3 and the drift check |
| `tests/test_advanced_modules.py` | Tests for the purge and the look-ahead fix |
| `tests/test_dispatch_vetoes.py` | Updated: quarantine errors now veto |

No SMC/ICT modules were added. Structure, BOS/CHoCH, order blocks, FVG, liquidity sweeps, SMT, order flow, ATR regimes, MTF, news and session filters all already exist and are wired in. Earlier gold research found no significant edge from them, so adding more would be untested complexity.

## 8. Testing

- The full suite ran on an isolated worktree, so the running engine's databases were not touched.
- With the verifier in enforce: 4,030 passed and 19 failed.
- The 16 enforce-caused failures pass once the verifier is back in shadow (re-run of those 16).
- The other 3 also fail on `main`: options-math, and two symbol-universe tests that read the local `allowed_symbols`.
- New regression tests: 7, all passing. The A1 test was confirmed to fail without the fix.

## 9. Remaining limitations and recommendations

1. **Keep Gold off live** until a candidate passes §6b's rule. Re-run the holdout monthly; the drift monitor will flag decay on anything that is live.
2. **Manual trading lost −$880.** The biggest single lever is to stop manual gold trades, especially stacked bursts.
3. **Account size.** Gold's minimum lot can't fit a 3.5% risk cap below about $800 equity on a typical $18 stop.
4. **Verifier to enforce:** move the call after broker-stop alignment first (§4).
5. **Ledger cleanup.** 205 demo rows are labelled `live`. Relabel them, with a backup, once you approve: `UPDATE executed_trades SET execution_mode='demo' WHERE origin='broker' AND execution_mode='live' AND account_login=101059540`.
6. **Not changed** (noted in earlier audits):
   - the live strategy bandit only learns in shadow
   - per-regime target geometry isn't used live
   - swap isn't modelled in backtests
   - the backtest spread is one median per run (immaterial for gold: std 1.6 points)
7. **The running engine** (`HM_start.py`) still has the old code loaded. These fixes take effect after a restart.
