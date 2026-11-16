# Gold research — 2026-11-16

## 1. Why gold was not traded while it fell

Gold fell 4,140.9 → 3,855.3 (−6.9%) between 11-09 and 11-16. The bot took 5 SELLs (+$32.55) and 3 SELL limits expired unfilled. On 11-16 `/api/radar` showed gold DAY_TRADING SELL as #1, decision EXECUTE, grade A+, all gates passed — and nothing was sent.

| Cause | Evidence | Fix |
|---|---|---|
| **Minimum-lot risk cap.** 0.01 lot of `GOLD.i#` = $1 per $1 move; the DAY stop was 48.89 → $48.89 (9% of $545). The gold cap for $250–2,500 accounts is $28 / 5.5% (`account_tier.get_nano_risk_cap`), so sizing returns 0 lots. Only stops ≤ 28 points can ever trade — exactly the 8–18-point trades that filled. | Code + live numbers | **Kept** (your decision): capital protection |
| **Stop scales with H1 ATR, no gold ceiling.** DAY floor `1.2×H1_ATR + spread` (`institutional_entry_engine.py`); H1 ATR ≈ 40 after the sell-off ⇒ ≈ 48. | Code | Research below |
| **Arbiter RR gate used the stale planned RR (1.97 < 2.00)** although gold's TP is rewritten to a fixed 2.5R at dispatch. | Code | **Fixed** — gate uses `fixed_target_r` |
| **Refusal was invisible.** The decision stayed EXECUTE after the risk engine refused, and `auth_reason` read `reason` while the risk engine returns `reasons`. | Code + radar | **Fixed** — decision becomes WAIT with `RISK: …` in `waiting_reasons` |
| **Every gold style used a 120-min time stop** under the fixed target. | Code | **Fixed** — each style's own time stop (SCALP 90, DAY 240, SWING/H4/D1 720); validated below |

The arbiter already falls through to the next affordable candidate when the risk engine refuses one, so no new selection logic was needed.

## 2. Research method

`tools/gold_research.py` on frozen real `GOLD.i#` bars (M5 Mar–Nov 2026, M15 Oct 2024–Nov 2026, H1/H4/D1 2018–2026), times converted broker → UTC with `broker_bar_times_to_utc`.

- Top-down timeframes per style: SCALP H1→M15→M5, DAY H4→H1→M15, SWING D1→H4→H1.
- Decisions on completed bars only; entry at the next bar's open; BUY at the ask, SELL exits pay the spread (real per-bar spread); $0.10 slippage on stop/time exits; stop assumed first when both are inside one bar.
- **The $28 budget**, expressed as a share of price (28 / 3,900), so 2018 prices are judged consistently; wider stops are skipped, never shrunk.
- **No fitted parameters** (EMA 20/50/200, ATR 14, fixed thresholds chosen a priori), so there is nothing to overfit. Robustness is judged by calendar halves/years and by two benchmarks at the same entries: **always long** (gold's drift) and **flipped direction** (is the direction call worth anything?).
- Adoption rule agreed in the plan: better than the alternatives, PF > 1.1, **both halves positive**, n ≥ 100.

Candidates:
1. **Trend pullback (top-down institutional entry):** bias TF EMA50/200 trend, setup-TF pullback into EMA20, trigger-TF break of the last 4-bar structure; stop beyond the trigger-TF 10-bar swing + spread + 0.3 ATR, never inside 1 ATR.
2. Same without the HTF trend permission.
3. **London/NY liquidity sweep (Judas swing)** of the Asian range, in the HTF trend direction.
4. **Asian-range breakout** at the London open, in the HTF trend direction.

Each was run with a 2.5R and a 2.0R target, the style time stop, a 120-min time stop, and no time stop.

## 3. Results (net R per trade, after costs)

| Style | Strategy (2.5R, style time stop) | n | WR | Exp R | PF | 1st half | 2nd half | Always long | Flipped |
|---|---|---|---|---|---|---|---|---|---|
| SCALP | Trend pullback | 764 | 31% | −0.009 | 0.98 | −0.014 | −0.004 | −0.145 | −0.058 |
| SCALP | London sweep | 39 | 28% | −0.167 | 0.75 | | | | |
| SCALP | Asian breakout | 37 | 46% | +0.242 | 1.98 | −0.073 | +0.540 | −0.085 | −0.014 |
| DAY | **Trend pullback** | 686 | 34% | **+0.052** | **1.12** | **−0.025** | +0.129 | 0.000 | −0.074 |
| DAY | Trend pullback, no HTF bias | 1,570 | 30% | −0.051 | 0.89 | | | | |
| DAY | London sweep | 140 | 26% | −0.060 | 0.91 | | | | |
| DAY | Asian breakout | 109 | 33% | −0.035 | 0.92 | | | | |
| SWING | Trend pullback | 577 | 30% | +0.045 | 1.09 | +0.094 | −0.004 | +0.036 | −0.118 |
| SWING | Trend pullback, no HTF bias | 1,491 | 28% | −0.066 | 0.86 | | | | |

DAY trend pullback by year: 2024 Q4 −0.085 (n 91), 2025 +0.030 (344), **2026 +0.132 (251) while always-long was −0.085** — it made money selling this year's decline. SWING results equal always-long in 2019, 2020, 2024 and 2025: most of its trades were longs, so it is gold's drift, not skill.

Exit variants (same entries):

| Style | Style time stop | 120 min | No time stop | 2.0R (style stop) |
|---|---|---|---|---|
| SCALP | −0.009 | −0.024 | −0.006 | −0.028 |
| DAY | **+0.052** | −0.014 | +0.050 | +0.032 |
| SWING | +0.045 | +0.020 | +0.088 | +0.013 |

Affordability: with trigger-timeframe structural stops, about 65% of DAY signals and 87% of SCALP signals fit the $28 budget; only about 1 in 3 SWING signals does.

## 4. Conclusions

1. **The HTF trend permission is the one robust ingredient.** Removing it turns every style negative (DAY +0.052 → −0.051, SWING +0.045 → −0.066), and flipping direction loses money — real direction skill, not drift.
2. **Per-style time stops beat the forced 120 min in all three styles** → shipped (Part A4).
3. **2.5R beats 2.0R in all three styles** → the existing fixed 2.5R gold target stays.
4. **SCALP on M5 has no edge** in any variant. The Asian-breakout result (n = 37) is too small and negative in its first half.
5. **Liquidity-sweep (Judas) and Asian-breakout entries are negative** for DAY → rejected.
6. **SWING is mostly gold's long drift** → no SWING strategy change.
7. **DAY trend pullback is the best candidate** (PF 1.12, n = 686, strongly positive in 2026 while selling) **but fails the agreed both-halves rule** (first half −0.025). Per the plan it is **not wired into live trading**. It is the recommended next step as a forward test on the demo account (see §6).

## 5. Not tested here

- Volatility-normalised gold caps and the BUY-only premium/discount asymmetry live inside the decision engine, whose backtester feeds H1 bars to every role, so they can't be judged faithfully for DAY/SCALP. They need a real multi-timeframe path in `BacktestEngine` first.
- The engine's own gold entries were not re-backtested on M5/M15 for the same reason. The comparison above is between candidate rule sets, not against the live engine.
- Multiple-testing caution: about 50 variants were run, so a single +0.05R result needs forward confirmation.

## 6. Recommended next steps

1. Restart `HM_start.py` so the dispatch fixes take effect. The radar will then show `RISK: …` for unaffordable gold setups instead of a silent EXECUTE.
2. Forward-test the DAY trend-pullback rule (H4 bias → H1 pullback → M15 trigger, M15 structural stop, 2.5R, 240-min time stop) on the demo for at least 60 trades. Promote it only if live expectancy stays ≥ +0.05R.
3. Give `BacktestEngine` real per-timeframe frames, so engine-level gold changes can be validated on M5/M15.
