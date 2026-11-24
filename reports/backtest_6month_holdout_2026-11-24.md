# HM Algo — Backtest on Real MT5 Data (730d cache, scored from 2026-05-19)

**Mode:** calibrated per-symbol win-rate profiles  
**Data:** MT5 terminal, real H1 bars (validated non-synthetic)  
**Initial balance:** $10,000.00 at 0.5% risk per trade  
**Generated:** 2026-11-24T19:42:15.644726+00:00

## 1. Headline

| Metric | Value |
|---|---|
| Symbols traded | 16 |
| Total trades | 2794 |
| Win rate | 55.91% |
| Expectancy | -0.0734 R per trade |
| Average win / loss | +0.619 R / -0.952 R |
| Payoff ratio | 0.651 |
| Total R | -205.07 R |
| Profit factor | 0.79 |
| Net profit | $-4,832.45 |
| Max drawdown | 50.05% |
| Sharpe / Sortino / Calmar | -1.3 / -2.59 / -0.95 |
| Expectancy (sample-uniqueness weighted) | -0.0700 R |

**Win-rate target outcome:** 0/16 symbols met the target out-of-sample. 2 met it in-sample but failed out-of-sample (i.e. the target was reachable only by overfitting).

## 2. Per-symbol results

| Symbol | Trades | WR % | Exp (R) | PF | Net $ | MaxDD % | OOS WR % | OOS Exp (R) | Target | Binding constraint |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|---|
| GER40 | 421 | 67.9 | -0.058 | 0.68 | -642.83 | 6.81 | 71.4 | -0.041 | in-sample | out-of-sample - met in-sample (75.5%) but not on purged folds; OOS exp |
| NAS100 | 398 | 70.8 | -0.029 | 0.81 | -325.81 | 4.03 | 76.1 | -0.007 | in-sample | out-of-sample - met in-sample (76.1%) but not on purged folds; OOS exp |
| XAUUSD | 347 | 37.5 | -0.106 | 0.83 | -652.34 | 7.64 | 49.4 | +0.204 | ✗ | win rate - best achievable in-sample with positive expectancy is 69.3% |
| UK100 | 337 | 54.6 | -0.127 | 0.42 | -1,018.91 | 10.36 | 68.8 | -0.048 | ✗ | selection stability - 77.0% is reachable in-sample (tp0.4_beoff_pcoffx |
| XAGUSD | 313 | 44.4 | -0.060 | 0.87 | -886.64 | 12.39 | 48.6 | +0.047 | ✗ | win rate - best achievable in-sample with positive expectancy is 54.6% |
| USDCHF | 233 | 55.4 | -0.156 | 0.54 | -716.80 | 7.62 | 64.1 | -0.001 | ✗ | win rate - best achievable in-sample with positive expectancy is 69.6% |
| BTCUSD | 210 | 59.5 | -0.030 | 0.94 | -70.99 | 2.72 | 55.4 | +0.014 | ✗ | win rate - best achievable in-sample with positive expectancy is 63.6% |
| US30 | 190 | 41.6 | -0.050 | 0.91 | -152.42 | 3.27 | 42.9 | -0.018 | ✗ | win rate - best achievable in-sample with positive expectancy is 67.6% |
| USDCAD | 149 | 50.3 | +0.012 | 0.92 | -104.48 | 2.33 | 62.5 | +0.526 | ✗ | win rate - best achievable in-sample with positive expectancy is 74.6% |
| USDJPY | 99 | 37.4 | -0.138 | 0.86 | -109.75 | 2.04 | 36.6 | +0.031 | ✗ | expectancy - the walk-forward-selected configuration has no edge out o |
| ETHUSD | 97 | 39.2 | -0.069 | 0.79 | -151.48 | 4.12 | 39.1 | +0.376 | ✗ | win rate - best achievable in-sample with positive expectancy is 61.7% |
| AUDUSD | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 74.9 | -0.009 | ✗ | expectancy - the walk-forward-selected configuration has no edge out o |
| EURUSD | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 22.2 | -0.301 | ✗ | win rate - best achievable in-sample with positive expectancy is 61.5% |
| GBPUSD | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 40.5 | -0.134 | ✗ | win rate - best achievable in-sample with positive expectancy is 72.8% |
| NZDUSD | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 62.4 | -0.031 | ✗ | expectancy - the walk-forward-selected configuration has no edge out o |
| SOLUSD | 0 | 0.0 | +0.000 | 0.00 | +0.00 | 0.00 | 28.0 | -0.183 | ✗ | win rate - best achievable in-sample with positive expectancy is 58.8% |

### 2a. What the learned regime policy contributes

Calibration reports the same out-of-sample sample twice: once with every regime enabled, and once with the regimes the learned policy has switched off removed. Both are purged out-of-sample w.r.t. the geometry and threshold; the policy itself is fitted on **training folds only**, so it has never seen the out-of-sample bars it filters. The gap between the two columns is the policy's entire contribution — read it as the honest size of the effect, not as free money.

| Symbol | OOS n (all regimes) | OOS WR | OOS Exp (R) | OOS n (policy applied) | OOS WR | OOS Exp (R) | Policy fitted on |
|---|---:|---:|---:|---:|---:|---:|---|
| GER40 | 179 | 71.5 | -0.040 | 178 | 71.4 | -0.041 | train folds |
| NAS100 | 109 | 76.1 | -0.007 | 109 | 76.1 | -0.007 | train folds |
| XAUUSD | 190 | 45.3 | +0.111 | 158 | 49.4 | +0.204 | train folds |
| UK100 | 121 | 67.8 | -0.055 | 122 | 68.8 | -0.048 | train folds |
| XAGUSD | 226 | 48.2 | +0.012 | 220 | 48.6 | +0.047 | train folds |
| USDCHF | 173 | 63.6 | -0.009 | 167 | 64.1 | -0.001 | train folds |
| BTCUSD | 74 | 55.4 | +0.013 | 74 | 55.4 | +0.014 | train folds |
| US30 | 21 | 42.9 | -0.018 | 21 | 42.9 | -0.018 | train folds |
| USDCAD | 16 | 81.2 | +0.759 | 16 | 62.5 | +0.526 | train folds |
| USDJPY | 40 | 47.5 | +0.385 | 41 | 36.6 | +0.031 | train folds |
| ETHUSD | 22 | 59.1 | +0.610 | 23 | 39.1 | +0.376 | train folds |
| AUDUSD | 203 | 74.9 | -0.013 | 199 | 74.9 | -0.009 | train folds |
| EURUSD | 43 | 25.6 | -0.201 | 45 | 22.2 | -0.301 | train folds |
| GBPUSD | 37 | 40.5 | -0.134 | 37 | 40.5 | -0.134 | train folds |
| NZDUSD | 119 | 66.4 | +0.027 | 117 | 62.4 | -0.031 | train folds |
| SOLUSD | 25 | 28.0 | -0.183 | 25 | 28.0 | -0.183 | train folds |

## 3. Win-rate / expectancy frontier

For each target size (`tp_r`, as a multiple of initial risk) the table gives the highest win rate found at all, and the highest win rate that still carries positive expectancy. Where those two diverge, the gap is win rate that can only be bought by running a losing system. This is the direct evidence for whether the 75% target is reachable.

**AUDUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 72.4% | -0.034 | 395 | — | — | — |
| 0.5 | 69.9% | -0.033 | 349 | — | — | — |
| 0.6 | 66.2% | -0.033 | 302 | — | — | — |
| 0.75 | 62.3% | -0.041 | 249 | — | — | — |
| 1 | 64.1% | +0.008 | 212 | 64.1% | +0.008 | 212 |
| 1.5 | 50.0% | -0.050 | 132 | — | — | — |
| 2 | 44.2% | -0.151 | 104 | 43.5% | +0.009 | 85 |
| 2.5 | 45.2% | -0.129 | 104 | — | — | — |

**BTCUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 63.6% | +0.020 | 346 | 63.6% | +0.020 | 346 |
| 0.5 | 58.0% | +0.007 | 286 | 58.0% | +0.007 | 286 |
| 0.6 | 58.1% | +0.013 | 217 | 58.1% | +0.014 | 217 |
| 0.75 | 63.5% | +0.071 | 148 | 63.5% | +0.072 | 148 |
| 1 | 54.0% | -0.013 | 185 | 53.9% | +0.071 | 141 |
| 1.5 | 49.5% | -0.001 | 105 | 49.5% | +0.011 | 105 |
| 2 | 51.1% | -0.011 | 47 | 48.4% | +0.046 | 62 |
| 2.5 | 44.8% | -0.000 | 96 | 44.8% | +0.003 | 96 |

**ETHUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 60.5% | -0.018 | 223 | 59.2% | +0.021 | 164 |
| 0.5 | 61.7% | +0.064 | 133 | 61.7% | +0.064 | 133 |
| 0.6 | 59.0% | +0.093 | 100 | 59.0% | +0.099 | 100 |
| 0.75 | 58.2% | +0.040 | 122 | 58.2% | +0.051 | 122 |
| 1 | 57.4% | +0.058 | 108 | 57.4% | +0.065 | 108 |
| 1.5 | 54.8% | +0.137 | 73 | 54.8% | +0.137 | 73 |
| 2 | 55.6% | +0.236 | 36 | 55.6% | +0.236 | 36 |
| 2.5 | 58.5% | +0.202 | 41 | 58.5% | +0.202 | 41 |

**EURUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 72.1% | -0.042 | 362 | — | — | — |
| 0.5 | 67.8% | -0.046 | 314 | — | — | — |
| 0.6 | 67.3% | -0.012 | 278 | — | — | — |
| 0.75 | 63.7% | -0.033 | 234 | — | — | — |
| 1 | 62.1% | -0.035 | 198 | 61.5% | +0.003 | 221 |
| 1.5 | 56.7% | +0.066 | 120 | 56.7% | +0.066 | 120 |
| 2 | 54.7% | +0.091 | 106 | 54.7% | +0.091 | 106 |
| 2.5 | 56.3% | +0.124 | 87 | 56.3% | +0.124 | 87 |

**GBPUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 74.5% | -0.011 | 282 | 66.4% | +0.007 | 527 |
| 0.5 | 72.8% | +0.014 | 349 | 72.8% | +0.014 | 349 |
| 0.6 | 67.0% | -0.036 | 276 | 62.3% | +0.002 | 398 |
| 0.75 | 62.5% | -0.018 | 261 | 59.2% | +0.025 | 343 |
| 1 | 62.4% | -0.001 | 170 | 61.8% | +0.000 | 170 |
| 1.5 | 54.3% | +0.066 | 140 | 54.3% | +0.066 | 140 |
| 2 | 51.3% | +0.055 | 117 | 51.3% | +0.055 | 117 |
| 2.5 | 48.4% | +0.031 | 91 | 48.4% | +0.034 | 91 |

**GER40**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 75.5% | +0.007 | 388 | 75.5% | +0.007 | 388 |
| 0.5 | 72.4% | -0.003 | 435 | 68.2% | +0.005 | 427 |
| 0.6 | 71.9% | +0.044 | 331 | 71.9% | +0.044 | 331 |
| 0.75 | 69.5% | +0.053 | 311 | 69.5% | +0.053 | 311 |
| 1 | 66.7% | +0.058 | 258 | 66.7% | +0.058 | 258 |
| 1.5 | 58.9% | +0.102 | 168 | 58.9% | +0.102 | 168 |
| 2 | 51.5% | +0.091 | 132 | 51.5% | +0.091 | 132 |
| 2.5 | 56.8% | +0.158 | 111 | 56.8% | +0.158 | 111 |

**NAS100**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 76.4% | +0.002 | 518 | 76.4% | +0.002 | 518 |
| 0.5 | 73.3% | +0.025 | 438 | 73.3% | +0.025 | 438 |
| 0.6 | 71.3% | +0.025 | 369 | 71.3% | +0.034 | 369 |
| 0.75 | 69.0% | +0.034 | 306 | 69.0% | +0.039 | 306 |
| 1 | 66.5% | +0.028 | 230 | 66.5% | +0.029 | 230 |
| 1.5 | 56.4% | +0.061 | 156 | 56.4% | +0.061 | 156 |
| 2 | 58.6% | +0.155 | 128 | 58.6% | +0.155 | 128 |
| 2.5 | 54.5% | +0.003 | 110 | 54.5% | +0.011 | 110 |

**NZDUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 70.7% | -0.045 | 331 | — | — | — |
| 0.5 | 66.1% | -0.054 | 357 | — | — | — |
| 0.6 | 66.9% | -0.031 | 254 | — | — | — |
| 0.75 | 63.8% | -0.013 | 268 | — | — | — |
| 1 | 62.4% | -0.059 | 242 | — | — | — |
| 1.5 | 51.9% | -0.057 | 154 | — | — | — |
| 2 | 46.7% | -0.058 | 105 | 40.4% | +0.005 | 104 |
| 2.5 | 44.4% | -0.086 | 72 | — | — | — |

**SOLUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 57.4% | -0.015 | 338 | — | — | — |
| 0.5 | 57.0% | -0.012 | 258 | — | — | — |
| 0.6 | 58.7% | +0.026 | 189 | 58.7% | +0.030 | 189 |
| 0.75 | 55.0% | +0.028 | 149 | 55.0% | +0.028 | 149 |
| 1 | 58.8% | +0.050 | 136 | 58.8% | +0.051 | 136 |
| 1.5 | 56.6% | +0.094 | 53 | 56.6% | +0.105 | 53 |
| 2 | 51.3% | +0.200 | 37 | 51.3% | +0.200 | 37 |
| 2.5 | 48.7% | +0.022 | 39 | 48.7% | +0.079 | 39 |

**UK100**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 77.0% | +0.006 | 270 | 77.0% | +0.006 | 270 |
| 0.5 | 73.4% | +0.005 | 229 | 73.4% | +0.005 | 229 |
| 0.6 | 70.3% | +0.032 | 320 | 70.3% | +0.038 | 320 |
| 0.75 | 66.9% | +0.015 | 269 | 66.9% | +0.019 | 269 |
| 1 | 64.8% | +0.052 | 230 | 64.8% | +0.052 | 230 |
| 1.5 | 60.9% | +0.154 | 151 | 60.9% | +0.154 | 151 |
| 2 | 51.3% | +0.102 | 117 | 51.3% | +0.102 | 117 |
| 2.5 | 53.6% | +0.130 | 84 | 53.6% | +0.130 | 84 |

**US30**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 74.0% | -0.020 | 427 | — | — | — |
| 0.5 | 72.4% | -0.004 | 413 | 67.6% | +0.008 | 491 |
| 0.6 | 67.0% | -0.010 | 327 | 63.0% | +0.015 | 324 |
| 0.75 | 66.2% | +0.016 | 210 | 66.2% | +0.016 | 210 |
| 1 | 67.3% | +0.038 | 260 | 67.3% | +0.038 | 260 |
| 1.5 | 57.0% | -0.016 | 128 | 57.0% | +0.020 | 128 |
| 2 | 49.6% | +0.012 | 119 | 49.6% | +0.014 | 119 |
| 2.5 | 50.0% | -0.040 | 114 | 50.0% | +0.001 | 114 |

**USDCAD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 74.6% | +0.009 | 256 | 74.6% | +0.009 | 256 |
| 0.5 | 74.0% | +0.027 | 223 | 74.0% | +0.027 | 223 |
| 0.6 | 72.6% | +0.079 | 201 | 72.6% | +0.079 | 201 |
| 0.75 | 69.0% | +0.045 | 171 | 69.0% | +0.062 | 171 |
| 1 | 68.7% | +0.060 | 211 | 68.7% | +0.060 | 211 |
| 1.5 | 56.6% | +0.057 | 129 | 56.6% | +0.057 | 129 |
| 2 | 58.3% | +0.236 | 96 | 58.3% | +0.236 | 96 |
| 2.5 | 51.8% | +0.262 | 54 | 51.8% | +0.262 | 54 |

**USDCHF**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 71.2% | -0.026 | 351 | — | — | — |
| 0.5 | 69.6% | +0.016 | 253 | 69.6% | +0.016 | 253 |
| 0.6 | 65.7% | +0.001 | 309 | 65.7% | +0.001 | 309 |
| 0.75 | 65.0% | +0.018 | 234 | 65.0% | +0.018 | 234 |
| 1 | 64.3% | +0.030 | 210 | 64.3% | +0.030 | 210 |
| 1.5 | 55.0% | +0.050 | 131 | 55.0% | +0.050 | 131 |
| 2 | 53.3% | +0.084 | 92 | 53.3% | +0.084 | 92 |
| 2.5 | 49.4% | -0.003 | 83 | 49.4% | +0.011 | 83 |

**USDJPY**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 74.2% | -0.022 | 356 | — | — | — |
| 0.5 | 70.8% | +0.003 | 342 | 70.8% | +0.003 | 342 |
| 0.6 | 66.3% | -0.003 | 264 | 66.3% | +0.006 | 264 |
| 0.75 | 65.6% | +0.001 | 244 | 65.6% | +0.011 | 244 |
| 1 | 65.0% | +0.017 | 203 | 65.0% | +0.023 | 203 |
| 1.5 | 55.7% | -0.000 | 140 | 54.3% | +0.010 | 140 |
| 2 | 45.3% | +0.027 | 64 | 45.3% | +0.027 | 64 |
| 2.5 | 45.6% | +0.051 | 57 | 45.6% | +0.051 | 57 |

**XAGUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 68.6% | -0.085 | 886 | — | — | — |
| 0.5 | 66.1% | -0.074 | 840 | — | — | — |
| 0.6 | 63.9% | -0.052 | 800 | — | — | — |
| 0.75 | 62.4% | -0.030 | 753 | — | — | — |
| 1 | 62.1% | -0.009 | 909 | — | — | — |
| 1.5 | 54.6% | +0.017 | 590 | 54.6% | +0.017 | 590 |
| 2 | 48.0% | -0.001 | 935 | 47.7% | +0.015 | 524 |
| 2.5 | 48.1% | +0.007 | 605 | 48.1% | +0.007 | 605 |

**XAUUSD**

| tp_r | best WR | exp at best WR | trades | best WR with exp > 0 | exp | trades |
|---:|---:|---:|---:|---:|---:|---:|
| 0.4 | 72.8% | -0.015 | 1332 | — | — | — |
| 0.5 | 69.3% | +0.002 | 1262 | 69.3% | +0.002 | 1262 |
| 0.6 | 66.9% | +0.023 | 1204 | 66.9% | +0.023 | 1204 |
| 0.75 | 65.5% | +0.040 | 1125 | 65.5% | +0.040 | 1125 |
| 1 | 65.1% | +0.052 | 396 | 65.1% | +0.052 | 396 |
| 1.5 | 59.5% | +0.046 | 341 | 59.5% | +0.046 | 341 |
| 2 | 53.0% | +0.068 | 298 | 53.0% | +0.068 | 298 |
| 2.5 | 51.1% | +0.026 | 284 | 51.1% | +0.026 | 284 |

## 4. Calibrated geometry per symbol

`tp_r` is the target distance in multiples of initial risk; `be` is the breakeven trigger (off = never lock breakeven); `pc` the partial bank; `mb` the time stop in bars; `thr` the entry score threshold.

The last two columns come from the isotonic score calibration: the realised win probability the fitted map assigns to a score sitting exactly at the deployed threshold, and the Brier score of that map (lower is better; 0.25 is the skill-free baseline for a balanced sample). The calibration is monotone, so it cannot change which candidates pass — it exists to make the score interpretable and to give the AI layer a probability rather than an arbitrary index.

| Symbol | tp_r | be | pc | mb | threshold | P(win) @ thr | Brier | Enabled regimes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| AUDUSD | 0.4 | off | off | 48 | 0.351 | 60.0% | 0.185 | TREND_BULL, TREND_BEAR, REVERSAL, BREAKOUT |
| BTCUSD | 0.75 | off | 0.5 | 48 | 0.402 | 55.4% | 0.247 | TREND_BEAR, TREND_BULL, RANGE, REVERSAL, BREAKOUT, CONSOLIDATION |
| ETHUSD | 2.5 | off | off | 48 | 0.538 | 56.2% | 0.240 | TREND_BEAR, REVERSAL, RANGE, LIQUIDITY_SWEEP |
| EURUSD | 2.5 | off | off | 24 | 0.456 | 22.2% | 0.188 | TREND_BULL, TREND_BEAR, BREAKOUT, RANGE, WEAK_TREND |
| GBPUSD | 2 | 1 | off | 24 | 0.290 | 20.0% | 0.213 | TREND_BULL, LIQUIDITY_SWEEP, TREND_BEAR, RANGE, WEAK_TREND, REVERSAL, CONSOLIDATION |
| GER40 | 0.4 | off | off | 48 | 0.446 | 65.2% | 0.203 | TREND_BULL, TREND_BEAR, LIQUIDITY_SWEEP, REVERSAL, RANGE, CONSOLIDATION |
| NAS100 | 0.4 | off | off | 48 | 0.387 | 69.2% | 0.180 | TREND_BEAR, RANGE, TREND_BULL, REVERSAL, LIQUIDITY_SWEEP, BREAKOUT, WEAK_TREND, CONSOLIDATION |
| NZDUSD | 1 | off | 0.5 | 48 | 0.375 | 66.4% | 0.223 | TREND_BULL, TREND_BEAR, LIQUIDITY_SWEEP, BREAKOUT, WEAK_TREND |
| SOLUSD | 2 | off | off | 48 | 0.476 | 6.7% | 0.121 | TREND_BEAR, TREND_BULL, LIQUIDITY_SWEEP, REVERSAL, RANGE, BREAKOUT, WEAK_TREND, CONSOLIDATION |
| UK100 | 0.5 | off | off | 48 | 0.453 | 64.4% | 0.215 | TREND_BULL, TREND_BEAR, RANGE, WEAK_TREND, LIQUIDITY_SWEEP, CONSOLIDATION |
| US30 | 2 | off | off | 24 | 0.406 | 28.6% | 0.235 | TREND_BEAR, TREND_BULL, BREAKOUT, REVERSAL, LIQUIDITY_SWEEP, CONSOLIDATION, WEAK_TREND |
| USDCAD | 2.5 | 1 | off | 48 | 0.491 | 81.2% | 0.152 | TREND_BEAR, TREND_BULL, LIQUIDITY_SWEEP, BREAKOUT, RANGE |
| USDCHF | 0.75 | off | 0.5 | 48 | 0.420 | 63.6% | 0.232 | TREND_BEAR, TREND_BULL, LIQUIDITY_SWEEP, BREAKOUT |
| USDJPY | 2.5 | off | off | 48 | 0.290 | 47.5% | 0.249 | TREND_BULL, BREAKOUT, REVERSAL, WEAK_TREND, RANGE |
| XAGUSD | 2.5 | 1 | off | 24 | 0.436 | 41.4% | 0.249 | TREND_BULL, TREND_BEAR, RANGE, BREAKOUT, LIQUIDITY_SWEEP |
| XAUUSD | 2 | off | off | 24 | 0.530 | 40.4% | 0.245 | TREND_BULL, LIQUIDITY_SWEEP, RANGE, WEAK_TREND, CONSOLIDATION |

## 5. Portfolio risk allocation (HRP)

Inverse-variance weights from the HRP allocator over per-symbol daily R:

| Symbol | Risk weight |
|---|---:|
| ETHUSD | 16.99% |
| BTCUSD | 15.15% |
| GER40 | 10.42% |
| USDCHF | 10.23% |
| USDJPY | 9.91% |
| UK100 | 8.41% |
| NAS100 | 8.02% |
| US30 | 7.89% |
| USDCAD | 7.05% |
| XAGUSD | 3.34% |
| XAUUSD | 2.60% |

## 6. Entry rejection analysis

Why candidates were not traded under the calibrated profile. In calibrated mode these are the capital-protection gates plus the calibrated edge filter; the legacy 29-check stack no longer decides.

Counts are per **bar evaluated**, not per candidate: a bar on which the pipeline found no setup at all (`no directional bias`) is counted here too, because the engine has to consider and decline it. A large `no directional bias` count therefore means the pipeline rarely formed a view, not that a good trade was vetoed.

| Symbol | Top rejection reasons |
|---|---|
| GER40 | capital protection: Forex Prime Session (729); capital protection: Forex Prime Session, Directional Bias (128); capital protection: Directional Bias ( |
| NAS100 | capital protection: Forex Prime Session (1046); capital protection: Forex Prime Session, Directional Bias (101); capital protection: Forex Prime Sessi |
| XAUUSD | regime TREND_BEAR disabled by learned policy (expectancy -0.074R worse than -0.050R over 625 trades) (1018); capital protection: Directional Bias (201 |
| UK100 | capital protection: Forex Prime Session (521); capital protection: Forex Prime Session, Directional Bias (110); capital protection: Directional Bias ( |
| XAGUSD | capital protection: Directional Bias (67); Cooldown active: 2 bars remaining. (35); Cooldown active: 1 bars remaining. (35) |
| USDCHF | capital protection: Forex Prime Session (466); capital protection: Forex Prime Session, Strategy Viable (201); capital protection: Strategy Viable (17 |
| BTCUSD | capital protection: Directional Bias (33); Cooldown active: 1 bars remaining. (10); regime LIQUIDITY_SWEEP disabled by learned policy (expectancy -0.1 |
| US30 | capital protection: Forex Prime Session (293); capital protection: Forex Prime Session, Directional Bias, Strategy Viable (48); capital protection: Fo |
| USDCAD | capital protection: Forex Prime Session (291); capital protection: Forex Prime Session, Directional Bias (56); capital protection: Directional Bias (2 |
| USDJPY | capital protection: Forex Prime Session (273); regime TREND_BEAR disabled by learned policy (expectancy -0.089R worse than -0.050R over 233 trades) (2 |
| ETHUSD | regime TREND_BULL disabled by learned policy (expectancy -0.086R worse than -0.050R over 148 trades) (622); capital protection: Directional Bias (95); |
| AUDUSD | calibrated profile has no validated edge (OOS expectancy -0.009R over 199 trades) - refusing symbol (1385); capital protection: Forex Prime Session (5 |
| EURUSD | capital protection: Forex Prime Session (1326); calibrated profile has no validated edge (OOS expectancy -0.301R over 45 trades) - refusing symbol (11 |
| GBPUSD | capital protection: Forex Prime Session (1372); calibrated profile has no validated edge (OOS expectancy -0.134R over 37 trades) - refusing symbol (11 |
| NZDUSD | calibrated profile has no validated edge (OOS expectancy -0.031R over 117 trades) - refusing symbol (2333); capital protection: Directional Bias (447) |
| SOLUSD | calibrated profile has no validated edge (OOS expectancy -0.183R over 25 trades) - refusing symbol (3626); capital protection: Directional Bias (766); |

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
