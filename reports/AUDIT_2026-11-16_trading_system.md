# HM Algo audit — 2026-11-16

Scope: trailing stop / exit management, reversal detection, BUY-trade drought, strategy and journal correctness. Every finding below was reproduced (code + data, or a failing test) before any change; unverified items are listed separately.

## 1. Why there were no BUY trades

**Root cause: the market, not a code fault.**

| Window | BTC | ETH | SOL | EURUSD | Bot BUY / SELL |
|---|---|---|---|---|---|
| 11-11 → 11-14 (daily close) | 74,389 → 64,457 (−13%) | 2,070 → 1,773 (−14%) | 84.3 → 69.7 (−17%) | 1.1087 → 1.1023 | **0 / 110** (11-12..11-14) |

- BUYs resumed on 11-15/16 (ETH, SOL, USDJPY, XAUUSD), so the BUY path works.
- A mirrored-input audit of the whole decision path (levels, devil's advocate, decision engine, confluence, momentum, arbiter, risk, execution, config, bandit/learning state) found **no SELL-only switch and no direction-keyed learning state**. Commits 485404e / d44a3a8 (Ask/Bid, pipeline blockers) are direction-symmetric.
- Demo results confirm selling was right in that tape: closed demo trades since 11-09 — BUY −$106, SELL +$37 (397 trades, 30% WR, −$69.30 net).

**Real but narrow BUY-only friction (not changed — see §6):**
- `decision_engine.py:890-907` "Macro MTF Alignment" hard gate: a SELL against a bullish H4/D1 is exempt on an intraday breakdown; a BUY against a bearish H4/D1 has no mirrored exemption. Present since 2026-10-18, so it does not explain the 11-12 change.
- Metals premium/discount gate: BUY is blocked on `PREMIUM or RSI>70`, SELL only on `DISCOUNT and RSI<30`.
- Several asymmetries lean the *other* way (bullish-leaning `trend_score`, BUY-only trend-template bonus, BUY wins ties in order-flow/sweep).

## 2. Trailing stop-loss — test results

The canonical stop math (`exit_policy.evaluate_exit`) is sound: 551k random-walk evaluations, 4 symbols × 3 styles × BUY/SELL — the stop never loosened and never crossed price; BUY/SELL mirror exactly; pip/point scaling is correct for FX, JPY, BTC and indices. Live evidence: of 45 closed trades with MFE recorded since 11-11, only 1 reached ≥1R and still lost.

The defects were in the layers around it:

| # | Defect | Status |
|---|---|---|
| T1 | A restart re-derived 1R from the already-ratcheted stop → every R threshold fired ~5x early, the stop jumped (−0.2R → +0.45R) | **Fixed** — 1R recovered from the broker's opening order |
| T2 | A restart repeated the partial close | **Fixed** — volume below the opening order's volume ⇒ partial already taken |
| T3 | Partial trigger measured R against the live (ratcheted) stop → banked at +1.05R instead of +1.3R | **Fixed** — uses the frozen 1R |
| T4 | Gold's backtested fixed 2.5R exit was not what ran live: MFE-retrace lock, 94%-of-TP lock, proximity harvest, reversal/regime/VWAP exits and ML TP rewrites all still ran | **Fixed** — skipped when the policy has `profit_locks=False` (gold only) |
| T5 | Broker stop-level clamp could loosen a resting stop (TP-only modify while SL sits inside the stop level) | **Fixed** — the clamp may not loosen; an explicit wider request is still honoured |
| T6 | Backtest ratcheted the stop from a bar's high, then stopped out on that same bar's low (optimistic) | **Fixed** — tests the stop resting at bar open, like `trade_simulator` |
| T7 | Paper mode: `point` = pip while `spread` was in tenth-pips ⇒ minimum stop distance ~10x (14 pips EURUSD, $300 BTC) | **Fixed** — MT5 semantics (`point = 10^-digits`) |
| T8 | A rejected SL modify is re-sent every 2 s with no backoff or alert (the old stop stays, so protected but noisy) | Not changed |

## 3. Market reversal detection — test results

Correctness: **no look-ahead** (pivots confirmed `w` bars late; backtest uses closed bars). Mirror test on 2,044 real windows — CHoCH/BOS/bias flip exactly.

Accuracy, 12 months H1, EURUSD/GBPUSD/BTCUSD; win = +1 ATR before −1 ATR within 24 bars:

| Signal | n (bull/bear) | Hit bull | Hit bear | Base rate (long/short) |
|---|---|---|---|---|
| CHoCH (all) | 2,078 / 2,195 | 0.499 | 0.488 | 0.490 / 0.510 |
| CHoCH classic | 884 / 875 | 0.499 | 0.485 | |
| BOS new event | 693 / 763 | 0.493 | 0.505 | |
| Bias flip | 1,335 / 1,344 | 0.454 | 0.522 | |
| RSI divergence | 2,194 / 1,974 | 0.495 | 0.497 | |

**No reversal signal has a directional edge** (standard error ±0.017). They are context, not triggers.

Wiring defects:

| # | Defect | Status |
|---|---|---|
| R1 | Exit guard counted one structure break as 3 signals (CHoCH, BOS and bias all come from the same close) → a single H1 wick closed winners at market in every profit phase | **Fixed** — one break = one signal (now locks BE / +0.5R instead of closing; runners ≥1.8R still exit) |
| R2 | "Validated reversal" accepted a CHoCH/sweep in **either** direction, or any non-neutral bias, so a bearish CHoCH could lift counter-trend vetoes for a BUY | **Fixed** — the evidence must point the trade's way |
| R3 | `bullish_divergence`/`bearish_divergence` read from a schema that only has `divergence` → divergence branches are dead | Not changed (no measured edge; enabling it is a strategy change) |
| R4 | Sweep-reversal detector always receives `df_m5=None` → never fires | Not changed (same reason) |
| R5 | Live structure uses the still-forming bar; the backtest uses closed bars | Not changed — recommended next |
| R6 | Divergence: bearish overwrites bullish when both fire | Not changed |

## 4. Journal / data integrity

| # | Defect | Status |
|---|---|---|
| D1 | Order-state reconciliation used `{2,3,5,8}`; MT5 is CANCELED=2, PARTIAL=3, REJECTED=5, **EXPIRED=6**, REQUEST_MODIFY=8 → expired limit orders stayed "open" forever (11 on the live journal) | **Fixed** → `{2,5,6}` |
| D2 | Exit-deal sync overwrote the journaled **initial** stop with the exit comment's **final** (trailed) stop → recorded risk shrinks, R-multiples inflate | **Fixed** — fills only a missing stop |
| D3 | 146 of 148 "open" demo rows are not positions: 51 cancelled + 11 expired limits, 82 from a previous account. Reconciliation works but only runs from the read path when a terminal is attached in-process | Partly addressed by D1; the 82 old-account rows need a one-off cleanup |
| D4 | 1,125 paper rows (11-09/10) were filled at **synthetic** prices (EURUSD 1.28–1.35). `DataFeedEngine.fetch_rates` silently returns `SYNTHETIC_FALLBACK` data when it cannot reach MT5 (reproduced during this audit) | Not changed — recommended next |

## 5. Before / after backtest

Same frozen MT5 H1 data (to 2026-11-16; 4,400 bars per symbol), measured per-symbol median spread, $5/lot commission, 0.5 pip slippage, 0.5% risk, real `DecisionEngine`.

| Symbol | Trades | Net before | Net after | PF before → after | MaxDD % |
|---|---|---|---|---|---|
| EURUSD | 3 | −46.69 | −49.24* | 0.29 → 0.28 | 0.7 |
| GBPUSD | 1 | −23.10 | −23.10 | 0 → 0 | 0.2 |
| USDJPY | 0 | 0 | 0 | — | 0 |
| BTCUSD | 10 | +19.14 | +28.93 | 1.11 → 1.17 | 0.9 |
| ETHUSD | 34 → 37 | −79.63 | −53.77 | 0.86 → 0.91 | 2.4 → 2.6 |
| **Total** | 48 → 51 | **−130.28** | **−97.18** | | |

\* EURUSD varies ±$3 between identical runs (the engine is not fully deterministic); its trade set is identical.

Honest reading: **51 trades in ~6 months across 5 symbols is far too few to claim an improvement.** The fixes are justified by their failing tests, not by this P&L. The backtest does not model the live-only exit layers (T4, R1), so their effect is not captured here. Gold could not be tested on this terminal account (no XAUUSD symbol).

Test suite: 3,587 passed. The 31 failures match the pre-existing baseline (HEAD: 29), except one order-dependent test that passes in isolation and one test that pinned defect D2 (updated). 9 new regression tests were added; each fails on the old code.

## 6. Research-backed opportunities (recommended, not implemented)

1. **Signal edge before more filters.** The reversal study shows structure signals are coin flips at the H1/24-bar horizon. Measure each entry component's marginal edge with purged walk-forward folds (the repo already has `tools/p0_1_direction_audit.py` and isotonic calibration) and drop components with none. Fewer, validated filters beat stacked unvalidated vetoes.
2. **Symmetric macro gate (§1).** Either mirror the SELL intraday-breakdown exemption for BUY, or remove it from SELL. Decide with a walk-forward test, not by preference.
3. **Closed-bar structure live (R5)** for live/backtest parity.
4. **Fail closed on synthetic data (D4)** in every mode that places or simulates orders.
5. **Modify backoff (T8):** exponential backoff and an alert after N rejected modifies.
6. **Fewer discretionary exits.** Trend-following with an ATR stop and a higher-timeframe trend filter is the most robust documented edge for these instruments. The current stack has many live-only exits that no backtest reproduces, so their contribution is unknown.

## 7. Remaining risks and next steps

- **The running engine (`HM_start.py`) still runs the old code** — restart it to apply these fixes.
- Demo performance is negative (30% WR, −$69 over 397 trades); none of these fixes makes the strategy profitable on its own.
- Clean up the 82 old-account ghost rows once.
- Live-only exit layers (ML TP rewrite, MFE retrace, regime/VWAP) remain untested by any backtest for non-gold symbols.
