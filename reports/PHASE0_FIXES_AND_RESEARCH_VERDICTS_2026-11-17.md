# Phase 0 live-code fixes and research verdicts (2026-11-17)

**Request:**
- verify the existing code;
- test the pasted SMC/ICT spec, the news logic, multi-timeframe (MTF) entries, style-based trailing, M1 and AI decisions;
- change live code only after a test confirms the change.

## Summary
- **SMC/ICT spec:** no part passed. See `reports/SMC_ENTRY_EXIT_RESEARCH_2026-11-17.md`.
  - The base setup averages −0.036R per trade after costs.
  - With all filters stacked, only 44 trades remain in all available history.
  - So no SMC entry gate, HTF-structure bias, premium/discount rule, retrace entry or partial-at-1R was added.
- **News:** one change passed. See `reports/NEWS_RESEARCH_2026-11-17.md`.
  - **N1 passed:** the entry blackout widens to −30/+30 min.
  - **N2 failed** (closing or moving to break-even before the release), as did **N3 and N4** (post-release entries).
  - A Phase-0 fix that banked winners *before* the release was **reverted** because N2 rejected it.
- **AI layer (meta-labeling v2):** not started. The rule fixed in advance requires a primary signal with n ≥ 300 that passes the gate, and none passed.
- **M1 study (Phase 3): rejected.** See `reports/M1_RESEARCH_2026-11-17.md`.
  - Forex and BTC fail the cost gate: spread + slippage is 16–28% of the stop.
  - Gold passes on cost but loses on the base setup: −0.03R, PF 0.96.
  - No M1 logic was added.
- **20 defects in the live path:** 18 are fixed with regression tests. One (#14) was reverted on evidence. One (#20, dead code) is left.

## Fixes (all in `jarvis/`, each with a test)
| # | Fix | Where |
|---|---|---|
| — | **H4 data validator rejected every H4 bar.** Since the broker→UTC conversion, H4 bars open at 21/01/05 UTC. That blocked the 183-day fetch for every DAY/SWING backtest. | `data/mt5_history.py` |
| 1 | A partial target is used only if the decision has the same side and style and the target is on the profit side. Before, a later SELL's TP1 could close half of a BUY. | `execution/position_monitor.py` |
| 2 | The monitor builds context (and ATR) on the position's own style timeframes. Scalps had been trailed on the H1 ATR. | `position_monitor.py` |
| 3 | A real tight stop now defines 1R. It is no longer inflated to 1.5 ATR. | `position_monitor.py` |
| 4 | Partial splitting uses the broker's min lot/step. An unsplittable position now gets the fallback stop-lock instead of nothing. | `position_monitor.py` |
| 5 | A SELL is measured on the ask (+spread), so SELL trails are no longer a spread tighter than BUY trails. | `position_monitor.py` |
| 6 | The SELL structural target no longer subtracts the spread twice. | `intelligence/dynamic_levels.py` |
| 7 | BUY targets get the same ranging rules as SELL (cap ×0.85, TP3 base 2.2). | `dynamic_levels.py` |
| 8 | Direction resolver: on intraday trades the HTF bias outranks D1 in both directions. Before, both conflict cases went to BUY. | `intelligence/decision_engine.py` |
| 9 | H4_SWING and D1_SWING bias now comes from the closed context bar, not the forming bar. | `market/market_context.py` |
| 10 | The stop anchor can no longer sit inside the liquidity pool (the SMC_AUDIT B2 defect). | `dynamic_levels.py` |
| 11 | Mitigated OB/FVG zones are no longer used as targets, and the HTF OB finder respects side and mitigation. | `dynamic_levels.py`, `institutional_entry_engine.py` |
| 12 | USD news now blocks USDCAD, ETHUSD, SOLUSD, XAGUSD, USDCHF, AUDUSD and NZDUSD. CHF maps to USDCHF. | `market/news.py` |
| 13 | The news gate **fails closed**. With no exact-time feed, it blocks USD-linked symbols around the published FOMC/NFP/CPI schedule (`data/news_history_usd.json`, through 2027-12). If that file is missing, it falls back to the fixed US slots. | `news.py`, `application/orchestrator.py` |
| N1 | The entry blackout widens from −10/+15 to **−30/+30 min**. | `news.py`, `orchestrator.py` |
| 14 | ~~Bank winners before the release~~: **reverted**. N2 rejected it, so trades hold through the release as before. | — |
| 15 | Position news protection ignores estimated (guessed) times, the same rule the entry gate uses. | `position_monitor.py` |
| 16 | Post-news sweep bonus: bounded calendar wait (no 20–30 s stall), HIGH exact events only, the sweep must come after the release, and an unknown sweep type no longer defaults to BUY. | `news.py`, `decision_engine.py` |
| 17 | The scalp counter-trend check needs a sweep on the correct side. `"NONE"` had passed both ways. | `scalping/scalp_execution_engine.py` |
| 18 | When the stop is widened, scalp TPs keep their R-multiples, and the real R:R is reported instead of a 1.8 floor. | `decision_engine.py` |
| 19 | The M1/timing frame reads closed bars only. | `market/data_feed.py` |

New tests:
- `tests/test_phase0_exit_fixes.py`
- `tests/test_phase0_scalp_fixes.py`
- `tests/test_phase0_levels_fixes.py`
- `tests/test_phase0_direction_symmetry.py`
- additions in the news, protocol and symbol-registry tests

Two existing test fixtures were updated, for real-feed fields and for the per-style context cache.

## Verification
**Full pytest suite:**
- 28 failures before the changes (stash of HEAD) and the same 28 after;
- no new failures, none fixed;
- 3,724 passed.

**Engine replay** (`tools/backtests/run_mode_backtest.py`):
- 183 days, XAUUSD, EURUSD, GBPUSD and BTCUSD, × SWING, DAY and SCALP;
- frozen MT5 bars;
- run before (HEAD worktree) and after (patched worktree).

| | Trades | Net $ (10k acct, 0.5% risk) | Total R |
|---|---|---|---|
| Before | 69 | −207.27 | −3.00 |
| After | 72 | −122.57 | +0.17 |

- All 9 DAY and SWING jobs are **identical trade-for-trade**.
- The only difference is SCALP: 0 → 3 trades (XAUUSD +1.79R; BTCUSD 2 trades, +0.69R average).
- **That is too few trades to call a profit improvement.** The honest reading is that the fixes did no harm in the replay.
- Most fixes (#1–5, #12–16) are in the live position monitor and news gate, which this replay does not exercise. They are correctness fixes backed by unit tests, not backtested gains.

## Not done / risks
- **The live bot (`HM_start.py`) is running the old code.** None of this is live until it restarts. Nothing is committed.
- **#20 dead code:** not removed. That covers the scalp news lockout, the `EVENT_RISK` regime, the institutional `trail_mode`, and `config/economic_calendar.json`.
- **The engine replay is thin.** About 70 trades in 6 months, and SCALP was nearly silent before the fix. A component-level A/B in the engine is not meaningful at this trade count.
- **Research leads, not adopted:**
  - forex DAY with session filter only: +0.195R, PF 1.29;
  - crypto SWING with a 3-ATR chandelier exit: +0.104R, PF 1.22.
  - Both fail PF > 1.5 and are affordable at min lot on a $545 account only. Candidates for a forward test.
