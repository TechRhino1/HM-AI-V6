# News filter and news-trading research — 2026-11-17

Tool: `tools/news_research.py` (`--selftest` passes). History: `data/news_history_usd.json`.
Raw results: produced by `python tools/news_research.py <bars.pkl> <out.json>` on frozen XM MT5 bars fetched 2026-11-17.
No live code under `jarvis/` was changed.

## Verdicts

| Study | Question | Verdict |
|---|---|---|
| N1 | Blackout window: −10/+15 (live) vs −30/+30 vs none | **ADOPT −30/+30.** It passes the gate on M15. On H1 it misses the gate on first-half expectancy, but is neutral within noise. Keep a blackout: "none" is worse than live on both timeframes. |
| N2 | De-risk open trades 10 min before release | **REJECT (keep hold).** Closing at +0.5R fails on both timeframes. Moving the stop to break-even passes on H1 only by +0.002R in the second half, and fails on M15. |
| N3 | Post-release sweep reversal | **REJECT.** Too rare: 64 trades pooled in 2 years on M15. Pooled expectancy is +0.02R with PF 1.08, which fails spread ×2. |
| N4 | Post-release momentum (first 15 min) | **REJECT, as the literature predicts.** Pooled M15: −0.12R, PF 0.77. Fading the move is also negative (−0.02R), so there is no edge either way. |

Caveat that applies to N1 and N2: the entry proxy loses money before any news rule is applied. It is the MTF pullback + trigger-TF veto with a 1R target, and it makes −0.11R per trade on M15 and −0.07R on H1 after costs. N1 and N2 are therefore judged relative to the live setting, not as profitable systems.

## Step 1 — historical calendar (`data/news_history_usd.json`)

- **319 USD HIGH events, 2018-01 to 2027-12:** FOMC statements, NFP and CPI.
- **Format:** a note at the top of the file, then `events: [{event, currency, utc_iso, impact}]`. Extra keys hold sources, the NFP dates that were not first Fridays, and the bar check.
- **Sources:** published schedules only.
  - NFP and CPI: the BLS archive (release dates from the archived file names), plus the BLS release schedules for dates after 2026-11-10.
  - FOMC: the Fed's meeting calendars (2021–2027) and the historical pages for 2018–2020, including the unscheduled cuts on 2020-03-03 and 2020-03-15.
  - Future dates run only as far as published (BLS to Dec 2027, Fed to Nov 2027).
- **Times:** NFP and CPI at 08:30, the FOMC statement at 14:00 America/New_York. `zoneinfo` converts these to UTC, giving 12:30/13:30 and 18:00/19:00.
- **First-Friday rule:** 21 published NFP dates are not the first Friday. These include the 2025 shutdown releases (2025-11-20, 2025-12-16, 2026-02-11). A rule-only calendar would have been wrong about 7% of the time.

Cross-check: the release bar's range divided by the prior bar's ATR(14), taking the best of the six symbols. An event is flagged if that ratio is ≤ 3.

| Bars | Events checked | Median ratio | Flagged (≤ 3×) | Stated time beats ±1h (DST check) |
|---|---|---|---|---|
| M5 (Mar–Nov 2026) | 24 | 11.0× | 1: CPI 2026-05-12 (2.94×) | 100% |
| M15 (Nov 2024 – Nov 2026) | 67 | 7.2× | 7: low-surprise FOMC holds and CPIs, all ≥ 1.76× | 97% |

The flagged events are quiet releases, not wrong times: the stated time still beats ±1h. The M5 bars cover both EST and EDT releases (2026-03-06, 2026-11-06 at 13:30; summer releases at 12:30).

## Step 2 — method

The study reuses the `tools/strategy_research.py` machinery, with the same cost honesty:

- decisions on completed bars only;
- entry at the next open with the real per-bar spread;
- slippage, and swap;
- stop assumed hit first when stop and target share a bar;
- gaps through the stop fill at the open.

Symbols: XAUUSD, EURUSD, GBPUSD, USDJPY, USDCAD and BTCUSD, all of them exposed to USD events. Every parameter was fixed before the run.

- **N1 and N2 entries:** `mtf_entry_research` pullback + veto, 1R target, time stop of 32 M15 bars or 24 H1 bars. Trades are taken one position at a time, and results are pooled across the six symbols.
  - M15: Nov 2024 – Nov 2026. H1: Oct 2018 – Nov 2026 (BTC from Oct 2020).
  - Blackout: no entry with an entry time in [release − pre, release + post).
  - "Event trades" are trades whose holding window [entry, exit) contains a release.
  - Halves split at the median entry time of the live variant: 2025-12-04 for M15, 2023-01-30 for H1.
  - Gate: event-trade expectancy higher **and** event-trade max drawdown lower than live, in both halves.
- **N2 decision bar:** the last completed bar closing at or before release − 10 min, acted on at the next open. On M15 that is about 15 min before; on H1 it is 20–60 min before.
  - Break-even applies only when the trade is in profit.
- **N3 and N4:** M5 (Mar–Nov 2026) and M15 (Nov 2024 – Nov 2026). 2R target, 4h time stop.
  - Gate: `sr.verdict` (n ≥ 100, positive expectancy, PF > 1.1, both halves positive, survives spread ×2, beats always-long and flipped, min lot affordable) **plus PF > 1.5**.
  - Pooled rows apply the edge tests only.

## N1 — blackout window

| TF | Variant | Event trades n (h1/h2) | Event exp R h1 / h2 | Event max DD R h1 / h2 | Event total R | All trades n | All exp R | All total R | All max DD R | vs live |
|---|---|---|---|---|---|---|---|---|---|---|
| M15 | none | 128 (67/61) | −0.193 / −0.068 | 12.9 / 9.3 | −17.1 | 8662 | −0.111 | −961.7 | 988.1 | reject |
| M15 | live −10/+15 | 115 (58/57) | −0.207 / 0.000 | 12.0 / 6.6 | −12.0 | 8650 | −0.111 | −957.6 | 984.1 | reference |
| M15 | **−30/+30** | 85 (42/43) | −0.087 / +0.053 | 5.9 / 5.5 | −1.4 | 8575 | −0.109 | −937.6 | 968.2 | **passes** |
| H1 | none | 489 (251/238) | −0.232 / −0.049 | 59.7 / 26.0 | −69.9 | 8942 | −0.069 | −616.9 | 628.9 | reject |
| H1 | live −10/+15 | 478 (243/235) | −0.223 / −0.053 | 55.6 / 27.0 | −66.7 | 8931 | −0.069 | −613.7 | 625.7 | reference |
| H1 | −30/+30 | 447 (225/222) | −0.249 / −0.042 | 56.6 / 23.9 | −65.4 | 8908 | −0.069 | −614.2 | 626.3 | fails h1 |

**Why the verdict is adopt −30/+30:**
- On M15, the ~30 extra entries it blocks in ±30 min averaged about −0.35R. That is three times worse than the system's average trade.
- Removing them lifts event expectancy in both halves, roughly halves event drawdown, and adds about +20R of total R over 2 years. It removes about 1% of entries.
- On H1 the change only blocks the bar opening 30 min before a :30 release, and the effect is within noise: event total −65.4 vs −66.7, all-trade total −614.2 vs −613.7.
- The "none" variant is worse than live in event total R on both timeframes, so the blackout itself is worth keeping.
- **Confidence:** moderate. The M15 evidence rests on 115 vs 85 event trades in 2 years.

## N2 — de-risk 10 min before release

| TF | Variant | Event trades n (h1/h2) | Event exp R h1 / h2 | Event max DD R h1 / h2 | Event total R | All exp R | All total R | All max DD R | vs live |
|---|---|---|---|---|---|---|---|---|---|
| M15 | hold (live) | 110 (53/57) | −0.015 / −0.037 | 5.2 / 7.3 | −2.9 | −0.111 | −961.7 | 988.1 | reference |
| M15 | close if ≥ +0.5R | 110 (53/57) | −0.038 / −0.019 | 5.2 / 8.0 | −3.1 | −0.111 | −961.9 | 988.4 | reject |
| M15 | stop to BE | 110 (53/57) | −0.102 / +0.025 | 9.0 / 5.8 | −4.0 | −0.111 | −962.7 | 989.1 | reject |
| H1 | hold (live) | 435 (220/215) | −0.263 / −0.032 | 58.1 / 21.6 | −64.8 | −0.069 | −616.9 | 628.9 | reference |
| H1 | close if ≥ +0.5R | 435 (220/215) | −0.279 / +0.012 | 61.6 / 12.0 | −58.8 | −0.069 | −612.9 | 623.3 | reject |
| H1 | stop to BE | 436 (221/215) | −0.206 / −0.030 | 46.8 / 14.4 | −52.0 | −0.068 | −611.3 | 625.3 | passes |

**Why the verdict is reject:**
- Break-even on H1 clears the gate by +0.002R in the second half, which is noise.
- Its H1 decision is made 20–60 min before the release, not 10 min.
- On M15, where the timing is close to the rule, it lowers first-half expectancy by 0.087R and raises drawdown from 5.2R to 9.0R.
- Closing at +0.5R fails on both timeframes.
- Keep holding through the release, as live does now.
- The H1 break-even result (+12.8R and less drawdown over 8 years) is the one lead worth re-testing. That needs an engine-level replay that decides on M5 bars exactly 10 min before the release.

## N3 — post-release sweep reversal (M5, M15)

| Symbol | TF | n | Win | Exp R | PF | 1st half | 2nd half | Spread ×2 | Always long | Flipped | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pooled | M5 | 16 | 38% | −0.160 | 0.73 | −0.069 | −0.251 | −0.181 | −0.403 | −0.102 | reject |
| pooled | M15 | 64 | 55% | +0.023 | 1.08 | −0.045 | +0.090 | −0.037 | −0.138 | −0.101 | reject |
| XAUUSD | M15 | 12 | 67% | +0.213 | 1.96 | +0.397 | +0.028 | +0.206 | +0.052 | −0.206 | reject: n 12; min lot fits 17% at $545 |
| USDCAD | M15 | 13 | 54% | +0.106 | 1.37 | −0.418 | +0.556 | −0.136 | −0.158 | −0.184 | reject |
| other symbols | M15 | 5–12 each | | ≤ +0.03 | ≤ 1.15 | | | | | | reject |

The setup fires on only about 1 event in 6. Every symbol is far below n = 100. The pooled edge is about zero and fails spread ×2. Gold's 12 trades are not evidence.

## N4 — post-release momentum (first 15 min)

| Symbol | TF | n | Win | Exp R | PF | 1st half | 2nd half | Spread ×2 | Always long | Flipped | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pooled | M5 | 127 | 45% | +0.007 | 1.02 | +0.083 | −0.068 | −0.065 | −0.140 | −0.174 | reject |
| pooled | M15 | 362 | 40% | −0.119 | 0.77 | −0.109 | −0.129 | −0.157 | −0.110 | −0.019 | reject |
| XAUUSD | M15 | 66 | 41% | +0.010 | 1.02 | +0.003 | +0.018 | −0.083 | −0.059 | +0.055 | reject |
| EURUSD | M15 | 63 | 40% | −0.158 | 0.70 | −0.229 | −0.088 | −0.169 | −0.239 | +0.004 | reject |
| GBPUSD | M15 | 63 | 40% | −0.106 | 0.79 | −0.159 | −0.054 | −0.118 | −0.338 | −0.139 | reject |
| USDJPY | M15 | 63 | 41% | −0.152 | 0.66 | −0.032 | −0.268 | −0.164 | +0.159 | +0.088 | reject |
| USDCAD | M15 | 63 | 40% | −0.232 | 0.59 | −0.148 | −0.314 | −0.309 | +0.055 | −0.128 | reject |
| BTCUSD | M15 | 44 | 36% | −0.068 | 0.89 | −0.370 | +0.234 | −0.077 | −0.295 | +0.011 | reject |

This matches Andersen–Bollerslev and Kurov et al.: the move happens before and during the release, and there is no drift to harvest after the first 15 minutes. M5 per-symbol rows (16–23 trades each) are in the raw output. EURUSD (+0.23R) and BTC (+0.53R) look positive there, but on 22 and 16 trades, and both fail the gate on n and affordability.

## What this means for the live news code

1. Widen the HIGH-impact blackout to −30/+30 min. This is the only change with evidence.
2. Keep holding open trades through the release. Do not add pre-release closes or break-even moves.
3. Do not add a post-release entry engine (sweep reversal or momentum).
4. Use `data/news_history_usd.json` as the fail-closed fallback when the feed is down: block entries in the window around any listed USD release. Before Dec 2027, extend it from the BLS and Fed schedules.

## Limits

- **USD events only.** The live blackout also covers other currencies' HIGH events, which this file does not include.
- **Timing granularity.** The M5 history is only 8 months, so N3 and N4 rely on M15, where "15–45 min after" means only two bars.
- **A losing proxy.** The N1/N2 entry proxy loses money on its own (see the caveat under Verdicts), so these are relative results.
