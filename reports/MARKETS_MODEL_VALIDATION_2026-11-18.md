# Market model validation — 2026-11-18

All data: real daily closes from the Yahoo chart API (closed bars only). Nothing simulated.

## 1. Volatility risk premium (core edge of the F&O adviser)

| Market | Underlying | Implied index | Days | IV > next-21d realised | Mean IV−RV | Median | Worst 5% |
|---|---|---|---:|---:|---:|---:|---:|
| IN | NIFTY | INDIAVIX | 2427 | 80.1% | +2.51 | +3.28 | -5.94 |
| US | SPX | VIX | 2490 | 83.3% | +3.60 | +4.65 | -7.20 |

Read: positive IV−RV means option sellers were paid more than the moves that followed; the worst-5% column is the tail risk that defined-risk structures exist to cap.

## 2. Direction models (5-day horizon, walk-forward, embargoed)

Published only if out-of-sample Brier beats the base rate by ≥ 0.002 over ≥ 150 test days.

| Market | Symbol | Test days | Brier model | Brier base | Gain | Hit rate | Published |
|---|---|---:|---:|---:|---:|---:|---|
| IN | NIFTY | 2151 | 0.2580 | 0.2485 | -0.0095 | 55.8% | no |
| IN | BANKNIFTY | 2152 | 0.2573 | 0.2496 | -0.0077 | 54.3% | no |
| IN | FINNIFTY | 2137 | 0.2610 | 0.2506 | -0.0104 | 54.2% | no |
| IN | SENSEX | 2148 | 0.2571 | 0.2479 | -0.0092 | 55.8% | no |
| IN | RELIANCE | 2156 | 0.2575 | 0.2496 | -0.0079 | 52.2% | no |
| IN | HDFCBANK | 2156 | 0.2622 | 0.2527 | -0.0095 | 49.5% | no |
| IN | ICICIBANK | 2156 | 0.2535 | 0.2498 | -0.0037 | 50.5% | no |
| IN | INFY | 2156 | 0.2517 | 0.2483 | -0.0035 | 53.5% | no |
| IN | TCS | 2156 | 0.2569 | 0.2508 | -0.0060 | 54.2% | no |
| IN | SBIN | 2156 | 0.2525 | 0.2491 | -0.0035 | 52.3% | no |
| IN | AXISBANK | 2156 | 0.2581 | 0.2494 | -0.0086 | 53.1% | no |
| IN | KOTAKBANK | 2156 | 0.2577 | 0.2521 | -0.0056 | 50.0% | no |
| IN | LT | 2156 | 0.2546 | 0.2497 | -0.0049 | 51.7% | no |
| IN | ITC | 2156 | 0.2577 | 0.2510 | -0.0067 | 48.6% | no |
| IN | BHARTIARTL | 2156 | 0.2545 | 0.2497 | -0.0048 | 49.1% | no |
| IN | HINDUNILVR | 2156 | 0.2606 | 0.2533 | -0.0073 | 49.7% | no |
| IN | BAJFINANCE | 2156 | 0.2566 | 0.2500 | -0.0065 | 52.2% | no |
| IN | MARUTI | 2156 | 0.2601 | 0.2516 | -0.0084 | 48.5% | no |
| IN | SUNPHARMA | 2156 | 0.2531 | 0.2490 | -0.0041 | 50.7% | no |
| IN | TITAN | 2156 | 0.2525 | 0.2465 | -0.0060 | 55.8% | no |
| US | SPY | 2197 | 0.2490 | 0.2411 | -0.0079 | 58.6% | no |
| US | QQQ | 2197 | 0.2500 | 0.2428 | -0.0073 | 58.2% | no |
| US | AAPL | 2197 | 0.2500 | 0.2444 | -0.0056 | 56.6% | no |
| US | MSFT | 2197 | 0.2524 | 0.2448 | -0.0077 | 58.0% | no |
| US | NVDA | 2197 | 0.2507 | 0.2466 | -0.0041 | 57.0% | no |
| US | AMZN | 2197 | 0.2550 | 0.2500 | -0.0050 | 54.4% | no |
| US | GOOGL | 2197 | 0.2531 | 0.2470 | -0.0061 | 55.2% | no |
| US | META | 2197 | 0.2574 | 0.2482 | -0.0092 | 52.8% | no |
| US | TSLA | 2197 | 0.2574 | 0.2506 | -0.0068 | 51.0% | no |
| US | JPM | 2197 | 0.2559 | 0.2478 | -0.0081 | 52.9% | no |
| US | AMD | 2197 | 0.2566 | 0.2485 | -0.0081 | 52.6% | no |
| US | AVGO | 2197 | 0.2517 | 0.2478 | -0.0039 | 54.0% | no |

**0 of 32 direction models published.** Symbols without a published model get no directional view: the adviser then relies only on the volatility edge and shows trend/OI as unvalidated context.

## 3. Cross-sectional momentum (12-1 month, equities scanner universes)

Each month end: rank eligible stocks by their return from month t-12 to t-1 (most recent month skipped), hold the top quintile equal-weight for the next month, compare with the equal-weight eligible universe. Real month-end closes from Yahoo daily bars; a stock is eligible only with real closes for every month needed. Published only if t-stat >= 2 and >= 55% of months beat the universe.

### IN — PUBLISHED

t-stat 2.35 and 59.8% positive months meet the bar (t >= 2 and >= 55%). Universe 36 symbols, 36 with >= 14 month-ends; 107 test months 2017-12 to 2026-10, avg 32.1 names eligible.

| Period | Months | Mean monthly excess | t-stat | % months positive | Max DD of excess | Cumulative excess |
|---|---:|---:|---:|---:|---:|---:|
| 2017 | 1 | 2.48% | — | —% | —% | —% |
| 2018 | 12 | 0.552% | 0.85 | 50.0% | -2.71% | 6.54% |
| 2019 | 12 | 0.972% | 1.16 | 58.3% | -4.29% | 11.79% |
| 2020 | 12 | 0.997% | 0.66 | 66.7% | -13.28% | 10.98% |
| 2021 | 12 | 6.334% | 1.99 | 66.7% | -15.8% | 97.28% |
| 2022 | 12 | -1.163% | -1.01 | 50.0% | -14.52% | -13.88% |
| 2023 | 12 | 0.687% | 0.78 | 58.3% | -4.55% | 8.02% |
| 2024 | 12 | 2.948% | 3.55 | 91.7% | -0.84% | 41.11% |
| 2025 | 12 | 0.634% | 0.69 | 66.7% | -7.23% | 7.29% |
| 2026 | 10 | -1.985% | -2.41 | 20.0% | -18.43% | -18.43% |
| **overall** | 107 | 1.179% | 2.35 | 59.8% | -18.67% | 207.01% |

### US — PUBLISHED

t-stat 2.87 and 62.6% positive months meet the bar (t >= 2 and >= 55%). Universe 46 symbols, 46 with >= 14 month-ends; 107 test months 2017-12 to 2026-10, avg 40.7 names eligible.

| Period | Months | Mean monthly excess | t-stat | % months positive | Max DD of excess | Cumulative excess |
|---|---:|---:|---:|---:|---:|---:|
| 2017 | 1 | -0.29% | — | —% | —% | —% |
| 2018 | 12 | 0.251% | 0.17 | 58.3% | -14.92% | 1.52% |
| 2019 | 12 | 0.654% | 0.59 | 50.0% | -8.6% | 7.26% |
| 2020 | 12 | 5.768% | 4.12 | 91.7% | -0.07% | 93.78% |
| 2021 | 12 | 1.562% | 0.56 | 50.0% | -11.84% | 14.75% |
| 2022 | 12 | 2.653% | 2.02 | 75.0% | -8.61% | 35.39% |
| 2023 | 12 | 0.435% | 0.18 | 66.7% | -22.64% | 1.01% |
| 2024 | 12 | 4.572% | 1.43 | 66.7% | -14.79% | 61.16% |
| 2025 | 12 | 0.45% | 0.32 | 58.3% | -12.37% | 4.13% |
| 2026 | 10 | 2.935% | 0.77 | 50.0% | -16.47% | 25.59% |
| **overall** | 107 | 2.105% | 2.87 | 62.6% | -22.64% | 595.85% |

**Survivorship bias:** Universe = today's large caps (the scanner list), back-filled 10 years: stocks that fell out or were delisted are missing, and names that became large caps are included before they were. This biases momentum results upward; treat the numbers as an optimistic upper bound.

## 4. Institutional positioning (NSE participant-wise OI)

(a) FII index-futures long % = long / (long + short) from NSCCL `fao_participant_oi` files. Signal on day t when it is below the 20th / above the 80th percentile of the previous 250 files. Outcome: NIFTY close(t+1) → close(t+6) (the file comes out after t's close). t-stat on non-overlapping events; Brier compares P(up | same signal, past only) with the past base rate.

**Not published** — best |t| 0.58 on 63 non-overlapping events, OOS Brier gain -0.00273 over 387 signal days: does not meet the bar (|t| >= 2, >= 30 events, Brier gain >= 0.002)

Test window 2022-08-12 to 2026-11-06 (1044 days); base: mean 5-day NIFTY return 0.185%, up 54.2% of the time.

| FII long % signal | Days | Non-overlapping | Mean 5d return | Up rate | Mean excess | t-stat |
|---|---:|---:|---:|---:|---:|---:|
| low | 298 | 63 | 0.325% | 59.4% | +0.129% | 0.58 |
| high | 134 | 28 | 0.131% | 54.5% | -0.099% | -0.32 |

OOS Brier on 387 signal days: model 0.25262 vs base 0.24989 (gain -0.00273).

(b) PCR: skipped: no historical option-chain PCR source (only today's chain is served; markets.db snapshots are too short).
(c) Futures basis: skipped: futures basis history exists only inside the daily NSE F&O bhavcopy (~1.4 MB/day zip, ~1 GB for 3 years); not downloaded for this run.

_Run time 58s._
