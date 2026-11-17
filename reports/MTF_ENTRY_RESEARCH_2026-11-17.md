# Multi-timeframe entry research and the BTCUSD sell-into-rally (2026-11-17)

**Request:** "please analyse all the time frames like a pro master trader before entring into trade and find a better way to fix all issues and make the Win rate to above 70% ... make it production ready in live account."

## The trade

BTCUSD #995648912. SELL 0.01 at 64,489.56, opened 2026-11-16 15:43 UTC by the DAY_TRADING engine (TREND_PULLBACK, TREND_BEAR regime). It was closed by the 360-minute time stop at 65,378.55, for −$8.86. Price never moved in the trade's favour: MFE 0, MAE 850.

What each timeframe said, from the decision journal and the frozen M5/M15 bars:

| Time (UTC) | Engine | Verdict |
|---|---|---|
| 15:40–15:41 | SCALP | SELL, but blocked: "ZERO UNVALIDATED COUNTER-TREND TRADES … currently DISCOUNT" |
| 15:42–15:44 | SCALP | **BUY** |
| 15:42–15:44 | DAY_TRADING | SELL, WAIT with no failing gate, then executed |
| bars | M5 | bounced from 64,153 to 64,436 in 10 min (sweep of the low) |
| bars | M15 | still below EMA20 < EMA50 (bearish by EMA) |

**Root cause:** the H1/M15 view was still bearish, but the M5 had just rejected the low. The SCALP engine read that correctly as BUY. Nothing let a faster engine's verdict stop a slower one. A plain EMA filter on M15/M5 would *not* have caught it, because M15 was still bearish by EMA.

ETHUSD #995648239 was a DAY_TRADING SELL in the same minute, with SCALP saying BUY. It also lost.

## Live record (299 closed trades in `trade_records`)

- Overall: **28.8% win rate, +$33.61.**
- TREND_PULLBACK: 108 trades, 40.7% win, +$22. This is the only clearly positive strategy.
- TREND_FOLLOWING: 92 trades, 23.9% win, −$10. **BTCUSD TREND_FOLLOWING BUY: 40 trades, 10% win, −$51.**
- CHOCH and sweep reversals: 14–21% win, net negative.

## Study: `tools/mtf_entry_research.py`

Same cost-honest machinery and adoption gate as `tools/strategy_research.py`:

- next-bar entry with the real spread, plus slippage and swap;
- stop assumed hit first when stop and target share a bar;
- results compared against flipped trades and always-long, and re-tested at spread × 2.

Data: 9 symbols, M5–D1. All parameters were fixed in advance.

The test is 2 entry patterns × 4 filters × 4 targets × 2 timeframes:

- **Patterns:** pullback, and chase (a close at a 20-bar extreme).
- **Filters:** none, trigger-TF veto, trigger-TF strict alignment, and veto plus a 50-bar zone veto.
- **Targets:** 0.5, 1, 1.5 and 2R.
- **Timeframes:** M15 (H1 trend, M5 trigger) and H1 (H4 trend, M15 trigger).

### Findings

1. **Crypto: no variant makes money after costs** at M15 or H1. Pooled expectancy runs from −0.08R to −0.29R per trade. The chase pattern loses on BTC (strict, 1R): BUY −0.14R, 41% win. This matches the live TREND_FOLLOWING leak.
2. **A 70% win rate only appears with a 0.5R target, and it lowers expectancy.** For example, gold H1 chase-strict:

   | Target | Win rate | Expectancy |
   |---|---|---|
   | 0.5R | 71% | +0.09R |
   | 1.0R | 58% | +0.19R |

   Shrinking take-profits to hit a win-rate number costs money. Expectancy (R per trade after costs) is the number that matters.
3. **The trigger-TF veto changes almost nothing** in the mechanical test (vetoed trades ≈ 0.5%). It does not hurt, and it does not create edge.
4. **The zone veto (no sell in the bottom 25% of the range, no buy in the top 25%) reduced expectancy in every group.** The premium/discount rule is not supported in this mechanical form, so it was not tightened.
5. **Gold H1 chase with strict M15 alignment** passes every edge test:
   - PF 1.35–1.53 at all four targets;
   - both halves positive;
   - survives spread × 2;
   - beats flipped trades and always-long.

   It is not adopted, for three reasons:
   - The M15 history starts in Oct 2024, so this is ~2 years, mostly gold's 2025 bull run. SELLs were negative before 2026.
   - At 0.01 lot, only ~10% of its trades fit 2.5% risk on $545.
   - It is the best of 576 configurations tested.

## Changes made

| Change | Evidence | File |
|---|---|---|
| Timeframe-conflict backstop: a slower style may not EXECUTE when a faster style on the same symbol resolved the opposite side within 10 min (reason `TIMEFRAME_CONFLICT`) | Prevents #995648912 and #995648239 (both lost); in the mechanical test it only removes trades and does not reduce expectancy | `jarvis/application/orchestrator.py` |
| BTCUSD `TREND_FOLLOWING` banned (weight 0) | Live 53 trades ~13% win −$52; chase loses on every crypto test | `jarvis/intelligence/symbol_profile_config.py` |

Tests: `tests/test_timeframe_conflict_backstop.py`.

## Not changed, and why

- **Take-profit size:** not reduced to chase a 70% win rate; see finding 2.
- **Premium/discount guard:** the crypto exception is not direction-aware (any BOS or sweep, even a bullish one, unlocks a SELL in discount). Making it direction-aware tightens the guard, and the zone test says tighter zone rules cost expectancy, so it was left alone. Worth revisiting with engine-level replay.
- **Trailing stop and profit booking:** the 2026-11-17 exit research already found no trailing policy beats the current stack where entries have edge. No new evidence here.

## Live-account recommendation

No crypto intraday configuration tested here has positive expectancy after costs. The live record (+$33 over 299 trades) is consistent with roughly zero edge. Do not move crypto intraday to a real-money account on this evidence. Keep it on demo and judge it on expectancy per trade over at least 100 more trades.
