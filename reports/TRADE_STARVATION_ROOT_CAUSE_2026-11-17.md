# Why so few trades, and would more trades make money? (2026-11-17)

**Request:** find the root cause of the low trade count, fix it permanently, and make the bot profitable.

## Answer in one paragraph
The low trade count has two causes, and only one of them was a bug.

- **The bugs.** Two live defects blocked or killed valid trades:
  - session gates read the wrong clock;
  - pending orders expired after 30 minutes instead of their intended lifetime.
  - Both are fixed and covered by tests.
- **The main cause is not a bug.** The engine's own entry signals do not make money after costs. The gates mostly block losers and coin-flips.
  - Opening the gates would raise the trade count and lower profit. The evidence is below, measured on today's code and 6 months of real MT5 bars.
  - So no gate was loosened.
- **Profit has to come from a better entry signal, not from more of the current ones.** See "What would actually raise profit".

## Evidence 1: every signal the engine forms, with all gates removed
**Tool:** `tools/gate_attribution.py`.
- It runs the unchanged production backtest path (`run_mode_backtest.run_one`) and records every directional decision, whether executed or blocked, with its entry, SL, TP and failing gates.
- Each decision is replayed as a shadow trade: next-bar entry paying the spread, stop checked first, one position at a time.
- Each shadow trade is also checked against two benchmarks: a **flipped** trade and an **always-long** trade.
- Data: 4 symbols (XAUUSD, EURUSD, GBPUSD, BTCUSD), 3 styles, 183 days.

| Set | n | Exp R | Win rate | Total R | Flipped |
|---|---|---|---|---|---|
| **All signals, no gates** | 4,525 | **−0.024** | 42% | −108.2 | −0.032 |
| Passed every quality gate | 7 | −0.122 | 43% | −0.9 | — |
| SCALP | 2,190 | −0.047 | 42% | −102.5 | −0.048 |
| DAY_TRADING | 1,842 | −0.018 | 44% | −33.4 | −0.008 |
| SWING | 493 | +0.056 (SE 0.076) | 33% | +27.6 | −0.051 |

- **Direction carries no information on average.** A flipped trade does about as badly as the real one.
- **SWING is the only positive style, and it decays.** By calendar quarter: +0.29R, +0.19R, −0.25R, −0.01R. Its standard error (0.076R) is larger than its edge.
- **EURUSD SWING** is positive in all four quarters (+0.196R, n = 65). It is one symbol picked after looking at 12 cells, so it is a forward-test candidate, not a deployable edge.

**Trades blocked by a single gate (the trade would have happened without it):**
- Honest Base Rate +5%: n = 138, **+0.027R**. That is noise; the standard error is about 0.1R.
- Premium/Discount Alignment: n = 20, +0.012R.
- Every other sole blocker has 8 trades or fewer.

**Across every gate:** the trades each one blocked average between −0.17R and +0.01R. Calibrated Win Prob, Honest Base Rate, Devil Guard, Premium/Discount, Macro MTF and Forex Prime Session are all negative.

This repeats `reports/entry_edge_verdict.md` (2026-09, 18,998 candidates, no positive bucket) on current code.

## Evidence 2: the calibrated policy that the live arbiter ignores
`config/winrate_profiles.json` covers only XAUUSD, USDCAD and USDJPY. The live arbiter never executes a setup that the legacy stack marks `NO_TRADE`, even when the calibrated policy allowed it. That looked like a defect, so it was tested. Engine replay with `--profile`, XAUUSD, 183 days:

| Style | Trades | Win rate | Exp R | PF |
|---|---|---|---|---|
| SWING | 925 | 60% | +0.002 | 1.01 |
| DAY_TRADING | 373 | 67% | −0.010 | 0.96 |

- It produces 13× the trades and a high win rate, at zero expectancy.
- Wiring it into the arbiter would add costs and risk, not profit. **Left as is.**

## Evidence 3: the live journal
- **The journal records the dry-run scan, not orders.** The 44,094 rows on 11-16/17, with 12 marked EXECUTE, come from `scan_all_modes(dry_run=True)`. `jarvis_history.db` shows about 50 real orders in the same period.
- **Live blockers are mostly limits, not bugs:**
  - **Max concurrent positions** (4 at $545 equity): saturated 11-16 from 09:27 to 21:06Z by the bot's own stagnant trades of about 0R.
  - **Risk ceiling:** a de facto XAUUSD ban. At 0.01 lot, the median $18 stop risks 3.3% against the 2.5% cap. That is an account-size limit.
  - **Circuit breaker:** tripped twice after 3 losses in 45 minutes, and reset correctly.
  - **PENDING_ORDER_EXISTS:** see fix 2.

## Fixes (each with a regression test in `tests/test_root_cause_trade_starvation.py`)
1. **Session gates used the bar's open time.** Affected checks: Forex Prime Session, Gold Session Window, killzones, market-open, and the institutional killzone.
   - **Live:** the bar is still forming, so a D1 primary read its day-open. That is Sunday 22:00 UTC for an EET broker, so XAUUSD and USDCAD D1_SWING failed "Forex Prime Session" for all of Monday (11-16, 09:00–22:59Z, 100% of rows).
   - **Backtest:** the decision was dated one bar early.
   - **Fix:** the decision time is now `min(now, bar_open + bar_length)`. `jarvis/market/market_context.py` (`_decision_time`).
2. **Pending orders expired at about 30 minutes, whatever their TTL.** Once an order was 30 minutes old, its age switched to the broker clock, which is 2 hours ahead, so "TTL expired (150m > 40m)" fired at a real 30 minutes.
   - The age now takes the smaller non-negative reading of the two clocks.
   - `jarvis/execution/position_monitor.py` (`_pending_order_age`).

**Engine replay (same frozen bars, 4 symbols × 3 styles, 183 days):**

| | Trades | Net $ | Total R |
|---|---|---|---|
| Phase 0 | 72 | −122.57 | +0.17 |
| + these fixes | 74 | −56.51 | +1.43 |

The only change is XAUUSD SWING, at 29 trades instead of 27. Fix 2 is live-only, because the replay does not simulate pending-order TTLs.

**Tests:** 29 failures against the 28 baseline. The extra one, `test_backtest_is_hermetic::test_reusing_one_engine_gives_the_same_trades`, also fails on the untouched original commit `68f269f` today, so it is time or environment dependent and not caused by this change.

## Not fixed, by evidence or by scope
- **Gates:** not loosened (Evidence 1).
- **Calibrated policy:** not wired into the arbiter (Evidence 2).
- **XAUUSD risk ceiling:** policy. Either a bigger account or a smaller stop is needed to trade gold at 0.01 lot within 2.5%.
- **Unexplained position:** XAUUSD #995683493 had SL 0, was recorded via broker sync with no features, and its origin is unknown. Worth checking by hand in MT5.
- **Max-positions saturation by stagnant trades:** a slot or time-stop policy question. It was not tested here.

## What would actually raise profit
1. **New entry information, not looser filters.** Every test so far points the same way: SMC, M1, gates and the calibrated policy. The current features carry no edge.
   - The audit's own list: order flow and imbalance, cross-asset confirmation, volatility regime at entry, session state.
   - Any new feature must pass the same cost-honest gate before it goes live.
2. **Forward-test the three leads on demo, unchanged, for at least 100 trades each:**
   - EURUSD SWING (+0.196R, all quarters positive);
   - forex DAY with the session filter only (+0.195R, PF 1.29);
   - crypto SWING with a 3-ATR chandelier (+0.104R, PF 1.22).
   - Judge on expectancy per trade, not win rate.
