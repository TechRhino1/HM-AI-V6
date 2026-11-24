# HM Algo — Backtest on Real MT5 Data (730d cache, scored from 2026-05-19)

**Mode:** calibrated per-symbol win-rate profiles  
**Data:** MT5 terminal, real H1 bars (validated non-synthetic)  
**Initial balance:** $10,000.00 at 0.5% risk per trade  
**Generated:** 2026-11-24T17:23:45.381837+00:00

## 1. Headline

| Metric | Value |
|---|---|
| Symbols traded | 16 |
| Total trades | 2851 |
| Win rate | 47.88% |
| Expectancy | -0.0760 R per trade |
| Average win / loss | +0.852 R / -0.929 R |
| Payoff ratio | 0.918 |
| Total R | -216.56 R |
| Profit factor | 0.81 |
| Net profit | $-4,896.51 |
| Max drawdown | 50.83% |
| Sharpe / Sortino / Calmar | -1.22 / -2.77 / -0.96 |
| Expectancy (sample-uniqueness weighted) | -0.0502 R |

**Win-rate target outcome:** 0/16 symbols met the target out-of-sample. 1 met it in-sample but failed out-of-sample (i.e. the target was reachable only by overfitting).

## 2. Per-symbol results

| Symbol | Trades | WR % | Exp (R) | PF | Net $ | MaxDD % | OOS WR % | OOS Exp (R) | Target | Binding constraint |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|---|
| XAUUSD | 758 | 50.3 | -0.024 | 0.93 | -413.87 | 6.10 | 57.7 | +0.041 | ✗ | win rate - best achievable in-sample with positive expectancy is 64.2% |
| USDCAD | 363 | 67.8 | -0.071 | 0.64 | -631.21 | 6.59 | 74.4 | -0.000 | in-sample | out-of-sample - met in-sample (75.9%) but not on purged folds; OOS exp |
| XAGUSD | 306 | 45.4 | -0.023 | 0.94 | -404.02 | 8.66 | 49.1 | +0.091 | ✗ | win rate - best achievable in-sample with positive expectancy is 62.9% |
| USDCHF | 233 | 55.4 | -0.156 | 0.54 | -716.80 | 7.62 | 65.1 | +0.055 | ✗ | win rate - best achievable in-sample with positive expectancy is 64.8% |
| GBPUSD | 190 | 44.7 | -0.011 | 0.89 | -168.88 | 3.07 | 50.0 | +0.001 | ✗ | win rate - best achievable in-sample with positive expectancy is 67.5% |
| US30 | 190 | 41.6 | -0.050 | 0.91 | -152.42 | 3.27 | 46.2 | +0.088 | ✗ | win rate - best achievable in-sample with positive expectancy is 68.3% |
| EURUSD | 179 | 29.1 | -0.305 | 0.50 | -818.36 | 9.26 | 34.2 | +0.045 | ✗ | win rate - best achievable in-sample with positive expectancy is 62.5% |
| UK100 | 142 | 27.5 | -0.307 | 0.46 | -776.89 | 8.14 | 36.7 | +0.089 | ✗ | expectancy - the walk-forward-selected configuration has no edge out o |
| GER40 | 134 | 39.5 | +0.035 | 1.01 | +9.24 | 2.45 | 34.4 | +0.072 | ✗ | expectancy - the walk-forward-selected configuration has no edge out o |
| SOLUSD | 124 | 39.5 | -0.081 | 0.56 | -464.55 | 5.80 | 38.5 | +0.306 | ✗ | win rate - best achievable in-sample with positive expectancy is 58.7% |
| ETHUSD | 119 | 39.5 | -0.059 | 0.75 | -228.82 | 4.01 | 30.0 | +0.068 | ✗ | win rate - best achievable in-sample with positive expectancy is 59.3% |
| NZDUSD | 113 | 35.4 | -0.062 | 0.87 | -129.93 | 2.88 | 36.5 | +0.024 | ✗ | win rate - best achievable in-sample with positive expectancy is 66.4% |
| AUDUSD | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 55.7 | -0.140 | ✗ | expectancy - the walk-forward-selected configuration has no edge out o |
| BTCUSD | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 33.3 | -0.158 | ✗ | win rate - best achievable in-sample with positive expectancy is 64.1% |
| NAS100 | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 75.1 | -0.009 | ✗ | expectancy - the walk-forward-selected configuration has no edge out o |
| USDJPY | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 17.9 | -0.397 | ✗ | expectancy - the walk-forward-selected configuration has no edge out o |

### 2a. What the learned regime policy contributes

Calibration reports the same out-of-sample sample twice: once with every regime enabled, and once with the regimes the learned policy has switched off removed. Both are purged out-of-sample w.r.t. the geometry and threshold; the policy itself is fitted on **training folds only**, so it has never seen the out-of-sample bars it filters. The gap between the two columns is the policy's entire contribution — read it as the honest size of the effect, not as free money.

| Symbol | OOS n (all regimes) | OOS WR | OOS Exp (R) | OOS n (policy applied) | OOS WR | OOS Exp (R) | Policy fitted on |
|---|---:|---:|---:|---:|---:|---:|---|
| XAUUSD | 964 | 58.1 | +0.048 | 959 | 57.7 | +0.041 | train folds |
| USDCAD | 93 | 75.3 | +0.005 | 90 | 74.4 | -0.000 | train folds |
| XAGUSD | 803 | 47.6 | +0.051 | 761 | 49.1 | +0.091 | train folds |
| USDCHF | 67 | 65.7 | +0.059 | 63 | 65.1 | +0.055 | train folds |
| GBPUSD | 26 | 50.0 | +0.001 | 26 | 50.0 | +0.001 | train folds |
| US30 | 39 | 46.2 | +0.088 | 39 | 46.2 | +0.088 | train folds |
| EURUSD | 74 | 33.8 | +0.048 | 73 | 34.2 | +0.045 | train folds |
| UK100 | 62 | 35.5 | +0.072 | 60 | 36.7 | +0.089 | train folds |
| GER40 | 66 | 34.8 | +0.088 | 64 | 34.4 | +0.072 | train folds |
| SOLUSD | 26 | 38.5 | +0.306 | 26 | 38.5 | +0.306 | train folds |
| ETHUSD | 10 | 30.0 | +0.068 | 10 | 30.0 | +0.068 | train folds |
| NZDUSD | 55 | 25.4 | -0.240 | 52 | 36.5 | +0.024 | train folds |
| AUDUSD | 79 | 58.2 | -0.087 | 79 | 55.7 | -0.140 | train folds |
| BTCUSD | 33 | 33.3 | -0.158 | 33 | 33.3 | -0.158 | train folds |
| NAS100 | 238 | 75.2 | -0.008 | 237 | 75.1 | -0.009 | train folds |
| USDJPY | 28 | 17.9 | -0.397 | 28 | 17.9 | -0.397 | train folds |

## 3. Win-rate / expectancy frontier

For each target size (`tp_r`, as a multiple of initial risk) the table gives the highest win rate found at all, and the highest win rate that still carries positive expectancy. Where those two diverge, the gap is win rate that can only be bought by running a losing system. This is the direct evidence for whether the 75% target is reachable.

**AUDUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 72.2% | -0.029 | 533 | — | — | — |
| 0.5 | 69.4% | -0.028 | 470 | — | — | — |
| 0.6 | 67.4% | -0.014 | 414 | — | — | — |
| 0.75 | 65.1% | +0.001 | 255 | 65.1% | +0.001 | 255 |
| 1 | 64.6% | +0.023 | 288 | 64.6% | +0.023 | 288 |
| 1.5 | 55.4% | +0.006 | 177 | 55.4% | +0.015 | 177 |
| 2 | 46.7% | -0.110 | 135 | 45.5% | +0.015 | 110 |
| 2.5 | 46.2% | -0.055 | 143 | — | — | — |

**BTCUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 61.3% | +0.011 | 488 | 61.3% | +0.011 | 488 |
| 0.5 | 58.3% | +0.016 | 362 | 58.3% | +0.016 | 362 |
| 0.6 | 56.7% | +0.015 | 215 | 56.7% | +0.021 | 215 |
| 0.75 | 64.1% | +0.103 | 195 | 64.1% | +0.104 | 195 |
| 1 | 55.6% | +0.010 | 178 | 55.6% | +0.026 | 178 |
| 1.5 | 52.3% | +0.014 | 153 | 52.3% | +0.016 | 153 |
| 2 | 48.8% | +0.072 | 82 | 48.8% | +0.072 | 82 |
| 2.5 | 49.2% | +0.056 | 67 | 49.2% | +0.056 | 67 |

**ETHUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 59.1% | +0.019 | 472 | 59.1% | +0.019 | 472 |
| 0.5 | 58.6% | +0.049 | 275 | 58.6% | +0.049 | 275 |
| 0.6 | 57.0% | +0.067 | 214 | 57.0% | +0.070 | 214 |
| 0.75 | 57.0% | +0.020 | 223 | 57.0% | +0.032 | 223 |
| 1 | 59.3% | +0.083 | 172 | 59.3% | +0.083 | 172 |
| 1.5 | 51.5% | +0.168 | 99 | 51.5% | +0.168 | 99 |
| 2 | 53.5% | +0.146 | 86 | 53.5% | +0.146 | 86 |
| 2.5 | 57.4% | +0.340 | 54 | 57.4% | +0.340 | 54 |

**EURUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 72.6% | -0.019 | 576 | — | — | — |
| 0.5 | 68.7% | -0.017 | 457 | — | — | — |
| 0.6 | 67.0% | -0.011 | 370 | — | — | — |
| 0.75 | 64.1% | -0.021 | 320 | 58.0% | +0.003 | 376 |
| 1 | 62.5% | +0.007 | 304 | 62.5% | +0.007 | 304 |
| 1.5 | 55.4% | +0.015 | 168 | 55.4% | +0.015 | 168 |
| 2 | 52.8% | +0.088 | 144 | 52.8% | +0.088 | 144 |
| 2.5 | 50.5% | +0.046 | 105 | 50.5% | +0.046 | 105 |

**GBPUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 73.4% | -0.015 | 365 | — | — | — |
| 0.5 | 71.6% | -0.002 | 465 | 63.5% | +0.003 | 589 |
| 0.6 | 68.1% | -0.009 | 370 | 67.5% | +0.001 | 348 |
| 0.75 | 64.1% | -0.005 | 334 | 59.5% | +0.011 | 395 |
| 1 | 62.4% | -0.010 | 218 | — | — | — |
| 1.5 | 52.9% | +0.028 | 187 | 52.9% | +0.028 | 187 |
| 2 | 54.4% | +0.117 | 147 | 54.4% | +0.117 | 147 |
| 2.5 | 51.0% | +0.027 | 102 | 51.0% | +0.027 | 102 |

**GER40**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 75.1% | -0.014 | 714 | — | — | — |
| 0.5 | 71.3% | -0.017 | 571 | — | — | — |
| 0.6 | 68.4% | +0.009 | 304 | 68.4% | +0.011 | 304 |
| 0.75 | 67.7% | +0.025 | 384 | 67.7% | +0.025 | 384 |
| 1 | 68.0% | +0.071 | 347 | 68.0% | +0.071 | 347 |
| 1.5 | 57.3% | +0.038 | 220 | 57.3% | +0.038 | 220 |
| 2 | 53.1% | +0.094 | 179 | 53.1% | +0.094 | 179 |
| 2.5 | 56.5% | +0.127 | 145 | 56.5% | +0.127 | 145 |

**NAS100**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 75.9% | +0.007 | 590 | 75.9% | +0.007 | 590 |
| 0.5 | 73.7% | +0.023 | 463 | 73.7% | +0.023 | 463 |
| 0.6 | 71.0% | +0.018 | 487 | 71.0% | +0.026 | 487 |
| 0.75 | 68.4% | +0.034 | 408 | 68.4% | +0.034 | 408 |
| 1 | 66.6% | +0.015 | 350 | 66.6% | +0.026 | 350 |
| 1.5 | 56.6% | +0.045 | 182 | 56.6% | +0.045 | 182 |
| 2 | 59.4% | +0.148 | 170 | 59.4% | +0.155 | 170 |
| 2.5 | 57.2% | +0.095 | 138 | 57.2% | +0.095 | 138 |

**NZDUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 69.9% | -0.053 | 462 | — | — | — |
| 0.5 | 69.0% | -0.040 | 197 | — | — | — |
| 0.6 | 67.9% | -0.019 | 168 | — | — | — |
| 0.75 | 66.4% | +0.004 | 149 | 66.4% | +0.017 | 149 |
| 1 | 65.3% | +0.031 | 262 | 65.3% | +0.031 | 262 |
| 1.5 | 56.2% | +0.029 | 96 | 56.2% | +0.029 | 96 |
| 2 | 52.3% | +0.058 | 128 | 52.3% | +0.058 | 128 |
| 2.5 | 56.8% | +0.207 | 111 | 56.8% | +0.207 | 111 |

**SOLUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 57.6% | -0.009 | 465 | — | — | — |
| 0.5 | 58.9% | -0.005 | 348 | 56.1% | +0.009 | 328 |
| 0.6 | 58.4% | +0.022 | 274 | 58.4% | +0.026 | 274 |
| 0.75 | 56.4% | +0.043 | 195 | 56.4% | +0.043 | 195 |
| 1 | 58.7% | +0.053 | 172 | 58.7% | +0.053 | 172 |
| 1.5 | 51.5% | +0.013 | 103 | 51.5% | +0.034 | 103 |
| 2 | 53.5% | +0.165 | 43 | 53.5% | +0.165 | 43 |
| 2.5 | 49.1% | +0.077 | 53 | 49.1% | +0.119 | 53 |

**UK100**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 74.5% | -0.028 | 611 | — | — | — |
| 0.5 | 69.6% | -0.028 | 339 | — | — | — |
| 0.6 | 67.9% | -0.012 | 418 | — | — | — |
| 0.75 | 65.5% | -0.035 | 371 | — | — | — |
| 1 | 67.1% | +0.042 | 313 | 67.1% | +0.050 | 313 |
| 1.5 | 55.4% | +0.013 | 213 | 55.4% | +0.028 | 213 |
| 2 | 48.4% | +0.017 | 153 | 48.4% | +0.017 | 153 |
| 2.5 | 50.9% | +0.006 | 114 | 50.9% | +0.032 | 114 |

**US30**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 73.5% | -0.012 | 385 | — | — | — |
| 0.5 | 71.2% | -0.002 | 487 | 68.3% | +0.015 | 600 |
| 0.6 | 67.0% | -0.013 | 482 | 63.6% | +0.016 | 431 |
| 0.75 | 66.4% | +0.020 | 280 | 66.4% | +0.020 | 280 |
| 1 | 66.4% | +0.031 | 351 | 66.4% | +0.031 | 351 |
| 1.5 | 56.9% | -0.007 | 174 | 56.9% | +0.019 | 174 |
| 2 | 51.5% | +0.017 | 171 | 51.5% | +0.028 | 171 |
| 2.5 | 49.7% | -0.025 | 153 | 40.5% | +0.079 | 121 |

**USDCAD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 75.9% | +0.021 | 328 | 75.9% | +0.021 | 328 |
| 0.5 | 75.2% | +0.039 | 298 | 75.2% | +0.039 | 298 |
| 0.6 | 74.4% | +0.088 | 266 | 74.4% | +0.088 | 266 |
| 0.75 | 70.9% | +0.068 | 227 | 70.9% | +0.085 | 227 |
| 1 | 71.0% | +0.106 | 276 | 71.0% | +0.106 | 276 |
| 1.5 | 59.9% | +0.095 | 177 | 59.9% | +0.095 | 177 |
| 2 | 60.0% | +0.251 | 130 | 60.0% | +0.251 | 130 |
| 2.5 | 55.2% | +0.286 | 96 | 55.2% | +0.286 | 96 |

**USDCHF**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 71.9% | -0.031 | 469 | — | — | — |
| 0.5 | 68.8% | -0.023 | 471 | — | — | — |
| 0.6 | 66.3% | -0.008 | 407 | — | — | — |
| 0.75 | 64.8% | +0.003 | 304 | 64.8% | +0.003 | 304 |
| 1 | 62.8% | +0.001 | 269 | 62.8% | +0.001 | 269 |
| 1.5 | 56.4% | +0.031 | 179 | 56.4% | +0.031 | 179 |
| 2 | 49.6% | -0.027 | 125 | 49.2% | +0.035 | 132 |
| 2.5 | 47.1% | -0.009 | 121 | 45.5% | +0.053 | 154 |

**USDJPY**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 70.5% | -0.057 | 492 | — | — | — |
| 0.5 | 68.3% | -0.049 | 476 | — | — | — |
| 0.6 | 65.4% | -0.034 | 410 | — | — | — |
| 0.75 | 61.8% | -0.050 | 259 | — | — | — |
| 1 | 64.6% | +0.022 | 305 | 64.6% | +0.022 | 305 |
| 1.5 | 52.9% | -0.033 | 187 | 51.0% | +0.035 | 245 |
| 2 | 47.7% | -0.019 | 151 | 46.9% | +0.023 | 143 |
| 2.5 | 46.8% | -0.019 | 126 | 40.2% | +0.087 | 107 |

**XAGUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 69.5% | -0.071 | 1506 | — | — | — |
| 0.5 | 66.0% | -0.073 | 1412 | — | — | — |
| 0.6 | 65.1% | -0.036 | 2080 | — | — | — |
| 0.75 | 62.8% | -0.023 | 1949 | — | — | — |
| 1 | 62.9% | +0.002 | 1185 | 62.9% | +0.002 | 1185 |
| 1.5 | 55.1% | +0.011 | 977 | 55.1% | +0.011 | 977 |
| 2 | 49.9% | +0.021 | 1195 | 49.9% | +0.021 | 1195 |
| 2.5 | 49.8% | +0.050 | 775 | 49.8% | +0.050 | 775 |

**XAUUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 70.3% | -0.044 | 2593 | — | — | — |
| 0.5 | 67.3% | -0.028 | 3613 | — | — | — |
| 0.6 | 65.6% | -0.003 | 3437 | — | — | — |
| 0.75 | 64.2% | +0.020 | 3201 | 64.2% | +0.020 | 3201 |
| 1 | 63.0% | +0.017 | 2092 | 63.0% | +0.017 | 2092 |
| 1.5 | 56.1% | +0.043 | 2389 | 56.1% | +0.043 | 2389 |
| 2 | 49.2% | +0.012 | 2022 | 49.2% | +0.012 | 2022 |
| 2.5 | 48.8% | -0.001 | 1877 | 48.6% | +0.002 | 1452 |

## 4. Calibrated geometry per symbol

`tp_r` is the target distance in multiples of initial risk; `be` is the breakeven trigger (off = never lock breakeven); `pc` the partial bank; `mb` the time stop in bars; `thr` the entry score threshold.

The last two columns come from the isotonic score calibration: the realised win probability the fitted map assigns to a score sitting exactly at the deployed threshold, and the Brier score of that map (lower is better; 0.25 is the skill-free baseline for a balanced sample). The calibration is monotone, so it cannot change which candidates pass — it exists to make the score interpretable and to give the AI layer a probability rather than an arbitrary index.

| Symbol | tp_r | be | pc | mb | threshold | P(win) @ thr | Brier | Enabled regimes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| AUDUSD | 1 | off | 0.5 | 48 | 0.351 | 56.5% | 0.241 | TREND_BEAR, TREND_BULL, REVERSAL, BREAKOUT, RANGE |
| BTCUSD | 2.5 | 1 | off | 48 | 0.506 | 0.0% | 0.214 | TREND_BULL, TREND_BEAR, LIQUIDITY_SWEEP, REVERSAL, BREAKOUT, RANGE, CONSOLIDATION |
| ETHUSD | 2.5 | off | off | 48 | 0.540 | 30.0% | 0.210 | TREND_BULL, TREND_BEAR, REVERSAL, LIQUIDITY_SWEEP, RANGE, WEAK_TREND, CONSOLIDATION |
| EURUSD | 2.5 | off | off | 24 | 0.456 | 30.0% | 0.221 | TREND_BULL, TREND_BEAR, LIQUIDITY_SWEEP, BREAKOUT, RANGE |
| GBPUSD | 2 | off | off | 24 | 0.378 | 42.9% | 0.248 | TREND_BULL, TREND_BEAR, REVERSAL, WEAK_TREND, LIQUIDITY_SWEEP, CONSOLIDATION |
| GER40 | 2.5 | off | off | 48 | 0.444 | 28.0% | 0.224 | TREND_BEAR, TREND_BULL, LIQUIDITY_SWEEP, REVERSAL, CONSOLIDATION, WEAK_TREND |
| NAS100 | 0.4 | off | off | 48 | 0.410 | 71.9% | 0.186 | TREND_BULL, TREND_BEAR, LIQUIDITY_SWEEP, BREAKOUT, REVERSAL |
| NZDUSD | 2.5 | off | off | 48 | 0.375 | 19.1% | 0.187 | TREND_BEAR, REVERSAL, BREAKOUT, WEAK_TREND |
| SOLUSD | 2 | off | off | 48 | 0.481 | 0.0% | 0.207 | TREND_BULL, TREND_BEAR, RANGE, REVERSAL, CONSOLIDATION, LIQUIDITY_SWEEP, WEAK_TREND |
| UK100 | 2.5 | off | 0.5 | 48 | 0.300 | 0.0% | 0.216 | TREND_BEAR, TREND_BULL, BREAKOUT, REVERSAL, WEAK_TREND, LIQUIDITY_SWEEP |
| US30 | 2 | off | off | 24 | 0.377 | 40.0% | 0.246 | RANGE, BREAKOUT, TREND_BULL, REVERSAL, LIQUIDITY_SWEEP, TREND_BEAR, CONSOLIDATION, WEAK_TREND |
| USDCAD | 0.4 | off | off | 48 | 0.492 | 75.3% | 0.186 | TREND_BEAR, TREND_BULL, LIQUIDITY_SWEEP, BREAKOUT, RANGE |
| USDCHF | 0.75 | off | 0.5 | 48 | 0.420 | 65.7% | 0.225 | TREND_BEAR, TREND_BULL, LIQUIDITY_SWEEP, BREAKOUT |
| USDJPY | 2.5 | off | off | 48 | 0.364 | 0.0% | 0.141 | TREND_BEAR, TREND_BULL, LIQUIDITY_SWEEP, RANGE, REVERSAL, BREAKOUT, WEAK_TREND |
| XAGUSD | 2.5 | 1 | off | 24 | 0.437 | 42.3% | 0.248 | TREND_BULL, TREND_BEAR |
| XAUUSD | 1.5 | off | 0.5 | 24 | 0.340 | 56.5% | 0.243 | TREND_BEAR, TREND_BULL, WEAK_TREND, LIQUIDITY_SWEEP, RANGE, CONSOLIDATION |

## 5. Portfolio risk allocation (HRP)

Inverse-variance weights from the HRP allocator over per-symbol daily R:

| Symbol | Risk weight |
|---|---:|
| SOLUSD | 15.05% |
| ETHUSD | 11.42% |
| USDCAD | 10.90% |
| NZDUSD | 10.32% |
| USDCHF | 10.28% |
| GBPUSD | 8.62% |
| UK100 | 8.09% |
| US30 | 7.93% |
| EURUSD | 6.11% |
| GER40 | 5.99% |
| XAGUSD | 3.60% |
| XAUUSD | 1.67% |

## 6. Entry rejection analysis

Why candidates were not traded under the calibrated profile. In calibrated mode these are the capital-protection gates plus the calibrated edge filter; the legacy 29-check stack no longer decides.

Counts are per **bar evaluated**, not per candidate: a bar on which the pipeline found no setup at all (`no directional bias`) is counted here too, because the engine has to consider and decline it. A large `no directional bias` count therefore means the pipeline rarely formed a view, not that a good trade was vetoed.

| Symbol | Top rejection reasons |
|---|---|
| XAUUSD | capital protection: Directional Bias (174); Max 8 trades per day reached for symbol XAUUSD. (82); Cooldown active: 2 bars remaining. (69) |
| USDCAD | capital protection: Forex Prime Session (842); capital protection: Forex Prime Session, Directional Bias (161); capital protection: Directional Bias ( |
| XAGUSD | capital protection: Directional Bias (92); regime REVERSAL disabled by learned policy (expectancy -0.386R worse than -0.050R over 96 trades) (40); Coo |
| USDCHF | capital protection: Forex Prime Session (466); capital protection: Forex Prime Session, Strategy Viable (201); capital protection: Strategy Viable (17 |
| GBPUSD | capital protection: Forex Prime Session (392); capital protection: Forex Prime Session, Directional Bias (88); capital protection: Directional Bias (3 |
| US30 | capital protection: Forex Prime Session (293); capital protection: Forex Prime Session, Directional Bias, Strategy Viable (48); capital protection: Fo |
| EURUSD | capital protection: Forex Prime Session (432); capital protection: Forex Prime Session, Directional Bias (109); Cooldown active: 2 bars remaining. (58 |
| UK100 | capital protection: Forex Prime Session (300); capital protection: Forex Prime Session, Directional Bias (57); Cooldown active: 2 bars remaining. (40) |
| GER40 | capital protection: Forex Prime Session (290); capital protection: Forex Prime Session, Directional Bias (55); capital protection: Directional Bias (1 |
| SOLUSD | capital protection: Directional Bias (20); Cooldown active: 1 bars remaining. (18); Cooldown active: 2 bars remaining. (17) |
| ETHUSD | capital protection: Directional Bias (35); Cooldown active: 1 bars remaining. (24); Cooldown active: 2 bars remaining. (22) |
| NZDUSD | regime TREND_BULL disabled by learned policy (expectancy -0.068R worse than -0.050R over 277 trades) (420); capital protection: Directional Bias (81); |
| AUDUSD | calibrated profile has no validated edge (OOS expectancy -0.140R over 79 trades) - refusing symbol (1385); capital protection: Forex Prime Session (56 |
| BTCUSD | calibrated profile has no validated edge (OOS expectancy -0.158R over 33 trades) - refusing symbol (3704); capital protection: Directional Bias (694); |
| NAS100 | capital protection: Forex Prime Session (1540); calibrated profile has no validated edge (OOS expectancy -0.009R over 237 trades) - refusing symbol (1 |
| USDJPY | calibrated profile has no validated edge (OOS expectancy -0.397R over 28 trades) - refusing symbol (1534); capital protection: Forex Prime Session (88 |

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
