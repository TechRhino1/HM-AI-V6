# Market model validation (section 5 only) — 2026-11-18

## 5. Global institutional (CFTC COT, dollar, yields) — forex / gold / crypto

Real data only: CFTC Legacy futures-only COT (publicreporting.cftc.gov dataset 6dca-aqww, since 2010), Yahoo daily closes (FX relabelled to the session they close; XAUUSD = COMEX GC=F). Same bar as section 4: |t| >= 2 on >= 30 non-overlapping events and OOS Brier gain >= 0.002.

(a) COT extremes (3y index < 10 long / > 90 short, entry first close after the Friday release, 4-week hold): **not published** — pooled contrarian t 1.21 on 236 non-overlapping extremes, OOS Brier gain -0.0032 over 596 obs: does not meet the bar (t >= 2, >= 30 events, Brier gain >= 0.002)

| Symbol | Weeks | Signal | Events | Non-overlapping | Mean 4w fwd | Up rate | Mean excess | t |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| EURUSD | 721 | high | 69 | 20 | 0.19% | 50.7% | +0.467% | 1.04 |
| EURUSD | 721 | low | 36 | 11 | -0.017% | 50.0% | +0.169% | 0.19 |
| GBPUSD | 721 | high | 58 | 21 | -0.538% | 39.7% | -0.462% | -1.04 |
| GBPUSD | 721 | low | 50 | 16 | 0.432% | 74.0% | +0.186% | 0.21 |
| USDJPY | 721 | high | 82 | 29 | 0.003% | 51.2% | -0.634% | -1.06 |
| USDJPY | 721 | low | 108 | 30 | -0.1% | 46.3% | -0.533% | -1.18 |
| USDCAD | 721 | high | 90 | 29 | -0.265% | 43.3% | -0.372% | -1.14 |
| USDCAD | 721 | low | 47 | 14 | 0.571% | 66.0% | +0.705% | 1.91 |
| XAUUSD | 721 | high | 59 | 18 | 1.319% | 71.2% | +0.984% | 1.51 |
| XAUUSD | 721 | low | 68 | 19 | 0.397% | 63.2% | +0.539% | 0.56 |
| BTCUSD | 290 | high | 57 | 19 | -0.109% | 54.4% | -3.315% | -0.97 |
| BTCUSD | 290 | low | 9 | 4 | 0.887% | 44.4% | -3.363% | -0.75 |
| ETHUSD | 134 | high | 17 | 5 | -3.726% | 29.4% | -5.490% | -0.51 |
| ETHUSD | 134 | low | 2 | 1 | 34.84% | 100.0% | +15.517% | None |

(b) DXY 20d trend → EURUSD next 5d: **not published** — best |t| 0.96 on 373 non-overlapping events, OOS Brier gain -0.00207 over 2951 signal obs: does not meet the bar (|t| >= 2, >= 30 events, Brier gain >= 0.002)

Window 2006-12-18 to 2026-11-06 (4975 days), base mean -0.019%, up 49.3%; Brier model 0.25255 vs base 0.25048.

| Driver signal | Days | Non-overlapping | Mean 5d fwd | Up rate | Mean excess | t |
|---|---:|---:|---:|---:|---:|---:|
| down | 1441 | 373 | -0.005% | 49.4% | +0.061% | 0.96 |
| up | 1551 | 403 | -0.036% | 49.3% | +0.012% | 0.17 |

(b) DXY 20d trend → XAUUSD next 5d: **not published** — best |t| 0.22 on 400 non-overlapping events, OOS Brier gain -0.00218 over 2973 signal obs: does not meet the bar (|t| >= 2, >= 30 events, Brier gain >= 0.002)

Window 2006-12-18 to 2026-11-09 (5003 days), base mean 0.215%, up 55.3%; Brier model 0.25096 vs base 0.24878.

| Driver signal | Days | Non-overlapping | Mean 5d fwd | Up rate | Mean excess | t |
|---|---:|---:|---:|---:|---:|---:|
| down | 1446 | 364 | 0.234% | 55.4% | +0.011% | 0.08 |
| up | 1568 | 400 | 0.237% | 54.8% | +0.032% | 0.22 |

(c) 10y yield 20d change → XAUUSD next 5d: **not published** — best |t| 0.23 on 328 non-overlapping events, OOS Brier gain -0.00269 over 2389 signal obs: does not meet the bar (|t| >= 2, >= 30 events, Brier gain >= 0.002)

Window 2006-12-18 to 2026-11-09 (5000 days), base mean 0.216%, up 55.3%; Brier model 0.2488 vs base 0.2461.

| Driver signal | Days | Non-overlapping | Mean 5d fwd | Up rate | Mean excess | t |
|---|---:|---:|---:|---:|---:|---:|
| down | 1190 | 314 | 0.365% | 57.0% | -0.010% | -0.06 |
| up | 1247 | 328 | 0.291% | 57.3% | +0.032% | 0.23 |

Unpublished tests stay labelled "context · not validated" in /api/markets/inst/global.

