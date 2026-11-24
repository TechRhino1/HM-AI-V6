# Full-system audit + 6-month per-symbol backtest — 2026-11-24

Real MT5 H1 data only (`data/market/real/SYM/SYM_H1_730d.parquet`, provenance `MT5_TERMINAL_REAL`,
fetched 2026-11-18, last bar 2026-11-18 09:00 UTC). No synthetic values. Nothing committed.

## 1. Verdict

**No symbol shows a real out-of-sample edge over the last 6 months.** In the true walk-forward test
(calibrate on data before 2026-05-19, trade 2026-05-19 → 2026-11-18 through the real `BacktestEngine`),
every symbol that traded has expectancy ≤ +0.012R and DSR < 0.05. The only positive one (USDCAD +0.012R,
PF 0.92, DSR 0.047) is noise. The portfolio lost −0.073R/trade (PF 0.79, max DD 50%).

The calibration simulator's OOS numbers (e.g. XAUUSD +0.204R, PF 1.40 on its own OOS folds) do **not**
survive the engine on the following 6 months (XAUUSD −0.106R). That divergence is the main risk in the
current pipeline (see §6).

## 2. Audit — fixed

| # | Item | Fix | File |
|---|------|-----|------|
| 1 | Broker-history sync labelled every row `execution_mode='live'`, even on demo accounts | Uses `account_info().trade_mode` → demo/live/unknown | `jarvis/data/database.py` (`sync_mt5_history`) |
| 2 | `/api/risk_status` returned hard-coded placeholder `hrp_weights` (fake numbers) | Returns `{}`; test updated | `jarvis/risk/risk_engine.py`, `tests/test_bugatti_ui_and_endpoints.py` |
| 3 | Orchestrator ignored `trading.magic_number` setting (hard-coded default) | Reads the setting (value 888999, unchanged behaviour) | `jarvis/application/orchestrator.py` |
| 4 | `WRProfileStore.merge_realised` dropped the profile-file `meta` on save | Keeps meta; test added | `jarvis/intelligence/winrate_targeting.py` |
| 5 | No way to calibrate on a train window only (so no honest holdout) | `--train-end`, `--purge-days`, `--out` | `tools/calibrate_winrate.py` |
| 6 | Backtest runner fixed to a 3-month window, no DSR, no feedback path | `--days/--start/--profiles/--out/--n-trials/--stamp`; per-symbol max DD (R), PSR, DSR | `tools/backtests/run_3month_backtest.py` |
| 7 | Live gate had no walk-forward evidence | New `HOLDOUT_GATE` in `deployment_refusal` (holdout ≤ 0R over ≥ 10 trades → refuse) + 4 new profile fields | `jarvis/backtesting/exit_geometry.py`, `winrate_targeting.py` |

Tests: `tests/test_holdout_gate.py` (4 tests). Full suite after changes: **3 failed / 4113 passed** — the same
3 failures as before my changes (below), no new ones. Paper DBs restored after the run.

## 3. Audit — flagged, not changed (need a decision)

- **`forward_test_modes` includes `"live"`** (uncommitted user edit in `config/settings.json`). DonchianForwardTest,
  research leads and trend_router would then trade live **without** `RiskEngine.authorize_execution`
  (`kn_adaptive` is hard-coded demo-only; `session_leads` is empty). Live still needs `JARVIS_CONFIRM_LIVE=1`.
- **205 mislabelled broker rows** in `jarvis_history.db` (`execution_mode='live'`, account 101059540 = demo). Fix #1 stops new ones;
  backfill needs your OK: `UPDATE executed_trades SET execution_mode='demo' WHERE origin='broker' AND execution_mode='live' AND account_login=101059540`.
- The two trade stores (`trade_records` vs `executed_trades`) are never reconciled; `trade_records` has no `execution_mode`
  column, so AutoStyleSelector mixes paper/demo/live/FT outcomes.
- UI Performance view defaults to `mode=""` (mixes modes and FT rows); `/api/history` has no mode filter.
- Auto-tune DYNAMIC selection ignores `deployment_refusal` (can pick symbols the live gate will refuse).
- `merge_realised` (self-learning from realised trades) has **no callers** — unwired.
- `trading.primary_timeframe` setting is unused. `donchian_eth_h4.ENABLED_MODES` is a dead constant.
- `orchestrator.py` imports the **untracked** `jarvis/forward_tests/kn_adaptive.py` — committing the orchestrator alone breaks import.
- Pre-existing test failures: `test_allowed_symbols_includes_gold_and_crypto`, `test_added_symbols_are_in_the_universe`
  (caused by your uncommitted `allowed_symbols` edit removing BTCUSD/ETHUSD/EURUSD/USDCAD/USDJPY/GER40) and
  `test_markets_options_math::test_no_edge_when_the_view_equals_the_market` (unrelated).

Wiring checks: `audit_wiring` 200 modules, 0 broken imports (35 "unreferenced" are false positives / tools-only).
API smoke: 88/91 dispatched OK; `/api/markets/overview/changes/summary` timed out once on a cold AI call, then 200 in 0.24 s.
Frontend `tsc -b` clean.

## 4. Data verification (`reports/holdout_data_check_2026-11-24.json`)

All 16 symbols, window 2026-05-19 → 2026-11-18, compared bar-by-bar with live MT5 (`copy_rates_range`, broker EET→UTC, DST-aware):
OHLC match 100% (USDCAD 99.97%; its last bar is 2026-11-17 21:00). No duplicates, NaNs, OHLC inconsistencies or zero spreads.
UK100 has one >72 h gap (holiday). Data is reliable for this test.

## 5. Per-symbol results, 2026-05-19 → 2026-11-18 (engine, after costs, 0.5% risk, $10k)

**A. Walk-forward holdout** — profiles calibrated only on data before 2026-05-19 (3-day purge), then traded blind.
Source: `reports/backtest_6month_holdout_2026-11-24.json`. DSR n_trials = 16.

| Symbol | Trades | WR % | Exp R | PF | Max DD R | Max DD % | PSR | DSR |
|---|---|---|---|---|---|---|---|---|
| AUDUSD | 0 | – | – | – | – | – | – | – |
| BTCUSD | 210 | 59.5 | −0.030 | 0.94 | 15.4 | 2.72 | 0.261 | 0.007 |
| ETHUSD | 97 | 39.2 | −0.069 | 0.79 | 20.5 | 4.12 | 0.247 | 0.008 |
| EURUSD | 0 | – | – | – | – | – | – | – |
| GBPUSD | 0 | – | – | – | – | – | – | – |
| GER40 | 421 | 67.9 | −0.058 | 0.68 | 26.8 | 6.81 | 0.021 | 0.000 |
| NAS100 | 398 | 70.9 | −0.030 | 0.81 | 21.8 | 4.03 | 0.158 | 0.002 |
| NZDUSD | 0 | – | – | – | – | – | – | – |
| SOLUSD | 0 | – | – | – | – | – | – | – |
| UK100 | 337 | 54.6 | −0.127 | 0.42 | 50.4 | 10.36 | 0.000 | 0.000 |
| US30 | 190 | 41.6 | −0.050 | 0.91 | 19.8 | 3.27 | 0.276 | 0.009 |
| USDCAD | 149 | 50.3 | +0.012 | 0.92 | 9.6 | 2.33 | 0.552 | 0.047 |
| USDCHF | 233 | 55.4 | −0.156 | 0.54 | 40.3 | 7.62 | 0.001 | 0.000 |
| USDJPY | 99 | 37.4 | −0.138 | 0.86 | 18.3 | 2.04 | 0.131 | 0.003 |
| XAGUSD | 313 | 44.4 | −0.060 | 0.87 | 29.3 | 12.39 | 0.198 | 0.005 |
| XAUUSD | 347 | 37.5 | −0.106 | 0.83 | 43.4 | 7.64 | 0.059 | 0.001 |
| **Portfolio** | 2794 | 55.9 | −0.073 | 0.79 | – | 50.05 | – | – |

0-trade symbols: the train-only calibration itself found negative OOS expectancy, so the engine refused them
("calibrated profile has no validated edge"). That is a "no edge" result, not a missing test.

**B. Current production profiles** (fitted 2026-11-19 on 730 d, which **includes** this window → in-sample, optimistic).
Source: `reports/backtest_6month_production_profiles_2026-11-24.json`.

| Symbol | Trades | WR % | Exp R | PF | Max DD R | Max DD % | PSR | DSR |
|---|---|---|---|---|---|---|---|---|
| AUDUSD / BTCUSD / NAS100 / USDJPY | 0 | – | – | – | – | – | – | – |
| ETHUSD | 119 | 39.5 | −0.059 | 0.75 | 18.3 | 4.01 | 0.270 | 0.009 |
| EURUSD | 179 | 29.1 | −0.305 | 0.50 | 62.4 | 9.26 | 0.001 | 0.000 |
| GBPUSD | 190 | 44.7 | −0.011 | 0.89 | 15.1 | 3.07 | 0.441 | 0.026 |
| GER40 | 134 | 39.6 | +0.035 | 1.01 | 10.7 | 2.45 | 0.622 | 0.067 |
| NZDUSD | 113 | 35.4 | −0.062 | 0.87 | 18.1 | 2.88 | 0.310 | 0.012 |
| SOLUSD | 124 | 39.5 | −0.081 | 0.56 | 20.1 | 5.80 | 0.165 | 0.003 |
| UK100 | 142 | 27.5 | −0.307 | 0.46 | 46.9 | 8.14 | 0.004 | 0.000 |
| US30 | 190 | 41.6 | −0.050 | 0.91 | 19.8 | 3.27 | 0.276 | 0.009 |
| USDCAD | 363 | 67.8 | −0.071 | 0.64 | 28.5 | 6.59 | 0.010 | 0.000 |
| USDCHF | 233 | 55.4 | −0.156 | 0.54 | 40.3 | 7.62 | 0.001 | 0.000 |
| XAGUSD | 306 | 45.4 | −0.023 | 0.94 | 19.6 | 8.66 | 0.374 | 0.018 |
| XAUUSD | 758 | 50.3 | −0.024 | 0.93 | 34.0 | 6.10 | 0.256 | 0.007 |
| **Portfolio** | 2851 | 47.9 | −0.076 | 0.81 | – | 50.83 | – | – |

Even in-sample, only GER40 is positive (+0.035R, DSR 0.067 — not significant).

## 6. Calibration feedback applied (per symbol)

The holdout results were stamped into `config/winrate_profiles.json` (`holdout_window/trades/expectancy_r/profit_factor`;
backup of the previous file: `data/signals/holdout/winrate_profiles.before_stamp_2026-11-24.json`). The live gate now reads them:

| Symbol | In `allowed_symbols` | Live gate now |
|---|---|---|
| ETHUSD, GER40, UK100, US30, USDCHF, XAGUSD, XAUUSD | UK100, US30, USDCHF, XAGUSD, XAUUSD | **HOLDOUT_GATE** (new) |
| NZDUSD, SOLUSD | NZDUSD, SOLUSD | **HOLDOUT_GATE** — stamped with the production-profile engine run on the same window (−0.062R / 113, −0.081R / 124), on user request |
| AUDUSD, BTCUSD, GBPUSD, NAS100, USDCAD, USDJPY | GBPUSD | EXPECTANCY_GATE (unchanged) |
| EURUSD | – | allowed by the gate (holdout had 0 trades); not in `allowed_symbols` |

**Effect on the running demo bot:** profiles are re-read on mtime change, so **every allowed symbol is now refused
for new live/demo entries**. The gate sits in the entry path (`authorize_execution`), so the bot opens nothing until a
symbol passes a fresh holdout. If EURUSD is re-added to `allowed_symbols` it would trade (in-sample −0.305R) — stamp it too first.
To undo, restore the backup file.

Caveat: the holdout tests the *calibration method* (train-only profile), not the exact production geometry. Since the
production profiles also lose on this window in-sample, both lines of evidence agree.

**Why calibration and engine diverge (needs its own investigation):** the calibrator's simulator scores candidate
signals with its own fill/exit model; the engine adds the full gate stack (sessions, directional bias, capital
protection), spread/slippage per bar and position overlap. Its OOS folds also come from the same 2-year period that
selected the signal family. Until the calibrator reproduces engine results on the same bars, its OOS figures should
not be used to deploy.

## 7. How to reproduce

```
python tools/calibrate_winrate.py --days 730 --target 0.75 --wide-grid --train-end 2026-05-19 --out data/signals/holdout/winrate_profiles_train_to_2026-05-19.json
python tools/backtests/run_3month_backtest.py --days 730 --start 2026-05-19 --profiles data/signals/holdout/winrate_profiles_train_to_2026-05-19.json --out backtest_6month_holdout_2026-11-24 --stamp config/winrate_profiles.json
python tools/backtests/run_3month_backtest.py --days 730 --start 2026-05-19 --out backtest_6month_production_profiles_2026-11-24
```
