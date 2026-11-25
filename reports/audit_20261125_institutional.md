# Institutional audit — 2026-11-25

Branch `audit/institutional-2026-11-25` (off `910237c`). All numbers below come from
real XM MT5 history cached under `data/market/real` (provenance manifests, no synthetic bars).

## Method
- Four independent read-only audits (risk sizing, exits/SL-TP, backtest look-ahead/MTF,
  order execution). Every finding below was re-verified against the code before it was fixed.
- Tests: full suite on a clean worktree of HEAD vs. the patched tree.
- Backtest: `tools/backtests/run_mode_backtest.py --styles SWING,DAY_TRADING` (183 d,
  style-aware real MTF, profile=none) on both trees, same data.

## Defects fixed (13)

| # | Area | File | Defect | Effect |
|---|---|---|---|---|
| 1 | Execution | `execution/mt5_client.py` | Market-order retry loop re-sent on any non-OK code (10010 partial, 10019 no money, 10018 closed, …) | Up to 3 duplicate positions; journal under-reported volume |
| 2 | Execution | `execution/mt5_client.py` | 10031 (CONNECTION) treated as a filling error; 10020/10021 re-sent at the stale price | Extra sends on a dead link; avoidable rejects |
| 3 | Execution | `execution/mt5_client.py` | Partial close (10010) reported FAILED | Caller re-sends; scale-out executed twice |
| 4 | Sizing | `execution/mt5_client.py` | Live `symbol_info` failure returned EURUSD-shaped defaults (1.0 / 0.0001) | FX lots up to 10x oversized; now uses the symbol registry, uncached |
| 5 | Risk | `risk/risk_engine.py` | Portfolio risk budget ran before sizing, never counted the new trade | Book could exceed the 2.5 % cap (2.4 % + 1 % = 3.4 %) |
| 6 | Sync | `execution/mt5_client.py`, `state_synchronizer.py` | A failed broker read (`None`/exception/disconnect) looked like "flat" | Book emptied, POSITION_CLOSED fired for every ticket, symbol limits saw 0 |
| 7 | Execution | `application/orchestrator.py` | Inline trailing and stop-and-reverse acted on positions without our magic | Manual / other-EA trades could be modified or closed |
| 8 | Execution | `execution/position_monitor.py` | Magic number hard-coded (888999) | A configured magic made every bot trade "manual" (exits off) |
| 9 | Sizing | `risk/position_sizing.py`, `mt5_client.py`, `execution_engine.py` | Lot rounding from `log10` / fixed decimals / round-to-nearest | Steps 0.5 / 0.05 / 0.001 rounded lots UP past the risk budget |
| 10 | Risk | `risk/circuit_breaker.py` | Served cooldown zeroed the loss streak | Losing faster restored 1.0x size sooner; streak sizing bypassed |
| 11 | Backtest | `backtesting/engine.py` | Stray `else` nulled H4/D1 frames on the legacy (no `trade_style`) path | `run_3month_backtest`, `engine_select`, walk-forward ran with no HTF context |
| 12 | Backtest | `backtesting/engine.py` | Partial booked on the same bar the starting stop was hit; gap-through stops filled at the stop | Optimistic results |
| 13 | Calibration | `backtesting/exit_geometry.py` | BE/trail ratcheted on a bar's high, then tested against the same bar's low | Same-bar look-ahead inflated calibrated OOS expectancy |

Regression tests: `tests/test_audit_2026_11_25_fixes.py` (11 tests).

## Backtest before / after (real MT5, 183 d, 8 symbols with full cached MTF data)

26 of 42 symbol/style jobs had no cached 183-day multi-timeframe frames in either run and
were skipped identically; results cover the 16 that ran.

| Style | Trades | Exp R before | Exp R after | Total R before | Total R after | Positive symbols |
|---|---|---|---|---|---|---|
| SWING (H1) | 168 | +0.0821 | +0.0821 | +13.79 | +13.79 | 6/8 |
| DAY_TRADING (M15) | 515 | −0.0327 | −0.0333 | −16.83 | −17.17 | 2/8 |

Interpretation:
- The style-aware path the live bot uses was already causal for HTF bars, and same-bar
  partial+stop / gap stops are rare at H1/M15, so fixes 11–13 move these numbers by one
  trade (USDCAD DAY). Their effect is on the legacy engine path and on calibration output.
- Fixes 1–10 are live execution/risk defects; a bar backtest cannot measure them.
  They are covered by the regression tests.
- 168 SWING trades at +0.08 R is not statistically distinguishable from zero.
  DAY_TRADING is negative. **No trading style has demonstrated a robust edge**, consistent
  with `reports/six_month_multimode_report.md`.

## Found, not fixed (need a decision or a larger change)
- **Calibrator/live mismatch:** `exit_geometry.to_policy` drops scale-out legs and keeps
  `profit_locks=True`; live never executes the calibrated ladders, so calibrated OOS
  expectancy is not what live earns. Time stops also differ (calibrator unconditional,
  live only below +0.10 R).
- **Optimizer leakage:** score-quantile threshold fitted over the whole series including
  validation (`optimizer.py:229-265`, `regime_optimizer.py:336`); train/test split by bar
  index across symbols with different bar density; no purge. Walk-forward folds overlap
  and fit nothing.
- **OrderManager (only when the monitor is off):** SELL trail measured from bid; R
  recomputed from the current stop after restart; partial never executed.
- **Exposure:** currency-concentration check only runs on second trades.
- **Account type:** hedging assumed; netting accounts not detected.
- **Backtest costs:** no slippage on SL/time-stop exits, no entry slippage, constant spread.
- **Sizer:** combined deleveraging floored at 0.25x; per-trade ceiling inflated by
  `vol_scalar` before it is applied (the execution ceiling re-caps it).

## Not done from the brief
Per-style / per-timeframe / per-symbol recalibration, a new MTF scoring engine, AUTO-mode
ranking changes and regime-selection changes. Recalibrating before the leakage items above
are fixed would optimise against a biased evaluator; doing it after needs those fixes first.
