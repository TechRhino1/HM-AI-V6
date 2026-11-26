# HM Algo — Backtest on Real MT5 Data (730d cache, scored from 2026-05-24)

**Mode:** calibrated per-symbol win-rate profiles  
**Data:** MT5 terminal, real H1 bars (validated non-synthetic)  
**Initial balance:** $10,000.00 at 0.5% risk per trade  
**Generated:** 2026-11-24T23:59:50.391246+00:00

## 1. Headline

| Metric | Value |
|---|---|
| Symbols traded | 16 |
| Total trades | 2201 |
| Win rate | 42.34% |
| Expectancy | -0.0177 R per trade |
| Average win / loss | +1.235 R / -0.939 R |
| Payoff ratio | 1.316 |
| Total R | -38.91 R |
| Profit factor | 0.91 |
| Net profit | $-2,052.40 |
| Max drawdown | 33.68% |
| Sharpe / Sortino / Calmar | -0.56 / -1.44 / -0.59 |
| Expectancy (sample-uniqueness weighted) | -0.0188 R |

**Win-rate target outcome:** 0/16 symbols met the target out-of-sample. 0 met it in-sample but failed out-of-sample (i.e. the target was reachable only by overfitting).

## 2. Per-symbol results

| Symbol | Trades | WR % | Exp (R) | PF | Net $ | MaxDD % | OOS WR % | OOS Exp (R) | Target | Binding constraint |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|---|
| XAUUSD | 533 | 39.2 | +0.068 | 1.08 | +451.46 | 3.88 | 65.2 | +1.255 | ✗ | win rate - best achievable in-sample with positive expectancy is 54.2% |
| XAGUSD | 250 | 37.6 | +0.002 | 0.97 | -163.50 | 12.60 | 55.7 | +0.878 | ✗ | win rate - best achievable in-sample with positive expectancy is 58.2% |
| SOLUSD | 202 | 39.1 | -0.196 | 0.29 | -1,038.24 | 10.39 | 69.9 | +0.200 | ✗ | selection stability - 75.6% is reachable in-sample (tp0.4_beoff_pcoffx |
| USDCAD | 193 | 45.1 | +0.003 | 0.97 | -43.79 | 2.99 | 42.1 | +0.145 | ✗ | win rate - best achievable in-sample with positive expectancy is 62.1% |
| UK100 | 180 | 27.8 | -0.146 | 0.55 | -678.34 | 7.69 | 62.7 | +0.868 | ✗ | win rate - best achievable in-sample with positive expectancy is 74.7% |
| NAS100 | 168 | 41.1 | -0.080 | 0.86 | -223.02 | 2.53 | 52.0 | +0.436 | ✗ | win rate - best achievable in-sample with positive expectancy is 68.9% |
| US30 | 149 | 36.2 | -0.119 | 0.78 | -303.16 | 3.45 | 47.5 | +0.445 | ✗ | win rate - best achievable in-sample with positive expectancy is 68.8% |
| GER40 | 138 | 42.0 | +0.099 | 1.14 | +182.66 | 2.72 | 44.1 | +0.396 | ✗ | win rate - best achievable in-sample with positive expectancy is 70.1% |
| ETHUSD | 130 | 39.2 | -0.081 | 0.68 | -344.72 | 5.23 | 32.1 | -0.037 | ✗ | win rate - best achievable in-sample with positive expectancy is 73.4% |
| GBPUSD | 130 | 41.5 | +0.045 | 0.95 | -54.97 | 2.82 | 32.8 | +0.036 | ✗ | win rate - best achievable in-sample with positive expectancy is 64.5% |
| BTCUSD | 128 | 51.6 | +0.094 | 1.16 | +163.22 | 2.13 | 66.7 | +0.632 | ✗ | win rate - best achievable in-sample with positive expectancy is 72.2% |
| AUDUSD | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 22.8 | -0.375 | ✗ | win rate - best achievable in-sample with positive expectancy is 45.8% |
| EURUSD | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 28.1 | -0.215 | ✗ | win rate - best achievable in-sample with positive expectancy is 65.0% |
| NZDUSD | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 32.4 | -0.248 | ✗ | win rate - best achievable in-sample with positive expectancy is 53.7% |
| USDCHF | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 27.9 | -0.147 | ✗ | win rate - best achievable in-sample with positive expectancy is 62.6% |
| USDJPY | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 37.1 | -0.059 | ✗ | win rate - best achievable in-sample with positive expectancy is 54.3% |

### 2a. What the learned regime policy contributes

Calibration reports the same out-of-sample sample twice: once with every regime enabled, and once with the regimes the learned policy has switched off removed. Both are purged out-of-sample w.r.t. the geometry and threshold; the policy itself is fitted on **training folds only**, so it has never seen the out-of-sample bars it filters. The gap between the two columns is the policy's entire contribution — read it as the honest size of the effect, not as free money.

| Symbol | OOS n (all regimes) | OOS WR | OOS Exp (R) | OOS n (policy applied) | OOS WR | OOS Exp (R) | Policy fitted on |
|---|---:|---:|---:|---:|---:|---:|---|
| XAUUSD | 587 | 65.2 | +1.255 | 587 | 65.2 | +1.255 | train folds |
| XAGUSD | 1464 | 55.7 | +0.878 | 1464 | 55.7 | +0.878 | train folds |
| SOLUSD | 145 | 70.3 | +0.206 | 143 | 69.9 | +0.200 | train folds |
| USDCAD | 243 | 39.9 | +0.085 | 223 | 42.1 | +0.145 | train folds |
| UK100 | 110 | 62.7 | +0.868 | 110 | 62.7 | +0.868 | train folds |
| NAS100 | 639 | 51.8 | +0.430 | 633 | 52.0 | +0.436 | train folds |
| US30 | 61 | 47.5 | +0.445 | 61 | 47.5 | +0.445 | train folds |
| GER40 | 93 | 44.1 | +0.396 | 93 | 44.1 | +0.396 | train folds |
| ETHUSD | 196 | 32.1 | -0.037 | 196 | 32.1 | -0.037 | train folds |
| GBPUSD | 157 | 42.0 | +0.324 | 192 | 32.8 | +0.036 | train folds |
| BTCUSD | 24 | 66.7 | +0.632 | 24 | 66.7 | +0.632 | train folds |
| AUDUSD | 133 | 17.3 | -0.569 | 127 | 22.8 | -0.375 | train folds |
| EURUSD | 194 | 27.8 | -0.177 | 146 | 28.1 | -0.215 | train folds |
| NZDUSD | 34 | 32.4 | -0.248 | 34 | 32.4 | -0.248 | train folds |
| USDCHF | 178 | 29.2 | -0.127 | 129 | 27.9 | -0.147 | train folds |
| USDJPY | 124 | 37.1 | -0.059 | 124 | 37.1 | -0.059 | train folds |

## 3. Win-rate / expectancy frontier

For each target size (`tp_r`, as a multiple of initial risk) the table gives the highest win rate found at all, and the highest win rate that still carries positive expectancy. Where those two diverge, the gap is win rate that can only be bought by running a losing system. This is the direct evidence for whether the 75% target is reachable.

**AUDUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 59.1% | -0.179 | 1277 | — | — | — |
| 0.5 | 58.0% | -0.141 | 1232 | — | — | — |
| 0.6 | 57.7% | -0.095 | 1154 | — | — | — |
| 0.75 | 55.3% | -0.086 | 443 | — | — | — |
| 1 | 52.6% | -0.054 | 403 | — | — | — |
| 1.5 | 45.8% | +0.021 | 642 | 45.8% | +0.021 | 642 |
| 2 | 38.9% | +0.038 | 396 | 38.9% | +0.038 | 396 |
| 2.5 | 42.3% | +0.227 | 246 | 42.3% | +0.227 | 246 |

**BTCUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 70.9% | +0.057 | 512 | 70.9% | +0.057 | 512 |
| 0.5 | 69.4% | +0.092 | 458 | 69.4% | +0.092 | 458 |
| 0.6 | 72.2% | +0.158 | 663 | 72.2% | +0.160 | 663 |
| 0.75 | 69.6% | +0.224 | 329 | 69.6% | +0.224 | 329 |
| 1 | 66.7% | +0.279 | 514 | 66.7% | +0.279 | 514 |
| 1.5 | 58.2% | +0.367 | 153 | 58.2% | +0.367 | 153 |
| 2 | 57.8% | +0.602 | 90 | 57.8% | +0.602 | 90 |
| 2.5 | 51.7% | +0.525 | 87 | 51.7% | +0.525 | 87 |

**ETHUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 71.9% | +0.051 | 558 | 71.9% | +0.051 | 558 |
| 0.5 | 71.7% | +0.093 | 728 | 71.7% | +0.093 | 728 |
| 0.6 | 72.4% | +0.167 | 635 | 72.4% | +0.168 | 635 |
| 0.75 | 71.0% | +0.232 | 535 | 71.0% | +0.232 | 535 |
| 1 | 68.0% | +0.313 | 444 | 68.0% | +0.313 | 444 |
| 1.5 | 72.7% | +0.747 | 242 | 72.7% | +0.747 | 242 |
| 2 | 73.4% | +1.054 | 327 | 73.4% | +1.054 | 327 |
| 2.5 | 58.7% | +0.772 | 208 | 58.7% | +0.772 | 208 |

**EURUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 66.5% | -0.079 | 535 | — | — | — |
| 0.5 | 64.8% | -0.035 | 304 | — | — | — |
| 0.6 | 65.0% | +0.016 | 294 | 65.0% | +0.018 | 294 |
| 0.75 | 63.0% | +0.053 | 281 | 63.0% | +0.053 | 281 |
| 1 | 63.5% | +0.163 | 252 | 63.5% | +0.163 | 252 |
| 1.5 | 60.0% | +0.282 | 300 | 60.0% | +0.282 | 300 |
| 2 | 57.1% | +0.484 | 336 | 57.1% | +0.484 | 336 |
| 2.5 | 54.9% | +0.542 | 233 | 54.9% | +0.542 | 233 |

**GBPUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 65.5% | -0.092 | 595 | — | — | — |
| 0.5 | 64.7% | -0.051 | 567 | — | — | — |
| 0.6 | 64.5% | +0.003 | 544 | 64.5% | +0.004 | 544 |
| 0.75 | 61.4% | +0.026 | 505 | 61.4% | +0.026 | 505 |
| 1 | 58.1% | +0.046 | 449 | 58.1% | +0.046 | 449 |
| 1.5 | 49.6% | +0.041 | 345 | 49.6% | +0.041 | 345 |
| 2 | 45.0% | +0.144 | 496 | 45.0% | +0.144 | 496 |
| 2.5 | 41.5% | +0.288 | 342 | 41.5% | +0.288 | 342 |

**GER40**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 70.5% | -0.026 | 589 | — | — | — |
| 0.5 | 70.1% | +0.027 | 572 | 70.1% | +0.027 | 572 |
| 0.6 | 69.0% | +0.076 | 554 | 69.0% | +0.076 | 554 |
| 0.75 | 67.6% | +0.147 | 521 | 67.6% | +0.147 | 521 |
| 1 | 65.9% | +0.234 | 461 | 65.9% | +0.234 | 461 |
| 1.5 | 59.8% | +0.373 | 552 | 59.8% | +0.373 | 552 |
| 2 | 61.7% | +0.726 | 381 | 61.7% | +0.726 | 381 |
| 2.5 | 53.7% | +0.723 | 354 | 53.7% | +0.723 | 354 |

**NAS100**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 69.7% | -0.036 | 594 | — | — | — |
| 0.5 | 68.9% | +0.014 | 578 | 68.9% | +0.014 | 578 |
| 0.6 | 68.6% | +0.068 | 561 | 68.6% | +0.070 | 561 |
| 0.75 | 67.5% | +0.139 | 514 | 67.5% | +0.139 | 514 |
| 1 | 64.0% | +0.208 | 472 | 64.0% | +0.208 | 472 |
| 1.5 | 58.5% | +0.279 | 561 | 58.5% | +0.279 | 561 |
| 2 | 54.7% | +0.515 | 245 | 54.7% | +0.515 | 245 |
| 2.5 | 44.7% | +0.385 | 190 | 44.7% | +0.385 | 190 |

**NZDUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 59.9% | -0.175 | 892 | — | — | — |
| 0.5 | 58.1% | -0.141 | 1130 | — | — | — |
| 0.6 | 57.0% | -0.112 | 793 | — | — | — |
| 0.75 | 56.0% | -0.063 | 741 | — | — | — |
| 1 | 53.7% | +0.017 | 1138 | 53.7% | +0.017 | 1138 |
| 1.5 | 49.0% | +0.098 | 829 | 49.0% | +0.098 | 829 |
| 2 | 43.9% | +0.198 | 431 | 43.9% | +0.198 | 431 |
| 2.5 | 40.4% | +0.269 | 416 | 40.4% | +0.269 | 416 |

**SOLUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 75.6% | +0.102 | 512 | 75.6% | +0.102 | 512 |
| 0.5 | 74.8% | +0.153 | 421 | 74.8% | +0.153 | 421 |
| 0.6 | 72.5% | +0.181 | 375 | 72.5% | +0.183 | 375 |
| 0.75 | 71.5% | +0.226 | 316 | 71.5% | +0.226 | 316 |
| 1 | 63.9% | +0.192 | 238 | 63.9% | +0.192 | 238 |
| 1.5 | 55.4% | +0.240 | 159 | 55.4% | +0.240 | 159 |
| 2 | 50.3% | +0.333 | 149 | 50.3% | +0.333 | 149 |
| 2.5 | 41.9% | -0.000 | 74 | 41.2% | +0.037 | 51 |

**UK100**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 74.7% | +0.041 | 601 | 74.7% | +0.041 | 601 |
| 0.5 | 73.8% | +0.094 | 573 | 73.8% | +0.094 | 573 |
| 0.6 | 72.9% | +0.143 | 557 | 72.9% | +0.144 | 557 |
| 0.75 | 71.7% | +0.208 | 523 | 71.7% | +0.208 | 523 |
| 1 | 68.3% | +0.269 | 464 | 68.3% | +0.269 | 464 |
| 1.5 | 64.5% | +0.435 | 313 | 64.5% | +0.435 | 313 |
| 2 | 56.6% | +0.457 | 228 | 56.6% | +0.457 | 228 |
| 2.5 | 57.2% | +0.800 | 271 | 57.2% | +0.800 | 271 |

**US30**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 68.1% | -0.055 | 565 | — | — | — |
| 0.5 | 67.4% | -0.004 | 540 | 67.2% | +0.004 | 2351 |
| 0.6 | 68.8% | +0.078 | 516 | 68.8% | +0.078 | 516 |
| 0.75 | 66.7% | +0.126 | 489 | 66.7% | +0.126 | 489 |
| 1 | 65.5% | +0.235 | 893 | 65.5% | +0.235 | 893 |
| 1.5 | 60.2% | +0.370 | 641 | 60.2% | +0.370 | 641 |
| 2 | 54.9% | +0.411 | 559 | 54.9% | +0.411 | 559 |
| 2.5 | 52.6% | +0.665 | 342 | 52.6% | +0.665 | 342 |

**USDCAD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 65.0% | -0.094 | 1101 | — | — | — |
| 0.5 | 64.1% | -0.060 | 848 | — | — | — |
| 0.6 | 62.7% | -0.018 | 1041 | — | — | — |
| 0.75 | 62.1% | +0.054 | 960 | 62.1% | +0.054 | 960 |
| 1 | 59.3% | +0.134 | 1146 | 59.3% | +0.134 | 1146 |
| 1.5 | 55.0% | +0.268 | 815 | 55.0% | +0.268 | 815 |
| 2 | 55.9% | +0.530 | 433 | 55.9% | +0.530 | 433 |
| 2.5 | 47.8% | +0.329 | 381 | 47.8% | +0.329 | 381 |

**USDCHF**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 64.0% | -0.105 | 676 | — | — | — |
| 0.5 | 63.3% | -0.056 | 644 | — | — | — |
| 0.6 | 62.6% | -0.001 | 436 | 62.6% | +0.002 | 436 |
| 0.75 | 62.6% | +0.067 | 567 | 62.6% | +0.067 | 567 |
| 1 | 61.2% | +0.152 | 392 | 61.2% | +0.152 | 392 |
| 1.5 | 57.4% | +0.309 | 324 | 57.4% | +0.309 | 324 |
| 2 | 56.1% | +0.497 | 253 | 56.1% | +0.497 | 253 |
| 2.5 | 55.4% | +0.661 | 186 | 55.4% | +0.661 | 186 |

**USDJPY**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 60.2% | -0.161 | 1499 | — | — | — |
| 0.5 | 59.5% | -0.118 | 1418 | — | — | — |
| 0.6 | 58.9% | -0.072 | 1381 | — | — | — |
| 0.75 | 57.7% | -0.018 | 1292 | — | — | — |
| 1 | 54.3% | +0.026 | 1136 | 54.3% | +0.026 | 1136 |
| 1.5 | 49.1% | +0.125 | 751 | 49.1% | +0.125 | 751 |
| 2 | 43.6% | +0.153 | 491 | 43.6% | +0.153 | 491 |
| 2.5 | 36.5% | +0.021 | 351 | 36.5% | +0.021 | 351 |

**XAGUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 59.2% | -0.179 | 2326 | — | — | — |
| 0.5 | 58.7% | -0.130 | 1710 | — | — | — |
| 0.6 | 58.7% | -0.074 | 1700 | — | — | — |
| 0.75 | 58.2% | +0.004 | 1686 | 58.2% | +0.004 | 1686 |
| 1 | 57.9% | +0.127 | 2230 | 57.9% | +0.127 | 2230 |
| 1.5 | 57.4% | +0.370 | 1578 | 57.4% | +0.370 | 1578 |
| 2 | 56.5% | +0.639 | 1921 | 56.5% | +0.639 | 1921 |
| 2.5 | 55.6% | +0.851 | 1770 | 55.6% | +0.851 | 1770 |

**XAUUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 54.8% | -0.237 | 2473 | — | — | — |
| 0.5 | 54.3% | -0.189 | 2465 | — | — | — |
| 0.6 | 54.3% | -0.136 | 2459 | — | — | — |
| 0.75 | 54.2% | -0.061 | 2445 | — | — | — |
| 1 | 54.2% | +0.065 | 2417 | 54.2% | +0.065 | 2417 |
| 1.5 | 53.6% | +0.300 | 2351 | 53.6% | +0.300 | 2351 |
| 2 | 52.9% | +0.533 | 2271 | 52.9% | +0.533 | 2271 |
| 2.5 | 53.0% | +0.743 | 2244 | 53.0% | +0.743 | 2244 |

## 4. Calibrated geometry per symbol

`tp_r` is the target distance in multiples of initial risk; `be` is the breakeven trigger (off = never lock breakeven); `pc` the partial bank; `mb` the time stop in bars; `thr` the entry score threshold.

The last two columns come from the isotonic score calibration: the realised win probability the fitted map assigns to a score sitting exactly at the deployed threshold, and the Brier score of that map (lower is better; 0.25 is the skill-free baseline for a balanced sample). The calibration is monotone, so it cannot change which candidates pass — it exists to make the score interpretable and to give the AI layer a probability rather than an arbitrary index.

| Symbol | tp_r | be | pc | mb | threshold | P(win) @ thr | Brier | Enabled regimes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| AUDUSD | 2.5 | off | off | 24 | 0.250 | 0.0% | 0.139 | TREND_BULL, TREND_BEAR, WEAK_TREND, CONSOLIDATION |
| BTCUSD | 2 | off | off | 48 | 0.423 | 66.7% | 0.222 | TREND_BEAR, TREND_BULL, BREAKOUT, RANGE, REVERSAL, WEAK_TREND |
| ETHUSD | 2 | 1 | off | 48 | 0.330 | 20.8% | 0.212 | TREND_BEAR, TREND_BULL, LIQUIDITY_SWEEP, BREAKOUT, RANGE, WEAK_TREND, REVERSAL, CONSOLIDATION |
| EURUSD | 2.5 | off | off | 24 | 0.300 | 16.0% | 0.198 | LIQUIDITY_SWEEP, TREND_BULL, RANGE, REVERSAL, BREAKOUT, CONSOLIDATION |
| GBPUSD | 2.5 | off | off | 48 | 0.290 | 30.0% | 0.240 | TREND_BULL, TREND_BEAR, LIQUIDITY_SWEEP, REVERSAL, BREAKOUT, WEAK_TREND, CONSOLIDATION |
| GER40 | 2.5 | off | off | 48 | 0.423 | 41.3% | 0.245 | TREND_BULL, BREAKOUT, RANGE, TREND_BEAR, REVERSAL, LIQUIDITY_SWEEP, CONSOLIDATION, WEAK_TREND |
| NAS100 | 2 | off | off | 48 | 0.365 | 48.5% | 0.249 | TREND_BEAR, TREND_BULL, REVERSAL, RANGE, LIQUIDITY_SWEEP, BREAKOUT |
| NZDUSD | 2 | off | off | 24 | 0.416 | 20.0% | 0.216 | TREND_BULL, LIQUIDITY_SWEEP, TREND_BEAR, REVERSAL, BREAKOUT, WEAK_TREND |
| SOLUSD | 0.75 | off | off | 48 | 0.479 | 55.6% | 0.202 | TREND_BEAR, TREND_BULL, LIQUIDITY_SWEEP, REVERSAL, CONSOLIDATION, WEAK_TREND |
| UK100 | 2.5 | 1 | off | 24 | 0.403 | 50.0% | 0.225 | TREND_BULL, TREND_BEAR, RANGE, REVERSAL, LIQUIDITY_SWEEP, BREAKOUT, CONSOLIDATION |
| US30 | 2.5 | off | off | 48 | 0.377 | 40.5% | 0.235 | TREND_BULL, TREND_BEAR, LIQUIDITY_SWEEP, RANGE, REVERSAL, BREAKOUT, WEAK_TREND, CONSOLIDATION |
| USDCAD | 2 | off | off | 24 | 0.412 | 39.9% | 0.240 | TREND_BEAR, REVERSAL, TREND_BULL, RANGE, WEAK_TREND, CONSOLIDATION |
| USDCHF | 2.5 | off | off | 48 | 0.387 | 22.7% | 0.204 | TREND_BEAR, REVERSAL, LIQUIDITY_SWEEP, RANGE, BREAKOUT, CONSOLIDATION, WEAK_TREND |
| USDJPY | 2 | 1 | off | 48 | 0.384 | 37.1% | 0.233 | TREND_BEAR, LIQUIDITY_SWEEP, RANGE, TREND_BULL, REVERSAL, BREAKOUT, WEAK_TREND, CONSOLIDATION |
| XAGUSD | 2.5 | off | off | 48 | 0.420 | 53.6% | 0.246 | TREND_BULL, TREND_BEAR, RANGE, REVERSAL, WEAK_TREND, LIQUIDITY_SWEEP, BREAKOUT, CONSOLIDATION |
| XAUUSD | 2.5 | off | off | 24 | 0.439 | 62.1% | 0.225 | TREND_BEAR, REVERSAL, TREND_BULL, LIQUIDITY_SWEEP, BREAKOUT, RANGE, CONSOLIDATION, WEAK_TREND |

## 5. Portfolio risk allocation (HRP)

Inverse-variance weights from the HRP allocator over per-symbol daily R:

| Symbol | Risk weight |
|---|---:|
| ETHUSD | 15.63% |
| SOLUSD | 15.33% |
| BTCUSD | 14.32% |
| USDCAD | 9.26% |
| US30 | 8.88% |
| GBPUSD | 8.86% |
| UK100 | 7.68% |
| GER40 | 7.07% |
| NAS100 | 6.97% |
| XAGUSD | 4.31% |
| XAUUSD | 1.69% |

## 6. Entry rejection analysis

Why candidates were not traded under the calibrated profile. In calibrated mode these are the capital-protection gates plus the calibrated edge filter; the legacy 29-check stack no longer decides.

Counts are per **bar evaluated**, not per candidate: a bar on which the pipeline found no setup at all (`no directional bias`) is counted here too, because the engine has to consider and decline it. A large `no directional bias` count therefore means the pipeline rarely formed a view, not that a good trade was vetoed.

| Symbol | Top rejection reasons |
|---|---|
| XAUUSD | capital protection: Directional Bias (103); Cooldown active: 2 bars remaining. (77); Cooldown active: 1 bars remaining. (77) |
| XAGUSD | Cooldown active: 2 bars remaining. (40); Cooldown active: 1 bars remaining. (40); capital protection: Directional Bias (37) |
| SOLUSD | Cooldown active: 1 bars remaining. (41); capital protection: Directional Bias (38); Cooldown active: 2 bars remaining. (38) |
| USDCAD | capital protection: Forex Prime Session (310); capital protection: Forex Prime Session, Directional Bias (61); capital protection: Directional Bias (2 |
| UK100 | capital protection: Forex Prime Session (323); capital protection: Forex Prime Session, Directional Bias (78); Cooldown active: 2 bars remaining. (57) |
| NAS100 | capital protection: Forex Prime Session (523); capital protection: Forex Prime Session, Directional Bias (56); capital protection: Forex Prime Session |
| US30 | capital protection: Forex Prime Session (224); capital protection: Forex Prime Session, Directional Bias, Strategy Viable (29); Cooldown active: 2 bar |
| GER40 | capital protection: Forex Prime Session (258); capital protection: Forex Prime Session, Directional Bias (51); capital protection: Directional Bias (1 |
| ETHUSD | capital protection: Directional Bias (56); Cooldown active: 2 bars remaining. (22); Cooldown active: 1 bars remaining. (22) |
| GBPUSD | capital protection: Forex Prime Session (266); capital protection: Forex Prime Session, Directional Bias (34); Cooldown active: 2 bars remaining. (22) |
| BTCUSD | capital protection: Directional Bias (29); Cooldown active: 1 bars remaining. (15); Cooldown active: 2 bars remaining. (14) |
| AUDUSD | calibrated profile has no validated edge (OOS expectancy -0.375R over 127 trades) - refusing symbol (1403); capital protection: Forex Prime Session (5 |
| EURUSD | capital protection: Forex Prime Session (1334); calibrated profile has no validated edge (OOS expectancy -0.215R over 146 trades) - refusing symbol (1 |
| NZDUSD | calibrated profile has no validated edge (OOS expectancy -0.248R over 34 trades) - refusing symbol (2366); capital protection: Directional Bias (431); |
| USDCHF | capital protection: Forex Prime Session (953); calibrated profile has no validated edge (OOS expectancy -0.147R over 129 trades) - refusing symbol (80 |
| USDJPY | calibrated profile has no validated edge (OOS expectancy -0.059R over 124 trades) - refusing symbol (1551); capital protection: Forex Prime Session (8 |

## 7. Method and honesty notes

**Calibration is walk-forward.** Each symbol's geometry and entry threshold were chosen only on training folds and reported on purged out-of-sample folds (`PurgedKFold`, with the embargo excluded from both train and test). The deployed configuration is the one the folds agree on most often, not the best in-sample point.

**Win rate is a constrained objective, not a bare target.** The calibrator maximises expectancy subject to `win_rate >= target`, `trades >= min_trades` and `expectancy > 0`. A high win rate is trivially obtainable by shrinking the target relative to the stop, so a profile that reached 75% with negative expectancy would be rejected.

**The regime policy is fitted out-of-sample.** Which regimes are switched off is learned from trades the fold-selected configuration would have taken *inside its training windows*, never from the out-of-sample bars it then filters. Fitting the policy on the same sample it filters is a filter tuned to the test set: measured on this data it moved the aggregate out-of-sample result from roughly break-even to about +52R, which is the size of the artefact. Section 2a publishes both figures so the contribution can be judged rather than assumed.

**Intrabar ordering is conservative.** A bar whose range spans both the stop and the target is booked as a loss, because OHLC data does not reveal which came first. The previous engine resolved this optimistically, which inflated win rate exactly where the target lives.

**The backtest is hermetic.** All persistent-state reads and writes on the decision path are disabled during simulation (`jarvis.config.runtime`), so results are reproducible and cannot be influenced by live trade history.

### Known limitations

* Three months of H1 data bounds the achievable sample: with one-position-at-a-time and a time stop, a symbol yields roughly `bars / max_bars` trades. Per-symbol win rates on 20-40 trades carry wide confidence intervals.
* Costs are modelled as the realised spread from the data plus the symbol profile's commission (zero on XM Ultra Low). Swap/financing is not modelled.
* Regime labels and the candidate set come from the same pipeline under test; a regime that the pipeline cannot detect will not appear here.
